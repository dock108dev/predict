"""Compact, sorted views of the ordinary publication for the three-page desk."""
from datetime import date, datetime
from fractions import Fraction
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.storage.comparison_snapshot import expand_row
from .local_security import PublicRequestError
from .snapshot_display import comparison_groups, odds, ranking_value, search_index


EV_METRIC = 'gross_return_percent'


def number(value):
    if len(value) > 40 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', value):
        raise ValueError('Expected a decimal')
    return Fraction(value)


def filters(query):
    try:
        zone = ZoneInfo(query.get('timezone') or 'UTC')
        day = date.fromisoformat(query['day']) if query.get('day') else None
        minimum = number(query['minimum']) if query.get('minimum') else None
        dollars = number(query['profit']) if query.get('profit') else None
        stake = number(query.get('stake', '100'))
        if not 0 < stake <= 1_000_000:
            raise ValueError()
    except (ValueError, ZeroDivisionError, ZoneInfoNotFoundError):
        raise PublicRequestError('Check the date, time zone, stake and minimums') from None
    return zone, day, minimum, dollars, stake


def offer(original, metric=None):
    row = expand_row(original)
    price = row['original']
    ref = row.get('snapshot_benchmark') or row.get('reference') or {}
    ref_venue = ref.get('bookmaker', 'pinnacle' if row.get('snapshot_benchmark') else None)
    value = ranking_value(row, metric, current=True) if metric and ref_venue == 'pinnacle' else None
    reasons = row.get('current_reasons', [])
    reference = row.get('reference_calculation') or {}
    reference_prices = ref.get('odds') or []
    selected = ref.get('selected')
    selected_price = ref.get('selected_odds')
    if selected_price is None and isinstance(selected, int) and 0 <= selected < len(reference_prices):
        selected_price = reference_prices[selected]
    reason = None
    if metric and value is None:
        if not row.get('price_current'):
            reason = 'Price expired' if 'source_expired' in reasons else 'Price unavailable'
        elif row.get('probability_missing') == 'finance_pending':
            reason = 'Calculation pending'
        else:
            reason = 'Current Pinnacle reference unavailable'
    return dict(id=row['id'], venue=row['venue'], selection=row.get('selection'),
                participant=row.get('participant_label'), market=row['market'],
                odds=odds(price['value'], price['units'], price.get('payout', '1')),
                current=bool(row.get('price_current')), value=None if value is None else str(value), reason=reason,
                reference=odds(selected_price) if selected_price is not None and ref_venue == 'pinnacle' else None,
                reference_current=value is not None, probability=row.get('probability') if value is not None else None,
                overround=reference.get('overround') if value is not None else None,
                source_at=(row.get('book_confirmation') or {}).get('confirmed_at') or row.get('times', {}).get('source_at'),
                received_at=row.get('times', {}).get('received_at'))


def page(result, query, options, *, captured_pairs=(), policy=None):
    view, _, offset, limit = options
    zone, day, minimum, dollars, stake = filters(query)
    search = search_index(result)
    terms = query.get('search', '').casefold().split()
    leagues, families, venues = (set(query.get(key, '').split(',')) - {''} for key in ('league', 'family', 'venue'))

    def matches(row):
        market = row['market']
        return ((not leagues or row['league'] in leagues) and (not families or market['market'] in families)
                and (not query.get('period') or market['period'] == query['period'])
                and (not day or datetime.fromisoformat(row['start_at']).astimezone(zone).date() == day)
                and all(term in (row['game_title'].casefold() + ' ' + search.get(row['game_key'], '')) for term in terms))

    def passes(value):
        return ((not query.get('positive') or value is not None and value > 0)
                and (minimum is None or value is not None and value >= minimum)
                and (dollars is None or value is not None and value * stake / 100 >= dollars))

    rows = [row for row in result['rows'] if (not venues or row['venue'] in venues) and matches(row)]
    by_id = {row['id']: row for row in rows}
    metric = EV_METRIC
    if view == 'arbs':
        eligible = {r['id']: r for r in rows if r.get('price_current')
                    and r.get('publication_policy') == policy}
        markets = {}
        for pair in captured_pairs:
            proof = pair.get('before_fees')
            if proof and all(leg in eligible for leg in pair['legs']):
                markets.setdefault(proof['market_key'], []).append(pair)
        groups = []
        for key, pairs in markets.items():
            pairs.sort(key=lambda pair: (-Fraction(pair['before_fees']['value']), pair['id']))
            first = pairs[0]
            groups.append(dict(first, id=key, quotes=pairs, score=first['before_fees']['value']))
        groups.sort(key=lambda g: (-Fraction(g['score']), g['start_at'], g['id']))
    else:
        # Do not let a separately configured non-Pinnacle calculation rank here.
        def ev_row(row):
            return row if result.get('assumptions', {}).get('benchmark_venue') == 'pinnacle' else dict(row, gross_return_percent=None)

        groups = comparison_groups([ev_row(row) for row in rows], by_id, metric, current=True)
    groups = [g for g in groups if passes(Fraction(g['score']) if g['score'] is not None else None)]
    if query.get('sort') == 'start':
        groups.sort(key=lambda g: g['start_at'])

    def present(group):
        summary = {k: group[k] for k in ('id', 'game_key', 'game_title', 'league', 'start_at', 'market', 'score')}
        if view == 'arbs':
            pairs = [dict(pair['before_fees'], id=pair['id'], legs=pair['legs']) for pair in group['quotes']]
            summary['pairs'] = pairs
            summary['offers'] = [offer(by_id[id_]) for id_ in dict.fromkeys(leg for pair in pairs for leg in pair['legs'])]
        else:
            summary['offers'] = [offer(row, metric) for row in group['quotes']]
        return summary

    visible = [present(g) for g in groups[offset:offset + limit]]
    keys = {g['game_key'] for g in visible}
    return dict(state='ready', rows=visible, total=len(groups), offset=offset, limit=limit,
                games=[g for g in result.get('games', []) if g['game_key'] in keys],
                publication=result['publication'], provider_requests=0)
