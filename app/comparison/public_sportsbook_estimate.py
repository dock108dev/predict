"""Exact-line display matching and indicative pregame sportsbook estimates."""
from collections import Counter
from fractions import Fraction
import json

from app.collection.current_policy import aggregate_provider
from app.dashboard.current_contract import price
from app.normalization.registry import Registry
from app.storage.store import hashed, stamp
from .cashflows import exact_wire
from .sgo_reference import BEST_BOOKS, OPPOSITE, american_probability, best_payout_book, no_vig_probability

SPORTS = ('NBA', 'NFL', 'NHL', 'NCAAF', 'NCAAB', 'MLB')
SOURCE = 'oddslink_public_board'
MAX_BYTES = 512 * 1024
HISTORY_SLOTS = 11
FAMILIES = {'h2h': 'moneyline', 'spreads': 'spread', 'totals': 'total'}


def cache_path(root, league=None):
    name = f'public-sportsbook-board-{league.lower()}' if league else 'public-sportsbook-board'
    return root / '.local' / f'{name}.json'


def read_capture(path, *, at, league=None):
    try:
        with path.open('rb') as stream:
            wire = stream.read(MAX_BYTES + 4096)
        if len(wire) >= MAX_BYTES + 4096:
            return None
        data = json.loads(wire)
        sport = data['sport_key'].upper()
        if (sport in SPORTS and (league is None or sport == league)
                and isinstance(data['fixtures'], list) and len(data['fixtures']) <= 60
                and stamp(data['generated_at']) <= stamp(data['received_at']) <= at):
            return data
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return None


def read_captures(root, *, at):
    captures = {}
    for league in (None, *SPORTS):
        data = read_capture(cache_path(root, league), at=at, league=league)
        if data:
            captures[data['sport_key'].upper()] = data
    return captures


def retained_prices(root, captures, *, at, leagues, coherent=False):
    matches = index(captures, at=at, retained=True)
    frames = {key: [observation] for key, observation in matches.items()} if coherent else None
    directory = cache_path(root).parent / 'public-sportsbook-history'
    for league in SPORTS:
        if league not in leagues:
            continue
        for slot in range(HISTORY_SLOTS):
            path = directory / f'{league.lower()}-{slot}.json'
            capture = read_capture(path, at=at, league=league)
            if not capture:
                continue
            older = index({league: capture}, at=at, retained=True)
            for key, observation in older.items():
                if coherent:
                    saved = frames.setdefault(key, [])
                    if not any(item['frame_id'] == observation['frame_id'] for item in saved):
                        saved.append(observation)
                    continue
                latest = matches.setdefault(key, observation)
                for side, books in observation['quotes'].items():
                    quotes = latest['quotes'].setdefault(side, {})
                    for book, prices in books.items():
                        quotes.setdefault(book, prices)
    for match in matches.values():
        quotes = match['quotes']
        match['revision'] = hashed([match['event_id'], match['scheduled'],
            [(str(selection), quotes[selection]) for selection in sorted(quotes, key=str)]])
    return frames if coherent else matches


def allowed(owner):
    config = owner.get('config') or {}
    return bool(owner.get('active') and not owner.get('global_stopped')
                and config.get('aggregate_enabled') and aggregate_provider(config) == 'sportsgameodds'
                and 'sportsgameodds' not in owner.get('paused_sources', ()))


def signature(event, league):
    return league, stamp(event['scheduled_start']), event['home'], event['away']


def outcome(family, selection, home, away):
    predicate, line = selection.get('predicate'), selection.get('signed_line')
    participant = selection.get('participant')
    side = 'home' if participant == home else 'away' if participant == away else None
    if family == 'moneyline' and predicate == 'win' and line is None and side:
        return family, side, None
    if family == 'spread' and predicate == 'cover' and side and line is not None:
        return family, side, Fraction(line)
    if family == 'total' and predicate in ('over', 'under') and line is not None:
        return family, predicate, Fraction(line)
    return None


