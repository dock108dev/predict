"""ProphetX V4 ingestion with corroborated American prices and unsized quotes.

Contract sources and limitations: docs/slice-3.md. No order/account endpoints.
"""
import asyncio
import base64
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
import time
from urllib.parse import quote, urlsplit

import httpx
from app.adapters.base import ReadOnlyAdapter
from app.models.core import (BookSync, Depth, Event, EvidenceKind, Market, MarketState,
    MarketType, NativeRef, OrderBook, Outcome, OutcomeBook, Quantity, RawPayload,
    ReceiptFreshness, SettlementProfile, SourceTimeProgress, Venue, parse_decimal,
    reject_constant, Probability, Quote, QuoteSide)

BASES = {'sandbox': 'https://api.sandbox.prophetx.dev/partner',
         'production': 'https://cash.api.prophetx.co/partner'}
GET_PATHS = {'/mm/get_tournaments', '/mm/get_sport_events',
             '/v4/mm/get_multiple_markets', '/v4/mm/get_price_ladder',
             '/websocket/connection-config'}
POST_PATHS = {'/auth/login', '/auth/refresh', '/v4/mm/websocket'}


def decode(value):
    try:
        return json.loads(value, parse_float=Decimal, parse_constant=reject_constant)
    except (TypeError, ValueError):
        raise ValueError('invalid ProphetX JSON') from None


def obj(value):
    if not isinstance(value, dict):
        raise ValueError('expected object')
    return value


def rows(value):
    if not isinstance(value, list):
        raise ValueError('expected array')
    return value


def identity(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).strip():
        raise ValueError('missing native identity')
    return str(value)


