"""Read-only Retail market images for the Dashboard's selected Polymarket US books."""

import asyncio
import json
from contextlib import suppress
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from app.adapters import polymarket_us as pmus
from app.adapters.polymarket_us_stream import AuthenticatedTransport, WS_URL, subscription
from app.comparison.source_clock import NATIVE_BOOK_MAX_AGE_SECONDS
from app.storage.store import exact_time, stamp

from .native_experiment_depth import ERRORS, polymarket_ladders
from .venue_access import load_credentials

MAX_SLUGS = 32
INITIAL_IMAGE_WAIT = .5
BOOK_AGE = timedelta(seconds=NATIVE_BOOK_MAX_AGE_SECONDS)


class DashboardMarketStream:
    def __init__(self, *, now, allowed, credentials=None, transport=None):
        self.now, self.allowed = now, allowed
        self.credentials = credentials or (lambda: load_credentials(['polymarket_us'])['polymarket_us'])
        self.transport = transport or (lambda credential: AuthenticatedTransport(
            credential.signer, allow_connection=True)())
        self.wanted = frozenset()
        self.images = {}
        self.incoming = asyncio.Event()
        self.task = None
        self.backoff_until = 0

    async def close(self):
        self.wanted = frozenset()
        self.images.clear()
        task, self.task = self.task, None
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def read(self, bindings, cutoff):
        bindings = {cid: binding for cid, binding in bindings.items()
                    if binding['venue'] == 'polymarket_us' and not binding['reason']}
        slugs = frozenset(sorted({binding['route'] for binding in bindings.values()})[:MAX_SLUGS])
        if not slugs or not self.allowed():
            await self.close()
            return {}
        self.wanted = slugs
        now = asyncio.get_running_loop().time
        if self.task is None or self.task.done():
            if now() < self.backoff_until:
                return {}
            self.task = asyncio.create_task(self._run())
        remaining = min(INITIAL_IMAGE_WAIT, (cutoff - self.now()).total_seconds())
        if remaining > 0:
            with suppress(TimeoutError):
                async with asyncio.timeout(remaining):
                    while not slugs <= self.images.keys() and not self.task.done():
                        self.incoming.clear()
                        await self.incoming.wait()
        if not self.allowed():
            return {}
        at = self.now()
        result = {}
        for cid, binding in bindings.items():
            image = self.images.get(binding['route'])
            if image is None or binding['route'] not in slugs:
                continue
            source = stamp(image['source_at'])
            expires = min(source + BOOK_AGE, stamp(binding['scheduled_start']),
                          stamp(binding['terms_valid_until']))
            if not stamp(image['received_at']) <= at <= cutoff or expires <= at:
                continue
            result[cid] = dict(binding, complete=False, reason=image['reason'],
                levels=image['levels'][binding['native_side']], native_book=image['native_book'],
                source_at=image['source_at'], received_at=image['received_at'],
                valid_until=expires.isoformat(), receipts=[image['receipt']])
        return result

    async def _run(self):
        now = asyncio.get_running_loop().time
        failures = 0
        try:
            try:
                credential = self.credentials()
            except RuntimeError:
                self.backoff_until = now() + 900
                return
            while self.wanted and self.allowed():
                if self.backoff_until > now():
                    await asyncio.sleep(self.backoff_until - now())
                if not self.wanted or not self.allowed():
                    break
                socket = None
                try:
                    socket = await self.transport(credential)
                    await self._read_connection(socket, credential)
                except Exception:
                    # Never log connection, signature, or book message text.
                    failures += 1
                    self.backoff_until = now() + min(60, 2 ** min(failures, 6))
                finally:
                    self.images.clear()
                    if socket is not None:
                        with suppress(Exception):
                            await socket.close()
        finally:
            self.incoming.set()

    async def _read_connection(self, socket, credential):
        subscribed, request = frozenset(), None
        while self.wanted and self.allowed():
            if self.wanted != subscribed:
                self.images.clear()
                if request:
                    async with asyncio.timeout(2):
                        await socket.send(json.dumps({'unsubscribe': {'requestId': request}}))
                        while True:
                            _, data = await self._frame(socket, credential)
                            if data.get('requestId') == request and data.get('unsubscribed') is True:
                                break
                subscribed = self.wanted
                if not subscribed or not self.allowed():
                    break
                request = str(uuid4())
                requested_at = self.now().isoformat()
                command = subscription(sorted(subscribed), request, debounced=True)
                async with asyncio.timeout(2):
                    await socket.send(json.dumps(command))
            try:
                async with asyncio.timeout(.25):
                    raw, data = await self._frame(socket, credential)
            except TimeoutError:
                continue
            if data.get('requestId') != request:
                continue
            if 'error' in data:
                raise ValueError('polymarket_us_dashboard_subscription_failed')
            if (data.get('subscriptionType') != 'SUBSCRIPTION_TYPE_MARKET_DATA'
                    or set(data) != {'requestId', 'subscriptionType', 'marketData'}):
                continue
            book = data['marketData']
            if not isinstance(book, dict) or book.get('marketSlug') not in subscribed & self.wanted:
                continue
            self._image(book, raw, requested_at)

    @staticmethod
    async def _frame(socket, credential):
        raw = await socket.recv()
        raw = raw.encode() if isinstance(raw, str) else raw
        credential.check(raw)
        return raw, pmus.decode(raw)

    def _image(self, book, raw, requested_at):
        slug = book['marketSlug']
        received = self.now().isoformat()
        try:
            source = book['transactTime']
            order = exact_time(source)
            prior = self.images.get(slug)
            if order > exact_time(received) or (prior and order <= prior['source_order']):
                return
            state = pmus.state(book['state']).value
            if state == 'active':
                levels, original = polymarket_ladders(book)
                reason = None
            elif state in ('suspended', 'closed'):
                reason = 'native_market_halted'
                levels, original = dict(Long=[], Short=[]), dict(bids=[], offers=[])
            else:
                return
        except ERRORS:
            return
        self.images[slug] = dict(source_order=order, source_at=source, received_at=received,
            reason=reason, levels=levels, native_book=dict(marketSlug=slug, state=book['state'],
                transactTime=source, **original), receipt=dict(source_url=WS_URL, market_slug=slug,
                source='polymarket_us_market_stream', sha256=sha256(raw).hexdigest(),
                requested_at=requested_at, received_at=received))
        self.incoming.set()
