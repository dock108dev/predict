"""Independent cash ledgers, probability invariants and adversarial domains."""
import unittest
from copy import deepcopy
from decimal import Decimal as D, localcontext
from app.reference.product import odds_cashflows,devig
from app.fees.engine import generic_fee
from app.settlement import portfolio
from app.depth import explicit_allocation,solve_explicit
from app.dashboard.math_scenarios import evaluate,replay,reference_sets


def fee(rate='0',basis='notional',aggregation='per_fill',rounding='half_even'):
    return dict(rate=rate,basis=basis,aggregation=aggregation,rounding=rounding,grid='.01')


def scenario():
    return dict(states=['A','B'],complete=True,ceiling='10',probabilities={'A':'.5','B':'.5'},legs=[
        dict(id=name,minimum='.5',increment='.5',partial_final=True,fee_policy=fee(),
             levels=[dict(price=price,quantity='3',liquidity_id=name)],
             payouts={s:dict(kind='fraction',value='1' if name==s else '0',settlement_fee_per_unit='0') for s in ['A','B']})
        for name,price in [('A','.4'),('B','.5')]])


class MathPackage(unittest.TestCase):
    def test_odds_hand_ledger(self):
        for value,kind in [('2.5','decimal_odds'),('150','american_odds'),('3/2','fractional_odds'),('.4','probability'),('40','percent'),('.4','price')]:
            r=odds_cashflows(value,kind,stake='12')
            self.assertEqual(D(r['gross_win_payout']),30);self.assertEqual(D(r['win_profit']),18)
            self.assertEqual(D(r['loss_profit']),-12);self.assertEqual(D(r['implied_probability']),D('.4'))
        r=odds_cashflows('-200','american_odds',quantity='3',payout_unit='10')
        self.assertAlmostEqual(D(r['stake']),20,places=35)
        for invalid in ('NaN','0','1'):
            with self.assertRaises(ValueError):odds_cashflows(invalid,'decimal_odds',stake='1')

    def test_fees_rounding_and_market_netting(self):
        fills=[dict(price='.5',quantity='1')]*2
        self.assertEqual(generic_fee(fills,fee('.01'))['entry_fee'],'0.00')
        self.assertEqual(generic_fee(fills,fee('.01',aggregation='order'))['entry_fee'],'0.01')
        self.assertEqual(generic_fee(fills,fee('.01',rounding='half_up'))['entry_fee'],'0.02')
        self.assertEqual(generic_fee(fills,fee('.01',rounding='ceiling'))['entry_fee'],'0.02')
        self.assertEqual(generic_fee(fills,fee('.01',rounding='floor'))['entry_fee'],'0.00')
        pos=dict(account='hypothetical',market='m',complete=True,net_before={'win':'-10','lose':'5'})
        # A $15 incremental gain offsets $10 prior loss: tax is on $5, not $15.
        r=generic_fee([],fee('.02','net_gain'),positions=pos,outcomes={'win':'15','lose':'0'})
        self.assertEqual(D(r['state_fees']['win']),D('.1'));self.assertEqual(D(r['state_fees']['lose']),0)
        with self.assertRaises(ValueError):generic_fee([],fee('.02','net_gain'),outcomes={'win':'1'})
        with self.assertRaisesRegex(ValueError,'adjustment'):generic_fee([],fee('.02','net_gain'),positions=pos,outcomes={'win':'0','lose':'-5'})

    def test_joint_states_push_refund_and_unknown(self):
        # Ledger: $4 + $5 committed; wins pay $10, mutual refund returns $9;
        # conflicting void/win branch pays only $4 => -$5, defeating arbitrage.
        legs=[dict(cash='4',receipts={'A':'10','B':'0','refund':'4','conflict':'4'}),dict(cash='5',receipts={'A':'0','B':'10','refund':'5','conflict':'0'})]
        r=portfolio(legs,['A','B','refund','conflict'],complete=True)
        self.assertEqual(r['states'],{'A':'1','B':'1','refund':'0','conflict':'-5'})
        self.assertEqual(r['worst_case_return'],'-5');self.assertFalse(r['mathematical_arbitrage'])
        r=portfolio(legs,['A','B','refund','conflict'],complete=False)
        self.assertIsNone(r['worst_case_return'])
        legs[0]['receipts']['conflict']=None
        self.assertIsNone(portfolio(legs,['A','B','refund','conflict'],complete=True)['worst_case_return'])

    def test_ev_nonbinary_cash_ledger_and_denominator(self):
        r=portfolio([dict(cash='4',receipts={'win':'10','loss':'0','push':'4','shared':'5'})],
                    ['win','loss','push','shared'],complete=True,probabilities={'win':'.3','loss':'.2','push':'.1','shared':'.4'},reserve='1')
        # Expected receipts $3 + $0 + $.4 + $2 = $5.4; $5 committed => $.4.
        self.assertEqual(D(r['expected_net']),D('.4'));self.assertEqual(D(r['ev_pct']),8)
        self.assertEqual(D(r['return_denominator']),5);self.assertEqual(D(r['worst_case_return']),-5)
        with self.assertRaises(ValueError):portfolio([dict(cash='1',receipts={'a':'2'})],['a'],complete=True,probabilities={'a':'.9'})

    def test_unequal_quantities_depth_budget_and_fractional_units(self):
        s=scenario();s['legs'][0]['payouts']['A']['value']='.5'
        # 2 A units and 1 B unit pay $1 in either state, costing $.8+$.5=$1.3.
        r=explicit_allocation(s,['2','1']);self.assertEqual(D(r['worst_case_return']),D('-.3'))
        s=scenario();s['legs'][0]['levels']=[dict(price='.4',quantity='1',liquidity_id='a1'),dict(price='.6',quantity='2',liquidity_id='a2')]
        r=explicit_allocation(s,['1.5','1.5'])
        self.assertEqual(D(r['committed_cash']),D('1.45'));self.assertEqual(D(r['worst_case_return']),D('.05'))
        s['ceiling']='1.44';self.assertFalse(explicit_allocation(s,['1.5','1.5'])['within_ceiling'])
        with self.assertRaisesRegex(ValueError,'depth'):explicit_allocation(s,['4','1'])
        with self.assertRaisesRegex(ValueError,'increment'):explicit_allocation(s,['.75','1'])

    def test_solver_exhaustive_shared_exclusive_and_limit(self):
        s=scenario();r=solve_explicit(s)
        self.assertEqual(r['search']['total_grid_allocations'],49)
        self.assertEqual(r['search']['evaluated'],49)
        self.assertEqual(r['best']['quantities'],['3.0','3.0']);self.assertEqual(D(r['best']['worst_case_return']),D('.3'))
        self.assertTrue(any(D(x['worst_case_return'])<0 for x in r['partial_fill_exposure']))
        self.assertIn('limit',solve_explicit(s,max_evaluations=2)['search']['optimality'])
        for l in s['legs']:l['levels'][0]['liquidity_id']='shared'
        with self.assertRaisesRegex(ValueError,'Shared'):explicit_allocation(s,['2','2'])
        r=solve_explicit(s);self.assertEqual(sum(map(D,r['best']['quantities'])),3)
        for l in s['legs']:l['exclusive_group']='alternatives'
        with self.assertRaisesRegex(ValueError,'exclusive'):explicit_allocation(s,['1','1'])
        self.assertEqual(D(solve_explicit(s)['best']['worst_case_return']),0)

    def test_net_gain_combines_positions_across_legs(self):
        s=scenario()
        for l in s['legs']:
            l['fee_policy']=fee('.1','net_gain');l['positions']=dict(account='a',market='m',complete=True,net_before={'A':'0','B':'0'})
        # Combined $.10 gain owes $.01, not $.06 commission on winning leg alone.
        r=explicit_allocation(s,['1','1']);self.assertEqual(D(r['worst_case_return']),D('.09'))
        s['legs'][1]['positions']['net_before']['A']='1'
        with self.assertRaisesRegex(ValueError,'Conflicting'):explicit_allocation(s,['1','1'])

    def test_devig_complete_set_and_invariants(self):
        kw=dict(identity={'period':'first_half','line':'7'},provenance='response',freshness='historical')
        r=devig({'a':'2','b':'4','c':'4'},['a','b','c'],**kw)
        self.assertEqual({k:D(v) for k,v in r['probabilities'].items()},{'a':D('.5'),'b':D('.25'),'c':D('.25')})
        r=devig({'a':'1.8','b':'1.8'},['a','b'],**kw)
        self.assertEqual(D(r['probabilities']['a']),D('.5'))
        with self.assertRaises(ValueError):devig({'a':'2'},['a','b'],**kw)
        with self.assertRaises(ValueError):devig({'a':'1.01','b':'1.01','c':'100'},['a','b','c'],method='additive',**kw)
        # Scaling quantities without rounded fees scales every cashflow, preserving ROI.
        s=scenario();a=explicit_allocation(s,['.5','.5']);b=explicit_allocation(s,['1','1'])
        self.assertEqual(D(a['return_pct']),D(b['return_pct']));self.assertEqual(D(b['expected_net']),2*D(a['expected_net']))
        s['legs'][0]['fee_policy']=None
        self.assertIsNone(explicit_allocation(s,['1','1'])['expected_net'])

    def test_all_63_cells_derived_details_replay_and_original_preservation(self):
        from tests.test_full_scope_engineering import cases
        from tests.test_periods import snapshot
        from app.dashboard.product_view import calculate
        count=0
        for cell,rows in cases():
            with self.subTest(cell=cell):
                snap=snapshot(rows);g=next(g for g in snap['games'] if set(g['sources'])=={'kalshi','polymarket_us'})
                old=calculate(snap,g,dict(quantity='1'))
                r=evaluate(snap,g,dict(spec=scenario(),quantities=['.5','.5']))
                self.assertEqual(replay(r),r);self.assertEqual(calculate(snap,g,dict(quantity='1')),old)
                self.assertFalse(r['watch_metrics']['live_signal_eligible']);count+=1
        self.assertEqual(count,63)


