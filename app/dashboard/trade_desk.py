"""Compact, sorted views of the ordinary publication for the three-page desk."""
from datetime import date, datetime, time, timedelta
from fractions import Fraction
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.comparison.sgo_reference import BEST_BOOKS, BEST_VERSION, NAMED_VERSION, VERSION as SGO_MEDIAN
from app.comparison.ordinary_arb import current_payoff
from app.comparison.game_phase import PREGAME_SPORTSBOOK_SECONDS
from app.storage.comparison_snapshot import expand_row
from app.storage.current_rows import contract_id
from app.storage.store import hashed, stamp
from .local_security import PublicRequestError
from .snapshot_display import comparison_groups, decimal, odds, outcome_id, outcome_key, ranking_value, search_index
from .u0_display import quote_display


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


def unavailable_calculation(row, metric, *, sportsbook_updates_paused=False):
    reference = row.get('reference_calculation') or {}
    reasons = row.get('current_reasons', [])
    if not row.get('price_current'):
        return 'Price expired' if 'source_expired' in reasons else 'Price unavailable'
    if row.get('probability_missing') == 'finance_pending' or 'finance_pending' in reasons:
        return 'Calculation pending'
    if metric == SPORTSBOOK_METRIC:
        if sportsbook_updates_paused:
            return 'sgo_charge_unresolved'
        return 'sportsbook_baseline_unavailable'
    if not reference.get('available') and reference.get('method') == BEST_VERSION:
        if sportsbook_updates_paused:
            return 'sgo_charge_unresolved'
        if reference.get('reason'):
            return reference['reason']
    reasons_by_metric = {'conditional_return_percent':'after_trade_fee_ev',
                         'conservative_return_percent':'conservative_trade_fee_ev',
                         'gross_return_percent':'before_fee_ev'}
    unavailable = row.get('metric_status', {}).get(reasons_by_metric.get(metric), {}).get('reasons', [])
    return ', '.join(unavailable) or row.get('snapshot_benchmark_reason') or 'exact_reference_pair_unavailable'


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
    reason = unavailable_calculation(row, metric, sportsbook_updates_paused=sportsbook_updates_paused) if metric and value is None else None
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


def game_source_key(row):
    source = row.get('source') or {}
    if any(not source.get(key) for key in ('provider', 'native_event_id', 'native_market_id', 'native_outcome_id')):
        return None
    return contract_id(dict(quote=row))


def source_event_key(row):
    source = row.get('source') or {}
    if source.get('provider') and source.get('native_event_id'):
        return hashed([source['provider'], row['league'], source['native_event_id']])
    return None


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


def add_sgo_prices(db, out, rows, states, *, at, include_retained, mark_retained=False):
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
        if not (include_retained or mark_retained):
            return
    games = {game['game_key']: game for game in out['games']}
    roles = {key: {p['id']: p['role'] for p in game['participants']
                   if p.get('id') and p.get('role') in ('home', 'away')}
             for key, game in games.items()}
    signatures = {}
    group_games = {group['game_key'] for group in groups}
    for key, game in games.items():
        if key not in group_games:
            continue
        ids = {role: team for team, role in roles[key].items()}
        if ids.keys() == {'home', 'away'} and game.get('start_at'):
            signature = (game['league'], stamp(game['start_at']), ids['home'], ids['away'])
            signatures.setdefault(signature, []).append(key)
    candidates = {}
    if signatures:
        starts = [signature[1] for signature in signatures]
        events = db.execute("""SELECT native_event_id, competition, scheduled_start,
                                      facts->>'home' AS home, facts->>'away' AS away
                               FROM current_event
                               WHERE provider='sportsgameodds' AND competition=ANY(%s)
                                 AND scheduled_start::timestamptz BETWEEN %s AND %s""",
                            (sorted({signature[0] for signature in signatures}), min(starts), max(starts))).fetchall()
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
        scheduled = stamp(facts['starts_at'])
        live = at >= scheduled
        deadline = timedelta(seconds=LIVE_SECONDS if live else PREGAME_SPORTSBOOK_SECONDS)
        frame_current = (at - deadline <= frame_at <= at and phase['reason'] is None
                         and (phase['state'] == 'live') == live)
        if not frame_current and not (include_retained or mark_retained):
            continue
        try:
            observations = read_event(db, event, bookmakers=BEST_BOOKS,
                                      source_since=None if include_retained or mark_retained else at - deadline)
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
            if starts != scheduled:
                continue
            source_at = stamp(fact['source_at']) if fact.get('source_at') else None
            received_at = stamp(fact['received_at'])
            current = bool(frame_current and fact['available'] and source_at and source_at <= received_at <= frame_at
                           and at <= source_at + deadline and (source_at >= starts) == live
                           and fact['phase'] == ('live' if live else 'pregame')
                           and source_allowed(state, fact['league']))
            if mark_retained:
                if not current:
                    for group in (by_schedule | exact).values():
                        hidden = group.setdefault('retained_sportsbooks', [])
                        if fact['venue'] not in hidden:
                            hidden.append(fact['venue'])
            elif current or include_retained:
                for group_id, group in (by_schedule | exact).items():
                    book = group['sportsbook_quotes'].setdefault(fact['venue'], [])
                    prior = next((price for price in book if price.get('price_american') == fact['price_american']
                                  and price.get('source_at') == fact['source_at']), None)
                    if prior is not None:
                        prior['alternate'] = fact.get('alternate')
                    else:
                        book.append(dict(price_american=fact['price_american'], source_at=fact['source_at'],
                                         current=current, side=fact['side'], line=fact['line'],
                                         alternate=fact.get('alternate'),
                                         match='source_event' if group_id in exact else 'schedule_and_teams'))


