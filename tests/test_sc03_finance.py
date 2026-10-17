"""Independent authored SC03 arithmetic; no provider or owner acceptance.

Expected amounts below are calculated directly from fill prices, stakes, fee
rules and refunds. Existing fixtures supply typed source/model bindings only.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.comparison.costs import FundingComponent, FeeTerms, CostRule, UnitSpec
from app.comparison.current_dependencies import references
from app.comparison.estimated_pair import Leg
from app.comparison.estimated_policy import EstimatePolicy, RequestedTradePolicy
from app.comparison.requested_sizing import allocations
from app.comparison.net_costs import wire
from app.comparison.scanner_ticket_finance import calculate
from tests.test_ev04_content import AT
from tests.test_ev05_funded import vector, bind
from tests.test_ev06_pairs import pair


def selected(legs, amount='100', **kw):
    inputs={str(i):dict(quote=x.q,group=x.group,profiles=x.profiles,event=x.event) for i,x in enumerate(legs)}
    instruments={k:dict(checks=dict(ev=dict(state='ready'))) for k in inputs}
    policy=EstimatePolicy(capital_ceiling_usd=amount)
    with patch('app.comparison.scanner_ticket_finance.Leg',side_effect=legs):
        return calculate(dict(legs=list(inputs)),instruments,inputs,at=AT.isoformat(),policy=policy,**kw)


def contracts(prices=('.24','.74'),flat='0',depth=10000,**kw):
    legs,_,_=pair(prices=prices,flat=flat,**kw)
    for x in legs:x.path['levels']=[(F(price),F(depth)) for price in [x.q['original']['value']]]
    return legs


def stakes(odds=('2','4'),depth=10000):
    legs=[]
    for venue,predicate,odds_value in zip(('novig','prophetx'),('win','not_win'),odds):
        q,p,c=vector(venue,predicate=predicate)
        q['original']['value']=odds_value
        q['depth']=[dict(price=odds_value,quantity=str(depth))]
        # Explicit authored cent stake grid; no assertion about venue rules.
        bind(q,p,'quantity',dict(grid=dict(minimum_native='0.01',increment_native='0.01',legal_price_tick=None),grid_qualification='authored'))
        from tests.test_comparison_net_costs import setup_case
        _,_,args=setup_case(venue)
        rule=CostRule.from_dict(args['registry'].data['rules'][0])
        rule=replace(rule,unit=UnitSpec('stake_usd'),terms=FeeTerms('notional','0','0.01','half_even','order','taker'))
        bind(q,p,'fee',json.loads(json.dumps(dict(rule=rule.to_dict()))))
        if legs:bind(q,p,'reference',references(legs[0].q,legs[0].profiles)['reference']['payload'])
        leg=Leg(q,c['group'],p,c['event'],AT)
        leg.conditions=dict(kind='authored_common_grading')
        legs.append(leg)
    return legs


def authored_finance_fixture(amount='100',prices=('0.2','0.2'),depth=1000,kind='native'):
    """Unpatched (pair, instruments, inputs, policy) for integrated SC03 tests.

    All depth/prices/completion conditions are authored. 'stake' uses native
    stake observations and 'mixed' joins one stake with one contract. This
    helper is calculation evidence, never source/destination qualification.
    """
    legs=(stakes() if kind=='stake' else contracts(prices=prices,depth=depth))
    if kind=='mixed':legs[0]=stakes()[0]
    inputs={};instruments={}
    for index,leg in enumerate(legs):
        q,p,e,g=deepcopy((leg.q,leg.profiles,leg.event,leg.group))
        q['depth']=[dict(price=str(price),quantity=str(n)) for price,n in leg.path['levels']]
        from app.comparison.payouts import PayoutProfile, CompletionContext, selection_digest
        from app.comparison.domain import CanonicalSelection
        identity=deepcopy(references(q,p)['identity']['payload'])
        selection=CanonicalSelection.from_dict(identity['selection'])
        payout=deepcopy(json.loads(Path('app/fixtures/comparison-payouts-v1.json').read_text())['profile_rows'][0]['profile'])
        stake=leg.unit.unit=='stake_usd';win=wire(F(q['original']['value'])) if stake else '1'
        payout.update(profile_id='authored-sc03-payout:'+str(index),rule_revision='authored-sc03-payout-1',
            native_key=list(selection.native.key),selection_sha256=selection_digest(selection),
            payout_unit='usd_per_usd_stake' if stake else 'usd_per_contract',
            effective_from=AT.isoformat(),effective_until=None,refund_fees='retained',
            source_evidence=[dict(ref='authored:sc03:payout',sha256='a'*64,evidence_class='authored')],
            normal_condition=dict(kind='authored_completed_assumption',maximum=None,original_start=None,original_scheduled_date=None,date_timezone=None))
        values=dict(above=win if leg.sign>0 else '0',below='0' if leg.sign>0 else win,
                    equal='1' if stake else '0.5',noncompleted='1' if stake else wire(F(q['original']['value'])))
        for name,value in values.items():payout[name]=dict(value=value,status='estimated',reason='Authored SC03 arithmetic vector')
        payout=PayoutProfile.from_dict(payout)
        identity.update(rule_revision=payout.rule_revision,completion_context=CompletionContext(None,None,'America/New_York',selection.native.evidence).to_dict())
        bind(q,p,'identity',identity);bind(q,p,'payout',payout.to_dict())
        q['times'].update(source_at=AT.isoformat(),received_at=AT.isoformat(),projected_at=AT.isoformat())
        key=str(index)
        inputs[key]=dict(quote=q,profiles=p,event=e,group=g)
        instruments[key]=dict(id=key,checks=dict(ev=dict(state='ready')))
    return dict(id='authored-sc03-finance',legs=list(inputs)),instruments,inputs,EstimatePolicy(capital_ceiling_usd=amount)


def financial_reconciliation_evidence():
    """Exact authored inputs/results for closeout, with no writes or acquisition."""
    rows=[]
    for kind in ('native','stake','mixed'):
        for amount in ('40','500'):
            pair,instruments,inputs,policy=authored_finance_fixture(amount=amount,kind=kind)
            for index,x in enumerate(inputs.values()):
                stake=x['quote']['original']['units']=='decimal_odds'
                if stake:
                    top=x['quote']['original']['value'];quantity='30' if index==0 else '20'
                    x['quote']['depth']=[dict(price=top,quantity=quantity),dict(price='1.1',quantity='10000')]
                else:
                    x['quote']['depth']=[dict(price='0.2',quantity='100'),dict(price='0.9',quantity='10000')]
            result=calculate(pair,instruments,inputs,at=AT.isoformat(),policy=policy)
            rows.append(dict(name=kind+'-depth-'+amount,evidence_class='authored',
                pair=pair,instruments=instruments,inputs=inputs,at=AT.isoformat(),policy=policy.to_dict(),result=result))
    return dict(version='sc03-authored-financial-reconciliation-1',provider_requests=0,cases=rows)


class TicketFinance(TestCase):
    def test_unpatched_depth_budgets_reconcile_native_stake_and_mixed(self):
        cases=financial_reconciliation_evidence()['cases']
        self.assertEqual(len(cases),6)
        for case in cases:
            r=case['result'];capital=F(r['funding']['deployed_capital_usd'])
            self.assertEqual(capital+F(r['funding']['residual_cash_usd']),F(case['policy']['capital_ceiling_usd']))
            for leg in r['legs']:
                if leg['native_unit']['unit']=='stake_usd':
                    fills=leg['fills']['stake_fills']
                    expected_receipt=sum(F(f['stake_usd'])*F(f['decimal_odds']) for f in fills)
                    self.assertEqual(sum(F(f['stake_usd']) for f in fills),F(leg['native_quantity']))
                    self.assertEqual(F(leg['acquisition_usd']),F(leg['native_quantity']))
                else:
                    fills=leg['fills']['fills']
                    expected_receipt=F(leg['native_quantity'])
                    self.assertEqual(F(leg['acquisition_usd']),sum(F(f['price'])*F(f['quantity']) for f in fills))
                index=r['legs'].index(leg)
                receipts=[F(r['states'][s]['legs'][index]['receipt_usd']) for s in ('a_wins','b_wins')]
                self.assertEqual(max(receipts),expected_receipt)
                self.assertEqual(leg['modeled_native_quantity'],'0')
                if case['name'].endswith('-500'):self.assertEqual(len(fills),2)
            self.assertEqual(F(r['metrics']['buffer_usd']),capital/200)
        for small,large in zip(cases[::2],cases[1::2]):
            self.assertIn('conditional_hedge',[c['category'] for c in small['result']['categories']])
            self.assertNotIn('conditional_hedge',[c['category'] for c in large['result']['categories']])
    def test_unpatched_native_stake_mixed_fixtures_are_json_safe_and_input_immutable(self):
        for kind in ('native','stake','mixed'):
            with self.subTest(kind=kind):
                p,i,x,policy=authored_finance_fixture(kind=kind)
                before=deepcopy((p,i,x,policy))
                r=calculate(p,i,x,at=AT.isoformat(),policy=policy)
                self.assertEqual((p,i,x,policy),before)
                self.assertEqual(json.loads(json.dumps(r)),r)
                capital=F(r['funding']['deployed_capital_usd'])
                self.assertLessEqual(capital,100)
                self.assertEqual(sum(F(l['deployed_capital_usd']) for l in r['legs']),capital)
                self.assertEqual(F(r['funding']['residual_cash_usd']),100-capital)
                self.assertEqual(F(r['metrics']['buffer_usd']),capital/200)
                self.assertTrue(r['settlement_complete'])
                self.assertEqual(r['metrics']['buffer_applications'],1)

    def test_actual_ordinary_original_structure_with_authored_depth_two_leg_budget(self):
        from tests.test_ev09_n01 import envelopes,AT as READ_AT,SELECTED
        from app.comparison.combined_inputs import build
        from app.dashboard.current_contract import quotes_of
        from app.comparison.shared_templates import keys,resolve
        # Ordinary original structure is retained; injected depth is authored.
        state=build(envelopes(),at=READ_AT,selected=SELECTED)[0]['state_inputs']
        profiles={k:resolve(state['comparison_profiles'],k) for k in keys(state['comparison_profiles'])}
        candidates=[(e,g,q) for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)
                    if q['source']['provider']=='the_odds_api']
        chosen=[next(row for row in candidates if row[2]['venue']==v and row[2]['binding']['selection']['participant']==team)
                for v,team in (('novig','NFL:DEN'),('prophetx','NFL:SEA'))]
        inputs={}
        for index,(e,g,q) in enumerate(chosen):
            q=deepcopy(q);q['depth']=[dict(price=q['original']['value'],quantity='10000')]
            q['times'].update(source_at=READ_AT,received_at=READ_AT,projected_at=READ_AT)
            e=deepcopy(e);e['stage']='regular_season'
            bind(q,profiles,'quantity',dict(grid=dict(minimum_native='0.01',increment_native='0.01',legal_price_tick=None),grid_qualification='authored'))
            inputs[str(index)]=dict(quote=q,event=e,group=g,profiles=profiles)
        r=calculate(dict(legs=list(inputs)),{k:{} for k in inputs},inputs,at=READ_AT,
                    policy=EstimatePolicy(capital_ceiling_usd='100'))
        a,b=[F(l['native_quantity']) for l in r['legs']];capital=a+b
        # Authentic original odds: Novig Denver 2.3; ProphetX Seattle 1.75.
        # The selected named 2% standalone model rounds winning-gain commission up.
        gain=F('.75')*b;raw=F('.02')*gain
        fee=F(-(-100*raw.numerator//raw.denominator),100)
        self.assertEqual(F(r['funding']['deployed_capital_usd']),capital)
        self.assertEqual(F(r['states']['a_wins']['profit_usd']),F('2.3')*a-capital)
        self.assertEqual(F(r['states']['b_wins']['profit_usd']),F('1.75')*b-capital-fee)
        self.assertTrue(all(l['source']['provider']=='the_odds_api' for l in r['legs']))
        self.assertTrue(all(l['modeled_native_quantity']=='0' for l in r['legs']))

    def test_unpatched_ordinary_plus_native_depth_reconciles_one_requested_budget(self):
        from tests.test_ev09_n01 import envelopes,AT as READ_AT,SELECTED
        from app.comparison.combined_inputs import build
        from app.dashboard.current_contract import quotes_of
        from app.comparison.shared_templates import keys,resolve
        state=build(envelopes(),at=READ_AT,selected=SELECTED)[0]['state_inputs']
        profiles={k:resolve(state['comparison_profiles'],k) for k in keys(state['comparison_profiles'])}
        observations=[(e,g,q) for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]
        ordinary=next(row for row in observations if row[2]['source']['provider']=='the_odds_api' and
                      row[2]['venue']=='novig' and row[2]['binding']['selection']['participant']=='NFL:DEN')
        native=next(row for row in observations if row[2]['venue']=='polymarket_us' and row[2]['source']['native_side']=='Long')
        inputs={}
        for index,(e,g,q) in enumerate((ordinary,native)):
            q=deepcopy(q);e=deepcopy(e);e['stage']='regular_season'
            q['times'].update(source_at=READ_AT,received_at=READ_AT,projected_at=READ_AT)
            if index==0:
                q['depth']=[dict(price='2.3',quantity='30'),dict(price='1.1',quantity='10000')]
                bind(q,profiles,'quantity',dict(grid=dict(minimum_native='0.01',increment_native='0.01',legal_price_tick=None),grid_qualification='authored'))
            else:q['depth']=[dict(price='0.575',quantity='50'),dict(price='0.8',quantity='10000')]
            inputs[str(index)]=dict(quote=q,profiles=profiles,event=e,group=g)
        before=deepcopy(inputs)
        for amount in ('40','500'):
            r=calculate(dict(legs=list(inputs)),{k:{} for k in inputs},inputs,at=READ_AT,
                        policy=EstimatePolicy(capital_ceiling_usd=amount))
            self.assertEqual(inputs,before)
            capital=F(r['funding']['deployed_capital_usd'])
            self.assertLessEqual(capital,F(amount))
            self.assertEqual(capital+F(r['funding']['residual_cash_usd']),F(amount))
            self.assertEqual(r['legs'][0]['source']['provider'],'the_odds_api')
            self.assertEqual(r['legs'][1]['source']['provider'],'polymarket_us')
            stake=r['legs'][0];contract=r['legs'][1]
            gross=sum(F(f['stake_usd'])*F(f['decimal_odds']) for f in stake['fills']['stake_fills'])
            self.assertEqual(max(F(r['states'][s]['legs'][0]['receipt_usd']) for s in ('a_wins','b_wins')),gross)
            acquire=sum(F(f['price'])*F(f['quantity']) for f in contract['fills']['fills'])
            self.assertEqual(F(contract['acquisition_usd']),acquire)
            self.assertEqual(F(stake['acquisition_usd']),F(stake['native_quantity']))
            self.assertEqual(F(r['funding']['net_upfront_fee_usd']),
                             sum(F(l['net_upfront_fee_usd']) for l in r['legs']))
            self.assertTrue(all(l['modeled_native_quantity']=='0' for l in r['legs']))
            if amount=='500':
                self.assertEqual(len(stake['fills']['stake_fills']),2)
                self.assertEqual(len(contract['fills']['fills']),2)
                self.assertLess(F(r['metrics']['decisive_minimum_usd']['value']),0)

    def test_one_budget_two_native_contracts_flat_fees_and_exact_manual_rows(self):
        r=selected(contracts(flat='5'))
        # Equal $1 payouts at n=91 cost .24n + .74n + two $5 fees.
        n=F(91);capital=F('.98')*n+10;buffer=capital/200
        self.assertEqual([F(l['native_quantity']) for l in r['legs']],[n,n])
        self.assertEqual(F(r['funding']['deployed_capital_usd']),capital)
        self.assertEqual(F(r['funding']['residual_cash_usd']),100-capital)
        self.assertEqual(F(r['states']['a_wins']['profit_usd']),n-capital)
        self.assertEqual(F(r['states']['terminal_noncompletion']['profit_usd']),-10)
        self.assertEqual(F(r['metrics']['buffer_usd']),buffer)
        self.assertEqual(r['metrics']['buffer_applications'],1)
        self.assertEqual(len(r['manual_legs']),2)
        self.assertEqual(r['manual_legs'][0]['predicate'],r['legs'][0]['predicate'])
        self.assertEqual(F(r['manual_legs'][0]['american_odds']),F(950,3))
        self.assertEqual(F(r['manual_legs'][1]['american_odds']),-F(3700,13))
        self.assertEqual(r['policy']['sizing_mode'],'requested_trade')
        self.assertEqual(r['policy']['requested_amount_usd'],'100')
        self.assertEqual(json.loads(json.dumps(r)),r)

    def test_ordinary_stake_arithmetic_and_opposing_native_actions(self):
        r=selected(stakes(),amount='150')
        # 2x $100 and 4x $50 return $200 in either decisive outcome.
        self.assertEqual([F(l['native_quantity']) for l in r['legs']],[100,50])
        self.assertEqual(F(r['funding']['deployed_capital_usd']),150)
        self.assertEqual(F(r['states']['a_wins']['profit_usd']),50)
        self.assertEqual(F(r['states']['b_wins']['profit_usd']),50)
        self.assertEqual([l['american_odds'] for l in r['manual_legs']],['100','300'])
        self.assertTrue(all(l['native_unit']['unit']=='stake_usd' for l in r['legs']))
        self.assertEqual(F(r['metrics']['decisive_minimum_usd']['value']),F('49.25'))

    def test_observed_depth_partial_budget_never_probes_or_models_residual(self):
        legs=contracts(prices=('.2','.2'),depth=40)
        for leg in legs:
            original=leg.get
            def guarded(n,original=original,**kw):
                self.assertLessEqual(n,40,'sizing must never extrapolate even for derivatives')
                return original(n,**kw)
            leg.get=guarded
        r=selected(legs,amount='1000')
        self.assertEqual([l['native_quantity'] for l in r['legs']],['40','40'])
        self.assertEqual(r['funding']['deployed_capital_usd'],'16')
        self.assertEqual(r['funding']['residual_cash_usd'],'984')
        self.assertTrue(all(l['modeled_native_quantity']=='0' for l in r['legs']))
        self.assertFalse(r['search']['maximum_size_proven'])
        self.assertFalse(r['search']['global_optimality_proven'])

    def test_unequal_observed_bounds_balance_opposite_instead_of_spending_residual(self):
        legs=contracts(prices=('.2','.2'),depth=1000)
        legs[0].path['levels']=[(F('.2'),F(40))]
        r=selected(legs,amount='1000')
        self.assertEqual([l['native_quantity'] for l in r['legs']],['40','40'])
        self.assertEqual(r['funding']['deployed_capital_usd'],'16')

    def test_depth_worsens_large_requested_trade_instead_of_discovery_best_size(self):
        def prepare():
            legs=contracts(prices=('.2','.2'))
            for leg in legs:leg.path['levels']=[(F('.2'),F(100)),(F('.7'),F(10000))]
            return legs
        small=selected(prepare(),amount='40');large=selected(prepare(),amount='200')
        self.assertEqual([l['native_quantity'] for l in small['legs']],['100','100'])
        self.assertEqual([l['native_quantity'] for l in large['legs']],['214','214'])
        self.assertEqual(large['funding']['deployed_capital_usd'],'199.6')
        # Independent exact large-fill acquisition: 2*(100*.2 + 114*.7).
        self.assertEqual(F(large['funding']['acquisition_usd']),2*(100*F('.2')+114*F('.7')))
        self.assertGreater(F(small['metrics']['decisive_minimum_usd']['value'])/40,
                           F(large['metrics']['decisive_minimum_usd']['value'])/F('199.6'))

    def test_unknown_and_incomparable_completion_meaning_never_invents_joint_states(self):
        for conditions in ((None,None),({'kind':'first'},{'kind':'second'})):
            legs=contracts(prices=('.2','.2'),depth=100)
            for leg,condition in zip(legs,conditions):leg.conditions=condition
            r=selected(legs,amount='40')
            self.assertFalse(r['settlement_complete'])
            self.assertEqual(set(r['states']),{'a_wins','b_wins','tie'})
            self.assertIsNone(r['metrics']['complete_minimum_usd'])
            self.assertIn('conditional_hedge',[c['category'] for c in r['categories']])
            self.assertNotIn('covered_outcome_arb',[c['category'] for c in r['categories']])
            self.assertIn('joint_settlement_meaning_unknown',r['reasons'])

    def test_nested_windows_keep_only_feasible_asymmetric_states(self):
        legs=contracts(prices=('.2','.2'),depth=100)
        for leg,hours in zip(legs,('24','48')):
            leg.conditions=dict(kind='starts_within_hours',maximum=hours,original_start=AT.isoformat())
        r=selected(legs,amount='40')
        self.assertTrue(r['settlement_complete'])
        self.assertTrue(any(s.startswith('terminal_grade_1') for s in r['states']))
        self.assertFalse(any(s.startswith('terminal_grade_0') for s in r['states']))

    def test_reference_missing_preserves_scenarios_mandatory_unknown_refuses(self):
        legs=contracts(prices=('.2','.2'),depth=100)
        for leg in legs:leg.reference=None;leg.weight=None
        r=selected(legs,amount='40')
        self.assertNotIn('ev',[c['category'] for c in r['categories']])
        self.assertIsNone(r['metrics']['expected_profit_usd'])
        self.assertIsNotNone(r['metrics']['decisive_minimum_usd'])
        leg=legs[0];original=leg.get
        def unknown(n,**kw):
            c=deepcopy(original(n,**kw))
            c['components']['payout']['receipt_usd:tie']['modeled_value']=None
            return c
        leg.get=unknown
        with self.assertRaisesRegex(ValueError,'mandatory_state_cashflows_unknown'):
            selected(legs,amount='40')

    def test_independent_holds_consumed_allowances_and_legal_grid(self):
        holds=(FundingComponent('authored hold','20','refundable_hold','entry'),)
        spent=(FundingComponent('authored allowance','3','consumed_allowance','entry'),)
        legs=contracts(prices=('.2','.2'),depth=1000,funding=[
            dict(extra_funding=holds,hold_returns_usd={s:'20' for s in ('home_win','away_win','tie','terminal_noncompletion')}),
            dict(extra_funding=spent)])
        for leg in legs:
            leg.minimum=F(1);leg.increment=F(3);leg.lower=leg.ceil(F(25))
        r=selected(legs,amount='100')
        n=F(r['legs'][0]['native_quantity']);capital=F('.4')*n+23
        self.assertEqual((n-1)%3,0)
        self.assertEqual(F(r['funding']['independent_funding_usd']),23)
        self.assertEqual(F(r['funding']['deployed_capital_usd']),capital)
        self.assertLessEqual(capital,100)
        self.assertEqual(F(r['states']['a_wins']['profit_usd']),n+20-capital)
        self.assertEqual(F(r['states']['terminal_noncompletion']['profit_usd']),-3)
        self.assertEqual(F(r['metrics']['buffer_usd']),capital/200)

    def test_shared_depth_and_insufficient_meaningful_exposure_refuse(self):
        legs=contracts()
        for leg in legs:leg.shared_depth='authored-resource'
        with self.assertRaisesRegex(ValueError,'shared_depth_conflict'):selected(legs)
        legs=contracts(depth=24)
        with self.assertRaisesRegex(ValueError,'depth_below_meaningful_minimum'):selected(legs)
        with self.assertRaisesRegex(ValueError,'no_feasible_observed_requested_allocation'):
            selected(contracts(),amount='1')

    def test_final_nonlinear_entry_fee_is_recomputed_at_allocation(self):
        legs=contracts(prices=('.4','.4'),depth=1000)
        for leg in legs:
            payload=deepcopy(references(leg.q,leg.profiles)['fee']['payload'])
            rule=CostRule.from_dict(payload['rule'])
            # Authored convex probability charge, rounded up per whole order.
            payload['rule']=replace(rule,terms=FeeTerms('quadratic','0.07','0.01','ceiling','order','taker')).to_dict()
            bind(leg.q,leg.profiles,'fee',json.loads(json.dumps(payload)))
            leg.inputs=None
        # Reconstruct to ensure the consumer reads changed fee profiles.
        rebound=[]
        for leg in legs:
            leg.q['depth']=[dict(price='.4',quantity='1000')]
            x=Leg(leg.q,leg.group,leg.profiles,leg.event,AT)
            x.conditions=leg.conditions;rebound.append(x)
        r=selected(rebound,amount='100')
        n=F(r['legs'][0]['native_quantity'])
        raw=F('.07')*n*F('.4')*F('.6')
        fee=F(-(-100*raw.numerator//raw.denominator),100)
        self.assertEqual(F(r['funding']['net_upfront_fee_usd']),2*fee)
        self.assertEqual(F(r['funding']['deployed_capital_usd']),F('.8')*n+2*fee)

    def test_venue_commission_pools_caps_and_independence_recomputed(self):
        prepared=[]
        for leg in stakes():
            payload=deepcopy(references(leg.q,leg.profiles)['fee']['payload'])
            rule=CostRule.from_dict(payload['rule'])
            payload['rule']=replace(rule,terms=FeeTerms('net_gain','0.02','0.01','ceiling',None,'taker')).to_dict()
            payload['commission_pool']=dict(venue=leg.q['venue'],channel=rule.channel,
                                           market_id='authored-pool',cap_usd='0.1')
            bind(leg.q,leg.profiles,'fee',json.loads(json.dumps(payload)))
            rebuilt=Leg(leg.q,leg.group,leg.profiles,leg.event,AT)
            rebuilt.conditions=leg.conditions;prepared.append(rebuilt)
        r=selected(prepared,amount='150')
        self.assertEqual([l['native_quantity'] for l in r['legs']],['100','50'])
        self.assertEqual(r['states']['a_wins']['settlement_charge_usd'],'0.1')
        self.assertEqual(r['states']['b_wins']['settlement_charge_usd'],'0.1')
        self.assertEqual(r['states']['a_wins']['profit_usd'],'49.9')
        self.assertEqual(r['states']['b_wins']['profit_usd'],'49.9')
        self.assertNotEqual(r['legs'][0]['settlement_terms'][0]['pool']['venue'],
                            r['legs'][1]['settlement_terms'][0]['pool']['venue'])

    def test_legacy_requested_solver_default_output_and_optional_bounds(self):
        from app.comparison.estimated_pair import economics
        from app.comparison.scanner_finance import _joint
        legs=contracts();basis,_=_joint(legs)
        unbounded,search=allocations(legs,F(100),basis,economics)
        wide,wide_search=allocations(legs,F(100),basis,economics,observed_bounds=[F(10000)]*2)
        self.assertEqual(unbounded,wide)
        self.assertEqual(search,wide_search)
        self.assertEqual(search['continuous_target_quantities'],['102','102'])
        bounded,_=allocations(legs,F(100),basis,economics,observed_bounds=[F(40),F(50)])
        self.assertTrue(all(a<=40 and b<=50 for a,b in bounded))

