"""Prepare retail previews from the same immutable economics as the desk."""

from app.comparison.trade_preview import preview
from app.storage import comparison_snapshot as snapshots
from app.storage.store import stamp


def claim_cost(row):
    from fractions import Fraction

    from app.comparison.cashflows import exact_wire
    from .current_contract import price

    if row.get('cost_per_normal_claim') is not None:
        return row['cost_per_normal_claim']
    try:
        if Fraction(row['original'].get('payout', '1')) == 1:
            return exact_wire(price(row))
    except (KeyError, ValueError, TypeError, ArithmeticError):
        pass
    return None


def missing_terms(row):
    return (row['venue'] in ('kalshi', 'polymarket_us')
            and (row.get('trade_fee') or {}).get('available')
            and not (row.get('preview_fee_input') or row.get('fee_applicability')))


def published_members(db, rows):
    wanted = {}
    for row in rows:
        if (member := row.get('evidence_result_id')) and missing_terms(row):
            wanted.setdefault(member, set()).add(row['id'])
    if not wanted:
        return {}
    members = {}
    # Stream the batches of compressed members. Never keep full decoded
    # captures in memory just to recover a few per-offer sizing fields.
    ids = list(wanted)
    for offset in range(0, len(ids), 16):
        for stored in db.execute('SELECT id, result FROM comparison_snapshot_result WHERE id=ANY(%s)',
                                 (ids[offset:offset + 16],)):
            member = stored['id']
            result = snapshots.unpack(stored['result'], db=db, lazy=True)
            for row in result['rows']:
                if row['id'] in wanted[member]:
                    exact = snapshots.expand_row(row)
                    members[member, row['id']] = exact.get('preview_fee_input') or exact.get('fee_applicability')
    return members


def prepared_preview(row, amount, members):
    row = snapshots.expand_row(row)
    if missing_terms(row):
        row = dict(row, fee_applicability=members.get((row.get('evidence_result_id'), row['id'])))
    baseline = row.get('sportsbook_baseline') or {}
    prices = baseline.get('prices') or ()
    if len(prices) != 2 or any(not price.get('price_american') for price in prices):
        row = dict(row, sportsbook_baseline=None)
    result = preview(dict(row, cost_per_normal_claim=claim_cost(row)), amount)
    if result.get('estimated_return_percent') is None:
        result['estimated_return_reason'] = (result.get('reason') or result.get('fee_reason')
                                             or 'exact_reference_pair_unavailable')
    return result