def add_public_prices(out, owner, *, at, include_retained, mark_retained=False):
    from app.comparison.public_sportsbook_estimate import LIFETIME, allowed, index, read_captures, retained_prices
    from app.storage.store import ROOT

    if not out['rows'] or not (include_retained or mark_retained or allowed(owner)):
        return
    captures = read_captures(ROOT, at=at)
    current = index(captures, at=at) if allowed(owner) else {}
    retained = retained_prices(ROOT, captures, at=at,
                               leagues={group.get('league') for group in out['rows']}) if include_retained or mark_retained else {}
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
        for entries, fresh in ((retained, False),) if mark_retained else ((current, True), (retained, False)):
            for book, prices in entries.get(occurrence, {}).get('quotes', {}).get(key, {}).items():
                if mark_retained:
                    if prices and not group['sportsbook_quotes'].get(book):
                        hidden = group.setdefault('retained_sportsbooks', [])
                        if book not in hidden:
                            hidden.append(book)
                    continue
                display = group['sportsbook_quotes'].setdefault(book, [])
                for price in prices:
                    source = stamp(price['source_at'])
                    if fresh and not (source < occurrence[1] and source <= at <= source + LIFETIME):
                        continue
                    if not any(old['price_american'] == price['price_american']
                               and old.get('source_at') == price['source_at'] for old in display):
                        display.append(dict(price, current=fresh))


def quote_places(group, *, retained=False):
    """Count quotes for this exact outcome, once per exchange or sportsbook."""
    books = {
        book for book, prices in group['sportsbook_quotes'].items() if book in BEST_BOOKS
        and any((retained or price.get('current')) and price.get('price_american') not in (None, 0, '0') for price in prices)}
    offers = [quote for quote in group['offers'] if retained or quote['current']]
    if not retained and len(books | {quote['venue'] for quote in offers}) < 3:
        return set()
    return books | {quote['venue'] for quote in offers if quote_display(
        quote['original']['value'], quote['original']['units'],
        quote['original'].get('payout', '1'))['supported']}


def main_line_key(group, roles):
    market = group['market']
    family = market['market']
    selection = group['offers'][0]['selection'] or {}
    line = selection.get('signed_line')
    if family in ('spread', 'total') and line is not None:
        line = Fraction(line)
        if family == 'spread':
            participant = selection.get('participant')
            role = roles.get(participant)
            # Express both spread sides as the home team's handicap.
            line = ('home', -line if role == 'away' else line) if role else (participant, line)
    return (group['game_key'], market['period'], family), line


