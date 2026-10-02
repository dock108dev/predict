"""Offline native v3 envelope and ordinary runtime; no provider traffic."""
import asyncio
import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from aiohttp import web
from app.collection import native_payload as policy
from app.collection.continuous import Discovery
from app.collection.coverage import catalog
from app.collection.transport_session import reopen
from app.dashboard.session_history import load, project_rows
from tests.test_acquisition_r3 import Fixture as Prior, configuration as prior_configuration
from tests.test_r3_retained_repairs import rows as retained_rows
from tests.test_coverage import pe

OUT=Path(__file__).resolve().parents[1]/'evidence/native-redesign-20260930'
def configuration():
    s=prior_configuration();s['source_session']['native_discovery']=policy.POLICY
    s['prediction']['discovery_requests']=max(policy.REQUEST_CAPS.values())
    s['mapping_revision']='native-discovery-v3; summaries and bounded typed payloads'
    return s

class Fixture(Prior):
    async def boot(self,path):
        o=await super().boot(path)
        def factory():s=configuration();s['mode']='mock';return s
        o.spec_factory=factory;self.native_calls=[]
        return o
    async def start(self,duration=30,fast=True):
        cfg=configuration()['source_session']
        if fast:cfg['refresh_seconds']=1
        r=await self.client.post('/api/start',json=dict(duration=duration,source_settings=cfg),headers=self.origin)
        assert r.status==200,await r.text()
        save=self.owner.session.journal.save
        def observe(row):save(row);self.books+=row['type']=='prediction_book';self.changed.set()
        self.owner.session.journal.save=observe
    async def rest(self,req):
        if req.path.startswith('/v4/'):return await super().rest(req)
        self.native_calls.append((req.path,dict(req.query)))
        if req.path=='/trade-api/v2/events':
            assert req.query['with_nested_markets']=='false'
        if req.path=='/v1/events':
            offset=int(req.query['offset'])
            if self.fault=='oversized':return web.Response(body=b' '* (policy.BODY_LIMITS['discovery']+1))
            if self.fault=='compressed':return web.Response(body=b'compressed-refused',headers={'Content-Encoding':'gzip'})
            if self.fault=='deep':return web.Response(body=b'['*33+b']'*33)
            if offset==0:
                page=next(r for r in retained_rows() if r['type']=='prediction_discovery_http' and r['source']=='polymarket_us' and r['complete'])
                events=json.loads(base64.b64decode(page['body_b64']))['events']
                # Originals above are untouched. This extra fixture is explicitly
                # synthetic, a single large nested event with null schedule.
                large=deepcopy(events[0]);large['id']='SIMULATED-large';large['startTime']=None
                large['description']='SIMULATED large event envelope '+ 'x'*350000
                for m in large['markets']:m['id']='SIMULATED-'+str(m['id'])
                events += [large,dict(id='SIMULATED-null',startTime=None),dict(id='SIMULATED-missing')]
            elif offset<25:events=[dict(id='SIMULATED-small-'+str(offset+i),startTime=None) for i in range(5)]
            else:
                e=pe('p');e.update(gameId=1,startTime=self.schedule,markets=[self.us_market('p0')]);events=[e]
            return web.json_response(dict(events=events))
        return await super().rest(req)

class Parsing(unittest.TestCase):
    def test_structure_keys_and_nonfinite(self):
        for raw in (b'['*33+b']'*33,b'{"id":1,"id":2}',b'{"x":NaN}',b'['+b'0,'*100001+b'0]'):
            with self.assertRaises(ValueError):policy.parse(raw)
        self.assertEqual(policy.parse(b'{"x":"[[[\\\""}'),{'x':'[[["'})
    def test_original_sizes_and_associations(self):
        from app.collection.listing_evidence import retained_us_futures
        pages=[r for r in retained_rows() if r['type']=='prediction_discovery_http']
        self.assertEqual(len(retained_us_futures(pages)),21)
        self.assertEqual(sum(len(r['records']) for r in retained_rows() if r['type']=='aggregate_snapshot'),246)
        self.assertEqual(sum(not r['complete'] for r in pages),2)
        report=[dict(source=r['source'],path=r['path'],complete=r['complete'],bytes=len(base64.b64decode(r['body_b64']))) for r in pages]
        (OUT/'retained-sizes.json').write_text(json.dumps(report,indent=2))

