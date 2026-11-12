"""Compact, sorted views of the ordinary publication for the three-page desk."""
from datetime import date, datetime, time
from fractions import Fraction
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.storage.comparison_snapshot import expand_row
from .local_security import PublicRequestError
from .snapshot_display import comparison_groups, odds, ranking_value, search_index


EV_METRIC = 'conditional_return_percent'
SPORTSBOOK_METRIC = 'sportsbook_return_percent'
METRICS={'reviewed':EV_METRIC,'before':'gross_return_percent','conservative':'conservative_return_percent',
         'sportsbooks':SPORTSBOOK_METRIC}


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
        for key in ('time_from','time_to'):
            if query.get(key):time.fromisoformat(query[key])
        if query.get('time_from') and query.get('time_to') and query['time_from']>=query['time_to']:
            raise ValueError()
        if query.get('game_state','') not in ('','scheduled','live','suspended','final','unknown'):raise ValueError()
        if query.get('basis','reviewed') not in METRICS:raise ValueError()
        stake = number(query.get('stake', '100'))
        if not 0 < stake <= 1_000_000 or (stake * 100).denominator != 1:
            raise ValueError()
    except (ValueError, ZeroDivisionError, ZoneInfoNotFoundError):
        raise PublicRequestError('Check the date, time zone, stake and minimums') from None
    return zone, day, minimum, dollars, stake


def offer(original, metric=None):
    row = expand_row(original)
    price = row['original']
    ref = row.get('snapshot_benchmark') or row.get('reference') or {}
    reference = row.get('reference_calculation') or {}
    from app.comparison.sgo_reference import NAMED_VERSION, VERSION as SGO_MEDIAN
    sgo_reference = reference.get('available') and reference.get('method') in (NAMED_VERSION, SGO_MEDIAN)
    ref_venue = ref.get('bookmaker', 'pinnacle' if row.get('snapshot_benchmark') else None)
    sportsbook = row.get('sportsbook_baseline') if row.get('price_current') else None
    if sportsbook:
        from .snapshot_display import decimal
        sportsbook = dict(sportsbook, fair_odds=odds(decimal(sportsbook['fair_decimal_odds'])))
    value = ranking_value(row, metric, current=True) if metric and (
        metric == SPORTSBOOK_METRIC or ref_venue == 'pinnacle' or sgo_reference) else None
    reasons = row.get('current_reasons', [])
    reference_prices = ref.get('odds') or []
    selected = ref.get('selected')
    selected_price = ref.get('selected_odds')
    if selected_price is None and isinstance(selected, int) and 0 <= selected < len(reference_prices):
        selected_price = reference_prices[selected]
    reason = None
    if metric and value is None:
        if not row.get('price_current'):
            reason = 'Price expired' if 'source_expired' in reasons else 'Price unavailable'
        elif metric == SPORTSBOOK_METRIC:
            reason = 'sportsbook_baseline_unavailable'
        elif row.get('probability_missing') == 'finance_pending':
            reason = 'Calculation pending'
        else:
            reasons_by_metric={'conditional_return_percent':'after_trade_fee_ev','conservative_return_percent':'conservative_trade_fee_ev','gross_return_percent':'before_fee_ev'}
            unavailable=row.get('metric_status',{}).get(reasons_by_metric.get(metric),{}).get('reasons',[])
            reason = ', '.join(unavailable) or 'exact_reference_pair_unavailable'
    gross=ranking_value(row,'gross_return_percent',current=True)
    reviewed=ranking_value(row,'conditional_return_percent',current=True)
    conservative=ranking_value(row,'conservative_return_percent',current=True)
    fair = reference.get('fair_decimal_odds')
    if sgo_reference and fair:
        from .snapshot_display import decimal
        reference_price = odds(decimal(fair))
    else:
        reference_price = odds(selected_price) if selected_price is not None and ref_venue == 'pinnacle' else None
    return dict(before_fee=None if gross is None else str(gross),after_fee=None if reviewed is None else str(reviewed),
                conservative=None if conservative is None else str(conservative),metric=metric,
                sportsbook=sportsbook,
                trade_fee=row.get('trade_fee'),fee=row.get('conditional_trade_benchmark'),conservative_fee=row.get('conservative_trade_benchmark'),
                reference_calculation=row.get('reference_calculation'),economic_revision=row.get('economic_revision'),price_revision=row.get('price_revision'),evidence_result_id=row.get('evidence_result_id'),
                captured_at=row.get('captured_at'),game_state=row.get('game_state','unknown'),
                game_state_basis=row.get('game_state_basis'),current_reasons=reasons,
                source_clock_at=row.get('times',{}).get('source_at'),
                confirmed_at=(row.get('book_confirmation') or {}).get('confirmed_at'),
                projected_at=row.get('times',{}).get('projected_at'),
                id=row['id'], venue=row['venue'], source_provider=(row.get('source') or {}).get('provider'), selection=row.get('selection'),
                participant=row.get('participant_label'), market=row['market'],
                odds=odds(price['value'], price['units'], price.get('payout', '1')),
                current=bool(row.get('price_current')), value=None if value is None else str(value), reason=reason,
                reference=reference_price,
                reference_current=gross is not None if sgo_reference else row.get('exact_pinnacle_reference_current', gross is not None),
                probability=row.get('probability') if gross is not None else None,
                overround=reference.get('overround') if value is not None else None,
                source_at=(row.get('book_confirmation') or {}).get('confirmed_at') or row.get('times', {}).get('source_at'),
                received_at=row.get('times', {}).get('received_at'))


