"""Bounded SportsGameOdds page decoding and source-local observations.

This module does not dispatch requests or write current rows. A complete cursor
walk alone is not proof of absence: moving provider pages may omit events.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re

LEAGUES = frozenset(('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'))
MARKETS = {'ml': 'moneyline', 'sp': 'spread', 'ou': 'total'}
MAX_PAGE_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 100
MAX_ODDS_PER_EVENT = 20000
MAX_BOOKS_PER_ODD = 200


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


@dataclass(frozen=True)
class Page:
    events: tuple
    quotes: tuple
    next_cursor: str | None
    receipt_sha256: str | None = None


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
        names = {}
        for role in ('home', 'away'):
            try:
                team = teams[role]
                names[role] = {'id': _identity(team['teamID']), 'name': _identity(team['names']['long'])}
            except (KeyError, TypeError) as exc:
                raise ValueError('team identity') from exc
        if not isinstance(status.get('live'), bool) or not isinstance(status.get('started'), bool):
            raise ValueError('event phase unknown')
        phase = 'live' if status['live'] else 'started' if status['started'] else 'pregame'
        aliases = event.get('aliases', [])
        if not isinstance(aliases, list) or len(aliases) > 100:
            raise ValueError('event aliases')
        aliases = [_identity(alias) for alias in aliases]
        event_row = {'event_id': event_id, 'aliases': aliases, 'league': league, 'teams': names,
                     'starts_at': _time(status.get('startsAt')), 'phase': phase,
                     'status': {key: status.get(key) for key in ('started', 'live', 'ended', 'completed', 'cancelled', 'delayed')},
                     'received_at': received_at}
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
            fair = {'available': odd.get('fairOddsAvailable') is True, 'price_american': None,
                    'line': None, 'source_at': None}
            if fair['available']:
                try:
                    fair['price_american'] = _price(odd['fairOdds'])
                    if typ != 'ml':
                        fair['line'] = _number(odd['fairSpread' if typ == 'sp' else 'fairOverUnder'])
                except (KeyError, ValueError):
                    fair['available'] = False
            for venue, book in by_book.items():
                _identity(venue)
                if venues is not None and venue not in venues:
                    continue
                if not isinstance(book, dict) or not isinstance(book.get('available'), bool):
                    raise ValueError('book availability')
                alternatives = book.get('altLines', [])
                if not isinstance(alternatives, list) or len(alternatives) > 100:
                    raise ValueError('alternate-line limit')
                for entry in [book, *alternatives]:
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
                    if status.get('cancelled') is True or status.get('ended') is True or odd.get('cancelled') is True or odd.get('ended') is True:
                        reason = reason or 'event or market ended'
                    quotes.append({'event_id': event_id, 'league': league, 'phase': phase,
                                   'period': 'game', 'market': MARKETS[typ], 'side': side,
                                   'line': line, 'venue': venue, 'price_american': price,
                                   'source_at': source_at, 'received_at': received_at,
                                   'source_at_original': entry.get('lastUpdatedAt') if source_at else None,
                                   'received_at_original': receipt_original,
                                   'available': entry['available'] and reason is None,
                                   'provider_available': entry['available'], 'unavailable_reason': reason,
                                   'odd_id': odd_id, 'opposing_odd_id': opposite,
                                   'settlement': 'unverified', 'fair': fair.copy()})
    return Page(tuple(events), tuple(quotes), cursor, sha256(body).hexdigest())


class Traversal:
    """Track a cursor walk; callers must separately establish stable absence."""
    def __init__(self, max_pages=100):
        if not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError('page limit')
        self.max_pages = max_pages
        self.next_cursor = None
        self.pages = []
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
