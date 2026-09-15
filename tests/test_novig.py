import asyncio
import copy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import unittest
import httpx
from app.adapters.novig import *
from app.adapters.novig_stream import MarketStream
from app.novig_example import MARKET, order, snapshot, response

async def no_sleep(_): pass

class Reconstruction(unittest.TestCase):
    def setUp(self):
        self.m=parse_market(response(MARKET),MARKET,'synthetic-event')
        self.i=OrderImage(self.m); self.i.snapshot(snapshot())
    def book(self): return self.i.book(response({}).raw('synthetic-event','synthetic-market'))
    def test_units_aggregation_replacement(self):
        self.i.tick('PLACE',order(qty='40'))
        level=self.book().outcomes[0].bids.levels[0]
        self.assertEqual(level.quantity.value,Decimal(240)); self.assertEqual(level.price.value,Decimal('.55'))
        self.assertEqual(level.quantity.unit,'payout_cents')
    def test_duplicates_cancel_zero(self):
        self.i.tick('PLACE',order(qty='40')); self.i.tick('PLACE',order(qty='40'))
        self.i.tick('CANCEL',order('o2')); self.i.tick('CANCEL',order('o2'))
        self.assertEqual(self.book().outcomes[0].bids.levels[0].quantity.value,40)
        self.i.tick('PLACE',order(qty='0')); self.assertEqual(self.book().outcomes[0].bids.levels,())
    def test_price_replacement(self):
        self.i.tick('PLACE',order(price='.6'))
        self.assertEqual([l.price.value for l in self.book().outcomes[0].bids.levels],[Decimal('.6'),Decimal('.55')])
    def test_invalid_order_atomic(self):
        old=copy.deepcopy(self.i.orders)
        for change in ({'price':.5},{'price':'NaN'},{'qty':'-1'},{'currency':'COIN'},
                       {'outcomeId':'bad'},{'marketId':'bad'},{'price':'.0001'}):
            with self.subTest(change=change),self.assertRaises(ValueError): self.i.tick('PLACE',{**order(),**change})
            self.assertEqual(self.i.orders,old)
    def test_snapshot_atomic_missing_duplicate(self):
        old=copy.deepcopy(self.i.orders)
        for d in (dict(snapshot(),outcomeLadders=[]),dict(snapshot(),marketId='other')):
            with self.assertRaises(ValueError): self.i.snapshot(d)
            self.assertEqual(self.i.orders,old)
        d=snapshot(); d['outcomeLadders'][0]['bids'].append(order())
        with self.assertRaises(ValueError): self.i.snapshot(d)
    def test_timestamp_depth_sync_and_quotes(self):
        b=self.book()
        self.assertIsNone(b.raw.exchange_at); self.assertIsNone(b.sequence)
        self.assertEqual(b.sync,BookSync.UNKNOWN); self.assertEqual(b.outcomes[0].bids.depth,Depth.UNKNOWN)
        self.assertIsNone(quotes(b)[0].ask)
    def test_identity_validation(self):
        with self.assertRaises(ValueError): parse_market(response(MARKET),MARKET,'other')
    def test_tick_before_bootstrap(self):
        with self.assertRaises(ValueError): OrderImage(self.m).tick('PLACE',order())

class Protocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.a=NovigAdapter(environment='qa',client_id='synthetic',client_secret='synthetic',sleep=no_sleep)
        self.m=parse_market(response(MARKET),MARKET,'synthetic-event')
        self.a.markets={'synthetic-market':self.m}
        self.a.locks=response({'systemLock':None,'lockedEventIds':[]})
        self.s=MarketStream(self.a,[self.m]); self.s.generation=1
        self.apply({'event':'book','data':snapshot()})
    async def asyncTearDown(self): await self.s.aclose(); await self.a.aclose()
    def apply(self,d,g=1): return self.s.apply(response(d),g)
    def lifecycle(self,t): return self.apply({'type':t,'market':{'id':'synthetic-market','eventId':'synthetic-event','status':'OPEN'}})
    async def test_close_implicit_cancel_stale_place(self):
        out=self.lifecycle('CLOSE'); self.assertEqual(out[-1].state,MarketState.CLOSED)
        self.assertEqual(self.s.images['synthetic-market'].orders,{})
        self.assertEqual(self.apply({'type':'PLACE','order':order()}),[])
    async def test_live_edges_idempotent_repeat(self):
        self.lifecycle('EVENT_GOLIVE'); self.apply({'type':'PLACE','order':order('new')})
        self.lifecycle('EVENT_GOLIVE'); self.assertIn('new',self.s.images['synthetic-market'].orders)
        self.lifecycle('EVENT_UNLIVE'); self.lifecycle('EVENT_GOLIVE')
        self.assertEqual(self.s.images['synthetic-market'].orders,{})
    async def test_lock_wins_open_and_expires_to_unknown(self):
        self.a.locks=response({'systemLock':{'id':'lock'},'lockedEventIds':[]})
        self.assertEqual(self.lifecycle('OPEN')[-1].state,MarketState.SUSPENDED)
        self.a.locks=replace(self.a.locks,received_at=self.a.now()-timedelta(seconds=6))
        self.assertEqual(self.lifecycle('OPEN')[-1].state,MarketState.UNKNOWN)
    async def test_event_lock(self):
        self.a.locks=response({'systemLock':None,'lockedEventIds':['synthetic-event']})
        self.assertEqual(self.lifecycle('OPEN')[-1].state,MarketState.SUSPENDED)
    async def test_old_generation_ignored(self):
        self.assertEqual(self.apply({'type':'CLOSE'},0),[])
        self.assertTrue(self.s.images['synthetic-market'].orders)
    async def test_unverified_envelope_rejected(self):
        with self.assertRaises(ValueError): self.apply({'event':'book','data':[]})
    async def test_unknown_frame_rejected(self):
        with self.assertRaises(ValueError): self.apply({'type':'SOMETHING_NEW'})
    async def test_eventwide_drain_once(self):
        other=replace(self.m,raw=response({}).raw('synthetic-event','other-market'))
        image=OrderImage(other); image.orders={'old':('home',Decimal('.5'),Decimal(100))}; image.initialized=True
        self.s.images['other-market']=image
        self.lifecycle('EVENT_GOLIVE'); self.assertEqual(image.orders,{})
        image.orders={'new':('home',Decimal('.5'),Decimal(100))}
        self.apply({'type':'EVENT_GOLIVE','market':{'id':'other-market','eventId':'synthetic-event'}})
        self.assertIn('new',image.orders)

class HTTPTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self,handler,**kwargs):
        return NovigAdapter(environment='qa',client_id='fake',client_secret='fake',
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),sleep=no_sleep,**kwargs)
    async def test_auth_renew_and_hosts(self):
        calls=[]; now=[0]
        def h(r):
            calls.append(r)
            return httpx.Response(200,json={'access_token':'fake-token','expires_in':1800})
        async with self.adapter(h,clock=lambda:now[0]) as a:
            await a.access_token(); await a.access_token(); self.assertEqual(a.requests,1)
            now[0]=1771; await a.access_token(); self.assertEqual(a.renewals,2)
            self.assertEqual(str(calls[0].url),AUTH['qa'])
            self.assertEqual(json.loads(calls[0].content)['audience'],HOSTS['qa'])
            self.assertEqual(a.responses,[])
        self.assertIsNone(a.token); self.assertTrue(a.client.is_closed)
    async def test_401_refresh(self):
        n=[0]
        def h(r):
            if r.method=='POST': return httpx.Response(200,json={'access_token':'token'})
            n[0]+=1
            return httpx.Response(401 if n[0]==1 else 200,json={})
        async with self.adapter(h) as a:
            await a._get('locks'); self.assertEqual(a.renewals,2)
    async def test_millisecond_rate_limits(self):
        waits=[]
        async def sleep(n): waits.append(n)
        a=self.adapter(lambda _:httpx.Response(200))
        a.sleep=sleep
        await a._delay({'Retry-After':'1500','X-RateLimit-Reset':'2000'},0)
        self.assertEqual(waits,[2.0]); await a.aclose()
    async def test_budget_and_large_body(self):
        async with self.adapter(lambda _:httpx.Response(200,json={'access_token':'token'}),max_requests=1) as a:
            await a.access_token()
            with self.assertRaises(RuntimeError): await a._get('locks')
        async with self.adapter(lambda _:httpx.Response(200,text='x'*100),max_bytes=10) as a:
            with self.assertRaises(RuntimeError): await a.access_token()
    async def test_discovery_and_snapshot(self):
        def h(r):
            if r.method=='POST': return httpx.Response(200,json={'access_token':'token'})
            p=r.url.path
            if p.endswith('/events'): data=[{'id':'synthetic-event','league':'NFL','status':'OPEN_PREGAME','description':'Test','scheduledStart':'2099-01-01T00:00:00Z'}]
            elif 'getMarketsByEvent' in p: data=[MARKET]
            elif '/events/' in p: data={'id':'synthetic-event','status':'OPEN_PREGAME'}
            elif p.endswith('/locks'): data={'systemLock':None,'lockedEventIds':[]}
            else: data=snapshot()
            return httpx.Response(200,json=data)
        async with self.adapter(h) as a:
            self.assertEqual(len(await a.discover_events()),1)
            self.assertEqual(len(await a.discover_markets()),1)
            self.assertEqual((await a.get_snapshot('synthetic-market')).quantity_unit,'payout_cents')
            self.assertIsNone((await a.get_market_rules('synthetic-market')).official_source)
    async def test_429_bounded_retry(self):
        async with self.adapter(lambda r:httpx.Response(429,headers={'Retry-After':'5'})) as a:
            with self.assertRaises(ConnectionError): await a.access_token()
            self.assertEqual(a.requests,2)