if __name__=='__main__':unittest.main()

class ReferenceIntegration(unittest.TestCase):
    def test_retained_sets_and_missing_cross_cutoff_line_period_isolation(self):
        from tests.aggregate_fixture import FOLDER
        from app.dashboard.session_history import load
        s=load(FOLDER);g=next(g for g in s['games'] if g['product_identity']['family']=='moneyline')
        refs=reference_sets(s,g);self.assertTrue(refs['estimates'])
        for estimate in refs['estimates']:
            with localcontext() as c:
                c.prec=100
                self.assertEqual(sum(map(D,estimate['probabilities'].values())),1)
        estimate=refs['estimates'][0];spec=scenario();states=estimate['outcome_set'];spec['states']=states
        spec.pop('probabilities')
        for i,l in enumerate(spec['legs']):l['payouts']={s:dict(kind='fraction',value=str(int(i==j)),settlement_fee_per_unit='0') for j,s in enumerate(states)}
        r=evaluate(s,g,dict(spec=spec,quantities=['1','1'],reference_estimate=0,reference_conditioning_acknowledged=True))
        self.assertEqual(r['calculation']['ev_label'],'reference-derived estimate');self.assertIsNotNone(r['calculation']['expected_net'])
        self.assertEqual(replay(r),r)
        broken=deepcopy(s);target=estimate['provenance']['references'][0]
        broken['references']=[r for r in broken['references'] if r['id']!=target]
        self.assertTrue(reference_sets(broken,g)['exclusions'])
        tampered=deepcopy(r);tampered['calculation']['expected_net']='99'
        with self.assertRaises(ValueError):replay(tampered)


class MathRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_saved_ordinary_route_no_collection_and_exact_download_replay(self):
        import tempfile
        from pathlib import Path
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.coverage_owner import CoverageOwner
        from app.dashboard.multi_game_server import create_app
        from tests.aggregate_fixture import FOLDER
        class Owner(CoverageOwner):
            def history_paths(self):return {FOLDER.name:FOLDER}
            async def start(self,**kwargs):raise AssertionError('No collection')
        with tempfile.TemporaryDirectory() as tmp:
            c=TestClient(TestServer(create_app(owner=Owner(Path(tmp)/'legacy',pilot_output=Path(tmp)/'saved',product_mode=True),sessions={},watch_path=Path(tmp)/'watch.json')))
            await c.start_server()
            try:
                response=await c.get('/api/dashboard?view=feed&capture='+FOLDER.name);feed=await response.json();row=feed['comparisons'][0]
                origin={'Origin':str(c.make_url('/')).rstrip('/')}
                response=await c.post('/api/math-scenario',json={**{k:row[k] for k in ('session','hash','cutoff')},'spec':scenario()},headers=origin)
                self.assertEqual(response.status,200,await response.text());result=await response.json()
                response=await c.post('/api/math-scenario',json={'replay':result},headers=origin)
                self.assertEqual(response.status,200,await response.text());self.assertEqual(await response.json(),result)
                download=await c.get('/api/math-scenario-download?sha256='+result['sha256'])
                self.assertEqual(download.status,200);self.assertIn('attachment',download.headers['Content-Disposition']);self.assertEqual(await download.json(),result)
                html=await (await c.get('/admin/retained')).text();self.assertIn('/view/math-scenarios.js',html)
                ordinary=await (await c.get('/')).text();self.assertIn('/current/assets/current.js',ordinary);self.assertNotIn('/view/math-scenarios.js',ordinary)
                self.assertEqual((await c.get('/view/math-scenarios.js')).status,200)
            finally:await c.close()

