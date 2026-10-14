"""EV04 authored interface vectors; no live fee/payout qualification."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from app.comparison.adapters import adapt
from app.comparison.costs import CostRegistry, FundingComponent
from app.comparison.domain import ExactNumber
from app.comparison.estimated_templates import fee_provider, payout_provider
from app.comparison.event_links import EventLinks, digest, instant
from app.comparison.payouts import CompletionContext, PayoutProfile, bind_profile
from app.comparison.shared_templates import ProfilePool, resolve, validate
from tests.test_comparison_net_costs import setup_case


def contract(native, period='full_game', wording='Authored rule'):
    value = dict(version='predict-native-contract-1',
        source=dict(provider=native[0], native_event_id=native[1], native_market_id=native[2],
                    native_outcome_id=native[3], native_side=native[4]),
        predicate=dict(participant='authored-team', predicate='not_win', signed_line=None),
        wording=dict(rule_note=wording), result_policy='authored-rule-1',
        scope=dict(period=period, overtime='included'), material_sha256='a' * 64)
    return dict(value, id='native-contract:' + digest(value))


class EstimateTemplateTests(unittest.TestCase):
    def test_fee_engine_rounding_native_units_and_null_actuals(self):
        # Independently known one-fill quadratic fee: 100 dollar-face at .5.
        for venue, quantity, expected in [('novig', '10000', '0.75000'),
                                          ('polymarket_us', '100', '1.74'),
                                          ('kalshi', '100', '1.750000')]:
            with self.subTest(venue=venue):
                request, scenario, args = setup_case(venue, quantity)
                before = deepcopy(scenario)
                provider = fee_provider(contract(scenario['legs'][0]['native_key']), request, scenario, **args)
                value = provider.resolve(provider.scope_id('entry_fee_usd'))
                self.assertEqual(ExactNumber.parse(value.modeled_value).value, ExactNumber.parse(expected).value)
                self.assertIsNone(value.actual_value)
                self.assertEqual(value.basis, 'provisional_assumption')
                details = provider.to_dict()['payload']
                self.assertEqual(details['rule']['unit']['unit'], args['registry'].rules[0].unit.unit)
                self.assertEqual(details['rule']['terms']['rounding'], args['registry'].rules[0].terms.rounding)
                self.assertEqual(details['provider_rule_version'], request.pinned_version)
                self.assertEqual(scenario, before)

    def test_holds_and_refunds_stay_separate_from_fee_and_actual(self):
        request, scenario, args = setup_case('prophetx', '100', gross_win='200')
        args.update(extra_funding=(FundingComponent('authored-hold', '10', 'refundable_hold', 'entry'),),
                    hold_returns_usd={'win': '10', 'loss': '10', 'refund': '10'})
        p = fee_provider(contract(scenario['legs'][0]['native_key']), request, scenario, **args)
        payload = p.to_dict()['payload']
        self.assertEqual(payload['result']['states']['win']['hold_return_usd'], '10')
        self.assertEqual(p.resolve(p.scope_id('settlement_fee_usd:win')).modeled_value, '2')
        self.assertEqual(p.resolve(p.scope_id('entry_fee_usd')).modeled_value, '0')
        self.assertIsNone(payload['actual_charges'])
        self.assertIsNone(p.resolve(p.scope_id('settlement_fee_usd:win')).actual_value)

    def test_scope_unknown_and_held_cash_unknown_refuse_locally(self):
        request, scenario, args = setup_case('prophetx', '100')
        args['extra_funding'] = (FundingComponent('authored-hold', '10', 'refundable_hold', 'entry'),)
        p = fee_provider(contract(scenario['legs'][0]['native_key']), request, scenario, **args)
        self.assertIsNone(p.resolve(p.scope_id('settlement_fee_usd:win')).modeled_value)
        with self.assertRaisesRegex(ValueError, 'component scope'):
            p.resolve('some-other-instrument')
        bad = contract(['prophetx', 'e', 'm', 'sibling', 'side'])
        with self.assertRaisesRegex(ValueError, 'instrument/side'):
            fee_provider(bad, request, scenario, **args)
        with self.assertRaisesRegex(ValueError, 'standalone'):
            fee_provider(contract(scenario['legs'][0]['native_key']),
                         replace(request, account_ref='account:private'), scenario, **args)

    def test_expired_fee_cannot_emit_a_modeled_scalar(self):
        request, scenario, args = setup_case('polymarket_us', '100')
        rules = args['registry'].data
        rules['rules'][0]['expires_at'] = request.calculation_time
        args['registry'] = CostRegistry(rules)
        p = fee_provider(contract(scenario['legs'][0]['native_key']), request, scenario, **args)
        value = p.resolve(p.scope_id('entry_fee_usd'))
        self.assertIsNone(value.modeled_value)
        self.assertIsNone(value.actual_value)
        self.assertEqual(value.basis, 'unknown_actual')
        self.assertIn('fee_inputs_expired', p.to_dict()['payload']['result']['reasons'])
        self.assertEqual(p.profile()[1]['expires_at'], request.calculation_time)

    def payout(self, name='Dallas YES'):
        root = Path(__file__).resolve().parents[1] / 'app/fixtures'
        fixtures = json.loads((root / 'comparison-payouts-v1.json').read_text())
        adapters = json.loads((root / 'comparison-outcome-adapters-v1.json').read_text())
        at = fixtures['evaluation_at']
        fact = next(r['fact'] for r in adapters['rows'] if r['id'] == name)
        selection = adapt(fact, links=EventLinks.from_dict(adapters['links']), at=instant(at))
        profile = PayoutProfile.from_dict(next(r['profile'] for r in fixtures['profile_rows'] if r['selection_id'] == name))
        leg = bind_profile(selection, profile, at=instant(at), rule_revision=profile.rule_revision,
                           context=CompletionContext.from_dict(fixtures['ordinary_context']))
        return leg, at

    def test_native_no_payout_and_unknown_exception_preserve_contract_and_refunds(self):
        leg, at = self.payout('Dallas NO')
        c = contract(leg.selection.native.key)
        p = payout_provider(c, leg, at=at)
        # Native opposing NO retains its below/equal/above contract cashflows.
        for name, expected in [('below', '1'), ('equal', '1/2'), ('above', '0')]:
            value = p.resolve(p.scope_id(name))
            self.assertEqual(value.modeled_value, expected)
            self.assertIsNone(value.actual_value)
        self.assertIsNone(p.resolve(p.scope_id('noncompleted')).modeled_value)
        payload = p.to_dict()['payload']
        self.assertEqual(payload['native_key'], list(leg.selection.native.key))
        self.assertEqual(payload['native_contract'], c)
        self.assertEqual(payload['refund_fees'], leg.profile.refund_fees)
        self.assertEqual(payload['normal_condition'], leg.profile.normal_condition.to_dict())
        self.assertIsNone(payload['actual_settlement'])

    def test_lossless_shared_profiles_and_component_invalidation(self):
        leg, at = self.payout()
        c = contract(leg.selection.native.key)
        p = payout_provider(c, leg, at=at)
        key, value = p.profile()
        pool = ProfilePool(compact=True)
        self.assertTrue(pool.add(key, value))
        registry = pool.finish()
        validate(registry)
        self.assertEqual(resolve(registry, key), value)
        changed = payout_provider(contract(leg.selection.native.key, wording='Different exact wording'), leg, at=at)
        self.assertNotEqual(changed.scope_id('above'), p.scope_id('above'))
        value['payload']['refund_fees'] = 'unknown'
        self.assertEqual(p.to_dict()['payload']['refund_fees'], leg.profile.refund_fees)
        with self.assertRaisesRegex(ValueError, 'expired'):
            payout_provider(c, leg, at='2099-01-01T00:00:00Z')
        with self.assertRaisesRegex(ValueError, 'period conflict'):
            payout_provider(contract(leg.selection.native.key, period='first_half'), leg, at=at)
