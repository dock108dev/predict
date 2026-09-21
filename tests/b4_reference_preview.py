"""Isolated ordinary product browser fixture; no external transport or credential access."""
import asyncio
import json
from pathlib import Path
import sys
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.continuous import ContinuousSession
from app.dashboard.coverage_owner import CoverageOwner,spec
from app.dashboard.multi_game_server import create_app
from app.reference.product import emit_references
from tests.segmented_collector_fixture import Fixture
from tests.test_b4_reference import references

async def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
    class TermsFixture(Fixture):
        async def rest(self,req):
            response=await super().rest(req);data=json.loads(response.text)
            if req.path=='/trade-api/v2/markets':
                for m in data['markets']:m.update(rules_primary='SYNTHETIC normal winner; begins within 48 hours; tie $0.50',rules_secondary='Synthetic test terms only')
            if req.path in ('/v1/markets','/v1/events'):
                markets=data.get('markets',[])+[m for e in data.get('events',[]) for m in e.get('markets',[])]
                for m in markets:m.update(description='SYNTHETIC normal winner; rescheduled to a date within two days; tie $0.50',feeCoefficient='0.06')
            return web.json_response(data)
    f=TermsFixture()
    feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
    f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
    f.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
    class Session(ContinuousSession):
        async def start(self):
            await super().start();save=self.journal.save
            def observed(row):save(row);f.books+=row['type']=='prediction_book';f.changed.set()
            self.journal.save=observed
    def configuration():
        value=spec();value.update(mode='mock',reference_enabled=False);return value
    owner=CoverageOwner(root/'legacy',pilot_output=root/'sessions',endpoints=f.endpoints,product_mode=True,spec_factory=configuration,mock_segmented=True,session_factory=Session);f.owner=owner
    runner=web.AppRunner(create_app(owner=owner,sessions={}));await runner.setup();await web.TCPSite(runner,'127.0.0.1',8796).start()
    print('http://127.0.0.1:8796 · synthetic B4 ordinary product preview; explicit Start',flush=True)
    published=set()
    try:
        while True:
            await asyncio.sleep(1)
            for c in list(f.active()):await f.send(c)
            if owner.active() and owner.session.sid not in published:
                s=owner.session;snap=s.projection.snapshot()
                if snap['games']:
                    refs=references(snap['games'][0],s.projection.last)
                    (root/'synthetic-reference-import.json').write_text(json.dumps(refs,indent=2))
                    emit_references(s,refs);await s.queue.join();published.add(s.sid)
    finally:await runner.cleanup();await f.close()

if __name__=='__main__':asyncio.run(main())