def opposing(key):
    family, side, line = key
    return family, OPPOSITE[side], -line if family == 'spread' else line


def quote(american, clock, key):
    american_probability(american)
    _, side, line = key
    return dict(price_american=american, source_at=clock, side=side,
                line=None if line is None else exact_wire(line))


def clocks_current(prices, *, at, start):
    return (at < start and len(prices) == 2 and all(
        stamp(item['source_at']) <= at
        for item in prices))


def index(captures, *, at, retained=False):
    """Index full-game public quotes by unique occurrence, exact side and line."""
    registry = Registry.current()
    matches, seen, duplicates = {}, set(), set()
    for league, capture in captures.items():
        for event in capture['fixtures'][:60]:
            try:
                start = stamp(event['commence_time'])
                if event['sport_key'].upper() != league:
                    continue
                names = (event['home_team'], event['away_team'])
                teams = tuple(registry.resolve('team', name, league=league).canonical_id for name in names)
                if None in teams or teams[0] == teams[1]:
                    continue
                key = (league, start, *teams)
                if key in seen:
                    duplicates.add(key)
                seen.add(key)
                if not retained and (start <= at or event['in_play'] is not False):
                    continue
                books = Counter(book['key'] for book in event['bookmakers'])
                quotes = {}
                for book in event['bookmakers']:
                    venue = book['key']
                    if venue not in BEST_BOOKS or books[venue] != 1 or book['kind'] != 'sportsbook':
                        continue
                    clock = book.get('last_update')
                    if not clock or not stamp(clock) <= stamp(capture['generated_at']):
                        continue
                    roles = dict(zip(names, ('home', 'away'), strict=True))
                    for market, family in FAMILIES.items():
                        sides = book['markets'].get(market, [])
                        if len(sides) > (3 if family == 'moneyline' else 2):
                            continue
                        is_three_way = family == 'moneyline' and len(sides) == 3
                        for side in sides:
                            label = side['name']
                            role = label.lower() if family == 'total' else roles.get(label)
                            if is_three_way and label.lower() == 'draw':
                                role = 'draw'
                            valid_roles = ('over', 'under') if family == 'total' else ('home', 'away', 'draw')
                            if role not in valid_roles or role == 'draw' and not is_three_way:
                                continue
                            point = side.get('point')
                            value = side['price']
                            if (type(value) is not int or abs(value) < 100 or
                                    (family == 'moneyline') != (point is None)):
                                continue
                            selection = (family, role, None if point is None else Fraction(str(point)))
                            item = quote(f'{value:+d}', clock, selection)
                            if is_three_way:
                                item['partition'] = 'three_way'
                            quotes.setdefault(selection, {}).setdefault(venue, []).append(item)
                matches[key] = dict(source=SOURCE, event_id=event['id'], frame_id=capture['sha256'],
                                    frame_received_at=capture['received_at'], quotes=quotes,
                                    scheduled=event['in_play'] is False)
                matches[key]['revision'] = hashed([event['id'], matches[key]['scheduled'],
                    [(str(selection), quotes[selection]) for selection in sorted(quotes, key=str)]])
            except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
                continue
    return {key: value for key, value in matches.items() if key not in duplicates}


def market_pairs(observation, key, *, at, start, require_current=True):
    if not observation or not observation['scheduled'] or at >= start:
        return {}
    selected = observation['quotes'].get(key, {})
    other = observation['quotes'].get(opposing(key), {})
    pairs = {}
    for book in BEST_BOOKS:
        first, second = selected.get(book, ()), other.get(book, ())
        if len(first) == len(second) == 1:
            pair = [first[0], second[0]]
            if any(leg.get('partition') == 'three_way' for leg in pair):
                continue
            if observation['source'] != SOURCE and (
                    first[0]['odd_id'] == second[0]['odd_id']
                    or first[0]['opposing_odd_id'] != second[0]['odd_id']
                    or second[0]['opposing_odd_id'] != first[0]['odd_id']):
                continue
            if (clocks_current(pair, at=at, start=start) if require_current else
                    all(stamp(item['source_at']) < start and stamp(item['source_at']) <= at for item in pair)):
                pairs[book] = pair
    return pairs


