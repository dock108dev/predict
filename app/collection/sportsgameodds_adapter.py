"""Bounded SportsGameOdds page decoding and source-local observations.

This module does not dispatch requests or write current rows. A complete cursor
walk alone is not proof of absence: moving provider pages may omit events.
"""
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

from app.comparison.sgo_reference import BEST_BOOKS

LEAGUES = frozenset(('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'))
MARKETS = {'ml': 'moneyline', 'sp': 'spread', 'ou': 'total'}
MAX_PAGE_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 100
MAX_ODDS_PER_EVENT = 20000
MAX_BOOKS_PER_ODD = 200
PROPHETX_BOOKMAKER_ID = 'prophetexchange'
P2P_BOOKS = frozenset(('novig', 'prophetx', PROPHETX_BOOKMAKER_ID, 'kalshi', 'polymarket', 'matchbook', 'betfairexchange'))
LINK_BOOKS = P2P_BOOKS | {'pinnacle', *BEST_BOOKS}
OPPOSITE_SIDE = {'home': 'away', 'away': 'home', 'over': 'under', 'under': 'over'}


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON key')
        out[key] = value
    return out


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value):
        raise ValueError('invalid source time')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid source time') from exc
    if parsed.utcoffset() is None:
        raise ValueError('timezone required')
    return value if parsed.utcoffset().total_seconds() == 0 else parsed.astimezone(timezone.utc).isoformat()


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('invalid number')
    if len(str(value)) > 256:
        raise ValueError('invalid number')
    try:
        n = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('invalid number') from exc
    if not n.is_finite() or abs(n) > 1000000:
        raise ValueError('invalid number')
    return str(n)


def _price(value):
    n = _number(value)
    if Decimal(n) != Decimal(n).to_integral_value() or abs(Decimal(n)) < 100:
        raise ValueError('invalid American price')
    return value if isinstance(value, str) else str(value)


def _identity(value):
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError('invalid identity')
    return value


def _baseline(odd, typ, prefix):
    odds_key = prefix + 'Odds'
    result = dict(available=odd.get(odds_key + 'Available') is True, price_american=None, line=None, source_at=None)
    try:
        if odd.get(odds_key) is not None:
            result['price_american'] = _price(odd[odds_key])
        if typ != 'ml':
            line_key = prefix + ('Spread' if typ == 'sp' else 'OverUnder')
            if odd.get(line_key) is not None:
                result['line'] = _number(odd[line_key])
    except ValueError:
        result['available'] = False
    if result['price_american'] is None or (typ != 'ml' and result['line'] is None):
        result['available'] = False
    return result


def _link_witness(raw):
    if not isinstance(raw, str) or len(raw) > 2048 or not raw.isascii() or any(c.isspace() for c in raw):
        return None
    try:
        url = urlsplit(raw)
    except ValueError:
        return None
    if (url.scheme != 'https' or not re.fullmatch(r'[a-zA-Z0-9.-]{1,253}', url.netloc)
            or not re.fullmatch(r'/[a-zA-Z0-9_./%~+-]{1,384}', url.path) or url.path.startswith('//')):
        return None
    return {'host': url.netloc.lower(), 'path': url.path}


def bookmaker_event_links(event):
    """Retain bounded provider-attributed origin and path for manual review."""
    links = event.get('links')
    books = links.get('bookmakers') if isinstance(links, dict) else None
    if not isinstance(books, dict):
        return {}
    retained = {}
    for venue in sorted(LINK_BOOKS):
        if witness := _link_witness(books.get(venue)):
            retained[venue] = witness
    return retained


@dataclass(frozen=True)
class Page:
    events: tuple
    quotes: tuple
    next_cursor: str | None
    receipt_sha256: str | None = None
    payload_bytes: int = 0
    alternate_rows: int = 0
    duplicate_alternate_rows: int = 0
    conflicting_alternate_lines: int = 0
    ignored_bookmaker_groups: int = 0


