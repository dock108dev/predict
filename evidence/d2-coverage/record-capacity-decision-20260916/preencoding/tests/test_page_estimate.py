"""Focused saved-input checks; rational expectations never use app fee/EV output."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction as F
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from tests import test_math_reconciliation as reconciliation
from app.reference.page_estimate import retained, estimate, for_saved_game
from app.dashboard.multi_game import OUTPUT, saved_rows, project_game, default_point
from tests.test_math_reconciliation import native_inputs, oracle, dec

class PageEstimateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.x,cls.a=retained();cls.g=cls.x['target_identity'];cls.sid=cls.a['binding']['session']
        cls.saved=saved_rows(OUTPUT/cls.sid)
        cls.levels,_=native_inputs(cls.saved['rows'],cls.g,cls.x['target_cutoff'])
    def test_independent_probability_and_ten_contract_cashflow(self):
        p=F(218,318)/(F(100,280)+F(218,318))
        self.assertEqual(p,F(1526,2321))
        with localcontext() as c:
            c.prec=100
            stored=(Decimal(p.numerator)/Decimal(p.denominator)).quantize(Decimal('1e-18'))
        e=estimate(self.x,self.a,self.g)
        self.assertEqual(e['probability'],str(stored))
        v=oracle(self.levels['kalshi:yes'],10,'kalshi')
        self.assertEqual(v['cost'],F('6.80'));self.assertEqual(v['fee'],F('.16'));self.assertEqual(v['cash'],F('6.96'))
        self.assertEqual(F(e['expected_payout']),F(stored)*10)
        self.assertEqual(F(e['expected_profit']),F('-0.385247738043946570'))
        self.assertEqual(e['return_pct'],dec((F(stored)*10-v['cash'])/v['cash']*100))
    def test_actual_depth_boundaries_and_precision_scenarios(self):
        for q in ('1','100','11574336','11574337','21352164','27741763'):
            for scenario,grid in [('cent',F('.01')),('direct',F('.0001'))]:
                with self.subTest(q=q,scenario=scenario):
                    e=estimate(self.x,self.a,self.g,q,scenario);v=oracle(self.levels['kalshi:yes'],int(q),'kalshi',grid)
                    self.assertEqual(F(e['leg']['notional']),v['cost']);self.assertEqual(F(e['leg']['cash']),v['cash'])
                    self.assertEqual(F(e['leg']['fee']),v['fee'])
                    self.assertEqual([(F(f['price']),F(f['quantity'])) for f in e['leg']['fills']],v['fills'])
                    self.assertEqual(F(e['expected_profit']),F(e['probability'])*int(q)-v['cash'])
        self.assertIsNone(estimate(self.x,self.a,self.g,'27741764')['expected_profit'])
    def test_unknown_inputs_and_assessment(self):
        self.assertIsNone(estimate(self.x,self.a,self.g,scenario='unknown')['expected_profit'])
        a=deepcopy(self.a);a['ordinary_winner_comparable']=False
        self.assertIsNone(estimate(self.x,a,self.g)['expected_profit'])
        x=deepcopy(self.x);x['target_contract']['levels']=None
        self.assertIsNone(estimate(x,self.a,self.g)['expected_profit'])
        x=deepcopy(self.x);x['target_fee_assessment']['profiles']={}
        self.assertIsNone(estimate(x,self.a,self.g)['expected_profit'])
        for q in ('0','-1','NaN','Infinity','1.1'):
            with self.assertRaises(ValueError):estimate(self.x,self.a,self.g,q)
    def test_orientation_binding(self):
        for field,value in [('target_team','Detroit Lions'),('target_side','no'),('target_market_id','other'),('source_bookmaker','other'),('source_sha256','changed'),('target_rules_sha256','changed')]:
            a=deepcopy(self.a);a['binding'][field]=value
            with self.assertRaisesRegex(ValueError,'binding'):estimate(self.x,a,self.g)
        x=deepcopy(self.x);x['source_result']['page']['sides'].reverse()
        self.assertEqual(estimate(x,self.a,self.g)['probability'],'0.657475226195605343')
    def test_times_and_scope(self):
        e=for_saved_game(self.sid,self.g,'10','cent')
        self.assertEqual(e['reference_retrieved_at'],self.x['reference_retrieved_at'])
        self.assertEqual(e['target_received_at'],self.x['target_received_at'])
        self.assertEqual(e['label'],'Retrospective, time-mismatched research comparison')
        self.assertFalse(e['prospective_evaluation_eligible']);self.assertFalse(e['current_executable']);self.assertIsNone(e['unconditional_ev'])
        self.assertIsNone(for_saved_game(self.sid,self.g,'10','cent',live=True))
        self.assertIsNone(for_saved_game('other',self.g,'10','cent'))
        self.assertIsNone(for_saved_game(self.sid,dict(self.g,id='other'),'10','cent'))
    def test_baseline_reproduces_without_rewriting(self):
        original=Path('evidence/math-reconciliation/baseline.json').read_text()
        def check(path,text,*args,**kwargs):
            self.assertEqual(str(path),'evidence/math-reconciliation/baseline.json')
            self.assertEqual(text,original)
            return len(text)
        reconciliation.ReconciliationTests.setUpClass()
        with patch.object(Path,'write_text',check):
            reconciliation.ReconciliationTests('test_all_saved_candidates_and_ev').test_all_saved_candidates_and_ev()

class PageRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_separate_from_manual_and_rankings(self):
        from app.dashboard.multi_game_server import create_app
        x,a=retained();sid=a['binding']['session'];g=x['target_identity']
        client=TestClient(TestServer(create_app(sessions={})));await client.start_server()
        try:
            catalog=await (await client.get('/api/sessions')).json();item=next(i for i in catalog if i['game']['id']==g['id'])
            query=dict(session=item['id'],hash=sid,cutoff=item['timeline'][item['default_cutoff']]['id'],quantity='10',scenario='cent',contract='kalshi:yes')
            r=await (await client.get('/api/calculate',params=query)).json()
            self.assertIsNone(r['ev']['probability']);self.assertIsNone(r['ev']['expected_profit'])
            query['probability']='0.4'
            manual=await (await client.get('/api/calculate',params=query)).json()
            self.assertEqual(manual['ev']['probability'],'0.4');self.assertEqual(manual['page_estimate'],r['page_estimate'])
            dashboard=await (await client.get('/api/dashboard',params=dict(capture=sid,view='ev'))).json()
            self.assertTrue(all(row['probability'] is None and row['profit'] is None for row in dashboard['rows']))
            other=next(i for i in catalog if i['game']['id']!=g['id']);query.update(session=other['id'],cutoff=other['timeline'][other['default_cutoff']]['id'])
            self.assertNotEqual((await (await client.get('/api/calculate',params=query)).json())['page_estimate']['assessment']['binding']['game_id'],g['id'])
        finally:await client.close()
