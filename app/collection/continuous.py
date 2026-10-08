"""Finite inventory collector using shared projection, transport and journal.

No timer starts this collector. One explicit Start owns discovery and every socket;
all requests, refreshes and retries share the Start deadline and venue budgets.
"""
from .acquisition_policy import bounded_native, isolated_native, native_caps
from . import native_payload
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import fnmatch
import json
import resource
import shutil
import sys
import time

from app.adapters import kalshi, polymarket_us
from app.collection import coverage
from app.collection.prediction_producer import MockREST, PredictionProducer
from app.collection.continuous_streams import GroupBudget, Venue as StreamVenue
from app.collection.transport_session import TransportSession
from app.collection.odds_http import BudgetStop
from app.collection.venue_access import ENDPOINTS
from app.reference.records import packed
from app.diagnostics import failure

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
    """Eligibility remains source-local; exact counterpart reservations rank first."""
    if inventory.get('counterpart_reservation') and cap==100:
        cap=40 if inventory['counterpart_reservation'].get('source')=='kalshi' else 64
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
    from .v1_coverage import priority
    eligible.sort(key=lambda m: (not m.get('counterpart_priority',False),(priority(dict(sport=events[m['event_id']].get('competition'),period=m.get('period'),family=m.get('market_type'),category=m.get('category'))) if inventory.get('v1_coverage_policy') else ()),events[m['event_id']]['scheduled_start'], m['id']))
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

    def fail_budget(self, reason):
        session=getattr(self,'session',None)
        if session is None:return
        from .native_selectors import gap_enabled
        if (gap_enabled(session.spec) or getattr(self,'native_scope_request_context',False)) and reason in native_payload.query_cap_reasons(session.spec):
            # This family cannot fit; the fair selector records that terminal
            # operation without removing independent sport opportunities.
            return
        if reason=='native_response_byte_cap' and getattr(self,'gap_envelope',False):
            session.discovery.stop_source(self.source_venue,reason)
            return
        if getattr(self,'transport_policy',None) and reason.startswith('native_'):
            session.discovery.stop_source(self.source_venue,reason)
            return
        local={'prediction_discovery_byte_cap','prediction_discovery_request_cap',
               'prediction_session_byte_cap','discovery_generation_request_cap',
               'native_compression_refused','native_parse_rejected','native_incomplete_json','native_malformed_data'}
        if isolated_native(session.spec) and reason in local:
            session.discovery.stop_source(self.source_venue,reason)
        else:session.request_stop('prediction_rest_resource_cap')

    async def get(self, url, params=None, **kwargs):
        from urllib.parse import urlsplit
        from email.utils import parsedate_to_datetime
        async with self.lock:
            from .us_metadata_diagnostic import enabled as us_diagnostic
            metadata_diagnostic=bool(getattr(self,'session',None) and us_diagnostic(self.session.spec))
            if metadata_diagnostic and (getattr(self,'source_venue',None)!='polymarket_us'
                    or url!=self.endpoint+'/v1/events/127804' or params not in (None,{}) or kwargs):
                raise BudgetStop('us_metadata_request_outside_sealed_scope')
            if getattr(self,'session',None) and native_payload.enabled(self.session.spec):
                self.native_payload_policy=True
                self.response_cap=native_payload.BODY_LIMITS[native_payload.category(urlsplit(url).path)]
                from .native_selectors import gap_enabled
                from .native_books import enabled as book_slice
                self.gap_envelope=gap_enabled(self.session.spec) or book_slice(self.session.spec)
                if self.gap_envelope:self.response_cap=512*1024 if coverage.event_path(urlsplit(url).path) else 256*1024
                native_payload.configure_transport(self,self.session.spec)
            elif getattr(self,'session',None):
                # Validate an explicit new contract even outside a named probe.
                # An absent contract continues to select the historical reader.
                native_payload.configure_transport(self,self.session.spec)
            scope_ceiling=getattr(self,'native_scope_generation_ceiling',None)
            if scope_ceiling is not None and self.budget.requests>=scope_ceiling:
                raise BudgetStop('native_scope_generation_request_cap')
            if self.budget.requests >= min(self.limits['discovery_requests'],getattr(self,'request_ceiling',self.limits['discovery_requests'])):
                self.fail_budget('prediction_discovery_request_cap')
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
            from .v1_coverage import enabled as v1_coverage
            attempts=1 if metadata_diagnostic or getattr(self,'gap_envelope',False) or getattr(self,'native_scope_request_context',False) or v1_coverage(getattr(self,'session',None).spec if getattr(self,'session',None) else {}) else 2
            for attempt in range(attempts):
                if self.budget.requests >= getattr(self,'request_ceiling',self.limits['discovery_requests']):
                    raise BudgetStop('discovery_generation_request_cap')
                try:
                    response = await super().get(url, params, **kwargs)
                except BudgetStop as exc:
                    self.fail_budget(str(exc))
                    raise
                except (TimeoutError, __import__('aiohttp').ClientError):
                    if attempt==attempts-1:
                        raise
                    await self.bounded_wait(1)
                    continue
                if not metadata_diagnostic and getattr(self,'gap_envelope',False) and response.status_code in (429,500,502,503,504):
                    delay=1.0
                    value=response.headers.get('Retry-After')
                    if value:
                        try:delay=max(delay,float(value))
                        except ValueError:delay=max(delay,(parsedate_to_datetime(value)-now()).total_seconds())
                    if not 0<=delay<=180:raise ValueError('gap_recovery_retry_after_outside_bound')
                    self.gap_retry_at=time.monotonic()+delay
                if response.status_code not in (429, 500, 502, 503, 504) or attempt==attempts-1:
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
        self.source_stops = {}
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

    def stop_source(self, venue, reason):
        if venue in self.source_stops:return
        self.source_stops[venue]=reason
        producer=self.session.producers.get(venue)
        if producer:
            for group in producer.groups.values():
                group['invalidated']=True
                group['usable'].clear()
                if 'task' in group:group['task'].cancel()
        if hasattr(self.session,'set_health'):self.session.set_health(venue,'terminal:'+reason)
        self.session.emit(venue,dict(type='native_source_stopped',reason=reason,
            admission='disabled for remainder of attempt',retry=False))
        self.finish_terminal_sources()

    def bound_source_catalog(self, venue, catalog):
        """Admission requires the complete source catalog to fit its own budget.

        Complete raw receipts stay in the journal. A source that cannot fit is
        never semantically admitted by selecting only a cheap subset of fields.
        """
        limits = self.session.spec.get('native_transport')
        if limits is None:return
        from app.dashboard.bounds import retained_bytes
        size = retained_bytes(catalog)
        measurements = getattr(self, 'source_resource_measurements', {})
        previous = measurements.get(venue, {})
        if previous.get('generation') != self.generation or previous.get('last_bytes') != size:
            self.source_resource_measurements = measurements
            measurements[venue] = dict(generation=self.generation, last_bytes=size,
                max_bytes=max(size, previous.get('max_bytes',0)),
                limit_bytes=limits['source_inventory_bytes'],
                admission='within_bound' if size <= limits['source_inventory_bytes'] else 'rejected')
            self.session.emit(venue, dict(type='native_source_resource_measurement',
                generation=self.generation, catalog_retained_bytes=size,
                catalog_peak_retained_bytes=measurements[venue]['max_bytes'],
                limit=limits['source_inventory_bytes'],
                admission='within_bound' if size <= limits['source_inventory_bytes'] else 'rejected'))
        if size > limits['source_inventory_bytes']:
            self.stop_source(venue, 'native_source_inventory_cap')

    def finish_terminal_sources(self):
        if not self.completed or not self.session.spec.get('native_discovery'):return
        # Only a finite discovery session with no reference/aggregate worker is exhausted.
        if getattr(self.session,'aggregate',None) or getattr(self.session,'reference',None):return
        selected=[v for v in self.venues if self.session.spec.get('native_sources',{}).get(v,{}).get('state','enabled')=='enabled']
        if selected and all(v in self.source_stops for v in selected):
            self.session.request_stop('all_selected_sources_terminal_no_permitted_work')

    def status(self):
        return dict(source_stops=deepcopy(self.source_stops),
                    source_catalog_resources=deepcopy(getattr(self,'source_resource_measurements',{})),
                    published_generation=self.published_generation, published_at=self.published_at,
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
        partial = coverage.catalog(self.pages, venue, now(),v1_templates=self.session.spec.get('native_review_records',[]) if self.session.spec.get('v1_comparison_policy') else ())
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
        from .native_scope_discovery import enabled as scoped
        if scoped(self.session.spec,venue):
            row=dict(row,native_binding_revision='live-native-binding-2')
        if self.session.spec.get('v1_comparison_policy')in ('manual-comparison-1','manual-comparison-2'):
            row=dict(row,v1_comparison_policy=self.session.spec['v1_comparison_policy'])
        if bounded_native(self.session.spec):
            from .native_selectors import policy
            row=dict(row,acquisition_discovery_policy=policy(self.session.spec))
        binding=getattr(self.clients.get(venue),'native_scope_binding',None)
        if binding:
            from .native_scope_bindings import POLICY as SCOPE_POLICY
            row=dict(row,native_scope_policy=SCOPE_POLICY,native_scope_binding=deepcopy(binding))
        from .v1_coverage import enabled as v1_coverage
        if v1_coverage(self.session.spec):row=dict(row,v1_coverage_policy='v1-missing-pairs-1')
        if row.get('status') is not None:
            self.responses[venue]['received'] += 1
        admitted, error = self.admission(venue, dict(row, discovery_generation=self.generation))
        if admitted:
            if row.get('status') is not None:
                self.responses[venue]['durably_retained'] += 1
            if (coverage.event_path(row['path']) or coverage.market_path(row['path']) or row.get('v1_coverage_policy') and row['path']=='/trade-api/v2/milestones'):
                self.pages.append(dict(row, source=venue))
                self.safety(venue)
        if error:
            raise error
        if not admitted:
            raise BudgetStop('catalog_response_not_retained')

    async def pages_for(self, venue, path, query, field, size, page_cap=None, start_position=None):
        client = self.clients[venue]
        client.session = self.session
        cursor = start_position if start_position is not None and venue=='kalshi' else ''
        seen = set()
        results = []
        bounded=bounded_native(self.session.spec)
        override_cap=page_cap
        page_cap=(75 if venue=='polymarket_us' and isolated_native(self.session.spec) else 3) if field=='events' else 1
        if native_payload.enabled(self.session.spec):
            page_cap=native_payload.PAGE_CAPS[venue] if field=='events' else native_payload.MARKET_PAGES
        if override_cap is not None:page_cap=override_cap
        seen_rows=set()
        for page in range(page_cap if bounded or override_cap is not None else 10):
            pagination = dict(limit=size, **({'cursor': cursor} if venue == 'kalshi' else {'offset': (start_position or 0)+page*size}))
            response = await client.get(endpoints_for(self.session)[venue]['rest']+path, {**query, **pagination})
            if response.status_code != 200:
                raise ValueError('catalog_http_'+str(response.status_code))
            data = response.json()
            rows = data.get(field)
            if not isinstance(rows, list):
                raise ValueError('missing_catalog_array')
            if isolated_native(self.session.spec):
                if any(not isinstance(r,dict) for r in rows):raise ValueError('invalid_catalog_row')
                ids=[str(r.get('id' if venue=='polymarket_us' else 'event_ticker' if field=='events' else 'ticker') or '') for r in rows]
                explicit_v2=native_payload.exact_transport(self.session.spec.get('native_transport'))
                if (len(rows)>size and not explicit_v2) or any(not x for x in ids) or len(set(ids))!=len(ids) or seen_rows.intersection(ids):
                    self.stop_source(venue,'duplicate_or_invalid_catalog_page')
                    raise ValueError('duplicate_or_invalid_catalog_page')
                seen_rows.update(ids)
                if len(rows)>size:
                    self.session.emit(venue,dict(type='native_catalog_requested_limit_exceeded',path=path,
                        requested_limit=size,returned_rows=len(rows),
                        treatment='Retain every complete bounded row; do not infer page exhaustion or advance an offset'))
            results.extend(rows)
            if len(rows)>size:
                break
            if venue == 'kalshi':
                cursor = data.get('cursor')
                if not isinstance(cursor, str) or cursor in seen:
                    if isolated_native(self.session.spec):self.stop_source(venue,'invalid_catalog_cursor')
                    raise ValueError('invalid_catalog_cursor')
                if not cursor:
                    break
                seen.add(cursor)
            elif len(rows) < size:
                break
        return results

    async def venue(self, venue):
        s = self.session
        if venue in self.source_stops:raise BudgetStop(self.source_stops[venue])
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
                lambda r: self.receipt(venue, r),
                native_payload.transport_timeout(s.spec) if s.spec.get('native_transport') else 5,
                s.producers[venue].budget,
                venue=venue if s.spec['mode']=='real' else None,
                credential=(s.credentials or {}).get(venue))
        client = self.clients[venue]
        client.session = s
        # Source-local failures need identity even when discovery is isolated by
        # configured native scopes rather than the bounded acquisition policy.
        client.source_venue=venue
        if bounded_native(s.spec):
            client.request_ceiling=native_caps(s.spec)[venue]
            if isolated_native(s.spec):
                client.limits={**client.limits,'discovery_requests':min(client.limits['discovery_requests'],client.request_ceiling)}
                client.strict_eof=True
        if getattr(s,'profile',None):
            client.pacing_venue = venue
            client.request_ceiling=min(s.profile['requests'],client.budget.requests+s.profile['generation_requests'])
        if venue == 'kalshi':
            if client.rate is None and not s.spec.get('native_discovery'):
                values = []
                for path in ('/trade-api/v2/account/limits', '/trade-api/v2/account/endpoint_costs'):
                    r = await client.get(endpoints_for(self.session)[venue]['rest']+path)
                    if r.status_code != 200:
                        raise ValueError('account_limits_unavailable')
                    values.append(r.json())
                client.account_limits(*values)
                s.emit(venue, dict(type='verified_account_budget', limits=values[0], costs=values[1]))
            from .native_scope_discovery import enabled as scoped
            if scoped(s.spec,venue):
                await self.catalog_scope(venue)
                return
            series=s.spec.get('native_sources',{}).get(venue,{}).get('series',['KXNFLGAME'])
            if bounded_native(s.spec):
                await self.catalog_scope(venue)
                return
            for series_id in series:
                await self.pages_for(venue, '/trade-api/v2/events',
                    dict(series_ticker=series_id,status='open',with_milestones='true'),'events',200)
                cat=coverage.catalog(self.pages,venue,now(),v1_templates=self.session.spec.get('native_review_records',[]) if self.session.spec.get('v1_comparison_policy') else ())
                for event in cat['events']:
                    if event['exclusion'] is None and event['native_aliases'].get('series_ticker')==series_id:
                        await self.pages_for(venue,'/trade-api/v2/markets',dict(event_ticker=event['id']),'markets',native_payload.MARKET_SIZE if native_payload.enabled(self.session.spec) else 200)
        else:
            from .native_scope_discovery import enabled as scoped
            if scoped(s.spec,venue):
                await self.catalog_scope(venue)
                return
            if bounded_native(s.spec):
                await self.catalog_scope(venue)
                return
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

    async def catalog_scope(self,venue):
        """Discover IDs in bounded public catalogs; never invent series or tag keys."""
        from . import native_selectors, native_books
        from .us_metadata_diagnostic import enabled as us_diagnostic
        if us_diagnostic(self.session.spec):
            if venue!='polymarket_us':raise BudgetStop('us_metadata_request_outside_sealed_scope')
            # No parameters, pagination, fallback or a second operation exists.
            return await self.clients[venue].get(self.clients[venue].endpoint+'/v1/events/127804',{})
        if native_books.enabled(self.session.spec):
            return await native_books.discover(self,venue)
        from .native_scope_discovery import enabled as scoped, discover as discover_scopes
        if scoped(self.session.spec,venue):return await discover_scopes(self,venue)
        if native_selectors.enabled(self.session.spec):
            return await native_selectors.discover(self,venue)
        if venue=='kalshi':
            await self.pages_for(venue,'/trade-api/v2/events',
                dict(status='open',with_milestones='true',with_nested_markets='false' if native_payload.enabled(self.session.spec) else 'true'),'events',200)
        else:
            await self.pages_for(venue,'/v1/events',
                dict(active='true',closed='false',orderBy='startTime',orderDirection='asc'),'events',native_payload.PAGE_SIZES[venue] if native_payload.enabled(self.session.spec) else 2 if isolated_native(self.session.spec) else 50)
        cat=coverage.catalog(self.pages,venue,now(),v1_templates=self.session.spec.get('native_review_records',[]) if self.session.spec.get('v1_comparison_policy') else ())
        wanted={s['sport'] for s in self.session.spec['source_session']['scopes']}
        selected={}
        for event in sorted(cat['events'],key=lambda e:(e.get('scheduled_start') or '',e['id'])):
            sport=event.get('competition')
            if sport not in wanted or sport in selected or event['exclusion'] or event['identity']!='resolved':continue
            if coverage.stamp(event['scheduled_start'])<=now()+timedelta(seconds=300):continue
            selected[sport]=event
        self.session.emit(venue,dict(type='native_acquisition_selection',policy=self.session.spec['source_session']['native_discovery'],
            selected={k:v['id'] for k,v in selected.items()},unavailable_sports=sorted(wanted-set(selected)),
            discovery_state=cat['event_discovery'],
            limitation='Bounded catalog only; unavailable_sports means not selected from this retained traversal, not proven absent; unresolved raw listings retained; no inferred native identities'))
        for event in selected.values():
            if venue=='kalshi':
                await self.pages_for(venue,'/trade-api/v2/markets',dict(event_ticker=event['id']),'markets',native_payload.MARKET_SIZE if native_payload.enabled(self.session.spec) else 200)
            elif event['_native'].get('gameId'):
                await self.pages_for(venue,'/v1/markets',dict(gameId=str(event['_native']['gameId']),active='true',closed='false'),'markets',50)
        # Restrict subsequent subscription admission to these exact runtime IDs.
        if not hasattr(self,'acquisition_selected'):self.acquisition_selected={}
        self.acquisition_selected[venue]={e['id'] for e in selected.values()}

    def project(self):
        paired=self.session.spec.get('v1_comparison_policy')=='manual-comparison-2'
        cats = {v: deepcopy(self.native_catalogs[v]) if v in self.native_catalogs else coverage.catalog(self.pages, v, now(),v1_templates=self.session.spec.get('native_review_records',[]) if self.session.spec.get('v1_comparison_policy') else (),compact_output=not paired) for v in self.venues}
        if paired:
            if self.session.spec.get('source_session'):
                from .source_session import filter_native_catalog
                for v,c in cats.items():
                    if v in ('kalshi','polymarket_us'):filter_native_catalog(c,v,self.session.spec['source_session'])
            for v,ids in getattr(self,'acquisition_selected',{}).items():
                for m in cats[v]['markets']:
                    if m['event_id'] not in ids:m['exclusion']=m.get('exclusion') or 'Outside runtime-selected acquisition events'
            from .counterparts import reserve
            from .catalog_metadata import compact
            live={v:c for v,c in cats.items() if v in ('kalshi','polymarket_us') and v not in self.source_stops}
            reserve(live,now())
            for v,c in live.items():compact(c,v)
        if self.session.spec.get('native_transport'):
            from .catalog_metadata import compact
            for v, cat in cats.items():
                self.bound_source_catalog(v, cat)
                if v in self.source_stops:
                    # Preserve original terms through page references, with no
                    # operating identity or selected contract from this source.
                    for row in cat['events'] + cat['markets']:
                        row['exclusion'] = self.source_stops[v]
                    compact(cat, v)
        for v,ids in getattr(self,'acquisition_selected',{}).items():
            for market in cats[v]['markets']:
                if market['event_id'] not in ids:market['exclusion']=market.get('exclusion') or 'Outside runtime-selected acquisition events'
        if self.session.spec.get('source_session'):
            from .source_session import filter_native_catalog
            for v in cats:
                if v in ('kalshi','polymarket_us'):filter_native_catalog(cats[v],v,self.session.spec['source_session'])
        from .native_review_binding import apply as bind_current_reviews
        bind_current_reviews(self, cats, now())
        from .native_books import enabled as book_slice
        if book_slice(self.session.spec):
            for v in coverage.VENUES:
                cats[v]['qualification_ids']=getattr(self,'book_market_ids',{}).get(v,[])
        for v,reason in self.source_stops.items():
            if v in cats:cats[v].update(source_error=reason,selected_exclusions=[dict(reason=reason,admission='terminal',retry=False)])
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
                if isolated_native(self.session.spec):
                    from .native_selectors import policy, enabled, SPORTS
                    cat['acquisition_scope']=dict(policy=policy(self.session.spec),
                        sports=list(SPORTS) if enabled(self.session.spec) else [scope['sport'] for scope in self.session.spec['source_session']['scopes']],
                        listings='bounded evidenced series/league games; independent sport gaps' if enabled(self.session.spec) else 'bounded open catalog; no series/tag filter')
                from .native_scope_discovery import enabled as scoped, scopes as requested_scopes
                if scoped(self.session.spec,v):
                    from .native_scope_bindings import POLICY as SCOPE_POLICY
                    cat['acquisition_scope']=dict(policy=SCOPE_POLICY,requested_cells=requested_scopes(self.session.spec,v),
                        listings='exact retained Kalshi series or evidenced US game selectors; per-cell omissions retained',
                        predicate_admission='native catalog keys do not establish oriented line, period boundary, championship field or season terms')
                for item in cat['events']+cat['markets']:
                    item['native_metadata']=None if item.get('native_metadata_ref') else deepcopy(item.get('_native'))
                if v=='polymarket_us':
                    for item in cat['markets']:
                        for side in item['sides']:
                            if side.get('role')=='Short':side.update(purchase_support='supported',basis='1 minus native Long bid; same contract quantity; B3 conversion')
            cat['counts'] = coverage.totals(cat)
            for row in cat['markets']:
                if native_payload.enabled(self.session.spec) and row.get('exclusion'):continue
                proof = row['provenance'][0]
                page = next((p for p in self.pages if p['body_sha256']==proof['body_sha256'] and p['source']==v and p.get('complete') is True),None)
                parent = next((e for e in cat['events'] if e['id']==row['event_id']),None)
                if page is None or parent is None:
                    row['exclusion']='missing_source_or_parent_event'
                    row['parse_exclusion']='market_parse_error'
                    continue
                body, _ = coverage.decode_page(page)
                r = coverage.response(v, page, body)
                if getattr(self.session, 'mock_segmented', False) or (getattr(self.session,'product_session',False) and self.session.spec.get('mode','mock')=='mock'):
                    from dataclasses import replace
                    from app.models.core import EvidenceKind
                    r = replace(r, kind=EvidenceKind.SYNTHETIC)
                from .native_scope_bindings import POLICY as SCOPE_POLICY
                try:
                    markets[v][row['id']] = (kalshi.parse_market(r,row['_native'],row['event_id'],parent['native_aliases'].get('series_ticker','unknown'),
                            typed_scope=page.get('native_scope_policy')==SCOPE_POLICY)
                        if v=='kalshi' else polymarket_us.parse_market(r,row['_native'],row['event_id']))
                except (ValueError, KeyError, TypeError):
                    row['parse_exclusion'] = 'market_parse_error'
            from .v1_coverage import enabled as v1_coverage
            if v1_coverage(self.session.spec):cat['v1_coverage_policy']='v1-missing-pairs-1'
            ids, eligible = select_inventory(cat, now())
            if self.session.spec.get('native_discovery',{}).get('discovery_only'):ids=[]
            cat['selection'] = dict(ids=ids, eligible=eligible)
            for row in cat['markets']+cat['events']:
                row.pop('_native', None)
        return cats, markets

    async def discover(self, force=False):
        async with self.lock:
            if self.completed and not force:
                return self.markets
            if bounded_native(self.session.spec) and self.generation>=3:
                return self.markets
            if getattr(self.session,'profile',None) and self.generation>=self.session.profile['generations']:
                raise BudgetStop('supervised_generation_cap')
            if self.session.spec.get('native_discovery') and self.generation>=1:return self.markets
            self.selection_time=now()
            self.generation += 1
            self.pages = []
            self.counterpart_rank_catalogs={}
            self.partial = None
            self.refresh = dict(state='running', generation=self.generation, started_at=now().isoformat())
            try:
                from .us_metadata_diagnostic import enabled as us_diagnostic
                if us_diagnostic(self.session.spec):return await self.diagnostic()
                if self.session.spec.get('source_session',{}).get('coverage_policy')=='v1-counterpart-completion-1':
                    # Current US listing/detail establishes independent identities
                    # before Kalshi ranks its returned event candidates. Failures
                    # remain query/source-local and cannot skip the healthy venue.
                    results_by_source={}
                    for v in ('polymarket_us','kalshi',*[v for v in self.venues if v not in ('polymarket_us','kalshi')]):
                        if v not in self.venues:continue
                        try:results_by_source[v]=await self.venue(v)
                        except Exception as exc:results_by_source[v]=exc
                    results=[results_by_source[v] for v in self.venues]
                else:
                    results = await asyncio.gather(*(self.venue(v) for v in self.venues), return_exceptions=True)
                errors = [type(e).__name__ for e in results if isinstance(e, BaseException)]
                for venue,result in zip(self.venues,results):
                    if isinstance(result,BaseException):
                        failure(__name__, 'native_discovery_'+venue, result)
                if errors and (not getattr(self.session,'product_session',False) or (self.completed and not self.session.spec.get('native_sources') and not self.session.spec.get('source_session'))):
                    raise ValueError('; '.join(errors))
                if isolated_native(self.session.spec):
                    for v,result in zip(self.venues,results):
                        if isinstance(result,BaseException):self.stop_source(v,type(result).__name__)
                from .native_books import enabled as book_slice, finish as finish_books
                if book_slice(self.session.spec):await finish_books(self)
                cats, markets = self.project()
                if errors:
                    for v,result in zip(self.venues,results):
                        if isinstance(result,BaseException):
                            cats[v].update(event_discovery='failed',market_completeness='partial',selection=dict(ids=[],eligible=None),source_error=self.source_stops.get(v,type(result).__name__))
                            if v not in self.source_stops:self.stop_source(v,type(result).__name__)
                            for item in cats[v]['markets']:item['exclusion']='Source admission stopped: '+type(result).__name__
                            cats[v]['counts']=coverage.totals(cats[v])
                            markets[v]={}
                if getattr(self.session,'profile',None):
                    for cat in cats.values():
                        if len(cat['events'])>128 or len(cat['markets'])>256: raise BudgetStop('supervised_catalog_cap')
                from .native_selectors import policy as discovery_policy, POLICY as DIRECTED
                if self.session.spec.get('native_transport') or discovery_policy(self.session.spec) in ('bounded-open-catalog-v4',DIRECTED):
                    # Raw pages are already durable. Reject before publishing an
                    # inventory that cannot fit one queue slot; never write a
                    # giant row and discover the queue mismatch afterwards.
                    from app.dashboard.bounds import retained_bytes
                    if retained_bytes(cats)>LIMITS['queue_bytes']-65536:
                        self.session.request_stop('normalized_inventory_cap')
                        raise BudgetStop('normalized_inventory_cap')
                    if hasattr(self.session,'queue'):await self.session.queue.join()
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
                self.finish_terminal_sources()
                return self.markets
            except BaseException as exc:
                self.refresh.update(state='interrupted' if isinstance(exc, asyncio.CancelledError) else 'failed',
                                    reason=type(exc).__name__, finished_at=now().isoformat())
                # Durable partial progress is diagnostic only, never a coverage denominator.
                self.partial = {v:coverage.catalog(self.pages,v,now(),v1_templates=self.session.spec.get('native_review_records',[]) if self.session.spec.get('v1_comparison_policy') else ()) for v in self.venues}
                for cat in self.partial.values():
                    for row in cat['events']+cat['markets']:
                        row.pop('_native',None)
                raise

    async def diagnostic(self):
        """One public response, independent findings and immediate terminal cleanup.

        Whole raw receipts are durable before any catalog or semantic admission.
        Closed/started events can answer delivery; no market is selected for books.
        """
        from .us_metadata_diagnostic import evaluate
        from .native_product import empty_catalog
        from app.dashboard.bounds import retained_bytes
        venue='polymarket_us'
        try:
            await self.venue(venue)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure(__name__, 'native_diagnostic_discovery', exc)
            self.stop_source(venue,type(exc).__name__)
        catalog_error=None
        try:
            catalog=coverage.catalog(self.pages,venue,now(),v1_templates=self.session.spec.get('native_review_records',[]) if self.session.spec.get('v1_comparison_policy') else ())
            self.bound_source_catalog(venue,catalog)
            if self.source_stops.get(venue)=='native_source_inventory_cap':catalog_error='native_source_inventory_cap'
        except (ValueError,KeyError,TypeError,AttributeError):
            catalog=empty_catalog('unavailable','native_catalog_parse_error')
            catalog_error='native_catalog_parse_error'
            self.stop_source(venue,catalog_error)
        self.diagnostic_result=evaluate(self.pages,self.session.spec,now(),admission_error=catalog_error)
        self.session.emit(venue,self.diagnostic_result)
        # Keep every original contract field available through its complete raw
        # page reference. The diagnostic publishes no operating market objects.
        if catalog_error:
            from .catalog_metadata import compact
            for row in catalog['events']+catalog['markets']:row['exclusion']=catalog_error
            compact(catalog,venue)
        for kind in ('events','markets'):
            for row in catalog[kind]:
                row['native_metadata_ref']=dict(version='catalog-metadata-reference-1',source=venue,
                    response_sha256=row['provenance'][0]['body_sha256'],entity='event' if kind=='events' else 'market',
                    id=row['id'],event_id=row.get('event_id',row['id']))
                row.pop('_native',None)
                if kind=='markets':row['subscription_exclusion']='metadata_only_diagnostic_no_book_acquisition'
        catalog.update(selection=dict(ids=[],eligible=None),acquisition_scope='exact event metadata-only diagnostic',
            update_path='single public HTTP response; no stream',qualification='delivery and metadata findings only; no paired review or books')
        cats={v:catalog if v==venue else empty_catalog('disabled') for v in self.venues}
        if retained_bytes(cats)>LIMITS['queue_bytes']-65536:
            self.stop_source(venue,'normalized_inventory_cap')
            raise BudgetStop('normalized_inventory_cap')
        if hasattr(self.session,'queue'):await self.session.queue.join()
        at=now().isoformat()
        admitted,error=self.admission('session',dict(type='coverage_inventory',generation=self.generation,
            published_at=at,inventory=cats,previous_generation=self.published_generation,discovery_error=None))
        if error:raise error
        if not admitted:raise BudgetStop('inventory_publication_not_retained')
        self.inventory=cats;self.markets={v:{} for v in self.venues}
        self.published_generation,self.published_at=self.generation,at
        self.completed=True;self.coverage=cats;self.refresh.update(state='completed',finished_at=at)
        self.stop_source(venue,'metadata_diagnostic_complete')
        self.finish_terminal_sources()
        return self.markets


