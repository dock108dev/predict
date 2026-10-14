"""EV01 independent exact vectors; offline disposable policy/state only."""
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.comparison.estimated_policy import (DEFAULT_POLICY, SCOPE, EstimatePolicy,
    EstimateInput, EstimateResult, buffer_usd, buffered_profit, probability_partition, load)
from app.comparison.costs import CapitalInputs, FundingComponent, DEFAULT_POLICY as LEGACY
from app.comparison.metrics import snapshot_metrics
from app.comparison.current_metrics import typed_quote, _size
from app.dashboard.current_contract import serialize, packed, validate_snapshot, stamp
from app.dashboard.current_state import CurrentStore
from tests.comparison_fixture import software_fixture
from tests.current_fixture import InjectedTestProvider


class EstimatePolicyTests(unittest.TestCase):
    def test_signed_haircuts_and_exact_fixed_allocation_change(self):
        self.assertEqual(buffer_usd('1000'), 5)
        for before, after in (('-10', '-15'), ('5', '0'), ('20', '15')):
            self.assertEqual(buffered_profit(before, '1000'), Fraction(after))
        self.assertEqual(buffer_usd('999.80'), Fraction('4.999'))
        result = EstimateResult(DEFAULT_POLICY, '999.80', '8.8668',
            'modeled_complete', 'modeled_size').to_dict()
        self.assertEqual(result['buffered_profit_usd'], '3.8678')
        self.assertEqual(result['unused_cash_usd'], '0.2')
        self.assertEqual(Fraction(result['buffered_return_percent']), Fraction('3.8678')/Fraction('999.80')*100)
        high = EstimateResult(replace(DEFAULT_POLICY, buffer_rate='0.01'), '999.80',
            '8.8668', 'modeled_complete', 'modeled_size').to_dict()
        self.assertEqual(Fraction(result['buffered_profit_usd'])-Fraction(high['buffered_profit_usd']), Fraction('4.999'))
        self.assertEqual(high['deployed_capital_usd'], result['deployed_capital_usd'])
        self.assertEqual(high['unused_cash_usd'], result['unused_cash_usd'])
        self.assertNotEqual(high['revision'], result['revision'])
        for invalid in (0.005, '-0.1', '1.1', 'NaN'):
            with self.assertRaises(ValueError):buffer_usd('1000', invalid)

    def test_single_and_pair_fee_inclusive_funding_and_collateral(self):
        component = lambda id, amount, kind: FundingComponent(id, amount, kind, 'entry')
        single = CapitalInputs((component('stake', '950', 'acquisition'),
            component('entry', '10', 'entry_fee'), component('collateral', '40', 'refundable_hold')), '1000')
        self.assertEqual(single.deployed_usd, '1000')
        self.assertEqual(single.reasons, ())
        # Approved pair: floor((1000-10)/(.24+.74)) = 1010 contracts.
        pair = CapitalInputs((component('a', '242.40', 'acquisition'),
            component('b', '747.40', 'acquisition'), component('fees', '10', 'entry_fee')), '1000')
        self.assertEqual(pair.deployed_usd, '999.80')
        self.assertEqual(Fraction(pair.basis()['residual_ceiling_usd']), Fraction('0.20'))
        over = CapitalInputs(pair.components+(component('independent hold', '0.21', 'refundable_hold'),), '1000')
        self.assertEqual(over.reasons, ('comparison_capital_ceiling_exceeded',))
        with self.assertRaisesRegex(ValueError, 'more than once'):
            CapitalInputs(pair.components+(pair.components[0],), '1000')
        self.assertEqual(LEGACY.ceiling_usd, '100')
        self.assertEqual(LEGACY.version, 'comparison-cost-policy-1')

    def test_existing_size_engine_funds_independent_collateral(self):
        raw = software_fixture(); event = raw['events'][0]; group = event['groups'][0]
        outcome = group['outcomes'][0]; q = outcome['quotes']['kalshi']; at = stamp(raw['clock_at'])
        bound, request, rule, quantity, kwargs, _ = typed_quote(q, raw['comparison_profiles'], at,
            event=event, group=group, outcome=outcome)
        kwargs['extra_funding'] = (FundingComponent('independent collateral', '40', 'refundable_hold', 'entry'),)
        native, _, _, costs, _, complete = _size(bound, request, rule, quantity, kwargs, at,
            '1000', DEFAULT_POLICY.cost_policy(), reserve_adverse=False)
        # 2377*.40+40=990.80; next legal quantity 2476 requires 1030.40.
        self.assertTrue(complete)
        self.assertEqual(native, '2377')
        self.assertEqual(Fraction(costs['capital']['deployed_capital_usd']), Fraction('990.8'))
        self.assertEqual(Fraction(costs['capital']['residual_ceiling_usd']), Fraction('9.2'))

    def test_scoped_disjoint_probability_partition_and_rejections(self):
        p = probability_partition('0.6', scope=SCOPE)
        self.assertEqual(p, dict(a_wins=Fraction('0.5964'), b_wins=Fraction('0.3976'),
            tie=Fraction('0.005'), terminal_noncompletion=Fraction('0.001')))
        self.assertEqual(sum(p.values()), 1)
        for weight in ('0', '1'):
            self.assertTrue(all(v >= 0 for v in probability_partition(weight, scope=SCOPE).values()))
        for index, invalid in ((0, 'NHL'), (1, 'playoffs'), (2, 'live'), (3, 'first_half'),
                               (4, 'spread'), (5, 'regulation_only')):
            scope = list(SCOPE); scope[index] = invalid
            with self.assertRaisesRegex(ValueError, 'scope'):
                probability_partition('0.6', scope=scope)
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            probability_partition('0.6', scope=SCOPE,
                exceptional_states=('tie', 'terminal_noncompletion', 'cancelled'))
        for value in ('-0.1', '1.1'):
            with self.assertRaises(ValueError):probability_partition(value, scope=SCOPE)
        with self.assertRaises(ValueError):EstimatePolicy(tie='0.7', terminal_noncompletion='0.4')

    def test_metadata_config_and_unknown_actual_never_promoted(self):
        metadata = DEFAULT_POLICY.to_dict()
        self.assertEqual(EstimatePolicy.from_dict(metadata), DEFAULT_POLICY)
        self.assertEqual(metadata['probability_defaults']['tie']['high'], '0.01')
        self.assertEqual(metadata['probability_defaults']['terminal_noncompletion']['high'], '0.005')
        self.assertFalse(metadata['probability_defaults']['measured_rate'])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'policy.json'
            self.assertEqual(load(path), DEFAULT_POLICY)
            path.write_text(json.dumps(dict(buffer_rate='0.01', capital_ceiling_usd='750', tie='0')))
            self.assertEqual(load(path).buffer_rate, '0.01')
            self.assertEqual(load(path).capital_ceiling_usd, '750')
            path.write_text('{"buffer_rate":0.01}')
            with self.assertRaises(ValueError):load(path)
        value = EstimateInput('fee', 'authored-fee-1', 'published_template', 'authored-contract', None, '0')
        result = EstimateResult(DEFAULT_POLICY, '1000', '20', 'modeled_conditional',
            'size_unverified', inputs=(value,)).to_dict()
        self.assertIsNone(result['inputs'][0]['actual_value'])
        self.assertEqual(result['inputs'][0]['modeled_value'], '0')
        self.assertEqual(result['conditioning'], 'modeled_conditional')
        self.assertEqual(EstimateResult.from_dict(result, policy=DEFAULT_POLICY).to_dict(), result)
        with self.assertRaisesRegex(ValueError, 'revision conflict'):
            EstimateResult.from_dict(dict(result, buffered_profit_usd='20'), policy=DEFAULT_POLICY)
        with self.assertRaisesRegex(ValueError, 'promote'):
            replace(value, actual_value='0')
        with self.assertRaisesRegex(ValueError, 'support'):
            EstimateResult(DEFAULT_POLICY, '1000', '20', 'modeled_complete', 'supported_size')

    def test_ordinary_defaults_rounding_policy_invalidation_and_original_clocks(self):
        raw = software_fixture(); ticks = [0]
        store = CurrentStore(InjectedTestProvider(raw), monotonic=lambda: ticks[0])
        original = store.snapshot(); metadata = original['estimate_policy']
        self.assertEqual(metadata['capital_ceiling_usd'], '1000')
        rows = snapshot_metrics(original)['rows']
        kalshi = next(r for r in rows if r['venue'] == 'kalshi')['net_ev']
        # Legal grid 1+99k at .40: 2476*.40=990.40; next grid costs 1030.
        self.assertEqual(kalshi['details']['native_quantity'], '2476')
        self.assertEqual(kalshi['basis']['capital_denominator'], '990.4')
        self.assertEqual(kalshi['details']['unused_ceiling_usd'], '9.6')
        for row in rows:
            self.assertEqual(row['net_ev']['estimate_policy'], DEFAULT_POLICY.reference())
            self.assertFalse(row['net_ev']['buffer_applied'])
        changed = replace(DEFAULT_POLICY, capital_ceiling_usd='500', buffer_rate='0.01')
        with patch('app.comparison.estimated_policy.load', return_value=changed), \
                patch('app.dashboard.current_incremental.load', return_value=changed):
            updated = store.snapshot()  # Same clock; policy alone invalidates all graphs.
        self.assertGreater(updated['state_revision'], original['state_revision'])
        self.assertEqual(updated['estimate_policy'], changed.to_dict())
        a, b = original['events'][0]['groups'][0], updated['events'][0]['groups'][0]
        self.assertEqual(a['outcomes'][0]['quotes']['kalshi']['times'], b['outcomes'][0]['quotes']['kalshi']['times'])
        self.assertEqual(b['outcomes'][0]['quotes']['kalshi']['calculations']['net_ev']['basis']['capital_denominator'], '475.6')
        validate_snapshot(original, allow_synthetic=True)
        validate_snapshot(updated, allow_synthetic=True)

    def test_legacy_snapshot_reproduces_original_head_exactly(self):
        # Captured offline from HEAD 297bc9d in a separate disposable checkout.
        snapshot = serialize(software_fixture(), allow_synthetic=True, legacy=True)
        self.assertNotIn('estimate_policy', snapshot)
        self.assertEqual(sha256(packed(snapshot)).hexdigest(), '49d4d6755a694c28809894e2c302ce62add5439718500d819e612f85f75ae75a')
        validate_snapshot(snapshot, allow_synthetic=True)
