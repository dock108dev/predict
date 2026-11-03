"""Metric-local cashflow admission and prospective source-review regressions."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
from unittest import TestCase

from app.comparison.current_dependencies import instant, profile, references
from app.comparison.calculation_availability import result_availability
from app.comparison.conditional_benchmark import basis
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.comparison.bound_finance import pairs
from app.dashboard.current_contract import serialize, quotes_of
from app.dashboard.comparison_board import age
from tests.test_sc07_finance import BoundFinancial


class PairMetricDependencies(TestCase):
    def fixture(self):
        raw=BoundFinancial().raw(complete=True)
        for o in raw['events'][0]['groups'][0]['outcomes']:
            for q in quotes_of(o):
                for kind in ('reference','probability'):
                    q['comparison_input_refs']['refs'][kind]=None
        state=serialize(raw,allow_synthetic=True)
        event=state['events'][0]
        event['funded_pairs']=pairs(event,state['comparison_profiles'],DEFAULT_POLICY)
        self.assertTrue(event['funded_pairs'])
        return dict(state=state),raw['clock_at']

    def test_covered_minimum_current_without_EV_probability_or_benchmark(self):
        value,at=self.fixture()
        result=age(value,at=at)['state']['events'][0]['funded_pairs'][0]
        self.assertEqual(result['freshness']['status'],'current')
        self.assertEqual(Fraction(result['financial_metrics']['buffered_complete_modeled_minimum_usd']),Fraction('4.525'))
        self.assertIsNone(result['financial_metrics']['buffered_ev_usd'])
        self.assertEqual(result['availability']['metrics']['buffered_complete_modeled_minimum_usd']['state'],'numeric_current')

    def test_required_expiry_and_changed_price_withdraw_pair(self):
        value,at=self.fixture()
        changed=deepcopy(value['state'])
        changed['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']['original']['value']='0.41'
        result=age(value,at=at,current=changed)['state']['events'][0]['funded_pairs'][0]
        self.assertIn('dependency_changed_or_removed',result['freshness']['reasons'])
        for kind in ('fee','payout','quantity','identity'):
            case=deepcopy(value);state=case['state'];q=state['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']
            old=references(q,state['comparison_profiles'])[kind]
            key,item=profile(kind,old['payload'],expires_at=at)
            state['comparison_profiles'][key]=item;q['comparison_input_refs']['refs'][kind]=key
            result=age(case,at=at)['state']['events'][0]['funded_pairs'][0]
            self.assertEqual(result['freshness']['status'],'historical',kind)
            self.assertIn(kind+'_inputs_expired',result['freshness']['reasons'])

    def test_pair_missing_cashflow_is_not_reported_as_missing_probability(self):
        result=dict(financial_metrics={},benchmark={'reason':'probability_inputs_missing'})
        availability=result_availability(result,pair=True)
        reasons=availability['metrics']['buffered_complete_modeled_minimum_usd']['reason_codes']
        self.assertIn('complete_joint_cashflows_unsupported',reasons)
        self.assertNotIn('probability_inputs_missing',reasons)


class ReviewedFeeEvidence(TestCase):
    def test_prospective_review_keeps_gap_and_expiry_and_verifies_document(self):
        for venue in ('novig','polymarket_us'):
            old=basis(venue,at=instant('2026-10-30T12:00:00Z'))
            current=basis(venue,at=instant('2026-10-31T01:00:00Z'))
            start=instant(current['reviewed_at'])
            self.assertEqual(current['supersedes'],old['version'])
            self.assertGreater(start,instant(old['review_before']))
            self.assertEqual(basis(venue,at=start-timedelta(microseconds=1)),old)
            self.assertEqual(basis(venue,at=start),current)
            self.assertEqual(current['review_before'],'2026-11-01T00:00:00Z')
            from app.comparison.conditional_benchmark import _verified
            with self.assertRaisesRegex(ValueError,'conditional_fee_evidence_invalid'):
                import json
                _verified(json.dumps(current).encode(),b'changed source terms',venue)