class Runtime(unittest.IsolatedAsyncioTestCase):
    async def test_both_success_large_event_many_pages_books_and_reopening(self):
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
            f=Fixture();o=await f.boot(tmp)
            try:
                await f.start();await f.native_images();await f.images()
                await f.wait(lambda:o.session.aggregate.health=='completed')
                self.assertFalse(o.session.discovery.source_stops)
                self.assertEqual({k[0] for k in o.session.projection.books},{'kalshi','polymarket_us'})
                cat=o.session.discovery.inventory['polymarket_us']
                self.assertEqual(cat['selection']['ids'],['p0'])
                self.assertGreaterEqual(cat['counts']['markets']['discovered'],22)
                self.assertTrue(next(e for e in cat['excluded_catalog']['events'] if e[0]=='SIMULATED-large')[3])
                self.assertEqual(len(f.odds_calls),37)
                await f.stop_route()
                rs=reopen(o.session.journal.path)['rows'];saved=load(o.session.output)
                self.assertEqual(saved,project_rows(rs,saved['durable_cursor']))
                self.assertTrue(o.session.cleanup_complete)
                self.assertTrue(any(len(base64.b64decode(r['body_b64']))>262144 for r in rs if r['type']=='prediction_discovery_http' and r['complete']))
            finally:await f.close()
    async def test_local_rejection_keeps_other_native_and_aggregate_working(self):
        for fault in ('oversized','compressed','deep'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                f=Fixture(fault);o=await f.boot(tmp)
                try:
                    await f.start();await f.wait(lambda:len(f.active())==1);await f.images()
                    await f.wait(lambda:o.session.aggregate.health=='completed')
                    self.assertEqual(set(o.session.discovery.source_stops),{'polymarket_us'})
                    self.assertEqual(sum(p=='/v1/events' for p,q in f.native_calls),1)
                    self.assertTrue(any(k[0]=='kalshi' for k in o.session.projection.books))
                    self.assertFalse(o.session.stop_event.is_set())
                    await f.stop_route()
                finally:await f.close()
    async def test_page_bounds_duplicates_and_cursors(self):
        s=SimpleNamespace(spec=configuration(),producers={},emit=Mock())
        d=Discovery(s);calls=[]
        async def get(url,params):
            calls.append(params);offset=params['offset']
            return SimpleNamespace(status_code=200,json=lambda:dict(events=[dict(id=str(offset+i)) for i in range(5)]))
        d.clients['polymarket_us']=SimpleNamespace(get=get)
        result=await d.pages_for('polymarket_us','/v1/events',{},'events',5)
        self.assertEqual((len(result),len(calls)),(150,30))
        async def duplicate(url,params):return SimpleNamespace(status_code=200,json=lambda:dict(events=[dict(id='same')]*5))
        d.clients['polymarket_us'].get=duplicate
        with self.assertRaisesRegex(ValueError,'duplicate'):await d.pages_for('polymarket_us','/v1/events',{},'events',5)
        async def cursor(url,params):return SimpleNamespace(status_code=200,json=lambda:dict(events=[dict(event_ticker='a'+params['cursor'])],cursor='repeat'))
        d.clients['kalshi']=SimpleNamespace(get=cursor)
        with self.assertRaisesRegex(ValueError,'cursor'):await d.pages_for('kalshi','/trade-api/v2/events',{},'events',200)

class Envelopes(unittest.IsolatedAsyncioTestCase):
    async def test_exact_caps_and_one_byte_excess_no_decompression(self):
        from aiohttp.test_utils import TestServer
        from app.collection.continuous import REST
        from app.collection.prediction_producer import PredictionBudget
        from app.collection.odds_http import BudgetStop
        for path,kind in (('/v1/events','discovery'),('/v1/markets','metadata'),('/account/limits','account')):
            cap=policy.BODY_LIMITS[kind];raw=b'{"padding":"'+b'x'*(cap-14)+b'"}'
            self.assertEqual(len(raw),cap)
            async def serve(req):return web.Response(body=raw+(b' ' if req.query.get('excess') else b''))
            app=web.Application();app.router.add_get('/{path:.*}',serve)
            server=TestServer(app);await server.start_server();url=str(server.make_url('/')).rstrip('/')
            receipts=[];limits=configuration()['prediction'];budget=PredictionBudget(limits)
            client=REST(url,limits,receipts.append,5,budget);client.strict_eof=True
            client.session=SimpleNamespace(spec=configuration(),discovery=SimpleNamespace(stop_source=Mock()),request_stop=Mock())
            client.source_venue='polymarket_us'
            try:
                r=await client.get(url+path);self.assertEqual(len(r.content),cap)
                with self.assertRaises(BudgetStop):await client.get(url+path,{'excess':'1'})
                self.assertTrue(receipts[0]['complete']);self.assertFalse(receipts[1]['complete'])
                self.assertEqual(len(base64.b64decode(receipts[1]['body_b64'])),cap)
                self.assertEqual(budget.bytes,2*cap+1)
                self.assertFalse(client.session.request_stop.called)
            finally:await client.aclose();await server.close()

class Admission(unittest.TestCase):
    def test_malformed_nested_sides_and_conflicting_query(self):
        from tests.test_coverage import page,pm,AS_OF,ke,km
        e=pe();e['markets']=[dict(pm(),marketSides=None),dict(pm('bad'),marketSides=[None])]
        p=page('polymarket_us',dict(events=[e]));p['acquisition_discovery_policy']=policy.POLICY
        c=catalog([p],'polymarket_us',AS_OF)
        self.assertTrue(all(m['exclusion'] for m in c['markets']))
        e,milestone=ke('k');m=km('m','wrong')
        p=page('kalshi',dict(events=[e],milestones=[milestone],cursor=''))
        q=page('kalshi',dict(markets=[m],cursor=''),field='markets',eid='k',limit=50)
        c=catalog([p,q],'kalshi',AS_OF)
        self.assertEqual(c['markets'][0]['exclusion'],'conflicting_query_identity')
    def test_distinct_market_tickers_same_event_and_missing_series(self):
        from tests.test_coverage import page,ke,km,AS_OF
        e,milestone=ke('k')
        p=page('kalshi',dict(events=[e],milestones=[milestone],cursor=''))
        q=page('kalshi',dict(markets=[km('a','k'),km('b','k')],cursor=''),field='markets',eid='k',limit=50)
        p['acquisition_discovery_policy']=q['acquisition_discovery_policy']=policy.POLICY
        c=catalog([p,q],'kalshi',AS_OF)
        self.assertEqual(len(c['markets']),2)
        self.assertFalse(any(m['exclusion'] for m in c['markets']))
        e.pop('series_ticker',None)
        p=page('kalshi',dict(events=[e],milestones=[milestone],cursor=''));p['acquisition_discovery_policy']=policy.POLICY
        c=catalog([p],'kalshi',AS_OF)
        self.assertEqual(c['excluded_catalog']['events'][0][3],'event_parse_error')

class BookParsing(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_book_structure_stops_source_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture();o=await f.boot(tmp)
            try:
                await f.start();await f.native_images()
                c=next(c for c in f.active() if c['venue']=='polymarket_us')
                await c['socket'].send_str('['*33+']'*33)
                await f.wait(lambda:'polymarket_us' in o.session.discovery.source_stops)
                await f.wait(lambda:o.session.aggregate.health=='completed')
                self.assertFalse(o.session.stop_event.is_set())
                self.assertEqual(set(o.session.discovery.source_stops),{'polymarket_us'})
                await f.stop_route()
                self.assertTrue(any(r['type']=='native_frame_rejected' for r in reopen(o.session.journal.path)['rows']))
            finally:await f.close()

class ExpandedStorage(unittest.TestCase):
    def test_compressed_journal_cannot_exceed_saved_expansion_limit(self):
        from app.collection.transport_session import ObservationJournal
        from app.collection.journal_encoding import VERSION,MAX_EXPANDED
        from app.collection.odds_http import BudgetStop
        with tempfile.TemporaryDirectory() as tmp:
            j=ObservationJournal(Path(tmp)/'fixture.jsonl',encoding=VERSION)
            try:
                # Highly compressible records: disk bytes cannot stand in for
                # the size needed by exact saved reopening.
                row=dict(type='test',padding='x'*(1024*1024))
                for _ in range(31):j.save(row)
                before=j.bytes
                self.assertLess(before,100000)
                with self.assertRaisesRegex(BudgetStop,'expanded'):j.save(row)
                self.assertEqual(j.bytes,before)
                self.assertLess(j.expanded_bytes,MAX_EXPANDED)
                j.save(dict(type='session_finished'))
            finally:j.close()

class ExpandedRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_expanded_budget_is_global_and_preserves_inspectable_saved_prefix(self):
        from app.collection.odds_http import BudgetStop
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture();o=await f.boot(tmp)
            try:
                await f.start();await f.native_images()
                # Controlled resource counter fault at the global reserve edge.
                o.session.journal.expanded_bytes=32*1024*1024-65536-100
                with self.assertRaisesRegex(BudgetStop,'expanded_journal_reserved_stop'):
                    o.session.emit('session',dict(type='test_resource_boundary'))
                self.assertTrue(o.session.stop_event.is_set())
                await f.stop_route()
                saved=load(o.session.output);rs=reopen(o.session.journal.path)['rows']
                projected=project_rows(rs,saved['durable_cursor'])
                self.assertIn(saved,[projected,dict(projected,state='incomplete')])
                self.assertTrue(o.session.cleanup_complete)
                self.assertEqual(o.session.reason,'expanded_journal_reserved_stop')
            finally:await f.close()
