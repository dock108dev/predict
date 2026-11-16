"""Compact, sorted views of the ordinary publication for the three-page desk."""
from datetime import date, datetime, time, timedelta
from fractions import Fraction
from functools import lru_cache
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.comparison.sgo_reference import BEST_BOOKS, BEST_VERSION, NAMED_VERSION, VERSION as SGO_MEDIAN
from app.comparison.ordinary_arb import DEFAULT_FUNDING, current_payoff, published_payoff
from app.comparison.game_phase import PREGAME_SPORTSBOOK_SECONDS
from app.comparison.sporting_scope import supported
from app.storage.comparison_snapshot import expand_row
from app.storage.current_rows import contract_id
from app.storage.store import hashed, stamp
from .desk_sportsbooks import add_public_prices as add_public_prices
from .desk_sportsbooks import add_sgo_prices as add_sgo_prices
from .desk_sportsbooks import sportsbook_selection as sportsbook_selection
from .local_security import PublicRequestError
from .product_finance import EV_UNQUALIFIED, effective_quote, qualified_ev, reference_allowed, visible_publication, visible_row
from .snapshot_display import (
    comparison_groups, decimal, desk_game_aliases, matchup_search, odds, outcome_id, outcome_key, ranking_value,
    search_index, search_parts,
)
from .u0_display import quote_display


EV_METRIC = 'conditional_return_percent'
SPORTSBOOK_METRIC = 'sportsbook_return_percent'
NATIVE_VENUES = {'kalshi', 'polymarket_us'}
METRICS={'reviewed':EV_METRIC,'before':'gross_return_percent','conservative':'conservative_return_percent',
         'sportsbooks':SPORTSBOOK_METRIC}


def desk_phase(query, *, current=False):
    phase = query.get('phase', 'pregame' if query.get('layout') == 'desk' and query.get('ranked') == '1' else '')
    if phase not in ('', 'pregame', 'live'):
        raise PublicRequestError('Unknown Opportunities tab')
    return phase or ('pregame' if current else '')


def browse_retained(runtime):
    return (runtime.get('stopped') or runtime.get('healthy') is False
            or runtime.get('reason') == 'data_runtime_not_dispatching')


def phase_matches(row, phase, at):
    if not phase:
        return True
    market = row['market']
    family = 'moneyline' if market['market'] == 'winner' else market['market']
    if not supported(row['league'], family, market['period']):
        return False
    start = stamp(row['start_at'])
    if phase == 'live':
        return (start <= at and row.get('game_state') == 'live' and row.get('price_current')
                and not row.get('game_state_reason'))
    return (start > at and row.get('game_state') == 'scheduled' and not row.get('game_state_reason')
            and market['period'] == 'full_game')


def number(value):
    if len(value) > 40 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', value):
        raise ValueError('Expected a decimal')
    return Fraction(value)


def funding(value):
    stake = number(value)
    if not 0 < stake <= 1_000_000 or (stake * 100).denominator != 1:
        raise ValueError('Invalid stake')
    return stake


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
        stake = funding(query.get('stake', '100'))
    except (ValueError, ZeroDivisionError, ZoneInfoNotFoundError):
        raise PublicRequestError('Check the date, time zone, stake and minimums') from None
    return zone, day, minimum, dollars, stake


def unavailable_calculation(row, metric, *, sportsbook_updates_paused=False):
    reference = row.get('reference_calculation') or {}
    reasons = row.get('current_reasons', [])
    if row.get('posted_price') and not row.get('price_current'):
        return 'sportsbook_baseline_unavailable'
    if not row.get('price_current'):
        return 'Price expired' if 'source_expired' in reasons else 'Price unavailable'
    if row.get('probability_missing') == 'finance_pending' or 'finance_pending' in reasons:
        return 'Calculation pending'
    if metric == SPORTSBOOK_METRIC:
        if sportsbook_updates_paused:
            return 'sgo_charge_unresolved'
        return 'sportsbook_baseline_unavailable'
    if metric == EV_METRIC:
        fee = row.get('trade_fee') or {}
        if not fee.get('available') and fee.get('reason'):
            return fee['reason']
        if reference_allowed(row) and not qualified_ev(row):
            return EV_UNQUALIFIED
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


def desk_ranking_value(row, metric):
    if not row.get('price_current'):
        return None
    value = ranking_value(row, metric, current=True, qualified=metric == EV_METRIC)
    if value is None:
        return None
    if metric == SPORTSBOOK_METRIC:
        return value if row['sportsbook_baseline'].get('book') in BEST_BOOKS else None
    return value if metric == EV_METRIC or reference_allowed(expand_row(row)) else None


