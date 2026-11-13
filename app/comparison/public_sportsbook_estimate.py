"""Exact-line display matching and indicative pregame sportsbook estimates."""
from collections import Counter
from datetime import timedelta
from fractions import Fraction
import json

from app.dashboard.current_contract import price
from app.normalization.registry import Registry
from app.storage.store import hashed, stamp
from .cashflows import exact_wire
from .game_phase import PREGAME_SPORTSBOOK_SECONDS
from .sgo_reference import BEST_BOOKS, OPPOSITE, american_probability

SPORTS = ('NBA', 'NFL', 'NHL', 'NCAAF', 'MLB')
SOURCE = 'oddslink_public_board'
MAX_BYTES = 512 * 1024
HISTORY_SLOTS = 11
LIFETIME = timedelta(seconds=PREGAME_SPORTSBOOK_SECONDS)
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


def retained_prices(root, captures, *, at, leagues):
    matches = index(captures, at=at, retained=True)
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
                latest = matches.setdefault(key, observation)
                for side, books in observation['quotes'].items():
                    quotes = latest['quotes'].setdefault(side, {})
                    for book, prices in books.items():
                        quotes.setdefault(book, prices)
    return matches


def allowed(owner):
    config = owner.get('config') or {}
    return bool(owner.get('active') and not owner.get('global_stopped')
                and config.get('aggregate_enabled') and config.get('aggregate_provider') == 'sportsgameodds'
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
        (clock := stamp(item['source_at'])) < start and clock <= at <= clock + LIFETIME
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
                        # Two-way public board markets only. A three-way winner is a different predicate.
                        if len(sides) > 2:
                            continue
                        for side in sides:
                            label = side['name']
                            role = label.lower() if family == 'total' else roles.get(label)
                            if role not in (('over', 'under') if family == 'total' else ('home', 'away')):
                                continue
                            point = side.get('point')
                            value = side['price']
                            if (type(value) is not int or abs(value) < 100 or
                                    (family == 'moneyline') != (point is None)):
                                continue
                            selection = (family, role, None if point is None else Fraction(str(point)))
                            quotes.setdefault(selection, {}).setdefault(venue, []).append(
                                quote(f'{value:+d}', clock, selection))
                matches[key] = dict(source=SOURCE, event_id=event['id'], frame_id=capture['sha256'],
                                    frame_received_at=capture['received_at'], quotes=quotes,
                                    scheduled=event['in_play'] is False)
                matches[key]['revision'] = hashed([event['id'], matches[key]['scheduled'],
                    [(str(selection), quotes[selection]) for selection in sorted(quotes, key=str)]])
            except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
                continue
    return {key: value for key, value in matches.items() if key not in duplicates}


def market_pairs(observation, key, *, at, start):
    if not observation or not observation['scheduled'] or at >= start:
        return {}
    selected = observation['quotes'].get(key, {})
    other = observation['quotes'].get(opposing(key), {})
    pairs = {}
    for book in BEST_BOOKS:
        first, second = selected.get(book, ()), other.get(book, ())
        if len(first) == len(second) == 1:
            pair = [first[0], second[0]]
            if observation['source'] != SOURCE and (
                    first[0]['odd_id'] == second[0]['odd_id']
                    or first[0]['opposing_odd_id'] != second[0]['odd_id']
                    or second[0]['opposing_odd_id'] != first[0]['odd_id']):
                continue
            if clocks_current(pair, at=at, start=start):
                pairs[book] = pair
    return pairs


def sgo_observation(frame, rows, *, at, occurrence):
    from .game_phase import sgo_event_status, sporting_phase

    facts = (frame or {}).get('facts') or {}
    context = facts.get('event_context') or {}
    lifecycle = sporting_phase({'status': sgo_event_status(context.get('status') or {})})
    league, start, _, _ = occurrence
    received = stamp(facts['received_at']) if facts.get('received_at') else None
    if (not received or received > at or received >= start or at >= start
            or facts.get('provider') != 'sportsgameodds' or context.get('league') != league
            or context.get('phase') != 'pregame' or stamp(facts['starts_at']) != start
            or lifecycle['reason'] or lifecycle['state'] == 'live'):
        return None
    members = dict(facts['members'])
    if len(members) != len(facts['members']):
        return None
    quotes = {}
    for row in rows:
        fact = row['facts']
        if (members.get(row['id']) != row['revision'] or fact.get('provider') != 'sportsgameodds'
                or fact['event_id'] != facts['event_id'] or fact['league'] != league
                or fact['period'] != 'game' or fact['phase'] != 'pregame' or not fact['available']
                or fact['venue'] not in BEST_BOOKS or not fact.get('source_at')
                or fact['market'] not in FAMILIES.values() or fact['side'] not in OPPOSITE):
            continue
        try:
            family, side = fact['market'], fact['side']
            line = None if fact['line'] is None else Fraction(fact['line'])
            if ((family == 'moneyline') != (line is None)
                    or side not in (('over', 'under') if family == 'total' else ('home', 'away'))
                    or not stamp(fact['source_at']) <= stamp(fact['received_at']) <= received):
                continue
            key = (family, side, line)
            item = quote(fact['price_american'], fact['source_at'], key)
            item.update(odd_id=fact['odd_id'], opposing_odd_id=fact['opposing_odd_id'])
            quotes.setdefault(key, {}).setdefault(fact['venue'], []).append(item)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
    return dict(source='sportsgameodds', event_id=facts['event_id'], frame_id=facts['receipt_sha256'],
                frame_received_at=facts['received_at'], quotes=quotes, scheduled=True)


def select(row, authority, observations, *, at):
    record = row.get('original_record') or {}
    event = record.get('event') or {}
    market = record.get('market_identity') or {}
    original = row['original']
    if (authority.get('provider') not in ('kalshi', 'polymarket_us') or authority.get('reasons')
            or not authority.get('expected') or authority['lifecycle']['state'] != 'scheduled'
            or market.get('period') != 'full_game' or original.get('units') not in ('usd_per_contract', 'cents_per_contract')
            or original.get('payout') != '1' or original.get('payout_units') != 'USD'):
        return None
    occurrence = signature(event, row['league'])
    key = outcome(market.get('family'), record.get('selection') or {}, event['home'], event['away'])
    start = occurrence[1]
    if not key or at >= start:
        return None
    return estimate(price(row), observations, occurrence, key, at=at)


def estimate(cost, observations, occurrence, key, *, at):
    start = occurrence[1]
    candidates = {}
    for observation in observations.get(occurrence, ()):
        for book, pair in market_pairs(observation, key, at=at, start=start).items():
            prior = candidates.get(book)
            # Prefer the most recent complete pair without mixing feeds or clocks.
            rank = (min(stamp(item['source_at']) for item in pair), observation['source'] == SOURCE)
            if not prior or rank > prior[0]:
                candidates[book] = rank, observation, pair
    if not candidates or not 0 < cost < 1:
        return None
    book = min(candidates, key=lambda name: (american_probability(candidates[name][2][0]['price_american']),
                                             BEST_BOOKS.index(name)))
    _, selected, pair = candidates[book]
    implied, opposite = (american_probability(item['price_american']) for item in pair)
    probability = implied / (implied + opposite)
    prices = {name: [{field: item[field] for field in ('price_american', 'source_at', 'side', 'line')}
                     for item in value[2]] for name, value in candidates.items()}
    deadline = min(start, *(stamp(item['source_at']) + LIFETIME for item in pair))
    return dict(source=selected['source'], event_id=selected['event_id'], frame_id=selected['frame_id'],
                frame_received_at=selected['frame_received_at'], book=book, candidate_books=len(prices),
                current_until=deadline.isoformat(), probability=exact_wire(probability),
                fair_decimal_odds=exact_wire(1 / probability), return_percent=exact_wire(100 * (probability / cost - 1)),
                cost=exact_wire(cost), prices=prices[book], candidates=prices, indicative=True,
                reference_inputs={name: [value[1]['source'], value[1]['event_id'],
                                         value[1].get('revision', value[1]['frame_id'])]
                                  for name, value in candidates.items()})


def identity(observation, *, at):
    current = sorted((str(key), book, item['source_at']) for key, books in observation['quotes'].items()
                     for book, prices in books.items() for item in prices
                     if at <= stamp(item['source_at']) + LIFETIME)
    return [observation.get('revision', observation['frame_id']), current]