def page(result, query, options, *, captured_pairs=(), policy=None, browsing=None):
    view, _, offset, limit = options
    zone, day, minimum, dollars, stake = filters(query)
    search = search_index(result)
    terms = query.get('search', '').casefold().split()
    leagues, families, venues = (set(query.get(key, '').split(',')) - {''} for key in ('league', 'family', 'venue'))

    def matches(row):
        market = row['market']
        local=datetime.fromisoformat(row['start_at']).astimezone(zone)
        return ((not leagues or row['league'] in leagues) and (not families or market['market'] in families)
                and (not query.get('period') or market['period'] == query['period'])
                and (not day or local.date() == day)
                and (not query.get('time_from') or local.time()>=time.fromisoformat(query['time_from']))
                and (not query.get('time_to') or local.time()<time.fromisoformat(query['time_to']))
                and (not query.get('game_state') or row.get('game_state','unknown')==query['game_state'])
                and all(term in (row['game_title'].casefold() + ' ' + search.get(row['game_key'], '')) for term in terms))

    def passes(value):
        return ((not query.get('positive') or value is not None and value > 0)
                and (minimum is None or value is not None and value >= minimum)
                and (dollars is None or value is not None and value * stake / 100 >= dollars))

    # Provider event titles sometimes describe one market family (e.g. Total
    # Points). A matchup label comes from the captured participants, never from
    # another market's title; the exact canonical market remains on each row.
    games={g['game_key']:g for g in result.get('games',[])}
    def labeled(row):
        participants=games.get(row['game_key'],{}).get('participants',[])
        names={p.get('id',p.get('name')):p.get('name') for p in participants if p.get('name')}
        if len(names)!=2:return row
        return dict(row,source_game_title=row['game_title'],game_title=' vs. '.join(names.values()))
    rows = [labeled(row) for row in result['rows'] if (not venues or row['venue'] in venues) and matches(row)]
    by_id = {row['id']: row for row in rows}
    metric = METRICS[query.get('basis','reviewed')]
    eligible_pair_count = None
    if view == 'arbs':
        from app.comparison.inspection_math import pair_math
        eligible = {r['id']: r for r in rows if r.get('price_current')
                    and r.get('publication_policy') == policy}
        markets = {}
        for pair in captured_pairs:
            proof = pair.get('before_fees')
            if proof and all(leg in eligible for leg in pair['legs']):
                inspection = pair_math(proof, stake)
                markets.setdefault(proof['market_key'], []).append(dict(pair, inspection=inspection))
        groups = []
        for key, pairs in markets.items():
            pairs.sort(key=lambda pair: (-Fraction(pair['inspection']['rounded_return_percent']),
                                        -Fraction(pair['before_fees']['value']), pair['id']))
            first = pairs[0]
            groups.append(dict(first, id=key, quotes=pairs, score=first['inspection']['rounded_return_percent']))
        groups.sort(key=lambda g: (-Fraction(g['score']), g['start_at'], g['id']))
        eligible_pair_count = sum(len(g['quotes']) for g in groups)
    else:
        # Do not let a separately configured non-Pinnacle calculation rank here.
        def ev_row(row):
            return row if metric == SPORTSBOOK_METRIC or result.get('assumptions', {}).get('benchmark_venue') == 'pinnacle' else dict(row, **{metric:None})

        groups = comparison_groups([ev_row(row) for row in rows], by_id, metric, current=True,
                                   individual=query.get('group') == 'offer')
    groups = [g for g in groups if passes(Fraction(g['score']) if g['score'] is not None else None)]
    coverage = {}
    if view != 'arbs':
        visible_offers = [row for group in groups for row in group['quotes']]
        coverage = dict(offers=len(visible_offers), current=sum(bool(row.get('price_current')) for row in visible_offers),
                        before=sum(ranking_value(row, METRICS['before'], current=True) is not None for row in visible_offers),
                        reviewed=sum(ranking_value(row, METRICS['reviewed'], current=True) is not None for row in visible_offers),
                        conservative=sum(ranking_value(row, METRICS['conservative'], current=True) is not None for row in visible_offers),
                        sportsbooks=sum(ranking_value(row, SPORTSBOOK_METRIC, current=True) is not None for row in visible_offers))
    if query.get('sort') == 'start':
        groups.sort(key=lambda g: g['start_at'])

    def present(group):
        summary = {k: group[k] for k in ('id', 'game_key', 'game_title', 'league', 'start_at', 'market', 'score')}
        summary['source_titles']=sorted({q.get('source_game_title',q.get('game_title','')) for q in group['quotes']}) if view!='arbs' else []
        if view == 'arbs':
            from app.comparison.snapshot_pair_fees import pair_fees
            ids = dict.fromkeys(leg for pair in group['quotes'] for leg in pair['legs'])
            expanded = {id_: expand_row(by_id[id_]) for id_ in ids}
            pairs = [dict(pair['before_fees'], id=pair['id'], legs=pair['legs'],
                          inspection=pair['inspection'], assumed_scenario=pair.get('math'),
                          retail_payoff=pair_fees(pair['before_fees'], pair['inspection'],
                                                [expanded[id_] for id_ in pair['legs']])) for pair in group['quotes']]
            summary['pairs'] = pairs
            summary['offers'] = [offer(row) for row in expanded.values()]
        else:
            summary['offers'] = [offer(row, metric) for row in group['quotes']]
        return summary

    session=browsing.page(groups,query,offset,limit) if browsing else None
    if session and session['state']=='page_changed':return session
    visible = [g if g.get('withdrawn') else present(g) for g in (session['rows'] if session else groups[offset:offset + limit])]
    keys = {g['game_key'] for g in visible}
    return dict(**({k:v for k,v in session.items() if k not in ('rows','state','total')} if session else {}),
                state='ready', rows=visible, total=session['total'] if session else len(groups), offset=offset, limit=limit,
                games=[g for g in result.get('games', []) if g['game_key'] in keys],
                publication=result['publication'], basis=query.get('basis','reviewed'), coverage=coverage,
                eligible_pair_count=eligible_pair_count,
                row_kind='offers' if view != 'arbs' and query.get('group') == 'offer' else 'outcomes',
                game_count=len({g['game_key'] for g in groups}),outcome_count=len(groups),
                offer_count=len({q['id'] for g in groups for q in g['quotes']}) if view!='arbs' else len(by_id),
                provider_requests=0)