def offer(original, metric=None, *, sportsbook_updates_paused=False):
    row = visible_row(expand_row(original))
    price = row['original']
    cost = row.get('cost_per_normal_claim')
    if cost is None:
        from app.comparison.cashflows import exact_wire
        from .current_contract import price as normalized_cost

        try:
            cost = exact_wire(normalized_cost(row)) if Fraction(price.get('payout', '1')) == 1 else None
        except (KeyError, ValueError, TypeError, ArithmeticError):
            pass
    ref = row.get('snapshot_benchmark') or row.get('reference') or {}
    reference = row.get('reference_calculation') or {}
    sgo_reference = reference.get('available') and reference.get('method') in (BEST_VERSION, NAMED_VERSION, SGO_MEDIAN)
    ref_venue = ref.get('bookmaker') or reference.get('venue')
    sportsbook = row.get('sportsbook_baseline') if row.get('price_current') or row.get('posted_price') else None
    if sportsbook and sportsbook.get('book') not in BEST_BOOKS:
        sportsbook = None
    if sportsbook:
        sportsbook = dict(sportsbook, fair_odds=odds(decimal(sportsbook['fair_decimal_odds'])))
        for private in ('source', 'event_id', 'reference_inputs', 'frame_id', 'frame_received_at'):
            sportsbook.pop(private, None)
    value = desk_ranking_value(row, metric) if metric else None
    reasons = row.get('current_reasons', [])
    reason = unavailable_calculation(row, metric, sportsbook_updates_paused=sportsbook_updates_paused) if metric and value is None else None
    gross = desk_ranking_value(row, 'gross_return_percent')
    reviewed = desk_ranking_value(row, EV_METRIC)
    conservative = desk_ranking_value(row, 'conservative_return_percent')
    fair = reference.get('fair_decimal_odds') if reference_allowed(row) else None
    if reference_allowed(row) and row.get('probability') is not None:
        probability = Fraction(row['probability'])
        fair = str(1 / probability) if 0 < probability < 1 else None
    reference_price = odds(decimal(fair)) if fair else None
    source_metadata = (row.get('original_record') or {}).get('comparison_source_metadata') or {}
    authority = row.get('current_authority') or {}
    price_authority = authority.get('price') or {}
    price_deadline = price_authority.get('current_until')
    reference_deadlines = [item['current_until'] for item in authority.get('references', ()) if item.get('current_until')] if metric else []
    if metric and sportsbook and sportsbook.get('current_until'):
        reference_deadlines.append(sportsbook['current_until'])
    fee_deadline = authority.get({'conditional_return_percent': 'fee_until',
                                  'conservative_return_percent': 'conservative_fee_until'}.get(metric))
    if metric is None and (row.get('trade_fee') or {}).get('available'):
        fee_deadline = ((row['trade_fee'].get('evidence') or {}).get('review_before'))
    deadlines = [clock for clock in (price_deadline, fee_deadline, *reference_deadlines) if clock]
    selected_book = (reference.get('venue') or ref_venue) if sgo_reference else ref_venue
    fair_reference = None
    if reference_price or sportsbook:
        if sportsbook and (metric == SPORTSBOOK_METRIC or not reference_price):
            fair_reference = dict(books=[sportsbook['book']], method='single', indicative=True)
        elif reference.get('method') == 'authored_probability':
            fair_reference = dict(books=[], method='authored_probability')
        elif sgo_reference and reference['method'] == SGO_MEDIAN:
            fair_reference = dict(books=[item['venue'] for item in reference.get('contributors', ())],
                                  method='median')
        elif selected_book:
            fair_reference = dict(books=[selected_book], method='single')
    effective = effective_quote(row)
    return dict(before_fee=None if gross is None else str(gross),after_fee=None if reviewed is None else str(reviewed),
                conservative=None if conservative is None else str(conservative),metric=metric,
                sportsbook=sportsbook,fair_reference=fair_reference,
                **({'live_native_desk': True} if row.get('live_native_desk') else {}),
                **({'live_aggregate_desk': True} if row.get('live_aggregate_desk') else {}),
                trade_fee=row.get('trade_fee'),effective_quote=effective,
                effective_reason=None if effective else (row.get('trade_fee') or {}).get('reason') or 'effective_fill_unverified',
                fee=row.get('conditional_trade_benchmark'),conservative_fee=row.get('conservative_trade_benchmark'),
                reference_calculation=row.get('reference_calculation'),economic_revision=row.get('economic_revision'),price_revision=row.get('price_revision'),evidence_result_id=row.get('evidence_result_id'),
                captured_at=row.get('captured_at'),game_state=row.get('game_state','unknown'),
                game_state_basis=row.get('game_state_basis'), game_state_reason=row.get('game_state_reason'),
                game_state_observed_at=row.get('game_state_observed_at'), current_reasons=reasons,
                source_clock_at=row.get('times',{}).get('source_at'),
                confirmed_at=(row.get('book_confirmation') or {}).get('confirmed_at'),
                projected_at=row.get('times',{}).get('projected_at'),
                id=row['id'], venue=row['venue'], source_provider=(row.get('source') or {}).get('provider'), selection=row.get('selection'),
                native_side=(row.get('source') or {}).get('native_side'),
                price_basis=('native_book' if (row.get('source') or {}).get('provider') in NATIVE_VENUES
                             else 'synthetic' if (row.get('source') or {}).get('provider') == 'practice' else 'aggregate_snapshot'),
                participant=row.get('participant_label'), market=row['market'],
                alternate=row.get('alternate', source_metadata.get('alternate')),
                original=price, cost_per_normal_claim=cost, book_size=row.get('book_size'),
                current_until=price_deadline, desk_quote_key=price_authority.get('dependency'),
                calculation_current_until=min(deadlines, key=stamp) if (value is not None or metric is None) and deadlines else None,
                odds=odds(price['value'], price['units'], price.get('payout', '1')),
                current=bool(row.get('price_current')), posted_price=bool(row.get('posted_price')), value=None if value is None else str(value), reason=reason,
                reference=reference_price,
                reference_current=bool(reference_price and row.get('price_current')),
                probability=row.get('probability') if gross is not None else None,
                overround=reference.get('overround') if value is not None else None,
                source_at=(row.get('book_confirmation') or {}).get('confirmed_at') or row.get('times', {}).get('source_at'),
                received_at=row.get('times', {}).get('received_at'))


