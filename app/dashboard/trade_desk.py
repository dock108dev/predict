"""Compact, sorted views of the ordinary publication for the three-page desk."""
from datetime import date, datetime, time, timedelta
from fractions import Fraction
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.comparison.sgo_reference import BEST_BOOKS, BEST_VERSION, NAMED_VERSION, VERSION as SGO_MEDIAN
from app.comparison.ordinary_arb import current_payoff
from app.comparison.game_phase import PREGAME_SPORTSBOOK_SECONDS
from app.storage.comparison_snapshot import expand_row
from app.storage.store import hashed, stamp
from .local_security import PublicRequestError
from .snapshot_display import comparison_groups, decimal, odds, outcome_key, ranking_value, search_index


EV_METRIC = 'conditional_return_percent'
SPORTSBOOK_METRIC = 'sportsbook_return_percent'
METRICS={'reviewed':EV_METRIC,'before':'gross_return_percent','conservative':'conservative_return_percent',
         'sportsbooks':SPORTSBOOK_METRIC}


def desk_phase(query):
    phase = query.get('phase', 'pregame' if query.get('layout') == 'desk' and query.get('ranked') == '1' else '')
    if phase not in ('', 'pregame', 'live'):
        raise PublicRequestError('Unknown Opportunities tab')
    return phase


def phase_matches(row, phase, at):
    if not phase:
        return True
    if phase == 'live':
        return row.get('game_state') == 'live'
    market = row['market']
    return (row.get('game_state') == 'scheduled' and at < stamp(row['start_at'])
            and market['period'] == 'full_game' and market['market'] in ('winner', 'spread', 'total'))


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


def offer(original, metric=None, *, sportsbook_updates_paused=False):
    row = expand_row(original)
    price = row['original']
    ref = row.get('snapshot_benchmark') or row.get('reference') or {}
    reference = row.get('reference_calculation') or {}
    sgo_reference = reference.get('available') and reference.get('method') in (BEST_VERSION, NAMED_VERSION, SGO_MEDIAN)
    ref_venue = ref.get('bookmaker', 'pinnacle' if row.get('snapshot_benchmark') else None)
    sportsbook = row.get('sportsbook_baseline') if row.get('price_current') else None
    if sportsbook:
        sportsbook = dict(sportsbook, fair_odds=odds(decimal(sportsbook['fair_decimal_odds'])))
        for private in ('source', 'event_id', 'reference_inputs', 'frame_id', 'frame_received_at'):
            sportsbook.pop(private, None)
    value = ranking_value(row, metric, current=True) if metric and (
        metric == SPORTSBOOK_METRIC or ref_venue == 'pinnacle' or sgo_reference) else None
    reasons = row.get('current_reasons', [])
    reason = None
    if metric and value is None:
        if not row.get('price_current'):
            reason = 'Price expired' if 'source_expired' in reasons else 'Price unavailable'
        elif row.get('probability_missing') == 'finance_pending' or 'finance_pending' in reasons:
            reason = 'Calculation pending'
        elif metric == SPORTSBOOK_METRIC:
            reason = row.get('snapshot_benchmark_reason') or 'sportsbook_baseline_unavailable'
        else:
            reasons_by_metric={'conditional_return_percent':'after_trade_fee_ev','conservative_return_percent':'conservative_trade_fee_ev','gross_return_percent':'before_fee_ev'}
            unavailable=row.get('metric_status',{}).get(reasons_by_metric.get(metric),{}).get('reasons',[])
            reason = ', '.join(unavailable) or row.get('snapshot_benchmark_reason') or 'exact_reference_pair_unavailable'
    if (reason and row.get('price_current') and reason != 'Calculation pending'
            and not reference.get('available') and reference.get('method') == BEST_VERSION
            and reference.get('reason')):
        reason = reference['reason']
    if reason and metric != SPORTSBOOK_METRIC and sportsbook_updates_paused and row.get('price_current') and (
            not reference.get('available') and reference.get('method') == BEST_VERSION):
        reason = 'sgo_charge_unresolved'
    if metric == SPORTSBOOK_METRIC and value is None and row.get('price_current'):
        reason = 'sportsbook_baseline_unavailable'
    gross=ranking_value(row,'gross_return_percent',current=True)
    reviewed=ranking_value(row,'conditional_return_percent',current=True)
    conservative=ranking_value(row,'conservative_return_percent',current=True)
    fair = reference.get('fair_decimal_odds')
    if row.get('probability') is not None:
        probability = Fraction(row['probability'])
        fair = str(1 / probability) if 0 < probability < 1 else None
    reference_price = odds(decimal(fair)) if fair else None
    source_metadata = (row.get('original_record') or {}).get('comparison_source_metadata') or {}
    authority = row.get('current_authority') or {}
    price_deadline = (authority.get('price') or {}).get('current_until')
    reference_deadlines = [item['current_until'] for item in authority.get('references', ()) if item.get('current_until')] if metric else []
    if metric and sportsbook and sportsbook.get('current_until'):
        reference_deadlines.append(sportsbook['current_until'])
    fee_deadline = authority.get({'conditional_return_percent': 'fee_until',
                                  'conservative_return_percent': 'conservative_fee_until'}.get(metric))
    if metric is None and (row.get('trade_fee') or {}).get('available'):
        fee_deadline = ((row['trade_fee'].get('evidence') or {}).get('review_before'))
    deadlines = [clock for clock in (price_deadline, fee_deadline, *reference_deadlines) if clock]
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
                alternate=row.get('alternate', source_metadata.get('alternate')),
                original=price, cost_per_normal_claim=row.get('cost_per_normal_claim'),
                current_until=price_deadline,
                calculation_current_until=min(deadlines, key=stamp) if (value is not None or metric is None) and deadlines else None,
                odds=odds(price['value'], price['units'], price.get('payout', '1')),
                current=bool(row.get('price_current')), value=None if value is None else str(value), reason=reason,
                reference=reference_price,
                reference_current=gross is not None if sgo_reference else row.get('exact_pinnacle_reference_current', gross is not None),
                probability=row.get('probability') if gross is not None else None,
                overround=reference.get('overround') if value is not None else None,
                source_at=(row.get('book_confirmation') or {}).get('confirmed_at') or row.get('times', {}).get('source_at'),
                received_at=row.get('times', {}).get('received_at'))


