"""B02 authentic retained inputs; mutations and cashflow overrides are authored."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction as F
from unittest import TestCase
from unittest.mock import patch
from app.comparison.current_dependencies import instant, digest
from app.comparison.current_metrics import calculation_instant
from app.comparison.estimated_ev import evaluate
from app.comparison.estimated_pair import Leg, evaluate as pair
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.comparison.calculation_availability import result_availability, summary
from app.dashboard.comparison_board import response, entries
from app.storage.comparison_board import calculate_current
from tests.test_current_board_reads import context, bundle, frame
from tests.test_ev09_n01 import retained, AT
from tests.test_ev05_funded import vector, run


class Availability(TestCase):
    def source(self):
        _, s = retained()
        e, g, q = next(x for x in entries(s) if x[2]['venue'] == 'kalshi')
        return deepcopy(q), deepcopy(s['comparison_profiles']), deepcopy(e), deepcopy(g)

    def board(self, at=AT, paused=False, view='ev', filter='all', policy=DEFAULT_POLICY):
        f=frame()
        if paused:f['source_status']={'novig':dict(state='unavailable'), 'prophetx':dict(state='unavailable')}
        c=context(f,at=at);b=bundle(c,policy)
        from app.dashboard.comparison_board import expand_financial
        return expand_financial(response(b,calculate_current(b,policy,context=c),policy,view=view,filter=filter,at=at))

    def test_current_paused_stale_matrix_with_numeric_counts(self):
        later=(instant(AT)+timedelta(hours=1)).isoformat()
        for paused in (False,True):
            for at in (AT,later):
                with self.subTest(paused=paused,at=at):
                    b=self.board(at,paused)
                    supported=[r for r in b['rows'] if r['availability']['numeric_metrics']]
                    self.assertGreater(len(supported),0)
                    self.assertEqual(b['availability']['numeric_results'],len(supported))
                    for r in supported:
                        last=at!=AT or paused and r['venue'] in ('novig','prophetx')
                        self.assertEqual(r['availability']['state'],'numeric_last_known' if last else 'numeric_current')
                        if last:self.assertFalse(r['classification']['main_positive_eligible'])
                    if at!=AT:self.assertEqual(self.board(at,paused,filter='positive')['rows'],[])

    def test_mixed_time_does_not_backdate_fresh_native_or_models(self):
        q,p,e,g=self.source();now=instant(AT)+timedelta(hours=1)
        old=deepcopy(q['times']);q['times'].update(source_at=now.isoformat(),received_at=now.isoformat(),projected_at=now.isoformat())
        r=evaluate(q,p,at=now,event=e,group=g,details=True)
        self.assertIsNotNone(r['financial_metrics']['buffered_ev_usd'])
        self.assertEqual(r['evaluated_at'],now.isoformat());f=r['evaluation_frame']
        self.assertTrue(f['mixed_source_times']);self.assertFalse(f['simultaneous_historical_trade'])
        self.assertEqual(f['quotes'][0]['times'],q['times']);self.assertNotEqual(q['times'],old)
        for original in f['reference_originals']:self.assertLess(instant(original['received_at']),now)
        self.assertIn('reference_expired',r['eligibility_reasons']);self.assertFalse(r['ranking_eligible'])
        recipe=q['comparison_input_status']['fee']['estimate_content']
        recipe['expires_at']=(now-timedelta(seconds=1)).isoformat();recipe['id']=digest({k:v for k,v in recipe.items() if k!='id'})
        invalid=evaluate(q,p,at=now,event=e,group=g)
        self.assertFalse(invalid['model_available']);self.assertIn('expired',str(invalid['reasons']))

    def test_current_applicability_never_moves_into_future_model_interval(self):
        q,p,e,g=self.source();recipe=q['comparison_input_status']['fee']['estimate_content']
        recipe['effective_from']=(instant(AT)+timedelta(seconds=1)).isoformat()
        recipe['id']=digest({k:v for k,v in recipe.items() if k!='id'})
        r=evaluate(q,p,at=instant(AT),event=e,group=g)
        self.assertFalse(r['model_available']);self.assertEqual(calculation_instant((q,),p,instant(AT)),instant(AT))

    def test_future_conflicting_unknown_quote_clocks_are_refused(self):
        for field,value in [('source_at',None),('received_at',None),('source_at','2027-01-01T00:00:00Z'),('projected_at','2027-01-01T00:00:00Z'),('received_at','2026-10-01T00:00:00Z')]:
            q,p,e,g=self.source();q['times'][field]=value
            r=evaluate(q,p,at=instant(AT),event=e,group=g)
            self.assertFalse(r['model_available'],(field,value));self.assertIsNone(r['financial_metrics']['buffered_ev_usd'])
            with self.assertRaises(ValueError):Leg(q,g,p,e,instant(AT))

    def test_missing_reference_short_and_scoped_failure(self):
        q,p,e,g=self.source();q['comparison_input_refs']['refs']['reference']=None
        r=evaluate(q,p,at=instant(AT),event=e,group=g)
        self.assertEqual(result_availability(r)['state'],'missing_reference')
        b=self.board();short=next(r for r in b['rows'] if r['native_side']=='Short')
        self.assertEqual(short['availability']['state'],'unsupported_inputs')
        self.assertIn('short_collateral_unresolved',short['availability']['reason_codes'])
        self.assertTrue(any(r['availability']['state']=='numeric_current' for r in b['rows']))
        failed=result_availability(dict(reasons=['read_failed']))
        self.assertEqual(failed['state'],'calculation_failed')
        s=summary([('game',['kalshi'],failed)])
        self.assertEqual(s['outcome'],'unavailable');self.assertEqual(s['numeric_results'],0)

    def test_as_of_pairs_preserve_margin_conditional_and_null_complete_ev(self):
        at=(instant(AT)+timedelta(hours=1)).isoformat();b=self.board(at,True,view='arbs')
        r=next(r for r in b['rows'] if {l['venue'] for l in r['legs']}=={'novig','kalshi'})
        self.assertEqual(r['availability']['state'],'numeric_last_known')
        m=r['financial_metrics'];self.assertIsNotNone(m['buffered_decisive_opposing_margin_usd'])
        self.assertIsNotNone(m['conditional_buffered_ev_usd']);self.assertIsNone(m['buffered_ev_usd'])
        self.assertEqual(r['availability']['metrics']['buffered_ev_usd']['reason_codes'],['complete_probability_partition_unsupported'])
        self.assertEqual(self.board(at,True,view='arbs',filter='positive')['rows'],[])

    def test_amount_and_benchmark_remain_bound_to_exact_calculations(self):
        a=self.board();b=self.board(policy=replace(DEFAULT_POLICY,capital_ceiling_usd='500'))
        self.assertNotEqual(a['calculation_context']['context_id'],b['calculation_context']['context_id'])
        for r in b['rows']:
            if r['availability']['numeric_metrics']:
                self.assertEqual(r['funding']['requested_usd'],'500')
                self.assertEqual(F(r['buffer_usd']),F(r['funding']['deployed_usd'])/200)
        c=self.board(policy=replace(DEFAULT_POLICY,benchmark_venue='novig'))
        self.assertNotEqual(a['calculation_context']['context_id'],c['calculation_context']['context_id'])
        self.assertTrue(all(r['benchmark_identity']['venue']=='novig' for r in c['rows']))

    def test_signed_zero_positive_negative_and_checked_empty_are_distinct(self):
        q,p,ctx=vector('novig')
        base=run(q,p,ctx,policy=DEFAULT_POLICY,native_quantity='100')
        capital=F(base['deployed_capital_usd']);target=capital+capital/200
        for delta in (F(-1),F(0),F(1)):
            with self.subTest(delta=delta):
                # Explicit authored settlement cells, not observed venue payouts.
                receipts={s:str(target+delta) for s in ('home_win','away_win','tie','terminal_noncompletion')}
                r=run(q,p,ctx,policy=DEFAULT_POLICY,native_quantity='100',state_cashflows=receipts)
                self.assertEqual(F(r['financial_metrics']['buffered_ev_usd']),delta)
                self.assertEqual(result_availability(r)['state'],'numeric_current')
                s=summary([('authored',['novig'],result_availability(r))])
                self.assertEqual(s['outcome'],'positive' if delta>0 else 'evaluated_no_positive')

    def test_partial_healthy_rows_survive_local_calculation_failure(self):
        from app.comparison.estimated_ev import evaluate as real
        def scoped(q,*args,**kw):
            if q['venue']=='kalshi':return dict(model_available=False,ranking_eligible=False,reasons=['calculation_read_failed'])
            return real(q,*args,**kw)
        with patch('app.comparison.estimated_ev.evaluate',side_effect=scoped):b=self.board()
        self.assertGreater(b['availability']['counts']['calculation_failed'],0)
        self.assertGreater(b['availability']['numeric_results'],0)
        self.assertEqual(b['availability']['outcome'],'partial')

    def test_unsupported_reference_clocks_do_not_create_ev_or_probability_weights(self):
        from app.comparison.benchmark import TwoWayBenchmark
        q,p,e,g=self.source();reference=TwoWayBenchmark.from_dict(retained()[0]['benchmark'])
        for changes in ({'book_at':'2027-01-01T00:00:00Z'}, {'book_at':None,'market_at':None}, {'received_at':'2027-01-01T00:00:00Z'}):
            ref=replace(reference,outcomes=tuple(replace(row,**changes) for row in reference.outcomes))
            r=evaluate(q,p,at=instant(AT),event=e,group=g,benchmark=ref)
            self.assertIsNone(r['financial_metrics']['buffered_ev_usd'])
            self.assertIsNone(r['financial_metrics']['conditional_buffered_ev_usd'])

    def test_expired_bound_fee_envelope_is_not_revived_by_current_receipt(self):
        from app.comparison.current_dependencies import profile
        q,p,ctx=vector('novig')
        q['times'].update(source_at=AT,received_at=AT,projected_at=AT)
        ctx['event']['start_at']=(instant(AT)+timedelta(days=1)).isoformat()
        # An explicit authored selected model boundary, not price age.
        _,original=profile('fee',{},expires_at=(instant(AT)-timedelta(seconds=1)).isoformat())
        key=digest(original);p[key]=original;q['comparison_input_refs']['refs']['fee']=key
        status=q['comparison_input_status']['fee'];status['status']='available_and_bound'
        recipe=status['estimate_content'];recipe['original_profile_ref']=key;recipe['id']=digest({k:v for k,v in recipe.items() if k!='id'})
        r=run(q,p,ctx,policy=DEFAULT_POLICY,at=instant(AT))
        self.assertFalse(r['model_available']);self.assertIn('fee_inputs_expired',str(r['reasons']))