def comparable_groups(groups, games, *, alternates, requested, requested_source, retained=False):
    roles = {game['game_key']: {p['id']: p['role'] for p in game['participants']
                              if p.get('id') and p.get('role') in ('home', 'away')} for game in games}
    eligible, lines = [], {}
    for group in groups:
        current = quote_places(group)
        places = quote_places(group, retained=True) if retained else current
        if not places or not retained and len(current) < 3:
            continue
        market, line = main_line_key(group, roles.get(group['game_key'], {}))
        eligible.append((group, market, line))
        live_places, line_places, featured = lines.setdefault(market, {}).setdefault(line, (set(), set(), set()))
        live_places.update(current)
        line_places.update(places)
        featured.update(quote['venue'] for quote in group['offers']
                        if quote['current'] and quote['venue'] in places and quote['alternate'] is not True)
        featured.update(book for book, prices in group['sportsbook_quotes'].items() if book in places
                        and any(price.get('current') and price.get('alternate') is False for price in prices))
    # Widest coverage wins. Break ties with featured exchange prices, then a
    # stable line key. Never use EV to select the line we show.
    mains = {market: min(choices, key=lambda line: (
        -len(choices[line][0]), -len(choices[line][1]), -len(choices[line][2]), repr(line)))
        for market, choices in lines.items()}
    linked = {group['id'] for group, _, _ in eligible if requested_source
              and group.get('game_source') == requested_source}
    return [group['id'] for group, market, line in eligible
            if alternates or line == mains[market] or group['id'] == requested
            or len(linked) == 1 and group['id'] in linked]