class Venue(StreamVenue):
    """Bind stream dependencies while preserving the public collector entry point."""
    def __init__(self, session, venue):
        super().__init__(session, venue,
                         clock=lambda: now(),
                         inventory_selector=lambda *a, **k: select_inventory(*a, **k),
                         endpoints=lambda owner: endpoints_for(owner),
                         producer_factory=lambda *a, **k: PredictionProducer(*a, **k))


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
                      'expanded_journal_reserved_stop' if self.journal.expanded_bytes+len(packed(record).encode())+2048>=32*MIB-65536 else
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
        cadence = self.profile['refresh_seconds'] if self.profile else self.spec['discovery_cadence']
        tick = self.started_monotonic + cadence
        while not self.stop_event.is_set():
            await self.pause(max(0,tick-time.monotonic()))
            if self.stop_event.is_set():
                break
            try:await self.discovery.discover(force=True)
            except Exception as exc:
                if not getattr(self,'product_session',False):raise
                failure(__name__, 'product_discovery_refresh', exc)
                self.emit('session',dict(type='product_coverage_status',coverage=self.status_coverage(),refresh=self.discovery.refresh,safety_exclusions=self.discovery.blocked))
            if self.profile:
                await self.stop_event.wait()
                return
            tick += cadence
            while tick <= time.monotonic():
                tick += cadence

    def status_coverage(self):
        cats = self.discovery.inventory or {}
        return {v:dict(discovered_events=len(cats[v]['events']) if v in cats else None,
                       discovered_markets=len(cats[v]['markets']) if v in cats else None,
                       generation=self.discovery.published_generation,
                       eligible=cats.get(v,{}).get('selection',{}).get('eligible'),
                       selected=len(cats[v]['selection']['ids']) if v in cats else None,
                       event_discovery=cats.get(v,{}).get('event_discovery','pending'),
                       terminal_reason=self.discovery.source_stops.get(v),
                       market_completeness=cats.get(v,{}).get('market_completeness','pending'),
                       **p.snapshot()) for v,p in self.producers.items()}

    async def run(self):
        self.monitor_error = None
        async def monitored():
            try:
                await self.monitor()
                if not self.stop_event.is_set():
                    raise RuntimeError('resource monitor ended before Stop')
            except asyncio.CancelledError as exc:
                if not self.stop_event.is_set():
                    failure(__name__, 'resource_monitor', exc)
                    self.monitor_error = type(exc).__name__
                    self.intake_closed = True
                    self.request_stop('resource_monitor_failure:'+self.monitor_error)
                raise
            except Exception as exc:
                failure(__name__, 'resource_monitor', exc)
                self.monitor_error = type(exc).__name__
                self.intake_closed = True
                # A failed safety check cannot leave collection running without
                # its resource bounds. Terminal writing still belongs to run().
                self.request_stop('resource_monitor_failure:'+self.monitor_error)
        watcher = asyncio.create_task(monitored())
        try:
            await super().run()
        finally:
            self.closed_at=time.monotonic()
            self.collection_seconds = self.closed_at-self.started_monotonic
            watcher.cancel()
            await asyncio.gather(watcher,return_exceptions=True)
            if self.monitor_error:
                self.state = 'failed'

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
