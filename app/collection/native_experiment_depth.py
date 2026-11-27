"""Bounded public book reads for native markets matched to frozen paper offers."""

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from fractions import Fraction as F
from hashlib import sha256
from urllib.parse import quote

import httpx

from app.adapters import kalshi, polymarket_us
from app.comparison import current_pregame, scanner_kalshi, scanner_polymarket
from app.comparison.game_phase import original_price_phase
from app.comparison.sgo_reference import OPPOSITE
from app.comparison.snapshot_fee_outcome import reviews
from app.comparison.source_clock import NATIVE_BOOK_MAX_AGE_SECONDS
from app.dashboard.current_contract import price
from app.dashboard.session_projection import stable
from app.fees.product_schedules import for_offer, read_all
from app.storage import current_native_desk, experiment_depth, native_market_metadata
from app.storage.current_rows import event_id as current_event_id
from app.storage.store import exact_time, stamp
from .public_fee_refresh import REVIEW_WINDOW


VENUES = ('kalshi', 'polymarket_us')
DEPTH = 32
MAX_MARKETS_PER_DECISION = 64
HEADER_FIELDS = ('date', 'age', 'cache-control', 'etag', 'last-modified',
                 'cf-cache-status', 'x-cache', 'expires', 'retry-after')
ERRORS = (ArithmeticError, AttributeError, KeyError, StopIteration, TypeError, ValueError, OSError)
PMUS_TERMS = 'https://docs.polymarket.us/fees'
PMUS_CURRENT_FROM = stamp('2026-11-25T21:45:00-05:00')
PMUS_CURRENT_HASH = 'feb258b62257967f21f390de474bd1e7d7486a1da02f62ab54cf07a745237f87'


def _pmus_fee(products, at):
    # The historic approved rate is unsafe after the new upper tier .11.
    # Admit the new schedule only from a receipt independently fetched by the
    # existing ordinary fee-document owner. This affects only the depth model.
    if at >= PMUS_CURRENT_FROM:
        attempt = (products.get(scanner_polymarket.PRODUCT) or {}).get('last_attempt') or {}
        evidence = attempt.get('retrieval') or {}
        doc = evidence.get('document') or {}
        if (evidence.get('normalized_sha256') != PMUS_CURRENT_HASH
                or doc.get('url') != PMUS_TERMS or doc.get('http_status') != 200):
            raise ValueError('polymarket_us_current_terms_unreviewed')
        retrieved = stamp(doc['retrieved_at'])
        if not PMUS_CURRENT_FROM <= retrieved <= at <= retrieved + REVIEW_WINDOW:
            raise ValueError('polymarket_us_current_terms_unreviewed')
        return dict(model='polymarket_us_standard_taker_bound', coefficient='0.11',
                    api_coefficient='0.0695', rebates='0', schedule_revision=PMUS_CURRENT_HASH,
                    observed_at=doc['retrieved_at'], source_url=PMUS_TERMS,
                    effective_from=PMUS_CURRENT_FROM.isoformat())
    review = scanner_polymarket._fee_review(for_offer(products, dict(venue='polymarket_us'), at), at)
    return dict(model='polymarket_us_standard_taker_bound', coefficient=review['fee_rate'],
                schedule_revision=review['verification_revision'])


def _selected(record, *, at):
    quote_row = record['quote']
    venue = quote_row['venue']
    if quote_row['source']['provider'] != venue or not record.get('verified'):
        raise ValueError('native_identity_unmatched')
    family, side, line = current_pregame.reference_key(record)
    # Integer scores cannot land on the half-line. Integer lines require a
    # separate equality payout comparison to the SGO quote, so remain unknown.
    if line is None or line.denominator != 2:
        raise ValueError('native_settlement_equivalence_unverified')
    phase = original_price_phase(record, at.isoformat())
    metadata = record.get('comparison_source_metadata') or {}
    if phase['state'] != 'scheduled' or phase['reason'] is not None or (
            record.get('comparison_scope') or {}).get('overtime') != 'included':
        raise ValueError('native_pregame_scope_unverified')
    source = quote_row['source']
    if metadata.get('native_key') != [venue, source['native_event_id'], source['native_market_id'],
                                       source['native_outcome_id'], source['native_side']]:
        raise ValueError('native_identity_unmatched')
    return venue, family, side, line


