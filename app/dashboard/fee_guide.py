"""Public descriptions of the same reviewed terms used by the trade preview."""
from fractions import Fraction as F
from datetime import datetime, timezone

from app.comparison.cashflows import exact_wire
from app.comparison.snapshot_fee_outcome import reviews
from app.comparison.snapshot_conservative import prophetx_market_commission
from app.comparison.snapshot_polymarket_fee import CURRENT_CUTOVER, order_fee
from app.comparison.current_dependencies import instant
from app.fees import product_schedules, schedule_lifecycle
from app.fees.evidence import applies
from app.storage.store import connect


def hundred_dollar_example(venue, terms, at):
    """Illustrate a new standalone order using the published base schedule."""
    rate = F(terms['fee_rate'])
    if venue == 'prophetx':
        charge = prophetx_market_commission(rate=rate, cost_basis=F(100), gross_payout=F(204))[1]
        return dict(stake='100', upfront='100', entry_fee='0', win_fee=exact_wire(charge),
                    winning_return=exact_wire(204-charge), posted_odds='+104', basis='non-NHL standalone straight')
    rate = F(0) if venue == 'novig' else rate
    quantity = int(100 // (F(1, 2) + rate / 4))
    if venue == 'polymarket_us':
        audit = order_fee('guide-example', inserted_at=at.isoformat(), evaluated_at=at.isoformat(),
                          fills=[dict(price='0.50', quantity=str(quantity))], tier=terms['fee_rate'])
        if audit['entry_fees'] is None:
            return None
        charge = F(audit['entry_fees'])
    else:
        raw = rate * quantity / 4
        charge = F(-(-100 * raw // 1), 100)
    stake = F(quantity, 2)
    return dict(quantity=quantity, stake=exact_wire(stake), upfront=exact_wire(stake+charge),
                entry_fee=exact_wire(charge), win_fee='0', winning_return=str(quantity),
                posted_odds='+100', basis='50-cent posted price, base market multiplier')


def guide():
    with connect() as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        at = datetime.now(timezone.utc)
        products = product_schedules.read_all(db)
        prophetx = schedule_lifecycle.read(db)
        schedules = reviews(at)
    result = {}
    for venue, fallback in schedules.items():
        row = dict(venue=venue, game_state='scheduled')
        terms = (schedule_lifecycle.for_offer(prophetx, row, at, fallback=fallback)
                 if venue == 'prophetx' else product_schedules.for_offer(products, row, at, fallback=fallback))
        available = bool(terms and not terms.get('unavailable_reason') and applies(terms, at))
        if venue == 'polymarket_us' and at >= instant(CURRENT_CUTOVER):
            available = available and terms.get('published_effective_from') == CURRENT_CUTOVER
        item = result[venue] = dict(available=available)
        if not terms:
            continue
        item.update({key: terms[key] for key in ('source_url', 'document_url', 'published_effective_from',
                                                 'published_version', 'effective_from', 'reviewed_at') if key in terms})
        if not available:
            continue
        rate = terms['fee_rate']
        item['rate'] = rate
        item['hundred_dollar_example'] = hundred_dollar_example(venue, terms, at)
        if venue == 'kalshi':
            item['example_fee'] = exact_wire(F(rate) * 100 / 4)
        elif venue == 'polymarket_us' and terms.get('published_effective_from'):
            audit = order_fee('guide-example', inserted_at=at.isoformat(), evaluated_at=at.isoformat(),
                              fills=[dict(price='0.50', quantity='100')], tier=rate)
            item['example_fee'] = audit['entry_fees']
        elif venue == 'prophetx':
            item['nhl_taker_coefficient'] = terms.get('nhl_taker_coefficient')
            item['example_fee'] = exact_wire(prophetx_market_commission(
                rate=rate, cost_basis=F(10), gross_payout=F('20.40'))[1])
    return result
