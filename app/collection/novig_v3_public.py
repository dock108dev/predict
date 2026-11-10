"""Bounded, read-only discovery of Novig v3 public live source availability.

Public responses are cached and have no lifecycle sequence. They are inventory
observations only: they never assert an executable post-reset book or publish a
fee. A source-bound sequenced lifecycle is required before admitting live quotes.
"""
import asyncio
import json
import httpx

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
        self.metrics = dict(requests=0, events=0, markets=0, books=0,
            live_qualified=0, gap='novig_post_reset_sequence_evidence_missing', state='initializing')

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
            return value, dict(date=response.headers.get('date'), age=response.headers.get('age'),
                cache_control=response.headers.get('cache-control'), etag=response.headers.get('etag'))

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