def sgo_observation(frame, rows, *, at, occurrence, coherent=False):
    from .game_phase import sgo_event_status, sporting_phase
    from app.storage.sgo_schedule_review import frame_start

    facts = (frame or {}).get('facts') or {}
    context = facts.get('event_context') or {}
    lifecycle = sporting_phase({'status': sgo_event_status(context.get('status') or {})})
    league, start, _, _ = occurrence
    received = stamp(facts['received_at']) if facts.get('received_at') else None
    if (not received or received > at or received >= start or at >= start
            or facts.get('provider') != 'sportsgameodds' or context.get('league') != league
            or stamp(frame_start(facts['event_id'], league, context.get('teams'), facts['starts_at'],
                                 facts['receipt_sha256'], at=at)) != start):
        return None
    scheduled = context.get('phase') == 'pregame' and not lifecycle['reason'] and lifecycle['state'] != 'live'
    if not scheduled and not coherent:
        return None
    members = dict(facts['members'])
    if len(members) != len(facts['members']):
        return None
    quotes, retired = {}, {}
    for row in rows:
        fact = row['facts']
        if (fact.get('provider') != 'sportsgameodds'
                or fact['event_id'] != facts['event_id'] or fact['league'] != league
                or fact['period'] != 'game' or fact['phase'] != 'pregame'
                or fact['venue'] not in BEST_BOOKS or not fact.get('source_at')
                or fact['market'] not in FAMILIES.values() or fact['side'] not in (*OPPOSITE, 'draw')):
            continue
        try:
            family, side = fact['market'], fact['side']
            line = None if fact['line'] is None else Fraction(fact['line'])
            if ((family == 'moneyline') != (line is None)
                    or side not in (('over', 'under') if family == 'total' else ('home', 'away', 'draw'))
                    or not stamp(fact['source_at']) <= stamp(fact['received_at']) <= received):
                continue
            key = (family, side, line)
            if not fact['available']:
                if coherent:
                    retired[(fact['venue'], fact['odd_id'], None if line is None else exact_wire(line))] = fact['source_at']
                continue
            if coherent and members.get(row['id']) != row['revision']:
                continue
            item = quote(fact['price_american'], fact['source_at'], key)
            item.update(odd_id=fact['odd_id'], opposing_odd_id=fact['opposing_odd_id'],
                        received_at=fact['received_at'], revision=row.get('revision'))
            if fact.get('partition'):
                item['partition'] = fact['partition']
            quotes.setdefault(key, {}).setdefault(fact['venue'], []).append(item)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
    return dict(source='sportsgameodds', event_id=facts['event_id'], frame_id=facts['receipt_sha256'],
                frame_received_at=facts['received_at'], quotes=quotes, scheduled=scheduled, retired=retired,
                revision=hashed([scheduled, [(str(key), quotes[key]) for key in sorted(quotes, key=str)],
                                 sorted(retired.items(), key=str)]))


def select(row, authority, observations, *, at):
    record = row.get('original_record') or {}
    event = record.get('event') or {}
    market = record.get('market_identity') or {}
    original = row['original']
    provider = authority.get('provider')
    native = provider in ('kalshi', 'polymarket_us') and original.get('units') in ('usd_per_contract', 'cents_per_contract')
    public_execution = (provider == SOURCE and row['venue'] == 'prophetx'
                        and original.get('units') == 'american_odds')
    if (not (native or public_execution) or authority.get('reasons')
            or not authority.get('expected') or authority['lifecycle']['state'] != 'scheduled'
            or market.get('period') != 'full_game'
            or original.get('payout') != '1' or original.get('payout_units') != 'USD'):
        return None
    occurrence = signature(event, row['league'])
    key = outcome(market.get('family'), record.get('selection') or {}, event['home'], event['away'])
    start = occurrence[1]
    if not key or at >= start:
        return None
    return estimate(price(row), observations, occurrence, key, at=at)


