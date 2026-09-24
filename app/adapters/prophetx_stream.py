"""Bounded Pusher-compatible event transport; no private account subscriptions."""
import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import quote, urlsplit

from app.adapters.prophetx import (APIError, Response, book, decode, identity,
    integer_or_none, label, obj, rows)
from app.models.core import BookSync, ReceiptFreshness, SourceTimeProgress


def websocket_url(config):
    config = obj(config)
    key = label(config.get('key'))
    host = config.get('ws_host')
    if not host:
        cluster = label(config.get('cluster'))
        if not re.fullmatch(r'[a-z0-9-]+', cluster):
            raise ValueError('invalid cluster')
        host = f'ws-{cluster}.pusher.com'
    if not isinstance(host, str):
        raise ValueError('invalid websocket host')
    parsed = urlsplit(host if '://' in host else 'wss://' + host)
    if (parsed.scheme != 'wss' or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in ('', '/') or not parsed.hostname):
        raise ValueError('expected secure websocket host')
    return f'wss://{parsed.netloc}/app/{quote(key, safe="")}?protocol=7&client=prediction-arb&version=1&flash=false'


def frame(body):
    envelope = obj(decode(body))
    data = envelope.get('data', {})
    if isinstance(data, str):
        data = decode(data)
    return envelope, obj(data)


def market_message(body, scope, response):
    envelope, data = frame(body)
    if envelope.get('event') != 'market_selections' or data.get('change_type') != 'market_selections':
        raise ValueError('not a market selection message')
    op = data.get('op')
    if op not in ('c', 'u', 'd'):
        raise ValueError('unknown operation')
    encoded = data.get('payload')
    if not isinstance(encoded, str):
        raise ValueError('missing base64 payload')
    try:
        payload = obj(decode(base64.b64decode(encoded, validate=True)))
    except (ValueError, TypeError):
        raise ValueError('invalid nested market payload') from None
    eid = identity(payload.get('sport_event_id'))
    if eid != identity(scope.get('event_id')):
        raise ValueError('scope/event mismatch')
    info = obj(payload.get('info'))
    # info.id identifies the strike's current selection image; market_id is also
    # retained raw and can identify its containing market. Never overwrite it.
    identity(payload.get('market_id'))
    return book(response, eid, info, streaming=True, operation=op,
        native_timestamp=integer_or_none(data.get('timestamp')))


