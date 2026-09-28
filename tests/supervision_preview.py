"""Isolated four-event browser verification; every provider endpoint is loopback."""
import asyncio
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.comparison_policy import multi_specification
from app.collection.two_source import QualificationOwner,QualificationSession
from app.dashboard.multi_game_server import create_app
from tests.comparison_feed_preview import FeedFixture
from scripts.supervise_comparison import Supervisor,LocalApp,Evidence

async def main():
    root=Path(sys.argv[1]);root.mkdir(exist_ok=False)
    port=int(sys.argv[2]);f=FeedFixture()
    feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
    f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
    endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
    at=datetime.now(timezone.utc);attempt=str(uuid4());s=multi_specification(at.isoformat(),(at+timedelta(minutes=15)).isoformat(),attempt,'mock')
    class Session(QualificationSession):
        async def start(self):
            await super().start()
            (root/'run/b3-attempt.json').write_text(json.dumps(dict(attempt_id=attempt,started_monotonic=self.started_monotonic,mode='synthetic')))
            original=self.journal.save
            def saved(row):original(row);f.books+=row['type']=='prediction_book';f.changed.set()
            self.journal.save=saved
        async def close_resources(self):
            await super().close_resources()
            if not self.cleanup_errors:(root/'run/network-closed.json').write_text(json.dumps(dict(attempt_id=attempt,monotonic=time.monotonic(),mode='synthetic')))
    o=QualificationOwner(root/'legacy',pilot_output=root/'run',endpoints=endpoints,product_mode=True,spec_factory=lambda:s,session_factory=Session);f.owner=o
    runner=web.AppRunner(create_app(owner=o,sessions={}));await runner.setup();await web.TCPSite(runner,'127.0.0.1',port).start()
    (root/'fixture-config.json').write_text(json.dumps(dict(mode='synthetic',attempt=attempt,port=port,endpoints=endpoints,spec=s),indent=2)+'\n')
    monitor=Supervisor(LocalApp(f'http://127.0.0.1:{port}'),root/'run',attempt,Evidence(root/'observer'),start_before=s['start_before'])
    task=asyncio.create_task(asyncio.to_thread(monitor.run))
    print(f'SIMULATION only at http://127.0.0.1:{port}; idle monitor attached',flush=True)
    count=0
    try:
        while True:
            await asyncio.sleep(.5);count+=1
            if not o.active() or o.session.stop_event.is_set():continue
            for c in list(f.active()):
                if c['venue']!=('kalshi' if count%2 else 'polymarket_us'):continue
                mids=c['command']['params']['market_tickers'] if c['venue']=='kalshi' else c['command']['subscribe']['marketSlugs']
                for mid in mids:await f.send(c,mid)
    finally:
        if o.active():await o.stop()
        if o.finalizer:await o.finalizer
        await runner.cleanup();await f.close()

if __name__=='__main__':asyncio.run(main())