def direct_venue_offer(row):
    provider = (row.get('source') or {}).get('provider')
    return row['venue'] not in ('kalshi', 'polymarket_us') or provider in (None, row['venue'])


def sportsbook_selection(offer, roles):
    """Map a browsable outcome to a sportsbook side without inferring settlement."""
    market, selection = offer['market'], offer.get('selection') or {}
    family = market['market']
    if market['period'] != 'full_game':
        return None
    predicate = selection.get('predicate')
    if family == 'winner' and predicate == 'win':
        side = roles.get(selection.get('participant'))
        return ('moneyline', side, None) if side else None
    if family == 'spread' and predicate == 'cover':
        side = roles.get(selection.get('participant'))
    elif family == 'total' and predicate in ('over', 'under'):
        side = predicate
    else:
        return None
    line = selection.get('signed_line')
    return (family, side, Fraction(line)) if side and line is not None else None


def add_sgo_prices(db, out, rows, states, *, at, include_retained):
    """Join stored same-line book quotes for display, including native-only groups."""
    from app.comparison.game_phase import LIVE_SECONDS, sgo_event_status, sporting_phase
    from app.storage.ordinary_projection import source_allowed
    from app.storage.sportsgameodds_reference import read_event, read_event_frame

    groups = [group for group in out['rows'] if group.get('offers')]
    if not groups:
        return
    state = states['sportsgameodds']
    if state.get('reason_code') == 'sgo_charge_unresolved':
        for group in groups:
            group['sportsbook_source_reason'] = 'sgo_charge_unresolved'
        if not include_retained:
            return
    games = {game['game_key']: game for game in out['games']}
    roles = {key: {p['id']: p['role'] for p in game['participants']
                   if p.get('id') and p.get('role') in ('home', 'away')}
             for key, game in games.items()}
    signatures = {}
    for key, game in games.items():
        ids = {role: team for team, role in roles[key].items()}
        if ids.keys() == {'home', 'away'} and game.get('start_at'):
            signature = (game['league'], stamp(game['start_at']), ids['home'], ids['away'])
            signatures.setdefault(signature, []).append(key)
    candidates = {}
    if signatures:
        events = db.execute("""SELECT native_event_id, competition, scheduled_start,
                                      facts->>'home' AS home, facts->>'away' AS away
                               FROM current_event
                               WHERE provider='sportsgameodds' AND competition=ANY(%s)""",
                            (sorted({signature[0] for signature in signatures}),)).fetchall()
        for event in events:
            signature = (event['competition'], stamp(event['scheduled_start']), event['home'], event['away'])
            for key in signatures.get(signature, ()):
                candidates.setdefault(key, set()).add(event['native_event_id'])

    visible_ids = {offer['id'] for group in groups for offer in group['offers']}
    local = {row['id']: row['source'] for row in rows if row['id'] in visible_ids
             and (row.get('source') or {}).get('provider') == 'sportsgameodds'}
    wanted = {}
    for group in groups:
        sources = [local[offer['id']] for offer in group['offers'] if offer['id'] in local]
        ids = {source['native_event_id'] for source in sources}
        if len(ids) == 1:
            for source in sources:
                line = source.get('native_line')
                key = (source['native_outcome_id'], None if line is None else Fraction(line))
                wanted.setdefault(source['native_event_id'], {}).setdefault(key, {})[group['id']] = group
        elif not ids:
            game_key = group['game_key']
            ids = candidates.get(game_key, ())
            key = sportsbook_selection(group['offers'][0], roles.get(game_key, {}))
            if len(ids) == 1 and key is not None:
                wanted.setdefault(next(iter(ids)), {}).setdefault(key, {})[group['id']] = group

    for event, targets in wanted.items():
        frame = read_event_frame(db, event)
        if not frame:
            continue
        facts = frame['facts']
        members = dict(facts['members'])
        context = facts.get('event_context') or {}
        phase = sporting_phase({'status': sgo_event_status(context.get('status') or {})})
        frame_at = stamp(facts['received_at'])
        try:
            observations = read_event(db, event, bookmakers=BEST_BOOKS)
        except ValueError:
            continue
        for row in observations:
            fact = row['facts']
            if (fact['period'] != 'game' or fact.get('price_american') is None
                    or fact['venue'] not in BEST_BOOKS or members.get(row['id']) != row['revision']):
                continue
            line = None if fact['line'] is None else Fraction(fact['line'])
            exact = targets.get((fact['odd_id'], line), {})
            by_schedule = targets.get((fact['market'], fact['side'], line), {})
            if not exact and not by_schedule:
                continue
            starts = stamp(fact['starts_at'])
            if starts != stamp(facts['starts_at']):
                continue
            source_at = stamp(fact['source_at']) if fact.get('source_at') else None
            received_at = stamp(fact['received_at'])
            live = at >= starts
            deadline = timedelta(seconds=LIVE_SECONDS if live else PREGAME_SPORTSBOOK_SECONDS)
            current = bool(fact['available'] and source_at and source_at <= received_at <= frame_at <= at
                           and at <= source_at + deadline and (source_at >= starts) == live
                           and fact['phase'] == ('live' if live else 'pregame')
                           and phase['reason'] is None and (phase['state'] == 'live') == live
                           and source_allowed(state, fact['league']))
            if current or include_retained:
                for group_id, group in (by_schedule | exact).items():
                    book = group['sportsbook_quotes'].setdefault(fact['venue'], [])
                    if not any(price.get('price_american') == fact['price_american']
                               and price.get('source_at') == fact['source_at'] for price in book):
                        book.append(dict(price_american=fact['price_american'], source_at=fact['source_at'],
                                         current=current, side=fact['side'], line=fact['line'],
                                         match='source_event' if group_id in exact else 'schedule_and_teams'))


