"""Passive metadata retention: authentic old catalogs and authored book controls.

No source/model renewal or provider requests. Null, absent, unknown and oversized
fields remain unqualified observations. The original receipt clocks are kept.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.collection.current_sink import normalized_records, selected_market_observation
from app.dashboard.session_projection import stable
from app.storage.current_rows import prepare
from tests.test_current_occurrence import book


FIXTURE = Path(__file__).parent/'fixtures/current-colts-commanders-retained.json'
AT = '2026-10-03T14:00:00+00:00'


class SelectedMarketMetadata(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(FIXTURE.read_text())['catalogs']['kalshi']
        self.market = self.catalog['markets'][0]
        self.material = self.market['_native']

    def test_exact_retained_fields_and_metadata_receipt_survive_current_row_projection(self):
        projection = SimpleNamespace(inventory={'kalshi': self.catalog}, books={}, invalid=set())
        for market in self.catalog['markets']:
            projection.books[('kalshi', market['event_id'], market['id'])] = {'book': book('kalshi', market, AT)}
        with patch('socket.socket.connect', side_effect=AssertionError('zero provider requests')):
            rows, excluded = normalized_records(projection, {'kalshi': {'state': 'available'}}, {},
                                                dated_annotations=False, clock=AT)
        self.assertFalse(excluded)
        row = next(r for r in rows if r['quote']['source']['native_market_id'] == self.market['id'])
        actual = row['comparison_source_metadata']['selected_market_observation']
        fields = ('price_ranges', 'price_level_structure', 'notional_value_dollars')
        self.assertEqual(actual['values'], {k: self.material[k] for k in fields if k in self.material})
        self.assertEqual(actual['material_sha256'], stable(self.material))
        self.assertEqual(actual['source']['received_at'], self.market['provenance'][-1]['received_at'])
        self.assertNotEqual(actual['source']['received_at'], row['quote']['times']['received_at'])
        self.assertEqual(row['quote']['times']['source_at'], AT)
        self.assertEqual(actual['qualification'], 'unreviewed_source_metadata_only_no_execution_authority')
        prepared = prepare(row)
        self.assertEqual(prepared['contract']['comparison_source_metadata']['selected_market_observation'], actual)
        self.assertFalse(any(key in actual for key in ('minimum_quantity', 'quantity_increment', 'effective_until', 'actual_qualified')))
        actual['values']['price_ranges'][0]['step'] = 'CONTROLLED MUTATION'
        self.assertNotEqual(self.material['price_ranges'][0]['step'], 'CONTROLLED MUTATION')

    def test_absent_null_and_unknown_fields_never_receive_defaults(self):
        missing = selected_market_observation(self.market, {'unknown_grid_field': 'CONTROLLED'})
        self.assertEqual(missing['status'], 'absent')
        self.assertEqual(missing['values'], {})
        self.assertEqual(missing['present_fields'], [])
        explicit_null = selected_market_observation(self.market, {'price_ranges': None})
        self.assertEqual(explicit_null['values'], {'price_ranges': None})
        self.assertEqual(explicit_null['present_fields'], ['price_ranges'])
        self.assertNotIn('price_level_structure', explicit_null['values'])

    def test_changed_grid_updates_contract_revision_without_repricing(self):
        projection = SimpleNamespace(inventory={'kalshi': self.catalog}, books={}, invalid=set())
        for market in self.catalog['markets']:
            projection.books[('kalshi', market['event_id'], market['id'])] = {'book': book('kalshi', market, AT)}
        first, _ = normalized_records(projection, {'kalshi': {'state': 'available'}}, {},
                                      dated_annotations=False, clock=AT)
        previous = {r['_instrument']: dict(revision=r['quote']['revision'], fingerprint=r['_fingerprint'],
                                          original=deepcopy(r['quote']['original']), times=deepcopy(r['quote']['times']))
                    for r in first}
        self.material['price_ranges'][0]['step'] = '0.0050'  # Authored metadata-only change.
        changed, _ = normalized_records(projection, {'kalshi': {'state': 'available'}}, previous,
                                        dated_annotations=False, clock='2026-10-03T14:00:20+00:00')
        before = next(r for r in first if r['quote']['source']['native_market_id'] == self.market['id'])
        after = next(r for r in changed if r['_instrument'] == before['_instrument'])
        self.assertEqual(after['quote'], before['quote'])
        self.assertNotEqual(prepare(after)['revision'], prepare(before)['revision'])
        self.assertNotEqual(after['comparison_source_metadata']['selected_market_observation']['material_sha256'],
                            before['comparison_source_metadata']['selected_market_observation']['material_sha256'])

    def test_oversized_metadata_is_explicitly_excluded_without_partial_grid(self):
        material = deepcopy(self.material)
        material['price_ranges'] = [{'unreviewed': 'CONTROLLED'*2000}]
        actual = selected_market_observation(self.market, material)
        self.assertEqual(actual['status'], 'metadata_capacity_excluded')
        self.assertEqual(actual['values'], {})
        self.assertIn('price_ranges', actual['present_fields'])
        self.assertEqual(actual['material_sha256'], stable(material))


if __name__ == '__main__':
    unittest.main()
