"""Independent authored SC02 financial vectors, never evidence of live prices."""
import json
from pathlib import Path
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
from unittest import TestCase
from unittest.mock import patch

from app.comparison.scanner_finance import classify, evaluate, opportunity_identity
from app.comparison.estimated_pair import economics, joint_basis
from app.comparison.estimated_policy import LEGACY_POLICY
from app.comparison.current_dependencies import instant
from tests.test_ev06_pairs import pair, exact_example
from tests.test_ev04_content import AT
from tests.test_sc01_readiness import pair_rows

VECTORS=Path(__file__).parent/'fixtures/sc02-financial-vectors.json'


class Finance(TestCase):
    def test_independent_vector_table(self):
        for vector in json.loads(VECTORS.read_text()):
            with self.subTest(vector['name']):
                states={k:dict(profit_usd=v) for k,v in vector['profits'].items()}
                metrics,rows=classify(states,vector['capital'],policy=LEGACY_POLICY,
                    settlement_complete=vector.get('settlement_complete',True),
                    probabilities=vector.get('probabilities'))
                self.assertEqual([r['category'] for r in rows],vector['categories'])
                self.assertEqual(metrics['complete_minimum_usd'],None if vector['minimum'] is None else
                    dict(value=vector['minimum'],display=vector['minimum_display']))
                self.assertEqual(F(metrics['buffer_usd']),F(vector['capital'])/200)
                self.assertEqual(metrics['buffer_applications'],1)

    def test_real_fee_cashflow_owner_refund_asymmetric_and_adverse_tie(self):
        legs,_,_=exact_example();basis=joint_basis(legs)
        capital,states=economics([x.get(F(1010)) for x in legs],basis)
        self.assertEqual(capital,F('999.8'))
        self.assertEqual(states['a_wins']['profit_usd'],'10.2')
        self.assertEqual(states['tie']['profit_usd'],'-252.4')
        self.assertEqual(states['terminal_noncompletion']['profit_usd'],'-10')
        metrics,rows=classify(states,capital,policy=LEGACY_POLICY)
        self.assertEqual(F(metrics['complete_minimum_usd']['value']),F('-257.399'))
        self.assertEqual([r['category'] for r in rows],['conditional_hedge'])
        legs[1].conditions=dict(legs[1].conditions,kind='authored_different')
        _,states=economics([x.get(F(1010)) for x in legs],joint_basis(legs))
        self.assertEqual(len(states),10)
        self.assertTrue(any(F(v['profit_usd'])<0 for k,v in states.items() if k.startswith('terminal_grade')))

    def evaluate_fixture(self,legs,policy=LEGACY_POLICY):
        # Only construction is substituted: real Leg.get, depth, legal grid,
        # cashflow, fees, collateral and allocation code execute unchanged.
        ids=['a','b'];p=dict(legs=ids)
        inputs={k:dict(quote=x.q,group=x.group,profiles=x.profiles,event=x.event) for k,x in zip(ids,legs)}
        instruments={k:dict(checks=dict(ev=dict(state='unsupported'))) for k in ids}
        with patch('app.comparison.scanner_finance.Leg',side_effect=legs):
            return evaluate(p,instruments,inputs,at=AT.isoformat(),policy=policy)

    def test_partial_deployment_observed_only_and_no_ev_reference(self):
        legs,_,_=pair(prices=('.2','.2'),flat='0')
        for x in legs:
            x.path['levels']=[(F('.2'),F(30))]
            x.weight=None;x.reference=None
        result=self.evaluate_fixture(legs)
        self.assertTrue(result['evaluated']);self.assertLessEqual(result['search']['evaluations'],256)
        self.assertFalse(result['search']['maximum_size_proven'])
        self.assertTrue(result['rows'])
        self.assertTrue(all(F(r['supported_capital_usd'])<=12 for r in result['rows']))
        self.assertTrue(all(F(a['native_quantity'])<=30 for r in result['rows'] for a in r['allocation']))
        self.assertFalse(any(r['category']=='ev' for r in result['rows']))

    def test_insufficient_observed_depth_has_no_modeled_residual(self):
        legs,_,_=pair(flat='0')
        for x in legs:x.path['levels']=[(F('.2'),F(1))]
        result=self.evaluate_fixture(legs)
        self.assertEqual(result['rows'],[])
        self.assertEqual(result['reasons'],['no_supported_meaningful_allocation'])

    def test_shared_liquidity_refused(self):
        legs,_,_=pair(flat='0')
        for x in legs:x.shared_depth='authored-shared'
        with self.assertRaisesRegex(ValueError,'shared_depth_conflict'):self.evaluate_fixture(legs)
        for x in legs:x.shared_depth=None;x.liquidity_ids={'one-fill'}
        with self.assertRaisesRegex(ValueError,'shared_depth_conflict'):self.evaluate_fixture(legs)

    def test_legal_grid_and_nonlinear_fixed_charges_preserved(self):
        legs,_,_=pair(prices=('.2','.2'),flat='5')
        for x in legs:
            x.minimum=F(1);x.increment=F(3);x.lower=x.ceil(F(25));x.path['levels']=[(F('.2'),F(34))]
        result=self.evaluate_fixture(legs)
        for row in result['rows']:
            capital=F(row['supported_capital_usd'])
            self.assertEqual(capital,sum(F(a['native_quantity'])*F('.2')+5 for a in row['allocation']))
            for a in row['allocation']:self.assertEqual((F(a['native_quantity'])-1)%3,0)

    def test_unknown_joint_conditions_cannot_make_arb(self):
        legs,_,_=pair(prices=('.2','.2'),flat='0')
        for x in legs:x.conditions=None;x.path['levels']=[(F('.2'),F(30))]
        result=self.evaluate_fixture(legs)
        self.assertTrue(result['rows'])
        self.assertFalse(result['qualifying'])
        self.assertTrue(all(not r['settlement_complete'] for r in result['rows']))
        self.assertTrue(all('joint_settlement_meaning_unknown' in r['reasons'] for r in result['rows']))

    def test_identity_order_price_and_native_semantics(self):
        rows=pair_rows();key=opportunity_identity(rows)
        self.assertEqual(key,opportunity_identity(rows[::-1]))
        rows[0]['clocks']['received_at']='2026-10-14T01:15:10Z'
        self.assertEqual(key,opportunity_identity(rows))
        rows[0]['predicate']['predicate']='not_win'
        self.assertNotEqual(key,opportunity_identity(rows))
        rows=pair_rows();rows[1]['venue']=rows[0]['venue']
        with self.assertRaisesRegex(ValueError,'distinct_execution'):opportunity_identity(rows)

    def test_expired_required_models_and_unsupported_short_still_refused(self):
        from tests.test_sc01_readiness import Readiness
        test=Readiness()
        for kind in ('identity','fee','payout','quantity'):
            self.assertIn(kind+'_expired',test.expire(kind)['checks']['contract']['reason_codes'])
        test.test_native_side_collateral_and_contract_conflict()

    def test_unpatched_financial_path_missing_and_stale_optional_ev_inputs(self):
        from app.comparison.scanner_finance import evaluate as real_evaluate
        legs,_,_=pair(prices=('0.2','0.2'),flat='0')
        inputs={};instruments={}
        for index,x in enumerate(legs):
            q=deepcopy(x.q);at=x.at.isoformat()
            q['times'].update(source_at=at,received_at=at,projected_at=at)
            q['depth']=[dict(price='0.2',quantity='50')]
            q['comparison_input_refs']['refs']['reference']=None
            q['comparison_input_refs']['refs']['probability']=None
            inputs[str(index)]=dict(quote=q,profiles=x.profiles,event=x.event,group=x.group)
            instruments[str(index)]=dict(checks=dict(ev=dict(state='unsupported')))
        result=real_evaluate(dict(legs=['0','1']),instruments,inputs,at=at,policy=LEGACY_POLICY)
        self.assertTrue(result['evaluated'])
        self.assertTrue(result['rows'])
        self.assertTrue(all(r['category']!='ev' for r in result['rows']))
        self.assertTrue(all(r['size_status']=='supported_size' for r in result['rows']))

    def test_positive_complete_cashflows_include_nonlinear_settlement_costs(self):
        # Authored complete cashflows: each $50 deployed component returns $52
        # in each admitted state; a 10% net-gain charge costs $0.20 per leg.
        from app.comparison.estimated_content import STATES
        components=[]
        for index in range(2):
            comp=dict(deployed_capital_usd='50',settlement_already_withheld=False,
                components=dict(payout={},fee={}),settlement_terms=[])
            for state in STATES:
                for name,value in (('receipt_usd','52'),('hold_return_usd','0')):
                    comp['components']['payout'][name+':'+state]=dict(modeled_value=value)
                for name,value in (('fee_refund_usd','0'),('settlement_fee_usd','0.2')):
                    comp['components']['fee'][name+':'+state]=dict(modeled_value=value)
            comp['settlement_terms']=[dict(slot='authored-independent',pool=None,
                policy=dict(basis='net_gain',rate='0.1',grid='0.01',rounding='ceiling',aggregation=None,allow_fee_adjustment=False),
                state_fees={s:'0.2' for s in STATES})]
            components.append(comp)
        basis={s:dict(cells=[cell,cell],terminal=s=='terminal_noncompletion',weight=None) for s,cell in
            (('a_wins','home_win'),('b_wins','away_win'),('tie','tie'),('terminal_noncompletion','terminal_noncompletion'))}
        capital,states=economics(components,basis)
        self.assertEqual(capital,100)
        self.assertTrue(all(F(s['profit_usd'])==F('3.6') for s in states.values()))
        metrics,rows=classify(states,capital,policy=LEGACY_POLICY)
        self.assertEqual(F(metrics['complete_minimum_usd']['value']),F('3.1'))
        self.assertEqual(rows[0]['category'],'covered_outcome_arb')
        self.assertEqual(F(rows[0]['metric']['value']),F('3.1'))

    def test_private_profit_report_keeps_shared_pool_refunds_and_unknown_states(self):
        from app.comparison.estimated_pair import economics
        pool=dict(venue='authored',channel='direct_site',market_id='same-pool')
        policy=dict(basis='net_gain',rate='.02',grid='.01',rounding='ceiling',aggregation=None,allow_fee_adjustment=False)
        components=[]
        for index,receipt in enumerate(('200','10')):
            components.append(dict(deployed_capital_usd='100',settlement_already_withheld=bool(index),
                components=dict(payout={'receipt_usd:home_win':dict(modeled_value=receipt),
                    'hold_return_usd:home_win':dict(modeled_value='0')},
                    fee={'fee_refund_usd:home_win':dict(modeled_value='0'),
                        'settlement_fee_usd:home_win':dict(modeled_value='0')}),
                settlement_terms=[dict(policy=policy,pool=pool,slot='base')]))
        basis=dict(winner=dict(cells=['home_win','home_win'],terminal=False))
        capital,full=economics(components,basis)
        self.assertEqual(capital,200)
        self.assertEqual(full['winner']['settlement_charge_usd'],'0.2')
        self.assertEqual(full['winner']['profit_usd'],'9.8')
        self.assertEqual([v['receipt_charge_treatment'] for v in full['winner']['legs']],
            ['gross_receipt','attached_net_receipt'])
        self.assertEqual(economics(components,basis,_profit_only=True),
            (F(200),dict(winner=dict(profit_usd='9.8'))))
        components[0]['components']['payout']['receipt_usd:home_win']['modeled_value']=None
        self.assertIsNone(economics(components,basis)[1]['winner']['profit_usd'])
        self.assertEqual(economics(components,basis,_profit_only=True)[1],dict(winner=dict(profit_usd=None)))
        del basis['winner']['terminal']
        for private in (False,True):
            with self.subTest(private=private),self.assertRaisesRegex(KeyError,'terminal'):
                economics(components,basis,_profit_only=private)
        with self.assertRaisesRegex(ValueError,'profit_only_flag_invalid'):
            economics([],{},_profit_only=1)

    def test_every_search_checkpoint_runs_before_only_final_winner_formatting(self):
        from app.comparison import scanner_finance as owner
        from tests.test_sc03_finance import authored_finance_fixture
        for kind in ('native','stake','mixed'):
            p,i,x,policy=authored_finance_fixture(kind=kind,amount='500')
            with self.subTest(kind=kind),patch.object(owner,'checkpoint') as checkpoints,\
                    patch.object(owner,'classify',wraps=owner.classify) as rendered,\
                    patch.object(owner,'economics',wraps=owner.economics) as states:
                result=owner.evaluate(p,i,x,at=AT.isoformat(),policy=policy)
                self.assertTrue(result['rows'])
                self.assertEqual(checkpoints.call_count,result['search']['evaluations'])
                self.assertLessEqual(checkpoints.call_count,256)
                self.assertEqual(rendered.call_count,len(result['rows']))
                self.assertLessEqual(rendered.call_count,3)
                self.assertGreater(states.call_count,rendered.call_count)
                self.assertTrue(all(c.kwargs==dict(_profit_only=True) for c in states.call_args_list))

    def test_search_ties_use_wired_metric_then_capital_then_quantities(self):
        from types import SimpleNamespace
        from app.comparison import scanner_finance as owner
        from app.comparison.net_costs import wire
        # An authored scalar search vector deliberately places differences past
        # wire's200-digit decimal precision. Raw-metric ranking picks25/25;
        # the established wire-roundtrip score must instead retain26/26.
        class ScalarLeg:
            def __init__(self,index):
                self.sign=1 if index==0 else -1
                self.q=dict(venue=('kalshi','polymarket_us')[index],source=dict(provider='authored',
                    native_event_id='event',native_market_id='market',native_outcome_id=str(index),native_side='buy'),
                    binding=dict(selection=dict(participant=str(index))))
                self.conditions=dict(kind='authored_common')
                self.lower=F(25);self.increment=F(1)
                self.path=dict(levels=[(F('.2'),F(26))],minimum_cost=F('.2'))
                self.liquidity_ids=set();self.shared_depth=None
                self.exposure_per_native=F(1);self.unit=SimpleNamespace(unit='contracts');self.grid={}
            def floor(self,n):return F(n//1)
            def get(self,n):
                return dict(_pair_capital=F(25),_pair_exposure=F(100),pair_support=wire(n),
                    deployed_capital_usd='25',acquisition_usd='25',n=n)
        p=dict(legs=['0','1']);i={k:dict(checks=dict(ev=dict(state='unsupported'))) for k in p['legs']}
        x={k:dict(quote={},group={},profiles={},event={}) for k in p['legs']}
        policy=replace(LEGACY_POLICY,buffer_rate='0')
        def result(capital_tie):
            def states(components,basis,**kwargs):
                a,b=[c['n'] for c in components]
                capital=F(50) if capital_tie else a+b
                profit=F(1,2)+F(4-(a-25)*2-(b-25),10**205) if capital_tie else capital/100
                # Format this scalar vector without invoking the production wire
                # owner first, so it exercises that owner's score boundary.
                return capital,{s:dict(profit_usd=str(profit)) for s in ('a_wins','b_wins','tie','terminal_noncompletion')}
            with patch.object(owner,'Leg',side_effect=[ScalarLeg(0),ScalarLeg(1)]),\
                    patch.object(owner,'probabilities',return_value=(None,None,None)),\
                    patch.object(owner,'economics',side_effect=states):
                return owner.evaluate(p,i,x,at=AT.isoformat(),policy=policy)
        for capital_tie in (False,True):
            with self.subTest(capital_tie=capital_tie):
                r=result(capital_tie)
                self.assertEqual(r['search']['evaluations'],4)
                self.assertEqual([a['native_quantity'] for a in r['rows'][0]['allocation']],['26','26'])
                self.assertEqual(F(r['rows'][0]['metric']['value']),1)

    def test_deferred_report_preserves_refusal_for_unrenderable_losing_allocations(self):
        # This exact rational rate is admitted by the policy owner. Its
        # provisional report exceeds the existing display bound even when no
        # allocation is profitable enough to become a final category winner.
        policy=replace(LEGACY_POLICY,buffer_rate='1/'+str(10**120+7))
        for price in ('.6','.2'):
            legs,_,_=pair(prices=(price,price),flat='0')
            for leg in legs:
                leg.path['levels']=[(F(price),F(50))]
                leg.reference=None;leg.weight=None
            with self.subTest(price=price),patch('app.comparison.scanner_finance.checkpoint') as checkpoints:
                with self.assertRaisesRegex(ValueError,'Bounded finite decimal string required'):
                    self.evaluate_fixture(legs,policy=policy)
                self.assertEqual(checkpoints.call_count,1)