def add_public_prices(out, owner, *, at, include_retained):
    from app.comparison.public_sportsbook_estimate import LIFETIME, allowed, index, read_captures, retained_prices
    from app.storage.store import ROOT

    if not out['rows'] or not (include_retained or allowed(owner)):
        return
    captures = read_captures(ROOT, at=at)
    current = index(captures, at=at) if allowed(owner) else {}
    retained = retained_prices(ROOT, captures, at=at,
                               leagues={group.get('league') for group in out['rows']}) if include_retained else {}
    games = {game['game_key']: game for game in out['games']}
    for group in out['rows']:
        game = games.get(group['game_key'])
        if not game or not group.get('offers'):
            continue
        roles = {p['id']: p['role'] for p in game['participants'] if p.get('id') and p.get('role') in ('home', 'away')}
        teams = {role: team for team, role in roles.items()}
        key = sportsbook_selection(group['offers'][0], roles)
        if not key or teams.keys() != {'home', 'away'}:
            continue
        occurrence = (game['league'], stamp(group['start_at']), teams['home'], teams['away'])
        for entries, fresh in ((current, True), (retained, False)):
            for book, prices in entries.get(occurrence, {}).get('quotes', {}).get(key, {}).items():
                display = group['sportsbook_quotes'].setdefault(book, [])
                for price in prices:
                    source = stamp(price['source_at'])
                    if fresh and not (source < occurrence[1] and source <= at <= source + LIFETIME):
                        continue
                    if not any(old['price_american'] == price['price_american']
                               and old.get('source_at') == price['source_at'] for old in display):
                        display.append(dict(price, current=fresh))


