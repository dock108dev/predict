"""Synthetic contract-shaped cases, not observed sandbox/production behavior."""
import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import unittest

import httpx
from app.adapters.prophetx import *
from app.adapters.prophetx_stream import Stream, market_message, websocket_url

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def row(price='-125.25', quantity='12.345', oid=1, sid='synthetic-strike-a'):
    return {'outcome_id': oid, 'strike_id': sid, 'name': 'Synthetic A',
            'price': price, 'quantity': quantity, 'updated_at': 1780000000}


def market(selections=None, **extra):
    return {'id': 7, 'name': 'Synthetic moneyline', 'type': 'moneyline',
        'selections': selections if selections is not None else [[row()], [row('110', '5', 2, 'synthetic-strike-b')]], **extra}


def response(data):
    return Response(json.dumps(data), 'synthetic:test', NOW, EvidenceKind.SYNTHETIC)


def message(info=None, op='u', eid=11):
    payload = {'sport_event_id': eid, 'market_id': 7, 'info': info or market()}
    return json.dumps({'event': 'market_selections', 'channel': 'event-channel', 'data': json.dumps({
        'change_type': 'market_selections', 'op': op, 'timestamp': 1780000000123456789,
        'payload': base64.b64encode(json.dumps(payload).encode()).decode()})})


