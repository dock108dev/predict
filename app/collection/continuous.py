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
        if 'qualification_ids' in inventory and row['id'] not in inventory['qualification_ids']:
            reason='outside_frozen_qualification_selection'
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


def endpoints_for(session):
    if getattr(session, 'mock_segmented', False) or (getattr(session,'product_session',False) and session.spec['mode']=='mock'):
        from .mock_history import fixture_endpoints
        return fixture_endpoints(session)
    return ENDPOINTS


class REST(MockREST):
    """Sequential per-venue requests; retries are charged by the same client."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_interval = 1.0  # conservative bootstrap until account lookup
        self.rate = None
        self.costs = None
        self.lock = asyncio.Lock()

    async def bounded_wait(self, delay):
        session = getattr(self, 'session', None)
        if not getattr(session, 'profile', None):
            await asyncio.sleep(delay)
            return
        remaining = session.started_monotonic + session.spec['duration'] - time.monotonic()
        if session.stop_event.is_set():
            raise asyncio.CancelledError()
        if remaining <= 0:
            raise BudgetStop('prediction_rest_deadline')
        try:
            await asyncio.wait_for(session.stop_event.wait(), min(delay, remaining))
        except TimeoutError:
            if time.monotonic() >= session.started_monotonic + session.spec['duration']:
                raise BudgetStop('prediction_rest_deadline')
            return
        raise asyncio.CancelledError()

    async def pace(self):
        if getattr(self, 'pacing_venue', self.venue):
            await self.bounded_wait(self.request_interval)

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
            if self.budget.requests >= min(self.limits['discovery_requests'],getattr(self,'request_ceiling',self.limits['discovery_requests'])):
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
            elif getattr(self, 'pacing_venue', self.venue) == 'polymarket_us':
                self.request_interval = .5  # below documented retail 20/s
            for attempt in range(2):
                if self.budget.requests >= getattr(self,'request_ceiling',self.limits['discovery_requests']):
                    raise BudgetStop('discovery_generation_request_cap')
                try:
                    response = await super().get(url, params, **kwargs)
                except BudgetStop:
                    if hasattr(self, 'session'):
                        self.session.request_stop('prediction_rest_resource_cap')
                    raise
                except (TimeoutError, __import__('aiohttp').ClientError):
                    if attempt:
                        raise
                    await self.bounded_wait(1)
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
                await self.bounded_wait(delay)


class Discovery:
    def __init__(self, session):
        self.session = session
        self.venues = tuple(session.spec.get("native_sources", {})) or coverage.VENUES
        self.native_catalogs = {}
        self.lock = asyncio.Lock()
        self.completed = False
        self.generation = 0
        self.pages = []
        self.inventory = None
        self.markets = {v: {} for v in self.venues}
        self.coverage = None
        self.clients = {}
        self.published_generation = None
        self.published_at = None
        self.refresh = dict(state='pending', generation=0)
        self.partial = None
        self.responses = {v:dict(received=0, durably_retained=0) for v in self.venues}
        self.blocked = {v:{} for v in self.venues}

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
        if getattr(self.session,'product_session',False) and self.blocked[venue]:
            self.session.emit('session',dict(type='product_coverage_status',coverage=self.session.status_coverage(),refresh=self.refresh,safety_exclusions=self.blocked))

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
            response = await client.get(endpoints_for(self.session)[venue]['rest']+path, {**query, **pagination})
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
        if s.spec.get('native_sources'):
            config = s.spec['native_sources'][venue]
            if venue in getattr(s,'source_access_errors',{}):
                from .native_product import empty_catalog
                self.native_catalogs[venue]=empty_catalog('unavailable',s.source_access_errors[venue])
                return
            if config['state'] != 'enabled':
                from .native_product import empty_catalog
                self.native_catalogs[venue] = empty_catalog(config['state'])
                return
            if venue not in coverage.VENUES:
                cat, markets = await s.producers[venue].native_discover()
                self.native_catalogs[venue] = cat
                self.markets[venue] = markets
                return
        if venue not in self.clients:
            self.clients[venue] = REST(endpoints_for(self.session)[venue]['rest'], s.spec['prediction'],
                lambda r: self.receipt(venue, r), 5, s.producers[venue].budget,
                venue=venue if s.spec['mode']=='real' else None,
                credential=(s.credentials or {}).get(venue))
        client = self.clients[venue]
        client.session = s
        if getattr(s,'profile',None):
            client.pacing_venue = venue
            client.request_ceiling=min(s.profile['requests'],client.budget.requests+s.profile['generation_requests'])
        if venue == 'kalshi':
            if client.rate is None:
                values = []
                for path in ('/trade-api/v2/account/limits', '/trade-api/v2/account/endpoint_costs'):
                    r = await client.get(endpoints_for(self.session)[venue]['rest']+path)
                    if r.status_code != 200:
                        raise ValueError('account_limits_unavailable')
                    values.append(r.json())
                client.account_limits(*values)
                s.emit(venue, dict(type='verified_account_budget', limits=values[0], costs=values[1]))
            series=s.spec.get('native_sources',{}).get(venue,{}).get('series',['KXNFLGAME'])
            for series_id in series:
                await self.pages_for(venue, '/trade-api/v2/events',
                    dict(series_ticker=series_id,status='open',with_milestones='true'),'events',200)
                cat=coverage.catalog(self.pages,venue,now())
                for event in cat['events']:
                    if event['exclusion'] is None and event['native_aliases'].get('series_ticker')==series_id:
                        await self.pages_for(venue,'/trade-api/v2/markets',dict(event_ticker=event['id']),'markets',200)
        else:
            tags=s.spec.get('native_sources',{}).get(venue,{}).get('tags',['nfl'])
            for tag in tags:
                query=dict(tagSlug=tag,active='true',closed='false',orderBy='startTime',orderDirection='asc')
                if not s.spec.get('native_sources'):query['sportsMarketTypes']='football_team_full_game_winner'
                rows=await self.pages_for(venue,'/v1/events',query,'events',5)
                for event in {str(e['id']):e for e in rows}.values():
                    if event.get('gameId'):
                        query=dict(gameId=str(event['gameId']),active='true',closed='false')
                        if not s.spec.get('native_sources'):query['sportsMarketTypes']='SPORTS_MARKET_TYPE_MONEYLINE'
                        await self.pages_for(venue,'/v1/markets',query,'markets',5)

    def project(self):
        cats = {v: deepcopy(self.native_catalogs[v]) if v in self.native_catalogs else coverage.catalog(self.pages, v, now()) for v in self.venues}
        coverage.match_catalogs(cats)
        markets = {v: {} for v in self.venues}
        for v, cat in cats.items():
            if v in self.native_catalogs:
                markets[v] = self.markets.get(v,{})
                continue
            if self.session.spec.get('native_sources'):
                from .native_semantics import SEMANTICS
                cat.update(semantics=SEMANTICS[v],environment='production',update_path='native stream',
                    acquisition_scope=self.session.spec['native_sources'][v].get('series',['KXNFLGAME']) if v=='kalshi' else self.session.spec['native_sources'][v].get('tags',['nfl']))
                for item in cat['events']+cat['markets']:
                    item['native_metadata']=deepcopy(item.get('_native'))
                if v=='polymarket_us':
                    for item in cat['markets']:
                        for side in item['sides']:
                            if side.get('role')=='Short':side.update(purchase_support='supported',basis='1 minus native Long bid; same contract quantity; B3 conversion')
            cat['counts'] = coverage.totals(cat)
            for row in cat['markets']:
                proof = row['provenance'][0]
                page = next(p for p in self.pages if p['body_sha256']==proof['body_sha256'])
                body, _ = coverage.decode_page(page)
                r = coverage.response(v, page, body)
                if getattr(self.session, 'mock_segmented', False) or (getattr(self.session,'product_session',False) and self.session.spec.get('mode','mock')=='mock'):
                    from dataclasses import replace
                    from app.models.core import EvidenceKind
                    r = replace(r, kind=EvidenceKind.SYNTHETIC)
                try:
                    markets[v][row['id']] = (kalshi.parse_market(r,row['_native'],row['event_id'],next(e['native_aliases'].get('series_ticker','unknown') for e in cat['events'] if e['id']==row['event_id']))
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
            if getattr(self.session,'profile',None) and self.generation>=self.session.profile['generations']:
                raise BudgetStop('supervised_generation_cap')
            self.generation += 1
            self.pages = []
            self.partial = None
            self.refresh = dict(state='running', generation=self.generation, started_at=now().isoformat())
            try:
                results = await asyncio.gather(*(self.venue(v) for v in self.venues), return_exceptions=True)
                errors = [type(e).__name__+':'+str(e) for e in results if isinstance(e, BaseException)]
                if errors and (not getattr(self.session,'product_session',False) or (self.completed and not self.session.spec.get('native_sources'))):
                    raise ValueError('; '.join(errors))
                cats, markets = self.project()
                if errors:
                    for v,result in zip(self.venues,results):
                        if isinstance(result,BaseException):
                            cats[v].update(event_discovery='failed',market_completeness='partial',selection=dict(ids=[],eligible=None),source_error=type(result).__name__)
                            markets[v]={}
                if getattr(self.session,'profile',None):
                    for cat in cats.values():
                        if len(cat['events'])>128 or len(cat['markets'])>256: raise BudgetStop('supervised_catalog_cap')
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
                self.blocked = {v:{} for v in self.venues}
                self.refresh.update(state='completed', finished_at=at)
                return self.markets
            except BaseException as exc:
                self.refresh.update(state='interrupted' if isinstance(exc, asyncio.CancelledError) else 'failed',
                                    reason=type(exc).__name__+':'+str(exc), finished_at=now().isoformat())
                # Durable partial progress is diagnostic only, never a coverage denominator.
                self.partial = {v:coverage.catalog(self.pages,v,now()) for v in self.venues}
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
        if self.shared.session.connection_attempts >= (self.shared.session.profile['connections'] if self.shared.session.profile else 12):
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
        guard = getattr(self.session, 'guard_scope', None)
        if guard: guard(source, row)  # Before acknowledgement, books or usable-state mutation.
        if getattr(self.session, 'spec', {}).get('future_qualification_policy')=='native-prerequisites-1':
            g=self.groups[group]
            if row['type']=='prediction_command':g['qualification_epoch']=g.get('qualification_epoch',0)+1
            row=dict(row,connection_epoch=str(group)+':'+str(g.get('qualification_epoch',0)))
        segmented = getattr(self.session, 'segmented_history', False)
        error = None; result = None
        if segmented:
            before = self.session.counts['durably_acknowledged']
            try: result = self.session.emit(source, dict(row, stream_group=group))
            except BaseException as exc:
                if self.session.counts['durably_acknowledged'] == before: raise
                error = exc  # Retained despite a later queue rejection.
            if result is False: return False
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
        if not segmented: result = self.session.emit(source, dict(row, stream_group=group))
        self.snapshot()
        if error: raise error
        return result

    def safety_exclusions(self):
        d = getattr(self.session, 'discovery', None)
        if not d or not d.inventory:
            return set()
        cat = (dict(d.inventory[self.venue],markets=[dict(m) for m in d.inventory[self.venue]['markets']])
               if self.session.profile else deepcopy(d.inventory[self.venue]))
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
        return dict(**(dict(applying_generation=getattr(self,'applying_generation',None)) if getattr(self.session,'segmented_history',False) else {}), applied_generation=self.applied_generation, applied_eligible=self.eligible, applied_selected=len(self.selected), **counts,
                    ever={k:len(v) for k,v in self.ever.items()}, peak_simultaneous=dict(self.peak),
                    requests=self.budget.requests, connection_attempts=self.budget.connections,
                    body_bytes_charged=self.budget.bytes,
                    acknowledgement_basis='explicit channel acknowledgement' if self.venue=='kalshi' else 'valid current-request market image; no separate acknowledgement',
                    latest_receipts=deepcopy(self.records))

    async def reconcile(self):
        inventory = deepcopy(self.session.discovery.inventory[self.venue])
        ids, eligible = select_inventory(inventory, now())
        ids = [m for m in ids if m in self.session.discovery.markets[self.venue] and m not in self.safety_exclusions()]
        generation = getattr(self.session.discovery, 'published_generation', None)
        segmented = getattr(self.session, 'segmented_history', False)
        market_objects = self.session.discovery.markets[self.venue]
        if not segmented:
            self.applied_generation = generation
            self.selected, self.eligible = ids, eligible
        else:
            self.applying_generation = generation
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
                if self.session.profile:
                    self.records={mid:record for mid,record in self.records.items() if mid in ids}
        for group in desired:
            if any(g['ids']==group for g in self.groups.values()):
                continue
            if self.session.profile:
                if sum(v.serial for v in self.session.producers.values())>=self.session.profile['groups']: raise BudgetStop('supervised_group_cap')
                if sum(len(v.groups) for v in self.session.producers.values())>=self.session.profile['sockets']: raise BudgetStop('supervised_socket_cap')
                if len(self.ever['requested']|set(ids))>256: raise BudgetStop('supervised_market_union_cap')
            self.serial += 1
            name = self.venue+'-'+str(self.serial)
            spec = deepcopy(self.session.spec)
            spec['prediction']['connections'] = 2
            producer = PredictionProducer(self.venue, spec, endpoints_for(self.session)[self.venue]['rest'], endpoints_for(self.session)[self.venue]['ws'],
                lambda source,row,n=name:self.emit(n,source,row), lambda source,state,n=name:self.health(n,state),
                credential=(self.session.credentials or {}).get(self.venue), budget=GroupBudget(self))
            producer.mock_segmented = getattr(self.session, 'mock_segmented', False)
            self.groups[name] = dict(ids=group, signature=signatures[group], producer=producer, health='idle',
                **{k:set() for k in self.ever})
            if hasattr(self.session, 'queue'):
                producer.after_book = self.session.queue.join
            markets = [(market_objects if segmented else self.session.discovery.markets[self.venue])[m] for m in group]
            for market in markets:
                self.session.emit(self.venue, dict(type='market_selected',stream_group=name,market=json.loads(json.dumps(asdict(market),default=str))))
                await asyncio.sleep(0)
                if segmented and self.session.stop_event.is_set(): return
            self.groups[name]['task'] = asyncio.create_task(producer.run(markets))
        if segmented and self.applied_generation != generation:
            admitted = self.session.emit(self.venue, dict(type='coverage_applied', generation=generation,
                selected_ids=list(ids), stream_groups=list(self.groups), usable=self.snapshot()['usable']))
            if admitted is not False:
                self.applied_generation = generation
                self.selected, self.eligible = ids, eligible
        if segmented: self.applying_generation = None
        self.snapshot()

    async def run(self, markets):
        while not self.session.stop_event.is_set():
            await self.reconcile()
            if getattr(self.session,'segmented_history',False) and self.session.stop_event.is_set(): return
            for group in self.groups.values():
                if group['task'].done():
                    if self.session.spec.get('native_sources'):
                        self.health(next(n for n,g in self.groups.items() if g is group), 'disconnected')
                        try: await group['task']
                        except Exception: pass
                        await self.session.stop_event.wait()
                        return
                    await group['task']
                    self.session.request_stop('native_stream_ended')
                    return
            await self.session.pause(.25)

    async def aclose(self):
        tasks = [g['task'] for g in self.groups.values() if 'task' in g]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for group in self.groups.values():
            await group['producer'].aclose()
        client = self.session.discovery.clients.get(self.venue)
        if client:
            await client.aclose()


class ContinuousSession(TransportSession):
    journal_encoding = 'd2-zlib-row-1'
    def __init__(self, *args, mock_segmented=False, supervised_live=False, **kwargs):
        super().__init__(*args, **kwargs)
        if self.spec.get('two_source_qualification') and not getattr(self,'supports_two_source_qualification',False):
            raise ValueError('two-source scope requires its isolated qualification runtime')
        self.mock_segmented = mock_segmented
        self.supervised_live = supervised_live
        self.segmented_history = mock_segmented or supervised_live
        if supervised_live:
            from .supervised_live import validate_live
            if mock_segmented: raise ValueError('live and mock modes are exclusive')
            validate_live(self.spec, self.endpoints, self.credentials)
        self.profile = None
        if self.spec.get('supervised_profile'):
            from .supervised import profile, RateBudget, Samples
            if not self.segmented_history: raise ValueError('supervised profile requires isolated path')
            self.profile=profile(self.spec['supervised_profile']); self.rate_budget=RateBudget()
            self.ingress_byte_limit=self.profile['encoded_ingress']
        if mock_segmented:
            from .mock_history import validate_mock
            from .segmented import POLICY
            validate_mock(self.spec, self.endpoints, self.credentials)
            self.credentials = {}
            self.ingress_record_limit = self.profile['logical'] if self.profile else POLICY['logical']
        if self.profile: self.ingress_record_limit = self.profile['logical']
        self.connection_attempts = 0
        self.started_monotonic = None
        self.peak_rss = 0
        self.peak_queue = 0
        self.snapshots = Samples(60) if self.profile else []
        self.state_samples = []

    def admit_profile(self, row, encoded):
        from .supervised import MIB
        expanded=len(packed(row).encode())
        if encoded>MIB or expanded>MIB: raise BudgetStop('supervised_row_cap')
        if rss()>=self.profile['soft_rss']: raise BudgetStop('supervised_rss_cap')
        self.rate_budget.admit(encoded,expanded,row['type']=='prediction_frame')

    def check_state(self):
        from .supervised import native_state
        from app.dashboard.bounds import retained_bytes
        d=self.discovery
        natives={v:{g:native_state(x['producer'].stream) for g,x in p.groups.items()
                    if x['producer'].stream} for v,p in self.producers.items()}
        state=retained_bytes(dict(pages=d.pages,inventory=d.inventory,markets=d.markets,partial=d.partial,
            natives=natives,records={v:p.records for v,p in self.producers.items()},
            ever={v:p.ever for v,p in self.producers.items()},snapshots=self.snapshots))
        if state>self.profile['state_bytes']: raise BudgetStop('supervised_resident_state_cap')
        diagnostics=retained_bytes({v:{g:{k:getattr(x['producer'].stream,k,[]) for k in ('events','diagnostics')}
            for g,x in p.groups.items()} for v,p in self.producers.items()})
        if diagnostics>self.profile['diagnostic_bytes']: raise BudgetStop('supervised_diagnostics_cap')
        sample=dict(seconds=time.monotonic()-self.started_monotonic,bytes=state,rss=rss(),logical=self.delivered,
                    generation=d.published_generation,groups=sum(len(p.groups) for p in self.producers.values()))
        if len(self.state_samples)<31 and (not self.state_samples or sample['seconds']-self.state_samples[-1]['seconds']>=10):
            self.state_samples.append(sample)
        return state

    def resources(self):
        self.peak_rss = max(self.peak_rss, rss())
        self.peak_queue = max(self.peak_queue, self.queue.high_items)
        return dict(peak_rss_bytes=self.peak_rss, peak_queue_records=self.peak_queue,
                    peak_queue_bytes=self.queue.high_bytes,
                    ingress_bytes=self.ingress_bytes, journal_bytes=self.journal.bytes if self.journal else 0,
                    elapsed_seconds=time.monotonic()-self.started_monotonic if self.started_monotonic else 0)

    def open_journal(self):
        if self.segmented_history:
            from .mock_history import SegmentedTransportJournal
            return SegmentedTransportJournal(self.output, self.profile['name'] if self.profile else None,
                label='real supervised venue observations' if self.supervised_live else None)
        return super().open_journal()

    def accounting(self):
        value = super().accounting()
        if self.segmented_history and self.journal:
            value['segmented'] = self.journal.history.accounting()
            value['durable_not_queued'] = self.delivered-self.persisted-self.queue.qsize()
        return value

    def emit(self, source, record):
        if self.segmented_history:
            if self.stop_event.is_set(): self.intake_closed = True
            return super().emit(source, record)
        if self.stop_event.is_set():
            return False
        if self.journal:
            r = self.resources()
            n = len(packed(self.journal.encoded(record)).encode())+2048
            reason = ('rss_cap' if r['peak_rss_bytes']>=LIMITS['rss_bytes'] else
                      'journal_reserved_stop' if self.journal.bytes+n>=32*MIB-65536 or self.journal.count>=4032 else
                      'output_reservation_stop' if (self.journal.bytes+n)*3>=120*MIB else None)
            if reason:
                self.request_stop(reason)
                raise BudgetStop(reason)
        return super().emit(source,record)

    async def start(self):
        if self.mock_segmented:
            from .mock_history import validate_mock
            validate_mock(self.spec, self.endpoints, self.credentials)
        if self.supervised_live:
            from .supervised_live import validate_live
            validate_live(self.spec, self.endpoints, self.credentials)
        self.started_monotonic = time.monotonic()
        if shutil.disk_usage(self.output.parent).free < (self.profile['disk_floor']+self.profile['output'] if self.profile else LIMITS['free_disk_bytes']+LIMITS['output_bytes']):
            raise ValueError('insufficient_pilot_disk_reservation')
        await super().start()
        self.discovery = Discovery(self)
        self.producers = {v:Venue(self,v) for v in coverage.VENUES}
        if self.spec.get('native_sources'):
            from .native_product import NativeVenue
            self.producers = {v: self.producers[v] if v in coverage.VENUES and c['state']=='enabled' and v not in getattr(self,'source_access_errors',{}) else NativeVenue(self,v,dict(c,state='unavailable') if v in getattr(self,'source_access_errors',{}) else c) for v,c in self.spec['native_sources'].items()}
            if self.spec['native_sources']['novig'].get('transport')=='graphql':
                from .novig_graphql import GraphQLVenue
                self.producers['novig']=GraphQLVenue(self,'novig',self.spec['native_sources']['novig'])
            self.health = {v:'idle' for v in self.producers}
        return self.sid

    async def discoveries(self):
        # Start-relative cadence. Await each refresh; missed ticks are skipped.
        cadence = self.profile['refresh_seconds'] if self.profile else 60
        tick = self.started_monotonic + cadence
        while not self.stop_event.is_set():
            await self.pause(max(0,tick-time.monotonic()))
            if self.stop_event.is_set():
                break
            try:await self.discovery.discover(force=True)
            except Exception:
                if not getattr(self,'product_session',False):raise
                self.emit('session',dict(type='product_coverage_status',coverage=self.status_coverage(),refresh=self.discovery.refresh,safety_exclusions=self.discovery.blocked))
            if self.profile:
                await self.stop_event.wait()
                return
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
            self.closed_at=time.monotonic()
            self.collection_seconds = self.closed_at-self.started_monotonic
            watcher.cancel()
            await asyncio.gather(watcher,return_exceptions=True)

    async def monitor(self):
        while not self.stop_event.is_set():
            await self.pause(1)
            if self.stop_event.is_set():
                break
            if getattr(self,'product_session',False):
                status=dict(coverage=self.status_coverage(),refresh=self.discovery.refresh,safety_exclusions=self.discovery.blocked)
                encoded=packed(status)
                if encoded!=getattr(self,'last_product_status',None):
                    self.emit('session',dict(type='product_coverage_status',**status))
                    self.last_product_status=encoded
            stats = self.resources()
            if stats['peak_rss_bytes']>=(self.profile['soft_rss'] if self.profile else LIMITS['rss_bytes']):
                self.request_stop('rss_cap')
            if shutil.disk_usage(self.output).free < LIMITS['free_disk_bytes']:
                self.request_stop('disk_floor')
            if self.profile and hasattr(self,'discovery'):
                try: self.check_state()
                except BudgetStop as exc: self.request_stop(str(exc))
            if hasattr(self,'discovery'):
                self.snapshots.append(dict(at=now().isoformat(),coverage=self.status_coverage(),resources=stats))
