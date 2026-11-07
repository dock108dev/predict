"""Read-only presentation of exact captured inputs; never changes rank or records."""
from decimal import Decimal, localcontext
from fractions import Fraction
from functools import lru_cache
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
    from app.storage.comparison_snapshot import expand_row
    row = expand_row(row)
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
    display['conservative_profit_per_100'] = row.get('conservative_return_percent')
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


def outcome_key(row):
    """A browsing bucket, not proof of identical settlement or financial authority.

    Include event, period, predicate and signed line. In particular a native NO
    remains not_win; a Short already normalized to a participant is not negated.
    Missing semantic identity stays source-specific rather than falsely merging.
    """
    s, m = row.get('selection', {}), row.get('market', {})
    predicate = s.get('predicate')
    participant = s.get('participant')
    if (not predicate or not row.get('game_key') or not m.get('period') or not m.get('market')
            or (predicate not in ('over', 'under') and not participant)):
        return ('unresolved', row['id'])
    line = s.get('signed_line', m.get('line'))
    if m['market'] in ('spread', 'total') and line is None:
        return ('unresolved', row['id'])
    if line is not None:
        try:
            line = str(Fraction(line))
        except (ValueError, ZeroDivisionError):
            line = str(line)
    return (row.get('game_key'), m.get('market'), m.get('period'),
            participant if predicate not in ('over', 'under') else None,
            predicate, line, s.get('result_interpretation'))


def ranking_value(row, metric, *, current=False):
    """Only the declared supported current basis may compete; never fill blanks."""
    value = row.get(metric)
    if value is None:
        return None
    if current and row.get('kind') != 'pair':
        if not row.get('price_current') or not row.get('current_authority') or row.get('current_reasons'):
            return None
        status = {'conditional_return_percent': 'after_trade_fee_ev',
                  'conservative_return_percent': 'conservative_trade_fee_ev',
                  'gross_return_percent': 'before_fee_ev', 'net_return_percent': 'assumed_net_ev'}.get(metric)
        state=row.get('metric_status', {}).get(status, {}).get('state', row.get('_metric_states',{}).get(status))
        if status and state != 'available':
            return None
        if metric in ('conditional_return_percent', 'conservative_return_percent'):
            from app.comparison.snapshot_fee_scope import RANKING_BASIS
            key='conditional_trade_benchmark' if metric == 'conditional_return_percent' else 'conservative_trade_benchmark'
            fee = row.get(key)
            available,basis=(fee.get('available'),fee.get('ranking_basis')) if fee is not None else row.get('_fee_bases',{}).get(key,(None,None))
            if not available or basis != RANKING_BASIS:
                return None
    return Fraction(value)


@lru_cache(maxsize=32768)
def outcome_id(key):
    # Bounded cache of semantic IDs only, never prices or current authority.
    from app.storage.store import hashed
    return hashed(key)


def comparison_groups(rows, by_id, metric, *, pairs=False, current=False):
    """Group the complete filtered slate before pagination; preserve every quote."""
    groups = {}
    values = {r['id']: ranking_value(r, metric, current=current) for r in rows}
    def rank(r):
        value = values[r['id']]
        return (value is None, -value if value is not None else 0,
                r.get('start_at', ''), r['id'], r.get('evidence_result_id', ''))
    for row in rows:
        if pairs:
            keys = [outcome_key(by_id[i]) for i in row['legs'] if i in by_id]
            key = ('pair', tuple(sorted(keys, key=repr))) if len(keys) == 2 else ('unresolved', row['id'])
        else:
            key = outcome_key(row)
        groups.setdefault(key, []).append(row)
    result = []
    for key, members in groups.items():
        members = sorted(members, key=rank)
        first = members[0]
        result.append(dict(id=outcome_id(key), kind='pair_group' if pairs else 'outcome_group',
                           game_key=first['game_key'], game_title=first['game_title'],
                           league=first['league'], start_at=first['start_at'],
                           market=first['market'], quotes=members,
                           score=None if values[first['id']] is None else str(values[first['id']]),
                           score_source=None if values[first['id']] is None else dict(
                               id=first['id'], venue=first.get('venue'), source=first.get('source'),
                               evidence_result_id=first.get('evidence_result_id')),
                           outcome_key=list(key),
                           meaning='Display grouping only; each quote retains its own reference and settlement evidence.'))
    return sorted(result, key=lambda g: (g['score'] is None,
        -Fraction(g['score']) if g['score'] is not None else 0, g['start_at'],
        repr(g['outcome_key']), g['quotes'][0]['id']))
