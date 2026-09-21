"""Saved native odds/depth rational reconciliation and bounded research routes."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from app.reference.multi_page import SESSION,saved_comparisons,source_for_game,rank_research,research_row
from app.reference.page_estimate import estimate,binding_matches
from app.dashboard.multi_game import OUTPUT,saved_rows
from tests.test_math_reconciliation import native_inputs,oracle,dec

class MultiPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries=saved_comparisons();cls.saved=saved_rows(OUTPUT/SESSION)
        cls.raw=Path('evidence/public-nfl-reference/vegasinsider.html').read_bytes()
        cls.meta=json.loads(Path('evidence/public-nfl-reference/capture.json').read_text())

    def test_all_native_odds_depth_fees_and_times(self):
        self.assertEqual(len(self.entries),6)
        evidence=[]
        for entry in self.entries.values():
            c,a=entry['comparison'],entry['assessment'];g=c['target_identity'];page=c['source_result']['page']
            levels,proof=native_inputs(self.saved['rows'],g,c['target_cutoff']);ls=levels['kalshi:yes']
            observed_pairs={'32144330':{'Detroit Lions':'+180','Buffalo Bills':'-218'},'35985360':{'Carolina Panthers':'-135','Atlanta Falcons':'+114'},'35985380':{'New Orleans Saints':'+320','Baltimore Ravens':'-410'},'35985350':{'Minnesota Vikings':'+185','Chicago Bears':'-225'},'35985390':{'Cincinnati Bengals':'+120','Houston Texans':'-142'},'35985400':{'Cleveland Browns':'+310','Tampa Bay Buccaneers':'-395'}}
            self.assertEqual({s['team']:s['american_price'] for s in page['sides']},observed_pairs[page['event_id']])
            implied={s['team']:(F(100,100+int(s['american_price'])) if int(s['american_price'])>0 else F(-int(s['american_price']),100-int(s['american_price']))) for s in page['sides']}
            total=sum(implied.values());prob=implied[c['target_contract']['team']]/total
            with localcontext() as ctx:
                ctx.prec=100
                p=(Decimal(prob.numerator)/Decimal(prob.denominator)).quantize(Decimal('0.000000000000000001'))
            capacity=sum(n for _,n in ls)
            for quantity in (1,10,100,int(ls[0][1]),int(ls[0][1])+1,int(capacity),int(capacity)+1):
                if quantity>100000000:continue
                for scenario,grid in [('cent',F('.01')),('direct',F('.0001'))]:
                    r=estimate(c,a,g,str(quantity),scenario);v=oracle(ls,quantity,'kalshi',grid)
                    self.assertEqual(F(r['probability']),F(p))
                    self.assertEqual(r['target_received_at'],proof['kalshi']['received_at'])
                    self.assertEqual(r['reference_retrieved_at'],self.meta['retrieved_at'])
                    self.assertEqual(r['target_cutoff'],c['target_cutoff'])
                    self.assertFalse(r['prospective_evaluation_eligible']);self.assertFalse(r['current_executable']);self.assertIsNone(r['unconditional_ev'])
                    if v:
                        for k,vk in [('notional','cost'),('fee','fee'),('cash','cash')]:self.assertEqual(F(r['leg'][k]),v[vk])
                        net=F(p)*quantity-v['cash'];self.assertEqual(F(r['expected_profit']),net)
                        self.assertEqual(Decimal(r['return_pct']),Decimal(dec(net/v['cash']*100)))
                        self.assertEqual([(F(f['price']),F(f['quantity'])) for f in r['leg']['fills']],v['fills'])
                    else:self.assertIsNone(r['expected_profit']);self.assertIsNone(r['leg']['fills'])
                    self.assertEqual(r['quantity'],str(quantity))
            r=estimate(c,a,g,'100','cent');v=oracle(ls,100,'kalshi')
            evidence.append(dict(game=g['title'],team=r['target_team'],odds=page['sides'],overround_exact=str(total-1),probability_exact=str(prob),probability=r['probability'],ask=r['leg']['ask'],available=r['leg']['visible_size'],purchase_cost=dec(v['cost']),fee=dec(v['fee']),cash=dec(v['cash']),net=r['expected_profit'],roi=r['return_pct'],target_received_at=r['target_received_at'],reference_retrieved_at=r['reference_retrieved_at'],match=True))
        # Compare against retained evidence; routine tests must never rewrite it.
        self.assertEqual(evidence, json.loads(Path('evidence/multi-page-research/reconciliation.json').read_text()))

    def test_identity_orientation_and_each_assessment(self):
        values=list(self.entries.values())
        for entry in values:
            c,a=entry['comparison'],entry['assessment'];g=c['target_identity']
            self.assertTrue(binding_matches(c,a,g));self.assertEqual(a['binding']['target_team'],g['sides']['kalshi:yes']['participant'])
            reverse=deepcopy(c);reverse['source_result']['page']['sides'].reverse()
            self.assertEqual(estimate(c,a,g)['probability'],estimate(reverse,a,g)['probability'])
            for other in values:
                if other is entry:continue
                self.assertFalse(binding_matches(c,other['assessment'],g))
                with self.assertRaises(ValueError):source_for_game(self.raw,self.meta,other['assessment']['binding']['source_event_id'],g)
            wrong=deepcopy(g);wrong['scheduled_start']='2026-09-21T17:00:00Z'
            with self.assertRaises(ValueError):source_for_game(self.raw,self.meta,a['binding']['source_event_id'],wrong)
            a=deepcopy(a);a['ordinary_winner_comparable']=False;a['unavailable_reason']='Saved overtime binding unsupported'
            r=estimate(c,a,g);self.assertIsNotNone(r['probability']);self.assertIsNone(r['expected_profit']);self.assertIn(a['unavailable_reason'],r['reasons'])
            self.assertIsNone(estimate(c,a,g,scenario='unknown')['expected_profit'])

    def test_pair_failures_are_local(self):
        entry=list(self.entries.values())[4];g=entry['comparison']['target_identity'];eid=entry['assessment']['binding']['source_event_id']
        # Change only the selected event block, retaining a consistent test hash.
        source=self.raw.decode();start=source.index('/nfl/events/'+eid+'/odds/',source.index('id="odds-table-moneyline--0"'));lo=source.rfind('<tr',0,start);hi=source.index('game-time',start)
        block=source[lo:hi]
        for altered in (block.replace('alt="draftkings"','alt="missing"'),block.replace('alt="fanduel"','alt="draftkings"'),block.replace('+120','bad')):
            self.assertNotEqual(altered,block)
            raw=(source[:lo]+altered+source[hi:]).encode();meta=dict(self.meta,sha256=sha256(raw).hexdigest())
            with self.assertRaises(ValueError):source_for_game(raw,meta,eid,g)
            other=list(self.entries.values())[0]
            self.assertEqual(source_for_game(raw,meta,'32144330',other['comparison']['target_identity'])['page']['sides'][0]['american_price'],'+180')

    def test_exact_sort_and_unavailable_after_numbers(self):
        rows=[dict(id=str(i),game_title='game',profit=n,return_pct=n) for i,n in enumerate([None,'-1','0','1.00000000000000000000000000001','1.00000000000000000000000000002'])]
        for sort in ('roi','dollars'):self.assertEqual([r['id'] for r in rank_research(rows,sort)],['4','3','2','1','0'])
        entry=next(iter(self.entries.values()));c=entry['comparison'];a=entry['assessment'];g=c['target_identity']
        # Explicit synthetic copied probability exercises exact zero and signs.
        for p,sign in [('0.696','zero'),('0','negative'),('1','positive')]:
            x=deepcopy(c)
            for s in x['source_result']['page']['sides']:
                if s['team']==x['target_contract']['team']:s['probability']=p
            net=Decimal(estimate(x,a,g,'10')['expected_profit'])
            self.assertTrue(net==0 if sign=='zero' else net<0 if sign=='negative' else net>0)

class MultiPageRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_research_drilldown_same_basis_and_separation(self):
        from app.dashboard.multi_game_server import create_app
        client=TestClient(TestServer(create_app(sessions={})));await client.start_server()
        try:
            async def get(path,**q):
                response=await client.get(path,params=q);self.assertEqual(response.status,200);return await response.json()
            q=dict(capture=SESSION,quantity='100',scenario='cent',view='research')
            r=await get('/api/dashboard',**q,positive='true',freshness='usable',venue='polymarket_us')
            self.assertEqual(len(r['rows']),6);self.assertTrue(any(Decimal(x['profit'])<0 for x in r['rows']))
            for row in r['rows']:
                detail=await get('/api/calculate',session=row['session'],hash=row['hash'],cutoff=row['cutoff'],quantity='100',scenario='cent',contract='kalshi:yes')
                self.assertEqual(detail['page_estimate'],row['research']);self.assertIsNone(detail['ev']['probability'])
                detail=await get('/api/calculate',session=row['session'],hash=row['hash'],cutoff=row['cutoff'],quantity='100',scenario='cent',contract='kalshi:yes',probability='0.4')
                self.assertEqual(detail['page_estimate'],row['research']);self.assertEqual(detail['ev']['probability'],'0.4')
            unknown=await get('/api/dashboard',**dict(q,scenario='unknown'));self.assertTrue(all(x['profit'] is None for x in unknown['rows']))
            for view,count in [('arb',18),('ev',24)]:
                other=await get('/api/dashboard',**dict(q,view=view));self.assertEqual(len(other['rows']),count);self.assertTrue(all('research' not in x for x in other['rows']))
                if view=='ev':self.assertTrue(all(x['probability'] is None for x in other['rows']))
            for entry in saved_comparisons().values():
                g=entry['comparison']['target_identity'];row=research_row(SESSION,g,'100','cent',{},live=True)
                self.assertIsNone(row['profit']);self.assertIsNone(row['probability'])
        finally:await client.close()