class ParseTests(unittest.TestCase):
    def test_native_precision_identity_unknown_units(self):
        body = '{"id":7,"selections":[[{"outcome_id":1,"strike_id":"s","name":"A","price":-125.25123456789123,"quantity":12.3456789123456789}]],"name":"M"}'
        r = Response(body, 'synthetic:test', NOW, EvidenceKind.SYNTHETIC)
        b = book(r, 11, decode(body))
        level = b.native_windows[0][0]
        self.assertEqual(level.price, Decimal('-125.25123456789123'))
        self.assertEqual(level.quantity.value, Decimal('12.3456789123456789'))
        self.assertEqual(level.quantity.unit, 'unknown')
        self.assertEqual(level.strike_id, 's')
        self.assertEqual(b.outcomes[0].outcome_id, 's')
        self.assertIsNone(b.outcomes[0].asks)
        self.assertEqual(b.sync, BookSync.UNKNOWN)
        self.assertIsNone(b.raw.exchange_at)

    def test_window_replacement_not_delta(self):
        first = market([[row('-120', '2'), row('-130', '8')], []])
        second = market([[row('-120', '3')], []])
        a, b = [market_message(message(x), {'event_id': 11}, response(x)) for x in (first, second)]
        self.assertEqual(len(a.native_windows[0]), 2)
        self.assertEqual(len(b.native_windows[0]), 1)
        self.assertEqual(b.native_windows[0][0].quantity.value, Decimal(3))
        self.assertEqual(b.native_depth, Depth.PARTIAL)
        self.assertEqual(b.native_sync, BookSync.SYNCHRONIZED)

    def test_placeholders_delete_and_missing(self):
        b = book(response({}), 11, market([[row('0', '0')], []]))
        self.assertEqual(b.native_windows[0][0].quantity.value, 0)
        b = market_message(message(op='d'), {'event_id': 11}, response({}))
        self.assertIsNone(b.native_windows)
        self.assertEqual(b.native_sync, BookSync.UNSYNCHRONIZED)
        b = book(response({}), 11, {'id': 7, 'name': 'M'})
        self.assertIsNone(b.native_windows)
        self.assertEqual(b.native_sync, BookSync.UNKNOWN)

    def test_status_not_borrowed_from_order_enums(self):
        for state in ['open', 'inactive', 'closed', 'suspended', 'open', 'unrecognized']:
            b = book(response({}), 11, market(status=state))
            self.assertEqual(b.native_status, state)
            self.assertEqual(b.state, MarketState.UNKNOWN)
        b = book(response({}), 11, {'id': 7, 'status': 'open'})
        self.assertIsNone(b.native_windows)

    def test_malformed_nested_scope_and_decimal(self):
        for body in ['null', '{', message(eid=12), message(op='x')]:
            with self.assertRaises(ValueError):
                market_message(body, {'event_id': 11}, response({}))
        bad = json.loads(message());bad['data'] = {'change_type':'market_selections','op':'u','payload':'%%%'}
        with self.assertRaises(ValueError):market_message(json.dumps(bad), {'event_id':11}, response({}))
        for group in [[row(quantity='-1')], [row(), row()], [row(price=1.25)], [row(),row(oid=2)]]:
            with self.assertRaises(ValueError):parse_windows([group])

    def test_dynamic_transport_and_no_unsafe_url(self):
        self.assertIn('wss://talaria.example/app/key', websocket_url({'key':'key','ws_host':'talaria.example','cluster':'us2'}))
        self.assertIn('ws-us2.pusher.com', websocket_url({'key':'key','cluster':'us2'}))
        for host in ['ws://example.com','wss://user:pass@example.com','https://example.com','example.com/?key=bad']:
            with self.assertRaises(ValueError):websocket_url({'key':'key','ws_host':host})


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler, **kwargs):
        return Client(Credentials('sandbox','synthetic-access','synthetic-secret'),
                      http=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kwargs)

    async def test_refresh_401_and_redaction(self):
        calls=[]
        def handler(req):
            calls.append(req.url.path)
            if req.url.path.endswith('/auth/login'):
                return httpx.Response(200,json={'data':{'access_token':'a','refresh_token':'r'}})
            if req.url.path.endswith('/auth/refresh'):
                return httpx.Response(200,json={'data':{'access_token':'b'}})
            return httpx.Response(200 if req.headers['Authorization']=='Bearer b' else 401,json={'data':[]})
        c=self.client(handler)
        await c.request('GET','/v4/mm/get_price_ladder')
        self.assertEqual(calls.count('/partner/auth/login'),1)
        self.assertEqual(calls.count('/partner/auth/refresh'),1)
        self.assertNotIn('synthetic-secret',repr(c.credentials))
        self.assertNotIn('synthetic-secret',json.dumps(c.diagnostics))
        await c.aclose();await c.aclose()
        self.assertIsNone(c.access)
        self.assertTrue(c.http.is_closed)

    async def test_expiry_and_expired_refresh(self):
        now=[0];calls=[]
        def handler(req):
            calls.append(req.url.path)
            if req.url.path.endswith('refresh'):return httpx.Response(401,text='secret server error')
            return httpx.Response(200,json={'data':{'access_token':'a','refresh_token':'r'}})
        c=self.client(handler,clock=lambda:now[0])
        await c.authenticate();now[0]=301;await c.authenticate()
        self.assertEqual(len(calls),3)
        now[0]+=86401;await c.authenticate()
        self.assertEqual(calls[-1],'/partner/auth/login')
        await c.aclose()

    async def test_rate_retry_budget_and_error_redaction(self):
        sleeps=[]
        async def sleep(n):sleeps.append(n)
        c=self.client(lambda req:httpx.Response(429,headers={'Retry-After':'2'},text='secret'),sleep=sleep,request_budget=3)
        with self.assertRaises(APIError) as ctx:await c.authenticate()
        self.assertEqual(sleeps,[2,2])
        self.assertEqual(c.remaining,0)
        self.assertNotIn('secret',str(ctx.exception))
        await c.aclose()

    async def test_no_early_retry_on_large_retry_after(self):
        c=self.client(lambda req:httpx.Response(429,headers={'Retry-After':'120'}))
        with self.assertRaises(APIError):await c.authenticate()
        self.assertEqual(c.remaining,19)
        await c.aclose()

    async def test_allowlist_timeout_and_cancel(self):
        async def handler(req):await asyncio.sleep(10)
        c=self.client(handler,timeout=.01,retries=0)
        with self.assertRaises(ValueError):await c.request('POST','/v4/mm/submit_order')
        with self.assertRaises(APIError):await c.authenticate()
        c.timeout=10
        t=asyncio.create_task(c.authenticate());await asyncio.sleep(.01);t.cancel()
        with self.assertRaises(asyncio.CancelledError):await t
        await c.aclose()

    async def test_byte_limit(self):
        c=self.client(lambda req:httpx.Response(200,text='x'*100),byte_budget=10)
        with self.assertRaises(APIError):await c.authenticate()
        await c.aclose()