def _native_binding(db, record, opposite, *, at, source_reviews, products):
    q = record['quote']
    venue, source = q['venue'], q['source']
    metadata = record['comparison_source_metadata']
    event = record['event']
    family = record['market_identity']['family']
    event_id, market_id, outcome_id = (source['native_' + field] for field in ('event_id', 'market_id', 'outcome_id'))
    native_material = native_market_metadata.census_body(db, venue, event_id, market_id)
    if not native_material or stable(native_material) != metadata['material_sha256']:
        raise ValueError('native_market_terms_unavailable')
    # Preserve the established scanner's exact selected-market quantity and
    # fee contracts. The depth experiment uses its public direct taker model.
    if venue == 'kalshi':
        selected = metadata['selected_market_observation']
        if stamp(selected['source']['received_at']) > at:
            raise ValueError('native_market_terms_unavailable')
        review = for_offer(products, dict(venue=venue), at, fallback=source_reviews[venue])
        evidence = dict(metadata, market=native_material, material_sha256=selected['material_sha256'],
            event=dict(league=event['competition']), group=dict(market=family, period='full_game'),
            fee_review=review)
        grid, _ = scanner_kalshi._market_grid(q, evidence)
        model, reviewed, _ = scanner_kalshi._schedule(q, evidence, at)
        fee = dict(model='kalshi_direct_taker_bound', terms=model, schedule_revision=reviewed['metadata_revision'])
        route, bands = market_id, grid['price_ranges']
    else:
        listing = metadata['public_retail_observation']
        if (str(native_material.get('id')) != market_id or listing['material_sha256'] != metadata['material_sha256']
                or listing['long'] != (source['native_side'] == 'Long')
                or polymarket_us.side_ids(native_material).get(listing['long']) != outcome_id):
            raise ValueError('native_identity_unmatched')
        route = polymarket_us.identifier(native_material.get('slug'))
        grid = scanner_polymarket._grid(q, listing)
        tick = F(grid['tick'])
        # The public standard taker bound supports these prices only.
        bands = [[grid['minimum_price'], grid['maximum_price'], str(tick)]]
        fee = _pmus_fee(products, at)
    return dict(venue=venue, event_id=event_id, market_id=market_id, outcome_id=outcome_id,
        opposite_outcome_id=opposite['quote']['source']['native_outcome_id'], native_side=source['native_side'],
        source_price=str(price(q)), route=route, price_bands=bands, payout_usd='1',
        quantity_increment=grid['increment'], quantity_minimum=grid['minimum'], fee=fee,
        market_revision=metadata['material_sha256'], scheduled_start=event['scheduled_start'],
        levels=[], receipts=[], complete=False, reason=None)


