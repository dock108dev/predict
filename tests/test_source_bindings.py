"""Retained real evidence accounting; isolated mutation/overlay controls."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.collection.source_bindings import (PATH, SOURCES, build_ledger, digest,
    ledger_for_snapshot, load_ledger, required_cells, validate_ledger)


class SourceBindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = load_ledger()
        cls.cells = {c['cell_id']: c for c in cls.ledger['cells']}

    def test_exact_requirement_is_63_not_sample_coverage(self):
        self.assertEqual(len(required_cells()), 63)
        self.assertEqual(self.ledger['source_cell_count'], 252)
        self.assertEqual(self.ledger['summary']['groups'], dict(full_game=18,
            first_half=12, mlb_segments=12, nhl_periods=9, championships=12))
        for cell in self.cells.values():
            self.assertEqual(set(cell['sources']), set(SOURCES))
            self.assertTrue(all(s['dimensions']['economics']['status'] == 'UNAVAILABLE'
                                for s in cell['sources'].values()))
            self.assertTrue(all(s['missing'] and s['unlocks'] for s in cell['sources'].values()))

    def test_generator_reuses_exact_originals_and_denies_network_credentials(self):
        with (patch('socket.socket.connect', side_effect=AssertionError('No provider calls')),
              patch('app.collection.venue_access.load_credentials', side_effect=AssertionError('No credentials'))):
            self.assertEqual(build_ledger(), self.ledger)

    def test_27_documented_periods_and_exact_18_external_bindings(self):
        for source in ('novig', 'prophetx'):
            period = [c['sources'][source] for c in self.cells.values()
                      if c['period'] not in ('full_game', 'season')]
            self.assertEqual(sum(bool(s['binding']['market_keys']) for s in period), 27)
            unresolved = [c for c in self.cells.values()
                          if c['sources'][source]['engineering_status'] == 'blocked_by_external_fact']
            self.assertEqual(len(unresolved), 18)
            self.assertEqual(sum(c['period'] in ('first_6', 'regulation_9') for c in unresolved), 6)
            self.assertEqual(sum(c['category'] == 'conference_champion' for c in unresolved), 6)
            self.assertEqual(sum(c['category'] == 'league_champion' for c in unresolved), 6)
            self.assertTrue(all('catalog_review' in c['sources'][source] for c in unresolved))
            self.assertFalse(any(c['sources'][source]['engineering_status'] == 'demonstrably_unsupported_by_selected_source'
                                 for c in unresolved))

    def test_selected_book_coverage_and_invalid_prices_are_independent(self):
        n = self.cells['NFL/first_half/spread']['sources']['novig']
        p = self.cells['NFL/first_half/spread']['sources']['prophetx']
        self.assertEqual(n['counts']['observations'], 2)
        self.assertFalse(p['exact_bindings'])
        self.assertEqual(p['engineering_status'], 'implemented_awaiting_real_source_evidence')
        self.assertEqual(self.cells['NFL/first_half/moneyline']['sources']['prophetx']['counts']['observations'], 2)
        bad = self.cells['MLB/full_game/spread']['sources']['novig']
        self.assertEqual(bad['counts']['observations'], 8)
        self.assertEqual(bad['counts']['invalid_prices'], 8)
        self.assertEqual(bad['dimensions']['identity']['status'], 'RESPONSE_SCOPED')
        self.assertEqual(bad['dimensions']['books']['status'], 'NON_EXECUTABLE')

    def test_latest_delivery_does_not_erase_historical_identity_or_borrow_books(self):
        k, u = (self.cells['NHL/full_game/moneyline']['sources'][s] for s in SOURCES[:2])
        self.assertEqual(k['latest_capture']['book_observations']['initial_snapshot'], 2)
        self.assertEqual(k['latest_capture']['book_observations']['price_or_quantity_change'], 52)
        self.assertFalse(u['latest_capture']['metadata']['complete'])
        self.assertEqual(u['latest_capture']['metadata']['reason'], 'native_response_byte_cap')
        self.assertEqual(u['dimensions']['identity']['status'], 'REVIEWED_RETAINED')
        self.assertEqual(u['dimensions']['books']['status'], 'METADATA_ONLY')
        self.assertFalse(u['latest_capture']['paired_books'])
        self.assertTrue(all(not r['book_sessions'] for r in u['exact_bindings']))
        cfb = self.cells['NCAAF/full_game/moneyline']['sources']['kalshi']
        self.assertEqual(cfb['counts']['markets_with_historical_books'], 1)
        self.assertTrue(all(r['market_id'].endswith('-NMSU') for r in cfb['exact_bindings'] if r['book_sessions']))

    def test_single_source_mlb_and_event_only_associations_do_not_become_reviewed_pairs(self):
        u = self.cells['MLB/full_game/moneyline']['sources']['polymarket_us']
        self.assertEqual(u['dimensions']['identity']['status'], 'SINGLE_SOURCE_LISTING')
        self.assertFalse(u['exact_bindings'])
        self.assertEqual(u['listing_evidence'][0]['market_id'], '1081085')
        k = self.cells['MLB/full_game/moneyline']['sources']['kalshi']
        self.assertFalse(k['exact_bindings'])
        self.assertEqual(len(self.cells['NFL/full_game/moneyline']['sources']['kalshi']['event_only_associations']), 7)
        self.assertEqual(len(self.cells['NHL/full_game/moneyline']['sources']['kalshi']['event_only_associations']), 1)

    def test_tamper_duplicate_scope_and_oversize_fail_closed(self):
        value = deepcopy(self.ledger); value['cells'].pop()
        value.pop('sha256'); value['sha256'] = digest(value)
        with self.assertRaisesRegex(ValueError, 'all 63'):
            validate_ledger(value)
        value = deepcopy(self.ledger); value['cells'][0]['sources']['novig']['dimensions']['books']['status'] = 'EXECUTABLE'
        with self.assertRaisesRegex(ValueError, 'hash'):
            validate_ledger(value)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'oversize.json'; path.write_bytes(b' ' * (2 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, 'byte bound'):
                load_ledger(path)

    def test_selected_session_overlay_replays_without_changing_the_saved_projection(self):
        from app.dashboard.native_reviews import historical_paths
        from app.dashboard.session_history import load
        from app.dashboard.session_projection import stable
        path = historical_paths()['184493b2-9bc6-471c-9085-2f73390c7841']
        snapshot = load(path); before = stable(snapshot)
        first = ledger_for_snapshot(snapshot)
        self.assertEqual(stable(snapshot), before)
        self.assertEqual(ledger_for_snapshot(load(path)), first)
        selected = first['selected_session']
        self.assertEqual(selected['cutoff'], snapshot['durable_cursor'])
        self.assertEqual(len(selected['cells']), 63)
        cell = next(c for c in selected['cells'] if c['cell_id'] == 'NFL/full_game/moneyline')
        self.assertEqual(cell['sources']['kalshi']['metadata_rows'], 2)
        self.assertGreater(cell['sources']['polymarket_us']['metadata_rows'], 0)
        self.assertTrue(all(s['aggregate_rows'] == 0 for s in cell['sources'].values()))
        self.assertFalse(first['collection_authorized'])
