"""Retail full-window images, atomically replaced on the current subscription.

SYNCHRONIZED means the advertised window equals the latest valid current-subscription
image. It says nothing about total exchange depth, receipt/exchange freshness, or
receipt of every intervening change. Missing arrays never qualify as empty arrays.
"""
import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timezone
import json
import time
import uuid

from app.adapters.polymarket_us import (Response, decode, next_market_data, parse_book, source_time_value)
from app.models.core import BookSync, EvidenceKind, ReceiptFreshness, SourceTimeProgress

WS_PATH = '/v1/ws/markets'
WS_URL = 'wss://api.polymarket.us' + WS_PATH


def subscription(slugs, request_id, dialect='camel'):
    if not 1 <= len(slugs) <= 100 or len(set(slugs)) != len(slugs) or any(not isinstance(s, str) or not s for s in slugs):
        raise ValueError('requires 1-100 unique market slugs')
    if dialect == 'camel':
        return {'subscribe': {'requestId': request_id, 'subscriptionType': 'SUBSCRIPTION_TYPE_MARKET_DATA', 'marketSlugs': list(slugs)}}
    if dialect == 'snake':
        return {'subscribe': {'request_id': request_id, 'subscription_type': 1, 'market_slugs': list(slugs)}}
    raise ValueError('explicit camel or snake dialect required')


class RuntimeSigner:
    """Only explicitly passed secrets; no environment/keychain/filesystem lookup."""
    def __init__(self, key_id, secret_key):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        if not isinstance(key_id, str) or not key_id or '\n' in key_id or '\r' in key_id:
            raise ValueError('invalid key ID')
        try:
            seed = base64.b64decode(secret_key, validate=True)
            if len(seed) not in (32, 64):
                raise ValueError()
            self._key = Ed25519PrivateKey.from_private_bytes(seed[:32])
        except (ValueError, TypeError):
            raise ValueError('invalid secret key encoding') from None
        self._key_id = key_id

    def headers(self, milliseconds=None):
        ts = str(int(time.time() * 1000) if milliseconds is None else milliseconds)
        sig = self._key.sign((ts + 'GET' + WS_PATH).encode())
        return {'X-PM-Access-Key': self._key_id, 'X-PM-Timestamp': ts,
                'X-PM-Signature': base64.b64encode(sig).decode()}

    def __repr__(self):
        return 'RuntimeSigner(<redacted>)'


class AuthenticatedTransport:
    def __init__(self, signer, *, allow_connection=False):
        if allow_connection is not True:
            raise ValueError('explicit authenticated connection opt-in required')
        self._signer = signer

    async def __call__(self):
        from websockets.asyncio.client import connect
        try:
            return await connect(WS_URL, additional_headers=self._signer.headers(),
                open_timeout=10, close_timeout=2, ping_interval=10, ping_timeout=10,
                max_size=2**20, max_queue=16, proxy=None)
        except Exception:
            # Do not surface handshake objects or headers in error/evidence.
            raise ConnectionError('authenticated market transport failed') from None


class StaleSubscriptionFrame(ValueError):
    """A frame from a superseded connection/subscription is never applied."""


