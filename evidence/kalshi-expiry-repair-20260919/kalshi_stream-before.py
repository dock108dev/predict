"""Kalshi subscription-scoped snapshot/delta reconstruction with finite recovery.

SYNCHRONIZED: a valid current-generation snapshot plus contiguous subscription
messages, for the native aggregated image. Not source freshness, tradability,
exchange-wide liquidity or proof that every historical change was received.
"""
import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
import re
import time

from app.adapters.kalshi import Response, book_from_levels, decode, identity, levels, timestamp
from app.models.core import (BookSync, Depth, EvidenceKind, ReceiptFreshness,
                             SourceTimeProgress, Probability, parse_decimal)

WS_PATH = '/trade-api/ws/v2'
WS_URL = 'wss://external-api-ws.kalshi.com' + WS_PATH
KEYCHAIN_SERVICE = 'prediction-arb.kalshi.production'
KEYCHAIN_ACCOUNT = 'market-data'


def encode(value):
    """Serialize decoded Decimals as JSON numbers, preserving decimal precision."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('invalid JSON number')
        return str(value)
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + ':' + encode(v) for k, v in value.items()) + '}'
    if isinstance(value, (tuple, list)):
        return '[' + ','.join(encode(v) for v in value) + ']'
    return json.dumps(value, allow_nan=False)


def sanitize(message):
    """Allowlisted market data only; never retain own-order IDs/subaccounts/errors."""
    top = {k: message[k] for k in ('id', 'type', 'sid', 'seq') if k in message}
    msg = message.get('msg')
    if isinstance(msg, dict):
        allowed = ('channel', 'sid', 'market_ticker', 'market_id', 'yes_dollars_fp',
                   'no_dollars_fp', 'price_dollars', 'delta_fp', 'side', 'ts', 'ts_ms')
        top['msg'] = {k: msg[k] for k in allowed if k in msg}
    return top


class RuntimeSigner:
    def __init__(self, key_id, private_key):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        if not isinstance(key_id, str) or not key_id or '\r' in key_id or '\n' in key_id:
            raise ValueError('invalid key ID')
        try:
            self._key = load_pem_private_key(private_key.encode(), password=None)
            if not isinstance(self._key, RSAPrivateKey):
                raise ValueError()
        except Exception:
            raise ValueError('invalid RSA private key') from None
        self._key_id = key_id

    def headers(self, milliseconds=None):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        ts = str(int(time.time() * 1000) if milliseconds is None else milliseconds)
        signature = self._key.sign((ts + 'GET' + WS_PATH).encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
        return {'KALSHI-ACCESS-KEY': self._key_id, 'KALSHI-ACCESS-TIMESTAMP': ts,
                'KALSHI-ACCESS-SIGNATURE': base64.b64encode(signature).decode()}

    def __repr__(self):
        return 'RuntimeSigner(<redacted>)'


def keychain_signer():
    import keyring
    secret = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    if not secret:
        raise RuntimeError('dedicated Kalshi Keychain credential unavailable')
    try:
        data = json.loads(secret)
        return RuntimeSigner(data['key_id'], data['private_key'])
    except Exception:
        raise ValueError('invalid dedicated Kalshi credential') from None


def store_credentials(key_id, private_key):
    import keyring
    RuntimeSigner(key_id, private_key)
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT,
                         json.dumps({'key_id': key_id, 'private_key': private_key}))


class AuthenticatedTransport:
    def __init__(self, signer):
        self.signer = signer

    async def __call__(self):
        from websockets.asyncio.client import connect
        try:
            return await connect(WS_URL, additional_headers=self.signer.headers(),
                open_timeout=10, close_timeout=2, ping_interval=10, ping_timeout=10,
                max_size=2**20, max_queue=16, proxy=None)
        except Exception:
            raise ConnectionError('Kalshi authenticated transport failed') from None


class RecoveryRequired(ValueError):
    pass


class BookReconstructor:
    def __init__(self, markets, *, kind=EvidenceKind.OBSERVATION):
        self.markets = {m.raw.ref.market_id: m for m in markets}
        if not 1 <= len(self.markets) <= 20 or len(self.markets) != len(markets):
            raise ValueError('requires 1-20 unique markets')
        self.kind = kind
        self.generation, self.sid, self.seq, self.request_id = 0, None, None, None
        self.sides, self.native_ids, self.last, self.source_highwater = {}, {}, {}, {}
        self.frames = []

    def invalidate(self):
        self.sides.clear()
        self.sid, self.seq = None, None
        for mid, book in tuple(self.last.items()):
            self.last[mid] = replace(book, sync=BookSync.UNSYNCHRONIZED)
        return tuple(self.last.values())

    def begin(self, request_id):
        self.invalidate()
        self.generation += 1
        self.request_id = request_id
        return {'id': request_id, 'cmd': 'subscribe', 'params': {
            'channels': ['orderbook_delta'], 'market_tickers': list(self.markets)}}

    def feed(self, body, generation, received_at):
        if generation != self.generation:
            return None
        try:
            return self._feed(body, generation, received_at)
        except (ValueError, KeyError, TypeError, OverflowError, AttributeError, IndexError):
            self.invalidate()
            raise RecoveryRequired('invalid or ambiguous Kalshi subscription image') from None

    def _feed(self, body, generation, received_at):
        msg = decode(body)
        kind = msg.get('type')
        if kind == 'subscribed':
            if msg.get('id') != self.request_id:
                return None
            data = msg['msg']
            if data.get('channel') != 'orderbook_delta' or type(data.get('sid')) is not int or data['sid'] < 1:
                raise ValueError('invalid subscription acknowledgement')
            if self.sid is not None:
                raise ValueError('duplicate subscription acknowledgement')
            self.sid = data['sid']
            self.frames.append((generation, received_at, encode(sanitize(msg))))
            return None
        if kind == 'error':
            if msg.get('sid') not in (None, self.sid):
                return None
            raise ValueError('subscription error')
        if self.sid is None:
            if kind in ('orderbook_snapshot', 'orderbook_delta'):
                raise ValueError('book before acknowledgement')
            return None
        if msg.get('sid') != self.sid:
            return None
        # Sequence is scoped to the SID (all markets and sequenced control replies),
        # never to individual tickers or unrelated channels.
        seq = msg.get('seq')
        if type(seq) is not int or seq < 1:
            raise ValueError('missing sequence')
        if self.seq is not None and seq != self.seq + 1:
            raise ValueError('sequence gap, duplicate or regression')
        self.seq = seq
        if kind in ('ok',):
            return None
        if kind not in ('orderbook_snapshot', 'orderbook_delta'):
            raise ValueError('unexpected subscription message')
        data = msg['msg']
        mid, uuid = identity(data.get('market_ticker')), identity(data.get('market_id'))
        if mid not in self.markets or (mid in self.native_ids and self.native_ids[mid] != uuid):
            raise ValueError('market identity mismatch')
        self.native_ids[mid] = uuid
        if kind == 'orderbook_snapshot':
            # AsyncAPI explicitly defines omitted side as no offers in WS snapshots.
            candidate = {s: levels(data.get(s + '_dollars_fp', [])) for s in ('yes', 'no')}
            if any(v is None for v in candidate.values()):
                raise ValueError('null is not the documented omitted empty side')
        else:
            if mid not in self.sides:
                raise ValueError('delta before initial snapshot')
            side = data['side']
            if side not in ('yes', 'no'):
                raise ValueError('invalid side')
            price, delta = parse_decimal(data['price_dollars']), parse_decimal(data['delta_fp'])
            Probability(value=price)
            candidate = {s: dict(rows) for s, rows in self.sides[mid].items()}
            old = candidate[side].get(price, Decimal(0))
            with localcontext() as ctx:
                ctx.prec = max(34, len(old.as_tuple().digits) + len(delta.as_tuple().digits)
                               + abs(old.as_tuple().exponent) + abs(delta.as_tuple().exponent) + 2)
                size = old + delta
            if size < 0:
                raise ValueError('negative aggregate quantity')
            if size == 0:
                candidate[side].pop(price, None)
            else:
                candidate[side][price] = size
        exchange_at, source_key = None, None
        if kind == 'orderbook_delta':
            if 'ts_ms' in data:
                ms = data['ts_ms']
                if type(ms) is not int:
                    raise ValueError('ts_ms must be integer milliseconds')
                exchange_at = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)
                parts = Decimal(ms).as_tuple()
                source_key = Decimal((parts.sign, parts.digits, parts.exponent - 3))
            elif data.get('ts') is not None:
                exchange_at = timestamp(data['ts'])
                match = re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d+))?(?:Z|[+-]\d{2}:\d{2})", data['ts'])
                if match is None:
                    raise ValueError('invalid legacy source time')
                delta_time = exchange_at.replace(microsecond=0) - datetime(1970, 1, 1, tzinfo=timezone.utc)
                fraction = match[1] or '0'
                with localcontext() as ctx:
                    ctx.prec = max(34, len(fraction) + 20)
                    source_key = Decimal(delta_time.days * 86400 + delta_time.seconds) + Decimal('0.' + fraction)
        progress = SourceTimeProgress.MISSING
        if source_key is not None:
            prior = self.source_highwater.get(mid)
            progress = SourceTimeProgress.FIRST if prior is None else (
                SourceTimeProgress.ADVANCED if source_key > prior else
                SourceTimeProgress.REPEATED if source_key == prior else SourceTimeProgress.REGRESSED)
            if prior is None or source_key > prior:
                self.source_highwater[mid] = source_key
        safe = sanitize(msg)
        self.frames.append((generation, received_at, encode(safe)))
        raw_body = encode({'message': safe, 'connection_generation': generation,
            'reconstructed_bids': {s: [[str(p), str(q)] for p, q in sorted(rows.items())]
                                   for s, rows in candidate.items()}})
        market = self.markets[mid]
        raw = Response(raw_body, WS_URL + f'#sid={self.sid};generation={generation};book', received_at,
                       self.kind).raw(market.raw.ref.event_id, mid, exchange_at)
        book = book_from_levels(raw, candidate, depth=Depth.FULL, sync=BookSync.SYNCHRONIZED,
            sequence=str(seq), source_progress=progress)
        self.sides[mid], self.last[mid] = candidate, book
        return book


class MarketStream:
    def __init__(self, markets, factory, *, duration=30, max_messages=500, max_connections=2,
                 stale_seconds=10, snapshot_timeout=10, sleep=asyncio.sleep,
                 kind=EvidenceKind.OBSERVATION, reconnect_after_messages=None, reconnect_after_seconds=None, profile_name=None):
        from app.collection.supervised import profile, bound_native
        policy = profile(profile_name) if profile_name else None
        for value, limit in ((max_messages, policy['group_messages'] if policy else 5000), (max_connections, 5)):
            if type(value) is not int or not 1 <= value <= limit:
                raise ValueError('invalid stream bound')
        if not 0 < duration <= 300 or not 0 < stale_seconds <= 120 or not 0 < snapshot_timeout <= 30:
            raise ValueError('invalid time bound')
        if reconnect_after_messages is not None and (type(reconnect_after_messages) is not int or reconnect_after_messages < 1):
            raise ValueError('invalid deliberate reconnect bound')
        if reconnect_after_seconds is not None and not 0 < reconnect_after_seconds < duration:
            raise ValueError("invalid timed reconnect bound")
        self.reconnect_after_seconds = reconnect_after_seconds
        self.engine = BookReconstructor(markets, kind=kind)
        self.factory, self.sleep = factory, sleep
        self.duration, self.max_messages, self.max_connections = duration, max_messages, max_connections
        self.stale_seconds, self.snapshot_timeout = stale_seconds, snapshot_timeout
        self.reconnect_after_messages = reconnect_after_messages
        self.connection, self.closed, self.transport_health = None, False, 'not_started'
        self.diagnostics, self.reason, self.message_count = [], 'not_started', 0
        if policy: bound_native(self)

    async def _close_connection(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                await asyncio.wait_for(connection.close(), 3)
            except (Exception,):
                pass
        self.transport_health = 'disconnected'
        self.engine.invalidate()

    async def aclose(self):
        self.closed = True
        await self._close_connection()

    async def run(self):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.duration
        try:
            for attempt in range(self.max_connections):
                if self.closed or loop.time() >= deadline or self.message_count >= self.max_messages:
                    break
                try:
                    self.connection = await asyncio.wait_for(self.factory(), min(10, deadline - loop.time()))
                    self.transport_health = 'connected'
                    command = self.engine.begin(attempt + 1)
                    generation = self.engine.generation
                    await asyncio.wait_for(self.connection.send(json.dumps(command)), min(5, deadline - loop.time()))
                    self.diagnostics.append({'event': 'subscribed_request', 'generation': generation})
                    connected_at = loop.time()
                    initial_deadline = connected_at + self.snapshot_timeout
                    local_count = 0
                    while not self.closed and self.message_count < self.max_messages and loop.time() < deadline:
                        if len(self.engine.sides) != len(self.engine.markets) and loop.time() >= initial_deadline:
                            raise RecoveryRequired('initial snapshot deadline')
                        if attempt == 0 and self.reconnect_after_seconds and loop.time() - connected_at >= self.reconnect_after_seconds:
                            self.diagnostics.append({"event": "deliberate_timed_disconnect", "generation": generation})
                            break
                        try:
                            body = await asyncio.wait_for(self.connection.recv(), min(0.5, deadline - loop.time()))
                        except TimeoutError:
                            now = datetime.now(timezone.utc)
                            for mid, book in tuple(self.engine.last.items()):
                                if book.sync == BookSync.SYNCHRONIZED and (now - book.raw.received_at).total_seconds() > self.stale_seconds and book.receipt_freshness != ReceiptFreshness.STALE:
                                    stale = replace(book, receipt_freshness=ReceiptFreshness.STALE)
                                    self.engine.last[mid] = stale
                                    yield stale
                            if len(self.engine.sides) != len(self.engine.markets) and loop.time() >= initial_deadline:
                                raise RecoveryRequired('initial snapshot deadline')
                            continue
                        self.message_count += 1
                        local_count += 1
                        book = self.engine.feed(body, generation, datetime.now(timezone.utc))
                        if book is not None:
                            book = replace(book, receipt_freshness=ReceiptFreshness.RECENT)
                            self.engine.last[book.raw.ref.market_id] = book
                            yield book
                        if attempt == 0 and self.reconnect_after_messages and local_count >= self.reconnect_after_messages:
                            self.diagnostics.append({'event': 'deliberate_disconnect', 'generation': generation})
                            break
                except asyncio.CancelledError:
                    self.reason = 'cancelled'
                    raise
                except Exception:
                    self.diagnostics.append({'event': 'connection_or_protocol_failure', 'attempt': attempt + 1})
                finally:
                    await self._close_connection()
                for book in self.engine.last.values():
                    yield book
                if attempt + 1 < self.max_connections and not self.closed:
                    await self.sleep(min(2 ** attempt, max(0, deadline - loop.time())))
            self.reason = 'bounded_complete'
        finally:
            await self.aclose()