def label(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('missing native label')
    return value


def scheduled(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('scheduled time requires timezone')
    return parsed


@dataclass(frozen=True)
class Response:
    body: str
    source: str
    received_at: datetime
    kind: EvidenceKind = EvidenceKind.OBSERVATION

    def raw(self, event_id, market_id=None):
        # Integer updated_at/timestamp scale is not declared by these schemas.
        # Retain original spelling; do not guess seconds/milliseconds/nanoseconds.
        return RawPayload(ref=NativeRef(venue=Venue.PROPHETX, event_id=identity(event_id),
            market_id=None if market_id is None else identity(market_id)),
            source=self.source, received_at=self.received_at, json_text=self.body,
            kind=self.kind)


@dataclass(frozen=True)
class NativeSelection:
    outcome_id: str
    strike_id: str
    name: str
    price: Decimal | None
    quantity: Quantity | None
    updated_at: int | None
    # American price is corroborated; quantity ownership/unit remains unresolved.
    price_unit: str = 'American_odds'


@dataclass(frozen=True, kw_only=True)
class ProphetXBook(OrderBook):
    """Shared interface image plus lossless native best-selection windows.

    Native reconstruction can qualify independently of economic normalization.
    A None window means no supplied window; () is an explicitly empty array.
    Zero-size/absent-price rows remain native placeholders, not executable levels.
    """
    native_windows: tuple[tuple[NativeSelection, ...], ...] | None = None
    native_sync: BookSync = BookSync.UNKNOWN
    native_depth: Depth = Depth.UNKNOWN
    native_status: str | None = None
    native_timestamp: int | None = None
    operation: str | None = None
    native_timestamp_progress: SourceTimeProgress = SourceTimeProgress.UNKNOWN
    normalized_quotes: tuple[Quote, ...] = ()


def integer_or_none(value):
    if value is not None and type(value) is not int:
        raise ValueError('expected integer source field')
    return value


def parse_windows(value):
    if value is None:
        return None
    result = []
    seen = set()
    for group in rows(value):
        levels = []
        group_id = None
        seen_prices = set()
        for row in rows(group):
            row = obj(row)
            oid, sid = identity(row.get('outcome_id')), identity(row.get('strike_id'))
            if group_id is not None and group_id != (oid, sid):
                raise ValueError('mixed native selection identities')
            group_id = (oid, sid)
            price = None if row.get('price') is None else parse_decimal(row['price'])
            qty = None if row.get('quantity') is None else Quantity(
                value=parse_decimal(row['quantity']), unit='unknown')
            if price is not None:
                if price in seen_prices:
                    raise ValueError('duplicate native price')
                seen_prices.add(price)
            levels.append(NativeSelection(oid, sid, label(row.get('name')), price,
                qty, integer_or_none(row.get('updated_at'))))
        if group_id is not None:
            if group_id in seen:
                raise ValueError('duplicate native selection group')
            seen.add(group_id)
        result.append(tuple(levels))
    return tuple(result)


def outcomes(windows):
    result = {}
    for group in windows or ():
        for row in group:
            # strike_id is the native tradable selection identity. outcome_id can
            # recur at multiple lines, so is retained separately on each row.
            result[row.strike_id] = Outcome(native_id=row.strike_id, label=row.name)
    return tuple(result.values())


def market_key(event_id, market):
    # Market IDs identify templates and recur across native strikes/events.
    strike = market.get('strike')
    if strike is None:
        strike_text = 'none'
    else:
        value = parse_decimal(strike)
        strike_text = format(value, 'f')
        if '.' in strike_text:
            strike_text = strike_text.rstrip('0').rstrip('.')
        if strike_text == '-0':
            strike_text = '0'
    return f'{identity(event_id)}:{identity(market.get("id"))}:{strike_text}'


def american_probability(value):
    value = parse_decimal(value)
    if value.copy_abs() < 100:
        raise ValueError('invalid American odds')
    with localcontext() as context:
        context.prec = max(50, len(value.as_tuple().digits) + 20)
        return Probability(value=(Decimal(100) / (value + 100) if value > 0
                                  else -value / (-value + 100)))


def market_state(value):
    # 'active' is corroborated on the matched sandbox REST/UI listing.
    # Other values remain unknown until a market-specific source establishes them.
    return MarketState.ACTIVE if value == 'active' else MarketState.UNKNOWN


def book(response, event_id, market, *, streaming=False, operation=None, native_timestamp=None):
    mid = market_key(event_id, market)
    windows = parse_windows(market.get('selections'))
    status = market.get('status')
    if status is not None:
        label(status)
    # Map only the market state corroborated against the sandbox listing.
    # Never borrow order-status enums or inherit status across selection images.
    if streaming and windows is not None and (len(windows) != 2 or any(len(x) > 10 for x in windows)):
        raise ValueError("unexpected advertised window shape")
    native_sync = BookSync.SYNCHRONIZED if windows is not None else BookSync.UNKNOWN
    if operation == 'd':
        windows, native_sync = None, BookSync.UNSYNCHRONIZED
    raw = response.raw(event_id, mid)
    state = market_state(status)
    quotes = []
    for group in windows or ():
        available = [x for x in group if x.price is not None and x.quantity is not None and x.quantity.value > 0]
        if available:
            best = min(available, key=lambda x: american_probability(x.price).value)
            quotes.append(Quote(raw=raw, outcome_id=best.strike_id,
                ask=QuoteSide(price=american_probability(best.price)), state=state))
    return ProphetXBook(raw=raw, quantity_unit='unknown', state=state, normalized_quotes=tuple(quotes),
        outcomes=tuple(OutcomeBook(outcome_id=x.native_id) for x in outcomes(windows)),
        native_windows=windows, native_sync=native_sync,
        native_depth=Depth.PARTIAL if streaming else Depth.UNKNOWN,
        native_status=status, native_timestamp=integer_or_none(native_timestamp),
        operation=operation, sequence=None if market.get('sequence_number') is None
        else identity(market['sequence_number']), receipt_freshness=ReceiptFreshness.RECENT,
        source_time_progress=SourceTimeProgress.MISSING)


class APIError(RuntimeError):
    def __init__(self, status=None):
        self.status = status
        super().__init__('ProphetX request failed' + (f' (HTTP {status})' if status else ''))


@dataclass(repr=False)
class Credentials:
    environment: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)

    def __post_init__(self):
        if self.environment not in BASES or not self.access_key or not self.secret_key:
            raise ValueError('invalid environment-scoped credentials')


class Client:
    """Finite, allowlisted HTTP transport. Secrets and server errors never logged."""
    def __init__(self, credentials, *, http=None, request_budget=20, retries=2,
                 timeout=10, byte_budget=5_000_000, sleep=asyncio.sleep, clock=time.monotonic, observer=None):
        if request_budget < 1 or retries < 0 or timeout <= 0 or byte_budget < 1:
            raise ValueError('invalid request budget')
        self.credentials = credentials
        self.base = BASES[credentials.environment]
        self.http = http or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        self.timeout, self.remaining, self.retries = timeout, request_budget, retries
        self.bytes_remaining = byte_budget
        self.sleep, self.clock = sleep, clock
        self.access = self.refresh = None
        self.expires = self.refresh_expires = 0
        self.closed = False
        self.lock = asyncio.Lock()
        self.diagnostics = []
        self.observer = observer

    async def _wire(self, method, path, *, params=None, data=None, token=None):
        if path not in (GET_PATHS if method == 'GET' else POST_PATHS if method == 'POST' else set()):
            raise ValueError('endpoint is outside read-only allowlist')
        for attempt in range(self.retries + 1):
            if self.closed or self.remaining <= 0:
                raise APIError()
            self.remaining -= 1
            status, retry_after = None, None
            try:
                async with asyncio.timeout(self.timeout):
                    async with self.http.stream(method, self.base + path, params=params,
                            json=data, headers={} if token is None else {'Authorization': 'Bearer ' + token}) as r:
                        status = r.status_code
                        retry_after = r.headers.get('Retry-After')
                        chunks = []
                        async for chunk in r.aiter_bytes():
                            self.bytes_remaining -= len(chunk)
                            if self.bytes_remaining < 0:
                                raise APIError()
                            chunks.append(chunk)
                        body = b''.join(chunks).decode('utf-8')
                self.diagnostics.append({'path': path, 'status': status})
                if status == 200:
                    result = Response(body, str(r.request.url), datetime.now(timezone.utc))
                    if path in GET_PATHS - {'/websocket/connection-config'} and any(secret and secret in body for secret in (self.credentials.access_key,self.credentials.secret_key,self.access,self.refresh)):
                        raise APIError()
                    if self.observer and path in GET_PATHS - {'/websocket/connection-config'}:
                        self.observer(result)
                    return result
                if status != 429 and not 500 <= status <= 599:
                    raise APIError(status)
            except (httpx.TransportError, TimeoutError, UnicodeError):
                self.diagnostics.append({'path': path, 'status': None})
            if attempt == self.retries:
                raise APIError(status) from None
            delay = min(2 ** attempt, 8)
            if retry_after is not None:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    try:
                        delay = max(delay, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError):
                        raise APIError(status) from None
                if not 0 <= delay <= 30:
                    raise APIError(status)
            await self.sleep(delay)
        raise APIError()

    async def authenticate(self, force=False):
        async with self.lock:
            if not force and self.access and self.clock() < self.expires:
                return
            if self.refresh and self.clock() < self.refresh_expires:
                try:
                    r = await self._wire('POST', '/auth/refresh', data={'refresh_token': self.refresh})
                except APIError as exc:
                    if exc.status not in (400, 401, 403):
                        raise
                    self.refresh = None
            if not self.refresh or self.clock() >= self.refresh_expires:
                r = await self._wire('POST', '/auth/login', data={
                    'access_key': self.credentials.access_key, 'secret_key': self.credentials.secret_key})
                self.refresh = None
            try:
                session = obj(obj(decode(r.body))['data'])
                access = label(session.get('access_token'))
                refresh = session.get('refresh_token', self.refresh)
                if refresh is not None:
                    label(refresh)
            except (ValueError, KeyError):
                raise APIError() from None
            self.access, self.refresh = access, refresh
            # Guide says 20 min, refresh reference says 10. Fields have no stated
            # epoch/unit contract. Renew after 5 min; re-login after at most 1 day.
            self.expires = self.clock() + 300
            if 'refresh_token' in session:
                self.refresh_expires = self.clock() + 86400

    async def request(self, method, path, **kwargs):
        if path not in GET_PATHS | {'/v4/mm/websocket'}:
            raise ValueError('not a market-data endpoint')
        await self.authenticate()
        try:
            return await self._wire(method, path, token=self.access, **kwargs)
        except APIError as exc:
            if exc.status != 401:
                raise
        await self.authenticate(force=True)
        return await self._wire(method, path, token=self.access, **kwargs)

    async def aclose(self):
        if not self.closed:
            self.closed = True
            self.access = self.refresh = None
            await self.http.aclose()


class ProphetXAdapter(ReadOnlyAdapter):
    venue = Venue.PROPHETX

    def __init__(self, client, *, tournament_ids=(), connector=None):
        self.client = client
        self.tournament_ids = tuple(identity(x) for x in tournament_ids)
        self.connector = connector
        self.markets = {}
        self.native_books = {}
        self.tournaments = ()
        self.price_ladder = None
        self.stream = None

    async def discover_tournaments(self):
        r = await self.client.request('GET', '/mm/get_tournaments')
        self.tournaments = tuple(rows(obj(obj(decode(r.body))['data'])['tournaments']))
        self.tournament_response = r
        return self.tournaments

    async def discover_price_ladder(self):
        r = await self.client.request('GET', '/v4/mm/get_price_ladder')
        values = tuple(parse_decimal(x) for x in rows(obj(decode(r.body))['data']))
        self.price_ladder = (values, r)
        return values

    async def discover_events(self):
        if not self.tournament_ids:
            raise ValueError('choose tournament IDs from discovery before event requests')
        result = []
        for tid in self.tournament_ids:
            r = await self.client.request('GET', '/mm/get_sport_events', params={'tournament_id': tid})
            for row in rows(obj(obj(decode(r.body))['data'])['sport_events']):
                row = obj(row)
                result.append(Event(raw=r.raw(row.get('event_id')), title=label(row.get('name')),
                    participants=tuple(label(obj(x).get('name')) for x in rows(row.get('competitors', []))),
                    sport=row.get('sport_name'), league=row.get('tournament_name'),
                    scheduled_start=scheduled(row.get('scheduled'))))
        return tuple(result)

    async def discover_markets(self, event_id=None):
        if event_id is None:
            raise ValueError('choose one discovered event for bounded discovery')
        eid = identity(event_id)
        r = await self.client.request('GET', '/v4/mm/get_multiple_markets', params={'event_ids': eid})
        result = []
        staged_markets, staged_books = {}, {}
        def visit(items):
            for row in rows(items):
                row = obj(row)
                if row.get('market_strikes'):
                    visit(row['market_strikes'])
                    continue
                mid = market_key(eid, row)
                raw = r.raw(eid, mid)
                obs = book(r, eid, row)
                market = Market(raw=raw, title=label(row.get('name')), outcomes=outcomes(obs.native_windows),
                    market_type=MarketType.MONEYLINE if row.get('type') == 'moneyline' else MarketType.UNKNOWN,
                    state=market_state(row.get('status')), period={'moneyline':'full_game','first_half_moneyline':'first_half'}.get(row.get('sub_type')))
                result.append(market)
                if mid in staged_markets:
                    raise ValueError("duplicate native market identity")
                staged_markets[mid] = (eid, market, row)
                staged_books[mid] = obs
        visit(obj(obj(decode(r.body))['data'])[eid])
        self.markets.update(staged_markets)
        self.native_books.update(staged_books)
        return tuple(result)

    async def get_snapshot(self, market_id):
        if market_id not in self.markets:
            raise LookupError(market_id)
        eid = self.markets[market_id][0]
        current = await self.discover_markets(eid)
        if market_id not in {x.raw.ref.market_id for x in current}:
            self.native_books.pop(market_id, None)
            self.markets.pop(market_id, None)
            raise LookupError(market_id)
        return self.native_books[market_id]

    async def get_market_rules(self, market_id):
        if market_id not in self.markets:
            raise LookupError(market_id)
        _, market, row = self.markets[market_id]
        return SettlementProfile(raw=market.raw, rules_text=row.get('description'))

    async def get_quotes(self, market_id):
        return (await self.get_snapshot(market_id)).normalized_quotes

    def stream_markets(self, market_ids):
        from app.adapters.prophetx_stream import Stream
        if self.stream is not None:
            raise ValueError('one stream per adapter')
        self.stream = Stream(self, tuple(market_ids), connector=self.connector)
        return self.stream.updates()

    async def aclose(self):
        if self.stream:
            await self.stream.aclose()
        await self.client.aclose()
