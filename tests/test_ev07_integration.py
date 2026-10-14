"""Authored EV07 financial/identity and socket-free route-handler verification.

These checks do not substitute for HTTP transport or actual-browser qualification.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from aiohttp.test_utils import make_mocked_request
from app.comparison.effective_policy import effective_policy, recalculate
from app.comparison.estimated_policy import DEFAULT_POLICY, EstimatePolicy
from app.comparison.estimated_ev import compact
from app.comparison.funded_explanation import explanation
from app.comparison.metrics import snapshot_metrics
from app.dashboard.current_contract import packed, serialize, validate_snapshot, quotes_of
from app.dashboard.current_state import CurrentStore, CURRENT_KEY, SelectionError
from app.dashboard.multi_game_server import create_app
from app.dashboard.local_security import PublicRequestError
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner
from tests.test_ev05_funded import vector, run, bind
from tests.test_ev06_pairs import cross_group_workload, exact_example
from app.comparison.estimated_pair import evaluate


class FinancialAndIdentity(unittest.TestCase):
    def test_supported_size_uses_own_legal_allocation_commission_and_denominator(self):
        q,p,c=vector();q['depth']=[dict(price='2',quantity='200'),dict(price='1.9',quantity='300')]
        r=run(q,p,c,details=True);supported=r['supported_size_result']
        # 200*2 + 300*1.9 = 970; supported stake 500; win fee .02*470=9.40.
        expected=F('.994')*(F('.53')*F('460.6')-F('.47')*500)
        self.assertEqual(supported['native_quantity'],'500')
        self.assertEqual(supported['deployed_capital_usd'],'500')
        self.assertEqual(F(supported['fee_adjusted_expected_profit_usd']),expected)
        self.assertEqual(F(supported['buffered_profit_usd']),expected-F('2.5'))
        self.assertEqual(F(supported['buffered_return_percent']),100*(expected-F('2.5'))/500)
        win=next(row for row in supported['states'].values() if row['receipt_usd']=='970')
        self.assertEqual(win['separately_payable_charge_usd'],'9.4')
        self.assertNotEqual(F(r['buffered_profit_usd'])/500*100,F(supported['buffered_return_percent']))
        self.assertEqual(compact(r),compact(run(q,p,c)))
        # Partial observed depth is floored on the native grid, never traded off-grid.
        bind(q,p,'quantity',dict(grid=dict(minimum_native='10',increment_native='3'),grid_qualification='authored'))
        q['depth']=[dict(price='2',quantity='17')];r=run(q,p,c)
        self.assertEqual(r['supported_size_result']['native_quantity'],'16')
        q['depth']=[dict(price='2',quantity='9')];r=run(q,p,c)
        self.assertFalse(r['supported_size_result']['model_available'])
        self.assertEqual(r['supported_size_result']['reasons'],['observed_depth_below_legal_minimum'])
        q['depth']=[];self.assertNotIn('supported_size_result',run(q,p,c))

    def test_selected_waterfall_examples_reconcile_with_expected_state_fees(self):
        q,p,c=vector();single=run(q,p,c,details=True);e=explanation(single)
        self.assertEqual(F(e['gross_decisive_value_usd']),60)
        self.assertEqual(F(e['settlement_adjustment_usd']),F('-.36'))
        self.assertEqual(F(e['expected_payable_charge_usd']),F('10.5364'))
        self.assertEqual(F(e['buffered_profit_usd']),F('44.1036'))
        legs,p,c=exact_example();pair=evaluate(legs,quantities=('1010','1010'),details=True);e=explanation(pair,pair=True)
        self.assertEqual(F(e['gross_decisive_value_usd']),F('20.2'))
        self.assertEqual(F(e['settlement_adjustment_usd']),F('-1.3332'))
        self.assertEqual(F(e['expected_total_deduction_usd']),10)
        self.assertEqual(F(e['buffered_profit_usd']),F('3.8678'))

    def test_policy_readonly_exact_bounds_and_historical_reader(self):
        for kw in (dict(ceiling=1000),dict(buffer=.01),dict(ceiling='0'),dict(ceiling='100001'),dict(buffer='1.001'),dict(buffer='NaN'),dict(ceiling='1/3')):
            with self.subTest(kw=kw),self.assertRaises(ValueError):effective_policy(DEFAULT_POLICY,**kw)
        r=effective_policy(DEFAULT_POLICY,ceiling='500',buffer='0.01');self.assertEqual(r.capital_ceiling_usd,'500');self.assertEqual(DEFAULT_POLICY.buffer_rate,'0.005')
        raw=cross_group_workload();old=serialize(raw,allow_synthetic=True,supported=False)
        self.assertIs(validate_snapshot(old,allow_synthetic=True),old)
        self.assertTrue(all('supported_size_evaluation' not in q['calculations']['funded_estimate'] for e in old['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)))

    @patch('app.comparison.estimated_policy.load',return_value=EstimatePolicy())
    @patch('app.dashboard.current_incremental.load',return_value=EstimatePolicy())
    def test_pair_details_identity_revision_policy_both_groups_and_frozen_lease(self, *_policy):
        raw=cross_group_workload();store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
        state=store._state;original=packed(state);pair=next(p for p in state['events'][0]['funded_pairs'] if p['legs'][0]['group_id']!=p['legs'][1]['group_id']);a,b=pair['legs']
        params=dict(runtime_id=state['runtime_id'],state_revision=1,quote_id=a['quote_id'],quote_revision=str(a['quote_revision']),pair_id=pair['id'],pair_revision=pair['revision'],objective=pair['objective'],opposing_quote_id=b['quote_id'],opposing_quote_revision=str(b['quote_revision']))
        full=store.details(params);self.assertEqual(len(full['funded_pairs']),1);p=full['funded_pairs'][0]
        self.assertEqual(p['revision'],pair['revision']);self.assertEqual(p['objective_alternative']['objective'],'all_modeled_states_max_min')
        self.assertEqual(set(full['leg_quotes']),{a['quote_id'],b['quote_id']})
        for invalid in (dict(pair_id='absent'),dict(pair_revision='a'*64),dict(opposing_quote_revision='999'),dict(quote_revision='999'),dict(objective='all_modeled_states_max_min'),dict(state_revision=2)):
            with self.subTest(invalid=invalid),self.assertRaises(SelectionError):store.details(dict(params,**invalid))
        resized=recalculate(state,effective_policy(state['estimate_policy'],ceiling='500',buffer='0.01'))
        target=next(p for p in resized['events'][0]['funded_pairs'] if p['id']==pair['id'])
        resized_full=store.details(dict(params,ceiling='500',buffer='0.01',pair_revision=target['revision'],request_generation='42'))
        self.assertEqual(resized_full['request_generation'],'42');self.assertEqual(resized_full['estimate_policy'],resized['estimate_policy'])
        self.assertEqual(resized_full['funded_pairs'][0]['revision'],target['revision']);self.assertEqual(packed(store._state),original)
        lease=store.create(dict(schema='predict-current-1',runtime_id=state['runtime_id'],state_revision=1,quote_id=a['quote_id'],quote_revision=a['quote_revision'],client_id='authored:EV07'))
        frozen=packed(lease['review']);next_raw=deepcopy(raw);next_raw['state_revision']=2
        for event in next_raw['events']:
            for group in event['groups']:
                for outcome in group['outcomes']:
                    for q in quotes_of(outcome):
                        if q['id']==b['quote_id']:q['revision']+=1;q['original']['value']='0.31'
        self.assertTrue(store.commit(next_raw));self.assertEqual(packed(store.get(lease['selection_id'])['review']),frozen)
        with self.assertRaises(SelectionError):store.details(params)

    def test_authored_bills_rams_fixture_original_contracts_and_examples(self):
        from tests.ev07_fixture_runtime import authored_fixture,example_reviews
        state=serialize(authored_fixture(),allow_synthetic=True)
        self.assertEqual(len(state['events']),1)
        self.assertEqual(state['events'][0]['title'],'Buffalo Bills at Los Angeles Rams')
        quotes=[q for g in state['events'][0]['groups'] for o in g['outcomes'] for q in quotes_of(o)]
        self.assertEqual(len(quotes),9)
        self.assertTrue(any(q['source']['native_outcome_id'].endswith(':alternative') for q in quotes))
        short=next(q for q in quotes if q['source']['native_side']=='SHORT')
        self.assertFalse(short['calculations']['funded_estimate']['model_available'])
        prophet=next(q for q in quotes if q['venue']=='prophetx' and q['binding']['selection']['participant']=='NFL:BUF')
        self.assertEqual(prophet['calculations']['funded_estimate']['display']['buffered_profit_usd'],'+44.10')
        self.assertTrue(state['events'][0]['funded_pairs'])
        one,two=example_reviews()
        self.assertEqual(one['quote']['calculations']['funded_estimate']['display']['buffered_return_percent'],'+4.41')
        self.assertEqual(two['pair']['display']['buffered_profit_usd'],'+3.87')
        self.assertEqual(two['pair']['buffered_all_state_minimum_usd'],'-257.399')

    def test_fixture_transitions_preserve_original_clocks_and_expose_reference_free_states(self):
        from tests.ev07_fixture_runtime import authored_fixture,fixture_transition,EXAMPLE_SCRIPT
        self.assertIn("from '/current/assets/comparison-board.js'",EXAMPLE_SCRIPT)
        for action in ('change_second_leg','remove_second_leg','remove_reference','reset_runtime'):
            with self.subTest(action=action):
                store=CurrentStore(InjectedTestProvider(authored_fixture()),monotonic=lambda:0)
                before=packed(store._state);previous=store._state['runtime_id']
                fixture_transition(store,action)
                self.assertNotEqual(before,packed(store._state))
                if action=='remove_reference':
                    self.assertTrue(store._state['events'][0]['funded_pairs'])
                    self.assertTrue(all(p['conditioning']=='reference_free_scenarios' and p['buffered_profit_usd'] is None for p in store._state['events'][0]['funded_pairs']))
                if action=='reset_runtime':self.assertNotEqual(previous,store._state['runtime_id'])
        store=CurrentStore(InjectedTestProvider(authored_fixture()),monotonic=lambda:0)
        prepared=fixture_transition(store,'prepare_second_leg_expiry');target=prepared['quote_id']
        clocks={id:packed(value['quote']['times']) for id,value in store.index(store._state).items()}
        fixture_transition(store,'expire_second_leg')
        self.assertTrue(all(clocks[id]==packed(value['quote']['times']) for id,value in store.index(store._state).items()))
        self.assertFalse(store.index(store._state)[target]['quote']['calculations']['funded_estimate']['ranking_eligible'])
        self.assertTrue(any(q['calculations']['funded_estimate']['ranking_eligible'] for q in [value['quote'] for value in store.index(store._state).values()] if q['id']!=target))

    def test_funded_sign_basis_filters_never_use_predecessor_eligibility(self):
        state=serialize(cross_group_workload(),allow_synthetic=True)
        before=snapshot_metrics(state)
        for event in state['events']:
            for group in event['groups']:
                for outcome in group['outcomes']:
                    for q in quotes_of(outcome):q['calculations']['net_ev'].update(eligible=False,exact=None)
            for pair in event['funded_pairs']:pair.update(conditioning='reference_free_scenarios',buffered_profit_usd=None,buffered_return_percent=None,ranking_eligible=False)
        after=snapshot_metrics(state)
        self.assertEqual({r['id'] for r in before['rows']},{r['id'] for r in after['rows']})
        self.assertTrue(snapshot_metrics(state,results='reference_free')['funded_pairs'])
        self.assertTrue(all(p['buffered_profit_usd'] is None for p in snapshot_metrics(state,results='unavailable')['funded_pairs']))
        for sign in ('positive','negative','zero'):
            rows=snapshot_metrics(state,results=sign)['rows']
            self.assertTrue(all((F(r['funded_estimate']['buffered_profit_usd'])>0 if sign=='positive' else F(r['funded_estimate']['buffered_profit_usd'])<0 if sign=='negative' else F(r['funded_estimate']['buffered_profit_usd'])==0) for r in rows))


class SocketFreeHandlers(unittest.IsolatedAsyncioTestCase):
    async def test_comparison_and_selected_routes_readonly_shared_effective_policy(self):
        raw=cross_group_workload();provider=InjectedTestProvider(raw);app=create_app(owner=owner(),sessions={},current_provider=provider)
        store=app[CURRENT_KEY];store.monotonic=lambda:0;store._age_origin=0
        before=packed(store._state)
        async def get(path,params):
            req=make_mocked_request('GET',path+'?'+urlencode(params),app=app);info=await app.router.resolve(req);req._match_info=info
            req.transport.is_closing.return_value=False
            response=await info.handler(req)
            body=getattr(response,'body',None)
            if hasattr(body,'as_bytes'):body=await body.as_bytes()
            return response,json.loads(body) if body else None
        response,value=await get('/api/comparison',dict(ceiling='500',buffer='0.01',request_generation='7',runtime_id=store._state['runtime_id'],state_revision=1))
        self.assertEqual(response.status,200);self.assertEqual(value['request_generation'],'7');self.assertEqual(value['estimate_policy']['buffer_rate'],'0.01')
        p=value['funded_pairs'][0];a,b=p['legs'];params=dict(runtime_id=value['runtime_id'],state_revision=1,quote_id=a['quote_id'],pair_id=p['id'],pair_revision=p['revision'],objective=p['objective'],opposing_quote_id=b['quote_id'],opposing_quote_revision=str(b['quote_revision']),ceiling='500',buffer='0.01',request_generation='7')
        response,full=await get('/api/current/details',params);self.assertEqual(response.status,200);self.assertEqual(full['estimate_policy'],value['estimate_policy']);self.assertEqual(full['funded_pairs'][0]['revision'],p['revision'])
        response,error=await get('/api/comparison',dict(state_revision=2,runtime_id=value['runtime_id']));self.assertEqual(response.status,409)
        with self.assertRaises(PublicRequestError):await get('/api/comparison',dict(buffer='1.01'))
        response,_=await get('/current/assets/selected-details.js',{});self.assertEqual(response.status,200)
        self.assertEqual(before,packed(store._state));self.assertEqual(provider.initial_state(),raw)