class FixtureClient:
    def __init__(self):
        self.closed=False;self.omit=False;self.calls=[]
        self.sleep=lambda n:asyncio.sleep(0)
    async def request(self, method, path, **kwargs):
        self.calls.append((method,path,kwargs))
        if path.endswith('get_tournaments'):return response({'data':{'tournaments':[{'id':99,'name':'Synthetic league'}]}})
        if path.endswith('get_sport_events'):return response({'data':{'sport_events':[{'event_id':11,'name':'Synthetic A vs B','scheduled':'2026-09-13T12:00:00Z'}]}})
        if path.endswith('get_price_ladder'):return response({'data':[-125,100,110]})
        if path.endswith('get_multiple_markets'):return response({'data':{'11':[] if self.omit else [market()]}})
        if path.endswith('connection-config'):return response({'key':'synthetic-app','ws_host':'test.example'})
        if path.endswith('websocket'):return response({'data':{'success':True,'channel_count':2,'channel_limit':3,
          'authenticated':{'auth':'synthetic-signin','user_data':'{}'},'authorized_channel':[
            {'channel_name':'event-channel','auth':'synthetic-channel','scope':{'event_id':11},'binding_events':[{'name':'market_selections'}]},
            {'channel_name':'private-account','auth':'DO-NOT-SUBSCRIBE','binding_events':[]} ]}})
        raise AssertionError(path)
    async def aclose(self):self.closed=True


class Socket:
    def __init__(self, payloads):
        self.q=asyncio.Queue();self.sent=[];self.closed=False
        for x in [json.dumps({'event':'pusher:connection_established','data':'{"socket_id":"synthetic.1"}'}),
                  json.dumps({'event':'pusher:signin_success','data':{}}),
                  json.dumps({'event':'pusher_internal:subscription_succeeded','channel':'event-channel','data':'{}'}),*payloads]:self.q.put_nowait(x)
    async def recv(self):
        x=await self.q.get()
        if isinstance(x,Exception):raise x
        return x
    async def send(self,x):self.sent.append(json.loads(x))
    async def close(self):
        if not self.closed:self.closed=True;self.q.put_nowait(ConnectionError('closed'))


class AdapterStreamTests(unittest.IsolatedAsyncioTestCase):
    async def setup_adapter(self):
        c=FixtureClient();a=ProphetXAdapter(c,tournament_ids=('99',))
        await a.discover_markets('11');return a,c

    async def test_discovery_and_no_stale_snapshot_on_omission(self):
        a,c=await self.setup_adapter()
        self.assertEqual((await a.discover_tournaments())[0]['id'],99)
        self.assertEqual((await a.discover_events())[0].participants,())
        self.assertEqual(await a.discover_price_ladder(),(Decimal(-125),Decimal(100),Decimal(110)))
        self.assertIsNone((await a.get_market_rules('11:7:none')).rules_text)
        c.omit=True
        with self.assertRaises(LookupError):await a.get_snapshot('11:7:none')
        await a.aclose();self.assertTrue(c.closed)

    async def test_reconnect_resubscription_invalidation_and_cancel(self):
        a,c=await self.setup_adapter();sockets=[]
        async def connect(*args,**kwargs):
            s=Socket([message()]);sockets.append(s);return s
        s=Stream(a,('11:7:none',),connector=connect);iterator=s.updates()
        first=await anext(iterator)
        self.assertEqual(s.health,'connected')
        await s.disconnect()
        invalid=await anext(iterator)
        self.assertEqual(invalid.native_sync,BookSync.UNSYNCHRONIZED)
        self.assertIsNone(invalid.native_windows)
        second=await anext(iterator)
        self.assertEqual(s.generation,2)
        self.assertEqual(first.native_timestamp,second.native_timestamp)
        self.assertEqual(first.native_timestamp_progress,SourceTimeProgress.FIRST)
        self.assertEqual(second.native_timestamp_progress,SourceTimeProgress.REPEATED)
        self.assertEqual(second.source_time_progress,SourceTimeProgress.MISSING)
        self.assertEqual(len(sockets),2)
        for sock in sockets:
            self.assertEqual([x['event'] for x in sock.sent],['pusher:signin','pusher:subscribe'])
            self.assertEqual(sock.sent[1]['data']['channel'],'event-channel')
        task=asyncio.create_task(anext(iterator));await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(sockets[-1].closed)
        self.assertEqual(s.health,'disconnected')
        await a.aclose()

    async def test_quiet_receipt_stale_does_not_disconnect(self):
        a,c=await self.setup_adapter()
        sock=Socket([message()])
        async def connect(*args,**kwargs):return sock
        s=Stream(a,('11:7:none',),connector=connect,receipt_seconds=.01)
        it=s.updates();first=await anext(it);stale=await anext(it)
        self.assertEqual(stale.receipt_freshness,ReceiptFreshness.STALE)
        self.assertEqual(stale.raw,first.raw)
        self.assertEqual(stale.native_sync,BookSync.SYNCHRONIZED)
        self.assertEqual(s.health,'connected')
        await it.aclose();await a.aclose()

    async def test_malformed_message_invalidates_atomic_and_retry_exhausts(self):
        a,c=await self.setup_adapter()
        async def connect(*args,**kwargs):return Socket([message(),'{'])
        s=Stream(a,('11:7:none',),connector=connect,reconnects=0)
        it=s.updates();await anext(it);bad=await anext(it)
        self.assertIsNone(bad.native_windows)
        with self.assertRaises(APIError):await anext(it)
        self.assertEqual(s.health,'disconnected')
        await a.aclose()

    async def test_frame_counts_distinguish_filtered_data_without_retaining_secrets(self):
        a,c=await self.setup_adapter()
        other=market();other['id']=8
        sock=Socket([json.dumps({'event':'sensitive-unrecognized-name','data':{}}),
            message(other),message()])
        async def connect(*args,**kwargs):return sock
        s=Stream(a,('11:7:none',),connector=connect)
        it=s.updates();await anext(it)
        self.assertEqual(s.frame_counts, {'pusher:connection_established':1,
            'pusher:signin_success':1,'pusher_internal:subscription_succeeded':1,
            'other':1,'market_selections':2})
        self.assertEqual(s.filtered_markets,1)
        subscribed=s.diagnostics[-1]
        self.assertEqual(subscribed['requested_event_ids'],['11'])
        self.assertEqual(subscribed['authorized_event_ids'],['11'])
        self.assertTrue(subscribed['market_selections_binding'])
        self.assertNotIn('sensitive-unrecognized-name',json.dumps(s.diagnostics))
        await it.aclose();await a.aclose()

    async def test_duration_budget_cleanup(self):
        a,c=await self.setup_adapter();sock=Socket([])
        async def connect(*args,**kwargs):return sock
        s=Stream(a,('11:7:none',),connector=connect,duration=.02)
        with self.assertRaises(TimeoutError):await anext(s.updates())
        self.assertTrue(sock.closed)
        await a.aclose()

