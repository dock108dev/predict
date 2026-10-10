"""Independent offering/filter expectations; no account/provider access."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from app.comparison.coverage import CoverageLedger, SPORTS, aggregate_observation, current_rows

FIXTURE = Path(__file__).resolve().parents[1] / 'app/fixtures/comparison-coverage-v1.json'


class CoverageTests(unittest.TestCase):
    def ledger(self):
        return CoverageLedger({'kalshi':['NFL'], 'polymarket_us':['NFL'], 'novig':SPORTS, 'prophetx':SPORTS})

    def test_authored_six_sport_reconciliation_and_filter_only_absence(self):
        fixture = json.loads(FIXTURE.read_text())
        ledger = self.ledger()
        for row in fixture['observations']:
            ledger.observe(**row)
        before = deepcopy(ledger.observations)
        result = ledger.snapshot(fixture['inventory'], sports=['NBA'])
        self.assertEqual(result['totals'], dict(admitted_quotes=20,displayed_quotes=4,filtered_quotes=16))
        cells = {(c['sport'],c['venue']): c for c in result['cells']}
        self.assertEqual(len(cells),30)
        self.assertFalse(cells['NBA','kalshi']['configured'])
        self.assertTrue(cells['NFL','kalshi']['configured'])
        self.assertFalse(cells['NFL','kalshi']['checked'])
        self.assertEqual(cells['NHL','novig']['counts']['unresolved_mapping_quotes'],1)
        self.assertEqual(cells['NHL','novig']['display_reason'],'filtered_out')
        self.assertEqual(cells['NCAAB','novig']['status'],'no_offerings_returned')
        self.assertIsNone(cells['NCAAB','novig']['counts']['rejected_quotes'])
        self.assertEqual(ledger.observations,before)

    def test_failed_check_preserves_last_success_and_original_clock(self):
        ledger=self.ledger()
        ledger.observe('NBA','novig',checked_at='2026-10-08T20:00:00Z',status='offerings_returned',
            offered=dict(games=1,markets=1,quotes=2),source_clocks=['2026-10-08T19:45:00Z'])
        ledger.observe('NBA','novig',checked_at='2026-10-08T21:00:00Z',status='failed_source',reason='source_failed')
        row=next(c for c in ledger.snapshot()['cells'] if (c['sport'],c['venue'])==('NBA','novig'))
        self.assertEqual(row['status'],'failed_source')
        self.assertIsNone(row['latest']['offered']['quotes'])
        self.assertEqual(row['last_success']['source_clocks'],['2026-10-08T19:45:00Z'])
        self.assertEqual(row['last_success']['offered']['quotes'],2)
        ledger.observe('NBA','novig',checked_at='2026-10-08T22:00:00Z',status='no_offerings_returned',
            offered=dict(games=0,markets=0,quotes=0),reason='query_empty')
        self.assertEqual(ledger.observations['NBA','novig']['last_success']['offered']['quotes'],0)

    def test_rejected_unknowns_private_prose_and_duplicate_rows_refused(self):
        ledger=self.ledger()
        for kwargs in (dict(reason='provider private error'),dict(offered={'quotes':0}),dict(offered={'games':True})):
            with self.assertRaises(ValueError):
                ledger.observe('NFL','kalshi',checked_at='2026-10-08T20:00:00Z',status='rejected_payload',**kwargs)
        row=dict(id='one',sport='NFL',venue='kalshi',family='moneyline')
        with self.assertRaises(ValueError):ledger.snapshot([row,row])
        with self.assertRaises(ValueError):ledger.snapshot(sports=['invented'])

    def test_rejected_native_market_exclusions_and_query_hash_are_bounded(self):
        ledger=self.ledger()
        ledger.observe('NFL','kalshi',checked_at='2026-10-08T20:00:00Z',status='offerings_returned',
            offered=dict(games=1,markets=3),query={'series':'CONTROLLED'},completeness='partial')
        exclusions=[dict(sport='NFL',venue='kalshi',reason='mapping_unresolved')]
        row=next(c for c in ledger.snapshot(exclusions=exclusions)['cells'] if (c['sport'],c['venue'])==('NFL','kalshi'))
        self.assertEqual(row['counts']['rejected_markets'],1)
        self.assertIsNone(row['latest']['offered']['quotes'])
        self.assertEqual(row['latest']['completeness'],'partial')
        self.assertNotIn('CONTROLLED',json.dumps(row))
        self.assertEqual(len(row['latest']['query_sha256']),64)

    def test_aggregate_offerings_counts_and_book_clocks_are_independent(self):
        ledger=self.ledger()
        body=json.dumps([{'bookmakers':[{'key':'novig','last_update':'2026-10-08T19:00:00Z',
            'markets':[{'key':'h2h','outcomes':[{'name':'A'},{'name':'B'}]}]}]}]).encode()
        aggregate_observation(ledger,body,'NBA','2026-10-08T20:00:00Z',{'prophetx':'aggregate_total_line_conflict'})
        novig=ledger.observations['NBA','novig']['latest']
        self.assertEqual(novig['offered'],dict(games=1,markets=1,quotes=2))
        self.assertEqual(novig['source_clocks'],['2026-10-08T19:00:00Z'])
        self.assertEqual(ledger.observations['NBA','prophetx']['latest']['status'],'rejected_payload')
        self.assertEqual(ledger.observations['NBA','prophetx']['latest']['admission_code'],'aggregate_total_line_conflict')
        self.assertEqual(ledger.observations['NBA','pinnacle']['latest']['status'],'no_offerings_returned')
        for received in ('2026-10-08T20:00:00Z','2026-10-08T20:01:00Z'):
            ledger.observe_book('NFL','kalshi',received_at=received,source_at='2026-10-08T19:55:00Z')
        self.assertEqual(ledger.books['NFL','kalshi']['source_at'],'2026-10-08T19:55:00Z')

    def test_current_inventory_conversion_and_admin_read_never_acquire(self):
        from types import SimpleNamespace
        from app.collection.current_admin import project
        from app.collection.current_policy import DEFAULT
        index={'one':dict(event={'league':'NBA'},group={'family':'winner'},quote={
            'id':'one','venue':'novig','binding':{'verified':False}})}
        self.assertEqual(current_rows(index),[dict(id='one',sport='NBA',venue='novig',family='moneyline',mapping_verified=False)])
        # Empty store is a realistic stopped/read-only boundary. Any accidental
        # worker construction/acquisition is fatal rather than silently mocked.
        service=SimpleNamespace(store=None,workers={},states={v:dict(state='stopped') for v in ('kalshi','polymarket_us','novig','prophetx')},
            tasks={},issues=[],runtime_id='controlled',dispatch=False,cleanup_complete=True,deadline=None,
            sampled_rss=None,peak_rss=0,config=DEFAULT,recovery_reason=lambda:'controlled',coverage=self.ledger(),sink=None)
        with patch('app.collection.current_native.NativeWorker',side_effect=AssertionError('acquisition')):
            result=project(service,{})
        self.assertEqual(result['coverage']['totals']['admitted_quotes'],0)


if __name__ == '__main__':
    unittest.main()
