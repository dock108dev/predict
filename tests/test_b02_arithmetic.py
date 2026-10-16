"""Independent Fraction arithmetic from authentic original prices and public model terms.

No financial owner supplies the expected cashflows, fees, reference weights or
buffer. Retained facts are historical, not fresh trades or execution evidence.
"""
from fractions import Fraction as F
from unittest import TestCase
from app.comparison.estimated_ev import evaluate
from app.comparison.estimated_pair import Leg, evaluate as pair
from app.comparison.current_dependencies import instant
from app.dashboard.comparison_board import entries
from tests.test_ev09_n01 import retained, AT


def ceil4(x):
    n=x*10000
    return F(-(-n.numerator//n.denominator),10000)


def cashflows(q,n,home):
    price=F(q['original']['value'])
    selected_home=q['binding']['selection']['participant']==home
    if q['venue']=='novig':
        acquisition=n;fee=F(0);winning=n*price;tie=n;cancel=n
    elif q['venue']=='kalshi':
        acquisition=n*price;fee=ceil4(F('0.07')*n*price*(1-price));winning=n;tie=n/2;cancel=acquisition
    else:raise AssertionError('oracle scope')
    capital=acquisition+fee
    return capital,fee,dict(a_wins=(winning if selected_home else 0)-capital,
        b_wins=(0 if selected_home else winning)-capital,tie=tie-capital,terminal_noncompletion=cancel-capital)


class IndependentArithmetic(TestCase):
    def test_saved_sportsbook_native_and_mixed_pair(self):
        b,s=retained();rows=entries(s);profiles=s['comparison_profiles']
        fair=(1/F('2.23'))/((1/F('2.23'))+(1/F('1.72')))
        probabilities=dict(a_wins=(1-F('.005')-F('.001'))*fair,
            b_wins=(1-F('.005')-F('.001'))*(1-fair),tie=F('.005'),terminal_noncompletion=F('.001'))
        selected=[]
        for venue in ('novig','kalshi'):
            e,g,q=next(x for x in rows if x[2]['venue']==venue and x[2]['binding']['selection']['participant']==('NFL:SEA' if venue=='novig' else 'NFL:DEN') and x[2]['source']['native_side']!='no')
            selected.append((e,g,q))
            r=evaluate(q,profiles,at=instant(AT),event=e,group=g,details=True)
            capital,fee,profits=cashflows(q,F(r['native_quantity']),'NFL:DEN')
            ev=sum(probabilities[k]*v for k,v in profits.items())
            self.assertEqual(F(r['deployed_capital_usd']),capital)
            self.assertEqual(F(r['net_entry_fee_usd']),fee)
            self.assertEqual(F(r['financial_metrics']['net_modeled_ev_usd']),ev)
            self.assertEqual(F(r['financial_metrics']['buffered_ev_usd']),ev-capital/200)
            self.assertEqual(F(r['financial_metrics']['buffered_return_percent']),100*(ev-capital/200)/capital)
        result=pair([Leg(q,g,profiles,e,instant(AT)) for e,g,q in selected],details=True)
        expected=[cashflows(q,F(leg['native_quantity']),'NFL:DEN') for (_,_,q),leg in zip(selected,result['legs'])]
        capital=sum(c for c,_,_ in expected);profits={k:sum(p[k] for _,_,p in expected) for k in ('a_wins','b_wins')}
        conditional=fair*profits['a_wins']+(1-fair)*profits['b_wins']
        self.assertEqual(F(result['deployed_capital_usd']),capital)
        self.assertEqual(F(result['financial_metrics']['buffered_decisive_opposing_margin_usd']),min(profits.values())-capital/200)
        self.assertEqual(F(result['financial_metrics']['conditional_buffered_ev_usd']),conditional-capital/200)
        self.assertIsNone(result['financial_metrics']['buffered_ev_usd'])
