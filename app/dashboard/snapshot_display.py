"""Read-only presentation of exact captured inputs; never changes rank or records."""
from decimal import Decimal, localcontext
from fractions import Fraction
from .u0_display import quote_display


def decimal(value):
    with localcontext() as ctx:
        ctx.prec = 60
        f = Fraction(value)
        return str(Decimal(f.numerator) / Decimal(f.denominator))


def odds(value, units='decimal_odds', payout='1'):
    display = quote_display(value, units, payout, places=2)
    return dict(american=display.get('american'),
                decimal=display.get('conversion', {}).get('decimal_approx'),
                reason=display.get('reason'))


def presented(row, by_id=None):
    out = dict(row)
    original = row.get('original', {})
    display = dict(offered=odds(original.get('value'), original.get('units'), original.get('payout', '1')))
    p = row.get('probability')
    display['fair'] = odds(decimal(1 / Fraction(p))) if p is not None and 0 < Fraction(p) < 1 else None
    ref = row.get('snapshot_benchmark') or row.get('reference') or {}
    display['benchmark'] = [odds(v) for v in ref.get('odds', [])]
    display['benchmark_venue'] = ref.get('bookmaker', 'pinnacle' if row.get('snapshot_benchmark') else None)
    display['gross_profit_per_100'] = row.get('gross_return_percent')
    cost = row.get('cost_per_normal_claim')
    display['win_profit_per_100'] = str(100 * (1 / Fraction(cost) - 1)) if cost else None
    display['net_profit_per_100'] = row.get('net_return_percent')
    display['minimum_profit_per_100'] = row.get('minimum_return_percent')
    if row.get('kind') == 'pair':
        display['positions'] = [presented(by_id[i]) for i in row['legs'] if i in (by_id or {})]
    out['display'] = display
    return out


def search_index(result):
    return {g['game_key']: ' '.join([g.get('title', ''), *[
        str(p.get(k, '')) for p in g.get('participants', []) for k in ('id', 'name')
    ]]).casefold() for g in result.get('games', [])}