class Stream:
    def __init__(self, adapter, market_ids, *, connector=None, duration=60,
                 message_budget=200, byte_budget=2_000_000, reconnects=1,
                 receipt_seconds=20, handshake_timeout=10, observer=None):
        if not market_ids or any(x not in adapter.markets for x in market_ids):
            raise LookupError('discover requested markets first')
        if min(duration, message_budget, byte_budget, receipt_seconds, handshake_timeout) <= 0 or reconnects < 0:
            raise ValueError('invalid stream budgets')
        self.adapter, self.market_ids = adapter, market_ids
        self.event_ids = tuple(dict.fromkeys(adapter.markets[x][0] for x in market_ids))
        if len(self.event_ids) != 1:
            raise ValueError('ProphetX stream is bounded to one event')
        self.connector = connector
        self.duration, self.message_budget, self.byte_budget = duration, message_budget, byte_budget
        self.reconnects, self.receipt_seconds = reconnects, receipt_seconds
        self.handshake_timeout = handshake_timeout
        self.socket = None
        self.closed = False
        self.health = 'disconnected'
        self.generation = 0
        self.messages = self.bytes = 0
        self.frame_counts = {}
        self.filtered_markets = 0
        self.books = {}
        self.timestamp_highwater = {}
        self.diagnostics = []
        self.disconnect_requested = False
        self.observer = observer
        self.stage = "idle"

    def invalidate(self):
        for mid, value in list(self.books.items()):
            self.books[mid] = replace(value, native_windows=None,
                native_sync=BookSync.UNSYNCHRONIZED, sync=BookSync.UNSYNCHRONIZED,
                outcomes=(), normalized_quotes=())
            self.adapter.native_books[mid] = self.books[mid]

    async def disconnect(self):
        self.disconnect_requested = True
        if self.socket:
            await self.socket.close()

    async def aclose(self):
        self.closed = True
        self.invalidate()
        self.health = 'disconnected'
        if self.socket:
            await self.socket.close()

    async def receive(self):
        body = await self.socket.recv()
        if not isinstance(body, (str, bytes)):
            raise ValueError('invalid frame')
        self.messages += 1
        self.bytes += len(body.encode() if isinstance(body, str) else body)
        if self.messages > self.message_budget or self.bytes > self.byte_budget:
            raise APIError()
        if isinstance(body, bytes):
            body = body.decode('utf-8')
        # Count only known protocol names; arbitrary payload text never enters diagnostics.
        event = obj(decode(body)).get('event')
        known = ('pusher:connection_established', 'pusher:signin_success',
            'pusher_internal:subscription_succeeded', 'pusher:ping', 'pusher:pong',
            'pusher:error', 'market_selections')
        category = event if event in known else 'other'
        self.frame_counts[category] = self.frame_counts.get(category, 0) + 1
        return body

    async def send(self, event, data):
        await self.socket.send(json.dumps({'event': event, 'data': data}))

    async def expected(self, name, channel=None):
        async with asyncio.timeout(self.handshake_timeout):
            while True:
                raw = await self.receive()
                env, data = frame(raw)
                if env.get('event') == 'pusher:ping':
                    await self.send('pusher:pong', {})
                    continue
                if env.get('event') == name and (channel is None or env.get('channel') == channel):
                    return data
                # Don't silently drop market frames while waiting for another ack.
                raise ValueError('unexpected handshake frame')

    async def connect(self):
        self.stage = 'connection_config'
        r = await self.adapter.client.request('GET', '/websocket/connection-config')
        config = decode(r.body)
        self.diagnostics.append({"event":"connection_config", "fields":list(config), "ws_host":config.get("ws_host"), "cluster":config.get("cluster")})
        url = websocket_url(config)
        self.stage = "socket_connect"
        if self.connector is None:
            from websockets.asyncio.client import connect
            self.connector = connect
        self.socket = await self.connector(url, open_timeout=self.handshake_timeout,
            close_timeout=2, ping_interval=15, ping_timeout=10, max_size=self.byte_budget)
        self.generation += 1
        self.health = 'connecting'
        self.stage = 'connection_established'
        data = await self.expected('pusher:connection_established')
        socket_id = label(data.get('socket_id'))
        self.stage = 'register'
        r = await self.adapter.client.request('POST', '/v4/mm/websocket', data={
            'socket_id': socket_id, 'service': 'pusher',
            'subscriptions': [{'type': 'event', 'ids': list(self.event_ids)}]})
        data = obj(obj(decode(r.body))['data'])
        if data.get('success') is not True or data.get('rejected'):
            raise ValueError('subscription rejected')
        count, limit = data.get('channel_count'), data.get('channel_limit')
        if type(count) is not int or type(limit) is not int or not 0 <= count <= limit:
            raise ValueError('invalid channel allowance')
        channels = {}
        for channel in rows(data.get('authorized_channel')):
            channel = obj(channel)
            scope = channel.get('scope')
            # Never subscribe to user/account or broad broadcast channels.
            if not isinstance(scope, dict) or str(scope.get('event_id')) not in self.event_ids or scope.get('sub_type'):
                continue
            if not any(obj(x).get('name') == 'market_selections' for x in rows(channel.get('binding_events'))):
                continue
            channels[label(channel.get('channel_name'))] = channel
        if len(channels) != 1:
            raise ValueError('expected one authorized event channel')
        self.stage = 'signin'
        auth = obj(data.get('authenticated'))
        await self.send('pusher:signin', {'auth': label(auth.get('auth')), 'user_data': label(auth.get('user_data'))})
        await self.expected('pusher:signin_success')
        self.stage = "subscribe"
        for name, channel in channels.items():
            await self.send('pusher:subscribe', {'channel': name, 'auth': label(channel.get('auth'))})
            await self.expected('pusher_internal:subscription_succeeded', name)
        self.health = 'connected'
        self.stage = 'market_data'
        self.diagnostics.append({'event': 'subscribed', 'generation': self.generation,
            'channel_count': count, 'channel_limit': limit,
            'requested_event_ids': list(self.event_ids),
            'authorized_event_ids': [str(c['scope']['event_id']) for c in channels.values()],
            'market_selections_binding': True})
        return channels

    async def updates(self):
        pending = None
        try:
            async with asyncio.timeout(self.duration):
                for attempt in range(self.reconnects + 1):
                    try:
                        channels = await self.connect()
                        connection_start = time.monotonic()
                        while not self.closed:
                            # Finite sessions cannot outlive config refresh interval;
                            # renew auth on the transport without promoting book age.
                            if time.monotonic() - connection_start >= 900:
                                raise ConnectionError('renew configuration')
                            if pending is None:
                                pending = asyncio.create_task(self.receive())
                            done, _ = await asyncio.wait({pending}, timeout=min(self.receipt_seconds, 5))
                            if not done:
                                now = datetime.now(timezone.utc)
                                for mid, current in list(self.books.items()):
                                    if current.receipt_freshness != ReceiptFreshness.STALE and current.raw.receipt_age(now).total_seconds() >= self.receipt_seconds:
                                        stale = replace(current, receipt_freshness=ReceiptFreshness.STALE)
                                        self.books[mid] = stale
                                        self.adapter.native_books[mid] = stale
                                        yield stale
                                continue
                            body = pending.result()
                            pending = None
                            env, data = frame(body)
                            event = env.get('event')
                            if event == 'pusher:ping':
                                await self.send('pusher:pong', {})
                                continue
                            if event == 'pusher:pong':
                                continue
                            if event == 'pusher:error':
                                raise ValueError('stream error')
                            if event != 'market_selections':
                                continue
                            channel = channels.get(env.get('channel'))
                            if channel is None:
                                raise ValueError('unregistered market channel')
                            response = Response(body, 'prophetx:event:market_selections', datetime.now(timezone.utc))
                            if self.observer:
                                self.observer(response)
                            image = market_message(body, channel['scope'], response)
                            mid = image.raw.ref.market_id
                            if mid not in self.market_ids:
                                self.filtered_markets += 1
                                continue
                            native_time = image.native_timestamp
                            previous = self.timestamp_highwater.get(mid)
                            progress = (SourceTimeProgress.MISSING if native_time is None else
                                SourceTimeProgress.FIRST if previous is None else
                                SourceTimeProgress.ADVANCED if native_time > previous else
                                SourceTimeProgress.REPEATED if native_time == previous else
                                SourceTimeProgress.REGRESSED)
                            if native_time is not None and (previous is None or native_time > previous):
                                self.timestamp_highwater[mid] = native_time
                            image = replace(image, native_timestamp_progress=progress)
                            self.books[mid] = image
                            self.adapter.native_books[mid] = image
                            yield image
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self.invalidate()
                        self.health = 'disconnected'
                        # No exception text, frames, socket IDs or auth material.
                        self.diagnostics.append({'event': 'invalidated', 'reason': type(exc).__name__, 'stage':self.stage, 'generation': self.generation})
                        for current in self.books.values():
                            yield current
                        if attempt == self.reconnects or self.closed:
                            raise APIError() from None
                    finally:
                        if pending:
                            pending.cancel()
                            await asyncio.gather(pending, return_exceptions=True)
                            pending = None
                        if self.socket:
                            await self.socket.close()
                            self.socket = None
                    if self.closed:
                        break
                    await self.adapter.client.sleep(min(2 ** attempt, 8))
        finally:
            await self.aclose()
