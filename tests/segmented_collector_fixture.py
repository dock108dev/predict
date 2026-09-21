"""Busy, deterministic local native wire fixture. No retained identity repetition."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.reference.records import packed
from app.dashboard.coverage_owner import CoverageOwner
from tests.test_coverage import ke, km, pe, pm


class Fixture:
    def __init__(self, kalshi_markets=1):
        self.kalshi_markets = kalshi_markets
        self.us_markets = 1
        self.connections = []; self.rest_calls = []; self.changed = asyncio.Event()
        self.schedule = (datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
        self.books = 0; self.frames = 0; self.rows = 0; self.sequence = sha256()
        self.owner = None; self.last_record = None

    def us_market(self, mid):
        m=pm(mid);m.update(slug=mid,description='Synthetic fixture full-game winner terms',gameStartTime=self.schedule)
        for side,team in zip(m['marketSides'],('Detroit Lions','Buffalo Bills')):
            side.update(marketId=mid,team=dict(name=team))
        return m

    async def rest(self, req):
        self.rest_calls.append((req.path,dict(req.query)))
        if req.path.endswith('/account/limits'):
            return web.json_response(dict(read=dict(refill_rate=200,bucket_capacity=600)))
        if req.path.endswith('/account/endpoint_costs'):
            return web.json_response(dict(default_cost=10,endpoint_costs=[]))
        if req.path=='/trade-api/v2/events':
            e,m=ke('k');m['start_date']=self.schedule
            return web.json_response(dict(events=[e],milestones=[m],cursor=''))
        if req.path=='/trade-api/v2/markets':
            return web.json_response(dict(markets=[km('k'+str(i),'k') for i in range(self.kalshi_markets)],cursor=''))
        if req.path=='/v1/events':
            e=pe('p');e.update(gameId=1,startTime=self.schedule,markets=[self.us_market('p'+str(i)) for i in range(self.us_markets)])
            return web.json_response(dict(events=[e]))
        if req.path=='/v1/markets':
            return web.json_response(dict(markets=[self.us_market('p'+str(i)) for i in range(self.us_markets)]))
        raise AssertionError(req.path)

    async def ws(self, req):
        socket=web.WebSocketResponse();await socket.prepare(req)
        cmd=await socket.receive_json();venue='kalshi' if 'params' in cmd else 'polymarket_us'
        c=dict(socket=socket,command=cmd,venue=venue,seq=0,closed=False,images=set())
        self.connections.append(c);self.changed.set()
        if venue=='kalshi':
            await socket.send_json(dict(type='subscribed',id=cmd['id'],msg=dict(channel='orderbook_delta',sid=1)))
        try:
            async for _ in socket:pass
        finally:c['closed']=True;self.changed.set()
        return socket

    async def start(self, output, *, duration=180, profile_name=None, product_mode=False, segmented=True):
        app=web.Application();app.router.add_get('/ws',self.ws);app.router.add_get('/{path:.*}',self.rest)
        self.server=TestServer(app);await self.server.start_server()
        url=str(self.server.make_url('/')).rstrip('/')
        self.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
        from app.dashboard.coverage_owner import spec
        def product_spec():
            value=spec();value.update(mode='mock',reference_enabled=False);return value
        self.owner=CoverageOwner(Path(output)/'unused-saved',pilot_output=Path(output)/'pilot',
            endpoints=self.endpoints,mock_segmented=segmented,profile_name=profile_name,product_mode=product_mode,spec_factory=product_spec)
        await self.owner.start(duration=duration)
        s=self.owner.session
        original_save=s.journal.save
        def observed_save(r):
            original_save(r)
            self.sequence.update(packed(r).encode());self.rows+=1;self.last_record=r['type']
            self.books+=r['type']=='prediction_book';self.frames+=r['type']=='prediction_frame'
            self.changed.set()
        # Start was already durably admitted; include it without retaining the run.
        from app.collection.segmented import iter_journal
        for r,_ in iter_journal(s.journal.history.active.path if segmented else s.journal.path):
            if not r['type'].startswith('d3_'):self.sequence.update(packed(r).encode());self.rows+=1
        s.journal.save=observed_save
        await self.wait(lambda:len(self.active())==(2 if self.kalshi_markets<=20 else 3))
        await self.images()
        await self.wait(lambda:all(p.applied_generation==1 for p in s.producers.values()))
        return self.owner

    def active(self):return [c for c in self.connections if not c['closed']]

    async def wait(self, predicate):
        async with asyncio.timeout(20):
            while not predicate():
                self.changed.clear()
                if predicate():break
                if self.owner and self.owner.session.task.done():
                    raise AssertionError('collector ended before fixture objective: '+str(self.owner.session.reason))
                # State changes that don't write (e.g. a generation swap) get a
                # scheduled cooperative turn; primary ordering is event/ack based.
                try:await asyncio.wait_for(self.changed.wait(),.05)
                except TimeoutError:pass

    async def send(self, c, mid=None):
        if c['closed'] or self.owner.session.stop_event.is_set():return False
        before=self.books;c['seq']+=1
        if c['venue']=='kalshi':
            mid=mid or c['command']['params']['market_tickers'][0]
            if mid not in c['images']:
                body=dict(type='orderbook_snapshot',sid=1,seq=c['seq'],msg=dict(market_ticker=mid,market_id='synthetic-'+mid,
                    yes_dollars_fp=[['0.4000','100.00'],['0.3900','50.00']],no_dollars_fp=[['0.5000','200.00']]))
            else:
                body=dict(type='orderbook_delta',sid=1,seq=c['seq'],msg=dict(market_ticker=mid,market_id='synthetic-'+mid,side='yes',price_dollars='0.4000',delta_fp='1.00'))
        else:
            mid=mid or c['command']['subscribe']['marketSlugs'][0]
            body=dict(requestId=c['command']['subscribe']['requestId'],subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',
                marketData=dict(marketSlug=mid,bids=[],offers=[dict(px=dict(value='0.5000',currency='USD'),qty=str(100+c['seq']))],state='OPEN'))
        c['images'].add(mid)
        await c['socket'].send_json(body)
        await self.wait(lambda:self.books>before or self.owner.session.stop_event.is_set())
        await self.owner.session.queue.join()
        return self.books>before

    async def control(self):
        c=next(c for c in self.active() if c['venue']=='kalshi')
        c['seq']+=1;before=self.frames
        await c['socket'].send_json(dict(type='ok',sid=1,seq=c['seq'],msg={}))
        await self.wait(lambda:self.frames>before or self.owner.session.stop_event.is_set())
        await self.owner.session.queue.join()

    async def at_local(self, target):
        s=self.owner.session
        while s.journal.history.local['logical'] < target:
            if s.stop_event.is_set():raise AssertionError('resource stop before local target: '+str(s.reason))
            remaining=target-s.journal.history.local['logical']
            if remaining>=3:await self.send(self.active()[self.books%len(self.active())])
            else:await self.control()

    async def images(self):
        for c in list(self.active()):
            mids=c['command']['params']['market_tickers'] if c['venue']=='kalshi' else c['command']['subscribe']['marketSlugs']
            for mid in mids:
                if mid not in c['images']:await self.send(c,mid)

    async def busy(self, logical):
        i=0;s=self.owner.session
        while s.delivered < logical and not s.stop_event.is_set():
            cs=self.active();await self.send(cs[i%len(cs)]);i+=1

    async def close(self):
        if self.owner and self.owner.active():await self.owner.stop()
        try:
            if self.owner and self.owner.finalizer:await asyncio.wait_for(self.owner.finalizer,30)
        finally:await self.server.close()
