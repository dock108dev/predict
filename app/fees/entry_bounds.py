"""Allocation-independent US entry bound; shared by dated review and provisional display."""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN


def us_taker_bound(fills, coefficient="0.0695"):
    theta=Decimal(coefficient)
    if not theta.is_finite() or not 0<=theta<=1:raise ValueError("unsupported fee coefficient")
    if not fills:raise ValueError('fills required')
    with localcontext() as ctx:
        ctx.prec=100
        raw=Decimal(0);quantity=Decimal(0)
        for fill in fills:
            if not isinstance(fill.get('price'),str) or not isinstance(fill.get('quantity'),str):raise ValueError('decimal strings required')
            p=Decimal(fill['price']);q=Decimal(fill['quantity'])
            if not p.is_finite() or not q.is_finite() or not Decimal('.01')<=p<=Decimal('.99') or q<=0:raise ValueError('unsupported price/quantity')
            if len(p.as_tuple().digits)>24 or len(q.as_tuple().digits)>24 or abs(q.as_tuple().exponent)>12:raise ValueError('bounded decimal required')
            raw+=theta*q*p*(1-p);quantity+=q
        cap=raw.quantize(Decimal('.01'),rounding=ROUND_HALF_EVEN)
    return dict(available=True,lower='0.00',upper=str(cap),exact_fee=None,raw_model_fee=str(raw),quantity=str(quantity),coefficient=str(theta),
        rounding='Per-fill half-even cents capped by cumulative rounded exact fees; counterparty fill allocation unknown')
