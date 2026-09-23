"""Independent outcome truth tables, not generated from implementation output."""
import unittest
from copy import deepcopy
from app.normalization.score_lines import payout,partitions,distribution
from app.normalization.first_half import validate_payout
from app.normalization.futures import descriptor
from tests.test_b5_futures import fixture

class Payouts(unittest.TestCase):
    def test_three_way_home_tie_away(self):
        parts=partitions('home_margin','0');truth={'gt':['0','0','1'],'eq':['0','1','0'],'lt':['1','0','0']}
        for op,want in truth.items():
            side=dict(domain='home_margin',threshold='0',operator=op,equality='predicate',refund_fees='retained')
            self.assertEqual([payout(side,p) for p in parts],want)
        self.assertEqual([sum(int(v[n]) for v in truth.values()) for n in range(3)],[1,1,1])
        with self.assertRaises(ValueError):distribution('.6',parts)
    def test_half_shared_and_complement(self):
        parts=partitions('home_margin','0');base=dict(domain='home_margin',threshold='0',equality='fraction',equality_payout='0.5',refund_fees='retained')
        self.assertEqual([payout(dict(base,operator='gt'),p) for p in parts],['0','0.5','1'])
        self.assertEqual([payout(dict(base,operator='le'),p) for p in parts],['1','0.5','0'])
        validate_payout(dict(family='moneyline',line=None,winner_structure='shared_winner',outcomes=[dict(base,operator=k) for k in ['gt','le']]))
    def test_three_shared_champions_cent_floor_and_unknown_fair_price(self):
        rows=fixture(overlap=True,unknown=True);e=rows[1]['inventory']['kalshi']['events'][0];d=rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor']
        e['states'][-2]['winners']=e['field'];
        for side in d['outcomes']:side['payouts']['shared']='0.33' if side['role']=='achievement' else '0.67'
        self.assertEqual(descriptor(e,d)['domain'],'championship_states')
        d['outcomes'][0]['payouts']['shared']='0.333333'
        with self.assertRaisesRegex(ValueError,'cent-floor'):descriptor(e,d)
    def test_fractional_cashflow_uses_original_entry_fees(self):
        from tests.test_b5_periods import fixture,snapshot
        from tests.test_b5_score_lines import reseal
        from app.dashboard import product_view
        from decimal import Decimal
        rows=fixture(family='moneyline')
        for source,cat in rows[1]['inventory'].items():
            m=cat['markets'][0];d=m['score_review']['descriptor'];d['winner_structure']='shared_winner'
            for side in d['outcomes']:side.update(equality='fraction',equality_payout='0.5')
            for side in m['product_outcomes']:side.update(equality='fraction',equality_payout='0.5')
            reseal(rows,source)
        s=snapshot(rows);g=s['games'][0];key=next(k for k in g['sides'] if k.startswith('kalshi:yes:'));r=product_view.calculate(s,g,dict(contract=key,quantity='100',probability={'below':'.3','equal':'.1','above':'.6'}));leg=r['ev']['leg']
        self.assertEqual(Decimal(leg['cashflows']['equal']['gross_payout']),Decimal('50'))
        self.assertEqual(Decimal(leg['cashflows']['equal']['net_cashflow']),Decimal('50')-Decimal('68')-Decimal('1.53'))
