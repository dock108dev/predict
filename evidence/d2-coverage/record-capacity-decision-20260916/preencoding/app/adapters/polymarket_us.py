"""Bounded US retail REST ingestion. No account discovery or order functionality."""
import asyncio
from contextlib import aclosing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
import json
import re
from functools import lru_cache
from copy import deepcopy
from urllib.parse import quote, urlencode

import httpx
from app.adapters.base import ReadOnlyAdapter
from app.models.core import (BookLevel, BookSync, Depth, Event, EvidenceKind, Ladder,
    Market, MarketState, MarketType, NativeRef, OrderBook, Outcome, OutcomeBook,
    Probability, Quantity, Quote, QuoteSide, RawPayload, SettlementProfile, Venue,
    parse_decimal, reject_constant)

GATEWAY = 'https://gateway.polymarket.us'

def decode(body):
    try:
        result = json.loads(body, parse_float=Decimal, parse_constant=reject_constant)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid JSON') from exc
    if not isinstance(result, dict):
        raise ValueError('expected object')
    return result


def identifier(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError('missing native identity')
    return str(value)


def timestamp(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('timestamp must be RFC3339 text')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('timestamp needs timezone')
    return result


def source_time_value(value):
    """Exact (UTC seconds, fraction) ordering key, independent of Decimal context."""
    if value is None:
        return None
    parsed = timestamp(value)
    match = re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d+))?(?:Z|[+-]\d{2}:\d{2})", value)
    if match is None:
        raise ValueError('source timestamp must be RFC3339')
    whole = parsed.replace(microsecond=0) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    # Decimal addition rounds under the caller's precision; tuple comparison does
    # not. Keep the fractional text exact even for a low-precision caller.
    return whole.days * 86400 + whole.seconds, Decimal('0.' + (match[1] or '0'))


def state(value):
    # Explicit aliases only: no boolean-active fallback that could hide a halt.
    aliases = {'OPEN': MarketState.ACTIVE, 'PREOPEN': MarketState.PREOPEN,
               'SUSPENDED': MarketState.SUSPENDED, 'HALTED': MarketState.SUSPENDED,
               'EXPIRED': MarketState.CLOSED, 'TERMINATED': MarketState.CLOSED}
    for prefix in ('MARKET_STATE_', 'MARKET_STATUS_'):
        if isinstance(value, str) and value.startswith(prefix):
            return aliases.get(value[len(prefix):], MarketState.UNKNOWN)
    return aliases.get(value, MarketState.UNKNOWN) if isinstance(value, str) else MarketState.UNKNOWN


@dataclass(frozen=True)
class Response:
    body: str
    source: str
    received_at: datetime
    kind: EvidenceKind = EvidenceKind.OBSERVATION
    http_status: int | None = None
    http_headers: tuple[tuple[str, str], ...] = ()

    def raw(self, event_id, market_id=None, exchange_at=None):
        return RawPayload(ref=NativeRef(venue=Venue.POLYMARKET_US,
            event_id=identifier(event_id), market_id=market_id), source=self.source,
            received_at=self.received_at, exchange_at=timestamp(exchange_at),
            json_text=self.body, kind=self.kind)


def side_ids(market):
    if not isinstance(market, dict):
        raise ValueError('market must be an object')
    sides = market.get('marketSides', [])
    if not isinstance(sides, list):
        raise ValueError('invalid marketSides')
    result = {}
    for side in sides:
        if not isinstance(side, dict) or type(side.get('long')) is not bool:
            raise ValueError('native long/short flag unavailable')
        role = side['long']
        if role in result:
            raise ValueError('ambiguous long/short mapping')
        result[role] = identifier(side.get('id'))
    if len(set(result.values())) != len(result):
        raise ValueError('duplicate side identity')
    return result


def parse_market(response, data, event_id):
    side_ids(data)
    return Market(raw=response.raw(event_id, identifier(data.get('id'))),
        title=data.get('question') or data.get('title'),
        outcomes=tuple(Outcome(native_id=identifier(s.get('id')), label=s.get('description')
                       or s.get('team', {}).get('name') or identifier(s.get('id')))
                       for s in data.get('marketSides', [])),
        market_type=MarketType.MONEYLINE if data.get('marketType') == 'moneyline' or
            data.get('sportsMarketTypeV2') == 'SPORTS_MARKET_TYPE_MONEYLINE' else MarketType.UNKNOWN,
        state=state(data.get('status', data.get('ep3Status'))))


