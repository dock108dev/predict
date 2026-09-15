"""Synthetic transport messages only; no authenticated connection."""
import asyncio
import base64
import json
import unittest
from app.adapters.polymarket_us_stream import (MarketStream, RuntimeSigner, AuthenticatedTransport, subscription, StaleSubscriptionFrame)
from app.models.core import EvidenceKind, BookSync, ReceiptFreshness
from tests.test_polymarket_us import market, no_sleep

SLUG='aec-nfl-tb-cin-2026-09-13'

def message(request_id, price='0.4', **extra):
    return json.dumps({'requestId':request_id,'subscriptionType':'SUBSCRIPTION_TYPE_MARKET_DATA',
        'marketData':{'marketSlug':SLUG,'bids':[{'px':{'value':price,'currency':'USD'},'qty':'1.25'}],
                      'offers':[],**extra}})

class Socket:
    def __init__(self,actions):self.actions=list(actions);self.sent=[];self.closed=False
    async def send(self,text):self.sent.append(json.loads(text))
    async def recv(self):
        if not self.actions:raise ConnectionError()
        action=self.actions.pop(0)
        if action=='wait':await asyncio.sleep(10)
        if action=='disconnect':raise ConnectionError()
        request_id=self.sent[-1]['subscribe'].get('requestId')
        return action(request_id) if callable(action) else action
    async def close(self):self.closed=True

class StreamTests(unittest.IsolatedAsyncioTestCase):
    def stream(self, sockets, **kwargs):
        queue=iter(sockets)
        async def factory():return next(queue)
        return MarketStream([market()],factory,kind=EvidenceKind.SYNTHETIC,sleep=no_sleep,**kwargs)

    async def test_disconnect_resubscribe_replacement_and_bounds(self):
        first=Socket([lambda rid:message(rid),'disconnect'])
        second=Socket([lambda rid:message(rid,'0.3')])
        stream=self.stream([first,second],max_messages=2)
        results=[x async for x in stream.run()]
        self.assertTrue(first.closed and second.closed)
        self.assertNotEqual(first.sent[0],second.sent[0])
        self.assertEqual(results[1].sync,BookSync.UNSYNCHRONIZED)
        self.assertEqual(len(results[-1].outcomes[0].bids.levels),1)
        self.assertEqual(str(results[-1].outcomes[0].bids.levels[0].price.value),'0.3')
        self.assertEqual(results[0].sync,BookSync.SYNCHRONIZED)
        self.assertEqual(results[-1].sync,BookSync.SYNCHRONIZED)
        self.assertEqual(results[0].raw.kind,EvidenceKind.SYNTHETIC)
        self.assertEqual(stream.last[SLUG].sync,BookSync.UNSYNCHRONIZED)

    async def test_malformed_ambiguous_and_unknown(self):
        for bad in ['not json', json.dumps({'market_data':{}}), lambda rid:message(rid,delta=True),
                    lambda rid:message(rid,marketSlug='wrong')]:
            with self.subTest(bad=bad):
                socket=Socket([lambda rid:message(rid),bad])
                stream=self.stream([socket],max_connections=1)
                result=[x async for x in stream.run()]
                self.assertIn('unsupported_or_malformed',stream.diagnostics)
                self.assertEqual(result[-1].sync,BookSync.UNSYNCHRONIZED)
                self.assertTrue(socket.closed)

    async def test_stale_heartbeat_and_cancellation(self):
        socket=Socket([lambda rid:message(rid),'{"heartbeat":{}}','wait'])
        stream=self.stream([socket],max_connections=1,stale_seconds=.01,duration=.03)
        result=[x async for x in stream.run()]
        self.assertEqual(result[-1].sync,BookSync.SYNCHRONIZED)
        self.assertEqual(result[-1].receipt_freshness,ReceiptFreshness.STALE)
        self.assertIn('market_data_stale',stream.diagnostics)
        self.assertNotIn('disconnected',stream.diagnostics)
        socket=Socket(['wait']);stream=self.stream([socket])
        async def consume():return [x async for x in stream.run()]
        task=asyncio.create_task(consume());await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(socket.closed)

    async def test_missing_sides_no_inherited_depth(self):
        stream=self.stream([])
        generation=stream.begin_subscription('r')
        stream.parse(message('r'),'r',generation=generation)
        result=stream.parse(json.dumps({'requestId':'r','subscriptionType':'SUBSCRIPTION_TYPE_MARKET_DATA',
            'marketData':{'marketSlug':SLUG,'offers':[]}}),'r',generation=generation)
        self.assertIsNone(result.outcomes[0].bids)
        self.assertEqual(result.sync,BookSync.UNKNOWN)

    def test_subscription_and_signing(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        seed=bytes(range(32))  # SYNTHETIC test-only key, never a venue credential.
        signer=RuntimeSigner('synthetic-key',base64.b64encode(seed).decode())
        headers=signer.headers(123456)
        Ed25519PrivateKey.from_private_bytes(seed).public_key().verify(
            base64.b64decode(headers['X-PM-Signature']),b'123456GET/v1/ws/markets')
        self.assertNotIn('synthetic-key',repr(signer))
        with self.assertRaises(ValueError):AuthenticatedTransport(signer)
        self.assertEqual(subscription([SLUG],'r','snake')['subscribe']['subscription_type'],1)
        for slugs in [[],[SLUG,SLUG],list(map(str,range(101)))]:
            with self.assertRaises(ValueError):subscription(slugs,'r')
        with self.assertRaises(ValueError):RuntimeSigner('id','not-base64')

    async def test_adapter_stream_and_early_close(self):
        import httpx
        from app.adapters.polymarket_us import PolymarketUSAdapter
        sock=Socket([lambda rid:message(rid), 'wait'])
        async def factory():return sock
        a=PolymarketUSAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:None)),
                              stream_factory=factory,stream_options={'kind':EvidenceKind.SYNTHETIC})
        a.markets['381958']=market()
        iterator=a.stream_markets(('381958',))
        first=await anext(iterator)
        self.assertEqual(first.sync,BookSync.SYNCHRONIZED)
        await iterator.aclose()
        self.assertTrue(sock.closed)
        self.assertFalse(a.streams)
        await a.aclose()

    async def test_authenticated_transport_mock_only(self):
        from unittest.mock import AsyncMock, patch
        signer=RuntimeSigner('synthetic-key',base64.b64encode(bytes(range(32))).decode())
        transport=AuthenticatedTransport(signer,allow_connection=True)
        with patch('websockets.asyncio.client.connect',new_callable=AsyncMock) as connect:
            await transport()
            options=connect.call_args.kwargs
            self.assertIsNone(options['proxy'])
            self.assertIn('X-PM-Signature',options['additional_headers'])
            connect.side_effect=RuntimeError('synthetic-sensitive-error')
            with self.assertRaises(ConnectionError) as raised:await transport()
            self.assertNotIn('sensitive',str(raised.exception))


    async def test_quiet_market_keeps_connection_and_pending_message(self):
        class QuietSocket(Socket):
            async def recv(self):
                if len(self.actions) == 1:
                    await asyncio.sleep(.025)
                return await super().recv()
        sock=QuietSocket([lambda rid:message(rid),lambda rid:message(rid,'0.35')])
        stream=self.stream([sock],stale_seconds=.01,duration=.2,max_messages=2)
        results=[x async for x in stream.run()]
        self.assertEqual(len(sock.sent),1)
        self.assertIn('market_data_stale',stream.diagnostics)
        self.assertNotIn('disconnected',stream.diagnostics)
        self.assertEqual(str(results[-1].outcomes[0].bids.levels[0].price.value),'0.35')
        self.assertEqual(results[1].receipt_freshness,ReceiptFreshness.STALE)
        self.assertEqual(results[1].sync,BookSync.SYNCHRONIZED)

    async def test_connection_failure_retries_within_bound(self):
        calls=0
        async def fail():
            nonlocal calls
            calls+=1
            raise ConnectionError('synthetic transport failure')
        stream=MarketStream([market()],fail,max_connections=2,sleep=no_sleep)
        self.assertEqual([x async for x in stream.run()],[])
        self.assertEqual(calls,2)
        self.assertTrue(stream.closed)
        self.assertEqual(stream.diagnostics.count('disconnected'),2)


