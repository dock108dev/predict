"""Offline only: preserved Phase 0 responses and explicitly synthetic payloads."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
from app.adapters.polymarket_us import (PolymarketUSAdapter, Response, decode,
    parse_market, parse_book, parse_bbo, side_ids, state, timestamp)
from app.models.core import BookSync, Depth, EvidenceKind, MarketState

PHASE0 = Path(__file__).resolve().parents[1] / 'evidence/phase-0'
NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)
MID = '381958'

def captured(name):
    meta = next(r for r in json.loads((PHASE0/'manifest.json').read_text()) if r['file'] == name)
    return Response((PHASE0/name).read_text(), meta['source_endpoint'],
                    datetime.fromisoformat(meta['retrieved_at_utc']))

def market():
    response = captured('pmus-tb-market.json')
    return parse_market(response, decode(response.body)['market'], '74905')

def synthetic(data):
    return Response(json.dumps(data), 'synthetic://pmus-tests', NOW, EvidenceKind.SYNTHETIC)

async def no_sleep(seconds):
    await asyncio.sleep(0)

class Parsing(unittest.TestCase):
    def test_preserved_samples_and_original_provenance(self):
        m = market()
        response = captured('pmus-tb-cin-book.json')
        book = parse_book(response, decode(response.body)['marketData'], m)
        self.assertEqual([o.native_id for o in m.outcomes], ['763430', '763431'])
        self.assertEqual(len(book.outcomes[0].bids.levels), 27)
        self.assertEqual(len(book.outcomes[0].asks.levels), 24)
        self.assertEqual(book.outcomes[0].bids.levels[0].quantity.value, Decimal('77566.0300'))
        self.assertEqual(book.outcomes[0].bids.depth, Depth.UNKNOWN)
        self.assertIsNone(book.outcomes[1].asks)
        self.assertEqual(book.raw.json_text, response.body)
        self.assertIn('2026-09-11T21:53:15.642893046Z', book.raw.json_text)
        self.assertNotEqual(book.raw.exchange_at, book.raw.received_at)
        self.assertEqual(book.state, MarketState.ACTIVE)
        self.assertEqual(book.sync, BookSync.UNKNOWN)

    def test_decimal_initial_decode_low_context(self):
        body = '{"marketSlug":"aec-nfl-tb-cin-2026-09-13","bids":[{"px":{"value":0.12345678901234567890123456789,"currency":"USD"},"qty":0.12345678901234567890123456789}],"offers":[]}'
        response = Response(body, 'synthetic://precision', NOW, EvidenceKind.SYNTHETIC)
        with localcontext() as ctx:
            ctx.prec = 3
            book = parse_book(response, decode(body), market())
        self.assertEqual(book.outcomes[0].bids.levels[0].price.value, Decimal('0.12345678901234567890123456789'))
        self.assertEqual(book.outcomes[0].bids.levels[0].quantity.value, Decimal('0.12345678901234567890123456789'))

    def test_authoritative_mapping_not_array_order(self):
        data = json.loads(captured('pmus-tb-market.json').body)['market']
        data['marketSides'].reverse()
        self.assertEqual(side_ids(data)[True], '763430')
        data['marketSides'][0].pop('long')
        with self.assertRaises(ValueError):side_ids(data)
        with self.assertRaises(ValueError):side_ids({'marketSides':[{'id':'1','long':True},{'id':'2','long':True}]})

    def test_missing_empty_status_and_bbo(self):
        data = {'marketSlug':'aec-nfl-tb-cin-2026-09-13','bids':[], 'state':'NEW_STATE'}
        b = parse_book(synthetic(data), data, market())
        self.assertEqual(b.outcomes[0].bids.levels, ())
        self.assertIsNone(b.outcomes[0].asks)
        self.assertEqual(b.state, MarketState.UNKNOWN)
        data.update(bestBid={'value':'0.35','currency':'USD'}, bidDepth=12)
        q = parse_bbo(synthetic(data), data, market())
        self.assertIsNone(q.bid.quantity)  # depth count is not a contract size
        self.assertIsNone(q.ask)
        for s in ['MARKET_STATE_HALTED','MARKET_STATE_SUSPENDED']:
            self.assertEqual(state(s), MarketState.SUSPENDED)
        self.assertEqual(state('MARKET_STATE_MATCH_AND_CLOSE_AUCTION'), MarketState.UNKNOWN)
        self.assertEqual(state('MARKET_STATE_TERMINATED'), MarketState.CLOSED)
        self.assertIsNone(timestamp(None))
        with self.assertRaises(ValueError):timestamp('2026-09-11T00:00:00')

    def test_invalid_book_and_json(self):
        for body in ('[]', 'NaN', '{bad', '{"x":NaN}'):
            with self.assertRaises(ValueError):decode(body)
        for currency, qty, px in [('EUR','1','.4'),('USD','0','.4'),('USD','-1','.4'),('USD','1','1.1')]:
            data={'marketSlug':'aec-nfl-tb-cin-2026-09-13', 'bids':[{'px':{'value':px,'currency':currency},'qty':qty}]}
            with self.assertRaises(ValueError):parse_book(synthetic(data),data,market())
        with self.assertRaises(ValueError):parse_book(synthetic({}), {}, market())

class REST(unittest.IsolatedAsyncioTestCase):
    def adapter(self, handler, **kwargs):
        return PolymarketUSAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep=no_sleep, **kwargs)

    async def test_captured_full_flow_offline_and_cleanup(self):
        def handler(req):
            name='pmus-nfl-events.json' if req.url.path.endswith('/events') else 'pmus-tb-cin-book.json' if req.url.path.endswith('/book') else 'pmus-tb-market.json'
            return httpx.Response(200,text=(PHASE0/name).read_text())
        with patch('socket.socket', side_effect=AssertionError('offline tests')):
            async with self.adapter(handler, max_pages=1) as a:
                events=await a.discover_events()
                self.assertEqual(events[0].raw.ref.event_id,'74905')
                self.assertTrue(await a.discover_markets('74905'))
                self.assertEqual((await a.get_market(MID)).raw.ref.market_id,MID)
                self.assertEqual((await a.get_snapshot(MID)).state,MarketState.ACTIVE)
                self.assertIn('Overtime', (await a.get_market_rules(MID)).rules_text)
        self.assertTrue(a.client.is_closed)
        with self.assertRaises(RuntimeError):await a.get_snapshot(MID)

    async def test_pagination_filters_cap_and_duplicates(self):
        seen=[]
        def handler(req):
            seen.append(req)
            return httpx.Response(200,json={'events':[{'id':'1','title':'Synthetic','markets':[]}]})
        async with self.adapter(handler,max_pages=2,page_size=1) as a:
            self.assertEqual(len(await a.discover_events(league=None,filters={'closed':False})),1)
            self.assertTrue(a.discovery_truncated)
            self.assertEqual([r.url.params['offset'] for r in seen],['0','1'])
            self.assertEqual(seen[0].url.params['closed'],'false')
            with self.assertRaises(ValueError):await a.discover_events(filters={'bad':1})
        async with self.adapter(handler,request_cap=1,page_size=1) as a:
            with self.assertRaisesRegex(RuntimeError,'cap'):await a.discover_events()

    async def test_market_filter_pagination_and_identity(self):
        data=json.loads(captured('pmus-tb-market.json').body)['market']
        requests=[]
        def handler(req):
            requests.append(req)
            return httpx.Response(200,json={'markets':[data] if req.url.params['offset']=='0' else []})
        async with self.adapter(handler,page_size=1) as a:
            a.events['74905']=object();a.markets[MID]=market()
            result=await a.discover_markets('74905',filters={'active':True})
            self.assertEqual(len(result),1)
            self.assertEqual(requests[0].url.params['slug'],data['slug'])
            self.assertEqual(len(requests),2)

    async def test_retry_rate_limit_exhaustion_and_not_found(self):
        waits=[]
        async def sleep(s):waits.append(s)
        statuses=iter([429,503,200])
        a=self.adapter(lambda r:httpx.Response(next(statuses),headers={'Retry-After':'2'},json={'events':[]}))
        a.sleep=sleep
        async with a:await a.discover_events()
        self.assertEqual(waits,[2,2])
        async with self.adapter(lambda r:httpx.Response(429),attempts=2) as a:
            with self.assertRaisesRegex(RuntimeError,'exhaustion'):await a.discover_events()
            self.assertEqual(a.requests,2)
        async with self.adapter(lambda r:httpx.Response(429,headers={'Retry-After':'120'})) as a:
            with self.assertRaisesRegex(RuntimeError,'bounded wait'):await a.discover_events()
            self.assertEqual(a.requests,1)
        async with self.adapter(lambda r:httpx.Response(404)) as a:
            with self.assertRaises(LookupError):await a.discover_events()
            self.assertEqual(a.requests,1)

    async def test_timeout_invalid_and_cancellation(self):
        async def slow(r):await asyncio.sleep(10)
        async with self.adapter(slow,timeout=.001,attempts=2) as a:
            with self.assertRaisesRegex(RuntimeError,'exhaustion'):await a.discover_events()
            self.assertEqual(a.requests,2)
        async with self.adapter(lambda r:httpx.Response(200,text='not json')) as a:
            with self.assertRaises(ValueError):await a.discover_events()
            self.assertEqual(a.requests,1)
        async with self.adapter(slow) as a:
            task=asyncio.create_task(a.discover_events());await asyncio.sleep(0);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(a.client.is_closed)

    async def test_missing_rules_and_settlement_metadata(self):
        data=json.loads(captured('pmus-tb-market.json').body)['market'];data.pop('description')
        async with self.adapter(lambda r:httpx.Response(200,json={'market':data})) as a:
            a.markets[MID]=market()
            self.assertIsNone((await a.get_market_rules(MID)).rules_text)
            self.assertEqual((await a.get_settlement_metadata(MID)).ref.market_id,MID)
            with self.assertRaises(LookupError):await a.get_snapshot('unknown')
