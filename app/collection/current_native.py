"""Native source owner: bounded rediscovery and one reconciled socket per source.

Reuse complete HTTP admission, reviewed catalog bindings and native stream
reconstruction. Current operation retains no wire/frame/quote journal.
"""
import asyncio
import base64
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import time
from uuid import uuid4
from websockets.asyncio.client import connect
from app.models.core import BookSync, MarketState, SourceTimeProgress
from . import coverage, native_payload
from .continuous import REST
from .prediction_producer import MockREST, PredictionBudget
from .native_scope_bindings import selectors_for, POLICY as SCOPE_POLICY
from .native_selectors import query, candidates
from .venue_access import ENDPOINTS, load_credentials
from .current_sink import utc
from .odds_http import BudgetStop

class CatalogResync(Exception):
    """Local identity enrichment requires a fresh subscription image."""

class NativeWorker:
    def __init__(self, service, venue):
        self.service, self.venue = service, venue
        self.config = service.config
        self.closed = False
        self.socket = None
        self.stream_task = None
        self.client = None
        self.credential = None
        self.signature = None
        self.metrics = dict(requests=0, connections=0, frames=0, books=0, bytes=0,
                            generations=0, reconciliations=0, resyncs=0, retries=0,
                            source_receipt_ms=None, receipt_projection_ms=None)
        self.pages = []
        self.catalog = dict(events=[], markets=[])
        self.markets = {}
        self.backoff_until = 0
        self.failed = False
        self.findings = []
        self.reconcile_needed = False
        self.wake_task = None

    def request_resync(self):
        self.reconcile_needed = True
        if self.socket and (self.wake_task is None or self.wake_task.done()):
            self.wake_task = asyncio.create_task(self.socket.close())

    def guard(self):
        if self.closed or not self.service.dispatch or self.failed:
            raise asyncio.CancelledError()
        if time.monotonic() >= self.service.deadline:
            raise BudgetStop('attended_runtime_deadline')

    def receipt(self, row):
        # Complete responses are transient discovery inputs, then discarded.
        self.metrics['requests'] = self.client.budget.requests
        self.metrics['bytes'] = self.client.budget.bytes
        self.metrics['last_http'] = dict(path=row['path'],params=row.get('params',{}),status=row['status'],complete=row['complete'],
            reason=row.get('delivery_reason'),body_sha256=row['body_sha256'])
        self.service.observation(self.venue, 'http', dict(status=row['status'], complete=row['complete'],
            path=row['path'], bytes=row.get('resource_usage',{}).get('wire_bytes'),
            body_sha256=row['body_sha256'], reason=row.get('delivery_reason')))
        if row['status'] in (401, 403):
            self.failed = True
            self.service.issue(self.venue, 'authentication' if row['status']==401 else 'entitlement', 'http_'+str(row['status']))
            self.service.source_state(self.venue, 'unavailable', 'Native catalog access was refused.')
        if row['status'] == 429:
            from email.utils import parsedate_to_datetime
            delay = 60
            for key, value in row.get('response_headers', []):
                if key.lower() == 'retry-after':
                    try: delay = max(delay, float(value))
                    except ValueError: delay = max(delay, (parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
            if not 0 <= delay <= 300:
                self.failed = True
                raise BudgetStop('retry_after_outside_operational_envelope')
            self.backoff_until = time.monotonic()+delay
        if not row['complete'] or not row.get('usable_metadata'):
            query_caps=native_payload.query_cap_reasons(dict(native_transport=native_payload.TRANSPORT_CONTRACT,v1_comparison_policy='manual-comparison-2'))
            if row.get('delivery_reason') not in query_caps | {'http_status', None} and row['status']==200:
                self.failed = True
            return
        page = dict(row, source=self.venue, native_binding_revision='live-native-binding-2',
                    v1_comparison_policy='manual-comparison-2')
        scope = getattr(self, '_scope', None)
        if scope: page.update(native_scope_binding=scope, native_scope_policy=SCOPE_POLICY)
        if len(self.pages) >= self.config['discovery_pages'] or sum(len(p['body_b64']) for p in self.pages)+len(page['body_b64']) > 8*1024*1024:
            raise BudgetStop('current_discovery_retained_cap')
        self.pages.append(page)

    async def get(self, path, params, field=None, scope=None):
        self.guard()
        if self.backoff_until > time.monotonic():
            raise BudgetStop('provider_backoff_pending')
        self._scope = scope
        try:
            # No invisible per-operation retry: the source runtime owns backoff.
            response = await MockREST.get(self.client, self.client.endpoint+path, params)
        finally: self._scope = None
        if response.status_code != 200:
            raise ValueError('http_'+str(response.status_code))
        data = response.json()
        rows = data.get(field) if field else data
        if field:
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ValueError('malformed_catalog')
            id_field = 'event_ticker' if self.venue=='kalshi' and field=='events' else 'ticker' if self.venue=='kalshi' else 'id'
            ids = [str(r.get(id_field) or '') for r in rows]
            if not all(ids) or len(set(ids)) != len(ids): raise ValueError('duplicate_catalog_identity')
        return rows

    async def discover(self):
        self.pages = []
        self.findings = []
        now = datetime.now(timezone.utc)
        selected = []
        # Scope is deliberately bounded: one first page per sport/family and
        # selected-event metadata. Empty pages prove only this query's result.
        if self.venue == 'kalshi':
            for sport in self.config['sports']:
                for family in self.config['families']:
                    selectors = selectors_for(sport+'/full_game/'+family)
                    if not selectors: continue
                    selector = selectors[0]
                    rows = await self.get(selector['path'], dict(selector['params'], limit=5), 'events', selector['binding'])
                    # Exact typed series selectors also cover spread/total;
                    # the older game-only selector must not silently filter them.
                    page=self.pages[-1]
                    raw,_=coverage.decode_page(page)
                    native_events=[coverage.event_record(self.venue,page,raw,e,i,now) for i,e in enumerate(rows)]
                    found = [dict(id=e['id']) for e in native_events if not e.get('exclusion') and e.get('scheduled_start')]
                    found.sort(key=lambda e:next(n['scheduled_start'] for n in native_events if n['id']==e['id']))
                    self.findings.append(dict(sport=sport,family=family,rows=len(rows),selected=[e['id'] for e in found[:1]],
                        scope='first bounded listing page; later pages unobserved'))
                    for event in found[:1]:
                        if event['id'] not in {x[0] for x in selected}:
                            selected.append((event['id'], selector['binding']))
                    if len(selected) >= self.config['events_per_source']: break
            for eid, scope in selected:
                await self.get('/trade-api/v2/markets', dict(event_ticker=eid, limit=50), 'markets', scope)
        else:
            for sport in self.config['sports']:
                path, params = query(self.venue, sport, now)
                try:rows = await self.get(path, dict(params, limit=1, offset=0), 'events')
                except BudgetStop as exc:
                    query_caps=native_payload.query_cap_reasons(dict(native_transport=native_payload.TRANSPORT_CONTRACT,v1_comparison_policy='manual-comparison-2'))
                    if str(exc) not in query_caps:raise
                    self.service.issue(self.venue,'resource',str(exc))
                    self.findings.append(dict(sport=sport,state='query_capacity_exclusion',reason=str(exc),scope='one bounded query; no support inference'))
                    continue
                found, excluded = candidates(self.pages[-1:], self.venue, sport, now)
                self.findings.append(dict(sport=sport,rows=len(rows),selected=[e['id'] for e in found[:1]],exclusions=excluded[:5],
                    scope='first bounded listing page; later pages unobserved'))
                for event in found[:1]:
                    if event['id'] not in {x['id'] for x in selected}: selected.append(event)
            for event in selected[:self.config['events_per_source']]:
                # Listing-bound game ID is the only permitted market locator.
                if event.get('market_bindings'):
                    for binding in event['market_bindings'][:3]:
                        await self.get('/v1/market/id/'+binding['id'], {})
                elif event.get('game_id'):
                    await self.get('/v1/markets', dict(gameId=str(event['game_id']), active='true', closed='false', limit=5, offset=0), 'markets')
        selection=None
        if self.venue=='polymarket_us':
            selection=dict(events=[e['id'] for e in selected],markets=[b['id'] for e in selected for b in e.get('market_bindings',[])[:3]])
            # A game-ID market query must contribute its exact returned IDs.
            for page in self.pages:
                if page['path']=='/v1/markets':
                    _,data=coverage.decode_page(page)
                    selection['markets'] += [str(m['id']) for m in data['markets']]
        cat = coverage.catalog(self.pages, self.venue, now, compact_output=False,current_selection=selection)
        if len(cat['events']) > 200 or len(cat['markets']) > 512 or len(json.dumps(cat, default=str).encode()) > 2*1024*1024:
            raise BudgetStop('native_source_inventory_cap')
        from .continuous import select_inventory
        ids, eligible = select_inventory(cat, now, 512)
        events_by_id={e['id']:e for e in cat['events']}
        eligible_markets=[m for m in cat['markets'] if m['id'] in ids and not events_by_id[m['event_id']].get('exclusion')]
        eligible_markets.sort(key=lambda m:(m.get('market_type')!='moneyline',events_by_id[m['event_id']]['scheduled_start'],m['id']))
        ids=[m['id'] for m in eligible_markets[:self.config['markets_per_source']]]
        for m in eligible_markets[self.config['markets_per_source']:]:m['subscription_exclusion']='subscription_limit'
        cat['selection'] = dict(ids=ids)
        parsed = {}
        from app.adapters import kalshi, polymarket_us
        events = {e['id']:e for e in cat['events']}
        for market in cat['markets']:
            if market['id'] not in ids: continue
            parent = events[market['event_id']]
            proof = market['provenance'][0]
            page = next(p for p in self.pages if p['body_sha256']==proof['body_sha256'])
            raw, data = coverage.decode_page(page)
            response = coverage.response(self.venue, page, raw)
            try:
                value = (kalshi.parse_market(response, market['_native'], parent['id'], parent['native_aliases'].get('series_ticker','unknown'), typed_scope=True)
                         if self.venue=='kalshi' else polymarket_us.parse_market(response, market['_native'], parent['id']))
                parsed[market['id']] = value
            except (ValueError, KeyError, TypeError):
                market['parse_exclusion'] = 'native_market_parser_rejected'
        # Retire unselected/closed catalogs deliberately; leases are independent.
        self.metrics['generations'] += 1
        self.catalog, self.markets = cat, parsed
        self.metrics['catalog_events'] = len(cat['events'])
        self.metrics['catalog_markets'] = len(cat['markets'])
        self.metrics['selected_markets'] = len(parsed)
        self.metrics['coverage'] = self.findings
        self.metrics['identity_exclusions'] = [dict(kind='event',id=e['id'],reason=e['exclusion']) for e in cat['events'] if e.get('exclusion')][:100]
        self.metrics['identity_exclusions'] += [dict(kind='market',id=m['id'],reason=m.get('subscription_exclusion') or m.get('exclusion') or m.get('parse_exclusion'))
            for m in cat['markets'] if m.get('subscription_exclusion') or m.get('exclusion') or m.get('parse_exclusion')][:100]
        self.service.catalog(self.venue, cat)
        self.pages = []
        signature = sha256(json.dumps([asdict(m) for m in parsed.values()], sort_keys=True, default=str).encode()).hexdigest()
        # Metadata raw receipts change every rediscovery. Reconciliation depends
        # only on exact identity and material native terms/state.
        signature = sha256(json.dumps([(mid, m.raw.ref.event_id, m.state.value,
            catm.get('v1_raw_binding',{}).get('sha256'), catm.get('native_slug'))
            for mid,m in sorted(parsed.items()) for catm in cat['markets'] if catm['id']==mid], default=str).encode()).hexdigest()
        if signature != self.signature or self.stream_task is None or self.stream_task.done():
            await self.stop_stream()
            self.signature = signature
            if parsed and self.credential:
                self.stream_task = asyncio.create_task(self.stream(list(parsed.values())))
                self.metrics['reconciliations'] += 1
            elif not parsed:
                self.service.source_state(self.venue, 'not_offered', 'No admitted common markets in the bounded listing scope.')

    async def stream(self, markets):
        from app.adapters.kalshi_stream import BookReconstructor
        from app.adapters.polymarket_us_stream import MarketStream, subscription
        from .native_semantics import current_purchase_book
        failures = malformed = 0
        highwater = {}
        while not self.closed and not self.failed and self.service.dispatch:
            engine = None
            try:
                self.guard()
                if self.metrics['connections'] >= self.config['connections_per_source']:
                    raise BudgetStop('current_connection_cap')
                self.metrics['connections'] += 1
                self.service.source_state(self.venue, 'resyncing', 'Waiting for a complete native book image.')
                headers = self.credential.headers()
                class NoRedirect(connect):
                    def process_redirect(self, exc): return exc
                self.socket = await NoRedirect(ENDPOINTS[self.venue]['ws'], additional_headers=headers,
                    max_size=256*1024, max_queue=1, compression=None, proxy=None,
                    open_timeout=5, close_timeout=1, ping_interval=20, ping_timeout=20)
                self.reconcile_needed = False
                if self.venue == 'kalshi':
                    engine = BookReconstructor(markets)
                    engine.source_highwater = highwater
                    command = engine.begin(self.metrics['connections'])
                    generation = engine.generation
                    request_id = None
                else:
                    engine = MarketStream(markets, None, duration=1, max_messages=1, max_connections=1)
                    engine.source_time_high_water = highwater
                    request_id = str(uuid4())
                    generation = engine.begin_subscription(request_id)
                    command = subscription(tuple(engine.markets), request_id)
                await asyncio.wait_for(self.socket.send(json.dumps(command)), 3)
                initial_deadline = time.monotonic()+15
                seen = set()
                while True:
                    self.guard()
                    timeout = max(.01, initial_deadline-time.monotonic()) if len(seen)<len(markets) else 30
                    try: body = await asyncio.wait_for(self.socket.recv(), timeout)
                    except TimeoutError:
                        if len(seen)<len(markets): raise ValueError('initial_image_deadline')
                        continue  # quiet books age independently; socket ping owns transport failure
                    received = datetime.now(timezone.utc)
                    if self.reconcile_needed:raise CatalogResync()
                    raw = body.encode() if isinstance(body,str) else body
                    self.credential.check(raw, headers)
                    self.client.budget.charge_bytes(len(raw))
                    self.metrics['bytes'] = self.client.budget.bytes
                    self.metrics['frames'] += 1
                    data = native_payload.parse(raw)
                    if not isinstance(data,dict): raise ValueError('malformed_native_frame')
                    book = (engine.feed(raw, generation, received) if self.venue=='kalshi'
                            else engine.parse(raw.decode('utf-8'), request_id, generation=generation))
                    # Reused engines retain diagnostics for finite qualification;
                    # current mode keeps at most one input frame and no wire log.
                    if self.venue=='kalshi': engine.frames.clear()
                    else:
                        engine.responses.clear(); engine.events.clear(); engine.diagnostics.clear()
                    if book is None: continue
                    if book.sync != BookSync.SYNCHRONIZED:
                        raise ValueError('incomplete_native_image')
                    if book.source_time_progress==SourceTimeProgress.REGRESSED:
                        raise ValueError('regressed_native_source_clock')
                    if self.venue=='kalshi':
                        selected = next(m for m in markets if m.raw.ref.market_id==book.raw.ref.market_id)
                        book = replace(book, state=selected.state)
                    if book.state != MarketState.ACTIVE:
                        self.service.source_state(self.venue, 'resyncing', 'Market lifecycle changed; rediscovery required.')
                        return
                    seen.add(book.raw.ref.market_id)
                    book = current_purchase_book(book)
                    value = json.loads(json.dumps(asdict(book), default=lambda v:v.isoformat() if isinstance(v,datetime) else str(v)))
                    tick = time.perf_counter()
                    self.service.book(self.venue, value)
                    self.metrics['receipt_projection_ms'] = (time.perf_counter()-tick)*1000
                    self.metrics['source_receipt_ms'] = None if book.raw.exchange_at is None else (received-book.raw.exchange_at).total_seconds()*1000
                    self.metrics['books'] += 1
                    failures = 0
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.metrics['resyncs'] += 1
                status = getattr(getattr(exc,'response',None), 'status_code', None)
                if status in (401,403):
                    self.failed = True
                    self.service.issue(self.venue, 'authentication' if status==401 else 'entitlement', 'websocket_'+str(status))
                    self.service.source_state(self.venue, 'unavailable', 'Native feed access was refused.')
                    return
                if status == 429:
                    delay = 60
                    headers = getattr(exc.response, 'headers', {})
                    retry_after = headers.get('Retry-After')
                    if retry_after:
                        from email.utils import parsedate_to_datetime
                        try: delay = max(delay, float(retry_after))
                        except ValueError:
                            try: delay = max(delay, (parsedate_to_datetime(retry_after)-datetime.now(timezone.utc)).total_seconds())
                            except (ValueError, TypeError, OverflowError): delay = 60
                    if delay > 300:
                        self.failed = True
                        self.service.issue(self.venue, 'rate_limit', 'websocket_retry_after_outside_envelope')
                        self.service.source_state(self.venue, 'unavailable', 'Provider retry delay exceeds this runtime allowance.')
                        return
                    self.backoff_until = time.monotonic()+delay
                if isinstance(exc, BudgetStop):
                    self.failed = True
                    self.service.issue(self.venue, 'resource', str(exc))
                    self.service.source_state(self.venue, 'unavailable', 'Native runtime resource allowance reached.')
                    return
                if isinstance(exc, ValueError): malformed += 1
                failures += 1
                if not self.reconcile_needed and not isinstance(exc,CatalogResync):
                    self.service.issue(self.venue, 'malformed_source' if isinstance(exc,ValueError) else 'connection', type(exc).__name__)
                self.service.source_state(self.venue, 'resyncing', 'Native connection recovery requires a fresh image.')
                if malformed >= 3 or failures >= self.config['reconnect_failures']:
                    self.failed = True
                    self.service.source_state(self.venue, 'error', 'Repeated native feed failures; source paused.')
                    return
            finally:
                if self.socket:
                    await self.socket.close()
                    self.socket = None
            delay = max(self.config['backoff_seconds'][min(failures-1,4)], self.backoff_until-time.monotonic())
            self.metrics['retries'] += 1
            await asyncio.sleep(delay)

    async def stop_stream(self):
        task, self.stream_task = self.stream_task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.socket:
            await self.socket.close()
            self.socket = None
        if self.wake_task:
            await asyncio.gather(self.wake_task,return_exceptions=True)
            self.wake_task = None

    async def run(self):
        limits = dict(discovery_requests=self.config['requests_per_source'], session_bytes=self.config['source_bytes'],
            frame_bytes=256*1024, dollars_per_discovery_request='0', dollars_per_connection='0', dollar_cap_per_source='0')
        spec = dict(mode='real', native_sources={self.venue:dict(state='enabled')}, native_transport=native_payload.TRANSPORT_CONTRACT,
                    http=dict(timeout=10), v1_comparison_policy='manual-comparison-2')
        try:
            try: self.credential = load_credentials([self.venue])[self.venue]
            except RuntimeError:
                self.service.issue(self.venue, 'authentication', 'dedicated_credential_missing_or_invalid')
                self.service.source_state(self.venue, 'unavailable', 'Dedicated native feed credentials are unavailable.')
                return
            self.client = REST(ENDPOINTS[self.venue]['rest'], limits, self.receipt, 10,
                               PredictionBudget(limits), venue=self.venue, credential=self.credential)
            native_payload.configure_transport(self.client, spec)
            if self.venue=='polymarket_us': self.client.request_interval = .5
            # Conservative 1/s Kalshi bootstrap; no account data/trading calls.
            errors = 0
            while not self.closed and not self.failed and self.service.dispatch:
                self.guard()
                try:
                    await self.discover()
                    errors = 0
                except asyncio.CancelledError: raise
                except Exception as exc:
                    errors += 1
                    code = str(exc) if isinstance(exc,BudgetStop) else type(exc).__name__
                    self.service.issue(self.venue, 'resource' if isinstance(exc,BudgetStop) else 'discovery', code)
                    await self.stop_stream()
                    self.service.source_state(self.venue, 'unavailable' if self.failed else 'resyncing', 'Native discovery is unavailable; healthy sources continue.')
                    if self.failed or errors >= 3 or isinstance(exc,BudgetStop) and code!='provider_backoff_pending':
                        self.failed = True
                        break
                await asyncio.sleep(max(self.config['rediscovery_seconds'], self.backoff_until-time.monotonic()))
        finally:
            await self.stop_stream()
            if self.client: await self.client.aclose()

    async def close(self):
        self.closed = True
        await self.stop_stream()
        if self.client: await self.client.aclose()
