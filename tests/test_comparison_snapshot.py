"""Hand-calculated exact vectors, independent of captured authentic observations."""
from fractions import Fraction as F
from unittest import TestCase
from app.comparison.snapshot_math import assumptions,funded
from app.dashboard.snapshot_api import page


class SnapshotMath(TestCase):
    def settings(self,**changes):
        return assumptions(dict(amount='1000',buffer='0.005',scenario='decisive_only',
            sizing='hypothetical_fractional',fees={'novig':'0','prophetx':'0'},**changes))

    def test_positive_zero_negative_single_and_one_buffer(self):
        a,p=self.settings()
        # $1000 / $0.50 buys 2000 claims. EV = 2000*p - 1000;
        # exactly $5 is then deducted, once.
        for probability,expected in [('0.6','195'),('0.5025','0'),('0.4','-205')]:
            r=funded(['0.5'],[probability],['novig'],a,p)
            self.assertEqual(r['buffered_profit_usd'],expected)
            self.assertEqual(r['buffer_usd'],'5')
            self.assertEqual(r['quantity_per_leg'],'2000')

    def test_fees_consume_funding_and_not_unused_cash(self):
        a,p=assumptions(dict(amount='1020',buffer='0.005',scenario='decisive_only',sizing='hypothetical_fractional',fees={'novig':'0.02'}))
        r=funded(['0.5'],['0.6'],['novig'],a,p)
        # 2000 claims cost 1000 plus 20 fees; expected receipt 1200.
        self.assertEqual(r['quantity_per_leg'],'2000')
        self.assertEqual(r['acquisition_usd'],['1000'])
        self.assertEqual(r['upfront_fees_usd'],['20'])
        self.assertEqual(r['fee_adjusted_expected_profit_usd'],'180')
        self.assertEqual(r['buffered_profit_usd'],'174.9')
        self.assertEqual(r['unused_cash_usd'],'0')

    def test_opposing_minimum_without_ev_probability(self):
        a,p=self.settings()
        r=funded(['0.4','0.5'],[None],['novig','prophetx'],a,p)
        # 10000/9 claims on each side cost exactly 1000. Both states
        # return 10000/9; min profit = 1000/9; buffered = 955/9.
        self.assertEqual(F(r['scenario_minimum_usd']),F(955,9))
        self.assertIsNone(r['buffered_profit_usd'])
        self.assertEqual(set(r['scenario_profits_usd'].values()),{'1000/9'})

    def test_refund_other_probability_is_independent_of_minimum(self):
        a,p=assumptions(dict(amount='1000',buffer='0.005',scenario='refund_other',sizing='hypothetical_fractional',fees={'novig':'0','prophetx':'0'}))
        r=funded(['0.4','0.5'],['0.5'],['novig','prophetx'],a,p)
        self.assertEqual(r['scenario_minimum_usd'],'-5')
        self.assertIsNone(r['buffered_profit_usd'])
        a['exception_probability']='0.1'
        r=funded(['0.4','0.5'],['0.5'],['novig','prophetx'],a,p)
        self.assertEqual(r['buffered_profit_usd'],'95')

    def test_missing_inputs_and_no_implicit_zero_fee(self):
        a,p=assumptions()
        r=funded(['0.5'],['0.6'],['novig'],a,p)
        self.assertFalse(r['available']);self.assertEqual(len(r['missing']),3)
        for bad in ({'fees':{'novig':'-0.1'}},{'exception_probability':'1.1'},{'amount':'0'},{'fees':{'novig':'1e99999999'}},{'fees':{'novig':0}},{'exception_probability':0}):
            with self.assertRaises(ValueError):assumptions(bad)

    def test_rank_includes_zero_negative_and_complete_pages(self):
        rows=[dict(id=str(i),gross_return_percent=v,start_at='a',game_title='Test',league='NFL',market={}) for i,v in enumerate(['-2','0','3',None])]
        result=dict(rows=rows,pairs=[],references=[],id='result')
        self.assertEqual([r['gross_return_percent'] for r in page(result,{'limit':'2'})['rows']],['3','0'])
        self.assertEqual([r['gross_return_percent'] for r in page(result,{'limit':'2','offset':'2'})['rows']],['-2',None])

    def test_grid_does_not_merge_unmatched_outcomes_across_games(self):
        rows=[dict(id=str(i),quote_id=str(i),game_key='game-'+str(i),game_title='Game '+str(i),
            start_at='a',venue='novig',market={'market':'total','period':'full_game'},
            selection={'predicate':'over','signed_line':'10.5'},same_outcome={'supported':False}) for i in range(2)]
        result=dict(rows=rows,pairs=[],references=[],id='result')
        grid=page(result,{'view':'odds'})
        self.assertEqual(grid['total'],2)
        self.assertTrue(all(len(g['quotes'])==1 for g in grid['rows']))

    def test_opposing_zero_and_negative_have_numeric_minima(self):
        a,p=assumptions(dict(amount='1000',buffer='0',scenario='decisive_only',sizing='hypothetical_fractional',fees={'novig':'0','prophetx':'0'}))
        for costs,expected in [(['0.5','0.5'],F(0)),(['0.5','0.6'],-F(1000,11))]:
            r=funded(costs,[None],['novig','prophetx'],a,p)
            self.assertEqual(F(r['scenario_minimum_usd']),expected)


def test_snapshot_codec_preserves_legacy_originals():
    import gzip
    from app.storage.comparison_snapshot import pack, unpack
    from app.storage.store import encoded
    packet={'name':'Montréal','price':'0.0400','clock':None}
    legacy=gzip.compress(encoded(packet),compresslevel=1)
    assert unpack(legacy)==unpack(pack(packet))==packet
