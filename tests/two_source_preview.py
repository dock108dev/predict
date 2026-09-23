"""Disposable synthetic browser preview of the exact two-source policy, idle first."""
import asyncio
from pathlib import Path
import sys
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.two_source import QualificationOwner,QualificationSession
from app.dashboard.multi_game_server import create_app
from tests.integrated_workload import NativeFixture
from tests.test_two_source_qualification import spec

async def main():
    class BrowserFixture(NativeFixture):
        async def rest(self,request):
            if '--futures-only' in sys.argv and request.path=='/v1/events':
                from tests.segmented_collector_fixture import pe
                self.rest_calls.append((request.path,dict(request.query)))
                e=pe('future');e.update(gameId=0,startTime=self.schedule,title='Synthetic division winner',markets=[])
                return web.json_response(dict(events=[e]))
            return await super().rest(request)
    root=Path(sys.argv[1]);f=BrowserFixture(kalshi_markets=3);s=spec()
    feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
    f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
    f.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
    class Session(QualificationSession):
        async def start(self):
            result=await super().start();save=self.journal.save
            def observed(row):save(row);f.books+=row['type']=='prediction_book';f.changed.set()
            self.journal.save=observed;return result
    o=QualificationOwner(root/'legacy',pilot_output=root/'sessions',product_mode=True,endpoints=f.endpoints,spec_factory=lambda:s,session_factory=Session);f.owner=o
    runner=web.AppRunner(create_app(owner=o,sessions={}));await runner.setup();await web.TCPSite(runner,'127.0.0.1',8821).start()
    async def pump():
        while True:
            if o.session and o.session.state=='running':
                for c in list(f.active()):
                    ids=c['command']['params']['market_tickers'] if c['venue']=='kalshi' else c['command']['subscribe']['marketSlugs']
                    for mid in ids:
                        if not o.session.stop_event.is_set():await f.send(c,mid)
            await asyncio.sleep(1)
    task=asyncio.create_task(pump())
    print('Synthetic, idle: http://127.0.0.1:8821',flush=True)
    try:await asyncio.Event().wait()
    finally:task.cancel();await asyncio.gather(task,return_exceptions=True);await runner.cleanup();await f.close()

if __name__=='__main__':
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('Forbidden in fixture preview')),patch('app.collection.native_product.load_native_secret',side_effect=AssertionError('Forbidden in fixture preview')):
        asyncio.run(main())