class Adversarial(unittest.TestCase):
    def test_same_outcome_is_not_a_hedge_and_split_refund(self):
        s=scenario();s['legs'][1]['payouts']=deepcopy(s['legs'][0]['payouts'])
        self.assertFalse(explicit_allocation(s,['1','1'])['mathematical_arbitrage'])
        s=scenario();s['legs'][0]['payouts']['A']=dict(kind='split',value='.5',refund_fraction='.5',settlement_fee_per_unit='0')
        # Half of winning $1 payout plus half of $.40 stake = $.70, not $.50.
        r=explicit_allocation(s,['1','0']);self.assertEqual(D(r['states']['A']),D('.3'))
        s['legs'][0]['payouts']['A']['refund_fraction']='.6'
        with self.assertRaises(ValueError):explicit_allocation(s,['1','0'])

    def test_missing_zero_probability_state_is_still_unknown(self):
        s=scenario();s['probabilities']={'A':'1','B':'0'};s['legs'][1]['payouts'].pop('B')
        r=explicit_allocation(s,['1','1']);self.assertIsNone(r['expected_net']);self.assertIsNone(r['worst_case_return'])
        s=scenario();s['legs'][0]['fee_policy']=fee('.01','quantity')
        s['states'].append('void');s['probabilities']={'A':'.45','B':'.45','void':'.1'}
        for leg in s['legs']:leg['payouts']['void']=dict(kind='refund',value='1',settlement_fee_per_unit='0')
        r=explicit_allocation(s,['1','1']);self.assertEqual(D(r['states']['void']),D('-.01'));self.assertFalse(r['mathematical_arbitrage'])

    def test_partial_grid_exposure_and_ev_ranking(self):
        s=scenario();r=solve_explicit(s)
        self.assertEqual(r['exposure_search']['total'],49);self.assertTrue(r['exposure_search']['complete'])
        self.assertTrue(any(x['quantities']==['0.5','0'] for x in r['partial_fill_exposure']))
        s['objective']='expected_net';s['probabilities']={'A':'.9','B':'.1'}
        r=solve_explicit(s);self.assertEqual(r['best']['quantities'],['3.0','0'])
        self.assertEqual(D(r['best']['expected_net']),D('1.5'))
        self.assertFalse(r['best']['mathematical_arbitrage'])

    def test_devig_exact_closure_and_unsafe_inputs(self):
        from fractions import Fraction
        r=devig({'a':'2.13','b':'3.41','c':'4.12'},['a','b','c'],identity={'line':'3'},provenance='p',freshness='historical')
        self.assertEqual(sum(Fraction(v) for v in r['probabilities'].values()),1)
        with self.assertRaises(ValueError):odds_cashflows(2.5,'decimal_odds',stake='1')
        s=scenario();s['legs'][0]['levels'][0]['price']='NaN'
        with self.assertRaises(ValueError):solve_explicit(s)

class ChampionshipPortfolio(unittest.TestCase):
    def test_full_32_outcome_field_and_missing_contender(self):
        states=[str(i) for i in range(32)];s=dict(states=states,complete=True,legs=[])
        for state in states:
            s['legs'].append(dict(id=state,minimum='1',increment='1',partial_final=True,fee_policy=fee(),levels=[dict(price='.02',quantity='1',liquidity_id=state)],payouts={k:dict(kind='fraction',value=str(int(k==state)),settlement_fee_per_unit='0') for k in states}))
        r=explicit_allocation(s,['1']*32);self.assertEqual(D(r['committed_cash']),D('.64'));self.assertEqual(D(r['worst_case_return']),D('.36'))
        r=explicit_allocation(s,['1']*31+['0']);self.assertEqual(D(r['worst_case_return']),D('-.62'))
        s['complete']=False;self.assertIsNone(explicit_allocation(s,['1']*32)['worst_case_return'])

class LiabilityCapital(unittest.TestCase):
    def test_negative_receipt_needs_funding_without_double_expense(self):
        r=portfolio([dict(cash='2',receipts={'a':'5','b':'-1'})],['a','b'],complete=True,probabilities={'a':'.5','b':'.5'})
        self.assertEqual(D(r['acquisition_cash']),2);self.assertEqual(D(r['committed_cash']),3)
        self.assertEqual(D(r['settlement_liability_funding']),1)
        self.assertEqual({k:D(v) for k,v in r['states'].items()},{'a':D('3'),'b':D('-3')})
        self.assertEqual(D(r['return_pct']),-100);self.assertEqual(D(r['expected_net']),0)