def native_bindings(db, task, at, pregame_offers, *, venues=VENUES):
    """Attach existing exact native identity to the same pregame SGO quote key."""
    at = stamp(at)
    event = task['event']
    start = stamp(event['starts_at'])
    if not venues or at >= start:
        return {}
    requests = defaultdict(list)
    results = {}
    for offer in pregame_offers:
        record = offer.get('record', offer)
        q = record['quote']
        if q['venue'] not in venues or q['state'] != 'available':
            continue
        key = experiment_depth.offer_key(record)
        selection = dict(venue=q['venue'], complete=False, levels=[], receipts=[], reason='native_identity_unmatched')
        results[key] = selection
        try:
            family, side, line = current_pregame.reference_key(record)
            if family not in ('spread', 'total') or record['market_identity']['period'] != 'full_game':
                continue
            if q['venue'] == 'polymarket_us' and q['source']['provider'] == 'sportsgameodds':
                link = (record.get('comparison_source_metadata') or {}).get('bookmaker_market_link') or {}
                # Existing price routing treats this label as US for display.
                # Require a venue-domain instrument link for execution.
                if link.get('host') not in ('polymarket.us', 'www.polymarket.us', 'gateway.polymarket.us'):
                    selection['reason'] = 'provider_venue_fee_applicability_unestablished'
                    continue
            requests[q['venue'], family, side, line].append((key, record))
        except ERRORS:
            continue
    if not requests:
        return results
    rows = db.execute('''SELECT id,provider FROM public.current_event
        WHERE provider=ANY(%s) AND scheduled_start::timestamptz=%s
          AND facts->>'competition'=%s AND facts->>'home'=%s AND facts->>'away'=%s
        ORDER BY id LIMIT 9''', (list(venues), start, event['league'], event['home'], event['away'])).fetchall()
    if not rows or len(rows) > 8:
        return results
    records, _, _ = current_native_desk.active_records(db, at=at, venues=list(venues),
        event_ids=[row['id'] for row in rows], posted=True)
    expected = (event['league'], start, event['home'], event['away'])
    mappings, instruments, own_keys = defaultdict(list), defaultdict(list), set()
    for record in records:
        try:
            if current_native_desk.supported_occurrence(record) != expected:
                continue
            identity = _selected(record, at=at)
            q = record['quote']
            source = q['source']
            if stamp(q['times']['received_at']) > at:
                continue
            # Separate native contracts with identical team names stay separate.
            source_key = (q['venue'], source['native_event_id'], source['native_market_id'])
            side_key = source_key + (source['native_outcome_id'],)
            if side_key in own_keys:
                mappings[identity].append(None)
            else:
                own_keys.add(side_key)
                mappings[identity].append(record)
                instruments[source_key].append(record)
        except ERRORS:
            continue
    source_reviews = reviews(at)
    products = read_all(db)
    for identity, candidates in requests.items():
        matches = mappings[identity]
        if len(matches) != 1 or matches[0] is None:
            continue
        record, = matches
        source = record['quote']['source']
        others = [r for r in instruments[identity[0], source['native_event_id'], source['native_market_id']]
                  if r['quote']['source']['native_outcome_id'] != source['native_outcome_id']]
        if len(others) != 1 or _selected(others[0], at=at) != (identity[0], identity[1], OPPOSITE[identity[2]], identity[3]):
            continue
        try:
            binding = _native_binding(db, record, others[0], at=at, source_reviews=source_reviews, products=products)
        except ERRORS as exc:
            reason = str(exc) if isinstance(exc, ValueError) else 'native_market_terms_unavailable'
            for key, _ in candidates:
                results[key]['reason'] = reason
            continue
        for key, original in candidates:
            link = (original.get('comparison_source_metadata') or {}).get('bookmaker_market_link') or {}
            if identity[0] == 'polymarket_us' and original['quote']['source']['provider'] == 'sportsgameodds':
                if binding['route'] not in link.get('path', '').split('/'):
                    continue
            results[key] = binding
    return results


