"""Independent UI01 values and projection/search invariants."""
from copy import deepcopy
from fractions import Fraction as F
from unittest import TestCase
from app.dashboard.snapshot_display import presented, odds
from app.dashboard.snapshot_api import page
from app.dashboard.u0_display import quote_display


class SnapshotDisplay(TestCase):
    def row(self, **kw):
        return dict(id='a', game_key='ravens', game_title='JAC vs BAL',
                    start_at='2026-11-06', league='NFL', market={'market':'winner'},
                    original={'value':'8.33','units':'decimal_odds','payout':'1'},
                    cost_per_normal_claim='100/833', probability='37/267',
                    gross_return_percent='4121/267', **kw)

    def test_winnipeg_exact_oracle_and_display(self):
        row=self.row();before=deepcopy(row);d=presented(row)['display']
        self.assertEqual(d['offered']['american'],'+733')
        self.assertEqual(d['fair']['american'],'+621.62')
        self.assertEqual(F(d['win_profit_per_100']),733)
        self.assertEqual(F(d['gross_profit_per_100']),F(100)*(F(37,267)*F('8.33')-1))
        self.assertEqual(row,before)

    def test_canonical_default_preserved_and_precision_optional(self):
        self.assertEqual(quote_display('1.11','decimal_odds')['american'],'-909')
        self.assertEqual(odds('1.11')['american'],'-909.09')
        self.assertEqual(odds('2')['american'],'+100')
        self.assertEqual(odds('0.2500','usd_per_contract')['decimal'],'4')
        self.assertIsNone(odds('0','usd_per_contract')['american'])

    def test_full_names_and_abbreviations_same_result(self):
        result=dict(rows=[self.row()],pairs=[],references=[],games=[dict(game_key='ravens',title='JAC vs BAL',participants=[dict(id='NFL:BAL',name='Baltimore Ravens'),dict(id='NFL:JAX',name='Jacksonville Jaguars')])])
        for term in ['Baltimore','Ravens','BAL','baltimore ravens','JAX']:
            self.assertEqual(page(result,{'search':term})['total'],1,term)
        self.assertEqual(page(result,{'search':'zzzzz'})['total'],0)

    def test_format_projection_does_not_change_rank_or_originals(self):
        rows=[]
        for i,value in enumerate(['-1','0','5',None]):
            row=self.row();row['id']=str(i);row['gross_return_percent']=value;rows.append(row)
        result=dict(rows=rows,pairs=[],references=[]);before=deepcopy(result)
        first=page(result,{'limit':'2'});last=page(result,{'offset':'2','limit':'2'})
        self.assertEqual([r['gross_return_percent'] for r in first['rows']+last['rows']],['5','0','-1',None])
        self.assertEqual(result,before)

    def test_pair_carries_both_literal_positions_and_prices(self):
        a=self.row(kind='single');b=self.row(kind='single');b['id']='b';b['original']['value']='2.50';b['native_side']='Short'
        pair=dict(kind='pair',legs=['a','b'],minimum_return_percent='0')
        p=presented(pair,{'a':a,'b':b})['display']
        self.assertEqual([q['display']['offered']['american'] for q in p['positions']],['+733','+150'])
        self.assertEqual(p['minimum_profit_per_100'],'0')
        self.assertEqual(p['positions'][1]['native_side'],'Short')

    def test_unknown_probability_stays_unknown(self):
        q=self.row();q.update(probability=None,gross_return_percent=None)
        self.assertIsNone(presented(q)['display']['fair'])
        self.assertIsNone(presented(q)['display']['gross_profit_per_100'])
