"""A bounded, price-only copy of recently served desk views."""
from collections import OrderedDict
from contextlib import closing
import json
import sqlite3
from threading import Lock

from app.diagnostics import failure
from app.storage.store import stamp


MAX_PAGES = 64
MAX_PAGE_BYTES = 512 * 1024
PAGE_FIELDS = (
    'basis', 'phase', 'features', 'row_kind', 'games', 'selected_venues', 'selected_game_key',
    'selected_line_id', 'total', 'offset', 'limit', 'page_count', 'browse_id', 'browse_order',
)
ROW_FIELDS = (
    'id', 'game_key', 'game_title', 'league', 'market', 'start_at', 'source_titles', 'game_source',
    'source_event', 'game_line_id', 'settlement_match', 'matrix_order',
)
QUOTE_FIELDS = (
    'id', 'desk_quote_key', 'venue', 'selection', 'participant', 'market', 'alternate', 'original',
    'odds', 'price_basis', 'source_provider', 'cost_per_normal_claim', 'source_clock_at',
    'received_at', 'confirmed_at', 'captured_at', 'native_side',
)


def fields(value, names):
    return {name: value[name] for name in names if name in value}


def retained_page(page):
    """Copy prices and provenance; calculation and availability proofs stay in SQL."""
    rows = []
    for row in page['rows']:
        if row.get('withdrawn') or not row.get('offers'):
            continue
        offers = [dict(fields(offer, QUOTE_FIELDS), current=False, posted_price=False,
                       value=None, reason='data_runtime_unhealthy') for offer in row['offers']]
        books = {book: [dict(fields(price, ('price_american', 'source_at')), current=False)
                        for price in prices] for book, prices in row.get('sportsbook_quotes', {}).items()}
        rows.append(dict(fields(row, ROW_FIELDS), offers=offers, sportsbook_quotes=books, score=None))
    return dict(fields(page, PAGE_FIELDS), rows=rows, last_known_at=page['publication']['read_at'])


class LastKnownDesk:
    """Load the local projection at startup so outage reads do not queue behind SQL."""

    def __init__(self, path=None):
        self.path = path
        self.lock = Lock()
        self.pages = OrderedDict()
        if path is not None and path.is_file():
            try:
                with closing(self.connect()) as db:
                    rows = db.execute('''SELECT key, observed, page FROM desk_page
                        WHERE length(page)<=? ORDER BY observed DESC LIMIT ?''', (MAX_PAGE_BYTES, MAX_PAGES))
                    for key, observed, payload in reversed(rows.fetchall()):
                        self.pages[key] = (observed, payload)
            except (OSError, sqlite3.Error) as exc:
                failure(__name__, 'load_last_known_desk', exc)

    def connect(self):
        return sqlite3.connect(self.path, timeout=0.1)

    def remember(self, key, page):
        if page.get('state') != 'ready' or not page.get('publication', {}).get('read_at'):
            return
        observed = stamp(page['publication']['read_at']).timestamp()
        payload = json.dumps(retained_page(page), separators=(',', ':')).encode()
        # An authoritative empty result replaces the previous view. An oversized
        # replacement also invalidates the old copy instead of reviving its quotes.
        if len(payload) > MAX_PAGE_BYTES:
            payload = b'null'
        with self.lock:
            before = self.pages.get(key)
            if before and before[0] >= observed:
                return
            self.pages[key] = (observed, payload)
            self.pages.move_to_end(key)
            if len(self.pages) > MAX_PAGES:
                self.pages.popitem(last=False)
        if self.path is not None:
            try:
                self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with closing(self.connect()) as db, db:
                    db.execute('''CREATE TABLE IF NOT EXISTS desk_page (
                        key TEXT PRIMARY KEY, observed REAL NOT NULL, page BLOB NOT NULL)''')
                    db.execute('''INSERT INTO desk_page VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET observed=excluded.observed, page=excluded.page
                        WHERE excluded.observed > desk_page.observed''', (key, observed, payload))
                    db.execute('''DELETE FROM desk_page WHERE key IN (
                        SELECT key FROM desk_page ORDER BY observed DESC LIMIT -1 OFFSET ?)''', (MAX_PAGES,))
            except (OSError, sqlite3.Error) as exc:
                failure(__name__, 'save_last_known_desk', exc)

    def read(self, key, at):
        with self.lock:
            saved = self.pages.get(key)
        if not saved:
            return None
        try:
            page = json.loads(saved[1])
            if not page or not page['rows']:
                return None
            if page.get('phase') == 'pregame':
                page['rows'] = [row for row in page['rows'] if stamp(row['start_at']) > at]
            if not page['rows']:
                return None
        except (ValueError, KeyError, TypeError) as exc:
            failure(__name__, 'read_last_known_desk', exc)
            return None
        count = sum(len(row['offers']) for row in page['rows'])
        return dict(page, state='ready', provider_requests=0, ranked_group_count=0,
                    matched_offer_count=count, retained_offer_count=count,
                    calculation_reason='Current prices are temporarily unavailable.',
                    publication=dict(read_at=page['last_known_at'], current_prices=0,
                                     retained_prices=count))