def synchronized_kalshi(db, bindings, *, at, cutoff):
    """Use a current synchronized ladder for the exact market and selected side."""
    selected = {key: binding for key, binding in bindings.items()
                if binding['venue'] == 'kalshi' and binding.get('contract') and not binding['reason']}
    if not selected:
        return {}
    keys = {(current_event_id('kalshi', b['event_id']), b['market_id'], b['outcome_id']) for b in selected.values()}
    events, markets, sides = [list(values) for values in zip(*keys, strict=True)]
    floor = cutoff-timedelta(seconds=NATIVE_BOOK_MAX_AGE_SECONDS)
    rows = db.execute('''SELECT b.event_id,b.native_market_id,b.source_at,b.received_at,b.revision,b.sequence,
               wanted.side,e.scheduled_start,d.levels
        FROM unnest(%s::text[],%s::text[],%s::text[]) wanted(event_id,market_id,side)
        JOIN native_book_revision b ON b.event_id=wanted.event_id AND b.native_market_id=wanted.market_id
        JOIN current_event e ON e.id=b.event_id AND e.provider='kalshi'
        JOIN native_ladder_revision d ON d.id=b.ladder_refs#>>ARRAY[wanted.side,'asks']
        WHERE b.venue='kalshi' AND b.is_current AND b.state='active' AND b.sync='synchronized'
          AND b.quantity_units='contracts' AND b.source_order>=extract(epoch FROM %s::timestamptz)
          AND b.received_order<=extract(epoch FROM %s::timestamptz)''', (events,markets,sides,floor,at))
    exact = {(row['event_id'],row['native_market_id'],row['side']):row for row in rows}
    results = {}
    for key,b in selected.items():
        row = exact.get((current_event_id('kalshi', b['event_id']), b['market_id'], b['outcome_id']))
        if not row or stamp(row['scheduled_start']) != stamp(b['scheduled_start']):
            continue
        source, received = stamp(row['source_at']), stamp(row['received_at'])
        expires = min(source+timedelta(seconds=NATIVE_BOOK_MAX_AGE_SECONDS),
                      stamp(b['scheduled_start']), stamp(b['terms_valid_until']))
        if not floor <= source <= received <= at <= cutoff < expires:
            continue
        ladder = row['levels']
        if not all(price_unit == 'usd_per_contract' and size_unit == 'contracts'
                   for _,price_unit,_,size_unit in ladder):
            continue
        evidence = dict(observed_at=row['received_at'], source_at=row['source_at'],
                        source='synchronized_native_book', revision=row['revision'], sequence=row['sequence'])
        results[key] = dict(b, levels=[dict(price=p,quantity=q) for p,_,q,_ in ladder[:DEPTH]],
            complete=False, source_at=row['source_at'], received_at=row['received_at'],
            valid_until=expires.isoformat(), identity_receipts=[*b['identity_receipts'],evidence])
    return results


