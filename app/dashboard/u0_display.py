"""predict-current-1 display adapter. Decimal originals are never display inputs."""
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_UP
import re

VERSION = 'predict-current-1'


def bounded_decimal(value):
    if not isinstance(value,str) or len(value)>256 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',value):
        raise ValueError('Bounded finite decimal string required')
    if 'e' in value.lower() and abs(int(value.lower().split('e')[1]))>256:
        raise ValueError('Original exponent outside bounds')
    d=Decimal(value)
    if not d.is_finite():raise ValueError('Finite decimal required')
    return d


def quote_display(value, units, payout='1'):
    """Convert supported normal-win $1 claims; unsupported data stays inspectable."""
    invalid = dict(supported=False, american=None, cents=None, equivalent=None,
                   reason='Unsupported units or payout basis')
    if not isinstance(value, str) or not isinstance(payout, str):
        return dict(invalid, reason='Original decimal strings required')
    if len(value)>256 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',value):
        return dict(invalid, reason='Invalid or out-of-range decimal')
    if 'e' in value.lower() and abs(int(value.lower().split('e')[1]))>256:
        return dict(invalid, reason='Original exponent outside bounds')
    try:
        with localcontext() as ctx:
            ctx.prec = max(60, len(value)+abs(Decimal(value).adjusted())+20)
            v, basis = bounded_decimal(value), bounded_decimal(payout)
            if not v.is_finite() or not basis.is_finite():
                return dict(invalid, reason='Nonfinite original value')
            if basis != 1 or units not in ('usd_per_contract', 'cents_per_contract', 'decimal_odds'):
                return invalid
            if units == 'decimal_odds':
                if v <= 1:
                    return dict(invalid, reason='Decimal odds must exceed 1')
                d, p = v, 1/v
            else:
                p = v/100 if units == 'cents_per_contract' else v
                if not 0 < p < 1:
                    return dict(invalid, reason='Contract price must be strictly between 0 and $1')
                d = 1/p
            # Derive from the original value, not rounded d or display cents.
            a = (v-1)*100 if units == 'decimal_odds' and v >= 2 else -100/(v-1) if units == 'decimal_odds' else 100*(1-p)/p if p <= Decimal('.5') else -100*p/(1-p)
            cents = v*100 if units == 'usd_per_contract' else v if units == 'cents_per_contract' else 100/v
            american = a.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            return dict(supported=True, american=f'{american:+.0f}',
                        cents=f"{cents.quantize(Decimal('.1'), rounding=ROUND_HALF_UP):.1f}",
                        equivalent=units=='decimal_odds', reason=None,
                        conversion=dict(original=value, units=units, payout=payout,
                                        method='normal-win-dollar-1', decimal_approx=str(d),
                                        price_approx=str(p), precision=ctx.prec),
                        # Explicit manual scenario, not an estimated probability or venue cost.
                        what_if=dict(probability='0.5', cost_assumption='0',
                                     gross_profit_per_dollar_payout=str(Decimal('.5')-p)))
    except (InvalidOperation, ArithmeticError, ValueError):
        return dict(invalid, reason='Invalid or out-of-range decimal')