class EvidenceTests(unittest.TestCase):
    def test_nested_secret_rejected_and_exact_market_bytes_preserved(self):
        from app.prophetx_verify import Evidence
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as root:
            sink=Evidence(Path(root)/'capture',10000)
            body=message()
            sink.retain(Response(body,'synthetic:stream',NOW,EvidenceKind.SYNTHETIC),stream=True)
            self.assertEqual((sink.path/'market-001.json').read_text(),body)
            info=market();info['access_token']='synthetic-do-not-save'
            with self.assertRaises(ValueError):sink.retain(Response(message(info),'synthetic:stream',NOW),stream=True)
            self.assertEqual(sink.count,1)
            sink.remaining=1
            with self.assertRaises(ValueError):sink.retain(response({'data':[]}))

    def test_stream_contract_shape(self):
        with self.assertRaises(ValueError):book(response({}),11,market([[row()]]),streaming=True)
        with self.assertRaises(ValueError):
            book(response({}),11,market([[row(str(x)) for x in range(11)],[]]),streaming=True)

class MoreLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_rejection_closes_and_bounded_message_count(self):
        a=ProphetXAdapter(FixtureClient());await a.discover_markets('11')
        sockets=[]
        async def connect(*args,**kwargs):
            sock=Socket([message()]);sockets.append(sock);return sock
        s=Stream(a,('11:7:none',),connector=connect,message_budget=2,reconnects=0)
        with self.assertRaises(APIError):await anext(s.updates())
        self.assertTrue(sockets[0].closed)
        self.assertEqual(s.health,'disconnected')
        await a.aclose()

    async def test_discovery_malformed_is_atomic(self):
        c=FixtureClient();a=ProphetXAdapter(c);await a.discover_markets('11')
        previous=a.native_books['11:7:none']
        old_request=c.request
        async def bad(*args,**kwargs):
            if args[1].endswith('get_multiple_markets'):
                return response({'data':{'11':[market(status='changed'),{'id':8}]}})
            return await old_request(*args,**kwargs)
        c.request=bad
        with self.assertRaises(ValueError):await a.discover_markets('11')
        self.assertIs(a.native_books['11:7:none'],previous)
        await a.aclose()
