"""Native source owner: bounded rediscovery and one reconciled socket per source.

Reuse complete HTTP admission, reviewed catalog bindings and native stream
reconstruction. CurrentService retains catalogs and admitted book images.
"""
import asyncio
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
from .native_selectors import query, candidates, PAGE_SIZE
from .venue_access import ENDPOINTS, load_credentials
from .current_sink import utc
from .current_policy import native_scope, native_markets
from .odds_http import BudgetStop

# Re-export existing helper imports while keeping socket ownership in this module.
from .current_native_catalog import (
    CATALOG_BYTES, QUARANTINE_HEADROOM, balanced_markets, overlap_event_keys,
    overlapping_markets, identity_diagnostics, fair_order, fair_metadata_bindings,
    unique_metadata_counts, catalog_selection,
)

class CatalogResync(Exception):
    """Local identity enrichment requires a fresh subscription image."""

DISCOVERY_CAPS = frozenset(('native_discovery_wire_byte_cap', 'native_discovery_decoded_byte_cap'))
HOURLY_CAPS = frozenset(('prediction_session_byte_cap', 'prediction_discovery_request_cap',
                        'current_snapshot_request_cap', 'current_connection_cap'))

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
        self.discovery_cursor = 0
        self.subscription_cursor = 0
        self.catalog_cursor = 0
        self.event_cursors = {}
        self.listing_states = {}
        self.metrics = dict(requests=0, connections=0, frames=0, books=0, bytes=0,
                            generations=0, reconciliations=0, resyncs=0, retries=0,
                            source_receipt_ms=None, receipt_projection_ms=None)
        self.budget_started=time.monotonic()
        self.budget_totals=dict(requests=0,bytes=0,connections=0)
        self.http_totals=dict(wire=0,decoded=0)
        self.http_active=False
        self.http_lock=asyncio.Lock()
        self.supplemental_connections=0
        self.hourly_pause=False
        self.pages = []
        self.catalog = dict(events=[], markets=[])
        self.markets = {}
        self.material_quarantine = {}
        self.backoff_until = 0
        self.failed = False
        self.findings = []
        self.reconcile_needed = False
        self.wake_task = None
        self.source_highwater = {}
        self.pending_books = {}
        self.publication_handle = None
        from .current_confirmation import Confirmations
        self.confirmations = Confirmations(venue)
        from app.comparison.event_links import reviewed_links
        from app.comparison.lifecycle import LifecycleOwner
        self.lifecycle=LifecycleOwner(venue,getattr(service,'runtime_id','controlled-current-worker'),links=reviewed_links(),cap=self.config['markets_per_source'])
        self.lifecycle_initialized=False

    def queue_book(self, book):
        """Keep one fully reconstructed latest image per subscribed market."""
        mid=book['raw']['ref']['market_id']
        if mid in self.material_quarantine:
            self.metrics['quarantined_books_skipped']=self.metrics.get('quarantined_books_skipped',0)+1
            return
        if self.lifecycle_initialized:
            book=self.lifecycle.admit_book(book,generation=self.metrics['connections'])
        if mid not in self.pending_books and len(self.pending_books)>=self.config['markets_per_source']:
            raise BudgetStop('current_native_batch_capacity')
        self.pending_books[mid]=book
        if self.publication_handle is None:
            self.publication_handle=asyncio.get_running_loop().call_later(1,self.flush_books)

    def flush_books(self):
        if self.publication_handle:self.publication_handle.cancel()
        self.publication_handle=None
        books=list(self.pending_books.values());self.pending_books.clear()
        if not books or self.closed or self.failed or not self.service.dispatch:return
        try:
            tick=time.perf_counter()
            self.service.books(self.venue,books)
            self.metrics['receipt_projection_ms']=(time.perf_counter()-tick)*1000
        except Exception:
            self.failed=True
            self.service.source_state(self.venue,'error','Native batch admission failed; fresh complete images are required.')

    async def snapshots(self, engine, markets, pending):
        """At most one batched request per 20 seconds; same native request budget."""
        while True:
            await asyncio.sleep(20)
            self.guard()
            if engine.sid is None or pending:continue
            if self.metrics.get('snapshot_requests',0)>=max(0,(self.config['duration_seconds']-35)//20):return
            # Leave a final 35-second age-out window in every attended runtime.
            if self.service.deadline-time.monotonic()<35:return
            async with self.http_lock:
                await self.send_snapshot(engine,markets,pending)

    async def send_snapshot(self,engine,markets,pending):
        self.guard()
        if engine.sid is None or pending:return
        if self.client.budget.requests>=self.config['requests_per_source']:
            raise BudgetStop('current_snapshot_request_cap')
        self.client.budget.requests+=1
        self.metrics['requests']=self.budget_totals['requests']+self.client.budget.requests
        self.metrics['snapshot_requests']=self.metrics.get('snapshot_requests',0)+1
        request_id=100000+self.metrics['snapshot_requests']
        requested=utc()
        for m in markets:pending[m.raw.ref.market_id]=(request_id,requested)
        command=dict(id=request_id,cmd='update_subscription',params=dict(sid=engine.sid,
            market_tickers=[m.raw.ref.market_id for m in markets],action='get_snapshot'))
        wire=json.dumps(command);self.client.budget.charge_bytes(len(wire.encode()))
        await asyncio.wait_for(self.socket.send(wire),3)

    def request_resync(self):
        self.reconcile_needed = True
        if self.socket and (self.wake_task is None or self.wake_task.done()):
            self.wake_task = asyncio.create_task(self.socket.close())

    def guard(self):
        if (self.closed or not self.service.dispatch or self.failed
                or getattr(self.service,'globally_stopped',False)
                or self.venue in getattr(self.service,'paused_sources',set())):
            raise asyncio.CancelledError()
        # Hourly transport bounds with cumulative accounting, independent of tabs.
        # Never reset a budget underneath an outstanding HTTP byte reservation.
        if self.client and not self.http_active and time.monotonic()-self.budget_started>=3600:
            self.budget_totals['requests']+=self.client.budget.requests
            self.budget_totals['bytes']+=self.client.budget.bytes
            self.budget_totals['connections']=self.metrics['connections']
            self.client.budget.requests=0;self.client.budget.bytes=0
            self.budget_started=time.monotonic()
            self.supplemental_connections=0
            self.hourly_pause=False
        if self.client:
            self.metrics['budget_window']=dict(seconds_remaining=max(0,3600-(time.monotonic()-self.budget_started)),
                requests=self.client.budget.requests,bytes=self.client.budget.bytes,
                connections=self.connection_allowance_used(),
                paused=self.hourly_pause)
        if time.monotonic() >= self.service.deadline:
            raise BudgetStop('attended_runtime_deadline')

    def begin_discovery(self):
        """Six MiB belongs to one scheduled pass, never to the worker lifetime."""
        self.guard()
        if self.http_active:raise RuntimeError('discovery_http_in_progress')
        for name,key in (('http_wire_bytes','wire'),('http_decoded_bytes','decoded')):
            self.http_totals[key]+=getattr(self.client,name,0)
            setattr(self.client,name,0)

    async def wait_hourly_budget(self):
        self.hourly_pause=True
        self.service.source_state(self.venue,'budget_delayed','Native hourly transport allowance reached; waiting for its next window.')
        await self.stop_stream()
        await asyncio.sleep(max(0,3600-(time.monotonic()-self.budget_started)))
        self.guard()

    def receipt(self, row):
        # Complete responses are transient discovery inputs, then discarded.
        self.metrics['requests'] = self.budget_totals['requests']+self.client.budget.requests
        self.metrics['bytes'] = self.budget_totals['bytes']+self.client.budget.bytes
        self.metrics['http_wire_bytes']=self.http_totals['wire']+getattr(self.client,'http_wire_bytes',0)
        self.metrics['http_decoded_bytes']=self.http_totals['decoded']+getattr(self.client,'http_decoded_bytes',0)
        self.metrics['last_http'] = dict(path=row['path'],params=row.get('params',{}),status=row['status'],complete=row['complete'],
            reason=row.get('delivery_reason'),body_sha256=row['body_sha256'])
        self.service.observation(self.venue, 'http', dict(status=row['status'], complete=row['complete'],
            path=row['path'], bytes=row.get('resource_usage',{}).get('wire_bytes'),
            body_sha256=row['body_sha256'], reason=row.get('delivery_reason')))
        if row['status'] in (401, 403):
            self.failed = True
            self.service.issue(self.venue, 'authentication' if row['status']==401 else 'entitlement', 'http_'+str(row['status']))
            self.service.source_state(self.venue, 'unavailable', 'Native catalog access was refused.')
        self.apply_http_backoff(row)
        if not row['complete'] or not row.get('usable_metadata'):
            query_caps=native_payload.query_cap_reasons(dict(native_transport=native_payload.TRANSPORT_CONTRACT,v1_comparison_policy='manual-comparison-2'))
            if row.get('delivery_reason') not in query_caps | DISCOVERY_CAPS | HOURLY_CAPS | {'http_status', None, 'native_http_timeout', 'native_http_transport_error'} and row['status']==200:
                self.failed = True
            return
        page = dict(row, source=self.venue, native_binding_revision='live-native-binding-2',
                    v1_comparison_policy='manual-comparison-2')
        scope = getattr(self, '_scope', None)
        if scope: page.update(native_scope_binding=scope, native_scope_policy=SCOPE_POLICY)
        if len(self.pages) >= self.config['discovery_pages'] or sum(len(p['body_b64']) for p in self.pages)+len(page['body_b64']) > 8*1024*1024:
            raise BudgetStop('current_discovery_retained_cap')
        self.pages.append(page)

    def connection_allowance_used(self):
        return self.metrics['connections']-self.budget_totals['connections']+self.supplemental_connections

    def apply_http_backoff(self,row):
        """One source backoff owner, also used by explicit finite public reads."""
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
    async def get(self, path, params, field=None, scope=None):
        async with self.http_lock:
            return await self._get(path,params,field,scope)

    async def _get(self, path, params, field=None, scope=None):
        self.guard()
        if self.backoff_until > time.monotonic():
            raise BudgetStop('provider_backoff_pending')
        self._scope = scope
        self.http_active=True
        try:
            # No invisible per-operation retry: the source runtime owns backoff.
            response = await MockREST.get(self.client, self.client.endpoint+path, params)
        except Exception as exc:
            if hasattr(self.service,'coverage') and getattr(self,'_coverage_sport',None):
                self.service.coverage.observe(self._coverage_sport,self.venue,family=getattr(self,'_coverage_family',None),checked_at=utc(),
                    status='failed_source',reason='source_failed',query=dict(path=path,params=params),detail_code=str(exc))
            raise
        finally:
            self._scope = None
            self.http_active=False
        if response.status_code != 200:
            if hasattr(self.service,'coverage') and getattr(self,'_coverage_sport',None):
                self.service.coverage.observe(self._coverage_sport,self.venue,family=getattr(self,'_coverage_family',None),checked_at=utc(),
                    status='failed_source',reason='source_failed',query=dict(path=path,params=params),detail_code='http_'+str(response.status_code))
            raise ValueError('http_'+str(response.status_code))
        try:
            data = response.json()
            rows = data.get(field) if field else data
            if field:
                if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                    raise ValueError('malformed_catalog')
                id_field = 'event_ticker' if self.venue=='kalshi' and field=='events' else 'ticker' if self.venue=='kalshi' else 'id'
                ids = [str(r.get(id_field) or '') for r in rows]
                if not all(ids) or len(set(ids)) != len(ids): raise ValueError('duplicate_catalog_identity')
        except (ValueError,TypeError,AttributeError) as exc:
            if hasattr(self.service,'coverage') and getattr(self,'_coverage_sport',None):
                self.service.coverage.observe(self._coverage_sport,self.venue,family=getattr(self,'_coverage_family',None),checked_at=utc(),
                    status='rejected_payload',reason='payload_rejected',query=dict(path=path,params=params),detail_code=str(exc))
            raise
        if hasattr(self,'_coverage_checked') and getattr(self,'_coverage_sport',None):
            self._coverage_checked.add(self._coverage_sport)
        return rows

    def quarantine_changed_material(self,native_events,returned_markets):
        """Observed changed owned terms revoke comparison even when unfit.

        Retain only bounded hashes/field names, never the rejected replacement.
        The existing semantic contract masks only reviewed mutable observations.
        """
        from .native_review_contract import project,CURRENT_POLICY,ELIGIBILITY
        def material(raw,event=False):
            if event:raw={k:v for k,v in raw.items() if k!='markets'}
            try:terms=project(self.venue,raw,event=event,policy=CURRENT_POLICY)
            except (ValueError,TypeError):terms=dict(unparseable_semantic_material_sha256=digest(raw))
            return dict(terms=terms,
                eligibility={k:raw[k] for k in ELIGIBILITY[self.venue] if k in raw})
        def digest(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
        def fact_set(values):return sorted({digest(value) for value in values})
        events={e['id']:e for e in self.catalog['events']}
        markets={m['id']:m for m in self.catalog['markets']}
        # These are the same own linked identity fields retained by coverage.
        facts={}
        for page in self.pages:
            _,data=coverage.decode_page(page)
            for milestone in data.get('milestones',[]):
                for eid in milestone.get('related_event_tickers',[]):
                    if eid not in events:continue
                    fact=dict(id=milestone.get('id'),source_id=milestone.get('source_id'),
                        source_provider=milestone.get('source_provider'),start_date=milestone.get('start_date'),
                        **{k:v for k,v in milestone.get('details',{}).items() if k in
                           ('season','season_type','season_year','main_game_event_ticker','home_team_id','away_team_id',
                            'game_number','original_start','schedule_status','status')})
                    facts.setdefault(eid,[]).append(fact)
        changed=False
        for candidate in returned_markets:
            mid=candidate['id'];old=markets.get(mid)
            if mid not in self.lifecycle.leases or not old:continue
            parent=events.get(old['event_id'],{})
            prior=material(old.get('_native',{}))
            current=material(candidate['_native'])
            fields=['market.'+str(k) for k in set(prior['terms'])|set(current['terms'])
                if prior['terms'].get(k)!=current['terms'].get(k)]
            if prior['eligibility']!=current['eligibility']:fields.append('market.eligibility')
            eid=candidate['event_id']
            old_event=material(parent.get('_native',{}),True)
            new_event=material(native_events[eid],True) if eid in native_events else old_event
            if old['event_id']!=eid:fields.append('market.event_id')
            if old_event!=new_event:fields.append('event.material')
            if eid in facts and fact_set(facts[eid])!=fact_set(parent.get('observed_identity_facts',[])):
                fields.append('event.observed_identity_facts')
            if not fields:continue
            witness=dict(supported=False,reason='native_material_changed_capacity',
                missing_fields=['feasible_current_native_material'],
                prior_sha256=digest(dict(market=prior,event=old_event,facts=fact_set(parent.get('observed_identity_facts',[])))),
                observed_sha256=digest(dict(market=current,event=new_event,facts=fact_set(facts.get(eid,parent.get('observed_identity_facts',[]))))),
                changed_fields=[str(k).encode('ascii','backslashreplace')[:64].decode('ascii') for k in sorted(fields)[:6]],
                changed_fields_omitted=max(0,len(fields)-6))
            while len(json.dumps(witness).encode())>QUARANTINE_HEADROOM//20-64 and witness['changed_fields']:
                witness['changed_fields'].pop();witness['changed_fields_omitted']+=1
            self.material_quarantine[mid]=witness
            old['comparison_admission']=deepcopy(witness)
            self.lifecycle.leases[mid]['image_current']=False
            self.pending_books.pop(mid,None)
            changed=True
        self.metrics['material_quarantined_markets']=len(self.material_quarantine)
        if changed:
            # The outer admission marker survives ordinary catalog reannotation.
            # Membership/material is unchanged, retaining original books/clocks.
            self.service.catalog(self.venue,self.catalog)

    def retain_catalog_for_capacity(self,sports,families,native_events,returned_markets):
        """A local proposal limit cannot revoke coherent existing ownership."""
        self.metrics['catalog_projection'].update(
            state='retained_previous' if self.catalog['events'] or self.markets else 'deferred',
            reason='native_source_inventory_cap',selected_events=0,selected_markets=0)
        self.metrics['coverage']=self.findings
        self.quarantine_changed_material(native_events,returned_markets)
        for finding in self.findings:
            if finding.get('queried'):
                finding.update(state='budget_limited',reason='native_source_inventory_cap')
        if hasattr(self.service,'coverage'):
            for sport in sports:
                for family in families:
                    if any(f.get('queried') and f.get('sport')==sport and f.get('family') in (None,family)
                           for f in self.findings):
                        self.service.coverage.observe(sport,self.venue,family=family,checked_at=utc(),
                            status='not_checked',reason='query_capacity',completeness='partial',
                            offered=dict(games=None,markets=None,quotes=None))
        self.pages=[]

    async def discover(self):
        self.metrics['discovery_passes']=self.metrics.get('discovery_passes',0)+1
        self.pages = []
        self.findings = []
        self._coverage_checked=set()
        coverage_started=utc()
        now = datetime.now(timezone.utc)
        selected = []
        native_events={}
        sports=native_scope(self.config);families=native_markets(self.config)
        inventory=getattr(getattr(getattr(self.service,'sink',None),'reducer',None),'inventory',{})
        overlap={json.dumps([e.get('competition'),e.get('canonical_key')],sort_keys=True)
                 for venue,cat in inventory.items() if venue!=self.venue
                 for e in cat.get('events',[]) if not e.get('exclusion') and e.get('canonical_key')}
        pools=[]
        # First listing opportunities precede metadata. The same source-wide
        # page/request/byte limits apply to the whole pass, not to each league.
        scopes=[(sport,family) for sport in sports for family in families] if self.venue=='kalshi' else [(sport,None) for sport in sports]
        scopes=fair_order(scopes,self.discovery_cursor)
        self.discovery_cursor+=1
        listing_cap=min(len(scopes),max(1,self.config['discovery_pages']//2))
        for sport,family in scopes[listing_cap:]:
            for omitted_family in ([family] if family else families):
                self.findings.append(dict(sport=sport,family=omitted_family,state='budget_limited',
                    reason='shared_discovery_page_cap',configured=True,queried=False,scope='not queried in this bounded pass'))
                if hasattr(self.service,'coverage'):
                    self.service.coverage.observe(sport,self.venue,family=omitted_family,checked_at=utc(),
                        status='not_checked',reason='query_capacity',completeness='partial')
        for sport,family in scopes[:listing_cap]:
            self._coverage_sport=sport;self._coverage_family=family
            scope=None
            if self.venue=='kalshi':
                selectors=selectors_for(sport+'/full_game/'+family)
                if not selectors:
                    self.findings.append(dict(sport=sport,family=family,state='unsupported',configured=True,queried=False,
                        reason='selector_unestablished',scope='source/type selector unavailable'))
                    continue
                selector=selectors[0];scope=selector['binding']
                path,params=selector['path'],dict(selector['params'],limit=PAGE_SIZE)
            else:
                path,params=query(self.venue,sport,now,families=families)
                params=dict(params,limit=PAGE_SIZE,offset=0)
            cell=(sport,family,tuple(families))
            state=self.listing_states.get(cell)
            if state and state.get('blocked'):
                self.findings.append(dict(sport=sport,family=family,state='unsupported',configured=True,queried=False,
                    reason=state['blocked'],scope='listing continuation unavailable; other cells continue'))
                continue
            if state is None:
                state=dict(path=path,base={k:v for k,v in params.items() if k not in ('cursor','offset','limit')},
                    position='' if self.venue=='kalshi' else 0,receipt=None,seen=[])
                self.listing_states[cell]=state
            # The cursor/offset belongs to this exact frozen query, including
            # its time window. Only a completed traversal starts a new query.
            position=state['position']
            params=dict(state['base'],limit=PAGE_SIZE,**({'cursor':position} if self.venue=='kalshi' and position else
                {} if self.venue=='kalshi' else {'offset':position}))
            try:
                rows=await self.get(path,params,'events',scope)
            except BudgetStop as exc:
                query_caps=native_payload.query_cap_reasons(dict(native_transport=native_payload.TRANSPORT_CONTRACT,v1_comparison_policy='manual-comparison-2'))
                if str(exc) not in query_caps:raise
                self.service.issue(self.venue,'resource',str(exc))
                self.findings.append(dict(sport=sport,family=family,state='budget_limited',queried=True,
                    reason=str(exc),scope='one bounded query; no support inference'))
                continue
            page=self.pages[-1]
            for native in rows:
                native_events[str(native.get('event_ticker' if self.venue=='kalshi' else 'id'))]=native
            if position not in ('',0):
                page['current_listing_window']=dict(policy='current-recurring-page-1',position=position,
                    base_query_sha256=sha256(json.dumps(state['base'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                    previous_receipt_sha256=state['receipt'])
            _,listing=coverage.decode_page(page)
            exhausted=False;continuation=None
            if self.venue=='kalshi':
                cursor=listing.get('cursor')
                if not isinstance(cursor,str) or len(cursor)>4096:
                    state['blocked']='native_cursor_missing_or_invalid'
                elif not cursor:exhausted=True
                else:
                    fingerprint=sha256(cursor.encode()).hexdigest()
                    if fingerprint in state['seen'] or cursor==position:state['blocked']='native_cursor_repeated'
                    else:
                        state['seen']=(state['seen']+[fingerprint])[-64:]
                        continuation=cursor
            elif len(rows)<PAGE_SIZE:exhausted=True
            elif len(rows)==PAGE_SIZE:continuation=position+PAGE_SIZE
            else:state['blocked']='native_offset_progress_unestablished'
            if exhausted:self.listing_states.pop(cell,None)
            elif continuation is not None:state.update(position=continuation,receipt=page['body_sha256'])
            if self.venue=='kalshi':
                page=self.pages[-1];raw,_=coverage.decode_page(page)
                native_records=[coverage.event_record(self.venue,page,raw,e,i,now) for i,e in enumerate(rows)]
                found=[dict(id=e['id'],competition=sport,canonical_key=e.get('canonical_key'),scheduled_start=e['scheduled_start'],scope=scope)
                       for e in native_records if not e.get('exclusion') and e.get('scheduled_start')]
                found.sort(key=lambda e:(e['scheduled_start'],e['id']));excluded=[]
            else:
                found,excluded=candidates(self.pages[-1:],self.venue,sport,now,families=families)
            for event in found:
                event['cross_venue_overlap']=json.dumps([sport,event.get('canonical_key')],sort_keys=True) in overlap
            found.sort(key=lambda event:(not event['cross_venue_overlap'],event.get('scheduled_start') or '',event['id']))
            finding=dict(sport=sport,family=family,rows=len(rows),discovered=len(found),selected=[],
                state='discovered' if found else 'empty',configured=True,queried=True,exclusions=excluded[:5],
                page_position=position,next_position=continuation,traversal_exhausted=exhausted,
                continuation_limitation=state.get('blocked'),
                scope='one recurring bounded page window; other pages unobserved in this pass')
            self.findings.append(finding)
            key=(sport,family)
            pools.append((finding,fair_order(found,self.event_cursors.get(key,0))))
        metadata_cap=min(self.config['events_per_source'],self.config['discovery_pages']-len(self.pages))
        # An exact listed market can be fetched when no native gameId exists;
        # reserve all its (at most three) metadata requests before selecting it.
        spent=0
        while any(pool for _,pool in pools) and len(selected)<self.config['events_per_source']:
            progressed=False
            for finding,pool in pools:
                if not pool:continue
                event=pool.pop(0)
                if event['id'] in {e['id'] for e in selected}:continue
                cost=1 if self.venue=='kalshi' or event.get('game_id') else min(3,len(event.get('market_bindings',[])))
                if self.venue=='polymarket_us' and not event.get('game_id'):
                    event['selected_metadata_bindings']=fair_metadata_bindings(event,native_events.get(event['id'],{}),
                        families,self.event_cursors.get((finding['sport'],finding.get('family')),0))
                    cost=len(event['selected_metadata_bindings'])
                if cost==0:continue
                if spent+cost>metadata_cap:
                    finding['state']='budget_limited';finding['reason']='shared_metadata_page_cap';continue
                selected.append(event);finding['selected'].append(event['id']);spent+=cost;progressed=True
                key=(finding['sport'],finding.get('family'));self.event_cursors[key]=self.event_cursors.get(key,0)+1
                if len(selected)>=self.config['events_per_source']:break
            if not progressed:break
        for finding,pool in pools:
            if pool:
                finding['budget_omitted_events']=len(pool)
                finding['reason']='shared_event_or_metadata_cap'
        returned_markets=[]
        from app.adapters.polymarket_us import full_game_family
        def remember(rows,event):
            for native in rows:
                mid=native.get('ticker' if self.venue=='kalshi' else 'id')
                if not mid:continue
                family=(event.get('scope') or {}).get('family') if self.venue=='kalshi' else full_game_family(native.get('sportsMarketType'))
                returned_markets.append(dict(id=str(mid),event_id=event['id'],market_type=family or 'unknown',_native=native))
        for event in selected:
            self._coverage_sport=event.get('competition',event.get('sport'))
            self._coverage_family=(event.get('scope') or {}).get('family')
            remember(native_events.get(event['id'],{}).get('markets') or [],event)
            if self.venue=='kalshi':
                rows=await self.get('/trade-api/v2/markets',dict(event_ticker=event['id'],limit=50),'markets',event['scope'])
                remember(rows,event)
            elif event.get('game_id'):
                rows=await self.get('/v1/markets',dict(gameId=str(event['game_id']),active='true',closed='false',limit=50,offset=0),'markets')
                remember(rows,event)
            else:
                for binding in event.get('selected_metadata_bindings',[]):
                    data=await self.get('/v1/market/id/'+binding['id'],{})
                    remember([data.get('market',data)] if isinstance(data,dict) else data,event)
        selection,projection=catalog_selection(selected,native_events,returned_markets,families,self.catalog_cursor)
        self.catalog_cursor+=1
        self.metrics['metadata_budget_omitted_markets']=projection['omitted_markets']
        self.metrics['catalog_projection']=dict(projection,state='bounded',reason=None,byte_cap=CATALOG_BYTES,
            event_cap=200,market_cap=512,projection_event_cap=24,projection_market_cap=72,
            material_quarantine_reserved_bytes=QUARANTINE_HEADROOM)
        if ((projection['supported_family_candidates'] and not selection['markets'])
                or (selected and not selection['events'])):
            self.retain_catalog_for_capacity(sports,families,native_events,returned_markets)
            return
        cat = coverage.catalog(self.pages, self.venue, now, compact_output=False,current_selection=selection)
        from .current_occurrence import annotate as occurrence
        occurrence(cat, self.venue)
        # A conservative raw reservation normally fits in one projection. If a
        # derived field expands further, remove whole tail entries locally from
        # these same receipts; do not fetch, truncate terms or abandon old books.
        actual_bytes=len(json.dumps(cat,default=str).encode())
        while len(cat['events'])>200 or len(cat['markets'])>512 or actual_bytes>CATALOG_BYTES-QUARANTINE_HEADROOM:
            if not selection['markets']:
                self.retain_catalog_for_capacity(sports,families,native_events,returned_markets)
                return
            selection['markets'].pop()
            retained={m['event_id'] for m in returned_markets if m['id'] in selection['markets']}
            selection['events']=[eid for eid in selection['events'] if eid in retained]
            if not selection['markets']:
                self.retain_catalog_for_capacity(sports,families,native_events,returned_markets)
                return
            cat=coverage.catalog(self.pages,self.venue,now,compact_output=False,current_selection=selection)
            occurrence(cat,self.venue)
            actual_bytes=len(json.dumps(cat,default=str).encode())
        self.metrics['catalog_projection'].update(actual_bytes=actual_bytes,selected_events=len(cat['events']),
            selected_markets=len(cat['markets']),omitted_events=projection['candidate_events']-len(cat['events']),
            omitted_markets=projection['candidate_markets']-len(cat['markets']))
        self.metrics['metadata_budget_omitted_markets']=self.metrics['catalog_projection']['omitted_markets']
        from .continuous import select_inventory
        ids, eligible = select_inventory(cat, now, 512)
        events_by_id={e['id']:e for e in cat['events']}
        eligible_markets=[m for m in cat['markets'] if m['id'] in ids and not events_by_id[m['event_id']].get('exclusion')]
        eligible_markets.sort(key=lambda m:(m.get('market_type')!='moneyline',events_by_id[m['event_id']]['scheduled_start'],m['id']))
        overlap_priority=overlapping_markets(cat,[other for venue,other in inventory.items() if venue!=self.venue])
        chosen=balanced_markets(eligible_markets,self.config['markets_per_source'],families,events=events_by_id,offset=self.subscription_cursor,priority=overlap_priority)
        self.metrics['known_peer_priority_markets']=len(overlap_priority)
        self.subscription_cursor+=1
        ids=[m['id'] for m in chosen]
        for m in eligible_markets:
            if m['id'] not in ids:m['subscription_exclusion']='subscription_limit'
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
        # Include selection and parser diagnostics in the exact reservation.
        # The retained wrapper is at most 20 bounded witnesses inside this room.
        actual_bytes=len(json.dumps(cat,default=str).encode())
        if actual_bytes>CATALOG_BYTES-QUARANTINE_HEADROOM:
            self.retain_catalog_for_capacity(sports,families,native_events,returned_markets)
            return
        self.metrics['catalog_projection']['actual_bytes']=actual_bytes
        # Retire unselected/closed catalogs deliberately; leases are independent.
        self.metrics['generations'] += 1
        self.catalog, self.markets = cat, parsed
        from app.adapters.polymarket_us import next_market_data
        active_clock_keys=set(parsed) if self.venue=='kalshi' else {next_market_data(m)['slug'] for m in parsed.values()}
        for key in set(self.source_highwater)-active_clock_keys:self.source_highwater.pop(key)
        self.metrics['catalog_events'] = len(cat['events'])
        self.metrics['catalog_markets'] = len(cat['markets'])
        self.metrics['selected_markets'] = len(parsed)
        self.metrics['coverage'] = self.findings
        from .native_identity_trace import identity_trace
        self.metrics['native_identity_trace']=identity_trace(cat,self.venue,pages=self.pages,selected=ids,
            selected_events=[e['id'] for e in selected],pass_number=self.metrics['discovery_passes'])
        trace_bytes=len(json.dumps(self.metrics['native_identity_trace'],separators=(',',':')).encode())
        self.metrics['identity_exclusions'],self.metrics['identity_exclusions_omitted']=identity_diagnostics(
            cat,ids,byte_cap=24*1024-trace_bytes-256)
        self.service.catalog(self.venue, cat)
        from app.comparison.lifecycle import worker_selections
        delta=self.lifecycle.reconcile(worker_selections(self.venue,parsed,cat),now)
        self.material_quarantine.clear()
        self.metrics['material_quarantined_markets']=0
        self.lifecycle_initialized=True
        self.metrics['subscription_changes']=delta
        self.metrics['owned_subscriptions']=len(self.lifecycle.leases)
        for mid in set(self.pending_books)-set(self.lifecycle.leases):self.pending_books.pop(mid,None)
        if hasattr(self.service,'coverage'):
            for sport in sports:
                if sport not in self._coverage_checked:continue
                latest=self.service.coverage.observations.get((sport,self.venue),{}).get('latest')
                if latest and latest['checked_at']>=coverage_started and latest['status'] in ('failed_source','rejected_payload'):continue
                events=[e for e in cat['events'] if e.get('competition')==sport]
                event_ids={e['id'] for e in events}
                markets=[m for m in cat['markets'] if m['event_id'] in event_ids]
                for family in families:
                    related=[f for f in self.findings if f.get('sport')==sport and f.get('family') in (None,family)]
                    queried=[f for f in related if f.get('queried')]
                    if not queried:continue
                    family_markets=[m for m in markets if m.get('market_type')==family]
                    empty=all(f.get('rows')==0 for f in queried)
                    limited=any(f.get('state')=='budget_limited' or f.get('budget_omitted_events',0)>0
                        or f.get('discovered',0)>len(f.get('selected',[])) for f in queried)
                    limited=limited or any(m['id'] not in selection['markets'] and m['market_type']==family
                        and next((e.get('competition') for e in selected if e['id']==m['event_id']),None)==sport
                        for m in returned_markets)
                    status='offerings_returned' if family_markets else 'no_offerings_returned' if empty else 'not_checked'
                    reason=None if family_markets else 'query_empty' if empty else 'query_capacity' if limited else 'mapping_unresolved'
                    offered=(dict(games=len({m['event_id'] for m in family_markets}),markets=len(family_markets),quotes=None)
                        if family_markets or empty else dict(games=None,markets=None,quotes=None))
                    selected_event_ids={e['id'] for e in selected if e.get('competition',e.get('sport'))==sport}
                    measured=[m for m in returned_markets if m['market_type']==family and m['event_id'] in selected_event_ids]
                    unique=unique_metadata_counts(measured,self.venue) if measured or empty else dict(games=None,markets=None,quotes=None)
                    self.service.coverage.observe(sport,self.venue,family=family,checked_at=utc(),
                        status=status,offered=offered,reason=reason,completeness='partial',
                        unique_offered=unique,
                        offered_scope='bounded_listing_and_selected_metadata')
        self.pages = []
        # Metadata raw receipts change every rediscovery. Reconciliation depends
        # only on exact identity and material native terms/state.
        signature=self.lifecycle.signature()
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
        highwater = self.source_highwater
        while not self.closed and not self.failed and self.service.dispatch:
            engine = None
            snapshot_task = None
            try:
                self.guard()
                if self.connection_allowance_used() >= self.config['connections_per_source']:
                    raise BudgetStop('current_connection_cap')
                self.metrics['connections'] += 1
                self.lifecycle.begin_connection(self.metrics['connections'])
                self.confirmations.begin(self.metrics['connections'])
                if self.publication_handle:self.publication_handle.cancel()
                self.publication_handle=None;self.pending_books.clear()
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
                requested=utc()
                pending={m.raw.ref.market_id:(command['id'],requested) for m in markets} if self.venue=='kalshi' else {}
                await asyncio.wait_for(self.socket.send(json.dumps(command)), 3)
                if self.venue=='kalshi':snapshot_task=asyncio.create_task(self.snapshots(engine,markets,pending))
                initial_deadline = time.monotonic()+15
                seen = set()
                while True:
                    self.guard()
                    if snapshot_task and snapshot_task.done():snapshot_task.result()
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
                    self.metrics['bytes'] = self.budget_totals['bytes']+self.client.budget.bytes
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
                    if book.raw.exchange_at is not None and book.raw.exchange_at>datetime.now(timezone.utc):
                        raise ValueError('future_native_source_clock')
                    if self.venue=='kalshi':
                        selected = next(m for m in markets if m.raw.ref.market_id==book.raw.ref.market_id)
                        book = replace(book, state=selected.state)
                    if book.state != MarketState.ACTIVE:
                        self.service.source_state(self.venue, 'resyncing', 'Market lifecycle changed; rediscovery required.')
                        return
                    seen.add(book.raw.ref.market_id)
                    book = current_purchase_book(book)
                    value = json.loads(json.dumps(asdict(book), default=lambda v:v.isoformat() if isinstance(v,datetime) else str(v)))
                    from .current_confirmation import validate
                    request=pending.pop(book.raw.ref.market_id,None) if data.get('type')=='orderbook_snapshot' else None
                    confirmation=self.confirmations.observe(value,data,raw,generation=self.metrics['connections'],
                        request_id=(request[0] if request else engine.request_id) if self.venue=='kalshi' else request_id,
                        requested_at=request[1] if request else None,sid=engine.sid if self.venue=='kalshi' else None,
                        sequence=engine.seq if self.venue=='kalshi' else None)
                    if confirmation:
                        validate(confirmation,value['raw']['ref'],value)
                        value['book_confirmation']=confirmation
                    tick = time.perf_counter()
                    self.queue_book(value)
                    self.metrics['receipt_queue_ms'] = (time.perf_counter()-tick)*1000
                    self.metrics['source_receipt_ms'] = None if book.raw.exchange_at is None else (received-book.raw.exchange_at).total_seconds()*1000
                    self.metrics['books'] += 1
                    failures = 0
                    # Buffered WebSocket messages can complete receive without
                    # yielding. Let reads, Stop and independent sources run.
                    await asyncio.sleep(0)
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
                    if str(exc) in HOURLY_CAPS:
                        self.hourly_pause=True
                        self.service.issue(self.venue,'resource',str(exc))
                        self.service.source_state(self.venue,'budget_delayed','Native hourly transport allowance reached; waiting for its next window.')
                        return
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
                if self.publication_handle:self.publication_handle.cancel()
                self.publication_handle=None;self.pending_books.clear()
                if snapshot_task:
                    snapshot_task.cancel();await asyncio.gather(snapshot_task,return_exceptions=True)
                if self.socket:
                    await self.socket.close()
                    self.socket = None
            delay = max(self.config['backoff_seconds'][min(failures-1,4)], self.backoff_until-time.monotonic())
            self.metrics['retries'] += 1
            self.backoff_until=time.monotonic()+delay
            await asyncio.sleep(delay)

    async def stop_stream(self):
        if self.publication_handle:self.publication_handle.cancel()
        self.publication_handle=None;self.pending_books.clear()
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
                if self.hourly_pause:
                    await self.wait_hourly_budget()
                    continue
                try:
                    async with self.http_lock:
                        self.begin_discovery()
                    await self.discover()
                    errors = 0
                except asyncio.CancelledError: raise
                except Exception as exc:
                    errors += 1
                    code = str(exc) if isinstance(exc,BudgetStop) else type(exc).__name__
                    self.service.issue(self.venue, 'resource' if isinstance(exc,BudgetStop) else 'discovery', code)
                    if isinstance(exc,BudgetStop) and code in DISCOVERY_CAPS and not self.failed:
                        # Partial metadata cannot replace the last complete catalog.
                        # The existing stream may continue within the hourly budget.
                        self.pages=[]
                        errors=0
                        self.metrics['discovery_cap_stops']=self.metrics.get('discovery_cap_stops',0)+1
                        await asyncio.sleep(max(self.config['rediscovery_seconds'],self.backoff_until-time.monotonic()))
                        continue
                    if isinstance(exc,BudgetStop) and code in HOURLY_CAPS and not self.failed:
                        errors=0
                        await self.wait_hourly_budget()
                        continue
                    await self.stop_stream()
                    self.service.source_state(self.venue, 'unavailable' if self.failed else 'resyncing', 'Native discovery is unavailable; healthy sources continue.')
                    retryable=code in ('provider_backoff_pending','native_http_timeout','native_http_transport_error')
                    if self.failed or errors >= 3 or isinstance(exc,BudgetStop) and not retryable:
                        self.failed = True
                        break
                    await asyncio.sleep(max(self.config['backoff_seconds'][errors-1],self.backoff_until-time.monotonic()))
                    continue
                await asyncio.sleep(max(self.config['rediscovery_seconds'], self.backoff_until-time.monotonic()))
        finally:
            self.lifecycle.revoke()
            await self.stop_stream()
            if self.client: await self.client.aclose()
            await self.finish_lifecycle()

    async def finish_lifecycle(self):
        # The single source socket has already closed all physical subscriptions.
        # Release each local lease exactly once without changing outer ownership.
        async def closed(mid,token):return None
        await self.lifecycle.stop(closed)
        self.metrics['owned_subscriptions']=0

    async def close(self):
        self.closed = True
        self.lifecycle.revoke()
        await self.stop_stream()
        if self.client: await self.client.aclose()
        await self.finish_lifecycle()