def public_offer(quote, basis):
    fields = ('posted_price', 'id', 'venue', 'selection', 'participant', 'market', 'alternate', 'odds',
              'current', 'value', 'reason', 'before_fee', 'after_fee', 'conservative',
              'reference_current', 'fair_reference', 'current_until', 'calculation_current_until', 'desk_quote_key',
              'price_revision', 'economic_revision', 'evidence_result_id', 'captured_at',
              'game_state', 'game_state_basis', 'game_state_reason', 'game_state_observed_at', 'current_reasons',
              'source_clock_at', 'confirmed_at', 'received_at', 'native_side', 'live_aggregate_desk',
              'price_basis', 'source_provider', 'original', 'cost_per_normal_claim', 'effective_quote', 'effective_reason', 'book_size')
    result = {field: quote[field] for field in fields if field in quote}
    sportsbook = quote.get('sportsbook')
    if quote.get('live_native_desk'):
        result.update(live_native_desk=True, sportsbook=sportsbook,
                      cost_per_normal_claim=quote['cost_per_normal_claim'])
    result['fair_odds'] = (quote['reference'] if basis != 'sportsbooks' and quote['reference_current'] else None
                          ) or (sportsbook and sportsbook.get('fair_odds'))
    reference = quote.get('fair_reference')
    if result['fair_odds'] and reference and reference.get('books'):
        if reference.get('indicative') and sportsbook:
            inputs = {sportsbook['book']: sportsbook.get('prices') or []}
        else:
            calculation = quote.get('reference_calculation') or {}
            inputs = {book['venue']: book.get('inputs') or [] for book in calculation.get('contributors', ())}
        selected_prices = {
            book: inputs[book][0]['price_american'] for book in reference['books']
            if book in BEST_BOOKS and inputs.get(book) and inputs[book][0].get('price_american')
        }
        if selected_prices:
            result['fair_reference'] = dict(reference, selected_prices=selected_prices)
    result['trade_fee_available'] = bool((quote.get('trade_fee') or {}).get('available'))
    return result


def public_group(group, basis):
    if group.get('withdrawn'):
        return group
    result = dict(group, offers=[public_offer(quote, basis) for quote in group['offers']])
    if 'pairs' in group:
        result['pairs'] = [dict(id=pair['id'], legs=pair['legs'], score=pair['score'],
            evidence_result_id=pair['evidence_result_id'],
            retail_payoff={key: pair['retail_payoff'][key] for key in (
                'available', 'reason', 'funding_usd', 'minimum_net_payout_usd', 'minimum_net_profit_usd',
                'states_covered', 'states_unverified', 'execution_reason', 'full_arbitrage_qualified', 'sizing', 'fee_basis')
                           if key in pair['retail_payoff']},
            **({'scoring_scopes':pair['scoring_scopes']} if pair.get('scoring_scopes') else {}))
            for pair in group['pairs']]
    if 'sportsbook_quotes' in group:
        result['sportsbook_quotes'] = {}
        for book, prices in group['sportsbook_quotes'].items():
            price = max((price for price in prices if price.get('price_american')),
                        key=lambda price: (price.get('current') is True, price.get('source_at') or ''), default=None)
            if price:
                result['sportsbook_quotes'][book] = [dict(current=price.get('current') is True, price_american=price['price_american'],
                                                          source_at=price.get('source_at'))]
    return result


def direct_venue_offer(row):
    provider = (row.get('source') or {}).get('provider')
    return row['venue'] not in NATIVE_VENUES or provider in (None, row['venue'])


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


@lru_cache(maxsize=2048)
def quote_supported(value, units, payout):
    """Reuse the formatter's support predicate for identical price inputs."""
    return quote_display(value, units, payout)['supported']


def quote_places(group, *, retained=False, minimum_places=3):
    """Count quotes for this exact outcome, once per exchange or sportsbook."""
    books = {
        book for book, prices in group['sportsbook_quotes'].items() if book in BEST_BOOKS
        and any((retained or price.get('current')) and price.get('price_american') not in (None, 0, '0') for price in prices)}
    offers = [quote for quote in group['offers'] if retained or quote['current']]
    if not retained and len(books | {quote['venue'] for quote in offers}) < minimum_places:
        return set()
    for quote in offers:
        original = quote['original']
        inputs = original['value'], original['units'], original.get('payout', '1')
        if all(isinstance(part, str) for part in inputs) and quote_supported(*inputs):
            books.add(quote['venue'])
    return books


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


