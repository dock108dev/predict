"""Isolated ordinary dashboard, native-shaped synthetic data, explicit Start."""
import asyncio
from pathlib import Path
import sys
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.continuous import ContinuousSession
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from tests.segmented_collector_fixture import Fixture
from tests.test_native_integration import configuration
from tests.test_native_continuation import BODY
import httpx

async def main():
    root=Path(sys.argv[1]);f=Fixture()
    feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
    f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
    f.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
    class Session(ContinuousSession):
        graphql_fixture_transport=httpx.MockTransport(lambda r:httpx.Response(200,json=BODY))
        async def start(self):
            await super().start();save=self.journal.save
            def observed(row):save(row);f.books+=row['type']=='prediction_book';f.changed.set()
            self.journal.save=observed
    def graphql_spec():
        value=configuration();value['native_sources']['novig']=dict(state='enabled',transport='graphql',environment='public',selected=True)
        return value
    owner=CoverageOwner(root/'legacy',pilot_output=root/'sessions',endpoints=f.endpoints,product_mode=True,spec_factory=graphql_spec,mock_segmented=True,session_factory=Session);f.owner=owner
    runner=web.AppRunner(create_app(owner=owner,sessions={}));await runner.setup();await web.TCPSite(runner,'127.0.0.1',8795).start()
    print('http://127.0.0.1:8795 · idle synthetic GraphQL display preview',flush=True)
    try:
        while True:
            await asyncio.sleep(1)
            for c in list(f.active()):await f.send(c)
    finally:await runner.cleanup();await f.close()

if __name__=='__main__':asyncio.run(main())