def clock_sample(page, *, admitted_at=None):
    """Count receipt and admission clock stages for source-local observations."""
    from app.comparison.game_phase import LIVE_SECONDS, sgo_event_status, sporting_phase

    events = {e['event_id']: e for e in page.events}
    starts = {eid: datetime.fromisoformat(event['starts_at']) for eid, event in events.items()}
    eligible_live = {eid for eid, event in events.items()
                     if sporting_phase({'status': sgo_event_status(event['status'])})['state'] == 'live'}
    reference_books = {'pinnacle', *BEST_BOOKS}
    counts, reference = {}, defaultdict(list)
    live_offers = []
    for quote in page.quotes:
        venue, event_id = quote['venue'], quote['event_id']
        if venue not in P2P_BOOKS and venue not in reference_books:
            continue
        event = events[event_id]
        cohort = (quote['league'], quote['phase'], quote['market'], venue)
        tally = counts.setdefault(cohort, dict(observations=0, available=0, within_900_seconds=0,
            within_15_seconds=0,
            live_available=0, live_post_start=0, live_fresh=0, live_fresh_at_admission=0,
            live_with_exact_pinnacle_pair=0, live_with_post_start_pinnacle_pair=0,
            live_with_pinnacle_clocks=0, live_with_pinnacle_clocks_at_admission=0,
            live_with_exact_sportsbook_pair=0, live_with_post_start_sportsbook_pair=0,
            live_with_sportsbook_clocks=0, live_with_sportsbook_clocks_at_admission=0))
        tally['observations'] += 1
        tally['available'] += int(quote['available'])
        source = quote['source_at']
        receipt = datetime.fromisoformat(quote['received_at'])
        clock = datetime.fromisoformat(source) if source else None
        age = (receipt - clock).total_seconds() if clock else -1
        if quote['available'] and 0 <= age <= 900:
            tally['within_900_seconds'] += 1
        if quote['available'] and 0 <= age <= LIVE_SECONDS:
            tally['within_15_seconds'] += 1
        live_available = quote['available'] and event_id in eligible_live
        post_start = live_available and age >= 0 and clock >= starts[event_id]
        fresh = post_start and age <= LIVE_SECONDS
        fresh_at_admission = fresh and (admitted_at is not None and
            receipt <= admitted_at <= clock + timedelta(seconds=LIVE_SECONDS))
        tally['live_available'] += int(live_available)
        tally['live_post_start'] += int(post_start)
        tally['live_fresh'] += int(fresh)
        tally['live_fresh_at_admission'] += int(fresh_at_admission)
        line = Decimal(quote['line']) if quote['line'] is not None else None
        key = (event_id, quote['market'], quote['odd_id'], quote['side'], line)
        opposite_line = -line if line is not None and quote['market'] == 'spread' else line
        opposite = (event_id, quote['market'], quote['opposing_odd_id'], OPPOSITE_SIDE[quote['side']], opposite_line)
        if venue in reference_books:
            reference[venue, key].append((opposite, live_available, post_start, fresh, fresh_at_admission))
        elif live_available:
            live_offers.append((tally, key, opposite, post_start, fresh, fresh_at_admission))
    for tally, key, opposite, post_start, fresh, fresh_at_admission in live_offers:
        for label, venues in (('pinnacle', ('pinnacle',)), ('sportsbook', BEST_BOOKS)):
            matched = []
            for venue in venues:
                same, other = reference.get((venue, key), ()), reference.get((venue, opposite), ())
                if len(same) == len(other) == 1 and same[0][0] == opposite and other[0][0] == key:
                    matched.append((same[0], other[0]))
            for index, (field, offer_meets_clock) in enumerate((
                    (f'live_with_exact_{label}_pair', True),
                    (f'live_with_post_start_{label}_pair', post_start),
                    (f'live_with_{label}_clocks', fresh),
                    (f'live_with_{label}_clocks_at_admission', fresh_at_admission)), start=1):
                tally[field] += int(offer_meets_clock and any(same[index] and other[index] for same, other in matched))
    return counts


