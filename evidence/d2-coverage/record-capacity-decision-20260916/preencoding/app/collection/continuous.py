"""D2 finite inventory collector. Reuses D1 projection, E6 transport and journal.

No timer starts this collector. One explicit Start owns discovery and every socket;
all requests, refreshes and retries share the Start deadline and venue budgets.
"""
import asyncio
import base64
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import fnmatch
import json
import resource
import shutil
import sys
import time

from app.adapters import kalshi, polymarket_us
from app.collection import coverage
from app.collection.prediction_producer import MockREST, PredictionBudget, PredictionProducer
from app.collection.transport_session import TransportSession
from app.collection.odds_http import BudgetStop
from app.collection.venue_access import ENDPOINTS
from app.reference.records import packed

MIB = 1024 * 1024
LIMITS = dict(rest_per_venue=100, requests_per_second=2, markets_per_venue=100,
              simultaneous_connections=6, connection_attempts=12, frame_bytes=MIB,
              ingress_bytes=32*MIB, rss_bytes=256*MIB, queue_records=48,
              queue_bytes=4*MIB, output_bytes=128*MIB, free_disk_bytes=1024*MIB,
              journal_bytes=32*MIB, journal_records=4096, refresh_seconds=60,
              kickoff_margin_seconds=300)


def now():
    return datetime.now(timezone.utc)


def rss():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value * 1024)


def select_inventory(inventory, at, cap=100):
    """Matching is deliberately absent from eligibility and prioritization."""
    events = {e['id']: e for e in inventory['events']}
    eligible = []
    for row in inventory['markets']:
        event = events.get(row['event_id'])
        reason = row['exclusion'] or row.get('subscription_evidence_exclusion') or row.get('parse_exclusion')
        if not reason and (not event or not event['scheduled_start']):
            reason = 'unknown_schedule'
        if not reason and coverage.stamp(event['scheduled_start']) <= at + timedelta(seconds=300):
            reason = 'kickoff_margin'
        if not reason and not any(s['purchase_support'] == 'supported' for s in row['sides']):
            reason = 'no_supported_purchase_side'
        row['subscription_exclusion'] = reason
        if not reason:
            eligible.append(row)
    eligible.sort(key=lambda m: (events[m['event_id']]['scheduled_start'], m['id']))
    for row in eligible[cap:]:
        row['subscription_exclusion'] = 'subscription_limit'
    return [r['id'] for r in eligible[:cap]], len(eligible)