class NativeExperimentDepth:
    def __init__(self, *, client=None, now=None, concurrency=3, timeout=2.0, allowed=None):
        self.client = client
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout = timeout
        self.blocked_until = {}
        self.requests = Counter()
        self.allowed = allowed or (lambda _venue: True)

    async def __aenter__(self):
        if self.client is None:
            self.client = httpx.AsyncClient(follow_redirects=False, trust_env=False)
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    def _failed_read(self, url, started, cutoff, reason):
        finished = self.now()
        evidence = dict(requested_at=started.isoformat(), received_at=finished.isoformat(),
                        url=str(url), status=None, failure=reason)
        return None, evidence if finished <= cutoff else None, reason

    async def _read(self, venue, url, cutoff, *, params=None, body_limit=512 * 1024):
        async with self.semaphore:
            if not self.allowed(venue):
                return None, None, 'source_paused'
            sent = self.now()
            seconds = min(self.timeout, (cutoff - sent).total_seconds())
            if seconds <= 0:
                return None, None, 'cutoff_passed'
            if self.blocked_until.get(venue, sent) > sent:
                return None, None, 'throttled'
            self.requests[venue] += 1
            try:
                async with asyncio.timeout(seconds):
                    async with self.client.stream('GET', url, params=params, timeout=seconds) as response:
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > body_limit:
                                return self._failed_read(response.url, sent, cutoff, 'native_book_capacity')
                            chunks.append(chunk)
                        body = b''.join(chunks)
                        received = self.now()
                        if received > cutoff:
                            return None, None, 'cutoff_passed'
                        status = response.status_code
                        headers = {name: response.headers[name] for name in HEADER_FIELDS if name in response.headers}
                        evidence = dict(requested_at=sent.isoformat(), received_at=received.isoformat(),
                            path=response.url.path, url=str(response.url), status=status, headers=headers,
                            date=headers.get('date'), sha256=sha256(body).hexdigest())
            except (httpx.HTTPError, TimeoutError):
                return self._failed_read(url, sent, cutoff, 'native_book_unavailable')
            if status == 429:
                pause = headers.get('retry-after')
                try:
                    until = received + timedelta(seconds=int(pause))
                except (TypeError, ValueError, OverflowError):
                    try:
                        until = parsedate_to_datetime(pause)
                        if until.utcoffset() is None:
                            raise ValueError('Retry-After date needs timezone')
                    except (TypeError, ValueError):
                        until = received + timedelta(seconds=1)
                self.blocked_until[venue] = max(until, self.blocked_until.get(venue, received))
                return None, evidence, 'throttled'
            if status != 200:
                return None, evidence, 'native_book_unavailable'
            try:
                return (kalshi.decode if venue == 'kalshi' else polymarket_us.decode)(body), evidence, None
            except ERRORS:
                return None, evidence, 'native_book_invalid'

    @staticmethod
    def _fresh(evidence, cutoff, source_at=None):
        headers = evidence['headers']
        received = exact_time(evidence['received_at'])
        date = exact_time(parsedate_to_datetime(headers['date']).isoformat())
        cutoff_at = exact_time(cutoff.isoformat())
        age = int(headers.get('age', '0'))
        if not 0 <= age <= NATIVE_BOOK_MAX_AGE_SECONDS or not date <= received <= cutoff_at:
            return False
        ages = [cutoff_at - date, cutoff_at - received + age]
        if source_at:
            source = exact_time(source_at)
            if source > received:
                return False
            ages.append(cutoff_at - source)
        return max(ages) <= NATIVE_BOOK_MAX_AGE_SECONDS

    async def _kalshi(self, bindings, cutoff):
        ticker = bindings[0]['market_id']
        base = kalshi.REST_URL + '/markets/' + quote(ticker, safe='')
        book, evidence, reason = await self._read('kalshi', base + '/orderbook', cutoff, params={'depth': DEPTH})
        return await self._kalshi_levels(bindings, cutoff, book, evidence, reason)

    async def _kalshi_levels(self, bindings, cutoff, book, evidence, reason):
        ticker = bindings[0]['market_id']
        base = kalshi.REST_URL + '/markets/' + quote(ticker, safe='')
        receipts = [evidence] if evidence else []
        if reason:
            return [dict(binding, reason=reason, receipts=receipts) for binding in bindings]
        try:
            if not self._fresh(evidence, cutoff):
                reason = 'stale'
                return [dict(binding, reason=reason, receipts=receipts) for binding in bindings]
            data = book['orderbook_fp']
            native = {side: kalshi.levels(data[side + '_dollars']) for side in ('yes', 'no')}
            if any(not native[binding['opposite_outcome_id']] for binding in bindings):
                # This endpoint can return an empty book for an unknown ticker.
                # Confirm exact market existence and active status first.
                listing, witness, reason = await self._read('kalshi', base, cutoff)
                if witness:
                    receipts.append(witness)
                market = (listing or {}).get('market') or {}
                if (reason or market.get('ticker') != ticker or market.get('event_ticker') != bindings[0]['event_id']
                        or market.get('status') != 'active' or not self._fresh(witness, cutoff)):
                    return [dict(binding, reason=reason or 'native_market_open_unverified', receipts=receipts)
                            for binding in bindings]
            rows = []
            for binding in bindings:
                levels = sorted(native[binding['opposite_outcome_id']].items(), reverse=True)
                normalized = [dict(price=str(1 - F(bid)), quantity=str(size)) for bid, size in levels]
                rows.append(dict(binding, levels=normalized[:DEPTH], complete=len(levels) < DEPTH,
                    receipts=receipts, **self._book_window(binding, evidence)))
            return rows
        except ERRORS:
            return [dict(binding, reason='native_book_invalid', receipts=receipts) for binding in bindings]

    async def _polymarket(self, bindings, cutoff):
        slug = bindings[0]['route']
        url = polymarket_us.GATEWAY + '/v1/markets/' + quote(slug, safe='') + '/book'
        body, evidence, reason = await self._read('polymarket_us', url, cutoff)
        receipts = [evidence] if evidence else []
        source_at = None
        if not reason:
            try:
                data = body['marketData']
                source_at = data.get('transactTime')
                if data['marketSlug'] != slug or polymarket_us.state(data.get('state')).value != 'active':
                    reason = 'native_market_open_unverified'
                elif source_at is None or not self._fresh(evidence, cutoff, source_at):
                    reason = 'stale'
                else:
                    results = []
                    for binding in bindings:
                        long = binding['native_side'] == 'Long'
                        levels = []
                        for raw in data['offers' if long else 'bids']:
                            p, size = F(polymarket_us.price(raw['px']).value), F(raw['qty'])
                            if size > 0:
                                levels.append((p if long else 1 - p, size))
                        levels.sort()
                        normalized = [dict(price=str(ask), quantity=str(size)) for ask, size in levels[:DEPTH]]
                        # REST documents no complete-depth guarantee for PMUS.
                        results.append(dict(binding, levels=normalized, complete=False,
                            source_at=source_at, receipts=receipts, **self._book_window(binding, evidence, source_at)))
                    return results
            except ERRORS:
                reason = 'native_book_invalid'
        return [dict(binding, reason=reason, source_at=source_at, receipts=receipts) for binding in bindings]

    @staticmethod
    def _book_window(binding, evidence, source_at=None):
        lifetime = timedelta(seconds=NATIVE_BOOK_MAX_AGE_SECONDS)
        received = stamp(evidence['received_at'])
        headers = evidence['headers']
        earliest = min(received-timedelta(seconds=int(headers.get('age', '0'))),
            parsedate_to_datetime(headers['date']), stamp(source_at) if source_at else received)
        expiry = earliest+lifetime
        if binding.get('scheduled_start'):
            expiry = min(expiry, stamp(binding['scheduled_start']))
        if binding.get('terms_valid_until'):
            expiry = min(expiry, stamp(binding['terms_valid_until']))
        return dict(received_at=evidence['received_at'], valid_until=expiry.isoformat())

    async def _kalshi_batch(self, markets, cutoff):
        payload, evidence, reason = await self._read('kalshi', kalshi.REST_URL+'/markets/orderbooks', cutoff,
                                                     params=[('tickers', ticker) for ticker, _ in markets])
        rows = defaultdict(list)
        for row in (payload or {}).get('orderbooks', []):
            rows[row.get('ticker')].append(row)
        results = {}
        for ticker, pairs in markets:
            keys, bindings = zip(*pairs, strict=True)
            matched = rows[ticker]
            data = matched[0] if len(matched) == 1 else None
            items = await self._kalshi_levels(bindings, cutoff, data, evidence,
                                             reason or (None if data else 'native_book_unobserved'))
            results.update(zip(keys, items, strict=True))
        return results

    async def read_native(self, bindings, cutoff, *, batch=False):
        """Read each matched market once for all selected sides at this cutoff."""
        cutoff = stamp(cutoff)
        queries = defaultdict(list)
        results = {}
        for key, binding in bindings.items():
            if binding['reason']:
                results[key] = binding
            else:
                market = binding['venue'], binding['market_id']
                if market not in queries and len(queries) >= MAX_MARKETS_PER_DECISION:
                    results[key] = dict(binding, reason='native_book_capacity')
                else:
                    queries[market].append((key, binding))

        async def observation(venue, pairs):
            keys, items = zip(*pairs, strict=True)
            read = self._kalshi if venue == 'kalshi' else self._polymarket
            results.update(zip(keys, await read(items, cutoff), strict=True))

        kalshi_markets = [(ticker, pairs) for (venue, ticker), pairs in queries.items() if venue == 'kalshi']

        async def batch_observation(markets):
            results.update(await self._kalshi_batch(markets, cutoff))

        # Keep public response size and list length bounded independently of the external maximum.
        reads = [observation(venue, pairs) for (venue, _), pairs in queries.items() if venue != 'kalshi' or not batch]
        if batch:
            reads += [batch_observation(kalshi_markets[i:i+16]) for i in range(0, len(kalshi_markets), 16)]
        await asyncio.gather(*reads)
        return results
