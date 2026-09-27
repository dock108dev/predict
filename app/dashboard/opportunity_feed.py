"""Presentation groups over the ordinary shared calculation results."""
from decimal import Decimal

GROUPS = ('Sourced model EV%', 'Manual What-if EV%', 'Bookmaker-derived estimate %',
          'EV unavailable', 'Arbitrage return %')


def combine(ev, arb):
    rows = []
    for original in ev + arb:
        row = dict(original)
        is_arb = bool(row.get('candidate'))
        if is_arb and len(set(row['venues'])) < 2:
            continue
        role = row.get('reference_role')
        group = (GROUPS[4] if is_arb else GROUPS[0] if role == 'model_reference'
                 else GROUPS[2] if row.get('reference_id') else GROUPS[1]
                 if row.get('probability') is not None else GROUPS[3])
        row.update(group=group, calculation_view='arb' if is_arb else 'ev')
        if row.get('return_pct') is None:
            row['unavailable_reason'] = ('Probability input unavailable. ' if not is_arb and row.get('probability') is None else '') + '; '.join(dict.fromkeys(
                row.get('reasons', []) + [reason for leg in row['legs'] for reason in leg.get('reasons', [])]))
            row['unavailable_reason'] = row['unavailable_reason'] or 'Material costs, payout or purchasable size unavailable'
        rows.append(row)
    # No status, usability or dollar priority ahead of supported percentages.
    rows.sort(key=lambda r: (GROUPS.index(r['group']), r.get('return_pct') is None,
                            -Decimal(r['return_pct']) if r.get('return_pct') is not None else Decimal(0), r['id']))
    return rows