def comparable_groups(groups, games, *, alternates, requested, requested_source, retained=False, minimum_places=3):
    roles = {game['game_key']: {p['id']: p['role'] for p in game['participants']
                              if p.get('id') and p.get('role') in ('home', 'away')} for game in games}
    eligible, lines = [], {}
    for group in groups:
        current = quote_places(group, minimum_places=minimum_places)
        places = quote_places(group, retained=True) if retained else current
        if not places or not retained and len(current) < minimum_places:
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
              and requested_source in group['game_sources']}
    return [group['id'] for group, market, line in eligible
            if alternates or line == mains[market] or group['id'] == requested
            or len(linked) == 1 and group['id'] in linked]


def display_quotes(quotes):
    """Keep a latest last-known quote only where a venue has no current offer."""
    current_venues = {quote['venue'] for quote in quotes if quote.get('price_current')}
    current, retained = [], {}
    for quote in quotes:
        venue = quote['venue']
        if quote.get('price_current'):
            current.append(quote)
        elif venue not in current_venues:
            receipt = (quote.get('times') or {}).get('received_at') or quote.get('captured_at')
            clock = stamp(receipt) if receipt else None
            if venue not in retained or clock and (retained[venue][0] is None or clock > retained[venue][0]):
                retained[venue] = clock, quote
    return current + [quote for _, quote in retained.values()]


