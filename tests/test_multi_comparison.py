import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from app.collection.comparison_policy import multi_specification
from app.collection.two_source import QualificationOwner,QualificationSession
from app.collection.two_source_policy import validate
from app.collection.two_source_scope import violation
from app.dashboard.multi_game_server import create_app
from app.dashboard.price_comparison import comparisons
from app.dashboard import session_history
from tests.comparison_feed_preview import FeedFixture
from tests.test_two_source_qualification import spec

class MultiComparison(unittest.IsolatedAsyncioTestCase):
    async def test_four_event_frozen_scope_updates_details_and_exact_reopen(self):
        old=spec();s=multi_specification(old['start_after'],old['start_before'],old['two_source_qualification']['attempt_id'],'mock');validate(s)
        bad=deepcopy(s);bad['two_source_qualification']['events_selected']=5
        with self.assertRaises(ValueError):validate(bad)
        with tempfile.TemporaryDirectory() as t:
            f=FeedFixture();feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
            f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
            endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
            o=QualificationOwner(Path(t)/'legacy',pilot_output=Path(t)/'run',product_mode=True,endpoints=endpoints,spec_factory=lambda:s,session_factory=QualificationSession);f.owner=o
            client=TestClient(TestServer(create_app(owner=o,sessions={})));await client.start_server()
            try:
                await o.start(duration=180);await f.wait(lambda:len(f.active())==2)
                session=o.session;save=session.journal.save
                def observed(r):save(r);f.books+=r['type']=='prediction_book';f.changed.set()
                session.journal.save=observed
                await f.images()
                d=await (await client.get('/api/dashboard?view=feed')).json()
                self.assertEqual(len(d['comparisons']),8)
                self.assertEqual(len(session.selected_event['events']),4)
                for c in f.active():
                    mid=c['command']['params']['market_tickers'][0] if c['venue']=='kalshi' else c['command']['subscribe']['marketSlugs'][0]
                    await f.send(c,mid)
                r=d['comparisons'][0]
                query=dict(session=r['session'],hash=r['hash'],cutoff=r['cutoff'],quantity='100',scenario='unknown')
                details=await (await client.get('/api/calculate',params=query)).json()
                self.assertEqual(len(details['comparisons']),2)
                self.assertTrue(all(x['net'] is None for x in details['comparisons']))
                frozen=session.projection.snapshot(mode='saved');expected=comparisons(frozen,{})
                await o.stop();await o.finalizer;self.assertIsNone(o.error)
                self.assertEqual(expected,comparisons(session_history.load(session.output,frozen['durable_cursor']),{}))
                from app.collection.two_source_audit import verify
                self.assertEqual(verify(session.output)['scope']['state'],'PASS')
                selection=session.selected_event
                mid=selection['markets']['kalshi'][0]
                record=dict(type='market_selected',market=dict(raw=dict(ref=dict(market_id=mid,event_id='wrong'))))
                self.assertEqual(violation('kalshi',record,selection),'book_or_market_outside_frozen_selection')
                self.assertFalse(o.status()['start_available'])
            finally:await client.close();await f.close()

if __name__=='__main__':unittest.main()


class SnapshotCacheTests(unittest.TestCase):
    def test_reuse_copy_invalidation_and_bound(self):
        from app.dashboard.saved_snapshot_cache import SavedSnapshotCache
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);file=folder/'record';file.write_text('a');calls=[]
            def loader(p):calls.append(p);return {'value':file.read_text()}
            cache=SavedSnapshotCache(100)
            first=cache.load(folder,loader);first['value']='mutated'
            self.assertEqual(cache.load(folder,loader),{'value':'a'});self.assertEqual(len(calls),1)
            file.write_text('b');self.assertEqual(cache.load(folder,loader),{'value':'b'});self.assertEqual(len(calls),2)
            file.write_text('x'*101);cache.load(folder,loader);self.assertEqual(cache.size,0)
