"""Retained replay plus authored mutations; never live qualification."""
from copy import deepcopy
from fractions import Fraction as F
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.comparison.current_dependencies import instant,profile
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.comparison.modeled_winner import single,END
from app.comparison.calculation_availability import result_availability


class ModeledWinner(TestCase):
    def setUp(self):
        self.raw=json.loads((Path(__file__).parent/'fixtures/novig-nflwin-retained.json').read_text())
        self.e=self.raw['event'];self.g=self.e['groups'][0]
        self.q=self.g['outcomes'][0]['quotes']['novig'];self.p=self.raw['profiles']
        self.at=instant(self.raw['captured_at'])

    def run_model(self,at=None,policy=DEFAULT_POLICY):
        return single(self.q,self.p,at=at or self.at,event=self.e,group=self.g,policy=policy)

    def test_exact_full_and_conditional_reconciliation_without_execution_claim(self):
        before=deepcopy(self.raw)
        with patch('socket.socket.connect',side_effect=AssertionError('local reads only')):
            r=self.run_model()
        self.assertEqual(self.raw,before)
        d=F(self.q['original']['value']);p=F(r['gross_decisive_benchmark']['selected_decisive_probability'])
        conditional=1000*(p*d-1)
        full=F('0.994')*conditional+F('0.005')*1000*(d/2-1)
        m=r['financial_metrics']
        self.assertEqual(F(m['conditional_net_ev_usd']),conditional)
        self.assertEqual(F(m['net_modeled_ev_usd']),full)
        self.assertEqual(F(m['buffered_ev_usd']),full-5)
        self.assertEqual(F(m['rule_adjustment_usd'])+F(m['gross_benchmark_ev_usd']),full)
        self.assertEqual(m['net_upfront_fee_usd'],'0')
        self.assertIsNone(m['complete_modeled_minimum_usd'])
        self.assertIsNone(r['states']['noncompleted']['profit_usd'])
        self.assertIn('noncompleted',r['classification']['unknown_outcomes'])
        self.assertFalse(r['classification']['is_arb']);self.assertFalse(r['funding']['actual_fill_support'])
        self.assertEqual(sum(map(F,r['probabilities'].values())),1)
        self.assertEqual(result_availability(r)['state'],'numeric_last_known')
        self.assertIn('uncalibrated',r['modeled_basis']['probability'])

    def test_positive_nonpositive_amount_and_buffer(self):
        for odds in ('1.01','4'):
            self.q['original']['value']=odds
            r=self.run_model(policy=DEFAULT_POLICY.with_ceiling('17.239'))
            self.assertEqual(F(r['deployed_capital_usd']),F('17.23'))
            self.assertEqual(F(r['buffer_usd']),F('17.23')/200)
            self.assertEqual(F(r['residual_funding_usd']),F('0.009'))
            self.assertEqual(F(r['financial_metrics']['buffered_ev_usd'])>0,odds=='4')
            self.assertFalse(r['classification']['main_positive_eligible'])  # aged originals

    def test_expired_missing_conflicting_and_unsupported_inputs(self):
        with self.assertRaisesRegex(ValueError,'expired'):self.run_model(at=instant(END))
        for mutation,reason in [
            (lambda:self.q['times'].update(source_at='2027-01-01T00:00:00Z'),'future'),
            (lambda:self.q['binding']['selection'].update(participant='wrong'),'identity'),
            (lambda:self.q['comparison_input_refs']['refs'].update(reference=None),'missing')]:
            old=deepcopy(self.q);mutation()
            with self.assertRaises(ValueError,msg=reason):self.run_model()
            self.q=old
        self.q['source']['native_side']='NO'
        self.assertIsNone(self.run_model())
        self.q['source']['native_side']='bookmaker_outcome';self.g['market']='spread'
        self.assertIsNone(self.run_model())

    def test_expired_profile_and_bound_fee_never_overridden(self):
        k=self.q['comparison_input_refs']['refs']['reference'];v=self.p[k]
        key,value=profile('reference',v['payload'],expires_at='2026-10-22T00:00:00Z')
        self.p[key]=value;self.q['comparison_input_refs']['refs']['reference']=key
        with self.assertRaisesRegex(ValueError,'reference_inputs_expired'):self.run_model()
        key,value=profile('fee',dict(unknown_required_charge=True))
        self.p[key]=value;self.q['comparison_input_refs']['refs']['fee']=key
        self.assertIsNone(self.run_model())

    def test_funded_route_and_compact_row_keep_model_disclosure(self):
        from app.comparison.estimated_ev import evaluate
        from app.dashboard.comparison_board import financial_row
        r=evaluate(self.q,self.p,at=self.at,event=self.e,group=self.g)
        self.assertTrue(r['model_available'],r.get('reasons'))
        from app.comparison.estimated_ev import compact
        row=financial_row(compact(r))
        self.assertEqual(row['modeled_basis'],r['modeled_basis'])
        self.assertIsNotNone(row['financial_metrics']['buffered_ev_usd'])

    def test_sensitivity_partition_missing_evidence_and_sign_reversal(self):
        from app.comparison.modeled_winner import scenario_ev,sensitivity
        inputs=dict(risk=F(1000),odds=F(2),conditional=F(6),buffer=F(5))
        positive=scenario_ev(**inputs,tie='0.005',void='0.001',refund=1)
        negative=scenario_ev(**inputs,tie='0.005',void='0.001',refund=0,fair_value=0)
        self.assertGreater(positive,0);self.assertLess(negative,0)
        span=sensitivity(**inputs)
        self.assertTrue(span['sign_changes']);self.assertFalse(span['calibrated_estimate_available'])
        threshold=F(span['break_even_expected_void_receipt_per_face'])
        self.assertEqual(scenario_ev(**inputs,tie='0.005',void='0.001',refund=0,fair_value=threshold),0)
        v=F(span['break_even_void_probability_zero_receipt'])
        self.assertEqual(scenario_ev(**inputs,tie='0.005',void=v,refund=0,fair_value=0),0)
        for t,v,r,f in [('0.8','0.3','1',None),('-0.1','0','1',None),('0','0','2',None),('0','0.1','0','1.1')]:
            with self.assertRaises(ValueError):scenario_ev(**inputs,tie=t,void=v,refund=r,fair_value=f)
        with self.assertRaisesRegex(ValueError,'missing'):
            scenario_ev(**inputs,tie=0,void='0.1',refund='0.5')
        # A fully refunded void has zero profit; a 50/50 mixture is permitted only
        # as an explicit scenario, not a probability inferred from missing history.
        self.assertEqual(scenario_ev(**inputs,tie=0,void=1,refund=1),-5)
        self.assertEqual(scenario_ev(**inputs,tie=0,void=1,refund='0.5',fair_value='0.25'),-255)
        self.assertEqual(scenario_ev(**inputs,tie=1,void=0,refund=1),-5)

    def test_shared_engine_reconciles_scenario_and_sensitivity_survives_compaction(self):
        from app.comparison.modeled_winner import scenario_ev
        from app.comparison.estimated_ev import compact
        from app.dashboard.comparison_board import financial_row
        r=self.run_model();m=r['financial_metrics'];b=r['modeled_basis']
        value=scenario_ev(risk=r['deployed_capital_usd'],odds=self.q['original']['value'],
            conditional=m['conditional_net_ev_usd'],buffer=r['buffer_usd'],tie='0.005',void='0.001',refund=1)
        self.assertEqual(value,F(m['buffered_ev_usd']))
        self.assertEqual(financial_row(compact(r))['modeled_basis']['sensitivity'],b['sensitivity'])
        self.assertIsNone(b['scenario_parameters']['expected_fair_value_given_nonrefund'])
        self.assertIsNone(r['states']['noncompleted']['profit_usd'])
        self.assertFalse(r['classification']['is_arb'])

    def test_current_publication_does_not_treat_effective_model_as_expired(self):
        from datetime import timedelta
        from app.dashboard.comparison_board import freshness
        from app.comparison.estimated_ev import temporal
        from app.comparison.modeled_winner import START
        at=instant(self.q['times']['received_at'])+timedelta(seconds=30)
        r=self.run_model(at=at)
        f=freshness(self.q,self.p,self.e,at,bound_financial=True)
        self.assertEqual(f['status'],'current',f)
        r['freshness']=f
        self.assertEqual(result_availability(r)['state'],'numeric_current')
        self.assertFalse(any(x is True for x in temporal(self.q,self.p,at,self.e)))
        for boundary in (instant(START)-timedelta(microseconds=1),instant(END)):
            self.assertTrue(any(x is True for x in temporal(self.q,self.p,boundary,self.e)))
            self.assertEqual(freshness(self.q,self.p,self.e,boundary,bound_financial=True)['status'],'historical')
        self.assertEqual(freshness(self.q,self.p,self.e,at+timedelta(minutes=31),bound_financial=True)['status'],'historical')

    def test_independent_original_orientation_zero_and_changed_dependency(self):
        from datetime import timedelta
        at=instant(self.q['times']['received_at'])+timedelta(seconds=30)
        for outcome in self.g['outcomes']:
            self.q=outcome['quotes']['novig']
            r=self.run_model(at=at)
            originals=r['gross_decisive_benchmark']['reference_originals']
            weights={x['selection']['participant_id']:1/F(x['decimal_odds']) for x in originals}
            p=weights[self.q['binding']['selection']['participant']]/sum(weights.values())
            self.assertEqual(F(r['financial_metrics']['conditional_net_ev_usd']),1000*(p*F(self.q['original']['value'])-1))
            old=r['dependency_revision']
            self.q['original']['value']=str(1/p)
            zero=self.run_model(at=at)
            self.assertEqual(F(zero['financial_metrics']['conditional_net_ev_usd']),0)
            self.assertEqual(F(zero['financial_metrics']['conditional_buffered_ev_usd']),-5)
            self.assertNotEqual(zero['dependency_revision'],old)
            self.assertIsNone(zero['states']['noncompleted']['profit_usd'])
            self.assertFalse(zero['classification']['is_arb'])

    def test_public_model_deadline_does_not_age_bound_or_recipe_results(self):
        from app.comparison.estimated_ev import temporal
        from app.comparison.current_dependencies import references
        from app.comparison.modeled_winner import START
        from datetime import timedelta
        before=instant(START)-timedelta(seconds=1)
        bound=references(self.q,self.p)
        bound['fee']={'expires_at':None}
        with patch('app.comparison.estimated_ev.references',return_value=bound):
            self.assertFalse(any(x is True for x in temporal(self.q,self.p,before,self.e)))
        q=deepcopy(self.q)
        q.setdefault('comparison_input_status',{}).setdefault('fee',{})['estimate_content']={'id':'authored-separate-recipe'}
        self.assertFalse(any(x is True for x in temporal(q,self.p,before,self.e)))
