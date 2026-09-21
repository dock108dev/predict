import asyncio
from contextlib import aclosing
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from app.adapters.kalshi import (KalshiAdapter, Response, decode, parse_market, parse_book,
                                quotes, state)
from app.adapters.kalshi_stream import (BookReconstructor, MarketStream, RecoveryRequired,
                                       RuntimeSigner, encode, sanitize)
from app.models.core import BookSync, Depth, MarketState, ReceiptFreshness, SourceTimeProgress

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def market(mid='M'):
    data = {'ticker': mid, 'event_ticker': 'E', 'title': 'Team wins', 'status': 'active'}
    return parse_market(Response(json.dumps({'market': data}), 'fixture', NOW), data, 'E', 'KXNFLGAME')


def frame(seq, kind='orderbook_snapshot', mid='M', sid=7, **fields):
    data = {'market_ticker': mid, 'market_id': 'uuid-' + mid}
    if kind == 'orderbook_snapshot':
        data.update(yes_dollars_fp=[['0.4001', '3.25']], no_dollars_fp=[['0.5002', '8.75']])
    else:
        data.update(side='yes', price_dollars='0.4001', delta_fp='0.25')
    data.update(fields)
    return encode({'type': kind, 'sid': sid, 'seq': seq, 'msg': data})


def ack(request=1, sid=7):
    return json.dumps({'id': request, 'type': 'subscribed', 'msg': {'channel': 'orderbook_delta', 'sid': sid}})


def engine(markets=None):
    e = BookReconstructor(markets or [market()])
    e.begin(1)
    e.feed(ack(), 1, NOW)
    return e


