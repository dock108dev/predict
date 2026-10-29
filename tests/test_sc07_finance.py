"""SC07-M2 exact authored mathematics and pending/scope regression vectors."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
from unittest import TestCase
from unittest.mock import patch

from app.comparison.calculation_availability import summary, combine, result_availability, refusal
from app.comparison.current_dependencies import profile, references, instant
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.comparison.scanner_readiness import Selection
from app.storage.scanner_readiness import scope_inventory
from app.collection.current_policy import DEFAULT, GRANT
from app.dashboard.current_contract import serialize, quotes_of
from tests.comparison_fixture import software_fixture


class Availability(TestCase):
    def test_pending_empty_and_refused_are_never_financial_zero(self):
        self.assertEqual(summary([])['outcome'],'not_evaluated')
        for code,state in [('background_estimates_pending','not_evaluated'),('quantity_inputs_missing','missing_inputs'),
                ('estimate_prior_scope_excluded','unsupported_inputs'),('calculation_failed','calculation_failed')]:
            with self.subTest(code=code):
                self.assertEqual(refusal([code])[0],state)
                r=summary([],failures=[('game',code)])
                self.assertEqual(r['counts'][state],1)
                self.assertFalse(r['evaluation_complete'])
                self.assertNotEqual(r['outcome'],'evaluated_no_positive')
        pending=summary([],failures=[('game','background_estimates_pending')])
        self.assertEqual(pending['counts']['calculation_failed'],0)
        self.assertEqual(combine([pending],games=1)['outcome'],'not_evaluated')

    def test_completeness_precedes_positive_filter_and_preserves_last_known(self):
        yes=dict(state='numeric_current',reason_codes=[],current_opportunity_eligible=True)
        pending=dict(state='not_evaluated',reason_codes=['background_estimates_pending'],current_opportunity_eligible=False)
        value=summary([('a',['kalshi'],yes),('b',['novig'],pending)])
        self.assertEqual(value['outcome'],'partial');self.assertEqual(value['positive_results'],1)
        self.assertFalse(value['evaluation_complete'])
        history=dict(yes,state='numeric_last_known',current_opportunity_eligible=False)
        self.assertEqual(summary([('a',[],history)])['outcome'],'last_known_only')
        self.assertEqual(summary([('a',[],dict(yes,current_opportunity_eligible=False))])['outcome'],'evaluated_no_positive')
        self.assertTrue(summary([('a',[],yes)])['evaluation_complete'])

    def test_unfiltered_pending_board_counts_each_original(self):
        from tests.test_current_board_reads import context,bundle
        from app.dashboard.comparison_board import response,entries
        c=context();b=bundle(c)
        result=response(b,None,DEFAULT_POLICY,view='ev',filter='positive',at=c.at)
        self.assertEqual(result['rows'],[])
        self.assertEqual(result['availability']['outcome'],'not_evaluated')
        self.assertEqual(result['availability']['pending_results'],len(entries(b['state_inputs'])))
        self.assertEqual(result['availability']['counts']['calculation_failed'],0)

    def test_all_six_core_cells_are_selected_and_predicate_support_is_separate(self):
        selected=Selection();scopes=scope_inventory(selected,dict(DEFAULT,native_sports=list(selected.leagues)),GRANT)
        self.assertEqual(len(scopes),72)
        self.assertEqual({s['league'] for s in scopes},set(selected.leagues))
        self.assertEqual({s['market'] for s in scopes},{'winner','spread','total'})
        self.assertTrue(all(s['supported'] for s in scopes))
        self.assertEqual(sum(s['configured'] for s in scopes if s['venue']=='kalshi'),18)
        unsupported=scope_inventory(Selection(leagues=('UNKNOWN',),sports=('unknown',)),DEFAULT,GRANT)
        self.assertTrue(unsupported);self.assertTrue(all(not s['supported'] for s in unsupported))


class BoundFinancial(TestCase):
    def raw(self, probability=None, complete=False):
        raw=software_fixture();event=raw['events'][0];group=event['groups'][0]
        if complete:
            for o in group['outcomes']:
                for leg in quotes_of(o):
                    payout=deepcopy(references(leg,raw['comparison_profiles'])['payout']['payload'])
                    payout['noncompleted']=dict(value='0.5',status='estimated',reason='Authored complete terminal payout')
                    key,value=profile('payout',payout);raw['comparison_profiles'][key]=value
                    leg['comparison_input_refs']['refs']['payout']=key
        q=next(q for o in group['outcomes'] for q in quotes_of(o) if q['venue']=='kalshi')
        if probability is not None:
            from app.comparison.cashflows import cashflow_inputs
            from app.comparison.current_metrics import typed_quote
            state=serialize(raw,allow_synthetic=True,funded=False)
            e=state['events'][0];g=e['groups'][0];o=g['outcomes'][0];old=o['quotes']['kalshi']
            bound,*_=typed_quote(old,state['comparison_profiles'],instant(raw['clock_at']),event=e,group=g,outcome=o)
            scenario=cashflow_inputs((bound,),('1',),at=instant(raw['clock_at']))
            probs={'completed:None:-1':str(1-F(probability)), 'completed:0:0':'0', 'completed:1:None':probability}
            if complete:probs['noncompleted']='0'
            payload=dict(version='comparison-state-probabilities-1',kind='authored_sensitivity',
                partition_revision=scenario.table.revision,coverage='complete' if complete else 'conditional',conditioning='authored_decisive_home_or_away_win',
                probabilities=probs,evidence=[dict(ref='authored:m2-probability',sha256='f'*64,evidence_class='authored')],
                effective_from=raw['clock_at'],effective_until=None,ranking_qualified=False)
            key,value=profile('probability',payload);raw['comparison_profiles'][key]=value
            q['comparison_input_refs']['refs']['probability']=key
        return raw

    def test_supported_bound_inputs_do_not_require_expired_recipe(self):
        raw=self.raw();before=deepcopy(raw)
        with patch('socket.socket.connect',side_effect=AssertionError('No provider requests')):
            state=serialize(raw,allow_synthetic=True)
        self.assertEqual(raw,before)
        q=state['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi'];r=q['calculations']['funded_estimate']
        self.assertTrue(r['bound_financial_inputs']);m=r['financial_metrics']
        # Authored price .4, decisive probability .6; integer grid leaves 9.6 USD.
        self.assertEqual(F(r['deployed_capital_usd']),F('990.4'))
        self.assertEqual(F(r['funding']['residual_usd']),F('9.6'))
        self.assertEqual(F(m['conditional_net_ev_usd']),F('495.2'))
        self.assertEqual(F(m['conditional_buffered_ev_usd']),F('490.248'))
        self.assertIsNone(m['net_modeled_ev_usd']);self.assertFalse(r['classification']['is_arb'])
        self.assertFalse(r['classification']['main_positive_eligible'])

    def test_ordinary_conditional_basis_metadata_is_not_a_full_probability_model(self):
        raw=self.raw();e=raw['events'][0];q=e['groups'][0]['outcomes'][0]['quotes']['kalshi']
        ref=references(q,raw['comparison_profiles'])['reference']['payload']
        weights=[1/F(r['decimal_odds']) for r in ref['outcomes']];total=sum(weights)
        payload=dict(version='comparison-benchmark-basis-1',method='pinnacle_proportional_no_vig',
            conditioning=ref['conditioning'],probabilities=[str(w/total) for w in weights],
            reference_receipt_sha256=ref['receipt_sha256'],unknown_mass=['tie','exceptional'])
        key,value=profile('probability',payload);raw['comparison_profiles'][key]=value
        q['comparison_input_refs']['refs']['probability']=key
        state=serialize(raw,allow_synthetic=True)
        result=state['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']['calculations']['funded_estimate']
        self.assertTrue(result['bound_financial_inputs'])
        self.assertEqual(F(result['financial_metrics']['conditional_buffered_ev_usd']),F('490.248'))
        self.assertIsNone(result['financial_metrics']['buffered_ev_usd'])
        payload=deepcopy(payload);payload['probabilities']=['0.1','0.9'];key,value=profile('probability',payload)
        raw['comparison_profiles'][key]=value;q['comparison_input_refs']['refs']['probability']=key
        state=serialize(raw,allow_synthetic=True)
        result=state['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']['calculations']['funded_estimate']
        self.assertFalse(result['model_available'])

    def test_independent_positive_negative_zero_after_exactly_one_buffer(self):
        for p,expected_per_contract in [('0.5','0.098'),('0.402','0'),('0.3','-0.102')]:
            with self.subTest(p=p):
                state=serialize(self.raw(p),allow_synthetic=True)
                q=state['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi'];r=q['calculations']['funded_estimate']
                self.assertTrue(r['bound_financial_inputs'])
                self.assertEqual(F(r['financial_metrics']['conditional_buffered_ev_usd']),F(r['native_quantity'])*F(expected_per_contract))
                self.assertEqual(F(r['buffer_usd']),F(r['deployed_capital_usd'])/200)
                self.assertEqual(result_availability(r)['state'],'numeric_current')
                self.assertIsNone(r['financial_metrics']['buffered_ev_usd'])

    def test_complete_EV_signs_and_covered_pair_need_every_terminal_cashflow(self):
        from app.comparison.bound_finance import pairs
        for p,per_contract in [('0.5','0.098'),('0.402','0'),('0.3','-0.102')]:
            with self.subTest(p=p):
                state=serialize(self.raw(p,complete=True),allow_synthetic=True)
                e=state['events'][0];q=e['groups'][0]['outcomes'][0]['quotes']['kalshi']
                result=q['calculations']['funded_estimate']
                self.assertTrue(result['bound_financial_inputs'])
                self.assertEqual(F(result['financial_metrics']['buffered_ev_usd']),F(result['native_quantity'])*F(per_contract))
                self.assertTrue(result_availability(result)['evaluation_complete'])
                portfolio=pairs(e,state['comparison_profiles'],DEFAULT_POLICY)[0]
                self.assertTrue(portfolio['classification']['is_arb'])
                self.assertEqual(F(portfolio['financial_metrics']['buffered_complete_modeled_minimum_usd']),F('4.525'))
                self.assertEqual(portfolio['classification']['unknown_outcomes'],[])

    def test_shared_pair_is_conditional_with_exact_base_funding_and_one_haircut(self):
        from app.comparison.bound_finance import pairs
        state=serialize(self.raw(),allow_synthetic=True);event=state['events'][0]
        result=pairs(event,state['comparison_profiles'],DEFAULT_POLICY)[0]
        self.assertEqual(F(result['deployed_capital_usd']),95)
        self.assertEqual(F(result['financial_metrics']['decisive_opposing_margin_usd']),5)
        self.assertEqual(F(result['financial_metrics']['buffered_decisive_opposing_margin_usd']),F('4.525'))
        self.assertIsNone(result['financial_metrics']['complete_modeled_minimum_usd'])
        self.assertFalse(result['classification']['is_arb'])
        self.assertTrue(result['classification']['positive_rule_sensitive_eligible'])
        self.assertIn('noncompleted',result['classification']['unknown_outcomes'])

    def test_changed_missing_fee_and_future_clocks_withdraw_numeric_results(self):
        from app.comparison.estimated_ev import evaluate
        state=serialize(self.raw(),allow_synthetic=True);e=state['events'][0];g=e['groups'][0];q=g['outcomes'][0]['quotes']['kalshi']
        q['comparison_input_refs']['refs']['fee']=None
        result=evaluate(q,state['comparison_profiles'],at=instant(state['clock_at']),event=e,group=g)
        self.assertFalse(result['model_available']);self.assertIsNone(result['financial_metrics']['buffered_ev_usd'])
        self.assertNotEqual(result_availability(result)['state'],'numeric_current')


class PublicationAdmission(TestCase):
    def test_estimates_publish_each_neighborhood_with_unchanged_reservations(self):
        from app.collection.background_work import BackgroundWork, MIB
        from app.storage.latest_board import reconcile
        work=BackgroundWork(sampler=lambda:500*MIB,limit_bytes=768*MIB,
            source_runway_bytes=160*MIB,ingress_headroom_bytes=32*MIB)
        class DB:
            def transaction(self):return self
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,*args):return self
            def fetchall(self):return []
        def reservation(db,*,event_ids=None,**kwargs):
            return (32+20*len(event_ids or []))*MIB
        captured=[]
        def calculate(db,*,event_ids,reservation_bytes,**kwargs):
            captured.append((event_ids,reservation_bytes))
            # A queued whole-capture worker must get the next turn, but must
            # not prevent this already-admitted finite sweep from completing.
            with work.claim('coverage',40*MIB) as waiting:self.assertFalse(waiting)
            self.assertLessEqual(work.snapshot()['reserved_bytes'],72*MIB)
            return dict(published=True,computed=1,reused=0)
        with patch('app.collection.background_work.BACKGROUND',work),\
                patch('app.storage.latest_board.capture_batches',return_value=[['a'],['b'],['c']]),\
                patch('app.storage.latest_board.capture_reservation',side_effect=reservation),\
                patch('app.storage.latest_board._reconcile',side_effect=calculate):
            result=reconcile(DB())
        self.assertEqual(captured,[(['a'],52*MIB),(['b'],52*MIB),(['c'],52*MIB)])
        self.assertEqual(result['computed'],3)
        self.assertEqual({e for ids,_ in captured for e in ids},{'a','b','c'})
        self.assertFalse(work.snapshot()['active'])
        with work.claim('estimates',32*MIB) as denied:self.assertFalse(denied)
        with work.claim('coverage',40*MIB) as admitted:self.assertTrue(admitted)
        self.assertEqual(work.snapshot()['source_runway_bytes'],160*MIB)
        self.assertEqual(work.snapshot()['process_limit_bytes'],768*MIB)
