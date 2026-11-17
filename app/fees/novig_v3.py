"""Calculate a modeled Novig fill against the exact catalog fee schedule."""
from decimal import Decimal, localcontext
from fractions import Fraction

from .engine import Registry, calculate
from .evidence import applies
from .public_bindings import bind


def _fill(price, quantity, unit):
    price = Fraction(price)
    contracts = Fraction(quantity) * 100
    if contracts <= 0 or contracts.denominator != 1 or not 0 < price < 1:
        raise ValueError('Novig fee requires a valid price and whole native contracts')
    with localcontext() as ctx:
        ctx.prec = 60
        # The fee engine takes bounded decimal input. A linked American price
        # may be recurring; this conversion cannot change a no-charge result.
        decimal_price = format(Decimal(price.numerator) / Decimal(price.denominator), '.12f')
    return dict(fill_id='modeled-fill', order_id='modeled-order', role='taker', unit=unit,
                price=decimal_price, quantity=str(contracts))


def _result(result, version):
    if result['entry_fees'] is None:
        raise ValueError('Novig fee schedule cannot calculate this fill')
    return dict(amount=Fraction(result['entry_fees']), schedule_hash=result['schedule_hash'],
                schedule_version=version, trace=result['trace'], assumptions=result['assumptions'])


def taker_fill(*, market_id, terms, event_status, at, price, quantity):
    """Prices and quantities use $1 payout units; v3 fills use 1¢ contracts."""
    fill = dict(_fill(price, quantity, 'novig_v3_contracts'), event_status_at_match=event_status)
    context = bind(dict(venue='novig', environment='production', market_id=market_id,
        api_regime='v3', trade_time=at, calculation_time=at, complete_order_history=True,
        fills=[fill]), market=dict(marketId=market_id, fee=terms))
    return _result(calculate(context), context['schedule_version'])


def retail_pregame_fill(*, market_id, review, at, price, quantity):
    """Apply the reviewed retail straight schedule to an already typed game offer."""
    from app.storage.store import stamp

    if (review.get('product') != 'pregame_straight' or review.get('fee_rate') != '0'
            or review.get('unavailable_reason') or not applies(review, stamp(at))):
        raise ValueError('No applicable reviewed pregame straight fee schedule')
    version = review['version']
    schedule = dict(venue='novig', product='pregame', version=version, coefficient=review['fee_rate'],
        effective_from=review['reviewed_at'], effective_to=review.get('review_before'),
        sources=[dict(url=review['source_url'], sha256=review['sha256'],
                      revision=review.get('verification_revision'))])
    context = dict(venue='novig', environment='production', market_id=market_id, product='pregame',
        schedule_version=version, trade_time=at, calculation_time=at, complete_order_history=True,
        applicability_evidence=dict(product='pregame_straight', review=review.get('verification_revision')),
        fills=[_fill(price, quantity, 'payout_cents')])
    return _result(calculate(context, Registry(dict(schema=1, schedules=[schedule]))), version)