def has_retained_public_pair(baseline):
    return any(item[0] == SOURCE for item in (baseline.get('reference_inputs') or {}).values())


def restore_public_pairs(row, prior, observations, *, at):
    """Reuse the exact selected public pairs from the last immutable component.

    The rolling provider cache is for recent polling. Once a complete pair has
    been published, a page that omits that market must not retire its inputs.
    Reconstitution is limited to the same stored offer contract and schedule.
    """
    event = row['original_record']['event']
    occurrence = signature(event, row['league'])
    prior_record = prior['original_record']
    if (signature(prior_record['event'], prior['league']) != occurrence
            or stamp(prior['start_at']) != occurrence[1] or at >= occurrence[1]):
        return observations
    baseline = prior.get('sportsbook_baseline') or {}
    current = observations.get(occurrence, ())
    if any(item['source'] == SOURCE and not item.get('scheduled') for item in current):
        return observations
    market = row['original_record']['market_identity']
    key = outcome(market['family'], row['original_record']['selection'], event['home'], event['away'])
    saved = []
    prior_key = outcome(prior_record['market_identity']['family'], prior_record['selection'],
                        prior_record['event']['home'], prior_record['event']['away'])
    if key and key == prior_key:
        for book, pair in (baseline.get('candidates') or {}).items():
            evidence = baseline.get('reference_inputs', {}).get(book, ())
            if len(evidence) != 3 or evidence[0] != SOURCE or not clocks_current(pair, at=at, start=occurrence[1]):
                continue
            _, event_id, revision = evidence
            saved.append(dict(source=SOURCE, event_id=event_id, revision=revision, frame_id=revision,
                frame_received_at=baseline['frame_received_at'], scheduled=True,
                quotes={key: {book: [pair[0]]}, opposing(key): {book: [pair[1]]}}))
    return {occurrence: [*current, *saved]} if saved else observations


def collect_pairs(candidates, observations, key, *, at, start):
    for observation in observations:
        for book, pair in market_pairs(observation, key, at=at, start=start).items():
            prior = candidates.get(book)
            # Prefer the most recent complete pair without mixing feeds or clocks.
            clocks = sorted(stamp(item['source_at']) for item in pair)
            rank = (*clocks, observation['source'] == SOURCE)
            if not prior or rank > prior[0]:
                candidates[book] = rank, observation, pair


def choose_book(candidates):
    selected_implied = {book: american_probability(pair[0]['price_american'])
                        for book, (_, _, pair) in candidates.items()}
    book = best_payout_book(selected_implied)
    opposite = american_probability(candidates[book][2][1]['price_american'])
    return book, no_vig_probability(selected_implied[book], opposite)


def estimate(cost, observations, occurrence, key, *, at):
    start = occurrence[1]
    candidates = {}
    collect_pairs(candidates, observations.get(occurrence, ()), key, at=at, start=start)
    if not candidates or not 0 < cost < 1:
        return None
    book, probability = choose_book(candidates)
    _, selected, pair = candidates[book]
    prices = {name: [{field: item[field] for field in ('price_american', 'source_at', 'received_at', 'side', 'line', 'alternate')
                      if field in item}
                     for item in value[2]] for name, value in candidates.items()}
    deadline = start
    return dict(source=selected['source'], event_id=selected['event_id'], frame_id=selected['frame_id'],
                frame_received_at=selected['frame_received_at'], book=book, candidate_books=len(prices),
                current_until=deadline.isoformat(), probability=exact_wire(probability),
                fair_decimal_odds=exact_wire(1 / probability), return_percent=exact_wire(100 * (probability / cost - 1)),
                cost=exact_wire(cost), prices=prices[book], candidates=prices, indicative=True,
                reference_inputs={name: [value[1]['source'], value[1]['event_id'],
                                         value[1].get('revision', value[1]['frame_id'])]
                                  for name, value in candidates.items()})


def identity(observation, *, at):
    return observation.get('revision', observation['frame_id'])