def parse_event(response, data, league='nfl'):
    """Shared native event conversion for live adapters and offline inventory."""
    return Event(raw=response.raw(identifier(data.get('id'))), title=data.get('title'),
                 league=league, scheduled_start=timestamp(data.get('startTime')))


def price(amount):
    if not isinstance(amount, dict) or amount.get('currency') != 'USD':
        raise ValueError('expected explicit USD price')
    # US contracts pay $1; USD price is the payout fraction. No complement arithmetic.
    return Probability(value=parse_decimal(amount.get('value')))


def parse_book(response, data, market, *, stream=False):
    if not isinstance(data, dict):
        raise ValueError('book must be an object')
    native = market.raw.ref
    source_market = next_market_data(market)
    if data.get('marketSlug') != source_market['slug']:
        raise ValueError('book slug mismatch')
    ids = side_ids(source_market)
    if True not in ids:
        raise ValueError('long side identity unavailable')
    def ladder(name, reverse):
        rows = data.get(name)
        if rows is None:
            return None
        if not isinstance(rows, list):
            raise ValueError('invalid ladder')
        if any(not isinstance(row, dict) or 'px' not in row or 'qty' not in row for row in rows):
            raise ValueError('invalid book level')
        levels = []
        seen = set()
        for row in rows:
            px = price(row['px'])
            qty = Quantity(value=parse_decimal(row['qty']), unit='contracts')
            if px.value in seen:
                raise ValueError('duplicate price in image')
            seen.add(px.value)
            if qty.value == 0 and stream:
                # Total available quantity is zero; retain raw, not a usable level.
                continue
            levels.append(BookLevel(price=px, quantity=qty))
        return Ladder(levels=tuple(sorted(levels, key=lambda v: v.price.value, reverse=reverse)),
                      depth=Depth.PARTIAL if stream else Depth.UNKNOWN)
    long = OutcomeBook(outcome_id=ids[True], bids=ladder('bids', True), asks=ladder('offers', False))
    outcomes = (long,) + ((OutcomeBook(outcome_id=ids[False]),) if False in ids else ())
    return OrderBook(raw=response.raw(native.event_id, native.market_id, data.get('transactTime')),
        quantity_unit='contracts', outcomes=outcomes, state=state(data.get('state')),
        sync=BookSync.UNKNOWN)


@lru_cache(maxsize=2)
def _market_index(body):
    data = decode(body)
    if 'market' in data:
        candidates = [data['market']]
    elif 'markets' in data:
        candidates = data['markets']
    else:
        candidates = [m for e in data.get('events', []) for m in e.get('markets', [])]
    return {identifier(m.get('id')): m for m in candidates}


def next_market_data(market):
    """Copy just the native object; full original response remains immutable."""
    return deepcopy(_market_index(market.raw.json_text)[market.raw.ref.market_id])


def parse_bbo(response, data, market):
    if not isinstance(data, dict):
        raise ValueError('BBO must be an object')
    source = next_market_data(market)
    if data.get('marketSlug') != source['slug']:
        raise ValueError('BBO slug mismatch')
    ids = side_ids(source)
    if True not in ids:
        raise ValueError('long side identity unavailable')
    return Quote(raw=response.raw(market.raw.ref.event_id, market.raw.ref.market_id,
                                 data.get('transactTime')), outcome_id=ids[True],
        bid=QuoteSide(price=price(data['bestBid'])) if data.get('bestBid') is not None else None,
        ask=QuoteSide(price=price(data['bestAsk'])) if data.get('bestAsk') is not None else None,
        state=state(data.get('state')))


