import unittest
import tempfile
from pathlib import Path
from copy import deepcopy
from decimal import Decimal
from aiohttp.test_utils import AioHTTPTestCase
from app.dashboard.opportunity_board import load_sessions,create_app
from app.opportunities.board import evaluate,contracts,ASSESSMENT_AT
from app.dashboard.e6_real import exact_time
from app.dashboard.multi_game import default_point

class BoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sessions=load_sessions();p,cls.rows=next(iter(cls.sessions.values()));cls.timeline=p['timeline'];cls.point=default_point(cls.timeline)
    def calc(self,**kwargs):return evaluate(self.point,self.rows,**kwargs)
    def test_native_orientation_and_no_short_purchase(self):
        r=self.calc();legs={x['id']:x for x in r['contracts']}
        self.assertEqual(legs['kalshi:yes']['team'],'Buffalo Bills')
        self.assertEqual(legs['polymarket_us:1315440']['team'],'Detroit Lions')
        self.assertIsNone(legs['polymarket_us:1315441']['ask'])
        self.assertIsNone(legs['polymarket_us:1315441']['levels'])
        self.assertEqual(legs['kalshi:no']['contract'],'Buffalo does not win (NO)')
        self.assertEqual(r['candidates'][0]['settlement']['status'],'INCOMPATIBLE')
        self.assertIsNone(r['candidates'][0]['worst_case_all_outcomes'])
    def test_asof_and_future_rows(self):
        for p in self.timeline:
            r=evaluate(p,self.rows)
            for l in r['contracts']:
                if l['received_at']:self.assertLessEqual(exact_time(l['received_at']),exact_time(p['at']))
            for source in r['assessment']['sources'].values():self.assertLessEqual(exact_time(source['known_at']),exact_time(p['at']))
        early=self.timeline[0];r=evaluate(early,self.rows)
        self.assertTrue(all(l['ask'] is None for l in r['contracts']))
        self.assertIsNone(r['ev']['expected_profit'])
        prefix=[x for x in self.rows if exact_time(x['observed_at'])<=exact_time(self.point['at'])]
        self.assertEqual(self.calc(),evaluate(self.point,prefix))
    def test_stale_disconnect_and_skew(self):
        p=deepcopy(self.point);p['cards'][0]['receipt_stale']=True;p['cards'][0]['connection']='disconnected';p['cards'][0]['book']['sync']='unsynchronized';p['cards'][0]['book']['received_at']='2026-09-15T20:29:00+00:00'
        r=evaluate(p,self.rows);c=next(c for c in r['candidates'] if c['id']=='cross-buffalo')
        self.assertIn('Receipt stale at cutoff',c['reasons']);self.assertIn('Venue disconnected at cutoff',c['reasons']);self.assertIn('Books more than 5 seconds apart at cutoff',c['reasons']);self.assertFalse(c['current_executable'])
    def test_independent_real_arithmetic(self):
        # 100*.68=68; Kalshi .07*100*.68*.32=1.5232 -> cent cash 69.53.
        # 100*.33=33; US .06*100*.33*.67=1.3266 -> 1.33. Total 103.86.
        r=self.calc();c=next(c for c in r['candidates'] if c['id']=='cross-buffalo')
        self.assertEqual(Decimal(c['cash']),Decimal('103.86'));self.assertEqual(Decimal(c['profit']),Decimal('-3.86'))
        self.assertEqual(Decimal(c['raw_gap']),Decimal('-.01'))
        self.assertEqual(Decimal(c['return_pct']).quantize(Decimal('.000001')), (Decimal('-3.86')/Decimal('103.86')*100).quantize(Decimal('.000001')))
    def test_independent_positive_negative_unknown_ev(self):
        for p,profit in [('0.5','15.67'),('0.2','-14.33'),('0','-34.33'),('1','65.67')]:
            e=self.calc(probability=p)['ev'];self.assertEqual(Decimal(e['expected_profit']),Decimal(profit));self.assertEqual(Decimal(e['break_even_pct']),Decimal('34.33'))
        r=self.calc(scenario='unknown',probability='0.5');self.assertIsNone(r['ev']['expected_profit']);self.assertIsNone(r['ev']['break_even_pct'])
        self.assertIsNone(r['candidates'][0]['profit']);self.assertTrue(any(c['raw_gap'] is not None for c in r['candidates']))
        self.assertEqual(self.calc()['ev']['leg']['fee_audit']['context']['trade_time'],self.point['at'])
        self.assertEqual(self.calc()['assessment']['assessed_at'],ASSESSMENT_AT)
    def test_synthetic_positive_and_depth(self):
        # Modify only test copies: 100 contracts at .20 each side, fee independently .07*100*.2*.8=1.12;
        # US .06*100*.2*.8=.96. Gross 100 -40 -2.08 =57.92.
        p=deepcopy(self.point)
        for card in p['cards']:
            b=card['book']
            if card['venue']=='kalshi':
                target=next(o for o in b['outcomes'] if o['side']=='yes');other=next(o for o in b['outcomes'] if o['side']=='no')
                target['quote'].update(ask='0.20',ask_size='100');other['depth']['bids']['levels']=[dict(price=dict(value='.80'),quantity=dict(value='100',unit='contracts')),dict(price=dict(value='.70'),quantity=dict(value='100',unit='contracts'))]
            else:
                target=b['outcomes'][0];target['quote'].update(ask='.20',ask_size='100');target['depth']['asks']['levels']=[dict(price=dict(value='.20'),quantity=dict(value='100',unit='contracts')),dict(price=dict(value='.30'),quantity=dict(value='100',unit='contracts'))]
        r=evaluate(p,self.rows);c=next(c for c in r['candidates'] if c['id']=='cross-buffalo');self.assertEqual(Decimal(c['profit']),Decimal('57.92'))
        r=evaluate(p,self.rows,quantity='150');c=next(c for c in r['candidates'] if c['id']=='cross-buffalo');self.assertEqual(Decimal(c['notional']),Decimal('70'));self.assertEqual(len(c['legs'][0]['fills']),2)
        c=next(c for c in evaluate(p,self.rows,quantity='201')['candidates'] if c['id']=='cross-buffalo');self.assertIsNone(c['profit']);self.assertIn('quantity exceeds supplied depth',c['reasons'])
    def test_direct_rounding_and_fractional_fill_limit(self):
        c=next(c for c in self.calc(scenario='direct')['candidates'] if c['id']=='cross-buffalo')
        self.assertEqual(Decimal(c['cash']),Decimal('103.8532'))
        p=deepcopy(self.point)
        o=p['cards'][1]['book']['outcomes'][0]
        o['quote'].update(ask='.33',ask_size='99.5')
        o['depth']['asks']['levels']=[dict(price=dict(value='.33'),quantity=dict(value='99.5',unit='contracts')),dict(price=dict(value='.34'),quantity=dict(value='10',unit='contracts'))]
        e=evaluate(p,self.rows,probability='0.5')['ev']
        self.assertIsNone(e['expected_profit'])
        self.assertTrue(any('whole contracts' in x for x in e['leg']['reasons']))

    def test_no_implicit_probability(self):
        ev=self.calc()['ev']
        self.assertIsNone(ev['probability']);self.assertIsNone(ev['expected_profit'])
        self.assertEqual(ev['status'],'Assumption needed')

    def test_input_and_probability_separation(self):
        for kw in [dict(quantity='0'),dict(quantity='1.5'),dict(probability='NaN'),dict(probability='1.01'),dict(scenario='zero')]:
            with self.assertRaises(ValueError):self.calc(**kw)
        a=self.calc(probability='.2');b=self.calc(probability='.8');self.assertEqual(a['candidates'],b['candidates']);self.assertEqual(a['contracts'],b['contracts'])
        self.assertNotEqual(a['ev']['expected_profit'],b['ev']['expected_profit'])
        self.assertIn('excluded',a['ev']['conditional_on'])

class HTTPTests(AioHTTPTestCase):
    async def get_application(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        return create_app(output=Path(tmp.name))
    async def test_readonly_selection(self):
        c=(await (await self.client.get('/api/sessions')).json())[0]
        q=dict(session=c['id'],hash=c['hash'],cutoff=c['timeline'][c['default_cutoff']]['id'],quantity='100')
        response=await self.client.get('/api/calculate',params=q);self.assertEqual(response.status,200)
        result=await response.json();self.assertIsNone(result['ev']['probability']);self.assertIsNone(result['ev']['expected_profit'])
        self.assertEqual((await self.client.get('/api/dashboard')).status,200)
        q['hash']='bad';self.assertEqual((await self.client.get('/api/calculate',params=q)).status,422)
        self.assertEqual((await self.client.post('/api/start')).status,403)

if __name__=='__main__':unittest.main()