class MarketStream:
    def __init__(self, markets, factory, *, dialect='camel', max_messages=30,
                 max_connections=2, stale_seconds=10, duration=30,
                 kind=EvidenceKind.OBSERVATION, sleep=asyncio.sleep, profile_name=None):
        self.markets = {next_market_data(m)['slug']: m for m in markets}
        subscription(tuple(self.markets), 'validate', dialect)
        from app.collection.supervised import profile, bound_native
        policy = profile(profile_name) if profile_name else None
        for value, limit in ((max_messages, policy['group_messages'] if policy else 1000), (max_connections, 5)):
            if type(value) is not int or not 1 <= value <= limit:
                raise ValueError('invalid stream bound')
        if not 0 < stale_seconds <= 60 or not 0 < duration <= 300:
            raise ValueError('invalid stream duration')
        self.factory, self.dialect, self.kind, self.sleep = factory, dialect, kind, sleep
        self.max_messages, self.max_connections = max_messages, max_connections
        self.stale_seconds, self.duration = stale_seconds, duration
        self.last = {}
        self.diagnostics = []  # No exception strings, credentials or handshake material.
        self.responses = []
        self.connection = None
        self.closed = False
        self.reason = 'not_started'
        self.events = []
        self.subscription_id = None
        self.generation = 0
        self.source_time_high_water = {}  # Per market, retained across reconnects.
        if policy: bound_native(self)

    def begin_subscription(self, request_id):
        if self.closed or not isinstance(request_id, str) or not request_id:
            raise ValueError('open stream and nonempty subscription ID required')
        self.invalidate('awaiting_initial_image')
        self.generation += 1
        self.subscription_id = request_id
        return self.generation

    def record(self, event, **fields):
        self.events.append({"event": event, "received_at": datetime.now(timezone.utc).isoformat(), **fields})

    def invalidate(self, reason):
        self.reason = reason
        self.subscription_id = None
        self.diagnostics.append(reason)
        self.record(reason)
        for slug, book in list(self.last.items()):
            self.last[slug] = replace(book, sync=BookSync.UNSYNCHRONIZED)
        return tuple(self.last.values())

    def parse(self, body, request_id, *, generation=None):
        # A caller cannot relabel an old connection's frame with a current request ID.
        if (self.closed or self.subscription_id is None or request_id != self.subscription_id
                or generation != self.generation):
            raise StaleSubscriptionFrame('superseded connection/subscription')
        response = Response(body, WS_URL, datetime.now(timezone.utc), self.kind)
        self.responses.append(response)
        try:
            data = decode(body)
            if set(data) == {'heartbeat'} and isinstance(data['heartbeat'], dict):
                return None
            if 'requestId' in data and data['requestId'] != self.subscription_id:
                raise StaleSubscriptionFrame('superseded subscription response')
            if data.get('requestId') != self.subscription_id or data.get('subscriptionType') != 'SUBSCRIPTION_TYPE_MARKET_DATA':
                raise ValueError('unsupported stream envelope')
            md = data.get('marketData')
            if not isinstance(md, dict) or md.get('marketSlug') not in self.markets:
                raise ValueError('unknown market message')
            if set(data) - {'requestId', 'subscriptionType', 'marketData'} or set(md) & {'delta', 'sequence', 'snapshot', 'updateType'}:
                raise ValueError('ambiguous wire semantics')
            book = parse_book(response, md, self.markets[md['marketSlug']], stream=True)
            # Atomic replacement: do not merge, retain omitted levels or preserve
            # the other side from a previous frame. Explicit [] is known empty.
            complete = isinstance(md.get('bids'), list) and isinstance(md.get('offers'), list)
            slug = md['marketSlug']
            source_time = source_time_value(md.get('transactTime'))
            high_water = self.source_time_high_water.get(slug)
            if source_time is None:
                progress = SourceTimeProgress.MISSING
            elif high_water is None:
                progress = SourceTimeProgress.FIRST
            elif source_time < high_water:
                progress = SourceTimeProgress.REGRESSED
            elif source_time == high_water:
                progress = SourceTimeProgress.REPEATED
            else:
                progress = SourceTimeProgress.ADVANCED
            book = replace(book, sync=BookSync.SYNCHRONIZED if complete else BookSync.UNKNOWN,
                           receipt_freshness=ReceiptFreshness.RECENT, source_time_progress=progress)
            if source_time is not None and (high_water is None or source_time > high_water):
                self.source_time_high_water[slug] = source_time
            self.last[md['marketSlug']] = book
            self.reason = 'current_window_image' if complete else 'incomplete_image'
            return book
        except StaleSubscriptionFrame:
            raise
        except (ValueError, KeyError, TypeError):
            # Invalidate even when parse is called outside run(). A new subscription
            # is required before any later frame can requalify the current image.
            self.invalidate('unsupported_or_malformed')
            raise

    async def run(self):
        count = 0
        deadline = time.monotonic() + self.duration
        try:
            for attempt in range(self.max_connections):
                if self.closed or time.monotonic() >= deadline or count >= self.max_messages:
                    break
                request_id = str(uuid.uuid4())
                pending = None
                try:
                    async with asyncio.timeout(min(10, max(0.001, deadline - time.monotonic()))):
                        self.connection = await self.factory()
                    self.record('connected', connection_number=attempt + 1)
                    generation = self.begin_subscription(request_id)
                    await asyncio.wait_for(self.connection.send(json.dumps(subscription(tuple(self.markets), request_id, self.dialect))),
                                           timeout=min(5, max(0.001, deadline-time.monotonic())))
                    self.record('subscribed', request_id=request_id, dialect=self.dialect)
                    last_data = {slug: time.monotonic() for slug in self.markets}
                    stale = set()
                    while not self.closed and count < self.max_messages:
                        now = time.monotonic()
                        if now >= deadline:
                            self.record('duration_limit')
                            break
                        # Quiet books lose freshness, but do not imply socket failure.
                        # The transport's ping/pong timeout detects broken connections.
                        for slug, updated in last_data.items():
                            if slug not in stale and now - updated >= self.stale_seconds:
                                stale.add(slug)
                                self.record('market_data_stale', market_slug=slug)
                                self.diagnostics.append('market_data_stale')
                                if slug in self.last:
                                    self.last[slug] = replace(self.last[slug], receipt_freshness=ReceiptFreshness.STALE)
                                    yield self.last[slug]
                        next_expiry = min((t + self.stale_seconds for slug, t in last_data.items()
                                           if slug not in stale), default=deadline)
                        wait = max(0.001, min(deadline, next_expiry) - time.monotonic())
                        if pending is None:
                            pending = asyncio.create_task(self.connection.recv())
                        done, _ = await asyncio.wait({pending}, timeout=wait)
                        if not done:
                            continue  # Retain pending receive across freshness timers.
                        message = pending.result()
                        pending = None
                        count += 1
                        try:
                            book = self.parse(message, request_id, generation=generation)
                        except StaleSubscriptionFrame:
                            self.record('old_subscription_frame_ignored')
                            continue
                        except (ValueError, KeyError, TypeError):
                            for previous in self.last.values():
                                yield previous
                            raise ConnectionError() from None
                        if book is not None:
                            slug = decode(message)["marketData"]["marketSlug"]
                            last_data[slug] = time.monotonic()
                            stale.discard(slug)
                            self.record('market_observation', market_slug=slug)
                            yield book
                        else:
                            self.record('heartbeat')
                    break
                except asyncio.CancelledError:
                    self.invalidate('cancelled')
                    raise
                except Exception:
                    for previous in self.invalidate('disconnected'):
                        yield previous
                finally:
                    if pending is not None:
                        pending.cancel()
                        try:
                            await pending
                        except (asyncio.CancelledError, Exception):
                            pass
                    if self.connection is not None:
                        await self._close_connection()
                if attempt + 1 < self.max_connections and not self.closed:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        break
                    await self.sleep(min(2**attempt, remaining))
        finally:
            self.invalidate('stopped')
            await self.aclose()

    async def _close_connection(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                await asyncio.wait_for(connection.close(), 2)
                self.record("connection_closed")
            except Exception:
                self.diagnostics.append('close_failed')

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        self.invalidate('closed')
        await self._close_connection()