class FakeSocket:
    def __init__(self,frames): self.frames=list(frames); self.sent=[]; self.closed=False
    async def send(self,s): self.sent.append(json.loads(s))
    async def recv(self):
        if self.frames: return json.dumps(self.frames.pop(0))
        await asyncio.sleep(10)
    async def close(self): self.closed=True

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def setup_adapter(self,frames,**options):
        def h(r):
            if r.method=='POST': return httpx.Response(200,json={'access_token':'fake'})
            if r.url.path.endswith('/locks'): d={'systemLock':None,'lockedEventIds':[]}
            elif 'getMarketsByEvent' in r.url.path: d=[MARKET]
            else: d={'id':'synthetic-event','status':'OPEN_PREGAME'}
            return httpx.Response(200,json=d)
        sockets=[]
        async def factory(_):
            ws=FakeSocket(frames[len(sockets)]); sockets.append(ws); return ws
        a=NovigAdapter(environment='qa',client_id='fake',client_secret='fake',sleep=no_sleep,
            client=httpx.AsyncClient(transport=httpx.MockTransport(h)),stream_factory=factory,stream_options=options)
        a.markets={'synthetic-market':parse_market(response(MARKET),MARKET,'synthetic-event')}
        return a,sockets
    async def test_disconnect_fresh_bootstrap_and_cleanup(self):
        a,sockets=await self.setup_adapter([
            [{'event':'book','data':snapshot()},{'type':'PLACE','order':order(qty='40')}],
            [{'event':'book','data':snapshot()},{'type':'PLACE','order':order(qty='10')}]],
            duration=2,reconnect_after=.02,max_messages=4)
        async with a:
            updates=[u async for u in a.stream_markets(('synthetic-market',))]
            self.assertEqual(len(sockets),2); self.assertEqual(a.renewals,2)
            self.assertEqual(updates[-1].outcomes[0].bids.levels[0].quantity.value,210)
            self.assertTrue(any(u.sync==BookSync.UNSYNCHRONIZED for u in updates))
            self.assertEqual(a.streams,set())
        self.assertTrue(all(w.closed for w in sockets))
        self.assertTrue(all({'event':'unsubscribe','data':'synthetic-market'} in w.sent for w in sockets))
    async def test_cancel_closes_pending_receive(self):
        a,sockets=await self.setup_adapter([[{'event':'book','data':snapshot()}]],duration=2,reconnect_after=1)
        async def consume():
            async for _ in a.stream_markets(('synthetic-market',)): pass
        task=asyncio.create_task(consume())
        for _ in range(100):
            await asyncio.sleep(.001)
            if sockets: break
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(sockets[0].closed); self.assertFalse(a.streams)
        await a.aclose()
    async def test_early_iterator_close(self):
        a,sockets=await self.setup_adapter([[{'event':'book','data':snapshot()}]])
        iterator=a.stream_markets(('synthetic-market',)); await anext(iterator); await iterator.aclose()
        self.assertTrue(sockets[0].closed); self.assertFalse(a.streams); await a.aclose()
    async def test_bootstrap_failure_closes(self):
        a,sockets=await self.setup_adapter([[{'type':'PLACE','order':order()}]])
        with self.assertRaises(ValueError):
            async for _ in a.stream_markets(('synthetic-market',)): pass
        self.assertTrue(sockets[0].closed); await a.aclose()

class VerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_credentials_never_connects(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.novig_verify import verify
        with tempfile.TemporaryDirectory() as temp:
            with patch('app.novig_verify.credentials',return_value=(None,None)),patch('httpx.AsyncClient',side_effect=AssertionError('network forbidden')):
                r=await verify(SimpleNamespace(environment='qa',output=str(Path(temp)/'new')))
            self.assertEqual(r['status'],'blocked'); self.assertFalse(r['qualified'])
    async def test_protocol_ping_pong_and_disconnect_recovery(self):
        # Local loopback only; actual websockets client handles server protocol Ping.
        from websockets.asyncio.server import serve
        from websockets.asyncio.client import connect
        pongs=[]
        async def handler(ws):
            waiter=await ws.ping(b'novig-synthetic-heartbeat')
            await asyncio.wait_for(waiter,1); pongs.append(True)
            await ws.close()
        async with serve(handler,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            async with connect(f'ws://127.0.0.1:{port}',ping_interval=None) as ws:
                await ws.wait_closed()
        self.assertEqual(pongs,[True])