class ParsingTests(unittest.TestCase):
    def test_decimal_native_and_complement_precision(self):
        r = Response('{"orderbook_fp":{"yes_dollars":[[0.4000000000000000000000000001,3.25]],"no_dollars":[["0.59","2.50"]]}}', 'fixture', NOW)
        b = parse_book(r, market())
        self.assertEqual(b.outcomes[0].bids.levels[0].price.value, Decimal('0.4000000000000000000000000001'))
        self.assertEqual(b.outcomes[0].bids.levels[0].quantity.value, Decimal('3.25'))
        self.assertIsNone(b.outcomes[0].asks)
        with localcontext() as ctx:
            ctx.prec = 5
            q = quotes(b)
        self.assertEqual(q[1].ask.price.value, Decimal('0.5999999999999999999999999999'))
        self.assertEqual(q[0].ask.quantity.value, Decimal('2.50'))
        self.assertIn('ask=1-no-bid', q[0].raw.source)
        self.assertIsNone(b.raw.exchange_at)
        self.assertEqual(b.state, MarketState.UNKNOWN)
        self.assertEqual(b.outcomes[0].bids.depth, Depth.PARTIAL)

    def test_missing_empty_and_depth(self):
        b = parse_book(Response('{"orderbook_fp":{"yes_dollars":[]}}','fixture',NOW),market())
        self.assertEqual(b.outcomes[0].bids.levels, ())
        self.assertIsNone(b.outcomes[1].bids)
        self.assertEqual(b.sync, BookSync.UNSYNCHRONIZED)
        b = parse_book(Response('{"orderbook_fp":{"yes_dollars":[],"no_dollars":[]}}','fixture',NOW),market(),depth=0)
        self.assertEqual(b.sync, BookSync.SYNCHRONIZED)
        self.assertEqual(b.outcomes[0].bids.depth, Depth.FULL)

    def test_invalid_values_fail(self):
        for body in ('{"orderbook":{}}', '{"orderbook_fp":{"yes_dollars":[[".2","-1"]]}}',
                     '{"orderbook_fp":{"yes_dollars":[[".2","1"],[".2","2"]]}}',
                     '{"orderbook_fp":{"yes_dollars":[["1.2","1"]]}}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_book(Response(body,'fixture',NOW),market())
        with self.assertRaises(ValueError):
            decode('{"x":NaN}')

    def test_states_and_market_identity(self):
        self.assertEqual(state('inactive'), MarketState.SUSPENDED)
        self.assertEqual(state('finalized'), MarketState.SETTLED)
        self.assertEqual(state('surprise'), MarketState.UNKNOWN)
        self.assertEqual([o.native_id for o in market().outcomes], ['yes','no'])
        with self.assertRaises(ValueError):
            parse_market(Response('{}','fixture',NOW),{'event_ticker':'OTHER'},'E','KXNFLGAME')


class ReconstructionTests(unittest.TestCase):
    def test_signed_delta_and_level_removal(self):
        e = engine()
        e.feed(frame(2),1,NOW)
        b = e.feed(frame(3,'orderbook_delta',delta_fp='-3.25'),1,NOW)
        self.assertEqual(b.outcomes[0].bids.levels, ())
        b = e.feed(frame(4,'orderbook_delta',delta_fp='0.01'),1,NOW)
        self.assertEqual(b.outcomes[0].bids.levels[0].quantity.value,Decimal('.01'))

    def test_shared_sid_sequence_across_markets_and_control(self):
        e = engine([market('A'), market('B')])
        e.feed(frame(10,mid='A'),1,NOW)
        e.feed(frame(11,mid='B'),1,NOW)
        e.feed('{"type":"ok","sid":7,"seq":12,"msg":{}}',1,NOW)
        b = e.feed(frame(13,'orderbook_delta',mid='A'),1,NOW)
        self.assertEqual(b.sequence,'13')
        self.assertIsNone(e.feed(frame(987,mid='B',sid=9),1,NOW))
        self.assertEqual(e.seq,13)

    def test_gap_duplicate_regression_invalidates_entire_sid(self):
        for seq in (1,2,4):
            e = engine([market('A'),market('B')])
            e.feed(frame(1,mid='A'),1,NOW)
            e.feed(frame(2,mid='B'),1,NOW)
            with self.assertRaises(RecoveryRequired):
                e.feed(frame(seq,'orderbook_delta',mid='A'),1,NOW)
            self.assertTrue(all(b.sync == BookSync.UNSYNCHRONIZED for b in e.last.values()))
            self.assertEqual(e.sides,{})

    def test_missing_initial_image_and_negative_quantity(self):
        e = engine()
        with self.assertRaises(RecoveryRequired):
            e.feed(frame(1,'orderbook_delta'),1,NOW)
        e = engine()
        e.feed(frame(1),1,NOW)
        with self.assertRaises(RecoveryRequired):
            e.feed(frame(2,'orderbook_delta',delta_fp='-99'),1,NOW)

    def test_omitted_ws_sides_documented_empty_null_invalid(self):
        e = engine()
        b = e.feed('{"type":"orderbook_snapshot","sid":7,"seq":1,"msg":{"market_ticker":"M","market_id":"uuid-M"}}',1,NOW)
        self.assertEqual(b.outcomes[0].bids.levels,())
        self.assertEqual(b.sync, BookSync.SYNCHRONIZED)
        with self.assertRaises(RecoveryRequired):
            e.feed(frame(2,yes_dollars_fp=None),1,NOW)

    def test_reconnect_rejects_old_generation_and_old_sid(self):
        e = engine()
        e.feed(frame(1),1,NOW)
        e.begin(2)
        self.assertIsNone(e.feed(frame(2,'orderbook_delta'),1,NOW))
        self.assertIsNone(e.feed(ack(),2,NOW))
        e.feed(ack(2,8),2,NOW)
        self.assertIsNone(e.feed(frame(2,'orderbook_delta'),2,NOW))
        b = e.feed(frame(1,sid=8),2,NOW)
        self.assertEqual(b.outcomes[0].bids.levels[0].quantity.value,Decimal('3.25'))

    def test_timestamps_receipt_and_repeated_after_reconnect(self):
        e = engine()
        b = e.feed(frame(1),1,NOW)
        self.assertIsNone(b.raw.exchange_at)
        e.feed(frame(2,'orderbook_delta',ts_ms=1700000000123),1,NOW)
        e.begin(2); e.feed(ack(2,8),2,NOW)
        b = e.feed(frame(1,sid=8),2,NOW)
        self.assertEqual(b.source_time_progress,SourceTimeProgress.MISSING)
        b = e.feed(frame(2,'orderbook_delta',sid=8,ts_ms=1700000000123),2,NOW)
        self.assertEqual(b.source_time_progress,SourceTimeProgress.REPEATED)
        self.assertEqual(b.sync,BookSync.SYNCHRONIZED)
        self.assertGreater(b.raw.source_age_at_receipt,timedelta(days=100))
        b = e.feed(frame(3,'orderbook_delta',sid=8,ts_ms=1699999999000),2,NOW)
        self.assertEqual(b.source_time_progress,SourceTimeProgress.REGRESSED)

    def test_sanitization_and_original_timestamp_precision(self):
        e = engine(); e.feed(frame(1),1,NOW)
        b=e.feed(frame(2,'orderbook_delta',client_order_id='PRIVATE',subaccount=42,
                       ts='2026-09-12T00:00:00.123456789Z'),1,NOW)
        self.assertNotIn('PRIVATE',b.raw.json_text)
        self.assertNotIn('subaccount',b.raw.json_text)
        self.assertIn('.123456789Z',b.raw.json_text)
        self.assertEqual(decode(encode({'x':Decimal('0.12345678901234567890123456789')}))['x'],Decimal('0.12345678901234567890123456789'))

    def test_legacy_clock_preserves_submicrosecond_ordering(self):
        e=engine(); e.feed(frame(1),1,NOW)
        e.feed(frame(2,'orderbook_delta',ts='2026-09-12T00:00:00.123456001Z'),1,NOW)
        b=e.feed(frame(3,'orderbook_delta',ts='2026-09-12T00:00:00.123456002Z'),1,NOW)
        self.assertEqual(b.source_time_progress,SourceTimeProgress.ADVANCED)
        with localcontext() as ctx:
            ctx.prec=5
            b=e.feed(frame(4,'orderbook_delta',ts_ms=1789177000123),1,NOW)
        self.assertEqual(b.raw.exchange_at.microsecond,123000)

    def test_uuid_and_malformed_frame_invalidate(self):
        for body in (frame(2,'orderbook_delta',market_id='wrong'), '{bad', frame(2,'orderbook_delta',side='other'),
                     frame(2,'orderbook_delta',ts=123), '{"type":"orderbook_delta","sid":7,"seq":2,"msg":[]}'):
            e=engine(); e.feed(frame(1),1,NOW)
            with self.assertRaises(RecoveryRequired):
                e.feed(body,1,NOW)
            self.assertEqual(e.last['M'].sync,BookSync.UNSYNCHRONIZED)

    def test_signer_matches_rsa_pss_contract(self):
        from cryptography.hazmat.primitives.asymmetric import rsa,padding
        from cryptography.hazmat.primitives import serialization,hashes
        import base64
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        signer=RuntimeSigner('synthetic-key',pem)
        headers=signer.headers(123)
        key.public_key().verify(base64.b64decode(headers['KALSHI-ACCESS-SIGNATURE']),b'123GET/trade-api/ws/v2',
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())
        self.assertNotIn(pem,repr(signer))


async def no_sleep(_):
    pass


class Socket:
    def __init__(self, frames):
        self.frames=list(frames); self.closed=False; self.commands=[]
    async def send(self, body):
        self.commands.append(json.loads(body))
    async def recv(self):
        if self.frames:
            return self.frames.pop(0)
        await asyncio.Future()
    async def close(self):
        self.closed=True


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_gap_recovery_and_cleanup(self):
        sockets=[Socket([ack(),frame(1),frame(3,'orderbook_delta')]),
                 Socket([ack(2,8),frame(1,sid=8),frame(2,'orderbook_delta',sid=8)])]
        available=iter(sockets)
        async def factory(): return next(available)
        stream=MarketStream([market()],factory,max_messages=6,sleep=no_sleep)
        observations=[b async for b in stream.run()]
        self.assertTrue(any(b.sync==BookSync.UNSYNCHRONIZED for b in observations))
        self.assertEqual(len([b for b in observations if b.sync==BookSync.SYNCHRONIZED]),3)
        self.assertTrue(all(s.closed for s in sockets))
        self.assertEqual(sockets[1].commands[0]['id'],2)
        self.assertEqual(stream.engine.last['M'].sync,BookSync.UNSYNCHRONIZED)

    async def test_timed_reconnect_on_quiet_subscription(self):
        sockets=[Socket([ack(),frame(1)]),Socket([ack(2,8),frame(1,sid=8)])]
        available=iter(sockets)
        async def factory(): return next(available)
        stream=MarketStream([market()],factory,duration=1.3,reconnect_after_seconds=.01,
                            max_connections=2,max_messages=4,sleep=no_sleep)
        _=[b async for b in stream.run()]
        self.assertEqual(stream.engine.generation,2)
        self.assertTrue(all(s.closed for s in sockets))
        self.assertIn('deliberate_timed_disconnect',[d['event'] for d in stream.diagnostics])

    async def test_cancel_pending_receive(self):
        s=Socket([])
        async def factory(): return s
        stream=MarketStream([market()],factory)
        it=stream.run()
        task=asyncio.create_task(anext(it))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(s.closed)
        self.assertTrue(stream.closed)

    async def test_early_consumer_close(self):
        s=Socket([ack(),frame(1)])
        async def factory(): return s
        stream=MarketStream([market()],factory)
        async with aclosing(stream.run()) as updates:
            await anext(updates)
        self.assertTrue(s.closed)
        self.assertEqual(stream.engine.last['M'].sync,BookSync.UNSYNCHRONIZED)

    async def test_quiet_book_stale_receipt_socket_connected(self):
        s=Socket([ack(),frame(1)])
        async def factory(): return s
        stream=MarketStream([market()],factory,stale_seconds=.01,duration=.7,max_connections=1)
        updates=stream.run()
        first=await anext(updates)
        stale=await anext(updates)
        self.assertEqual(stale.receipt_freshness,ReceiptFreshness.STALE)
        self.assertEqual(stale.raw.received_at,first.raw.received_at)
        self.assertEqual(stale.sync,BookSync.SYNCHRONIZED)
        self.assertEqual(stream.transport_health,'connected')
        await updates.aclose()

    async def test_finite_connection_failure_and_snapshot_timeout(self):
        attempts=[]
        async def fail():
            attempts.append(1); raise ConnectionError('private error')
        stream=MarketStream([market()],fail,max_connections=2,sleep=no_sleep)
        self.assertEqual([b async for b in stream.run()],[])
        self.assertEqual(len(attempts),2)
        self.assertNotIn('private',str(stream.diagnostics))
        s=Socket([ack()])
        async def factory(): return s
        stream=MarketStream([market()],factory,duration=.7,snapshot_timeout=.01,max_connections=1)
        self.assertEqual([b async for b in stream.run()],[])
        self.assertTrue(s.closed)


class RESTTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_capture_replay_contract_offline(self):
        root=Path('evidence/slice-4/public-20260912')
        report=json.loads((root/'report.json').read_text())
        records=iter(report['responses'])
        def handler(request):
            record=next(records)
            self.assertEqual(str(request.url),record['source'])
            return httpx.Response(200,text=(root/record['file']).read_text())
        adapter=KalshiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            series=('KXNFLGAME',),max_pages=1,page_size=5,now=lambda:NOW,sleep=no_sleep)
        async with adapter:
            events=await adapter.discover_events()
            self.assertTrue(all(e.scheduled_start>NOW for e in events))
            markets=await adapter.discover_markets(events[0].raw.ref.event_id)
            rules=await adapter.get_market_rules(markets[0].raw.ref.market_id)
            book=await adapter.get_snapshot(markets[0].raw.ref.market_id)
            fees=await adapter.get_fee_metadata(events[0].raw.ref.event_id)
            self.assertTrue(rules.rules_text)
            self.assertEqual(book.outcomes[0].bids.depth,Depth.PARTIAL)
            self.assertIsNone(fees['effective_fee'])
            self.assertTrue(any(adapter.discovery_truncated.values()))
        self.assertTrue(adapter.client.is_closed)

    async def test_adapter_stream_interface_and_close(self):
        s=Socket([ack(),frame(1)])
        async def factory(): return s
        a=KalshiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(500))),
                       stream_factory=factory,stream_options={'max_messages':2})
        a.markets={'M':market()}
        async with a:
            results=[b async for b in a.stream_markets(('M',))]
            self.assertEqual(results[0].sync,BookSync.SYNCHRONIZED)
            self.assertEqual(results[-1].sync,BookSync.UNSYNCHRONIZED)
            self.assertEqual(a.streams,set())
            with self.assertRaises(ValueError):
                _=[b async for b in a.stream_markets('M')]
        self.assertTrue(s.closed)

    async def test_successful_retry_and_market_page_cursor(self):
        calls=[]
        def handler(request):
            calls.append(str(request.url))
            if len(calls)==1: return httpx.Response(429)
            second=bool(request.url.params.get('cursor'))
            return httpx.Response(200,json={'markets':[{'ticker':'B' if second else 'A'}],
                                          'cursor':'' if second else 'next'})
        a=KalshiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),sleep=no_sleep)
        async with a:
            pages=[rows async for _,rows in a._pages('/markets','markets',{'event_ticker':'E'})]
        self.assertEqual([r[0]['ticker'] for r in pages],['A','B'])
        self.assertEqual(a.requests,3)
        self.assertIn('cursor=next',calls[-1])

    async def test_retry_budget_and_no_nonread_requests(self):
        calls=[]
        def handler(request):
            calls.append(request.method)
            return httpx.Response(429)
        a=KalshiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),retries=3,max_requests=2,sleep=no_sleep)
        async with a:
            with self.assertRaises(RuntimeError): await a._get('/series/KXNFLGAME')
        self.assertEqual(calls,['GET','GET'])

    async def test_pagination_cycle_and_truncation(self):
        def handler(request): return httpx.Response(200,json={'events':[],'cursor':'same'})
        a=KalshiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),sleep=no_sleep,max_pages=3)
        async with a:
            with self.assertRaises(ValueError):
                _=[page async for page in a._pages('/events','events',{})]
        self.assertEqual(a.requests,2)

    async def test_missing_or_ambiguous_schedule_excluded(self):
        def handler(request):
            if '/series/' in request.url.path:
                return httpx.Response(200,json={'series':{'ticker':'KXNFLGAME','category':'Sports'}})
            return httpx.Response(200,json={'events':[{'event_ticker':'E','series_ticker':'KXNFLGAME','title':'game',
                'expected_expiration_time':'2099-01-01T00:00:00Z'}],'cursor':'','milestones':[]})
        a=KalshiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),series=('KXNFLGAME',),sleep=no_sleep)
        async with a:
            self.assertEqual(await a.discover_events(),())
        self.assertIsNone(a.schedule_evidence['E']['scheduled_start'])


if __name__=='__main__': unittest.main()
