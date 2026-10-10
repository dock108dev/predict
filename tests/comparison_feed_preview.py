"""Multi-event ordinary Predict simulation; every transport is loopback only."""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.continuous import ContinuousSession
from app.dashboard.coverage_owner import CoverageOwner, spec
from app.dashboard.multi_game_server import create_app
from tests.retained_comparison_fixture import ComparisonFixture
from tests.test_coverage import ke, km, pe

TEAMS=[('Detroit Lions','Buffalo Bills'),('Chicago Bears','Minnesota Vikings'),
       ('Kansas City Chiefs','Denver Broncos'),('Dallas Cowboys','Philadelphia Eagles')]

class FeedFixture(ComparisonFixture):
    def market(self,i):
        m=self.us_market('p'+str(i))
        for side,team in zip(m['marketSides'],TEAMS[i]):
            side.update(description=team,team=dict(name=team))
        m['description']='SYNTHETIC normal winner; rescheduled to a date within two days; tie $0.50'
        return m

    async def rest(self,req):
        if req.path=='/trade-api/v2/events':
            pairs=[ke('k'+str(i),' vs '.join(t),self.schedule) for i,t in enumerate(TEAMS)]
            return web.json_response(dict(events=[p[0] for p in pairs],milestones=[p[1] for p in pairs],cursor=''))
        if req.path=='/trade-api/v2/markets':
            eid=req.query['event_ticker'];i=int(eid[1:]);m=km(eid,eid)
            m.update(title=TEAMS[i][0]+' wins',yes_sub_title=TEAMS[i][0],no_sub_title='Not '+TEAMS[i][0],
                     rules_primary='SYNTHETIC normal winner; begins within 48 hours; tie $0.50')
            return web.json_response(dict(markets=[m],cursor=''))
        if req.path=='/v1/events':
            events=[]
            for i,t in enumerate(TEAMS):
                e=pe('p'+str(i),t);e.update(title=' vs '.join(t),gameId=i+1,startTime=self.schedule,markets=[self.market(i)])
                events.append(e)
            offset=int(req.query.get('offset',0));return web.json_response(dict(events=events[offset:offset+5]))
        if req.path=='/v1/markets':
            return web.json_response(dict(markets=[self.market(int(req.query['gameId'])-1)]))
        return await super().rest(req)

    async def send(self,c,mid=None):
        if c['venue']=='kalshi':return await super().send(c,mid)
        if c['closed'] or self.owner.session.stop_event.is_set():return False
        before=self.books;c['seq']+=1;i=int(mid[1:])
        offer=['0.48','0.46','0.50','0.49'][i]
        bid=['0.43','0.47','0.40','0.42'][i]
        await c['socket'].send_json(dict(requestId=c['command']['subscribe']['requestId'],subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',marketData=dict(
            marketSlug=mid,bids=[dict(px=dict(value=bid,currency='USD'),qty='120.75')],
            offers=[dict(px=dict(value=offer,currency='USD'),qty=str(100+c['seq'])+'.25')],
            state='MARKET_STATE_OPEN',transactTime=datetime.now(timezone.utc).isoformat())))
        c['images'].add(mid)
        await self.wait(lambda:self.books>before or self.owner.session.stop_event.is_set())
        await self.owner.session.queue.join();return self.books>before

async def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
    f=FeedFixture();feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
    f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
    endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
    class Session(ContinuousSession):
        async def start(self):
            await super().start();save=self.journal.save
            def observed(row):save(row);f.books+=row['type']=='prediction_book';f.changed.set()
            self.journal.save=observed
    def configuration():
        s=spec();s.update(mode='mock',reference_enabled=False,capture_authorization='Isolated multi-event loopback simulation only')
        s['native_sources']={v:dict(state='enabled',environment='production',poll_seconds=10,event_cap=4,market_cap=10) for v in endpoints}
        s['native_sources'].update(novig=dict(state='unselected'),prophetx=dict(state='unselected'))
        return s
    class IsolatedOwner(CoverageOwner):
        def history_paths(self):
            from app.dashboard.session_history import list_sessions
            return list_sessions([self.output,self.pilot_output])
    owner=IsolatedOwner(root/'legacy',pilot_output=root/'sessions',endpoints=endpoints,product_mode=True,
                        spec_factory=configuration,mock_segmented=True,session_factory=Session);f.owner=owner
    if not owner.history_paths():
        await owner.start(duration=30);await f.wait(lambda:len(f.active())==2);await f.images()
        await owner.stop();await owner.finalizer
        if owner.error:raise RuntimeError(owner.error)
    # Exclude the ordinary catalog and local watches from this disposable preview.
    isolation=patch('app.dashboard.native_reviews.historical_paths',return_value={})
    isolation.start()
    runner=web.AppRunner(create_app(owner=owner,sessions={},watch_path=root/'watchlists.json'));await runner.setup();await web.TCPSite(runner,'127.0.0.1',8822).start()
    print('http://127.0.0.1:8822 · four-event SIMULATION · loopback only',flush=True)
    try:
        while True:
            await asyncio.sleep(1)
            if owner.active() and not owner.session.stop_event.is_set():
                for c in list(f.active()):
                    mids=c['command']['params']['market_tickers'] if c['venue']=='kalshi' else c['command']['subscribe']['marketSlugs']
                    for mid in mids:await f.send(c,mid)
    finally:
        await runner.cleanup();await f.close();isolation.stop()

if __name__=='__main__':asyncio.run(main())
