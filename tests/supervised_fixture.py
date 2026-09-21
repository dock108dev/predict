"""Retained-shape synthetic local traffic; original evidence is read-only."""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from pathlib import Path
import time
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.segmented import iter_journal
from app.collection.supervised import NAME
from app.dashboard.coverage_owner import CoverageOwner
from app.reference.records import packed
from tests.segmented_collector_fixture import Fixture
from tests.test_journal_efficiency import ORIGINAL

class Representative(Fixture):
    def __init__(self):
        super().__init__(64)
        self.us_markets=32; self.catalog={}; self.snapshots={}; self.us_images={}
        self.delta_templates={}; self.sent=0; self.sent_bytes=0; self.flow_encoded=0; self.flow_expanded=0
        self.schedule=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
        def reschedule(value):
            if isinstance(value,dict):
                return {k:(self.schedule if k in ('start_date','startTime','gameStartTime','startDate') else reschedule(v)) for k,v in value.items()}
            if isinstance(value,list):return [reschedule(v) for v in value]
            return value
        for r,_ in iter_journal(ORIGINAL):
            if r['type']=='prediction_discovery_http':
                query=r.get('params') or {}
                discriminator=query.get('event_ticker',query.get('gameId',query.get('offset','')))
                self.catalog[(r['path'],str(discriminator))]=reschedule(json.loads(base64.b64decode(r['body_b64'])))
            elif r['type']=='prediction_frame':
                b=json.loads(base64.b64decode(r['body_b64']))
                if b.get('type')=='orderbook_snapshot':self.snapshots[b['msg']['market_ticker']]=b
                if b.get('type')=='orderbook_delta':self.delta_templates[b['msg']['market_ticker']]=b
                if 'marketData' in b:self.us_images[b['marketData']['marketSlug']]=b
        # All selected slugs need an image; use a retained native shape for those
        # not seen in the short capture, explicitly synthetic metadata association.
        for (path,_),body in self.catalog.items():
            if path=='/v1/events':
                for event in body['events']:
                    for m in event.get('markets',[]):
                        self.us_images.setdefault(m['slug'],next(iter(self.us_images.values())))

    async def rest(self,req):
        self.rest_calls.append((req.path,dict(req.query)))
        discriminator=req.query.get('event_ticker',req.query.get('gameId',req.query.get('offset','')))
        key=(req.path,str(discriminator))
        if key not in self.catalog:raise AssertionError(key)
        return web.json_response(self.catalog[key])

    async def start(self,output,*,duration=300):
        app=web.Application();app.router.add_get('/ws',self.ws);app.router.add_get('/{path:.*}',self.rest)
        self.server=TestServer(app);await self.server.start_server()
        url=str(self.server.make_url('/')).rstrip('/')
        self.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
        self.owner=CoverageOwner(Path(output)/'unused',pilot_output=Path(output)/'pilot',endpoints=self.endpoints,
            mock_segmented=True,profile_name=NAME)
        assert not self.owner.active()
        await self.owner.start(duration=duration)
        s=self.owner.session; original=s.journal.save
        def save(row):
            original(row);self.sequence.update(packed(row).encode());self.rows+=1
            if row['type'] in ('prediction_frame','prediction_book','source_health'):
                from app.collection.journal_encoding import encode
                self.flow_encoded+=len(packed(encode(row)).encode());self.flow_expanded+=len(packed(row).encode())
            self.books+=row['type']=='prediction_book';self.frames+=row['type']=='prediction_frame';self.changed.set()
        for r,_ in iter_journal(s.journal.history.active.path):
            if not r['type'].startswith('d3_'):self.sequence.update(packed(r).encode());self.rows+=1
        s.journal.save=save
        async with asyncio.timeout(70):
            while len(self.active())<5:
                if s.task.done():raise AssertionError('early stop '+str(s.reason))
                await asyncio.sleep(.05)
        await self.images()
        await self.wait(lambda:all(p.applied_generation==1 for p in s.producers.values()))
        return self.owner

    async def send(self,c,mid=None):
        if c['closed'] or self.owner.session.stop_event.is_set():return False
        before=self.books; c['seq']+=1
        if c['venue']=='kalshi':
            ids=c['command']['params']['market_tickers']; mid=mid or ids[c['seq']%len(ids)]
            # All first images use that market's original depth distribution.
            body=deepcopy(self.snapshots[mid] if mid not in c['images'] or mid not in self.delta_templates else self.delta_templates[mid])
            body.update(sid=1,seq=c['seq'])
            if body['type']=='orderbook_delta':body['msg']['delta_fp']='0.01'
        else:
            ids=c['command']['subscribe']['marketSlugs']; mid=mid or ids[c['seq']%len(ids)]
            body=deepcopy(self.us_images[mid]);body['requestId']=c['command']['subscribe']['requestId'];body['marketData']['marketSlug']=mid
        c['images'].add(mid); self.sent+=1;self.sent_bytes+=len(packed(body).encode())
        await c['socket'].send_json(body)
        await self.wait(lambda:self.books>before or self.owner.session.stop_event.is_set())
        await self.owner.session.queue.join()
        return self.books>before

    async def traffic(self):
        # 52 frames/s aggregate exceeds twice the retained active mean25.06/s.
        # 18 US +34 Kalshi gives the retained venue mix, including all96 markets.
        tick=time.monotonic(); i=0
        while not self.owner.session.stop_event.is_set():
            active=self.active(); ks=[c for c in active if c['venue']=='kalshi']; ps=[c for c in active if c['venue']=='polymarket_us']
            if not ks or not ps:break
            c=ps[0] if i%26<9 else ks[i%len(ks)]
            await self.send(c);i+=1;tick+=1/52
            await asyncio.sleep(max(0,tick-time.monotonic()))

    async def close(self):
        if self.owner and self.owner.active():await self.owner.stop()
        try:
            if self.owner and self.owner.finalizer:await asyncio.wait_for(self.owner.finalizer,310)
        finally:await self.server.close()
