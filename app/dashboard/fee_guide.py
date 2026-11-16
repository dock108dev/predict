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
