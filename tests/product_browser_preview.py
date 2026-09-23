"""Disposable browser preview: numeric loopback native fixtures only, idle startup."""
import asyncio
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sys
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.dashboard.coverage_owner import CoverageOwner,spec
from app.dashboard.multi_game_server import create_app
from app.collection.continuous import ContinuousSession
from tests.segmented_collector_fixture import Fixture

async def main():
    output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
    f=Fixture()
    feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
    f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
    f.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
    class Session(ContinuousSession):
        async def start(self):
            await super().start();original=self.journal.save
            def save(row):
                original(row);f.books+=row['type']=='prediction_book';f.changed.set()
            self.journal.save=save
    def configuration():
        value=spec();value.update(mode='mock',reference_enabled=False);return value
    owner=CoverageOwner(output/'legacy',pilot_output=output/'sessions',endpoints=f.endpoints,product_mode=True,session_factory=Session,spec_factory=configuration)
    f.owner=owner
    app=create_app(owner=owner,sessions={});runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',8794);await site.start()
    print('Product preview http://127.0.0.1:8794 · idle · synthetic only',flush=True)
    refs=set()
    try:
        while True:
            await asyncio.sleep(1)
            s=owner.session
            if not s or s.stop_event.is_set():continue
            for c in list(f.active()):await f.send(c)
            if s.sid not in refs:
                snap=owner.current_snapshot()
                if snap['games']:
                    g=snap['games'][0];side=next(x for x in g['sides'].values() if x['predicate']=='win');at=datetime.now(timezone.utc)-timedelta(hours=2)
                    for role,kind,value in [('model_reference','probability','0.57'),('bookmaker_reference','native_odds','2.15')]:
                        s.emit('reference',dict(type='product_reference',reference=dict(id=role,role=role,provider_id='B2 synthetic fixture',origin_id='independent-model' if role=='model_reference' else 'pinnacle',market_identity=g['product_identity'],participant=side['participant'],value_kind=kind,value=value,conversion_method='Explicit synthetic probability' if kind=='probability' else None,model_as_of=at.isoformat(),source_at=at.isoformat(),delay_seconds=None,provenance='Synthetic integration reference; no provider acquisition or real ratings')))
                    refs.add(s.sid)
    finally:await runner.cleanup();await f.close()

if __name__=='__main__':asyncio.run(main())
