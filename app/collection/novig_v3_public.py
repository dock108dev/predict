"""Bounded, read-only discovery and official catalog evidence from Novig v3.

Catalog responses can confirm exact instruments and pregame terms. A
source-bound sequenced lifecycle remains required to qualify a live fill.
"""
import asyncio
from hashlib import sha256
import json
import time

import httpx
import psycopg

from app.comparison.sgo_native_binding import capture_catalog
from app.storage import sgo_native_catalog
from app.storage.store import connect, now

HOST = 'https://api.novig.com'
LEAGUES = 'NFL,NCAAF,NBA,NCAAB,MLB,NHL'
MAX_BODY = 1_000_000


class NovigPublicDiscovery:
    def __init__(self, service, *, transport=None):
        self.service = service
        self.transport = transport
        self.closed = False
        self.client = None
        self.last_books = {}
        self.catalog_attempted = {}
        self.metrics = dict(requests=0, events=0, markets=0, books=0,
            live_qualified=0, gap='novig_post_reset_sequence_evidence_missing', state='initializing',
            sgo_catalog_requests=0, sgo_catalog_events=0, sgo_catalog_outcomes=0)

    async def read(self, path, params):
        if self.closed or not self.service.dispatch:
            raise asyncio.CancelledError()
        self.metrics['requests'] += 1
        async with self.client.stream('GET', HOST + path, params=params) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    raise ValueError('novig_public_body_limit')
            value = json.loads(body)
            return value, dict(path=path, observed_at=now(), sha256=sha256(body).hexdigest(),
                date=response.headers.get('date'), age=response.headers.get('age'),
                cache_control=response.headers.get('cache-control'), etag=response.headers.get('etag'))

    def catalog_enabled(self):
        return (not self.closed and self.service.dispatch and not self.service.globally_stopped
                and not {'novig','sportsgameodds'}.intersection(self.service.paused_sources)
                and self.service.config['aggregate_provider'] == 'sportsgameodds')

    def catalog_targets(self, attempted):
        with connect() as db:
            return sgo_native_catalog.targets(db, at=now(), exclude=attempted)

    def save_catalog(self, event_id, witness):
        if self.catalog_enabled():
            with connect() as db:
                if self.catalog_enabled():
                    sgo_native_catalog.write(db, event_id, witness)
                    return True
        return False

    async def poll_sgo_catalog(self):
        if not self.catalog_enabled():
            return
        at = time.monotonic()
        self.catalog_attempted = {event_id:due for event_id,due in self.catalog_attempted.items() if due > at}
        targets = await asyncio.to_thread(self.catalog_targets, list(self.catalog_attempted))
        for event_id, native_event_id, linked_outcomes, sgo_frame in targets:
            if not self.catalog_enabled():
                return
            self.catalog_attempted[event_id] = at + 180
            self.metrics['sgo_catalog_requests'] += 1
            event, event_receipt = await self.read('/v3/public/catalog/events/' + native_event_id, {})
            params = dict(event=native_event_id, marketType='MONEY,SPREAD,TOTAL', limit=240)
            pages = []
            for _ in range(2):
                if not self.catalog_enabled():
                    return
                self.metrics['sgo_catalog_requests'] += 1
                page, receipt = await self.read('/v3/public/catalog/markets', params)
                pages.append((page, receipt))
                cursor = page.get('next') if isinstance(page, dict) else None
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not 0 < len(cursor) <= 1024 or cursor == params.get('after'):
                    raise ValueError('novig_public_market_cursor_invalid')
                params = dict(params, after=cursor)
            witness = capture_catalog(event_id, native_event_id, event, event_receipt, pages, linked_outcomes,
                                      sgo_frame=sgo_frame)
            if await asyncio.to_thread(self.save_catalog, event_id, witness):
                self.metrics['sgo_catalog_events'] += 1
                self.metrics['sgo_catalog_outcomes'] += len(witness['markets'])
                self.metrics['sgo_catalog_state'] = 'observed' if witness['markets'] else 'linked_outcomes_unobserved'

    async def poll(self):
        events, _ = await self.read('/v3/public/catalog/events',
            dict(league=LEAGUES, status='OPEN_INGAME', limit=100))
        if not isinstance(events, dict) or not isinstance(events.get('items'), list) or events.get('next'):
            raise ValueError('novig_public_event_inventory_incomplete')
        live = [e for e in events['items'] if e.get('status') == 'OPEN_INGAME' and e.get('league') in LEAGUES.split(',')]
        self.metrics.update(events=len(live), markets=0, books=0, state='observed',
            gap='novig_post_reset_sequence_evidence_missing' if live else 'novig_no_live_events_observed')
        # Explicit per-cycle request and object bounds; no cursor is silently
        # represented as a complete market inventory.
        for event in live[:4]:
            markets, _ = await self.read('/v3/public/catalog/markets',
                dict(event=event['eventId'], marketType='MONEY,SPREAD,TOTAL', limit=20))
            if not isinstance(markets, dict) or not isinstance(markets.get('items'), list):
                raise ValueError('novig_public_market_inventory_invalid')
            self.metrics['markets'] += len(markets['items'])
            if markets.get('next'):
                self.metrics['gap'] = 'novig_public_market_inventory_incomplete'
            for market in markets['items'][:2]:
                if market.get('eventId') != event['eventId'] or not market.get('marketId'):
                    raise ValueError('novig_public_event_market_conflict')
                book, _ = await self.read('/v3/public/catalog/markets/' + market['marketId'] + '/book', dict(depth=1))
                if book.get('marketId') != market['marketId'] or not isinstance(book.get('seq'), int):
                    raise ValueError('novig_public_book_identity_invalid')
                previous = self.last_books.get(market['marketId'])
                if previous is not None:
                    if book['seq'] < previous['seq']:
                        self.metrics['gap'] = 'novig_public_book_sequence_regressed'
                        continue
                    if book['seq'] == previous['seq'] and book != previous:
                        self.metrics['gap'] = 'novig_public_book_sequence_conflict'
                        continue
                if market['marketId'] not in self.last_books and len(self.last_books) >= 128:
                    self.last_books.pop(next(iter(self.last_books)))
                self.last_books[market['marketId']] = book
                self.metrics['books'] += 1
        return dict(self.metrics)

    async def run(self):
        async with httpx.AsyncClient(transport=self.transport, timeout=8, follow_redirects=False) as client:
            self.client = client
            try:
                # Avoid an immediate burst on a process restart while the
                # provider's edge throttle may still be in effect.
                await asyncio.sleep(60)
                while not self.closed and self.service.dispatch:
                    delay = 60
                    try:
                        await self.poll_sgo_catalog()
                    except httpx.HTTPStatusError as exc:
                        status = exc.response.status_code
                        self.metrics['sgo_catalog_state'] = 'novig_public_http_' + str(status)
                        if status == 429:
                            retry = exc.response.headers.get('Retry-After','')
                            delay = max(60, min(int(retry),3600)) if retry.isdigit() else 300
                            await asyncio.sleep(delay)
                            continue
                    except (httpx.HTTPError, psycopg.Error, ValueError, KeyError, TypeError) as exc:
                        self.metrics['sgo_catalog_state'] = 'novig_public_catalog_unavailable:' + type(exc).__name__
                    try:
                        await self.poll()
                    except httpx.HTTPStatusError as exc:
                        status=exc.response.status_code
                        retry=exc.response.headers.get('Retry-After','')
                        if status == 429:
                            delay=max(60, min(int(retry),3600)) if retry.isdigit() else 300
                        self.metrics.update(state='unavailable', gap='novig_public_http_'+str(status),
                                            error='HTTPStatusError',retry_after_seconds=delay)
                    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                        self.metrics.update(state='unavailable', gap='novig_public_source_unavailable', error=type(exc).__name__)
                    await asyncio.sleep(delay)
            finally:
                self.client = None

    async def close(self):
        self.closed = True
        if self.client is not None:
            await self.client.aclose()
