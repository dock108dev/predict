"""Independent authored EV06 oracles; no provider/owner acceptance."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from app.comparison.costs import CostRule,FeeTerms,UnitSpec,FundingComponent
from app.comparison.current_dependencies import digest
from app.comparison.estimated_pair import Leg,evaluate,compact,joint_basis,pool_charge,assemble
from app.comparison.estimated_policy import LEGACY_POLICY as DEFAULT_POLICY
from functools import partial
evaluate = partial(evaluate, policy=DEFAULT_POLICY)
assemble = partial(assemble, policy=DEFAULT_POLICY)
from tests.test_ev05_funded import vector,bind
from tests.test_ev04_content import AT
from tests.test_comparison_net_costs import setup_case


def pair(prices=('0.24','0.74'),*,flat='5',funding=None,compatible=True,tick='0.01'):
    legs=[];profiles={};event=None
    for index,(venue,predicate,price) in enumerate(zip(('kalshi','polymarket_us'),('win','not_win'),prices)):
        q,p,ctx=vector(venue,'0.5',predicate=predicate)
        q['original']['value']=price
        for key in ('native_value','native_units','transformation'):q['original'].pop(key,None)
        q['id']='authored:ev06:'+str(index)
        if event is None:event=ctx['event']
        request,scenario,kw=setup_case(venue)
        rule=CostRule.from_dict(kw['registry'].data['rules'][0])
        rule=replace(rule,terms=FeeTerms('notional','0','0.01','half_even','order','taker'),market_id=None,event_id=None)
        bind(q,p,'fee',json.loads(json.dumps(dict(rule=rule.to_dict(),flat_entry_fee_usd=flat))))
        bind(q,p,'quantity',dict(grid=dict(minimum_native='1',increment_native='1',legal_price_tick=tick),grid_qualification='authored'))
        if legs:
            reference=legs[0].profiles[legs[0].q['comparison_input_refs']['refs']['reference']]['payload']
            bind(q,p,'reference',reference)
        profiles.update(p)
        leg=Leg(q,ctx['group'],profiles,event,AT,policy=DEFAULT_POLICY,funding=(funding or [{},{}])[index])
        # The independent example explicitly declares common official grading
        # and cancellation. Production consumes selected profile conditions.
        if compatible:leg.conditions=dict(kind='authored_completed_assumption',maximum=None,original_start=None,original_scheduled_date=None,date_timezone=None)
        legs.append(leg)
    return legs,profiles,event


def exact_example():
    funding=[dict(state_cashflows=dict(home_win='0',away_win='1010',tie='0',terminal_noncompletion='242.4')),
             dict(state_cashflows=dict(home_win='1010',away_win='0',tie='747.4',terminal_noncompletion='747.4'))]
    return pair(funding=funding)


def cross_group_workload():
    from tests.ev03_workload import records
    from tests.current_fixture import fixture
    from app.collection.current_benchmark import attach
    from app.dashboard.current_normalized import catalog_from_normalized
    rows,refs,_=records(1,6)
    def move(v):
        if isinstance(v,dict):return {k:move(x) for k,x in v.items()}
        if isinstance(v,list):return [move(x) for x in v]
        if isinstance(v,str):return v.replace('2026-10-08T','2026-10-11T').replace('2026-10-09T','2026-10-12T')
        return v
    rows,refs=move(rows),move(refs)
    for i,r in enumerate(rows):
        q=r['quote'];q.pop('sharp_reference',None)
        if q['source']['native_side'].lower()=='short':
            q['source']['native_side']='Long'
            for k in ('native_value','native_units','transformation'):q['original'].pop(k,None)
            r['comparison_source_metadata']['native_key'][-1]='Long'
        r['result_policy']='authored-independent-group:'+str(i//3)
    attach(rows,refs)
    env=fixture();env.update(events=[],runtime_id='synthetic:ev06:cross-groups',clock_at=AT.isoformat(),projected_at=AT.isoformat())
    return catalog_from_normalized(env,rows,reference_records=refs)


class PairVectors(unittest.TestCase):
    def test_example_82_independent_fixed_oracle(self):
        legs,p,e=exact_example();r=evaluate(legs,quantities=('1010','1010'),details=True)
        self.assertTrue(r['model_available'],r)
        a=1010*F('.24');b=1010*F('.74');capital=a+b+10
        decisive=1010-capital;tie=b-capital;terminal=a+b-capital
        ev=F('.994')*decisive+F('.005')*tie+F('.001')*terminal;haircut=capital*F('.005')
        self.assertEqual([a,b,capital,1000-capital],[F('242.4'),F('747.4'),F('999.8'),F('.2')])
        self.assertEqual([decisive,tie,terminal,ev,haircut],[F('10.2'),F('-252.4'),F('-10'),F('8.8668'),F('4.999')])
        for name,expected in dict(deployed_capital_usd=capital,unused_cash_usd=1000-capital,
            fee_adjusted_expected_profit_usd=ev,buffer_usd=haircut,buffered_profit_usd=ev-haircut,
            buffered_decisive_minimum_usd=F('5.201'),buffered_all_state_minimum_usd=F('-257.399')).items():
            self.assertEqual(F(r[name]),expected,name)
        self.assertEqual(r['display'],dict(buffered_profit_usd='+3.87',buffered_return_percent='+0.39'))
        self.assertEqual(r['category'],'Estimated hedge')
        self.assertEqual(F(r['sensitivity']['tie_break_even']),F('5.1808')/F('262.6'))
        self.assertEqual(r['cost_breakdown']['net_upfront_fee_usd'],'10')
        self.assertEqual(r['states']['a_wins']['profit_usd'],'10.2')
        self.assertEqual(r['states']['b_wins']['profit_usd'],'10.2')

    def test_shared_and_independent_commission_oracles_floor_cap_rounding(self):
        policy=dict(basis='net_gain',rate='.02',grid='.01',rounding='ceiling',aggregation=None,allow_fee_adjustment=False)
        self.assertEqual(pool_charge([F(100),F(-90)],policy),F('.20'))
        self.assertEqual(sum(pool_charge([n],policy) for n in [F(100),F(-90)]),F(2))
        self.assertEqual(pool_charge([F(100),F(-200)],policy),0)
        self.assertEqual(pool_charge([F('100.001')],policy,dict(market_id='authored-pool',cap_usd='1')),1)

    def test_actual_pair_pool_binding_and_independent_additional_terms(self):
        from app.comparison.estimated_pair import economics
        from app.comparison.estimated_consumer import consume
        legs,p,e=pair(flat='0');q=legs[0].q
        fee=deepcopy(next(v['payload'] for k,v in p.items() if v['kind']=='fee' and 'rule' in v['payload']))
        for index,leg in enumerate(legs):
            # Same explicit venue/channel/commission market. Original native
            # instruments remain distinct; mere equal rates are insufficient.
            rule=CostRule.from_dict(fee['rule']);rule=replace(rule,venue=leg.q['venue'],
                terms=FeeTerms('net_gain','0.02','0.01','ceiling',None,'taker'),unit=UnitSpec('dollar_face_contracts','1'))
            bind(leg.q,p,'fee',json.loads(json.dumps(dict(rule=rule.to_dict()))))
        # Test complete pool algebra using independently authored +100/-90
        # gain components. Explicit pool identity controls grouping.
        comps=[];pool=dict(venue='authored',channel='direct_site',market_id='exact:pool')
        for gain in (100,-90):
            comps.append(dict(deployed_capital_usd='100',settlement_already_withheld=False,
                components={'payout':{name+':home_win':dict(modeled_value=str(v)) for name,v in [('receipt_usd',100+gain),('hold_return_usd',0)]},
                    'fee':{name+':home_win':dict(modeled_value=str(v)) for name,v in [('fee_refund_usd',0),('settlement_fee_usd',2 if gain>0 else 0)]}},
                settlement_terms=[dict(policy=dict(basis='net_gain',rate='.02',grid='.01',rounding='ceiling',aggregation=None,allow_fee_adjustment=False),pool=pool,slot='base')]))
        basis={'winner':dict(cells=['home_win']*2,terminal=False)}
        capital,states=economics(comps,basis)
        self.assertEqual(states['winner']['settlement_charge_usd'],'0.2');self.assertEqual(states['winner']['profit_usd'],'9.8')
        for comp in comps:comp['settlement_terms'][0]['pool']=dict(pool,cap_usd='0.1')
        self.assertEqual(economics(comps,basis)[1]['winner']['settlement_charge_usd'],'0.1')
        comps[1]['settlement_terms'][0]['pool']['cap_usd']='0.2'
        with self.assertRaisesRegex(ValueError,'pair_pool_terms_conflict'):economics(comps,basis)
        for comp in comps:comp['settlement_terms'][0]['pool']=None
        self.assertEqual(economics(comps,basis)[1]['winner']['settlement_charge_usd'],'2')
        for comp in comps:comp['settlement_terms'].append(dict(policy=dict(basis='quantity'),pool=None,slot='additional',state_fees={'home_win':'3'}))
        self.assertEqual(economics(comps,basis)[1]['winner']['settlement_charge_usd'],'8')

    def test_optimizer_balanced_and_unequal_stakes(self):
        legs,p,e=pair(flat='0');r=evaluate(legs)
        self.assertTrue(r['model_available'],r)
        self.assertEqual([leg['native_quantity'] for leg in r['legs']],['1020','1020'])
        self.assertLessEqual(F(r['deployed_capital_usd']),1000)
        # Dollar-face payouts require equal face, while stakes differ exactly.
        self.assertNotEqual(F(r['legs'][0]['native_quantity'])*F('.24'),F(r['legs'][1]['native_quantity'])*F('.74'))
        self.assertFalse(r['search']['global_optimality_proven'])
        # Two stake contracts at 2 and 4 odds have equal $200 decisive exposure
        # at $100 and $50 stakes, independent of their displayed native labels.
        qs=[]
        for i,(odds,predicate,n) in enumerate([('2','win','100'),('4','not_win','50')]):
            q,p,ctx=vector('novig','0.5',predicate=predicate);q['original']['value']=odds;q['id']='stake:'+str(i)
            q['source']['native_outcome_id']+=':'+str(i)
            self._rebind_native(q,p)
            leg=Leg(q,ctx['group'],p,ctx['event'],AT);leg.conditions=legs[0].conditions;qs.append(leg)
        r=evaluate(qs,quantities=('100','50'))
        self.assertTrue(r['model_available'],r);self.assertEqual(r['decisive_minimum_usd'],'50')

    @staticmethod
    def _rebind_native(q,p):
        from app.comparison.domain import CanonicalSelection,NativeProvenance
        from app.comparison.current_dependencies import references
        identity=deepcopy(references(q,p)['identity']['payload']);s=CanonicalSelection.from_dict(identity['selection'])
        s=replace(s,native=replace(s.native,instrument_id=q['source']['native_outcome_id'],side_id=q['source']['native_side']))
        identity['selection']=s.to_dict();bind(q,p,'identity',identity)
        for kind in ('fee','payout'):
            recipe=q['comparison_input_status'][kind]['estimate_content'];recipe['native_key']=list(s.native.key)
            recipe['id']=digest({k:v for k,v in recipe.items() if k!='id'})

    def test_same_exposure_duplicate_token_and_labels(self):
        legs,p,e=pair(flat='0')
        legs[1].sign=legs[0].sign
        self.assertIn('same_decisive',evaluate(legs)['reasons'][0])
        self.assertIn('duplicate',evaluate([legs[0],legs[0]])['reasons'][0])
        legs,p,e=pair(flat='0')
        self.assertFalse(evaluate(legs,quantities=('100','1'))['model_available'])
        # Labels are presentation only; native cashflows establish opposition.
        legs[0].q['display']={'american':'NO'};legs[1].q['display']={'american':'YES'}
        self.assertTrue(evaluate(legs,quantities=('100','100'))['model_available'])

    def test_reference_free_conflicting_reference_and_conditional(self):
        legs,p,e=exact_example()
        for leg in legs:leg.reference=None;leg.weight=None
        r=evaluate(legs,quantities=('1010','1010'))
        self.assertTrue(r['model_available']);self.assertIsNone(r['buffered_profit_usd'])
        self.assertEqual(r['decisive_minimum_usd'],'10.2');self.assertEqual(r['all_state_minimum_usd'],'-252.4')
        legs,p,e=exact_example();legs[0].funding['state_cashflows']['tie']=None;legs[0].cache.clear()
        r=evaluate(legs,quantities=('1010','1010'))
        self.assertEqual(r['conditioning'],'modeled_conditional');self.assertEqual(sum(map(F,r['conditional_probabilities'].values())),1)
        self.assertEqual(r['conditional_decisive_profit_usd'],'10.2');self.assertIsNone(r['all_state_minimum_usd'])
        self.assertEqual(r['category'],'Estimated hedge')

    def test_joint_windows_weights_one_mass_and_zero_prior_adversity(self):
        legs,p,e=pair(flat='0',compatible=False)
        basis=joint_basis(legs);self.assertEqual(len(basis),10)
        weights={s:'0' for s,row in basis.items() if row['terminal']};weights['terminal_noncompletion']='1'
        r=evaluate(legs,quantities=('100','100'),terminal_weights=weights,policy=replace(DEFAULT_POLICY,tie='0',terminal_noncompletion='0'))
        self.assertTrue(r['model_available'],r);self.assertEqual(sum(map(F,r['probabilities'].values())),1)
        self.assertLess(F(r['all_state_minimum_usd']),0);self.assertEqual(r['category'],'Estimated hedge')
        conditional=evaluate(legs,quantities=('100','100'))
        self.assertEqual(conditional['conditioning'],'modeled_conditional')
        bad=evaluate(legs,quantities=('100','100'),terminal_weights={s:'1' for s in weights})
        self.assertFalse(bad['model_available'])
        # One grade home_win and other refund uses disjoint state receipts.
        self.assertEqual(r['states']['terminal_grade_0_a_wins']['cells'],['home_win','terminal_noncompletion'])

    def test_negative_minimum_spend_and_both_objectives(self):
        legs,p,e=pair(prices=('0.6','0.6'),flat='0')
        r=evaluate(legs);self.assertEqual([l['native_quantity'] for l in r['legs']],['25','25'])
        self.assertEqual(r['decisive_minimum_usd'],'-5');self.assertEqual(r['unused_cash_usd'],'970')
        self.assertEqual(set(r['search']['objective_allocations']),{'decisive_max_min','all_modeled_states_max_min'})
        legs,p,e=pair();d=evaluate(legs);all_states=evaluate(legs,objective='all_modeled_states_max_min')
        self.assertTrue(all_states['model_available']);self.assertLessEqual(F(all_states['deployed_capital_usd']),F(d['deployed_capital_usd']))

    def test_holds_allowances_refunds_withholding_and_grids(self):
        holds=tuple([FundingComponent('authored hold','20','refundable_hold','entry')])
        allowances=tuple([FundingComponent('authored allowance','3','consumed_allowance','entry')])
        legs,p,e=pair(flat='0',funding=[dict(extra_funding=holds,hold_returns_usd={s:'20' for s in ('home_win','away_win','tie','terminal_noncompletion')}),dict(extra_funding=allowances)])
        r=evaluate(legs,quantities=('100','100'));self.assertTrue(r['model_available'],r)
        self.assertEqual(r['deployed_capital_usd'],'121');self.assertEqual(r['decisive_minimum_usd'],'-1')
        self.assertEqual(r['cost_breakdown']['extra_funding_usd'],'23')
        legs,p,e=pair(flat='0');legs[0].increment=F(3);legs[0].lower=legs[0].ceil(F(25))
        r=evaluate(legs);self.assertEqual((F(r['legs'][0]['native_quantity'])-1)%3,0)
        refused=evaluate(legs,quantities=('26','100'));self.assertFalse(refused['model_available'])

    def test_fixed_buffer_prior_payout_and_reprice_sensitivity(self):
        legs,p,e=exact_example();r=evaluate(legs,quantities=('1010','1010'),details=True)
        rows=r['sensitivity']['buffer'];self.assertEqual(F(rows[0]['buffered_expected_profit_usd'])-F(rows[-1]['buffered_expected_profit_usd']),F('9.998'))
        self.assertEqual(r['sensitivity']['allocation'],'fixed_selected_quantities_and_fills')
        self.assertTrue(r['sensitivity']['terminal_payout']);self.assertTrue(r['sensitivity']['repriced_residual'])
        self.assertEqual(r['sensitivity']['repriced_residual'][0]['kind'],'repriced_fixed_quantity; no resizing')

    def test_small_exhaustive_grid_independent_objective(self):
        legs,p,e=pair(flat='0');policy=replace(DEFAULT_POLICY,capital_ceiling_usd='32')
        for leg in legs:leg.increment=F(10);leg.lower=leg.ceil(F(25))
        r=evaluate(legs,policy=policy)
        oracle=[]
        for a in range(31,134,10):
            for b in range(31,44,10):
                capital=a*F('.24')+b*F('.74')
                if capital<=32 and min(a,b)>=F('.2')*(a+b):oracle.append((min(a,b)-capital,capital,a,b))
        best=max(oracle,key=lambda x:(x[0],-x[1],x[2:]))
        self.assertEqual(F(r['decisive_minimum_usd']),best[0]);self.assertTrue(r['search']['global_optimality_proven'])

    def test_current_full_incremental_two_group_details_either_leg_and_old_reader(self):
        from tests.ev05_workload import workload
        from tests.current_fixture import InjectedTestProvider
        from app.dashboard.current_contract import serialize,quotes_of,packed,validate_snapshot
        from app.dashboard.current_state import CurrentStore
        raw=cross_group_workload();store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
        event=store._state['events'][0];self.assertTrue(event['funded_pairs'])
        self.assertEqual(len(event['groups']),2)
        pair=next(p for p in event['funded_pairs'] if p['legs'][0]['group_id']!=p['legs'][1]['group_id']);q=pair['legs'][0];request=dict(runtime_id=raw['runtime_id'],state_revision=1,quote_id=q['quote_id'])
        details=store.details(request);full=next(r for r in details['funded_pairs'] if r['id']==pair['id'])
        self.assertEqual(compact(full),pair);self.assertEqual(full['state_revision'],1)
        self.assertEqual(len(full['legs']),2)
        lease=store.create(dict(schema='predict-current-1',**request,quote_revision=q['quote_revision'],client_id='authored:ev06:other-leg'))
        frozen=packed(lease['review']);token=lease['selection_id']
        self.assertEqual(lease['status'],'held')
        self.assertIs(validate_snapshot(store._state,allow_synthetic=True),store._state)
        old=serialize(raw,allow_synthetic=True,paired=False);self.assertIs(validate_snapshot(old,allow_synthetic=True),old)
        # Mutating the second original quote invalidates the pair even though
        # selected leg is unchanged. Exact full rebuild is the independent oracle.
        second=store.index(store._state)[pair['legs'][1]['quote_id']]['quote']['source']['native_outcome_id'];changed=deepcopy(raw);changed['state_revision']=2
        for e in changed['events']:
            for g in e['groups']:
                for o in g['outcomes']:
                    for quote in quotes_of(o):
                        if quote['source']['native_outcome_id']==second:quote['revision']+=1;quote['original']['value']='0.55'
        self.assertTrue(store.commit(changed))
        self.assertEqual(packed(store._state),packed(serialize(changed,allow_synthetic=True)))
        self.assertNotEqual(next(r for r in store._state['events'][0]['funded_pairs'] if r['id']==pair['id'])['revision'],pair['revision'])
        newer=store.get(token)
        self.assertEqual(newer['status'],'newer_available');self.assertEqual(packed(newer['review']),frozen)
        removed=deepcopy(changed);removed['state_revision']=3
        removed['events'][0]['groups']=[g for g in removed['events'][0]['groups'] if g['id']==q['group_id']]
        self.assertTrue(store.commit(removed));self.assertEqual(store.get(token)['status'],'newer_available')
        self.assertEqual(packed(store.get(token)['review']),frozen)
        with self.assertRaises(Exception):store.details(request)


    def test_selected_pool_consumer_refunds_additional_and_withheld(self):
        def prepared(pool=True,additional=False,withheld=False):
            legs=[];profiles={}
            for i,predicate in enumerate(('win','not_win')):
                q,p,ctx=vector('prophetx','0.5',predicate=predicate);q['id']='pool-leg:'+str(i)
                q['source']['native_outcome_id']+=':'+str(i);self._rebind_native(q,p)
                _,_,args=setup_case('prophetx')
                rule=replace(args['registry'].rules[0],market_id=None,event_id=None,
                    terms=FeeTerms('net_gain','0.02','0.01','ceiling',None,'taker'),
                    settlement_status='known_terms' if additional and i==0 else 'declared_zero',
                    settlement_terms=FeeTerms('net_gain','0.03','0.01','ceiling',None,'taker') if additional and i==0 else None,
                    settlement_treatment='already_withheld_from_payout' if withheld and i==0 else 'separate_charge')
                payload=json.loads(json.dumps(dict(rule=rule.to_dict())))
                if pool:payload['commission_pool']=dict(venue='prophetx',channel='controlled',market_id='authored-exact-commission')
                bind(q,p,'fee',payload)
                profiles.update(p)
                if legs:bind(q,profiles,'reference',profiles[legs[0].q['comparison_input_refs']['refs']['reference']]['payload'])
                funding={}
                if withheld and i==0:funding=dict(settlement_charge_already_withheld=True,
                    state_cashflows=dict(home_win='0',away_win='197',tie='100',terminal_noncompletion='100'))
                leg=Leg(q,ctx['group'],profiles,ctx['event'],AT,funding=funding)
                leg.conditions=dict(kind='authored_completed_assumption');legs.append(leg)
            return legs
        shared=evaluate(prepared(),quantities=('100','90'))
        independent=evaluate(prepared(False),quantities=('100','90'))
        self.assertEqual(shared['states']['b_wins']['settlement_charge_usd'],'0.2')
        self.assertEqual(independent['states']['b_wins']['settlement_charge_usd'],'2')
        extra=evaluate(prepared(additional=True),quantities=('100','90'))
        self.assertEqual(extra['states']['b_wins']['settlement_charge_usd'],'3.2')
        held=evaluate(prepared(additional=True,withheld=True),quantities=('100','90'))
        self.assertEqual(held['states']['b_wins']['settlement_charge_usd'],'0.14')
        self.assertEqual(held['states']['b_wins']['profit_usd'],'6.86')

    def test_shared_observed_liquidity_and_source_boundaries(self):
        from datetime import timedelta
        legs,p,e=pair(flat='0')
        for leg in legs:leg.liquidity_ids={'same-visible-allowance'}
        refused=evaluate(legs,quantities=('100','100'));self.assertIn('duplicated fill',refused['reasons'][0])
        q,p,ctx=vector('polymarket_us');q['depth']=[dict(price='0.5',quantity='10',liquidity_id='same'),dict(price='0.5',quantity='10',liquidity_id='same')]
        with self.assertRaisesRegex(ValueError,'duplicate_observed_liquidity'):Leg(q,ctx['group'],p,ctx['event'],AT)
        q,p,ctx=vector('polymarket_us');stale=Leg(q,ctx['group'],p,ctx['event'],AT+timedelta(seconds=901))
        self.assertIn('source_price_expired',stale.rank_reasons)
        with self.assertRaisesRegex(ValueError,'pregame_phase_ended'):Leg(q,ctx['group'],p,ctx['event'],AT+timedelta(days=2))

    def test_strict_positive_complete_basis_and_fixed_zero_prior_loss(self):
        legs,p,e=exact_example();zero=replace(DEFAULT_POLICY,tie='0',terminal_noncompletion='0')
        result=evaluate(legs,quantities=('1010','1010'),policy=zero)
        self.assertGreater(F(result['buffered_profit_usd']),0);self.assertEqual(result['category'],'Estimated hedge')
        for leg in legs:
            leg.funding['state_cashflows'].update(tie='506',terminal_noncompletion='506');leg.cache.clear()
        result=evaluate(legs,quantities=('1010','1010'))
        self.assertEqual(result['category'],'Positive across modeled outcomes')
        self.assertEqual(result['buffered_all_state_minimum_usd'],'5.201')

    def test_completion_window_order_excludes_impossible_shorter_only_grade(self):
        legs,p,e=pair(flat='0',compatible=False)
        for leg,hours in zip(legs,('24','48')):
            leg.conditions=dict(kind='starts_within_hours',maximum=hours,original_start=AT.isoformat(),
                original_scheduled_date='2026-10-11',date_timezone='UTC')
        basis=joint_basis(legs)
        self.assertFalse(any(s.startswith('terminal_grade_0') for s in basis))
        self.assertTrue(any(s.startswith('terminal_grade_1') for s in basis))

    def test_either_group_removal_alternative_revision_matching_and_expiry(self):
        from app.dashboard.current_contract import serialize,quotes_of,packed
        from app.dashboard.current_state import CurrentStore
        from tests.current_fixture import InjectedTestProvider
        raw=cross_group_workload();store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
        event=store._state['events'][0]
        cross=next(p for p in event['funded_pairs'] if p['legs'][0]['group_id']!=p['legs'][1]['group_id'])
        removed=deepcopy(raw);removed['state_revision']=2;removed['events'][0]['groups']=removed['events'][0]['groups'][:1]
        self.assertTrue(store.commit(removed));self.assertEqual(packed(store._state),packed(serialize(removed,allow_synthetic=True)))
        self.assertFalse(any(p['id']==cross['id'] for p in store._state['events'][0]['funded_pairs']))
        revised=deepcopy(raw);revised['state_revision']=3
        target=store.index(store._state)[cross['legs'][0]['quote_id']]['quote']['source']['native_outcome_id']
        for g in revised['events'][0]['groups']:
            for o in g['outcomes']:
                for q in quotes_of(o):
                    if q['source']['native_outcome_id']==target:q['state']='unavailable';q['revision']+=1
        self.assertTrue(store.commit(revised));self.assertEqual(packed(store._state),packed(serialize(revised,allow_synthetic=True)))
        affected=[p for p in store._state['events'][0]['funded_pairs'] if p['id']==cross['id']]
        self.assertTrue(not affected or not affected[0]['ranking_eligible'])
        if affected:self.assertNotEqual(affected[0]['revision'],cross['revision'])

    def test_actual_missing_reference_inputs_and_selected_predicate_conflict(self):
        legs,profiles,event=pair(flat='0')
        prepared=[]
        for leg in legs:
            q=deepcopy(leg.q);q['comparison_input_refs']['refs']['reference']=None
            q['comparison_input_status']['reference']=dict(status='absent',reason='authored_reference_missing')
            rebuilt=Leg(q,leg.group,profiles,event,AT);rebuilt.conditions=leg.conditions;prepared.append(rebuilt)
        result=evaluate(prepared,quantities=('100','100'))
        self.assertTrue(result['model_available']);self.assertIsNone(result['buffered_profit_usd'])
        self.assertIsNotNone(result['all_state_minimum_usd'])
        from app.comparison.domain import CanonicalSelection
        q=deepcopy(legs[0].q);p=deepcopy(profiles)
        identity=deepcopy(p[q['comparison_input_refs']['refs']['identity']]['payload'])
        selected=CanonicalSelection.from_dict(identity['selection'])
        selected=replace(selected,predicate=replace(selected.predicate,operator='gt' if selected.predicate.operator=='lt' else 'lt'))
        identity['selection']=selected.to_dict();bind(q,p,'identity',identity)
        with self.assertRaisesRegex(ValueError,'predicate_conflict'):Leg(q,legs[0].group,p,event,AT)


if __name__=='__main__':unittest.main()