class WindowContractTests(unittest.TestCase):
    def test_atomic_replacement_omission_quantity_zero_and_empty(self):
        stream=MarketStream([market()],None)
        epoch=stream.begin_subscription('r')
        def apply(bids,offers=[]):
            return stream.parse(message('r',bids=bids,offers=offers),'r',generation=epoch)
        def row(p,q):return {'px':{'value':p,'currency':'USD'},'qty':q}
        first=apply([row('0.4','2.123456789'),row('0.3','4')])
        second=apply([row('0.4','7.123456789'),row('0.2','0')])
        self.assertEqual([(str(x.price.value),str(x.quantity.value)) for x in second.outcomes[0].bids.levels],[('0.4','7.123456789')])
        self.assertEqual(len(first.outcomes[0].bids.levels),2)
        self.assertIn('"qty": "0"',second.raw.json_text)
        empty=apply([])
        self.assertEqual(empty.outcomes[0].bids.levels,())
        self.assertEqual(empty.outcomes[0].asks.levels,())
        self.assertEqual(empty.sync,BookSync.SYNCHRONIZED)
        self.assertEqual(empty.outcomes[0].bids.depth.value,'partial')
        self.assertEqual(empty.receipt_freshness,ReceiptFreshness.RECENT)

    def test_old_epoch_and_subscription_cannot_replace_recovered_image(self):
        stream=MarketStream([market()],None)
        old=stream.begin_subscription('old')
        stream.parse(message('old'),'old',generation=old)
        new=stream.begin_subscription('new')
        self.assertEqual(stream.last[SLUG].sync,BookSync.UNSYNCHRONIZED)
        current=stream.parse(message('new','0.3'),'new',generation=new)
        for body,rid,epoch in [(message('old'),'old',old),(message('old'),'new',new),(message('new'),'new',old)]:
            with self.assertRaises(StaleSubscriptionFrame):stream.parse(body,rid,generation=epoch)
            self.assertIs(stream.last[SLUG],current)
        self.assertEqual(current.sync,BookSync.SYNCHRONIZED)

    def test_malformed_invalidates_atomically_and_new_subscription_recovers(self):
        stream=MarketStream([market()],None)
        epoch=stream.begin_subscription('r')
        stream.parse(message('r'),'r',generation=epoch)
        with self.assertRaises(ValueError):stream.parse(message('r',offers=[{'px':{'value':'0.8'},'qty':'bad'}]),'r',generation=epoch)
        self.assertEqual(stream.last[SLUG].sync,BookSync.UNSYNCHRONIZED)
        self.assertEqual(str(stream.last[SLUG].outcomes[0].bids.levels[0].price.value),'0.4')
        with self.assertRaises(StaleSubscriptionFrame):stream.parse(message('r'),'r',generation=epoch)
        epoch=stream.begin_subscription('new')
        self.assertEqual(stream.parse(message('new'),'new',generation=epoch).sync,BookSync.SYNCHRONIZED)
