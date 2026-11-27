"""Read anonymous Novig v3 books for a frozen pregame experiment decision."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from fractions import Fraction
from hashlib import sha256
import json
import re
import time

import httpx

from app.comparison.sgo_native_binding import UUID
from app.storage.store import stamp
from .novig_v3_public import HOST, MAX_BODY


MARKETS_PATH = '/v3/public/catalog/markets'
MARKET_TYPES = {'spread': 'SPREAD', 'total': 'TOTAL'}
PAGE_SIZE = 240
PAGE_LIMIT = 4
BOOK_LEVELS = 20
REQUEST_TIMEOUT = 3
MAX_CONCURRENCY = 4
REQUEST_SPACING_SECONDS = 0.65
# Measured on production CloudFront. Its separate stale-while-revalidate
# allowance is outside the decision freshness budget.
CATALOG_FRESH_SECONDS = 10
BOOK_FRESH_SECONDS = 5
FEE_SOURCE = 'https://docs.novig.com/api/concepts/fees#from-december-1-2026'
CUTOVER_DATE_UTC = datetime(2026, 12, 1, tzinfo=timezone.utc)
CUTOVER_DATE_ET = CUTOVER_DATE_UTC + timedelta(hours=5)
HTTP_EVIDENCE = ('date', 'age', 'cache-control', 'etag', 'x-cache', 'warning', 'retry-after', 'x-request-id')


@dataclass(frozen=True)
class PublicEventDepth:
    markets: dict
    receipts: tuple
    reason: str | None = None


@dataclass(frozen=True)
class PublicBookDepth:
    book: dict | None
    receipt: dict | None
    reason: str | None = None


def _uuid(value):
    return isinstance(value, str) and re.fullmatch(UUID, value) is not None


def _clock():
    return datetime.now(timezone.utc)


def _http_date(value):
    return stamp(parsedate_to_datetime(value))


def _retry_seconds(value, at):
    if value is not None:
        value = value.strip()
        if re.fullmatch(r'[0-9]{1,10}', value):
            return int(value)
        try:
            return max(0, (_http_date(value) - at).total_seconds())
        except (AttributeError, OverflowError, TypeError, ValueError):
            pass
    return 60


class NovigExperimentDepth:
    """Bound optional public work and share a Retry-After window across games."""

    def __init__(self, *, transport=None, clock=_clock):
        self.clock = clock
        self.client = httpx.AsyncClient(transport=transport, timeout=REQUEST_TIMEOUT,
                                       follow_redirects=False)
        self._requests = asyncio.Semaphore(MAX_CONCURRENCY)
        self._start_lock = asyncio.Lock()
        self._next_start = 0
        self._retry_at = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        await self.client.aclose()

    async def _read(self, path, params, cutoff):
        remaining = (cutoff - self.clock()).total_seconds()
        if remaining <= 0:
            return None, None, 'after_cutoff'
        receipt = None
        try:
            async with asyncio.timeout(min(remaining, REQUEST_TIMEOUT)):
                async with self._requests:
                    async with self._start_lock:
                        if time.monotonic() < self._retry_at:
                            return None, None, 'throttled'
                        delay = self._next_start - time.monotonic()
                        if delay > 0:
                            await asyncio.sleep(delay)
                        if time.monotonic() < self._retry_at:
                            return None, None, 'throttled'
                        requested = self.clock()
                        if requested >= cutoff:
                            return None, None, 'after_cutoff'
                        self._next_start = time.monotonic() + REQUEST_SPACING_SECONDS
                    receipt = dict(source='novig_public_v3', path=path, params=params,
                                   requested_at=requested.isoformat())
                    async with self.client.stream('GET', HOST + path, params=params) as response:
                        receipt.update(status=response.status_code, **{
                            name: response.headers[name] for name in HTTP_EVIDENCE if name in response.headers
                        })
                        if response.status_code == 429:
                            now = self.clock()
                            delay = _retry_seconds(response.headers.get('retry-after'), now)
                            self._retry_at = max(self._retry_at, time.monotonic() + delay)
                            if now > cutoff:
                                return None, None, 'after_cutoff'
                            receipt.update(received_at=now.isoformat(), retry_after_seconds=delay)
                            return None, receipt, 'throttled'
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_BODY:
                                received = self.clock()
                                if received > cutoff:
                                    return None, None, 'after_cutoff'
                                receipt['received_at'] = received.isoformat()
                                return None, receipt, 'response_too_large'
                    received = self.clock()
                    if received > cutoff:
                        return None, None, 'after_cutoff'
                    receipt.update(received_at=received.isoformat(), sha256=sha256(body).hexdigest())
                    return json.loads(body), receipt, None
        except (TimeoutError, httpx.TimeoutException):
            reason = 'after_cutoff' if self.clock() >= cutoff else 'timeout'
        except httpx.HTTPError:
            reason = 'unavailable'
        except (UnicodeDecodeError, ValueError):
            reason = 'invalid_response'
        if receipt is not None:
            ended = stamp(receipt['received_at']) if 'received_at' in receipt else self.clock()
            if ended > cutoff:
                return None, None, 'after_cutoff'
            receipt['received_at'] = ended.isoformat()
        return None, receipt, reason

    async def read_event(self, event_id, cutoff):
        cutoff = stamp(cutoff)
        if not _uuid(event_id):
            return PublicEventDepth({}, (), 'unmatched')
        params = dict(event=event_id, eventStatus='OPEN_PREGAME',
                      marketType='SPREAD,TOTAL', limit=PAGE_SIZE)
        markets, receipts, seen_cursors = {}, [], set()
        for _ in range(PAGE_LIMIT):
            page, receipt, reason = await self._read(MARKETS_PATH, params, cutoff)
            if receipt is not None:
                receipts.append(receipt)
            if reason:
                return PublicEventDepth(markets, tuple(receipts), reason)
            if not isinstance(page, dict) or not isinstance(page.get('items'), list) or len(page['items']) > PAGE_SIZE:
                return PublicEventDepth(markets, tuple(receipts), 'invalid_response')
            for market in page['items']:
                market_id = market.get('marketId') if isinstance(market, dict) else None
                if (not _uuid(market_id) or market.get('eventId') != event_id or market_id in markets):
                    return PublicEventDepth({}, tuple(receipts), 'identity_conflict')
                markets[market_id] = dict(market, receipt=receipt)
            cursor = page.get('next')
            if cursor is None:
                return PublicEventDepth(markets, tuple(receipts))
            if not isinstance(cursor, str) or not 0 < len(cursor) <= 1024 or cursor in seen_cursors:
                return PublicEventDepth(markets, tuple(receipts), 'invalid_pagination')
            seen_cursors.add(cursor)
            params = dict(params, after=cursor)
        return PublicEventDepth(markets, tuple(receipts), 'catalog_truncated')

    async def read_book(self, market_id, cutoff):
        if not _uuid(market_id):
            return PublicBookDepth(None, None, 'unmatched')
        path = f'{MARKETS_PATH}/{market_id}/book'
        book, receipt, reason = await self._read(path, {'depth': BOOK_LEVELS}, stamp(cutoff))
        if reason:
            return PublicBookDepth(None, receipt, reason)
        if (not isinstance(book, dict) or book.get('marketId') != market_id
                or type(book.get('seq')) is not int or book['seq'] < 0 or not isinstance(book.get('orders'), dict)):
            return PublicBookDepth(None, receipt, 'identity_conflict')
        return PublicBookDepth(book, dict(receipt, sequence=book['seq']))


def _cache_origin(receipt):
    return min(_http_date(receipt['date']),
               stamp(receipt['received_at']) - timedelta(seconds=int(receipt.get('age', '0'))))


def _fresh(receipt, cutoff, max_seconds):
    """Age a body from its oldest HTTP clock through the decision cutoff."""
    try:
        requested, received = (stamp(receipt[key]) for key in ('requested_at', 'received_at'))
        if not requested <= received <= cutoff:
            return 'after_cutoff'
        dated = _http_date(receipt['date'])
        age = receipt.get('age', '0')
        if (not re.fullmatch(r'[0-9]{1,10}', age)
                or dated > received + timedelta(seconds=1)
                or receipt.get('warning', '').startswith(('110 ', '111 '))):
            return 'stale'
        lifetime = re.search(r'(?:^|,)\s*max-age=([0-9]{1,10})(?:\s*,|\s*$)', receipt['cache-control'], re.I)
        if not lifetime:
            return 'cache_unverified'
        # Date and Age have second precision. The minimum also prevents a
        # freshly served stale object from inheriting the local receipt clock.
        origin = _cache_origin(receipt)
        allowed = min(max_seconds, int(lifetime[1]))
        if (cutoff - origin).total_seconds() > allowed:
            return 'stale'
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return 'cache_unverified'
    return None


def _fee(terms, cutoff=None):
    fee = dict(model='novig_v3', coefficient=None, round_usd='1/100000',
               source=FEE_SOURCE, terms=terms)
    if cutoff is None:
        return dict(fee, reason='fee_schedule_unverified')
    charged = terms.get('charged') if isinstance(terms, dict) else None
    try:
        coefficient = Fraction(terms['coefficient'])
    except (KeyError, TypeError, ValueError, ArithmeticError):
        coefficient = None
    if cutoff < CUTOVER_DATE_UTC and charged == 'WHEN_LIVE' and coefficient == Fraction('0.06'):
        return dict(fee, coefficient='0', version='novig_v3_pregame_zero')
    if cutoff >= CUTOVER_DATE_UTC and charged == 'ALWAYS' and coefficient == Fraction('0.03'):
        return dict(fee, coefficient='3/100', version='novig_v3_pregame_december_2026')
    if CUTOVER_DATE_UTC <= cutoff < CUTOVER_DATE_ET:
        return dict(fee, reason='fee_cutover_time_unverified')
    # The current market field documents the applied schedule. A legacy
    # live-only field after the announced change is unresolved evidence.
    return dict(fee, reason='fee_schedule_unverified')


def _base(binding):
    identity = {key: binding.get(key) for key in ('event_id', 'market_id', 'outcome_id', 'opposite_outcome_id')}
    return dict(identity, venue='novig', complete=False, reason=None, levels=[], receipts=[],
                payout_usd='1/100', quantity_increment='1',
                fee=_fee(None))


def _outcomes(market, binding, cutoff):
    market_type = MARKET_TYPES.get(binding.get('family'))
    side = binding.get('selected_side')
    line = Fraction(binding['signed_line'])
    strike = -line if side == 'away' else line
    starts = stamp(binding['starts_at'])
    if (not market_type or not binding.get('available') or binding.get('phase') != 'scheduled'
            or not binding.get('phase_verified') or cutoff >= starts
            or market.get('marketType') != market_type or market.get('status') != 'OPEN'
            or type(market.get('startsTs')) is not int
            or datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=market['startsTs']) != starts
            or Fraction(market['strike']) != strike):
        raise ValueError('market identity conflict')
    members = market['outcomes']
    outcomes = {outcome['outcomeId']: outcome for outcome in members}
    if (len(members) != 2 or len(outcomes) != 2 or set(outcomes) != {
            binding['outcome_id'], binding['opposite_outcome_id']
    } or any(outcome.get('status') != 'TBD' for outcome in members)):
        raise ValueError('outcome identity conflict')
    selected = outcomes[binding['outcome_id']]
    opposite = outcomes[binding['opposite_outcome_id']]
    if market_type == 'TOTAL':
        if side not in {'over', 'under'}:
            raise ValueError('total side unverified')
        directions = [selected['name'].split(), opposite['name'].split()]
        if (any(len(name) != 2 or Fraction(name[1]) != line for name in directions)
                or [name[0].lower() for name in directions] != [side, 'under' if side == 'over' else 'over']):
            raise ValueError('total outcome conflict')
    elif (side not in {'away', 'home'} or not _uuid(selected.get('subjectId'))
          or not _uuid(opposite.get('subjectId')) or selected['subjectId'] == opposite['subjectId']
          or Fraction(selected['name'].rsplit(' ', 1)[-1]) != line
          or Fraction(opposite['name'].rsplit(' ', 1)[-1]) != -line):
        raise ValueError('spread outcome conflict')
    elif binding.get('subject_role_anchors'):
        other_side = 'home' if side == 'away' else 'away'
        if any(anchor[f'{side}_subject'] != selected['subjectId']
               or anchor[f'{other_side}_subject'] != opposite['subjectId']
               for anchor in binding['subject_role_anchors']):
            raise ValueError('spread participant conflict')
    return selected, opposite


def _price_quantity(order):
    price, qty = order['price'], order['qty']
    if not isinstance(price, str) or not re.fullmatch(r'0\.[0-9]{1,3}', price):
        raise ValueError('price format')
    native_price = Fraction(price)
    milli = native_price * 1000
    if (not 0 < milli < 1000 or (50 < milli < 950 and milli % 5)
            or type(qty) is not int or qty <= 0):
        raise ValueError('price or size outside native increments')
    return 1 - native_price, qty


def catalog_depth(binding, snapshot, cutoff):
    """Use the opposite bid's full resting quantity at its best level."""
    cutoff = stamp(cutoff)
    depth = _base(binding)
    if not all(_uuid(depth.get(key)) for key in ('event_id', 'market_id', 'outcome_id', 'opposite_outcome_id')):
        return dict(depth, reason=binding.get('reason') or 'unmatched')
    market = snapshot.markets.get(depth['market_id'])
    if market is None:
        return dict(depth, reason=snapshot.reason or 'unmatched', receipts=list(snapshot.receipts))
    receipt = market['receipt']
    depth['receipts'] = [receipt]
    reason = _fresh(receipt, cutoff, CATALOG_FRESH_SECONDS)
    if reason:
        return dict(depth, reason=reason)
    try:
        if market['eventId'] != depth['event_id'] or market['marketId'] != depth['market_id']:
            raise ValueError('market identity conflict')
        selected, opposite = _outcomes(market, binding, cutoff)
        depth['contract'] = dict(family=binding['family'], starts_at=binding['starts_at'],
                                 selected_side=binding['selected_side'], signed_line=binding['signed_line'],
                                 event_status='OPEN_PREGAME', market_status=market['status'],
                                 labels=[selected['name'], opposite['name']],
                                 subjects=[selected.get('subjectId'), opposite.get('subjectId')],
                                 binding_revision=binding.get('revision'))
        depth['fee'] = _fee(market.get('fee'), cutoff)
        bid = opposite.get('bid')
        if bid is None:
            return dict(depth, complete=True)
        price, quantity = _price_quantity(bid)
        return dict(depth, levels=[dict(price=str(price), quantity=str(quantity))])
    except (ArithmeticError, AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return dict(depth, reason='identity_or_quote_conflict')


def book_depth(binding, snapshot, cutoff, *, catalog):
    """Retain price-time order and classify the observable depth lower bound."""
    cutoff = stamp(cutoff)
    receipts = list(catalog['receipts'])
    if snapshot.receipt is not None:
        receipts.append(snapshot.receipt)
    depth = dict(catalog, receipts=receipts)
    if catalog['reason']:
        return depth
    if _fresh(catalog['receipts'][0], cutoff, CATALOG_FRESH_SECONDS):
        return dict(depth, reason='stale')
    reason = snapshot.reason
    if not reason and snapshot.receipt is not None:
        reason = _fresh(snapshot.receipt, cutoff, BOOK_FRESH_SECONDS)
    if reason or snapshot.book is None or snapshot.receipt is None:
        return dict(depth, reason=reason or 'unavailable', catalog_lower_bound=True)
    try:
        book = snapshot.book
        sides = {binding['outcome_id'], binding['opposite_outcome_id']}
        if (book['marketId'] != binding['market_id'] or book['orders'].keys() - sides
                or any(catalog.get(key) != binding.get(key) for key in (
                    'event_id', 'market_id', 'outcome_id', 'opposite_outcome_id'
                ))):
            raise ValueError('book identity conflict')
        orders = book['orders'].get(binding['opposite_outcome_id'], [])
        if not isinstance(orders, list):
            raise ValueError('book order list conflict')
        levels, seen = {}, set()
        last = Fraction(0)
        for order in orders:
            price, qty = _price_quantity(order)
            order_id = order['orderId']
            if price < last or not _uuid(order_id) or order_id in seen:
                raise ValueError('book order conflict')
            last = price
            seen.add(order_id)
            levels.setdefault(price, []).append((qty, order_id))
        if len(levels) > BOOK_LEVELS:
            raise ValueError('book depth conflict')
        rows = [dict(price=str(price), quantity=str(sum(qty for qty, _ in fills)),
                     orders=[str(qty) for qty, _ in fills], order_ids=[order_id for _, order_id in fills])
                for price, fills in levels.items()]
        top = [{k: row[k] for k in ('price', 'quantity')} for row in rows[:1]]
        # Cached responses from the two routes can arrive in reverse source
        # order. A disagreeing older book cannot supersede a later best bid.
        if top != catalog['levels'] and _cache_origin(snapshot.receipt) < _cache_origin(catalog['receipts'][0]):
            return dict(depth, reason='older_book_top_conflict', catalog_lower_bound=True)
        return dict(depth, complete=len(rows) < BOOK_LEVELS, sequence=book['seq'], levels=rows)
    except (ArithmeticError, AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return dict(depth, reason='invalid_order_book')