def page(result, query, options, *, captured_pairs=(), policy=None, browsing=None):
    view, _, offset, limit = options
    zone, day, minimum, dollars, stake = filters(query)
    terms = query.get('search', '').casefold().split()
    search = search_index(result) if terms else {}
    browse = query.get('browse_odds') == '1'
    ranked = query.get('ranked') == '1'
    phase = desk_phase(query)
    read_at = stamp(result['publication'].get('read_at') or result['captured_at']) if phase else None
    basis = query.get('basis') or ('sportsbooks' if phase == 'pregame' else 'reviewed')
    show_retained = query.get('last_known') == '1' or (
        not (browse or ranked) and 'last_known' not in query)
    leagues, families, venues = (set(query.get(key, '').split(',')) - {''} for key in ('league', 'family', 'venue'))

    def matches(row):
        market = row['market']
        local = datetime.fromisoformat(row['start_at']).astimezone(zone) if (
            day or query.get('time_from') or query.get('time_to')) else None
        return (phase_matches(row, phase, read_at)
                and (not query.get('game_key') or row['game_key'] == query['game_key'])
                and (not leagues or row['league'] in leagues) and (not families or market['market'] in families)
                and (phase == 'pregame' or not query.get('period') or market['period'] == query['period'])
                and (not day or local.date() == day)
                and (not query.get('time_from') or local.time()>=time.fromisoformat(query['time_from']))
                and (not query.get('time_to') or local.time()<time.fromisoformat(query['time_to']))
                and (phase or not query.get('game_state') or row.get('game_state','unknown')==query['game_state'])
                and all(term in (row['game_title'].casefold() + ' ' + search.get(row['game_key'], '')) for term in terms))

    def passes(value, payoff=None):
        profit = (Fraction(payoff['minimum_net_profit_usd']) if payoff and payoff['available']
                  else value * stake / 100 if value is not None else None)
        return (browse or (not query.get('positive') or value is not None and value > 0)
                and (minimum is None or value is not None and value >= minimum)
                and (dollars is None or profit is not None and profit >= dollars))

    # Provider event titles sometimes describe one market family (e.g. Total
    # Points). A matchup label comes from the captured participants, never from
    # another market's title; the exact canonical market remains on each row.
    games={g['game_key']:g for g in result.get('games',[])}
    def labeled(row):
        participants=games.get(row['game_key'],{}).get('participants',[])
        names={p.get('id',p.get('name')):p.get('name') for p in participants if p.get('name')}
        if len(names)!=2:return row
        return dict(row,source_game_title=row['game_title'],game_title=' vs. '.join(names.values()))
    scoped_rows = [row for row in result['rows'] if matches(row)
                   and (query.get('layout') != 'desk' or direct_venue_offer(row))]
    rows = [labeled(row) for row in scoped_rows if show_retained or row.get('price_current')]
    selected_rows = [row for row in rows if not venues or row['venue'] in venues]
    by_id = {row['id']: row for row in rows}
    metric = METRICS[basis]
    eligible_pair_count = None
    pair_status = {}
    calculation_reason = None
    sportsbook_updates_paused = (result['publication'].get('sources', {}).get('sportsgameodds', {})
                                .get('reason_code') == 'sgo_charge_unresolved')
    if view == 'arbs':
        eligible = {r['id']: r for r in selected_rows if r.get('price_current')
                    and r.get('publication_policy') == policy}
        markets = {}
        expanded = {}
        scoped_ids = {r['id'] for r in scoped_rows}
        expired_pairs = 0
        for pair in captured_pairs:
            proof = pair.get('before_fees')
            if proof and all(leg in scoped_ids for leg in pair['legs']) and not all(
                    leg in eligible for leg in pair['legs']):
                expired_pairs += 1
            if proof and all(leg in eligible for leg in pair['legs']) and len(
                    {eligible[leg].get('game_state') for leg in pair['legs']}) == 1:
                for leg in pair['legs']:
                    if leg not in expanded:
                        expanded[leg] = expand_row(eligible[leg])
                payoff = current_payoff(pair, [expanded[leg] for leg in pair['legs']], stake)
                score = Fraction(payoff['score']) if payoff['score'] is not None else None
                markets.setdefault(proof['market_key'], []).append(
                    dict(pair, inspection=payoff['inspection'], retail_payoff=payoff['retail_payoff'], score=score))
        # The display can show additional exact-side offers. Only the pair's
        # evidenced legs participate in the payoff.
        sides = {}
        for row in rows:
            sides.setdefault(outcome_key(row)[:6], []).append(row['id'])
        groups = []
        for key, pairs in markets.items():
            pairs.sort(key=lambda pair: (pair['score'] is None,
                                         -pair['score'] if pair['score'] is not None else 0, pair['id']))
            first = pairs[0]
            offer_ids = dict.fromkeys(leg for pair in pairs for leg in pair['legs'])
            for leg in tuple(offer_ids):
                offer_ids.update(dict.fromkeys(sides[outcome_key(by_id[leg])[:6]]))
            groups.append(dict(first, id=key, quotes=pairs, offer_ids=list(offer_ids),
                               score=None if first['score'] is None else str(first['score'])))
        groups.sort(key=lambda g: (g['score'] is None, -Fraction(g['score']) if g['score'] is not None else 0,
                                   g['start_at'], g['id']))
        eligible_pair_count = sum(len(g['quotes']) for g in groups)
        pending_pairs = sum('finance_pending' in (pair.get('math') or {}).get('missing', ())
                            and pair['score'] is None for pairs in markets.values() for pair in pairs)
        pair_status = dict(finance_pending=pending_pairs, stale_or_replaced_legs=expired_pairs)
        if pending_pairs:
            calculation_reason = 'An opposing pair is waiting for calculation publication.'
        elif eligible_pair_count:
            calculation_reason = 'Current opposing pairs need applicable fees at the modeled size.'
        elif expired_pairs:
            calculation_reason = 'A previously matched pair lost a current leg.'
        elif any(row.get('price_current') for row in rows):
            calculation_reason = 'No verified opposing pair has two current prices.'
    else:
        # Old benchmark settings govern their own data source. A proved SGO
        # calculation uses the desk's fixed four-book policy.
        def ev_row(row):
            if (metric == SPORTSBOOK_METRIC
                    or (row.get('current_authority') or {}).get('reference_method') == BEST_VERSION
                    or result.get('assumptions', {}).get('benchmark_venue') == 'pinnacle'):
                return row
            return dict(row, **{metric:None})

        show_complete_outcomes = ranked and bool(phase) and query.get('group') != 'offer'
        candidates = comparison_groups([ev_row(row) for row in (rows if show_complete_outcomes else selected_rows)],
                                       by_id, metric, current=True, individual=query.get('group') == 'offer')
        groups = [group for group in candidates if not venues or any(
            row['venue'] in venues for row in group['quotes'])]
        if not show_complete_outcomes:
            rows = selected_rows
    matched_outcome_count = len(groups)
    ranked_group_count = sum(g['score'] is not None for g in groups)
    if view != 'arbs' and not ranked_group_count and rows:
        current = [row for row in rows if row.get('price_current')]
        aggregate = result['publication'].get('sources', {}).get('sportsgameodds', {})
        if sportsbook_updates_paused and metric != SPORTSBOOK_METRIC:
            calculation_reason = 'Sportsbook price updates are paused. Current exchange prices are available in Find my game.'
        elif current and all(row.get('probability_missing') == 'finance_pending' for row in current):
            calculation_reason = 'Current prices are waiting for calculation publication.'
        elif current and aggregate.get('state') == 'held':
            calculation_reason = 'The sportsbook reference source is on hold.'
        elif current:
            calculation_reason = 'Current prices are missing an eligible sportsbook pair or fee for this basis.'
    groups = [g for g in groups if (not ranked or g['score'] is not None)
              and passes(Fraction(g['score']) if g['score'] is not None else None, g.get('retail_payoff'))]
    coverage = {}
    if view != 'arbs':
        visible_offers = rows
        coverage = dict(offers=len(visible_offers), current=sum(bool(row.get('price_current')) for row in visible_offers),
                        before=sum(ranking_value(row, METRICS['before'], current=True) is not None for row in visible_offers),
                        reviewed=sum(ranking_value(row, METRICS['reviewed'], current=True) is not None for row in visible_offers),
                        conservative=sum(ranking_value(row, METRICS['conservative'], current=True) is not None for row in visible_offers),
                        sportsbooks=sum(ranking_value(row, SPORTSBOOK_METRIC, current=True) is not None for row in visible_offers))
    if query.get('sort') == 'start' and not ranked:
        groups.sort(key=lambda g: g['start_at'])

    def present(group):
        summary = {k: group[k] for k in ('id', 'game_key', 'game_title', 'league', 'start_at', 'market', 'score')}
        summary['source_titles']=sorted({q.get('source_game_title',q.get('game_title','')) for q in group['quotes']}) if view!='arbs' else []
        if view == 'arbs':
            pairs = [dict(pair['before_fees'], id=pair['id'], legs=pair['legs'],
                          inspection=pair['inspection'], assumed_scenario=pair.get('math'),
                          score=None if pair['score'] is None else str(pair['score']),
                          retail_payoff=pair['retail_payoff']) for pair in group['quotes']]
            summary['pairs'] = pairs
            summary['offers'] = [offer(by_id[id_]) for id_ in group['offer_ids']]
            summary['pair_status'] = 'calculated' if group['score'] is not None else pairs[0]['retail_payoff']['reason']
        else:
            summary['offers'] = [offer(row, metric, sportsbook_updates_paused=sportsbook_updates_paused)
                                 for row in group['quotes']]
            summary['score_source'] = group['score_source']
            if len({row['venue'] for row in group['quotes']}) > 1:
                identities = [(expand_row(row).get('same_outcome') or {}).get('key') for row in group['quotes']]
                if all(identities):
                    summary['settlement_match'] = 'matched' if all(key == identities[0] for key in identities) else 'different'
                else:
                    summary['settlement_match'] = 'unverified'
            book_prices = {}
            for quote in summary['offers']:
                baseline = quote.get('sportsbook') or {}
                reference = quote.get('reference_calculation') or {}
                candidates = dict(baseline.get('candidates') or {})
                if baseline.get('book') and baseline.get('prices'):
                    candidates[baseline['book']] = baseline['prices']
                if quote.get('reference_current'):
                    candidates.update((book['venue'], book['inputs']) for book in reference.get('contributors', ())
                                      if book.get('inputs'))
                for book, prices in candidates.items():
                    if prices and prices[0] not in book_prices.setdefault(book, []):
                        book_prices[book].append(prices[0])
            summary['sportsbook_quotes'] = book_prices
        return summary

    page_by_game = browse and not query.get('game_key') and view != 'arbs'
    page_units = groups
    if page_by_game:
        by_game = {}
        for group in groups:
            game = by_game.setdefault(group['game_key'], dict(id=group['game_key'],
                game_key=group['game_key'], game_title=group['game_title'], start_at=group['start_at'], outcomes=[]))
            game['outcomes'].append(group)
        page_units = sorted(by_game.values(), key=lambda game: (game['start_at'], game['id']))
    session=browsing.page(page_units,query,offset,limit) if browsing else None
    if session and session['state']=='page_changed':return session
    selected = session['rows'] if session else page_units[offset:offset + limit]
    visible_groups = [group for game in selected for group in game.get('outcomes', [game])] if page_by_game else selected
    visible = [g if g.get('withdrawn') else present(g) for g in visible_groups]
    keys = {g['game_key'] for g in visible}
    if browse and query.get('game_key'):
        keys.add(query['game_key'])
    return dict(**({k:v for k,v in session.items() if k not in ('rows','state','total')} if session else {}),
                state='ready', rows=visible, total=session['total'] if session else len(page_units), offset=offset, limit=limit,
                page_count=len(selected),
                games=[g for g in result.get('games', []) if g['game_key'] in keys],
                publication=result['publication'], basis=basis, phase=phase, coverage=coverage,
                matched_offer_count=len(rows), retained_offer_count=sum(not r.get('price_current') for r in scoped_rows),
                ranked_group_count=ranked_group_count, matched_outcome_count=matched_outcome_count,
                eligible_pair_count=eligible_pair_count, pair_status=pair_status,
                calculation_reason=calculation_reason if not ranked_group_count else None,
                row_kind=('games' if page_by_game else
                          'offers' if view != 'arbs' and query.get('group') == 'offer' else 'outcomes'),
                game_count=len({g['game_key'] for g in groups}),outcome_count=len(groups),
                offer_count=len({q['id'] for g in groups for q in g['quotes']}) if view!='arbs' else len(by_id),
                provider_requests=0)
