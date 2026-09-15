"""Bounded Kalshi market data. Native books contain bids; quotes derive asks.

No matching, fee calculation, account enumeration or trading endpoints.
"""
import asyncio
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
from urllib.parse import quote

import httpx
from app.adapters.base import ReadOnlyAdapter
from app.models.core import (BookLevel, BookSync, Depth, Event, EvidenceKind, Ladder,
    Market, MarketState, MarketType, NativeRef, OrderBook, Outcome, OutcomeBook,
    Probability, Quantity, Quote, QuoteSide, RawPayload, ReceiptFreshness,
    SettlementProfile, SourceTimeProgress, Venue, parse_decimal, reject_constant)

REST_URL = 'https://external-api.kalshi.com/trade-api/v2'
SPORT_SERIES = {'KXNFLGAME': ('football', 'NFL', 'football_game'),
                'KXMLBGAME': ('baseball', 'MLB', 'baseball_game')}


def decode(body):
    value = json.loads(body, parse_float=Decimal, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')
    return value


def timestamp(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('timestamp must be RFC3339 text')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('timezone required')
    return result


def identity(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('native identity missing')
    return value


def state(value):
    return {'initialized': MarketState.PREOPEN, 'active': MarketState.ACTIVE,
            'inactive': MarketState.SUSPENDED, 'closed': MarketState.CLOSED,
            'determined': MarketState.CLOSED, 'disputed': MarketState.CLOSED,
            'amended': MarketState.CLOSED, 'finalized': MarketState.SETTLED}.get(value, MarketState.UNKNOWN)


@dataclass(frozen=True)
class Response:
    body: str
    source: str
    received_at: datetime
    kind: EvidenceKind = EvidenceKind.OBSERVATION

    def raw(self, event_id, market_id=None, exchange_at=None):
        return RawPayload(ref=NativeRef(venue=Venue.KALSHI, event_id=identity(event_id),
            market_id=market_id), source=self.source, received_at=self.received_at,
            exchange_at=exchange_at, json_text=self.body, kind=self.kind)


def parse_market(response, data, event_id, series_id):
    if data.get('event_ticker') != event_id:
        raise ValueError('event identity mismatch')
    return Market(raw=response.raw(event_id, identity(data.get('ticker'))),
        title=data['title'], outcomes=(Outcome(native_id='yes', label=data.get('yes_sub_title') or 'YES'),
                                     Outcome(native_id='no', label=data.get('no_sub_title') or 'NO')),
        market_type=MarketType.MONEYLINE if series_id in SPORT_SERIES else MarketType.UNKNOWN,
        state=state(data.get('status')))


def levels(rows):
    if rows is None:
        return None
    if not isinstance(rows, list):
        raise ValueError('invalid book side')
    result = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError('invalid price level')
        price, size = parse_decimal(row[0]), parse_decimal(row[1])
        Probability(value=price)
        if size <= 0 or price in result:
            raise ValueError('nonpositive or duplicate snapshot level')
        result[price] = size
    return result


def book_from_levels(raw, sides, *, depth=Depth.UNKNOWN, sync=BookSync.UNKNOWN,
                     sequence=None, market_state=MarketState.UNKNOWN,
                     source_progress=SourceTimeProgress.MISSING):
    def ladder(side):
        rows = sides[side]
        if rows is None:
            return None
        return Ladder(depth=depth, levels=tuple(BookLevel(price=Probability(value=p),
            quantity=Quantity(value=q, unit='contracts')) for p, q in sorted(rows.items(), reverse=True)))
    return OrderBook(raw=raw, quantity_unit='contracts', outcomes=tuple(
        OutcomeBook(outcome_id=s, bids=ladder(s)) for s in ('yes', 'no')),
        state=market_state, sync=sync, sequence=sequence,
        receipt_freshness=ReceiptFreshness.UNKNOWN, source_time_progress=source_progress)


def parse_book(response, market, *, depth=20):
    data = decode(response.body).get('orderbook_fp')
    if not isinstance(data, dict):
        raise ValueError('fixed-point orderbook unavailable')
    sides = {s: levels(data.get(s + '_dollars')) for s in ('yes', 'no')}
    return book_from_levels(response.raw(market.raw.ref.event_id, market.raw.ref.market_id), sides,
        depth=Depth.PARTIAL if depth else Depth.FULL,
        sync=BookSync.SYNCHRONIZED if all(v is not None for v in sides.values()) else BookSync.UNSYNCHRONIZED)


def quotes(book):
    """Bid directly observed; ask = 1 - opposite bid with identical contracts.

    raw.source explicitly identifies the derivation; raw JSON remains source evidence.
    Native OrderBook asks remain None per the shared native-book contract.
    """
    from dataclasses import replace
    outcomes = {o.outcome_id: o for o in book.outcomes}
    result = []
    for side, opposite in (('yes', 'no'), ('no', 'yes')):
        own, other = outcomes[side].bids, outcomes[opposite].bids
        bid = QuoteSide(price=own.levels[0].price, quantity=own.levels[0].quantity) if own and own.levels else None
        ask = None
        if other and other.levels:
            p = other.levels[0].price.value
            with localcontext() as ctx:
                ctx.prec = max(34, len(p.as_tuple().digits) + abs(p.as_tuple().exponent) + 2)
                ask = QuoteSide(price=Probability(value=Decimal(1) - p), quantity=other.levels[0].quantity)
        result.append(Quote(raw=replace(book.raw, source=book.raw.source +
            f'#quote:{side}:bid=native;ask=1-{opposite}-bid;ask_quantity={opposite}-bid-contracts'),
            outcome_id=side, bid=bid, ask=ask, state=book.state))
    return tuple(result)


class KalshiAdapter(ReadOnlyAdapter):
    venue = Venue.KALSHI

    def __init__(self, *, client=None, series=('KXNFLGAME', 'KXMLBGAME'), max_pages=2,
                 page_size=20, max_requests=40, retries=1, depth=20, pregame_only=True,
                 now=None, sleep=asyncio.sleep, stream_factory=None, stream_options=None):
        for value, maximum in ((max_pages, 10), (page_size, 200), (max_requests, 200)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('invalid request bound')
        if type(retries) is not int or not 0 <= retries <= 3 or type(depth) is not int or not 0 <= depth <= 100:
            raise ValueError('invalid retry/depth bound')
        if not series or len(set(series)) != len(series) or any(s not in SPORT_SERIES for s in series):
            raise ValueError('explicit supported sports series required')
        self.client = client or httpx.AsyncClient(timeout=10, follow_redirects=False)
        self.series, self.max_pages, self.page_size = series, max_pages, page_size
        self.max_requests, self.retries, self.depth = max_requests, retries, depth
        self.pregame_only, self.now = pregame_only, now or (lambda: datetime.now(timezone.utc))
        self.sleep, self.stream_factory, self.stream_options = sleep, stream_factory, stream_options or {}
        self.requests = 0
        self.closed = False
        self.events, self.markets, self.event_series, self.series_metadata = {}, {}, {}, {}
        self.market_metadata, self.schedule_evidence, self.discovery_truncated = {}, {}, {}
        self.responses, self.streams = [], set()

    async def _get(self, path, params=None):
        if self.closed:
            raise RuntimeError('adapter closed')
        for attempt in range(self.retries + 1):
            if self.requests >= self.max_requests:
                raise RuntimeError('Kalshi request budget exhausted')
            self.requests += 1
            await self.sleep(0.1)
            try:
                r = await self.client.get(REST_URL + path, params=params)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise ConnectionError('Kalshi REST transport failed') from None
            else:
                if r.status_code == 404:
                    raise LookupError(path)
                if r.status_code == 200:
                    decode(r.text)
                    result = Response(r.text, str(r.url), self.now())
                    self.responses.append(result)
                    return result
                if r.status_code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise ConnectionError(f'Kalshi REST HTTP {r.status_code}')
            await self.sleep(min(2 ** attempt, 4))
        raise RuntimeError('unreachable')

    async def _pages(self, path, field, params):
        cursor, seen = '', set()
        self.discovery_truncated[path + str(params)] = False
        for _ in range(self.max_pages):
            response = await self._get(path, {**params, 'limit': self.page_size, 'cursor': cursor})
            data = decode(response.body)
            if not isinstance(data.get(field), list):
                raise ValueError('missing paginated results')
            yield response, data[field]
            cursor = data.get('cursor')
            if not isinstance(cursor, str):
                raise ValueError('missing pagination cursor')
            if not cursor:
                return
            if cursor in seen:
                raise ValueError('repeated pagination cursor')
            seen.add(cursor)
        self.discovery_truncated[path + str(params)] = True

    async def discover_events(self):
        found = {}
        for series in self.series:
            response = await self._get('/series/' + quote(series, safe=''))
            info = decode(response.body).get('series', {})
            if info.get('ticker') != series or info.get('category') != 'Sports':
                raise ValueError('sports series identity mismatch')
            self.series_metadata[series] = response
            async for response, rows in self._pages('/events', 'events',
                    {'series_ticker': series, 'status': 'open', 'with_milestones': 'true'}):
                milestones = decode(response.body).get('milestones', [])
                for data in rows:
                    event_id = identity(data.get('event_ticker'))
                    if data.get('series_ticker') != series:
                        raise ValueError('series relationship mismatch')
                    sport, league, milestone_type = SPORT_SERIES[series]
                    matching = [m for m in milestones if event_id in m.get('related_event_tickers', [])
                                and m.get('category') == 'Sports' and m.get('type') == milestone_type]
                    starts = {timestamp(m['start_date']) for m in matching}
                    start = next(iter(starts)) if len(starts) == 1 else None
                    self.schedule_evidence[event_id] = {'milestones': matching, 'scheduled_start': start,
                                                       'source': response, 'ambiguous': len(starts) > 1}
                    self.event_series[event_id] = series
                    if self.pregame_only and (start is None or start <= self.now()):
                        continue
                    found[event_id] = Event(raw=response.raw(event_id), title=data['title'], sport=sport,
                                            league=league, scheduled_start=start)
        self.events = found
        return tuple(found.values())

    async def discover_markets(self, event_id=None):
        if not self.events:
            await self.discover_events()
        if event_id is not None and event_id not in self.events:
            raise LookupError(event_id)
        found = {}
        for eid in ((event_id,) if event_id else tuple(self.events)):
            async for response, rows in self._pages('/markets', 'markets', {'event_ticker': eid}):
                for data in rows:
                    m = parse_market(response, data, eid, self.event_series[eid])
                    found[m.raw.ref.market_id] = m
                    self.market_metadata[m.raw.ref.market_id] = data
        self.markets.update(found)
        return tuple(found.values())

    def _market(self, mid):
        if self.closed:
            raise RuntimeError('adapter closed')
        if mid not in self.markets:
            raise LookupError('discover native market first')
        return self.markets[mid]

    async def get_market(self, mid):
        old = self._market(mid)
        response = await self._get('/markets/' + quote(mid, safe=''))
        data = decode(response.body)['market']
        if data.get('ticker') != mid:
            raise ValueError('market identity mismatch')
        m = parse_market(response, data, old.raw.ref.event_id, self.event_series[old.raw.ref.event_id])
        self.markets[mid], self.market_metadata[mid] = m, data
        return m

    async def get_snapshot(self, market_id):
        market = self._market(market_id)
        response = await self._get('/markets/' + quote(market_id, safe='') + '/orderbook', {'depth': self.depth})
        return parse_book(response, market, depth=self.depth)

    async def get_market_rules(self, market_id):
        market = await self.get_market(market_id)
        data = self.market_metadata[market_id]
        rules = '\n\n'.join(data[k] for k in ('rules_primary', 'rules_secondary') if data.get(k))
        series = decode(self.series_metadata[self.event_series[market.raw.ref.event_id]].body)['series']
        return SettlementProfile(raw=market.raw, rules_text=rules or None,
            official_source=series.get('contract_terms_url') or None)

    async def get_fee_metadata(self, event_id):
        if event_id not in self.events:
            raise LookupError(event_id)
        series = self.event_series[event_id]
        history = await self._get('/series/fee_changes', {'series_ticker': series, 'show_historical': 'true'})
        series_rows = decode(history.body).get('series_fee_change_arr')
        if not isinstance(series_rows, list) or any(row.get('series_ticker') != series for row in series_rows):
            raise ValueError('series fee history identity mismatch')
        event_pages = []
        async for response, rows in self._pages('/events/fee_changes', 'event_fee_changes', {'event_ticker': event_id}):
            if any(row.get('event_ticker') != event_id or row.get('series_ticker') != series for row in rows):
                raise ValueError('fee identity mismatch')
            event_pages.append(response)
        return {'series': self.series_metadata[series], 'series_history': history,
                'event_overrides': tuple(event_pages), 'effective_fee': None,
                'account_rounding': None, 'version': None,
                'truncated': self.discovery_truncated['/events/fee_changes' + str({'event_ticker': event_id})]}

    async def stream_markets(self, market_ids):
        from app.adapters.kalshi_stream import MarketStream
        if self.stream_factory is None:
            raise RuntimeError('authenticated transport required')
        if not isinstance(market_ids, tuple) or not 1 <= len(market_ids) <= 20 or len(set(market_ids)) != len(market_ids):
            raise ValueError('requires 1-20 unique native market IDs in a tuple')
        stream = MarketStream([self._market(mid) for mid in market_ids], self.stream_factory, **self.stream_options)
        self.streams.add(stream)
        try:
            async with aclosing(stream.run()) as updates:
                async for update in updates:
                    yield update
        finally:
            await stream.aclose()
            self.streams.discard(stream)

    async def aclose(self):
        self.closed = True
        for stream in tuple(self.streams):
            await stream.aclose()
        await self.client.aclose()
