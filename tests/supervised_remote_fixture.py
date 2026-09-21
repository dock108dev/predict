"""Separate bounded loopback venue fixture; no collector state leaves its owner."""
import asyncio
from collections import Counter
import ipaddress
import json
import multiprocessing
from pathlib import Path
import resource
import signal
import socket
import time
from types import SimpleNamespace
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.continuous import rss
from app.collection.segmented import iter_journal
from app.collection.supervised import NAME
from app.dashboard.coverage_owner import CoverageOwner
from app.reference.records import packed
from tests.supervised_fixture import Representative

class VenueFixture(Representative):
    async def images(self):
        for c in list(self.active()):
            mids=c['command']['params']['market_tickers'] if c['venue']=='kalshi' else c['command']['subscribe']['marketSlugs']
            for mid in mids:
                await self.send(c,mid)
                await asyncio.sleep(1/52)

    async def rest(self,req):
        self.request_times.append(dict(venue='kalshi' if req.path.startswith('/trade-api/') else 'polymarket_us',path=req.path,at=time.monotonic()))
        return await super().rest(req)

    async def wait(self,predicate):
        # A remote venue does not get an in-process collector acknowledgement.
        # WebSocket backpressure is real; the collector's exact replay validates
        # every admitted observation independently below.
        return

async def serve(pipe,out):
    f=VenueFixture();f.request_times=[]
    async def drained():pass
    f.owner=SimpleNamespace(session=SimpleNamespace(stop_event=asyncio.Event(),queue=SimpleNamespace(join=drained)))
    app=web.Application();app.router.add_get('/ws',f.ws);app.router.add_get('/{path:.*}',f.rest)
    server=TestServer(app);await server.start_server()
    url=str(server.make_url('/')).rstrip('/')
    pipe.send(dict(endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}))
    traffic=None;feed_started=None;error=None
    try:
        while True:
            if pipe.poll():
                command=pipe.recv()
                if command=='stop':break
            if rss()>=128*1024**2:raise RuntimeError('fixture RSS cap')
            if len(f.connections)>24 or len(f.rest_calls)>256:raise RuntimeError('fixture object cap')
            if traffic is None and len(f.active())==5:
                await f.images();feed_started=time.monotonic();traffic=asyncio.create_task(f.traffic())
                pipe.send(dict(ready=True,feed_started=feed_started))
            await asyncio.sleep(.02)
    except BaseException as exc:
        error=repr(exc)
    finally:
        f.owner.session.stop_event.set()
        if traffic:
            try:await traffic
            except (ConnectionResetError,RuntimeError) as exc:
                if any(not c['closed'] for c in f.connections):error=repr(exc)
        await server.close()
        result=dict(sent=f.sent,sent_bytes=f.sent_bytes,connections=len(f.connections),closed=all(c['closed'] for c in f.connections),request_timestamps=f.request_times,rest_requests=len(f.rest_calls),rss_peak=rss(),feed_started=feed_started,error=error)
        (out/'fixture.json').write_text(json.dumps(result,indent=2)+'\n');pipe.send(result)

def child(pipe,out):
    signal.alarm(660);resource.setrlimit(resource.RLIMIT_CPU,(120,120));resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024**2,2*1024**2))
    original=socket.socket.connect
    def connect(s,a):
        assert ipaddress.ip_address(a[0]).is_loopback
        return original(s,a)
    with patch('socket.socket.connect',connect),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials blocked')):
        asyncio.run(serve(pipe,Path(out)))

class RemoteRepresentative:
    def __init__(self):
        from hashlib import sha256
        self.owner=None;self.rows=self.books=self.frames=self.flow_encoded=self.flow_expanded=0
        self.sequence=sha256();self.fixture_result=None;self.process=None

    async def receive(self):
        async with asyncio.timeout(75):
            while not self.pipe.poll():
                if not self.process.is_alive():raise AssertionError('fixture process exited')
                await asyncio.sleep(.02)
            return self.pipe.recv()

    async def start(self,out,duration=300):
        ctx=multiprocessing.get_context('spawn');self.pipe,remote=ctx.Pipe()
        self.process=ctx.Process(target=child,args=(remote,str(out)));self.process.start();remote.close()
        message=await self.receive()
        self.owner=CoverageOwner(Path(out)/'unused',pilot_output=Path(out)/'pilot',endpoints=message['endpoints'],mock_segmented=True,profile_name=NAME)
        assert not self.owner.active()
        await self.owner.start(duration=duration)
        s=self.owner.session;original=s.journal.save
        def save(row):
            original(row);self.sequence.update(packed(row).encode());self.rows+=1
            if row['type'] in ('prediction_frame','prediction_book','source_health'):
                from app.collection.journal_encoding import encode
                self.flow_encoded+=len(packed(encode(row)).encode());self.flow_expanded+=len(packed(row).encode())
            self.books+=row['type']=='prediction_book';self.frames+=row['type']=='prediction_frame'
        for r,_ in iter_journal(s.journal.history.active.path):
            if not r['type'].startswith('d3_'):self.sequence.update(packed(r).encode());self.rows+=1
        s.journal.save=save
        message=await self.receive();assert message.get('ready'),message
        self.feed_started=message['feed_started']
        async with asyncio.timeout(10):
            while not all(s.status_coverage()[v]['usable']==n for v,n in [('kalshi',64),('polymarket_us',32)]):
                if s.task.done():raise AssertionError('collector early stop '+str(s.reason))
                await asyncio.sleep(.02)
        return self.owner

    async def finish_fixture(self):
        if self.fixture_result is None:
            self.pipe.send('stop');self.fixture_result=await self.receive()
            self.process.join(timeout=5)
            assert not self.process.is_alive(),'fixture closure timeout'
        return self.fixture_result

    async def close(self):
        if self.owner and self.owner.active():await self.owner.stop()
        if self.owner and self.owner.finalizer:await self.owner.finalizer
        if self.process and self.process.is_alive():await self.finish_fixture()
