"""Retained selected metadata replay plus explicit unknown/conflict controls.

This checks local matching and exact arithmetic, not ordinary current coverage.
"""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.comparison.native_scoring_scope import attach, resolve, registry, validate_registry
from app.dashboard.comparison_board import entries, gross_comparison
from app.dashboard.current_contract import snapshot_inputs
from app.storage.comparison_board import ReadContext
from app.storage.store import stamp


FIXTURE = Path(__file__).parent / 'fixtures/current-hou-jac-metadata-retained.json'
AT = '2026-10-17T15:33:23.070203+00:00'


def retained():
    return json.loads(FIXTURE.read_text())['records']


def selected(records=None, side='yes'):
    return next(row for row in (retained() if records is None else records)
        if row['quote']['venue'] == 'kalshi' and row['quote']['source']['native_side'] == side)


class MatchingMetadata(TestCase):
    def context(self, records=None):
        return ReadContext(SimpleNamespace(db=None), at=AT,
            frame=dict(epoch='authored-matching-test', revision='retained-fixture',
                records=retained() if records is None else records))

    def test_selected_review_evidence_is_retained_and_verified(self):
        review = validate_registry(registry())
        self.assertEqual(review['targets'][0]['bindings'][0]['native_key'], selected()['comparison_source_metadata']['native_key'])
        row = selected(); before = deepcopy(row)
        value = attach(row, at=AT)
        self.assertEqual(value['comparison_scope'], dict(overtime='included'))
        self.assertEqual(value['comparison_source_metadata']['scoring_scope']['status'], 'supported')
        self.assertTrue(any(fact['basis'] == 'source_type_rule'
            for fact in value['comparison_source_metadata']['scoring_scope']['evidence']))
        self.assertEqual(value['quote'], before['quote'])
        self.assertEqual(value['selection'], before['selection'])
        self.assertEqual(value['event'], before['event'])
        self.assertEqual(row, before)
        self.assertEqual(attach(value, at=AT), value)

    def test_changed_retained_evidence_is_rejected_after_a_valid_read(self):
        from app.comparison import native_scoring_scope as scope
        rules = scope.source_rules()
        for name in ('evidence', 'pointer'):
            changed = deepcopy(rules)
            own = next(r for r in changed if r['provider'] == 'kalshi' and r['native_type'] == 'KXNFLGAME')
            own.update(overtime='unknown', evidence_available=False)
            with self.subTest(part=name), patch.object(scope,'source_rules',return_value=changed):
                self.assertEqual(resolve(selected(), at=AT)['reason'], 'scope_rules_evidence_unavailable')
        self.assertEqual(resolve(selected(), at=AT)['status'], 'supported')

    def test_existing_sql_rows_match_jac_yes_to_us_short_without_recollection(self):
        records = retained(); before = deepcopy(records)
        with patch('socket.socket.connect', side_effect=AssertionError('offline matching only')):
            bundle = self.context(records).observation_bundles()[0]
        state = bundle['state_inputs']; values = entries(state)
        event, group, quote = next(item for item in values if item[2]['venue'] == 'kalshi'
            and item[2]['source']['native_side'] == 'yes')
        short = next(item[2] for item in values if item[2]['source']['native_side'] == 'Short')
        self.assertEqual(quote['binding']['selection']['participant'], 'NFL:JAX')
        self.assertEqual(short['binding']['selection']['participant'], 'NFL:JAX')
        self.assertEqual(quote['binding']['selection']['predicate'], 'win')
        self.assertEqual(short['binding']['selection']['predicate'], 'win')
        self.assertEqual(short['source']['native_outcome_id'], '2397287')
        self.assertEqual(quote['native_contract']['scope']['overtime'], 'included')
        self.assertEqual(quote['native_contract']['scope_evidence']['status'], 'supported')
        comparison = gross_comparison(quote, group, event, state, stamp(AT))
        self.assertTrue(comparison['available'])
        self.assertEqual(comparison['comparison_venue'], 'polymarket_us')
        self.assertEqual(comparison['inputs'][1]['native_side'], 'Short')
        oracle = (Fraction(short['original']['value']) - Fraction(quote['original']['value'])) * 100
        self.assertEqual(Fraction(int(comparison['exact']['numerator']), int(comparison['exact']['denominator'])), oracle)
        self.assertEqual(comparison['display_status'], 'current')
        self.assertEqual(records, before)
        for _, _, q in values:
            original = next(r['quote'] for r in records if r['quote']['source'] == q['source'])
            self.assertEqual(q['original'], original['original'])
            self.assertEqual(q['times'], original['times'])
        snapshot_inputs(state)

    def test_no_remains_not_win_and_review_does_not_widen_other_outcomes(self):
        row = selected(side='no'); value = attach(row, at=AT)
        self.assertEqual(value['selection']['predicate'], 'not_win')
        self.assertEqual(value['comparison_scope'], dict(overtime='included'))
        self.assertEqual(value['comparison_source_metadata']['scoring_scope']['reason'], 'selected_scoring_scope_supported')
        other = selected(); other['quote']['source']['native_market_id'] = 'KXNFLGAME-26OCT18HOUJAC-HOU'
        self.assertEqual(attach(other, at=AT)['comparison_scope'], dict(overtime='unknown'))
        state = self.context().observation_bundles()[0]['state_inputs']
        event, group, no = next(item for item in entries(state) if item[2]['venue'] == 'kalshi'
            and item[2]['source']['native_side'] == 'no')
        self.assertEqual(no['binding']['selection']['predicate'], 'not_win')
        self.assertFalse(gross_comparison(no, group, event, state, stamp(AT))['available'])

    def test_each_native_market_can_supply_its_own_literal_scoring_fact(self):
        row = selected(side='no')
        row['comparison_source_metadata']['combined_native_binding']['original_terms']['rules_secondary'] += ' Overtime is included if played.'
        row['comparison_source_metadata']['original_wording']['rules_secondary'] += ' Overtime is included if played.'
        row['comparison_source_metadata']['rules_secondary'] += ' Overtime is included if played.'
        value = attach(row, at=AT)
        self.assertEqual(value['comparison_scope'], dict(overtime='included'))
        self.assertEqual(value['selection']['predicate'], 'not_win')
        self.assertTrue(all(fact['basis'] != 'source_type_rule'
            for fact in value['comparison_source_metadata']['scoring_scope']['evidence']))
        for row in retained():
            if row['quote']['venue'] == 'polymarket_us':
                self.assertEqual(attach(row, at=AT)['comparison_scope'], dict(overtime='included'))

    def test_changed_terms_or_selected_identity_withhold_exact_review(self):
        for field in ('terms', 'wording', 'rules_copy', 'participant', 'series', 'native_key', 'schedule'):
            with self.subTest(field=field):
                row = selected()
                if field == 'terms':
                    row['comparison_source_metadata']['combined_native_binding']['original_terms']['rules_secondary'] += ' Authored changed terms.'
                elif field == 'wording':
                    row['comparison_source_metadata']['original_wording']['rules_secondary'] += ' Authored changed terms.'
                elif field == 'rules_copy':
                    row['comparison_source_metadata']['rules_secondary'] += ' Authored changed terms.'
                elif field == 'participant':
                    row['selection']['participant'] = 'NFL:HOU'
                elif field == 'series':
                    row['comparison_source_metadata']['series_id'] = 'OTHER-SERIES'
                elif field == 'native_key':
                    row['comparison_source_metadata']['native_key'][-1] = 'no'
                else:
                    row['event']['scheduled_start'] = '2026-10-19T13:30:00+00:00'
                audit = resolve(row, at=AT)
                self.assertEqual(audit['status'], 'contradictory')
                self.assertEqual(audit['overtime'], 'unknown')
                self.assertIn(audit['missing_fields'], ([], ['overtime']))
                self.assertTrue(audit['reason'].startswith('scope_rules_'))

    def test_conflicting_explicit_scope_and_retained_review_stay_unknown(self):
        row = selected(); row['comparison_scope']['overtime'] = 'excluded'
        audit = resolve(row, at=AT)
        self.assertEqual(audit['status'], 'contradictory')
        self.assertEqual(audit['overtime'], 'unknown')
        self.assertIn('scoring_overtime_facts_conflict', audit['conflicts'])
        short = next(row for row in retained() if row['quote']['source']['native_side'] == 'Short')
        short['comparison_source_metadata']['original_wording']['description'] += ' Overtime is excluded.'
        self.assertEqual(resolve(short, at=AT)['status'], 'contradictory')

    def test_game_review_clocks_do_not_gate_established_source_type_rules(self):
        with patch('app.comparison.native_scoring_scope.registry', side_effect=AssertionError('No game review')):
            self.assertEqual(resolve(selected(), at=AT)['status'], 'supported')
            self.assertEqual(resolve(selected(), at='2026-10-17T13:00:00+00:00')['status'], 'supported')