class REST(MockREST):
    """Sequential per-venue requests; retries are charged by the same client."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_interval = 1.0  # conservative bootstrap until account lookup
        self.rate = None
        self.costs = None
        self.lock = asyncio.Lock()

    def account_limits(self, limits, costs):
        read = limits['read']
        self.rate = float(read['refill_rate'])
        self.capacity = float(read['bucket_capacity'])
        self.costs = costs
        if self.rate <= 0 or self.capacity <= 0 or float(costs['default_cost']) <= 0:
            raise BudgetStop('unusable_account_budget')

    async def get(self, url, params=None, **kwargs):
        from urllib.parse import urlsplit
        from email.utils import parsedate_to_datetime
        async with self.lock:
            if self.budget.requests >= self.limits['discovery_requests']:
                if hasattr(self, 'session'):
                    self.session.request_stop('prediction_discovery_request_cap')
                raise BudgetStop('prediction_discovery_request_cap')
            if self.rate:
                cost = max([float(self.costs['default_cost']), *[
                    float(e['cost']) for e in self.costs['endpoint_costs']
                    if e['method'] == 'GET' and fnmatch.fnmatch(urlsplit(url).path, e['path'])]])
                if cost > self.capacity:
                    raise BudgetStop('request_cost_exceeds_account_bucket')
                self.request_interval = max(.5, cost / self.rate)
            elif self.venue == 'polymarket_us':
                self.request_interval = .5  # below documented retail 20/s
            for attempt in range(2):
                try:
                    response = await super().get(url, params, **kwargs)
                except BudgetStop:
                    if hasattr(self, 'session'):
                        self.session.request_stop('prediction_rest_resource_cap')
                    raise
                except (TimeoutError, __import__('aiohttp').ClientError):
                    if attempt:
                        raise
                    await asyncio.sleep(1)
                    continue
                if response.status_code not in (429, 500, 502, 503, 504) or attempt:
                    return response
                delay = 1.0
                retry = response.headers.get('Retry-After')
                if retry:
                    try:
                        delay = max(delay, float(retry))
                    except ValueError:
                        delay = max(delay, (parsedate_to_datetime(retry) - now()).total_seconds())
                if not 0 <= delay <= 180:
                    raise BudgetStop('retry_after_exceeds_deadline')
                await asyncio.sleep(delay)  # session cancellation bounds longer waits


class Discovery:
    def __init__(self, session):
        self.session = session
        self.lock = asyncio.Lock()
        self.completed = False
        self.generation = 0
        self.pages = []
        self.inventory = None
        self.markets = {v: {} for v in coverage.VENUES}
        self.coverage = None
        self.clients = {}
        self.published_generation = None
        self.published_at = None
        self.refresh = dict(state='pending', generation=0)
        self.partial = None
        self.responses = {v:dict(received=0, durably_retained=0) for v in coverage.VENUES}
        self.blocked = {v:{} for v in coverage.VENUES}

    def status(self):
        return dict(published_generation=self.published_generation, published_at=self.published_at,
                    age_seconds=(now()-coverage.stamp(self.published_at)).total_seconds() if self.published_at else None,
                    refresh=deepcopy(self.refresh), partial=deepcopy(self.partial),
                    responses={v:dict(c, attempted_requests=self.session.producers[v].budget.requests)
                               for v,c in self.responses.items() if v in self.session.producers},
                    safety_exclusions=deepcopy(self.blocked))

    def admission(self, venue, row):
        # Journal acknowledgement is authoritative even if queue insertion then fails.
        before = getattr(self.session, 'counts', {}).get('durably_acknowledged', 0)
        try:
            result = self.session.emit(venue, row)
        except BaseException as exc:
            if getattr(self.session, 'counts', {}).get('durably_acknowledged', 0) > before:
                return True, exc
            raise
        retained = (self.session.counts['durably_acknowledged'] > before
                    if hasattr(self.session, 'counts') else result is not False)
        return retained, None

    def safety(self, venue):
        if not self.inventory:
            return
        partial = coverage.catalog(self.pages, venue, now())
        old = self.inventory[venue]
        events = {e['id']:e for e in partial['events']}
        prior = {e['id']:e for e in old['events']}
        markets = {m['id']:m for m in partial['markets']}
        for m in old['markets']:
            e = events.get(m['event_id'])
            reason = markets.get(m['id'], {}).get('exclusion')
            if e and (e['exclusion'] or e['scheduled_start'] != prior[e['id']]['scheduled_start']):
                reason = 'observed_event_closure_or_schedule_change'
            if reason:
                self.blocked[venue][m['id']] = reason
        producer = self.session.producers.get(venue)
        if producer:
            for g in producer.groups.values():
                if set(g['ids']) & set(self.blocked[venue]):
                    g['invalidated'] = True
                    g['usable'].clear()

    def receipt(self, venue, row):
        if row.get('status') is not None:
            self.responses[venue]['received'] += 1
        admitted, error = self.admission(venue, dict(row, discovery_generation=self.generation))
        if admitted:
            if row.get('status') is not None:
                self.responses[venue]['durably_retained'] += 1
            if row['path'].endswith(('/events', '/markets')):
                self.pages.append(dict(row, source=venue))
                self.safety(venue)
        if error:
            raise error
        if not admitted:
            raise BudgetStop('catalog_response_not_retained')

    async def pages_for(self, venue, path, query, field, size):
        client = self.clients[venue]
        client.session = self.session
        cursor = ''
        seen = set()
        results = []
        for page in range(10):
            pagination = dict(limit=size, **({'cursor': cursor} if venue == 'kalshi' else {'offset': page*size}))
            response = await client.get(ENDPOINTS[venue]['rest']+path, {**query, **pagination})
            if response.status_code != 200:
                raise ValueError('catalog_http_'+str(response.status_code))
            data = response.json()
            rows = data.get(field)
            if not isinstance(rows, list):
                raise ValueError('missing_catalog_array')
            results.extend(rows)
            if venue == 'kalshi':
                cursor = data.get('cursor')
                if not isinstance(cursor, str) or cursor in seen:
                    raise ValueError('invalid_catalog_cursor')
                if not cursor:
                    break
                seen.add(cursor)
            elif len(rows) < size:
                break
        return results

    async def venue(self, venue):
        s = self.session
        if venue not in self.clients:
            self.clients[venue] = REST(ENDPOINTS[venue]['rest'], s.spec['prediction'],
                lambda r: self.receipt(venue, r), 5, s.producers[venue].budget,
                venue=venue if s.spec['mode']=='real' else None,
                credential=(s.credentials or {}).get(venue))
        client = self.clients[venue]
        if venue == 'kalshi':
            if client.rate is None:
                values = []
                for path in ('/trade-api/v2/account/limits', '/trade-api/v2/account/endpoint_costs'):
                    r = await client.get(ENDPOINTS[venue]['rest']+path)
                    if r.status_code != 200:
                        raise ValueError('account_limits_unavailable')
                    values.append(r.json())
                client.account_limits(*values)
                s.emit(venue, dict(type='verified_account_budget', limits=values[0], costs=values[1]))
            await self.pages_for(venue, '/trade-api/v2/events',
                dict(series_ticker='KXNFLGAME', status='open', with_milestones='true'), 'events', 200)
            cat = coverage.catalog(self.pages, venue, now())
            for event in cat['events']:
                if event['exclusion'] is None:
                    await self.pages_for(venue, '/trade-api/v2/markets',
                        dict(event_ticker=event['id']), 'markets', 200)
        else:
            rows = await self.pages_for(venue, '/v1/events', dict(tagSlug='nfl', active='true',
                closed='false', orderBy='startTime', orderDirection='asc',
                sportsMarketTypes='football_team_full_game_winner'), 'events', 5)
            # Independent market pagination by native gameId; never a slug-list intersection.
            for event in {str(e['id']):e for e in rows}.values():
                if event.get('gameId'):
                    await self.pages_for(venue, '/v1/markets', dict(gameId=str(event['gameId']),
                        sportsMarketTypes='SPORTS_MARKET_TYPE_MONEYLINE', active='true', closed='false'), 'markets', 5)

    def project(self):
        cats = {v: coverage.catalog(self.pages, v, now()) for v in coverage.VENUES}
        coverage.match_catalogs(cats)
        markets = {v: {} for v in coverage.VENUES}
        for v, cat in cats.items():
            cat['counts'] = coverage.totals(cat)
            for row in cat['markets']:
                proof = row['provenance'][0]
                page = next(p for p in self.pages if p['body_sha256']==proof['body_sha256'])
                body, _ = coverage.decode_page(page)
                r = coverage.response(v, page, body)
                try:
                    markets[v][row['id']] = (kalshi.parse_market(r,row['_native'],row['event_id'],'KXNFLGAME')
                        if v=='kalshi' else polymarket_us.parse_market(r,row['_native'],row['event_id']))
                except (ValueError, KeyError, TypeError):
                    row['parse_exclusion'] = 'market_parse_error'
            ids, eligible = select_inventory(cat, now())
            cat['selection'] = dict(ids=ids, eligible=eligible)
            for row in cat['markets']+cat['events']:
                row.pop('_native', None)
        return cats, markets

    async def discover(self, force=False):
        async with self.lock:
            if self.completed and not force:
                return self.markets
            self.generation += 1
            self.pages = []
            self.partial = None
            self.refresh = dict(state='running', generation=self.generation, started_at=now().isoformat())
            try:
                results = await asyncio.gather(*(self.venue(v) for v in coverage.VENUES), return_exceptions=True)
                errors = [type(e).__name__+':'+str(e) for e in results if isinstance(e, BaseException)]
                if errors:
                    raise ValueError('; '.join(errors))
                cats, markets = self.project()
                at = now().isoformat()
                admitted, error = self.admission('session', dict(type='coverage_inventory',
                    generation=self.generation, published_at=at, inventory=cats,
                    previous_generation=self.published_generation, discovery_error=None))
                if error:
                    raise error
                if not admitted:
                    raise BudgetStop('inventory_publication_not_retained')
                # No await between journal admission and the complete generation swap.
                self.inventory, self.markets = cats, markets
                self.published_generation, self.published_at = self.generation, at
                self.completed = True
                self.coverage = cats
                self.blocked = {v:{} for v in coverage.VENUES}
                self.refresh.update(state='completed', finished_at=at)
                return self.markets
            except BaseException as exc:
                self.refresh.update(state='interrupted' if isinstance(exc, asyncio.CancelledError) else 'failed',
                                    reason=type(exc).__name__+':'+str(exc), finished_at=now().isoformat())
                # Durable partial progress is diagnostic only, never a coverage denominator.
                self.partial = {v:coverage.catalog(self.pages,v,now()) for v in coverage.VENUES}
                for cat in self.partial.values():
                    for row in cat['events']+cat['markets']:
                        row.pop('_native',None)
                raise


class GroupBudget:
    def __init__(self, shared):
        self.shared = shared
        self.connections = 0
    def remaining_bytes(self):
        return self.shared.budget.remaining_bytes()
    def charge_bytes(self, n):
        try:
            self.shared.budget.charge_bytes(n)
        except BudgetStop:
            self.shared.session.request_stop('prediction_session_byte_cap')
            raise
    @property
    def bytes(self):
        return self.shared.budget.bytes
    @bytes.setter
    def bytes(self, value):
        self.shared.budget.bytes = value
    def reserve(self, kind):
        if self.shared.session.connection_attempts >= 12:
            self.shared.session.request_stop('connection_attempt_cap')
            raise BudgetStop('connection_attempt_cap')
        self.shared.session.connection_attempts += 1
        self.connections += 1
        self.shared.budget.reserve(kind)


class Venue:
    def __init__(self, session, venue):
        self.session, self.venue = session, venue
        self.budget = PredictionBudget(session.spec['prediction'])
        self.groups = {}
        self.serial = 0
        self.records = {}
        self.ever = {k:set() for k in ('requested','acknowledged','receiving','usable')}
        self.peak = {k:0 for k in self.ever}
        self.eligible = 0
        self.selected = []
        self.applied_generation = None

    async def discover(self):
        return (await self.session.discovery.discover())[self.venue]

    def health(self, group, state):
        g = self.groups[group]
        g['health'] = state
        if state in ('disconnected','awaiting_snapshot','ineligible'):
            g['usable'].clear()
            if state != 'ineligible':
                g['acknowledged'].clear()
                g['receiving'].clear()
        self.session.health[self.venue] = 'connected' if any(x['health']=='connected' for x in self.groups.values()) else state
        self.session.emit(self.venue, dict(type='source_health', state=state, stream_group=group,
            market_ids=list(g['ids']), gap_reason='fresh synchronization required' if state!='connected' else None))

    def emit(self, group, source, row):
        g = self.groups[group]
        if row['type']=='prediction_command':
            command = json.loads(row['body'])
            g['request'] = command.get('id') if self.venue=='kalshi' else command['subscribe']['requestId']
            g['requested'].update(g['ids'])
        elif row['type']=='prediction_frame' and self.venue=='kalshi':
            data = json.loads(base64.b64decode(row['body_b64']))
            if (data.get('type')=='subscribed' and data.get('id')==g.get('request')
                    and data.get('msg',{}).get('channel')=='orderbook_delta'
                    and type(data.get('msg',{}).get('sid')) is int and data['msg']['sid']>0):
                g['acknowledged'].update(g['ids'])
        elif row['type']=='prediction_book':
            book = row['book']; mid = book['raw']['ref']['market_id']
            if book['sync']=='synchronized' and book['receipt_freshness']=='recent':
                g['receiving'].add(mid)
                if self.venue=='polymarket_us':
                    g['acknowledged'].add(mid)  # valid matching subscription data; no separate ack
                if not g.get('invalidated') and mid not in self.safety_exclusions():
                    g['usable'].add(mid)
                self.records[mid] = dict(received_at=book['raw']['received_at'],
                    exchange_at=book['raw'].get('exchange_at'), sync=book['sync'],
                    source_time_progress=book['source_time_progress'])
            else:
                g['usable'].discard(mid)
        for key in self.ever:
            self.ever[key].update(g[key])
        result = self.session.emit(source, dict(row, stream_group=group))
        self.snapshot()
        return result

    def safety_exclusions(self):
        d = getattr(self.session, 'discovery', None)
        if not d or not d.inventory:
            return set()
        cat = deepcopy(d.inventory[self.venue])
        ids, _ = select_inventory(cat, now())
        return ({m['id'] for m in cat['markets']} - set(ids)) | set(getattr(d, 'blocked', {}).get(self.venue, {}))

    def snapshot(self):
        for group in self.groups.values():
            if group.get('invalidated'):
                group['usable'].clear()
            group['usable'].difference_update(self.safety_exclusions())
        counts = {}
        for key in self.ever:
            ids = set().union(*(g[key] for g in self.groups.values())) if self.groups else set()
            counts[key] = len(ids)
            self.peak[key] = max(self.peak[key], len(ids))
        return dict(applied_generation=self.applied_generation, applied_eligible=self.eligible, applied_selected=len(self.selected), **counts,
                    ever={k:len(v) for k,v in self.ever.items()}, peak_simultaneous=dict(self.peak),
                    requests=self.budget.requests, connection_attempts=self.budget.connections,
                    body_bytes_charged=self.budget.bytes,
                    acknowledgement_basis='explicit channel acknowledgement' if self.venue=='kalshi' else 'valid current-request market image; no separate acknowledgement',
                    latest_receipts=deepcopy(self.records))

    async def reconcile(self):
        inventory = deepcopy(self.session.discovery.inventory[self.venue])
        ids, self.eligible = select_inventory(inventory, now())
        ids = [m for m in ids if m in self.session.discovery.markets[self.venue] and m not in self.safety_exclusions()]
        self.selected = ids
        self.applied_generation = getattr(self.session.discovery, 'published_generation', None)
        size = 20 if self.venue=='kalshi' else 100
        desired = [tuple(ids[i:i+size]) for i in range(0,len(ids),size)]
        # Reschedules/metadata revisions require a new synchronized subscription too.
        rows = {r['id']:r for r in inventory['markets']}
        events = {r['id']:r for r in inventory['events']}
        signatures = {group: tuple(packed([rows[m]['event_id'], events[rows[m]['event_id']]['scheduled_start'],
                            rows[m]['status'], rows[m]['sides'], rows[m]['terms']]) for m in group) for group in desired}
        for name, group in list(self.groups.items()):
            if group.get('invalidated') or group['ids'] not in desired or group['signature']!=signatures.get(group['ids']):
                self.health(name, 'disconnected')
                self.session.emit(self.venue, dict(type='subscription_departure',stream_group=name,market_ids=list(group['ids']),reason='inventory_or_schedule_changed'))
                group['task'].cancel()
                await asyncio.gather(group['task'], return_exceptions=True)
                await group['producer'].aclose()
                del self.groups[name]
        for group in desired:
            if any(g['ids']==group for g in self.groups.values()):
                continue
            self.serial += 1
            name = self.venue+'-'+str(self.serial)
            spec = deepcopy(self.session.spec)
            spec['prediction']['connections'] = 2
            producer = PredictionProducer(self.venue, spec, ENDPOINTS[self.venue]['rest'], ENDPOINTS[self.venue]['ws'],
                lambda source,row,n=name:self.emit(n,source,row), lambda source,state,n=name:self.health(n,state),
                credential=(self.session.credentials or {}).get(self.venue), budget=GroupBudget(self))
            self.groups[name] = dict(ids=group, signature=signatures[group], producer=producer, health='idle',
                **{k:set() for k in self.ever})
            if hasattr(self.session, 'queue'):
                producer.after_book = self.session.queue.join
            markets = [self.session.discovery.markets[self.venue][m] for m in group]
            for market in markets:
                self.session.emit(self.venue, dict(type='market_selected',stream_group=name,market=json.loads(json.dumps(asdict(market),default=str))))
                await asyncio.sleep(0)
            self.groups[name]['task'] = asyncio.create_task(producer.run(markets))
        self.snapshot()

    async def run(self, markets):
        while not self.session.stop_event.is_set():
            await self.reconcile()
            for group in self.groups.values():
                if group['task'].done():
                    await group['task']
                    self.session.request_stop('native_stream_ended')
                    return
            await self.session.pause(.25)

    async def aclose(self):
        for group in self.groups.values():
            group['task'].cancel()
        await asyncio.gather(*(g['task'] for g in self.groups.values()), return_exceptions=True)
        for group in self.groups.values():
            await group['producer'].aclose()
        client = self.session.discovery.clients.get(self.venue)
        if client:
            await client.aclose()


class ContinuousSession(TransportSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connection_attempts = 0
        self.started_monotonic = None
        self.peak_rss = 0
        self.peak_queue = 0
        self.snapshots = []

    def resources(self):
        self.peak_rss = max(self.peak_rss, rss())
        self.peak_queue = max(self.peak_queue, self.queue.high_items)
        return dict(peak_rss_bytes=self.peak_rss, peak_queue_records=self.peak_queue,
                    peak_queue_bytes=self.queue.high_bytes,
                    ingress_bytes=self.ingress_bytes, journal_bytes=self.journal.bytes if self.journal else 0,
                    elapsed_seconds=time.monotonic()-self.started_monotonic if self.started_monotonic else 0)

    def emit(self, source, record):
        if self.stop_event.is_set():
            return False
        if self.journal:
            r = self.resources()
            n = len(packed(record).encode())+2048
            reason = ('rss_cap' if r['peak_rss_bytes']>=LIMITS['rss_bytes'] else
                      'journal_reserved_stop' if self.journal.bytes+n>=32*MIB-65536 or self.journal.count>=4032 else
                      'output_reservation_stop' if (self.journal.bytes+n)*3>=120*MIB else None)
            if reason:
                self.request_stop(reason)
                raise BudgetStop(reason)
        return super().emit(source,record)

    async def start(self):
        self.started_monotonic = time.monotonic()
        if shutil.disk_usage(self.output.parent).free < LIMITS['free_disk_bytes']+LIMITS['output_bytes']:
            raise ValueError('insufficient_pilot_disk_reservation')
        await super().start()
        self.discovery = Discovery(self)
        self.producers = {v:Venue(self,v) for v in coverage.VENUES}
        return self.sid

    async def discoveries(self):
        # Start-relative cadence. Await each refresh; missed ticks are skipped.
        tick = self.started_monotonic + 60
        while not self.stop_event.is_set():
            await self.pause(max(0,tick-time.monotonic()))
            if self.stop_event.is_set():
                break
            await self.discovery.discover(force=True)
            tick += 60
            while tick <= time.monotonic():
                tick += 60

    def status_coverage(self):
        cats = self.discovery.inventory or {}
        return {v:dict(discovered_events=len(cats[v]['events']) if v in cats else None,
                       discovered_markets=len(cats[v]['markets']) if v in cats else None,
                       generation=self.discovery.published_generation,
                       eligible=cats.get(v,{}).get('selection',{}).get('eligible'),
                       selected=len(cats[v]['selection']['ids']) if v in cats else None,
                       event_discovery=cats.get(v,{}).get('event_discovery','pending'),
                       market_completeness=cats.get(v,{}).get('market_completeness','pending'),
                       **p.snapshot()) for v,p in self.producers.items()}

    async def run(self):
        watcher = asyncio.create_task(self.monitor())
        try:
            await super().run()
        finally:
            self.collection_seconds = time.monotonic()-self.started_monotonic
            watcher.cancel()
            await asyncio.gather(watcher,return_exceptions=True)

    async def monitor(self):
        while not self.stop_event.is_set():
            await self.pause(1)
            if self.stop_event.is_set():
                break
            stats = self.resources()
            if stats['peak_rss_bytes']>=LIMITS['rss_bytes']:
                self.request_stop('rss_cap')
            if shutil.disk_usage(self.output).free < LIMITS['free_disk_bytes']:
                self.request_stop('disk_floor')
            if hasattr(self,'discovery'):
                self.snapshots.append(dict(at=now().isoformat(),coverage=self.status_coverage(),resources=stats))