def page(result, query, options, *, captured_pairs=(), policy=None, browsing=None, enrich=None, published_only=False,
         event_facts=None):
    view, _, offset, limit = options
    zone, day, minimum, dollars, stake = filters(query)
    search_query = search_parts(query.get('search', ''))
    terms = search_query[0]
    browse = query.get('browse_odds') == '1'
    ranked = query.get('ranked') == '1'
    comparable = query.get('lines') in ('main', 'all') and view != 'arbs' and (browse or ranked)
    current = published_only or (query.get('layout') == 'desk' and not result.get('replay')
                                 and bool(result['publication'].get('read_at')))
    phase = desk_phase(query, current=current)
    read_at = stamp(result['publication'].get('read_at') or result['captured_at']) if phase else None
    basis = query.get('basis') or 'reviewed'
    runtime = result['publication'].get('data_runtime') or {}
    public_summary = query.get('summary') == '1'
    pregame_desk = current and phase == 'pregame' and public_summary and query.get('layout') == 'desk'
    show_last_known = pregame_desk and (browse or ranked) and view != 'arbs'
    native_browse = browse and comparable and public_summary
    retained_fallback = (browse and phase != 'live' and view != 'arbs' and browse_retained(runtime)
                         and (current or not public_summary))
    show_retained = retained_fallback or not public_summary and (query.get('last_known') == '1' or (
        not (browse or ranked) and 'last_known' not in query))
    leagues, families, venues = (set(query.get(key, '').split(',')) - {''} for key in ('league', 'family', 'venue'))
    game_key = query.get('game_key')
    # A published occurrence can acquire a stronger identity on refresh.
    # A linked line follows its exact contract, while a matchup can also
    # follow an unambiguous provider event after one contract drops out.
    game_source = query.get('game_source')
    source_event = query.get('source_event')
    phase_rows = [row for row in result['rows'] if phase_matches(row, phase, read_at)
                  and (query.get('layout') != 'desk' or direct_venue_offer(row))]
    games = {g['game_key']: g for g in result.get('games', [])}
    search = search_index(result) if terms and len(search_query) == 1 else {}
    search_games = {}
    if pregame_desk and view != 'arbs' and (aliases := desk_game_aliases(phase_rows, games, event_facts)):
        game_key = aliases.get(game_key, game_key)
        if query.get('locate_game') in aliases:
            query = dict(query, locate_game=aliases[query['locate_game']])
        linked_outcomes = {name: query[name] for name in ('line', 'locate') if query.get(name)}
        for alias, canonical in aliases.items():
            if search:
                search[canonical] = ' '.join((search.get(canonical, ''), search.get(alias, '')))
            if len(search_query) == 2 and alias in games:
                search_games.setdefault(canonical, []).append(games[alias])
        for index, row in enumerate(phase_rows):
            if (canonical := aliases.get(row['game_key'])):
                display = dict(row, game_key=canonical)
                display.pop('display_outcome_key', None)
                phase_rows[index] = display
                if linked_outcomes:
                    old_id = outcome_id(outcome_key(row))
                    for name, identifier in linked_outcomes.items():
                        if identifier == old_id:
                            query = dict(query, **{name: outcome_id(outcome_key(display))})
    if browse and game_key and (game_source or source_event):
        replacement = set()
        event_matches = set()
        for row in phase_rows:
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

    def matches_search(row):
        key, title = row['game_key'], row['game_title']
        if len(search_query) == 1:
            return all(term in (title.casefold() + ' ' + search.get(key, '')) for term in terms)
        return any(matchup_search(search_query, game, title)
                   for game in (games.get(key, {}), *search_games.get(key, ())))

    def matches(row):
        market = row['market']
        local = datetime.fromisoformat(row['start_at']).astimezone(zone) if (
            day or query.get('time_from') or query.get('time_to')) else None
        return ((not game_key or row['game_key'] == game_key)
                and (not leagues or row['league'] in leagues) and (not families or market['market'] in families)
                and (phase == 'pregame' or not query.get('period') or market['period'] == query['period'])
                and (not day or local.date() == day)
                and (not query.get('time_from') or local.time()>=time.fromisoformat(query['time_from']))
                and (not query.get('time_to') or local.time()<time.fromisoformat(query['time_to']))
                and (phase or not query.get('game_state') or row.get('game_state','unknown')==query['game_state'])
                and matches_search(row))

    def passes(value, payoff=None):
        profit = (Fraction(payoff['minimum_net_profit_usd']) if payoff and payoff['available']
                  else value * stake / 100 if value is not None else None)
        return (browse or (not query.get('positive') or value is not None and value > 0)
                and (minimum is None or value is not None and value >= minimum)
                and (dollars is None or profit is not None and profit >= dollars))

    # Provider event titles sometimes describe one market family (e.g. Total
    # Points). A matchup label comes from the captured participants, never from
    # another market's title; the exact canonical market remains on each row.
    def labeled(row):
        participants=games.get(row['game_key'],{}).get('participants',[])
        names={p.get('id',p.get('name')):p.get('name') for p in participants if p.get('name')}
        if len(names)!=2:return row
        return dict(row,source_game_title=row['game_title'],game_title=' vs. '.join(names.values()))
    scoped_rows = [row for row in phase_rows if matches(row)]
    # Keep previously observed prices at their exact outcome when freshness
    # lapses. Ranking and mathematical calculations still require current inputs.
    rows = [labeled(row) for row in scoped_rows if show_retained or row.get('price_current')
            or show_last_known or native_browse and row['venue'] in NATIVE_VENUES]
    selected_rows = [row for row in rows if not venues or row['venue'] in venues]
    by_id = {row['id']: row for row in rows}
    metric = METRICS[basis]
    show_posted_unscored = pregame_desk and ranked and metric == SPORTSBOOK_METRIC
    eligible_pair_count = None
    pair_status = {}
    calculation_reason = None
    calculation_missing = []
    sportsbook_updates_paused = (result['publication'].get('sources', {}).get('sportsgameodds', {})
                                .get('reason_code') == 'sgo_charge_unresolved')
    if view == 'arbs':
        eligible = {r['id']: r for r in selected_rows if r.get('price_current')
                    and r.get('publication_policy') == policy and not r.get('comparison_capture_failed')}
        markets = {}
        expanded = {}
        scoped_legs = {r['id']: labeled(r) for r in scoped_rows if not venues or r['venue'] in venues}
        if phase == 'live':
            live_games = {(r['game_key'], r['start_at']) for r in eligible.values()}
            # A stale held leg belongs only to an inspectable pair on a game
            # that still has a qualifying Live price. It never makes a game Live.
            scoped_legs.update((r['id'], labeled(r)) for r in result['rows']
                if (r['game_key'], r['start_at']) in live_games and r.get('game_state') == 'live'
                and not r.get('price_current') and (not venues or r['venue'] in venues)
                and direct_venue_offer(r))
        blocker_counts = {}
        eligible_pair_count = 0
        for pair in captured_pairs:
            proof = pair.get('before_fees')
            if not proof or not all(leg in scoped_legs for leg in pair['legs']):
                continue
            current_legs = all(leg in eligible for leg in pair['legs'])
            if current_legs and len({eligible[leg].get('game_state') for leg in pair['legs']}) != 1:
                continue
            if not current_legs:
                payoff = dict(score=None, inspection=None, retail_payoff=dict(
                    available=False, reason='pair_leg_stale_or_replaced', legs=[]))
            elif blocker := proof.get('blocker'):
                payoff = dict(score=None, inspection=None, retail_payoff=dict(
                    available=False, reason=blocker, legs=[]))
            else:
                legs = [eligible[leg] for leg in pair['legs']]
                if published_only:
                    payoff = published_payoff(pair, legs)
                else:
                    for leg in legs:
                        if leg['id'] not in expanded:
                            expanded[leg['id']] = expand_row(leg)
                    payoff = current_payoff(pair, [expanded[leg] for leg in pair['legs']], stake)
            score = Fraction(payoff['score']) if payoff['score'] is not None else None
            eligible_pair_count += score is not None
            if reason := payoff['retail_payoff'].get('reason'):
                blocker_counts[reason] = blocker_counts.get(reason, 0) + 1
            if not passes(score, payoff['retail_payoff']):
                continue
            by_id.update((leg, scoped_legs[leg]) for leg in pair['legs'] if leg not in by_id)
            markets.setdefault(proof['market_key'], []).append(
                dict(pair, inspection=payoff['inspection'], retail_payoff=payoff['retail_payoff'], score=score))
        # The display can show additional exact-side offers. Only the pair's
        # evidenced legs participate in the payoff.
        sides = {}
        if not public_summary:
            for row in rows:
                sides.setdefault(outcome_key(row)[:6], []).append(row['id'])
        groups = []
        for key, pairs in markets.items():
            pairs.sort(key=lambda pair: (pair['score'] is None,
                                         -pair['score'] if pair['score'] is not None else 0, pair['id']))
            first = pairs[0]
            offer_ids = dict.fromkeys(leg for pair in pairs for leg in pair['legs'])
            if sides:
                for leg in tuple(offer_ids):
                    offer_ids.update(dict.fromkeys(sides[outcome_key(by_id[leg])[:6]]))
            groups.append(dict(first, id=key, quotes=pairs, offer_ids=list(offer_ids),
                               score=None if first['score'] is None else str(first['score'])))
        groups.sort(key=lambda g: (g['score'] is None, -Fraction(g['score']) if g['score'] is not None else 0,
                                   g['start_at'], g['id']))
        pending_pairs = blocker_counts.get('pair_fee_publication_pending', 0)
        expired_pairs = blocker_counts.get('pair_leg_stale_or_replaced', 0)
        pair_status = dict(finance_pending=pending_pairs, stale_or_replaced_legs=expired_pairs,
                           blockers=blocker_counts, withheld=sum(blocker_counts.values())
                           if query.get('positive') or minimum is not None or dollars is not None else 0)
        if pending_pairs:
            calculation_reason = 'An opposing pair is waiting for calculation publication.'
        elif expired_pairs and len(blocker_counts) == 1:
            calculation_reason = 'A previously matched pair lost a current leg.'
        elif blocker_counts and not eligible_pair_count:
            calculation_missing = sorted(blocker_counts)
            calculation_reason = 'Some opposing prices lack the evidence needed for a payoff.'
        elif any(row.get('price_current') for row in selected_rows):
            calculation_reason = 'No verified opposing pair has two current prices.'
    else:
        show_complete_outcomes = (comparable or ranked and bool(phase)) and query.get('group') != 'offer'
        def rank_row(row):
            if not (pregame_desk and venues and row['venue'] not in venues):
                return desk_ranking_value(row, metric)
            return None

        candidates = comparison_groups(rows if show_complete_outcomes else selected_rows,
                                       by_id, metric, current=True, individual=query.get('group') == 'offer',
                                       qualified=True, score_row=rank_row if ranked else None)
        # Browse chooses the main line from every venue. The site filter may
        # leave that outcome without a price, but cannot nominate a new line.
        groups = candidates if browse and comparable else [
            group for group in candidates if not venues or any(row['venue'] in venues for row in group['quotes'])]
        if not show_complete_outcomes:
            rows = selected_rows
    matched_outcome_count = len(groups)
    coverage = {}
    if view != 'arbs':
        visible_offers = selected_rows if pregame_desk and ranked else rows
        coverage = dict(offers=len(visible_offers), current=sum(bool(row.get('price_current')) for row in visible_offers),
                        **{basis_name: sum(desk_ranking_value(row, basis_metric) is not None for row in visible_offers)
                           for basis_name, basis_metric in METRICS.items()})
    if query.get('sort') == 'start' and not ranked:
        groups.sort(key=lambda g: g['start_at'])

    def present(group):
        summary = {k: group[k] for k in ('id', 'game_key', 'game_title', 'league', 'start_at', 'market', 'score')}
        summary['source_titles']=sorted({q.get('source_game_title',q.get('game_title','')) for q in group['quotes']}) if view!='arbs' else []
        if view == 'arbs':
            pairs = [dict(pair['before_fees'], id=pair['id'], legs=pair['legs'],
                          evidence_result_id=pair.get('evidence_result_id'),
                          inspection=pair['inspection'], assumed_scenario=pair.get('math'),
                          score=None if pair['score'] is None else str(pair['score']),
                          retail_payoff=pair['retail_payoff']) for pair in group['quotes']]
            summary['pairs'] = pairs
            summary['offers'] = [offer(by_id[id_]) for id_ in group['offer_ids']]
            summary['game_line_id'] = outcome_id(outcome_key(by_id[pairs[0]['legs'][0]]))
            summary['pair_status'] = 'calculated' if group['score'] is not None else pairs[0]['retail_payoff']['reason']
        else:
            quotes = display_quotes(group['quotes']) if show_last_known else group['quotes']
            summary['offers'] = [offer(row, metric, sportsbook_updates_paused=sportsbook_updates_paused)
                                 for row in quotes]
            if browse and not public_summary and metric == SPORTSBOOK_METRIC:
                for displayed, row in zip(summary['offers'], group['quotes'], strict=True):
                    if displayed['value'] is None and row.get('last_known_sportsbook_ev') is not None:
                        displayed['last_known_ev'] = row['last_known_sportsbook_ev']
            if query.get('group') == 'offer':
                summary['game_line_id'] = outcome_id(outcome_key(group['quotes'][0]))
            summary['score_source'] = group['score_source']
            if len({row['venue'] for row in group['quotes']}) > 1:
                identities = [(row.get('same_outcome') or {}).get('key') for row in group['quotes']]
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
        retained_comparison = show_posted_unscored or browse and (show_retained or show_last_known)
        candidates = []
        for group in groups:
            if (not (retained_comparison or show_last_known) and not any(row.get('price_current') for row in group['quotes'])
                    and not (native_browse and any(row['venue'] in NATIVE_VENUES for row in group['quotes']))):
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
                                   game_sources={game_source_key(row) for row in group['quotes']} if game_source else set()))
        if enrich and not retained_fallback:
            active = [candidate for candidate in candidates if any(quote['current'] for quote in candidate['offers'])]
            enrich(dict(rows=active if show_last_known else candidates, games=list(games.values())),
                   include_retained=show_retained)
        price_lists = {candidate['id']: candidate for candidate in candidates}
        comparison_options = dict(alternates=query['lines'] == 'all',
                                  requested=query.get('line') if game_key else None,
                                  requested_source=game_source if game_key and query.get('line') else None)
        minimum_places = 1 if pregame_desk and (browse or metric != EV_METRIC) else 3
        qualified = set(comparable_groups(candidates, games.values(), **comparison_options,
                                         retained=retained_comparison, minimum_places=minimum_places))
        if show_last_known and browse:
            limited_coverage = any(not any(offer['current'] for offer in candidate['offers'])
                                   for candidate in candidates if candidate['id'] in qualified)
        if browse and candidates and not retained_comparison:
            def game_market(group):
                return group['game_key'], group['market']['market'], group['market']['period']

            available = {game_market(group) for group in candidates if group['id'] in qualified}
            # A well-covered game elsewhere on the slate supplies no coverage
            # for this matchup. Keep its surviving quotes available in Browse.
            missing = [group for group in candidates if game_market(group) not in available
                       or game_key and group['id'] == query.get('line')]
            if missing:
                fallback = set(comparable_groups(missing, games.values(), alternates=query['lines'] == 'all',
                                                 requested=query.get('line'),
                                                 requested_source=game_source, retained=True)) - qualified
                qualified.update(fallback)
                limited_coverage = bool(fallback)
        if native_browse and query.get('lines') == 'all':
            # A different signed line may have only one direct venue. It
            # belongs in Browse at that exact line, outside EV qualification.
            qualified.update(group['id'] for group in candidates
                             if quote_places(group, retained=True) & NATIVE_VENUES)
        groups = [group for group in groups if group['id'] in qualified]
        if browse and venues and query['lines'] == 'all':
            groups = [group for group in groups if group['id'] == query.get('line')
                      or any(row['venue'] in venues for row in group['quotes'])]
    ranked_group_count = sum(g['score'] is not None for g in groups)
    if ranked and view != 'arbs' and not ranked_group_count and selected_rows:
        current_rows = [row for row in selected_rows if row.get('price_current')]
        aggregate = result['publication'].get('sources', {}).get('sportsgameodds', {})
        if show_last_known and not current_rows:
            calculation_reason = 'Fresh prices are required to calculate expected value.'
        elif coverage.get(basis):
            calculation_reason = 'Calculated prices exist outside the selected comparison lines.'
        elif current_rows and metric == SPORTSBOOK_METRIC:
            calculation_reason = ('Sportsbook updates are on hold.' if sportsbook_updates_paused else
                'No eligible two-sided sportsbook reference is available for these offers.')
        elif current_rows and all(row.get('probability_missing') == 'finance_pending' for row in current_rows):
            calculation_reason = 'Current prices are waiting for calculation publication.'
        elif current_rows and aggregate.get('state') == 'held' and not sportsbook_updates_paused:
            calculation_reason = 'The sportsbook reference source is on hold.'
        elif current_rows:
            reasons = [unavailable_calculation(visible_row(expand_row(row)), metric,
                                               sportsbook_updates_paused=sportsbook_updates_paused)
                       for row in current_rows]
            calculation_missing = sorted({reason for text in reasons if text for reason in text.split(', ')})[:8]
            calculation_reason = 'Current prices are missing inputs for the selected calculation.'
    if view != 'arbs':
        def posted_without_estimate(group):
            return show_posted_unscored and any(
                row.get('posted_price') and (not venues or row['venue'] in venues)
                and (row.get('selection') or {}).get('predicate') in ('win', 'cover', 'over', 'under')
                for row in group['quotes'])

        groups = [g for g in groups if (not ranked or g['score'] is not None or posted_without_estimate(g))
                  and passes(Fraction(g['score']) if g['score'] is not None else None, g.get('retail_payoff'))]

    page_by_game = (browse or pregame_desk and ranked) and not query.get('game_key') and view != 'arbs'
    page_units = groups
    if page_by_game:
        by_game = {}
        for group in groups:
            game = by_game.setdefault(group['game_key'], dict(id=group['game_key'],
                game_key=group['game_key'], game_title=group['game_title'], start_at=group['start_at'], outcomes=[]))
            game['outcomes'].append(group)
        page_units = (sorted(by_game.values(), key=lambda game: (game['start_at'], game['id']))
                      if browse else list(by_game.values()))
    session=browsing.page(page_units,query,offset,limit) if browsing else None
    if session and session['state']=='page_changed':return session
    if session:
        offset, anchor_state = session['offset'], session['anchor_state']
    else:
        from .browse_sessions import locate_page
        offset, anchor_state = locate_page(page_units, query, offset, limit)
    selected = session['rows'] if session else page_units[offset:offset + limit]
    visible_groups = [group for game in selected for group in game.get('outcomes', [game])] if page_by_game else selected
    visible = [g if g.get('withdrawn') else present(g) for g in visible_groups]
    display_groups = [group for group in visible if not group.get('withdrawn')]
    if enrich and show_last_known:
        # Historical book reads are needed only for the returned page.
        enrich(dict(rows=display_groups, games=list(games.values())), include_retained=True)
    for group in display_groups:
        pairs = group.pop('_sportsbook_pairs', None)
        if (candidate := price_lists.get(group['id'])) is not None:
            prices = group['sportsbook_quotes']
            for book, values in candidate['sportsbook_quotes'].items():
                shown = prices.setdefault(book, [])
                shown.extend(price for price in values if not any(
                    old.get('price_american') == price.get('price_american')
                    and old.get('source_at') == price.get('source_at') for old in shown))
            if candidate.get('sportsbook_source_reason'):
                group['sportsbook_source_reason'] = candidate['sportsbook_source_reason']
            pairs = pairs or candidate.get('_sportsbook_pairs')
        if basis == 'sportsbooks' and pairs:
            from app.comparison.public_sportsbook_estimate import choose_book
            book, probability = choose_book(pairs)
            pair = pairs[book][2]
            deadline = min(stamp(group['start_at']), *(
                stamp(price['source_at']) + timedelta(seconds=PREGAME_SPORTSBOOK_SECONDS) for price in pair))
            group['sportsbook_reference'] = dict(book=book, fair_odds=odds(decimal(1 / probability)),
                current_until=deadline.isoformat(),
                prices=[{key: price[key] for key in ('price_american', 'source_at')} for price in pair])
    if browse and not public_summary and not show_retained and visible:
        visible_games = {group['game_key'] for group in visible}
        retained_venues = {}
        for row in scoped_rows:
            if (row['game_key'] in visible_games and not row.get('price_current')
                    and (not venues or row['venue'] in venues)):
                retained_venues.setdefault(outcome_id(outcome_key(row)), set()).add(row['venue'])
        for group in visible:
            if not group.get('withdrawn') and group['id'] in retained_venues:
                group['retained_venues'] = sorted(retained_venues[group['id']])
    if enrich and view != 'arbs' and not show_last_known:
        displayed = dict(rows=display_groups, games=list(games.values()))
        if not comparable and not retained_fallback:
            enrich(displayed, include_retained=not public_summary and query.get('last_known') == '1')
        elif browse and not public_summary and (retained_fallback or not show_retained):
            # Retained prices and hints are needed only for the returned page.
            enrich(displayed, include_retained=retained_fallback, mark_retained=not retained_fallback)
    keys = {g['game_key'] for g in display_groups}
    if browse and game_key and any(row['game_key'] == game_key for row in phase_rows):
        keys.add(game_key)
    retained_game = None
    if current and browse and game_key and game_key not in keys:
        saved = max((row for row in result['rows'] if row['game_key'] == game_key
                     and row.get('captured_at') and row.get('evidence_result_id') and direct_venue_offer(row)),
                    key=lambda row: stamp(row['captured_at']), default=None)
        if saved is not None:
            retained_game = dict(game_key=game_key, result_id=saved['evidence_result_id'],
                                 captured_at=saved['captured_at'], lifecycle=saved.get('game_state_reason'))
    selected_line = None
    if browse and game_key and (requested_line := query.get('line')):
        selected_line = next((group['id'] for group in groups if group['id'] == requested_line), None)
        if not selected_line and game_source:
            matching_lines = {group['id'] for group in groups
                              if any(game_source_key(quote) == game_source for quote in group['quotes'])}
            if len(matching_lines) == 1:
                selected_line, = matching_lines
    if public_summary:
        visible = [public_group(group, basis) for group in visible]
    return dict(**({k:v for k,v in session.items() if k not in ('rows','state','total','offset','anchor_state')} if session else {}),
                state='ready', rows=visible,
                total=session['total'] if session else len(page_units), offset=offset, limit=limit,
                page_count=len(selected), anchor_state=anchor_state,
                games=[g for key, g in games.items() if key in keys],
                selected_game_key=game_key if browse else None, selected_line_id=selected_line,
                **({'selected_venues': sorted(venues)} if browse and comparable and venues else {}),
                **({'retained_game': retained_game} if retained_game else {}),
                publication=visible_publication(result['publication']), basis=basis, phase=phase, coverage=coverage,
                retained_fallback=bool(retained_fallback), limited_coverage=limited_coverage,
                matched_offer_count=len(rows), retained_offer_count=sum(not r.get('price_current') for r in scoped_rows),
                ranked_group_count=ranked_group_count, matched_outcome_count=matched_outcome_count,
                eligible_pair_count=eligible_pair_count, pair_status=pair_status,
                ranking_stake=str(DEFAULT_FUNDING if published_only else stake) if view == 'arbs' else None,
                calculation_reason=calculation_reason if not ranked_group_count else None,
                calculation_missing=calculation_missing if not ranked_group_count else [],
                row_kind=('games' if page_by_game else
                          'offers' if view != 'arbs' and query.get('group') == 'offer' else 'outcomes'),
                game_count=len({g['game_key'] for g in groups}),outcome_count=len(groups),
                offer_count=len({q['id'] for g in groups for q in g['quotes']}) if view!='arbs' else len(by_id),
                provider_requests=0)
