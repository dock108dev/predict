"""Exact normalized gross arithmetic, using the shared settlement engine.

A pair of $1 normal-win payouts is a mathematical basis, never execution sizing.
Probability is independent input; inverse odds is never supplied as fair value.
"""
from fractions import Fraction
from decimal import Decimal, localcontext
from app.settlement import portfolio


def normalized_pair(left, right):
    prices=[Fraction(left),Fraction(right)]
    if any(p<=0 or p>=1 for p in prices):raise ValueError('Positive price below normalized payout required')
    cash=sum(prices)
    pct=(1-cash)/cash*100
    with localcontext() as ctx:
        ctx.prec=100
        def value(f):return str(Decimal(f.numerator)/Decimal(f.denominator))
        # Same shared cashflow solver used by depth/EV. Zero fees here mean
        # arithmetic before costs, explicitly labeled gross, never supported net.
        shared=portfolio([dict(id=str(i),cash=value(p),receipts={'left':'1' if i==0 else '0','right':'1' if i==1 else '0'}) for i,p in enumerate(prices)],['left','right'],complete=True)
        return dict(value=value(pct),numerator=str(pct.numerator),denominator=str(pct.denominator),
                    acquisition_cost=value(cash),normal_payout='1',engine_version=shared['version'],
                    formula='100 × (1 − (left price + right price)) / (left price + right price)',
                    denominator_basis='Combined acquisition cost for one $1 normal-win payout on each opposing outcome')
