"""Isolated, clearly synthetic ordinary-app price updates. No provider access."""
import asyncio,json,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from aiohttp import web
from aiohttp.test_utils import TestServer
from tests.opportunity_card_preview import TermsFixture
from app.collection.comparison_policy import specification
from app.collection.two_source import QualificationOwner,QualificationSession
from app.dashboard.multi_game_server import create_app

class ComparisonFixture(TermsFixture):
    async def send(self,c,mid=None):
        if c['venue']=='kalshi':return await super().send(c,mid)
        if c['closed'] or self.owner.session.stop_event.is_set():return False
        before=self.books;c['seq']+=1
        mid=mid or c['command']['subscribe']['marketSlugs'][0]
        price='0.48' if c['seq']%2 else '0.49'
        body=dict(requestId=c['command']['subscribe']['requestId'],subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',marketData=dict(
            marketSlug=mid,bids=[dict(px=dict(value='0.43',currency='USD'),qty='120.75')],
            offers=[dict(px=dict(value=price,currency='USD'),qty=str(100+c['seq'])+'.25')],
            state='MARKET_STATE_OPEN',transactTime=datetime.now(timezone.utc).isoformat()))
        c['images'].add(mid);await c['socket'].send_json(body)
        await self.wait(lambda:self.books>before or self.owner.session.stop_event.is_set())
        await self.owner.session.queue.join();return self.books>before

async def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
    f=ComparisonFixture();feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
    f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
    endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
    at=datetime.now(timezone.utc);s=specification(at.isoformat(),(at+timedelta(minutes=15)).isoformat(),str(uuid4()),'mock')
    class Session(QualificationSession):
        async def start(self):
            await super().start();save=self.journal.save
            def observed(row):save(row);f.books+=row['type']=='prediction_book';f.changed.set()
            self.journal.save=observed
    owner=QualificationOwner(root/'legacy',pilot_output=root/'sessions',endpoints=endpoints,product_mode=True,session_factory=Session,spec_factory=lambda:s)
    f.owner=owner
    runner=web.AppRunner(create_app(owner=owner,sessions={}));await runner.setup();await web.TCPSite(runner,'127.0.0.1',int(sys.argv[2]) if len(sys.argv)>2 else 8821).start()
    print('Loopback SIMULATION · Start uses local fixtures only',flush=True)
    counter=0
    try:
        while True:
            await asyncio.sleep(.4);counter+=1
            if not owner.active() or owner.session.stop_event.is_set():continue
            for c in list(f.active()):
                if c['venue']!=('kalshi' if counter%2 else 'polymarket_us'):continue
                if (root/('disconnect-'+c['venue'])).exists():
                    (root/('disconnect-'+c['venue'])).unlink();await c['socket'].close();continue
                if not (root/('pause-'+c['venue'])).exists():await f.send(c)
    finally:await runner.cleanup();await f.close()

if __name__=='__main__':asyncio.run(main())
