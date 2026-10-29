from copy import deepcopy
import json
import unittest
from app.comparison.offered_scope import aggregate_inventory,native_inventory
from app.collection.current_aggregate_admission import admit_venues
from tests.test_current_aggregate import body


class OfferedScope(unittest.TestCase):
    def test_duplicate_pages_deduplicate_units_without_collapsing_lines(self):
        raw=body('NFL');payload=json.loads(raw)
        rows,_=admit_venues(raw,'NFL','2026-10-03T00:00:00Z')
        records=[r for batch in rows.values() for r in batch]
        one=aggregate_inventory(payload,'novig','spread',records)
        duplicate=aggregate_inventory(payload*2,'novig','spread',records)
        self.assertEqual(one,duplicate)
        alternate=deepcopy(payload[0]['bookmakers'][0]['markets'][1])
        for o in alternate['outcomes']:o['point']=str(float(o['point'])*2)
        payload[0]['bookmakers'][0]['markets'].append(alternate)
        changed=aggregate_inventory(payload,'novig','spread',records)
        self.assertEqual(changed['received'],4)
        self.assertEqual(changed['admitted'],2)
        self.assertEqual(changed['rejected'],2)

    def test_missing_price_is_listing_only_not_offered_zero_from_failure(self):
        payload=json.loads(body('NFL'))
        for o in payload[0]['bookmakers'][0]['markets'][0]['outcomes']:o.pop('price')
        value=aggregate_inventory(payload,'novig','moneyline',[])
        self.assertEqual(value['listing_only_markets'],1)
        self.assertEqual(value['received'],0)
        unknown=native_inventory([],[],set(),started_at='start',completed_at='end',venue='kalshi',sport='NFL',family='moneyline')
        self.assertEqual(unknown['denominator_status'],'unknown')
        self.assertIsNone(unknown['offered_price_units'])
        self.assertFalse(unknown['exhausted'])

    def test_native_reconnect_replaces_units_and_empty_image_withdraws(self):
        from app.comparison.offered_scope import NativePriceInventory
        from tests.test_current_service import native_fixture
        _,book=native_fixture()
        ledger=NativePriceInventory()
        ledger.observe('kalshi','NFL','moneyline',book,'pending')
        before=ledger.counts('kalshi','NFL','moneyline')
        self.assertGreater(before['received'],0)
        ledger.observe('kalshi','NFL','moneyline',book,'admitted')
        after=ledger.counts('kalshi','NFL','moneyline')
        self.assertEqual(after['received'],before['received'])
        self.assertEqual(after['admitted'],before['received'])
        self.assertEqual(after['pending'],0)
        empty=deepcopy(book)
        for outcome in empty['outcomes']:
            outcome['asks']=None;outcome['bids']=None
        ledger.observe('kalshi','NFL','moneyline',empty,'pending')
        ledger.observe('kalshi','NFL','moneyline',empty,'admitted')
        after=ledger.counts('kalshi','NFL','moneyline')
        self.assertEqual(after['received'],0)
        self.assertEqual(after['last_image_withdrawals'],before['received'])

    def test_batch_inventory_matches_sequential_replacement_and_counts_once(self):
        from app.comparison.coverage import CoverageLedger
        from tests.test_current_service import native_fixture
        from unittest.mock import patch
        catalog,book=native_fixture()
        sport=catalog['events'][0]['competition'];family=catalog['markets'][0]['market_type']
        sequential=CoverageLedger({'kalshi':[sport]});batched=CoverageLedger({'kalshi':[sport]})
        for ledger in (sequential,batched):
            ledger.observe(sport,'kalshi',family=family,checked_at=book['raw']['received_at'],status='offerings_returned')
        empty=deepcopy(book)
        for outcome in empty['outcomes']:outcome['asks']=None;outcome['bids']=None
        values=[book,empty,book]
        for disposition in ('pending','rejected','admitted'):
            for value in values:sequential.observe_native_price('kalshi',value,catalog,disposition)
            with patch.object(batched.native_prices,'counts',wraps=batched.native_prices.counts) as counts:
                batched.observe_native_prices('kalshi',values,catalog,disposition)
                self.assertEqual(counts.call_count,1)
            self.assertEqual(batched.native_prices.books,sequential.native_prices.books)
            self.assertEqual(batched.family_observations,sequential.family_observations)

    def test_one_bad_clock_preserves_independent_venue_inventory(self):
        from app.comparison.coverage import CoverageLedger,aggregate_observation
        payload=json.loads(body('NFL'))
        payload[0]['bookmakers'][0]['last_update']='invalid source clock'
        ledger=CoverageLedger({'novig':['NFL'],'prophetx':['NFL']})
        aggregate_observation(ledger,json.dumps(payload).encode(),'NFL','2026-10-03T00:00:00Z')
        self.assertEqual(ledger.family_observations['NFL','novig','moneyline']['latest']['completeness'],'unmeasured')
        self.assertEqual(ledger.family_observations['NFL','prophetx','moneyline']['latest']['inventory']['received'],2)

    def test_processing_failure_correlates_without_exposing_exception_text(self):
        import asyncio
        from types import SimpleNamespace
        from app.collection.current_aggregate import AggregateScheduler
        scheduler=AggregateScheduler.__new__(AggregateScheduler)
        scheduler.closed=False;scheduler.phase='database_ingress'
        scheduler.issue_context=dict(attempt_id='attempt',sport='NCAAF')
        scheduler.metrics=dict(last_received_at='2026-10-03T00:00:00Z',last_body_sha256='a'*64)
        scheduler.service=SimpleNamespace(dispatch=True,runtime_id='runtime',issue=lambda *args:None)
        scheduler.ledger=SimpleNamespace(snapshot=lambda:dict(pause=None),pause=lambda code:None,failed=None)
        scheduler.process_accounting=False;scheduler.quota_next_due_at=...
        scheduler.attended=lambda:True;scheduler.state=lambda *args:None
        async def fail():raise RuntimeError('PRIVATE-provider-url-and-credential')
        scheduler.step=fail
        with self.assertLogs('app.collection.current_aggregate',level='ERROR') as logs:
            asyncio.run(scheduler.run())
        self.assertNotIn('PRIVATE',str(logs.output)+str(scheduler.metrics))
        diagnostic=scheduler.metrics['last_processing_failure']
        self.assertEqual(diagnostic['phase'],'database_ingress')
        self.assertEqual(diagnostic['attempt_id'],'attempt')
        self.assertEqual(diagnostic['receipt_sha256'],'a'*64)