class PolymarketUSAdapter(ReadOnlyAdapter):
    """Owns its client, including an injected client. Defaults to bounded NFL discovery.

    Market calls require a discovered native event relationship; unknown IDs fail
    locally. Full original page responses are retained on every derived observation.
    """
    venue = Venue.POLYMARKET_US

    def __init__(self, *, client=None, max_pages=2, page_size=5, request_cap=20,
                 attempts=3, timeout=10.0, sleep=asyncio.sleep, stream_factory=None,
                 stream_options=None):
        for value, ceiling in ((max_pages, 10), (page_size, 100), (request_cap, 100), (attempts, 5)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError('invalid request bound')
        if not 0 < timeout <= 60:
            raise ValueError('invalid timeout')
        self.client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False)
        self.max_pages, self.page_size, self.request_cap = max_pages, page_size, request_cap
        self.attempts, self.timeout, self.sleep = attempts, timeout, sleep
        self.requests = 0
        self.closed = False
        self.responses = []
        self.markets = {}
        self.events = {}
        self.stream_factory, self.stream_options = stream_factory, stream_options or {}
        self.streams = set()
        self.discovery_truncated = False

    async def _get(self, path, params=None):
        if self.closed:
            raise RuntimeError('adapter closed')
        url = GATEWAY + path + ('?' + urlencode(params, doseq=True) if params else '')
        for attempt in range(self.attempts):
            if self.requests >= self.request_cap:
                raise RuntimeError('REST request cap exhausted')
            self.requests += 1
            try:
                # Total attempt timeout also bounds a peer sending a trickle of bytes.
                async with asyncio.timeout(self.timeout):
                    r = await self.client.get(url, timeout=self.timeout)
                receipt = datetime.now(timezone.utc)
                try:
                    status, body = r.status_code, r.text
                    retry_after = r.headers.get('Retry-After')
                    public_headers = tuple((key, r.headers[key]) for key in
                        ('date', 'age', 'cache-control', 'etag', 'last-modified',
                         'cf-cache-status', 'x-cache', 'expires', 'retry-after') if key in r.headers)
                finally:
                    await r.aclose()
                result = Response(body, url, receipt, http_status=status, http_headers=public_headers)
                self.responses.append(result)
                if status == 404:
                    raise LookupError(path)
                if status == 429 or status in (500, 502, 503, 504):
                    if attempt + 1 == self.attempts:
                        raise RuntimeError(f'HTTP {status}: bounded retry exhaustion')
                    delay = max(1.0, 2.0 ** attempt)
                    if retry_after:
                        try:
                            requested = float(retry_after)
                        except ValueError:
                            try:
                                requested = (parsedate_to_datetime(retry_after) - receipt).total_seconds()
                            except (ValueError, TypeError):
                                requested = delay
                        if requested > 30:
                            raise RuntimeError('Retry-After exceeds bounded wait; stopped')
                        delay = max(delay, requested)
                    await self.sleep(delay)
                    continue
                if status != 200:
                    raise RuntimeError(f'HTTP {status}; no retry')
                decode(body)
                return result
            except (httpx.TransportError, TimeoutError):
                if attempt + 1 == self.attempts:
                    raise RuntimeError('bounded transport retry exhaustion') from None
                await self.sleep(2.0 ** attempt)
        raise AssertionError('unreachable')

    async def discover_events(self, *, league='nfl', filters=None):
        filters = dict(filters or {})
        allowed = {'type', 'section', 'excludeEventId'} if league else {'active', 'closed', 'slug', 'id'}
        if set(filters) - allowed:
            raise ValueError('unsupported event filter')
        filters = {k: str(v).lower() if type(v) is bool else v for k, v in filters.items()}
        path = f'/v2/leagues/{quote(identifier(league), safe="")}/events' if league else '/v1/events'
        found = {}
        self.discovery_truncated = False
        for page in range(self.max_pages):
            response = await self._get(path, {**filters, 'limit': self.page_size, 'offset': page * self.page_size})
            rows = decode(response.body).get('events')
            if not isinstance(rows, list):
                raise ValueError('events unavailable')
            for e in rows:
                if not isinstance(e, dict):
                    raise ValueError('invalid event')
                event_id = identifier(e.get('id'))
                event = parse_event(response, e, league)
                found[event_id] = event
                self.events[event_id] = event
                embedded = e.get('markets')
                if embedded is None:
                    embedded = []
                if not isinstance(embedded, list):
                    raise ValueError('invalid embedded markets')
                for m in embedded:
                    market = parse_market(response, m, event_id)
                    self.markets[market.raw.ref.market_id] = market
            if len(rows) < self.page_size:
                break
        else:
            self.discovery_truncated = True
        return tuple(found.values())

    async def discover_markets(self, event_id=None, *, filters=None):
        if self.closed:
            raise RuntimeError('adapter closed')
        if not self.events:
            await self.discover_events()
        if event_id is not None and event_id not in self.events:
            raise LookupError(event_id)
        candidates = tuple(m for m in self.markets.values() if event_id is None or m.raw.ref.event_id == event_id)
        if filters is None:
            return candidates
        filters = dict(filters)
        if set(filters) - {'active', 'closed', 'sportsMarketTypes', 'slug'}:
            raise ValueError('unsupported market filter')
        # Event relationship is established by discovery, never guessed from a slug.
        slugs = [next_market_data(m)['slug'] for m in candidates]
        if 'slug' in filters:
            requested = filters.pop('slug')
            requested = [requested] if isinstance(requested, str) else requested
            slugs = [s for s in slugs if s in requested]
        if not slugs:
            return ()
        filters = {k: str(v).lower() if type(v) is bool else v for k, v in filters.items()}
        by_id = {m.raw.ref.market_id: m for m in candidates}
        found = {}
        self.discovery_truncated = False
        for page in range(self.max_pages):
            response = await self._get('/v1/markets', {**filters, 'slug': slugs,
                'limit': self.page_size, 'offset': page * self.page_size})
            rows = decode(response.body).get('markets')
            if not isinstance(rows, list):
                raise ValueError('markets unavailable')
            for m in rows:
                if not isinstance(m, dict):
                    raise ValueError('invalid market')
                mid = identifier(m.get('id'))
                if mid not in by_id or m.get('slug') != next_market_data(by_id[mid])['slug']:
                    raise ValueError('unrequested market identity')
                found[mid] = parse_market(response, m, by_id[mid].raw.ref.event_id)
            if len(rows) < self.page_size:
                break
        else:
            self.discovery_truncated = True
        self.markets.update(found)
        return tuple(found.values())

    def _market(self, market_id):
        if self.closed:
            raise RuntimeError('adapter closed')
        if market_id not in self.markets:
            raise LookupError('discover the native event/market relationship first')
        return self.markets[market_id]

    async def get_market(self, market_id):
        previous = self._market(market_id)
        slug = next_market_data(previous)['slug']
        response = await self._get('/v1/market/slug/' + quote(slug, safe=''))
        data = decode(response.body).get('market')
        if not isinstance(data, dict) or identifier(data.get('id')) != market_id or data.get('slug') != slug:
            raise ValueError('market identity mismatch')
        result = parse_market(response, data, previous.raw.ref.event_id)
        self.markets[market_id] = result
        return result

    async def get_snapshot(self, market_id):
        market = self._market(market_id)
        response = await self._get('/v1/markets/' + quote(next_market_data(market)['slug'], safe='') + '/book')
        return parse_book(response, decode(response.body).get('marketData', {}), market)

    async def get_bbo(self, market_id):
        market = self._market(market_id)
        response = await self._get('/v1/markets/' + quote(next_market_data(market)['slug'], safe='') + '/bbo')
        return parse_bbo(response, decode(response.body).get('marketData', {}), market)

    async def get_market_rules(self, market_id):
        market = await self.get_market(market_id)
        data = next_market_data(market)
        return SettlementProfile(raw=market.raw, rules_text=data.get('description') or None,
                                 official_source=market.raw.source)

    async def get_settlement_metadata(self, market_id):
        market = self._market(market_id)
        response = await self._get('/v1/markets/' + quote(next_market_data(market)['slug'], safe='') + '/settlement')
        return response.raw(market.raw.ref.event_id, market_id)

    async def stream_markets(self, market_ids):
        from app.adapters.polymarket_us_stream import MarketStream
        if self.stream_factory is None:
            raise RuntimeError('explicit runtime stream transport required')
        if not isinstance(market_ids, tuple) or not market_ids or len(set(market_ids)) != len(market_ids):
            raise ValueError('nonempty unique market tuple required')
        stream = MarketStream([self._market(mid) for mid in market_ids], self.stream_factory, **self.stream_options)
        self.streams.add(stream)
        try:
            async with aclosing(stream.run()) as observations:
                async for observation in observations:
                    yield observation
        finally:
            await stream.aclose()
            self.streams.discard(stream)

    async def aclose(self):
        if not self.closed:
            self.closed = True
            for stream in tuple(self.streams):
                await stream.aclose()
            await self.client.aclose()