def parse_page(body, received_at, *, leagues=LEAGUES, venues=None):
    """Decode a bounded provider page; malformed supported facts fail closed.

    Exact source decimals and separate receipt clocks are retained. A quote
    lacking a usable price or source clock remains visible as unavailable.
    Unsupported periods and player/team totals are excluded.
    """
    receipt_original = received_at
    received_at = _time(received_at)
    if not isinstance(leagues, (set, frozenset, list, tuple)) or not leagues or not set(leagues) <= LEAGUES:
        raise ValueError('invalid league scope')
    if not isinstance(body, bytes) or len(body) > MAX_PAGE_BYTES:
        raise ValueError('page size')
    try:
        data = json.loads(body, parse_float=Decimal, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid JSON number')))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid page JSON') from exc
    if not isinstance(data, dict) or data.get('success') is not True or not isinstance(data.get('data'), list):
        raise ValueError('provider response incomplete')
    if len(data['data']) > MAX_EVENTS:
        raise ValueError('event limit')
    cursor = data.get('nextCursor')
    if cursor is not None:
        _identity(cursor)
    events, quotes, seen = [], [], set()
    alternate_rows = duplicate_alternate_rows = conflicting_alternate_lines = ignored_bookmaker_groups = 0
    for event in data['data']:
        if not isinstance(event, dict):
            raise ValueError('event shape')
        event_id = _identity(event.get('eventID'))
        if event_id in seen:
            raise ValueError('duplicate event')
        seen.add(event_id)
        league = _identity(event.get('leagueID'))
        if league not in leagues:
            raise ValueError('event outside requested scope')
        status, teams, odds = event.get('status'), event.get('teams'), event.get('odds', {})
        if not isinstance(status, dict) or not isinstance(teams, dict) or not isinstance(odds, dict) or len(odds) > MAX_ODDS_PER_EVENT:
            raise ValueError('event shape or odds limit')
        names, scores = {}, {}
        for role in ('home', 'away'):
            try:
                team = teams[role]
                names[role] = {'id': _identity(team['teamID']), 'name': _identity(team['names']['long'])}
                if team.get('score') is not None:
                    scores[role] = _number(team['score'])
            except (KeyError, TypeError) as exc:
                raise ValueError('team identity') from exc
        if not isinstance(status.get('live'), bool) or not isinstance(status.get('started'), bool):
            raise ValueError('event phase unknown')
        phase = 'live' if status['live'] else 'started' if status['started'] else 'pregame'
        aliases = event.get('aliases', [])
        if not isinstance(aliases, list) or len(aliases) > 100:
            raise ValueError('event aliases')
        aliases = [_identity(alias) for alias in aliases]
        # Retain only bounded full-game team points, rather than the provider's
        # potentially large player/stat tree. These are audit observations,
        # not venue settlement authority or a substitute for a source clock.
        game_results = {}
        results = event.get('results')
        game = results.get('game') if isinstance(results, dict) else None
        if isinstance(game, dict):
            for role in ('home', 'away'):
                values = game.get(role)
                if isinstance(values, dict) and values.get('points') is not None:
                    game_results[role] = _number(values['points'])
        event_row = {'event_id': event_id, 'aliases': aliases, 'league': league, 'teams': names,
                     'starts_at': _time(status.get('startsAt')), 'phase': phase,
                     'status': {key: status.get(key) for key in ('started', 'live', 'ended', 'completed', 'cancelled', 'delayed', 'finalized')},
                     'scores': scores, 'game_results': game_results,
                     'received_at': received_at}
        previous_starts = status.get('previousStartsAt')
        if isinstance(previous_starts, list) and 0 < len(previous_starts) <= 16:
            try:
                event_row['previous_starts_at'] = [_time(value) for value in previous_starts]
            except ValueError:
                # Optional provider schedule history is supporting evidence.
                pass
        event_links = bookmaker_event_links(event)
        if event_links:
            event_row['bookmaker_event_links'] = event_links
        events.append(event_row)
        for odd_id, odd in odds.items():
            if not isinstance(odd, dict):
                raise ValueError('odd shape')
            typ, side, entity = odd.get('betTypeID'), odd.get('sideID'), odd.get('statEntityID')
            if odd.get('periodID') != 'game' or odd.get('statID') != 'points' or typ not in MARKETS:
                continue
            if typ in ('ml', 'sp') and (side not in ('home', 'away') or entity != side):
                continue
            if typ == 'ou' and (side not in ('over', 'under') or entity != 'all'):
                continue
            if odd.get('oddID') != odd_id:
                raise ValueError('odd identity mismatch')
            _identity(odd_id)
            opposite = _identity(odd.get('opposingOddID'))
            by_book = odd.get('byBookmaker', {})
            if not isinstance(by_book, dict) or len(by_book) > MAX_BOOKS_PER_ODD:
                raise ValueError('book shape or limit')
            fair = _baseline(odd, typ, 'fair')
            consensus = _baseline(odd, typ, 'book') if any(key in odd for key in ('bookOdds', 'bookOddsAvailable', 'bookSpread', 'bookOverUnder')) else None
            for venue, book in by_book.items():
                _identity(venue)
                if venues is not None and venue not in venues:
                    ignored_bookmaker_groups += 1
                    continue
                if not isinstance(book, dict) or not isinstance(book.get('available'), bool):
                    raise ValueError('book availability')
                alternatives = book.get('altLines', [])
                if not isinstance(alternatives, list) or len(alternatives) > 100:
                    raise ValueError('alternate-line limit')
                alternate_rows += len(alternatives)
                book_quotes = {}
                conflicts = set()
                for index, entry in enumerate([book, *alternatives]):
                    if not isinstance(entry, dict) or not isinstance(entry.get('available'), bool):
                        raise ValueError('alternate availability')
                    price = line = source_at = None
                    reason = None
                    try:
                        if 'odds' in entry:
                            price = _price(entry['odds'])
                        if typ != 'ml' and ('spread' if typ == 'sp' else 'overUnder') in entry:
                            line = _number(entry['spread' if typ == 'sp' else 'overUnder'])
                        if entry.get('lastUpdatedAt') is not None:
                            source_at = _time(entry['lastUpdatedAt'])
                    except ValueError:
                        reason = 'invalid price, line or source clock'
                    if price is None or source_at is None or (typ != 'ml' and line is None):
                        reason = reason or 'missing price, line or source clock'
                    if not entry['available']:
                        reason = reason or 'provider unavailable'
                    if (status.get('cancelled') is True or status.get('ended') is True
                            or status.get('completed') is True or odd.get('cancelled') is True
                            or odd.get('ended') is True):
                        reason = reason or 'event or market ended'
                    market_link = _link_witness(entry.get('deeplink')) if venue in LINK_BOOKS else None
                    observation = {'event_id': event_id, 'league': league, 'phase': phase,
                                   'period': 'game', 'market': MARKETS[typ], 'side': side,
                                   'line': line, 'venue': venue, 'price_american': price,
                                   'source_at': source_at, 'received_at': received_at,
                                   'source_at_original': entry.get('lastUpdatedAt') if source_at else None,
                                   'received_at_original': receipt_original,
                                   'available': entry['available'] and reason is None,
                                   'provider_available': entry['available'], 'unavailable_reason': reason,
                                   'odd_id': odd_id, 'opposing_odd_id': opposite,
                                   'settlement': 'unverified', 'fair': fair.copy(),
                                   **({'bookmaker_market_link': market_link} if market_link else {}),
                                   **({'consensus': consensus.copy()} if consensus is not None else {})}
                    line_key = Decimal(line) if line is not None else None
                    previous = book_quotes.get(line_key)
                    if previous is None:
                        book_quotes[line_key] = observation
                    elif all(previous.get(key) == observation.get(key)
                             for key in (previous.keys() | observation.keys()) - {'line', 'alternate'}):
                        duplicate_alternate_rows += 1
                    else:
                        conflicts.add(line_key)
                        # Retain the latest actual clock, while refusing any
                        # price authority for contradictory same-line entries.
                        prior_at = previous['source_at']
                        if source_at is not None and (prior_at is None or
                                datetime.fromisoformat(source_at) > datetime.fromisoformat(prior_at)):
                            book_quotes[line_key] = observation
                    if index and book_quotes[line_key] is observation:
                        observation['alternate'] = True
                for line_key in conflicts:
                    book_quotes[line_key].update(available=False, unavailable_reason='conflicting observations at exact line')
                conflicting_alternate_lines += len(conflicts)
                quotes.extend(book_quotes.values())
    return Page(tuple(events), tuple(quotes), cursor, sha256(body).hexdigest(), len(body),
                alternate_rows, duplicate_alternate_rows, conflicting_alternate_lines, ignored_bookmaker_groups)


class Traversal:
    """Track a cursor walk; callers must separately establish stable absence."""
    def __init__(self, max_pages=100):
        if not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError('page limit')
        self.max_pages = max_pages
        self.next_cursor = None
        self.pages = []
        self.charged_objects = 0
        self._seen_cursors = set()
        self._seen_events = set()
        self.finished = False
        self.failed = False

    def add(self, cursor, page):
        if self.finished or self.failed or cursor != self.next_cursor or len(self.pages) >= self.max_pages:
            self.failed = True
            raise ValueError('cursor traversal')
        ids = {event['event_id'] for event in page.events}
        if ids & self._seen_events or (page.next_cursor is not None and page.next_cursor in self._seen_cursors):
            self.failed = True
            raise ValueError('moving or cyclic traversal')
        self._seen_events.update(ids)
        if cursor is not None:
            self._seen_cursors.add(cursor)
        if page.next_cursor == cursor and cursor is not None:
            self.failed = True
            raise ValueError('cyclic traversal')
        self.pages.append(page)
        self.next_cursor = page.next_cursor
        self.finished = page.next_cursor is None

    @property
    def complete(self):
        return self.finished and not self.failed

    @property
    def authoritative_absence(self):
        # A successful traversal can still miss events moving between pages.
        return False
