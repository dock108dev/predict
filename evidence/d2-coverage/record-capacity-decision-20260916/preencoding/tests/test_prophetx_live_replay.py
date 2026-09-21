"""Offline replay of sanitized sandbox captures; no live requests."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
from pathlib import Path
import unittest
from app.adapters.prophetx import (ProphetXAdapter, Response, book, decode,
    american_probability, market_key, MarketState, BookSync)

ROOT = Path(__file__).resolve().parents[1] / 'evidence/slice-3/sandbox-qualification-20260912'
CAPTURE = ROOT / 'attempt-1/sandbox-20260912T005720Z'

def captured(name):
    metadata = json.loads((CAPTURE/'result.json').read_text())
    record = next(x for x in metadata['records'] if x['file']==name)
    return Response((CAPTURE/name).read_text(), record['source'], datetime.fromisoformat(record['received_at']))

class ReplayClient:
    async def request(self, method, path, **kwargs):
        return captured('market-002.json' if path.endswith('get_sport_events') else 'market-004.json')

class LiveReplay(unittest.IsolatedAsyncioTestCase):
    async def test_all_native_strikes_survive_template_id_reuse(self):
        a=ProphetXAdapter(ReplayClient())
        markets=await a.discover_markets('19458')
        self.assertEqual(len(markets),447)
        self.assertEqual(len({m.raw.ref.market_id for m in markets}),447)
        self.assertTrue({'19458:66:1.5','19458:66:2','19458:66:2.5'} <= set(a.markets))
        b=a.native_books['19458:219:0']
        self.assertEqual(b.state,MarketState.ACTIVE)
        self.assertEqual(b.native_windows[0][0].price,Decimal(146))
        self.assertEqual(b.native_windows[0][0].quantity.value,Decimal('91.71'))
        self.assertEqual(b.normalized_quotes[0].ask.price.value,american_probability(146).value)
        self.assertIsNone(b.normalized_quotes[0].ask.quantity)
        self.assertIsNone(b.outcomes[0].asks)
        self.assertEqual(b.sync,BookSync.UNKNOWN)
        self.assertEqual(a.markets['19458:219:0'][1].period,'full_game')
        self.assertEqual(a.markets['19458:64:0'][1].period,'first_half')

    async def test_followup_capture_retains_unsized_quotes_and_request_provenance(self):
        capture=ROOT.parent/'sandbox-followup-20260912/live/sandbox-20260912T011548Z'
        metadata=json.loads((capture/'result.json').read_text())
        record=next(x for x in metadata['records'] if x['file']=='market-004.json')
        r=Response((capture/record['file']).read_text(),record['source'],
            datetime.fromisoformat(record['received_at']))
        class CapturedClient:
            async def request(self,*args,**kwargs):return r
        a=ProphetXAdapter(CapturedClient());await a.discover_markets('19458')
        b=a.native_books['19458:219:0']
        self.assertIn('event_ids=19458',b.raw.source)
        self.assertTrue(b.normalized_quotes)
        self.assertTrue(all(q.ask.quantity is None for q in b.normalized_quotes))
        self.assertIsNone(b.raw.exchange_at)
        self.assertEqual(b.state,MarketState.ACTIVE)

    async def test_actual_pregame_eligibility_not_silently_relaxed(self):
        a=ProphetXAdapter(ReplayClient(),tournament_ids=('31',))
        events=await a.discover_events()
        self.assertEqual(len(events),32)
        event=next(x for x in events if x.raw.ref.event_id=='19458')
        self.assertEqual(event.scheduled_start,datetime(2026,9,13,17,tzinfo=timezone.utc))
        self.assertEqual(event.participants,('Carolina Panthers','Chicago Bears'))
        native=next(x for x in decode(event.raw.json_text)['data']['sport_events'] if x['event_id']==19458)
        self.assertEqual(native['status'],'not_started')

    async def test_observed_placeholders_do_not_create_quotes(self):
        a=ProphetXAdapter(ReplayClient());await a.discover_markets('19458')
        b=a.native_books['19458:64:0']
        self.assertEqual(len(b.native_windows),2)
        self.assertIsNone(b.native_windows[0][0].price)
        self.assertEqual(b.native_windows[0][0].quantity.value,0)
        self.assertEqual(b.normalized_quotes,())
        self.assertEqual(b.state,MarketState.ACTIVE)

class FocusedRepairs(unittest.TestCase):
    def test_price_conversion_independent_of_decimal_context(self):
        expected=american_probability('-164').value
        with localcontext() as context:
            context.prec=3
            self.assertEqual(american_probability('-164').value,expected)
        for invalid in ['0','99','-1','NaN']:
            with self.assertRaises(ValueError):american_probability(invalid)

    def test_identity_equal_strikes_and_distinct_events(self):
        self.assertEqual(market_key('1',{'id':2,'strike':Decimal('1.50')}),'1:2:1.5')
        self.assertNotEqual(market_key('1',{'id':2,'strike':0}),market_key('2',{'id':2,'strike':0}))
        self.assertNotEqual(market_key('1',{'id':2,'strike':None}),market_key('1',{'id':2,'strike':0}))

    def test_status_only_reopen_cannot_restore_quotes(self):
        r=captured('market-004.json')
        for status in ['active','suspended','closed','active','future_enum']:
            b=book(r,'19458',{'id':219,'strike':0,'status':status})
            self.assertEqual(b.normalized_quotes,())
            self.assertIsNone(b.native_windows)
            self.assertEqual(b.native_sync,BookSync.UNKNOWN)
            self.assertEqual(b.state,MarketState.ACTIVE if status=='active' else MarketState.UNKNOWN)

class RestReplacement(unittest.IsolatedAsyncioTestCase):
    async def test_naturally_removed_rest_prices_are_not_merged(self):
        class ChangingClient:
            calls=0
            async def request(self,*args,**kwargs):
                self.calls+=1
                if self.calls==1:return captured('market-004.json')
                p=ROOT/'verification-fixed/sandbox-20260912T010141Z'
                rec=next(x for x in json.loads((p/'result.json').read_text())['records'] if x['file']=='market-004.json')
                return Response((p/'market-004.json').read_text(),rec['source'],datetime.fromisoformat(rec['received_at']))
        a=ProphetXAdapter(ChangingClient());await a.discover_markets('19458')
        old=a.native_books['19458:219:0']
        new=await a.get_snapshot('19458:219:0')
        self.assertEqual([len(g) for g in old.native_windows],[2,3])
        self.assertEqual([len(g) for g in new.native_windows],[1,2])
        self.assertEqual(new.native_windows[0][0].price,Decimal(-265))
        self.assertEqual(new.normalized_quotes[0].ask.price,american_probability(-265))
        self.assertIsNone(new.normalized_quotes[0].ask.quantity)
