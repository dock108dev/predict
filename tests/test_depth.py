"""Independent small-domain arithmetic; all scenarios synthetic or offline replays."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D, localcontext, Inexact, ROUND_UP, ROUND_CEILING, ROUND_HALF_EVEN
from datetime import timedelta
import unittest

from app.depth import (Search, consume, size_depth, evaluate_allocation, replay, book_ladders, ladder_wire)
from app.depth_example import fixture, run, selected, change_outcome, historical_depth
from app.arbitrage_example import NOW
from app.fees import replay as fee_replay


class DepthTests(unittest.TestCase):
    def setUp(self): self.data,self.ladders=fixture()
    def candidate(self,search=None): return selected(run(self.data,self.ladders,search))
    def allocate(self,qs): return evaluate_allocation(self.candidate(),qs)
    def alter(self,**kw): self.ladders[0]=replace(self.ladders[0],**kw)
    def observe(self,**kw): self.alter(observation=replace(self.ladders[0].observation,**kw))

    def test_walk_exact_partial_no_reuse(self):
        levels=[dict(price='.2',quantity='1.25',provenance='a'),dict(price='.4',quantity='2.75',provenance='b')]
        fills=consume(levels,'2')
        self.assertEqual([D(f['quantity']) for f in fills],[D('1.25'),D('.75')])
        self.assertEqual(sum(D(f['price'])*D(f['quantity']) for f in fills),D('.55'))
        self.assertEqual(consume(levels,'2'),fills)
        with self.assertRaises(ValueError): consume(levels,'4.01')
        with self.assertRaises(ValueError): consume(levels,'2',partial_final=False)

    def test_reject_ambiguous_levels(self):
        for levels in [[('.2','3','x'),('.2','3','x')],[('.3','3','x'),('.2','3','y')],[('.2','-1','x')]]:
            self.alter(levels=tuple(levels)); c=self.candidate()
            self.assertEqual(c['search']['optimality'],'unsized-inputs')

    def test_fractional_grid_final(self):
        self.data,self.ladders=fixture(a=(('.2','1.25'),('.4','2.75')),b=(('.2','4'),),steps=('.25','1'),minimums=('.25','1'))
        a=self.allocate(('2','2'))
        self.assertEqual([D(x['quantity']) for x in a['legs'][0]['consumed_levels']],[D('1.25'),D('.75')])
        self.assertEqual(D(a['legs'][0]['entry_cost']),D('.55'))
        with self.assertRaises(ValueError): self.allocate(('2.1','2'))

    def test_minimum_and_increment(self):
        self.data,self.ladders=fixture(steps=('2','3'),minimums=('3','2'))
        c=self.candidate()
        self.assertEqual(c['search']['common_grid'],'6')
        with self.assertRaises(ValueError): evaluate_allocation(c,('2','3'))
        with self.assertRaises(ValueError): evaluate_allocation(c,('4','2'))
        self.assertEqual(evaluate_allocation(c,('4','3'))['quantities'],['4','3'])

    def test_no_common_positive_grid(self):
        self.data,self.ladders=fixture(a=(('.2','4'),),b=(('.2','3'),),steps=('2','3'))
        c=self.candidate()
        self.assertTrue(c['solutions']['equal_max_profit']['allocation']['no_trade'])
        self.assertFalse(c['solutions']['max_profit']['allocation']['no_trade'])

    def test_single_level_agrees_with_slice10(self):
        self.data,self.ladders=fixture(a=(('.4','4'),),b=(('.4','4'),))
        report=run(self.data,self.ladders); c=selected(report)
        old=next(c for c in report['top_of_book']['candidates'] if c['conditional_calculation'])['conditional_calculation']
        new=evaluate_allocation(c,('4','4'))
        for key in ('entry_fees','worst_case_profit','worst_case_roi'):
            self.assertEqual(D(old[key]),D(new[key]))
        self.assertEqual(D(old['entry_cash_requirement']),D(new['required_cash']))

    def test_unequal_improves_independent_numbers(self):
        self.data,self.ladders=fixture(a=(('.2','4'),('.95','2')),b=(('.2','3'),('.7','3')),steps=('2','3'))
        c=self.candidate(); a=c['solutions']['max_profit']['allocation']; e=c['solutions']['equal_max_profit']['allocation']
        self.assertEqual(a['quantities'],['4','3'])
        # Cost 1.4, Kalshi ceil(.0448)=.05, PMUS round(.0288)=.03.
        self.assertEqual(D(a['worst_case_profit']),D('1.52'))
        self.assertGreater(D(a['worst_case_profit']),D(e['worst_case_profit']))
        self.assertGreater(len(a['outcomes']),2)
        self.assertEqual(min(D(o['profit']) for o in a['outcomes'].values()),D('1.52'))

    def test_refund_is_exact_acquisition_cost(self):
        change_outcome(self.data,'canceled',{'kind':'refund','evidence':'test-only refund'})
        a=self.allocate(('4','4')); fee=a['legs'][0]['fee_audit']
        self.assertEqual(D(fee['outcomes']['canceled']['gross_payout']),D('1.25'))
        self.assertEqual(fee['engine'],'fees-1-refunds-1')
        self.assertEqual(fee_replay(fee),fee)
        self.assertEqual(D(a['outcomes']['canceled']['net_payout']),D('3.25'))

    def test_unknown_material_outcome(self):
        change_outcome(self.data,'canceled',{'kind':'unknown','reason':'test missing rule'})
        c=self.candidate(); a=evaluate_allocation(c,('3','3'))
        self.assertIsNone(a['worst_case_profit']); self.assertIsNone(a['outcomes']['canceled']['profit'])
        self.assertEqual(D(a['minimum_known_profit']),D('1.73'))
        self.assertEqual(c['input']['base']['settlement']['status'],'UNKNOWN')
        self.assertIn('objective-unresolved',c['solutions']['max_profit']['optimality'])
        self.assertFalse(c['solutions']['minimum_known_diagnostic']['allocation']['no_trade'])

    def test_all_exceptional_losses_prevent_recommendation(self):
        self.data,self.ladders=fixture(exception='0')
        c=self.candidate(); self.assertTrue(c['solutions']['max_profit']['allocation']['no_trade'])
        a=evaluate_allocation(c,('3','3'))
        self.assertEqual(D(a['outcomes']['tie']['profit']),D('-1.27'))

    def test_grouped_multilevel_pm_fees(self):
        self.data,self.ladders=fixture(a=(('.2','4'),),b=(('.5','1'),('.6','3')))
        a=self.allocate(('3','3')); fee=a['legs'][1]['fee_audit']
        # .015 -> .02; .0288 -> .03 capped to round(.0438)-.02 = .02.
        self.assertEqual(D(fee['entry_fees']),D('.04'))
        self.assertEqual(len({f['order_id'] for f in fee['context']['fills']}),1)
        self.assertEqual([D(t['amount']) for t in fee['trace']],[D('.02'),D('.02')])
        self.assertEqual(fee_replay(fee),fee)
        self.assertTrue(any('fragmentation' in x for x in a['reasons']))

    def test_independent_small_grid_oracle(self):
        # Closed-form fee arithmetic is independent of both search and fee engine.
        for pa,pb in [('.2','.3'),('.1','.5'),('.49','.49')]:
            self.data,self.ladders=fixture(a=((pa,'5'),),b=((pb,'4'),))
            expected=(D(0),(0,0))
            for x in range(6):
                for y in range(5):
                    ka=(D('.07')*D(pa)*(1-D(pa))*x).quantize(D('.01'),rounding=ROUND_CEILING)
                    pm=(D('.06')*D(pb)*(1-D(pb))*y).quantize(D('.01'),rounding=ROUND_HALF_EVEN)
                    profit=D(min(x,y))-D(pa)*x-D(pb)*y-ka-pm
                    if profit>expected[0]: expected=(profit,(x,y))
            c=self.candidate(); a=c['solutions']['max_profit']['allocation']
            self.assertEqual(D(a['worst_case_profit']),expected[0])
            self.assertEqual(tuple(map(D,a['quantities'])),expected[1])
            self.assertEqual(c['search']['evaluated'],30)
            self.assertIn('proven-optimal',c['search']['optimality'])

    def test_different_objectives_and_deeper_loss(self):
        c=self.candidate(Search(min_roi='.10'))
        self.assertEqual(c['solutions']['max_profit']['allocation']['quantities'],['3','3'])
        self.assertEqual(c['solutions']['max_deployment']['allocation']['quantities'],['6','6'])
        self.assertEqual(D(evaluate_allocation(c,('8','8'))['worst_case_profit']),D('.08'))
        # Add more bad depth: edge disappears, no monotonic interpolation needed.
        self.data,self.ladders=fixture(a=(('.2','3'),('.65','7')),b=(('.2','3'),('.65','7')))
        self.assertLess(D(self.allocate(('10','10'))['worst_case_profit']),0)

    def test_rounding_nonmonotonic_roi(self):
        self.data,self.ladders=fixture(a=(('.1','4'),),b=(('.5','4'),))
        c=self.candidate(); ps=[D(evaluate_allocation(c,(str(q),str(q)))['worst_case_profit']) for q in range(1,5)]
        self.assertEqual(ps,list(map(D,['.37','.75','1.14','1.51'])))
        self.assertEqual(c['solutions']['max_roi']['allocation']['quantities'],['3','3'])
        self.assertEqual(c['solutions']['max_profit']['allocation']['quantities'],['4','4'])

    def test_losing_and_zero_alternative(self):
        self.data,self.ladders=fixture(a=(('.55','4'),),b=(('.55','4'),))
        c=self.candidate()
        for s in c['solutions'].values(): self.assertTrue(s['allocation']['no_trade'])
        self.assertEqual(c['solutions']['max_profit']['allocation']['required_cash'],'0')
        self.assertIsNone(c['solutions']['max_roi']['allocation']['worst_case_roi'])

    def test_cash_limit_inclusive_and_thresholds(self):
        c=self.candidate(Search(total_cash_limit='1.27',min_profit='1.73'))
        self.assertEqual(c['solutions']['max_deployment']['allocation']['quantities'],['3','3'])
        c=self.candidate(Search(total_cash_limit='1.269999'))
        self.assertNotEqual(c['solutions']['max_profit']['allocation']['quantities'],['3','3'])
        c=self.candidate(Search(min_profit='1.730001'))
        self.assertTrue(c['solutions']['max_deployment']['allocation']['no_trade'])
        c=self.candidate(Search(venue_cash_limits=('.63',None)))
        self.assertLessEqual(D(c['solutions']['max_profit']['allocation']['required_cash_per_venue'][0]),D('.63'))

    def test_zero_cash_and_reserve(self):
        c=self.candidate(Search(total_cash_limit='0'))
        self.assertTrue(c['solutions']['max_profit']['allocation']['no_trade'])
        from app.arbitrage import Policy
        r=size_depth(self.data[0],self.data[1],self.ladders,self.data[3],evaluation_time=NOW,policy=Policy(execution_reserve_usd='2'))
        a=selected(r)['solutions']['max_profit']['allocation']
        self.assertTrue(a['no_trade']); self.assertEqual(a['execution_reserve'],'0')

    def test_budget_exhaustion_and_exact_boundary(self):
        c=self.candidate(Search(max_evaluations=5))
        self.assertTrue(c['search']['limit_reached']); self.assertEqual(c['search']['evaluated'],5)
        self.assertIn('best-found',c['search']['optimality'])
        c=self.candidate(Search(max_evaluations=81))
        self.assertFalse(c['search']['limit_reached']); self.assertEqual(c['search']['evaluated'],81)
        c=self.candidate(Search(max_evaluations=1))
        self.assertTrue(c['solutions']['max_profit']['allocation']['no_trade'])

    def test_huge_domain_is_bounded(self):
        self.data,self.ladders=fixture(a=(('.2','100000000'),),b=(('.2','100000000'),),steps=('.0001','1'),minimums=('.0001','1'))
        c=self.candidate(Search(max_evaluations=4))
        self.assertEqual(c['search']['evaluated'],4)
        self.assertTrue(c['search']['limit_reached'])

    def test_precision_isolation_and_determinism(self):
        first=self.candidate()
        with localcontext() as ctx:
            ctx.prec=2; ctx.rounding=ROUND_UP; ctx.traps[Inexact]=True
            self.assertEqual(first,self.candidate())
            self.assertEqual(replay(first),first)

    def test_duplicate_and_conflicting_observations(self):
        first=self.candidate(); self.ladders.extend(deepcopy(self.ladders)); self.ladders.reverse()
        self.assertEqual(first,self.candidate())
        self.ladders.append(replace(self.ladders[1],levels=(('.2','3','changed'),('.7','5','changed'))))
        r=run(self.data,self.ladders)
        self.assertTrue(any(any('conflicting-depth' in x for x in c['reasons']) for c in r['candidates']))
        self.assertTrue(all(c['solutions']['max_profit']['allocation']['no_trade'] for c in r['candidates']))

    def test_top_depth_conflict(self):
        self.alter(levels=(('.1','3','test'),))
        self.assertTrue(any('top-and-depth-conflict' in x for x in self.candidate()['reasons']))

    def test_unknown_sizing_rules_and_units(self):
        for kw in ({'units_verified':False},{'increment':None},{'minimum':None}):
            self.data,self.ladders=fixture(); self.observe(**kw)
            self.assertEqual(self.candidate()['search']['optimality'],'unsized-inputs')
        self.data,self.ladders=fixture(); self.alter(partial_final=None)
        self.assertTrue(any('partial-fill-rule-unknown' in x for x in self.candidate()['reasons']))

    def test_partial_not_permitted(self):
        self.alter(partial_final=False); c=self.candidate()
        self.assertGreater(c['search']['invalid_partial_allocations'],0)
        with self.assertRaises(ValueError): evaluate_allocation(c,('2','2'))
        self.assertEqual(evaluate_allocation(c,('3','3'))['quantities'],['3','3'])

    def test_unknown_fees_not_zero(self):
        next(c for c in self.data[3].values() if c['venue']=='polymarket_us').pop('assume_no_settlement_fee')
        c=self.candidate(); a=evaluate_allocation(c,('3','3'))
        self.assertIsNone(a['worst_case_profit'])
        self.assertIn('objective-unresolved',c['solutions']['max_profit']['optimality'])

    def test_identity_mismatch_fee_context(self):
        next(iter(self.data[3].values()))['market_id']='wrong'
        a=self.allocate(('3','3'))
        self.assertIsNone(a['required_cash']); self.assertFalse(a['qualified_modeled_arbitrage'])

    def test_propagate_existing_eligibility(self):
        for kw,reason in [({'locks_clear':False},'locked'),({'sync':'unsynchronized'},'reconstruction'),({'source_time_problem':'regression'},'regression'),({'role':'maker'},'maker-dependent')]:
            self.data,self.ladders=fixture(); self.observe(**kw)
            c=self.candidate(); a=evaluate_allocation(c,('3','3'))
            self.assertTrue(any(reason in x for x in a['reasons'])); self.assertFalse(a['qualified_modeled_arbitrage'])

    def test_stable_id_replay_provenance_and_tampering(self):
        c=self.candidate(); self.assertEqual(replay(c),c)
        self.assertEqual(c['id'],c['input']['base']['id'])
        for w in c['input']['ladders']:
            self.assertTrue(w['raw_json']); self.assertTrue(w['observation']['source_sha256'])
            self.assertTrue(all(x['provenance'] for x in w['levels']))
        a=c['solutions']['max_profit']['allocation']
        self.assertTrue(all(x['fee_audit']['registry_hash'] for x in a['legs']))
        bad=deepcopy(c); bad['input']['search']['min_profit']='99'
        with self.assertRaises(ValueError): replay(bad)
        bad=deepcopy(c); bad['curve'][0]['required_cash']='99'
        with self.assertRaises(ValueError): replay(bad)
        self.observe(quote=replace(self.ladders[0].observation.quote,raw=replace(self.ladders[0].observation.quote.raw,received_at=NOW-timedelta(seconds=1))))
        self.assertEqual(self.candidate()['id'],c['id'])

    def test_rule_refresh(self):
        first=self.candidate(); change_outcome(self.data,'canceled',{'kind':'unknown','reason':'changed test rule'})
        after=self.candidate(); self.assertEqual(first['id'],after['id'])
        self.assertGreater(after['input']['base']['pair_revision'],first['input']['base']['pair_revision'])
        self.assertEqual(after['input']['base']['settlement']['status'],'UNKNOWN')

    def test_adapter_kalshi_all_levels_and_pmus_no_short(self):
        from app.adapters.kalshi import book_from_levels
        from app.models.core import Depth,BookSync
        o=self.ladders[0].observation
        b=book_from_levels(o.quote.raw,{'yes':{D('.3'):D('2')},'no':{D('.8'):D('1.25'),D('.6'):D('2.75')}},depth=Depth.PARTIAL,sync=BookSync.SYNCHRONIZED)
        ls=book_ladders(b,partial_final=True,environment='synthetic',evidence_class='synthetic',source_time_semantics='snapshot',units_verified=True,minimum='.25',increment='.25',sizing_evidence='test',locks_clear=True)
        self.assertEqual([(D(p),D(q)) for p,q,_ in ls[0].levels],[(D('.2'),D('1.25')),(D('.4'),D('2.75'))])
        self.assertIn('1-no-bid',ls[0].transformation)
        r=historical_depth()
        self.assertEqual(r['summary']['current_production'],0)
        self.assertEqual(len(r['top_of_book']['matching']['pairs']),10)
        self.assertTrue(all(p['settlement']['status']=='UNKNOWN' for p in r['top_of_book']['matching']['pairs'].values()))
        self.assertTrue(any(w and w['levels'] is None and w['observation']['venue']=='polymarket_us' for c in r['candidates'] for w in c['input']['ladders']))

    def test_independent_objective_oracle_with_constraints(self):
        self.data,self.ladders=fixture(a=(('.1','4'),),b=(('.5','4'),))
        c=self.candidate(Search(min_roi='.60',total_cash_limit='2.00'))
        profit_best=(D(0),None); roi_best=(D(0),None); deploy_best=(D(0),None)
        for x in range(5):
            for y in range(5):
                cash=D('.1')*x+D('.5')*y+(D('.0063')*x).quantize(D('.01'),rounding=ROUND_CEILING)+(D('.015')*y).quantize(D('.01'),rounding=ROUND_HALF_EVEN)
                profit=D(min(x,y))-cash
                if not cash or cash>D('2') or profit<=0: continue
                roi=profit/cash
                if profit>profit_best[0]: profit_best=profit,(x,y)
                if roi>roi_best[0]: roi_best=roi,(x,y)
                if roi>=D('.60') and cash>deploy_best[0]: deploy_best=cash,(x,y)
        for objective,expected in [('max_profit',profit_best),('max_roi',roi_best),('max_deployment',deploy_best)]:
            self.assertEqual(tuple(map(D,c['solutions'][objective]['allocation']['quantities'])),expected[1])

    def test_qualified_branch_test_only_fee_stub(self):
        # Isolated branch test, deliberately not evidence of actual venue fees.
        from unittest.mock import patch
        self.data,self.ladders=fixture(environment='production')
        def stub(c,registry=None):
            cost=sum(D(f['price'])*D(f['quantity']) for f in c['fills'])
            quantity=sum(D(f['quantity']) for f in c['fills'])
            return dict(qualification='documented_scenario',entry_fees='0',entry_cash_requirement=str(cost),
                credits=[],schedule={'coefficient':'0'},unsupported=[],assumptions=[],
                scope='TEST ONLY zero-fee qualification stub',
                outcomes={n:dict(net_payout=str(D(v)*quantity),net_cashflow=str(D(v)*quantity-cost),settlement_fee='0') for n,v in c['outcomes'].items()})
        with patch('app.depth.calculate',side_effect=stub):
            a=self.candidate()['solutions']['max_profit']['allocation']
        self.assertTrue(a['qualified_modeled_arbitrage'])
        self.assertFalse(a['current_production_opportunity'])

    def test_curve_truncation_is_disclosed(self):
        c=self.candidate(Search(curve_limit=2))
        self.assertEqual(len(c['curve']),2)
        self.assertTrue(c['curve_truncated'])
        self.assertFalse(c['search']['limit_reached'])

    def test_search_validation(self):
        for kwargs in ({'max_evaluations':0},{'max_evaluations':True},{'min_roi':.1},{'total_cash_limit':'-1'},{'venue_cash_limits':('1',)}):
            with self.assertRaises(ValueError): Search(**kwargs)

if __name__=='__main__': unittest.main()