def page(result, query, options, *, captured_pairs=(), policy=None, browsing=None, enrich=None):
    view, _, offset, limit = options
    zone, day, minimum, dollars, stake = filters(query)
    terms = query.get('search', '').casefold().split()
    search = search_index(result) if terms else {}
    browse = query.get('browse_odds') == '1'
    ranked = query.get('ranked') == '1'
    comparable = query.get('lines') in ('main', 'all') and view != 'arbs' and (browse or ranked)
    phase = desk_phase(query)
    read_at = stamp(result['publication'].get('read_at') or result['captured_at']) if phase else None
    basis = query.get('basis') or ('sportsbooks' if phase == 'pregame' else 'reviewed')
    runtime = result['publication'].get('data_runtime') or {}
    retained_fallback = (browse and view != 'arbs'
                         and (runtime.get('stopped') or runtime.get('healthy') is False))
    show_retained = retained_fallback or query.get('last_known') == '1' or (
        not (browse or ranked) and 'last_known' not in query)
    leagues, families, venues = (set(query.get(key, '').split(',')) - {''} for key in ('league', 'family', 'venue'))
    game_key = query.get('game_key')
    # A published occurrence can acquire a stronger identity on refresh.
    # A linked line follows its exact contract, while a matchup can also
    # follow an unambiguous provider event after one contract drops out.
    game_source = query.get('game_source')
    source_event = query.get('source_event')
    if browse and game_key and (game_source or source_event):
        replacement = set()
        event_matches = set()
        for row in result['rows']:
            if not direct_venue_offer(row):
                continue
            if game_source and game_source_key(row) == game_source:
                replacement.add(row['game_key'])
            if source_event and source_event_key(row) == source_event:
                event_matches.add(row['game_key'])
        if not replacement and game_key not in event_matches:
            replacement = event_matches
        if len(replacement) == 1:
            game_key, = replacement

    def matches(row):
        market = row['market']
        local = datetime.fromisoformat(row['start_at']).astimezone(zone) if (
            day or query.get('time_from') or query.get('time_to')) else None
        return (phase_matches(row, phase, read_at)
                and (not game_key or row['game_key'] == game_key)
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
    practice = (result.get('replay') or {}).get('synthetic')
    metric = 'net_return_percent' if practice and basis == 'conservative' else METRICS[basis]
    eligible_pair_count = None
    pair_status = {}
    calculation_reason = None
    calculation_missing = []
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
        elif any(row.get('price_current') for row in selected_rows):
            calculation_reason = 'No verified opposing pair has two current prices.'
    else:
        # Old benchmark settings govern their own data source. A proved SGO
        # calculation uses the desk's fixed four-book policy.
        def ev_row(row):
            if (practice or metric == SPORTSBOOK_METRIC
                    or (row.get('current_authority') or {}).get('reference_method') == BEST_VERSION
                    or result.get('assumptions', {}).get('benchmark_venue') == 'pinnacle'):
                return row
            return dict(row, **{metric:None})

        show_complete_outcomes = (comparable or ranked and bool(phase)) and query.get('group') != 'offer'
        candidates = comparison_groups([ev_row(row) for row in (rows if show_complete_outcomes else selected_rows)],
                                       by_id, metric, current=True, individual=query.get('group') == 'offer')
        groups = [group for group in candidates if not venues or any(
            row['venue'] in venues for row in group['quotes'])]
        if not show_complete_outcomes:
            rows = selected_rows
    matched_outcome_count = len(groups)
    ranked_group_count = sum(g['score'] is not None for g in groups)
    if ranked and view != 'arbs' and not ranked_group_count and selected_rows:
        current = [row for row in selected_rows if row.get('price_current')]
        aggregate = result['publication'].get('sources', {}).get('sportsgameodds', {})
        if current and all(row.get('probability_missing') == 'finance_pending' for row in current):
            calculation_reason = 'Current prices are waiting for calculation publication.'
        elif current and metric != SPORTSBOOK_METRIC and aggregate.get('state') == 'held' and not sportsbook_updates_paused:
            calculation_reason = 'The sportsbook reference source is on hold.'
        elif current:
            if metric == SPORTSBOOK_METRIC:
                calculation_reason = 'No eligible two-sided sportsbook reference is available for these offers. Individual sportsbook quotes may still be available in Browse odds.'
            else:
                reasons = [unavailable_calculation(expand_row(row), metric, sportsbook_updates_paused=sportsbook_updates_paused)
                           for row in current]
                calculation_missing = sorted({reason for group in reasons if group for reason in group.split(', ')})[:8]
                calculation_reason = 'Current prices are missing inputs for the selected calculation.'
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
            summary['game_line_id'] = outcome_id(outcome_key(by_id[pairs[0]['legs'][0]]))
            summary['pair_status'] = 'calculated' if group['score'] is not None else pairs[0]['retail_payoff']['reason']
        else:
            summary['offers'] = [offer(row, metric, sportsbook_updates_paused=sportsbook_updates_paused)
                                 for row in group['quotes']]
            if query.get('group') == 'offer':
                summary['game_line_id'] = outcome_id(outcome_key(group['quotes'][0]))
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
                    if prices:
                        price = dict(prices[0], current=True)
                        if price not in book_prices.setdefault(book, []):
                            book_prices[book].append(price)
            summary['sportsbook_quotes'] = book_prices
        target = (by_id[pairs[0]['legs'][0]] if view == 'arbs' else group['quotes'][0])
        if source_key := game_source_key(target):
            summary['game_source'] = source_key
        if event_key := source_event_key(target):
            summary['source_event'] = event_key
        return summary

    # Qualify the complete slate before ranking thresholds and pagination.
    # Keep the full evidence decode in present() limited to the returned page.
    price_lists = {}
    limited_coverage = False
    if comparable:
        retained_comparison = browse and show_retained
        candidates = []
        for group in groups:
            first = group['quotes'][0]
            if not retained_comparison and not any(row.get('price_current') for row in group['quotes']):
                continue
            offers = []
            books = {}
            for row in group['quotes']:
                source = row.get('source') or {}
                offers.append(dict(id=row['id'], venue=row['venue'], current=bool(row.get('price_current')),
                                   alternate=row.get('alternate', (source.get('native_market_id') or '').startswith('alternate:')),
                                   market=row['market'], selection=row.get('selection'), original=row['original']))
                baseline = (row.get('sportsbook_baseline') or {}) if row.get('price_current') else {}
                prices = dict(baseline.get('candidates') or {})
                if baseline.get('book') and baseline.get('prices'):
                    prices[baseline['book']] = baseline['prices']
                for book, pair in prices.items():
                    if pair:
                        entry = dict(pair[0], current=True)
                        if entry not in books.setdefault(book, []):
                            books[book].append(entry)
            candidates.append(dict(id=group['id'], game_key=group['game_key'], start_at=group['start_at'],
                                   league=group['league'], market=group['market'], offers=offers, sportsbook_quotes=books,
                                   game_source=game_source_key(first)))
        if enrich and not retained_fallback:
            enrich(dict(rows=candidates, games=list(games.values())), include_retained=show_retained)
        price_lists = {candidate['id']: candidate for candidate in candidates}
        qualified = set(comparable_groups(candidates, games.values(), alternates=query['lines'] == 'all',
                                         requested=query.get('line') if game_key else None,
                                         requested_source=game_source if game_key and query.get('line') else None,
                                         retained=retained_comparison))
        if browse and candidates and not retained_comparison:
            missing = candidates if not qualified else []
            if game_key and qualified:
                available = {(group['market']['market'], group['market']['period'])
                             for group in candidates if group['id'] in qualified}
                missing = [group for group in candidates if (group['market']['market'], group['market']['period'])
                           not in available or group['id'] == query.get('line')]
            # Comparison depth can drop from one update to the next. Keep
            # the surviving exact quotes available even with a single site.
            if missing:
                fallback = set(comparable_groups(missing, games.values(), alternates=query['lines'] == 'all',
                                                 requested=query.get('line'),
                                                 requested_source=game_source, retained=True)) - qualified
                qualified.update(fallback)
                limited_coverage = bool(fallback)
        groups = [group for group in groups if group['id'] in qualified]
    groups = [g for g in groups if (not ranked or g['score'] is not None)
              and passes(Fraction(g['score']) if g['score'] is not None else None, g.get('retail_payoff'))]

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
    for group in visible:
        if (candidate := price_lists.get(group['id'])) is not None:
            prices = group['sportsbook_quotes']
            for book, values in candidate['sportsbook_quotes'].items():
                shown = prices.setdefault(book, [])
                shown.extend(price for price in values if not any(
                    old.get('price_american') == price.get('price_american')
                    and old.get('source_at') == price.get('source_at') for old in shown))
            if candidate.get('sportsbook_source_reason'):
                group['sportsbook_source_reason'] = candidate['sportsbook_source_reason']
    if browse and not show_retained and visible:
        visible_games = {group['game_key'] for group in visible}
        retained_venues = {}
        for row in scoped_rows:
            if (row['game_key'] in visible_games and not row.get('price_current')
                    and (not venues or row['venue'] in venues)):
                retained_venues.setdefault(outcome_id(outcome_key(row)), set()).add(row['venue'])
        for group in visible:
            if not group.get('withdrawn') and group['id'] in retained_venues:
                group['retained_venues'] = sorted(retained_venues[group['id']])
    if browse and enrich and (retained_fallback or not show_retained):
        # Retained prices and hints are needed only for the returned page.
        enrich(dict(rows=[g for g in visible if not g.get('withdrawn')], games=list(games.values())),
               include_retained=retained_fallback, mark_retained=not retained_fallback)
    keys = {g['game_key'] for g in visible}
    if browse and game_key:
        keys.add(game_key)
    selected_line = None
    if browse and game_key and (requested_line := query.get('line')):
        selected_line = next((group['id'] for group in groups if group['id'] == requested_line), None)
        if not selected_line and game_source:
            matching_lines = {group['id'] for group in groups
                              if any(game_source_key(quote) == game_source for quote in group['quotes'])}
            if len(matching_lines) == 1:
                selected_line, = matching_lines
    return dict(**({k:v for k,v in session.items() if k not in ('rows','state','total')} if session else {}),
                state='ready', rows=visible, total=session['total'] if session else len(page_units), offset=offset, limit=limit,
                page_count=len(selected),
                games=[g for g in result.get('games', []) if g['game_key'] in keys],
                selected_game_key=game_key if browse else None, selected_line_id=selected_line,
                publication=result['publication'], basis=basis, phase=phase, coverage=coverage,
                retained_fallback=bool(retained_fallback), limited_coverage=limited_coverage,
                matched_offer_count=len(rows), retained_offer_count=sum(not r.get('price_current') for r in scoped_rows),
                ranked_group_count=ranked_group_count, matched_outcome_count=matched_outcome_count,
                eligible_pair_count=eligible_pair_count, pair_status=pair_status,
                calculation_reason=calculation_reason if not ranked_group_count else None,
                calculation_missing=calculation_missing if not ranked_group_count else [],
                row_kind=('games' if page_by_game else
                          'offers' if view != 'arbs' and query.get('group') == 'offer' else 'outcomes'),
                game_count=len({g['game_key'] for g in groups}),outcome_count=len(groups),
                offer_count=len({q['id'] for g in groups for q in g['quotes']}) if view!='arbs' else len(by_id),
                provider_requests=0)
