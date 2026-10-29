"""Native source owner: bounded rediscovery and one reconciled socket per source.

Reuse complete HTTP admission, reviewed catalog bindings and native stream
reconstruction. CurrentService retains catalogs and admitted book images.
"""
import asyncio
from .current_ingress import call
from .bulk_checkpoint import owned_thread
from copy import deepcopy
from dataclasses import replace
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
RETRYABLE_DISCOVERY = frozenset(('provider_backoff_pending', 'native_http_timeout',
    'native_http_transport_error', 'native_http_framing_error', 'native_http_length_mismatch',
    'http_429', 'http_500', 'http_502', 'http_503', 'http_504'))

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
        from .current_book_images import CurrentBookImages
        self.pending_books = CurrentBookImages() if getattr(service,'database_mode',False) else {}
        self.pending_recalculations=set()
        self.pending_since = {}
        self.raw_since = {}
        self.derived_served = {}
        self.raw_served = {}
        self.raw_pending=CurrentBookImages() if getattr(service,'database_mode',False) else {}
        self.raw_context={}
        self.census_generation=None
        self.invalid_received={}
        self.raw_task=None
        self.publication_handle = None
        self.publication_task = None
        self.pending_health = False
        self.raw_inflight = {}
        self.derived_inflight = {}
        self.receiver = None
        self.subscription_groups = {}
        self.subscription_transition = None
        self.subscription_blocked = set()
        self.retired_subscription_ids = []
        self.reconstruction = None
        from .native_synchronization import Synchronization
        self.synchronization = Synchronization()
        from .current_confirmation import Confirmations
        self.confirmations = Confirmations(venue)
        from app.comparison.event_links import reviewed_links
        from app.comparison.lifecycle import LifecycleOwner
        self.lifecycle=LifecycleOwner(venue,getattr(service,'runtime_id','controlled-current-worker'),links=reviewed_links(),cap=None)
        self.lifecycle_initialized=False

    def queue_book(self, book, *, _content_sha256=None,_encoded_bytes=None):
        """Keep one fully reconstructed latest image per subscribed market."""
        mid=book['raw']['ref']['market_id']
        if mid in self.subscription_blocked:return
        if mid in self.material_quarantine:
            self.metrics['quarantined_books_skipped']=self.metrics.get('quarantined_books_skipped',0)+1
            return
        if self.lifecycle_initialized:
            book=self.lifecycle.admit_book(book,generation=self.metrics['connections'],owned=bool(getattr(self.service,'database_mode',False)),_content_sha256=_content_sha256,_encoded_bytes=_encoded_bytes)
        self.pending_since.setdefault(mid,time.monotonic())
        self.pending_recalculations.discard(mid)
        self.pending_books[mid]=book
        if getattr(self.service,'database_mode',False):
            self.raw_since.setdefault(mid,time.monotonic())
            self.raw_pending.retain_from(self.pending_books,[mid])
            self.raw_context[mid]=(getattr(self.service,'runtime_id',None),self.metrics['connections'],self.census_generation)
            if self.raw_task is None or self.raw_task.done():
                self.raw_task=asyncio.create_task(self.persist_raw(),name='predict-native-raw-'+self.venue)
                self.raw_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        if self.publication_handle is None:
            self.publication_handle=asyncio.get_running_loop().call_later(.01,self.flush_books)

    async def persist_raw(self):
        from .bulk_checkpoint import save_images
        while self.raw_pending:
            selected=list(self.raw_pending)[:200]
            images=[self.raw_pending.pop(mid) for mid in selected]
            contexts={mid:self.raw_context.pop(mid,(None,None,None)) for mid in selected}
            oldest=min(self.raw_since.pop(mid,time.monotonic()) for mid in selected)
            started=time.perf_counter()
            self.raw_inflight={mid:oldest for mid in selected}
            self.metrics['raw_inflight_images']=len(images)
            try:
                await owned_thread(save_images,self.venue,images,'pending',**(dict(contexts=contexts) if getattr(self.service,'runtime_id',None) else {}))
            except BaseException as exc:
                self.raw_inflight.clear()
                self.metrics['raw_inflight_images']=0
                self.metrics['raw_persistence_error']=type(exc).__name__
                for book in images:
                    mid=book['raw']['ref']['market_id']
                    self.raw_pending.setdefault(mid,book)
                    self.raw_context.setdefault(mid,contexts[mid])
                    self.raw_since.setdefault(mid,oldest)
                raise
            self.raw_inflight.clear()
            self.metrics['raw_inflight_images']=0
            for generation in {context[1] for context in contexts.values()}:
                self.synchronization.persist(generation,[mid for mid,context in contexts.items() if context[1]==generation])
            self.synchronization.delivered('raw',[b['raw']['received_at'] for b in images])
            self.metrics['raw_persistence_error']=None
            self.metrics['raw_write_ms']=(time.perf_counter()-started)*1000
            self.metrics['raw_oldest_served_seconds']=time.monotonic()-oldest
            self.raw_served.update({b['raw']['ref']['market_id']:time.monotonic() for b in images})
            self.metrics['raw_images_persisted']=self.metrics.get('raw_images_persisted',0)+len(images)
            self.metrics['raw_backlog']=len(self.raw_pending)
            await asyncio.sleep(0)

    async def drain_raw(self):
        if self.raw_task:
            await asyncio.gather(self.raw_task,return_exceptions=True)
            self.raw_task=None
        if self.raw_pending:await self.persist_raw()

    def queue_derived(self,book):
        """Recalculate a retained image without re-receiving or re-persisting it."""
        if self.closed or self.failed or not self.service.dispatch:return
        mid=book['raw']['ref']['market_id']
        if mid not in self.pending_books:self.pending_recalculations.add(mid)
        self.pending_books.setdefault(mid,book)
        self.pending_since.setdefault(mid,time.monotonic())
        if self.publication_handle is None:
            self.publication_handle=asyncio.get_running_loop().call_later(.01,self.flush_books)

    def flush_books(self):
        if self.publication_handle:self.publication_handle.cancel()
        self.publication_handle=None
        if self.publication_task and not self.publication_task.done():return
        # Overdue work owns a FIFO turn after the two-second processing target.
        # Otherwise preserve tail priority across reconnect initial-image order.
        # Pure last-service ordering could indefinitely put new quiet instruments
        # ahead of an already waiting hot one. Coalescing preserves arrival age.
        # Chunking limits each SQL transaction, never subscription membership.
        books=[];size=0;claimed={};recalculating=set()
        self.pending_recalculations.intersection_update(self.pending_books)
        # Large initial/reimage queues favor throughput. Once caught up, short
        # SQL turns prevent one source's large batch delaying the other feed.
        batch_limit=max(512 if len(self.pending_books)>512 else 128,self.config['markets_per_source'])
        now=time.monotonic()
        def priority(mid):
            arrived=self.pending_since.get(mid,0)
            return (0,arrived,0) if now-arrived>=2 else (1,self.derived_served.get(mid,-1),arrived)
        ordered=sorted(self.pending_books,key=priority)
        for mid in ordered:
            book=self.pending_books[mid]
            cost=len(json.dumps(book,default=str).encode())
            if books and (len(books)>=(batch_limit if getattr(self.service,'database_mode',False) else self.config['markets_per_source']) or size+cost>self.config['ingress_bytes']//2):break
            books.append(book);size+=cost
            del self.pending_books[mid]
            if mid in self.pending_recalculations:recalculating.add(mid)
            self.pending_recalculations.discard(mid)
            claimed[mid]=self.pending_since.pop(mid,time.monotonic())
            waited=time.monotonic()-claimed[mid]
            self.metrics['derived_oldest_served_seconds']=max(self.metrics.get('derived_oldest_served_seconds',0),waited)
        self.metrics['pending_books']=len(self.pending_books)
        if not books or self.closed or self.failed or not self.service.dispatch:return
        if not getattr(self.service,'database_mode',False):
            self.service.books(self.venue,books)
            return
        self.derived_inflight=claimed
        self.metrics['derived_inflight_images']=len(books)
        async def publish():
            nonlocal books
            try:
                tick=time.perf_counter()
                from .bulk_checkpoint import save_images
                await owned_thread(save_images,self.venue,books,'pending',ensure_only=True)
                books=[b for b in books if b['raw']['received_at']>self.invalid_received.get(b['raw']['ref']['market_id'],'')]
                if not books:return
                try:
                    await call(self.service,self.service.books,self.venue,books)
                except Exception:
                    await owned_thread(save_images,self.venue,books,'rejected',known_persisted=True)
                    raise
                await owned_thread(save_images,self.venue,books,'admitted',known_persisted=True)
                self.metrics['receipt_projection_ms']=(time.perf_counter()-tick)*1000
                self.derived_served.update({b['raw']['ref']['market_id']:time.monotonic() for b in books})
                self.synchronization.delivered('derived',[b['raw']['received_at'] for b in books
                    if b['raw']['ref']['market_id'] not in recalculating])
                completed=time.monotonic()
                self.synchronization.elapsed('metadata_recalculation',[
                    completed-claimed[b['raw']['ref']['market_id']] for b in books
                    if b['raw']['ref']['market_id'] in recalculating])
                self.metrics['derived_images_published']=self.metrics.get('derived_images_published',0)+len(books)
            except asyncio.CancelledError:raise
            except Exception as exc:
                # A malformed instrument cannot starve unrelated subscriptions.
                # Raw images remain durable; isolate admission within this chunk.
                self.metrics['last_admission_failure']=type(exc).__name__
                for book in books:
                    try:
                        await call(self.service,self.service.books,self.venue,[book])
                    except asyncio.CancelledError:raise
                    except Exception:
                        await owned_thread(save_images,self.venue,[book],'rejected')
                        self.metrics['rejected_book_updates']=self.metrics.get('rejected_book_updates',0)+1
                    else:
                        await owned_thread(save_images,self.venue,[book],'admitted')
            finally:
                self.derived_inflight.clear()
                self.metrics['derived_inflight_images']=0
                if self.pending_books and not self.closed and self.service.dispatch:
                    self.publication_handle=asyncio.get_running_loop().call_later(.01,self.flush_books)
        self.publication_task=asyncio.create_task(publish(),name='predict-native-publication-'+self.venue)
        self.publication_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    def request_resync(self):
        self.synchronization.revoke('catalog_changed')
        self.reconcile_needed = True
        if self.socket and (self.wake_task is None or self.wake_task.done()):
            self.wake_task = asyncio.create_task(self.socket.close())

    async def quiesce_catalog(self, parsed, catalog, selected=None):
        """Retire old socket/publication callbacks before replacing membership.

        SQL ingress serializes commands, but a timer can queue an old image behind
        the new catalog command. Cancellation revokes that image's owned ingress;
        the subsequent catalog waits for the same serialization lock. Never send
        an old subscription batch into the replacement inventory.
        """
        from app.comparison.lifecycle import worker_selections
        if selected is None:selected=await owned_thread(worker_selections,self.venue,parsed,catalog)
        old={mid:(lease['selection']['event']['id'],lease['selection']['material_revision'])
             for mid,lease in self.lifecycle.leases.items()}
        new={value['market_id']:(value['event']['id'],value['material_revision']) for value in selected}
        if old!=new and self.lifecycle_initialized:
            self.metrics['catalog_transition']=dict(previous_generation=self.metrics['connections'],
                old_markets=len(old),new_markets=len(new),retired_markets=sorted(set(old)-set(new)),
                changed_markets=sorted(mid for mid in old.keys()&new.keys() if old[mid]!=new[mid]),
                pending_images=len(self.pending_books),reason='subscription_membership_or_material_changed')
            if (self.venue=='kalshi' and new and all(old[k]==new[k] for k in old.keys()&new.keys())
                    and self.reconstruction and self.socket and self.stream_task and not self.stream_task.done()
                    and getattr(self.active_engine,'sid',None) is not None):
                self.subscription_transition=dict(kind='kalshi_membership',invalidated=set(old)^set(new),
                    added=set(new)-set(old),removed=set(old)-set(new))
                self.subscription_blocked=set(old)-set(new)
                for mid in self.subscription_blocked:
                    self.pending_books.pop(mid,None);self.pending_since.pop(mid,None);self.pending_recalculations.discard(mid)
                    self.synchronization.invalidate(mid)
                if self.publication_task:await asyncio.gather(self.publication_task,return_exceptions=True)
                self.metrics['catalog_transition']['mode']='update_markets_existing_sid'
            elif (self.venue=='polymarket_us' and parsed and self.subscription_groups and self.reconstruction
                    and self.socket and self.stream_task and not self.stream_task.done()):
                from .native_subscriptions import plan
                changed={mid for mid in old.keys()&new.keys() if old[mid]!=new[mid]}
                self.subscription_transition=plan(self.subscription_groups,self.markets,parsed,changed)
                self.subscription_blocked=set(self.subscription_transition['invalidated'])
                for mid in self.subscription_blocked:
                    self.pending_books.pop(mid,None);self.pending_since.pop(mid,None);self.pending_recalculations.discard(mid)
                    self.synchronization.invalidate(mid)
                # Finish any already-owned old-catalog transaction before the
                # catalog atomically withdraws these groups. Unaffected input
                # continues arriving and remains in its ordinary bounded queue.
                if self.publication_task:await asyncio.gather(self.publication_task,return_exceptions=True)
                self.metrics['catalog_transition']['mode']='affected_subscription_groups'
            else:await self.stop_stream()

    async def finish_subscription_transition(self):
        transition=self.subscription_transition
        if not transition:return
        self.guard()
        if not self.reconstruction or not self.socket:raise CatalogResync()
        if transition.get('kind')=='kalshi_membership':
            engine=self.active_engine
            commands=[];removal_request=None
            for action,members in (('delete_markets',transition['removed']),('add_markets',transition['added'])):
                if not members:continue
                rid=self.metrics.get('subscription_update_id',1000000)+1
                self.metrics['subscription_update_id']=rid
                if action=='delete_markets':removal_request=rid
                else:self.stream_snapshot_requests.update({mid:(rid,utc()) for mid in members})
                commands.append(dict(id=rid,cmd='update_subscription',params=dict(
                    sids=[engine.sid],market_tickers=sorted(members),action=action)))
            engine.reconfigure(list(self.markets.values()),removal_request)
            await self.reconstruction.reconfigure(list(self.markets.values()),None,
                dict(request_id=removal_request) if removal_request is not None else [])
            self.guard()
            self.stream_markets[:]=list(self.markets.values())
            self.stream_market_index.clear();self.stream_market_index.update(self.markets)
            self.stream_seen.intersection_update(self.markets)
            self.stream_isolated.intersection_update(self.markets)
            self.synchronization.members=set(self.markets)
            for values in (self.synchronization.images,self.synchronization.persisted,self.synchronization.invalid):
                values.intersection_update(self.markets)
            self.initial_deadline=time.monotonic()+15
            for command in commands:await asyncio.wait_for(self.socket.send(json.dumps(command)),3)
            self.metrics['catalog_transition']['reimaged_markets']=len(transition['added'])
            self.metrics.update(initial_images=len(self.stream_seen),missing_initial_images=len(self.markets)-len(self.stream_seen))
            self.signature=self.lifecycle.signature();self.subscription_transition=None
            return
        from .native_subscriptions import requests,commands
        from app.adapters.polymarket_us import next_market_data
        groups=transition['groups'];mapping=requests(groups,self.markets)
        self.retired_subscription_ids=(self.retired_subscription_ids+sorted(transition['retired']))[-512:]
        engine=self.active_engine
        engine.markets={next_market_data(m)['slug']:m for m in self.markets.values()}
        engine.market_requests=mapping;engine.retired_requests=set(self.retired_subscription_ids)
        await self.reconstruction.reconfigure(list(self.markets.values()),mapping,self.retired_subscription_ids)
        self.guard()
        self.stream_markets[:]=list(self.markets.values())
        self.stream_market_index.clear();self.stream_market_index.update(self.markets)
        self.stream_seen.difference_update(transition['invalidated'])
        self.stream_isolated.difference_update(transition['invalidated'])
        self.synchronization.members=set(self.markets)
        for values in (self.synchronization.images,self.synchronization.persisted,self.synchronization.invalid):
            values.intersection_update(self.markets)
        self.initial_deadline=time.monotonic()+15
        self.subscription_groups=groups
        self.subscription_blocked.clear()
        for rid in sorted(transition['retired']):
            await asyncio.wait_for(self.socket.send(json.dumps({'unsubscribe':{'requestId':rid}})),3)
        for command in commands(transition['added'],self.markets):
            await asyncio.wait_for(self.socket.send(json.dumps(command)),3)
        self.metrics.update(subscription_groups=len(groups),initial_images=len(self.stream_seen),
            missing_initial_images=len(self.markets)-len(self.stream_seen),
            subscription_group_replacements=self.metrics.get('subscription_group_replacements',0)+len(transition['added']))
        self.metrics['catalog_transition'].update(reimaged_markets=len(transition['invalidated'] & self.markets.keys()),
                                                retained_groups=len(groups)-len(transition['added']))
        self.signature=self.lifecycle.signature()
        self.subscription_transition=None

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
        await call(self.service, self.service.source_state, self.venue, 'budget_delayed', 'Native hourly transport allowance reached; waiting for its next window.')
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
            if getattr(self.service,'database_mode',False):self.pending_health = True
            else:self.service.source_state(self.venue,'unavailable','Native catalog access was refused.')
        self.apply_http_backoff(row)
        if not row['complete'] or not row.get('usable_metadata'):
            query_caps=native_payload.query_cap_reasons(dict(native_transport=native_payload.TRANSPORT_CONTRACT,v1_comparison_policy='manual-comparison-2'))
            if row.get('delivery_reason') not in query_caps | DISCOVERY_CAPS | HOURLY_CAPS | {'http_status', None} | RETRYABLE_DISCOVERY and row['status']==200:
                self.failed = True
            return
        page = dict(row, source=self.venue, native_binding_revision='live-native-binding-2',
                    v1_comparison_policy='manual-comparison-2')
        scope = getattr(self, '_scope', None)
        if scope: page.update(native_scope_binding=scope, native_scope_policy=SCOPE_POLICY)
        page['transport_policy']=dict(getattr(self.client,'transport_policy',None) or native_payload.TRANSPORT_CONTRACT)
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
            if self.pending_health:
                self.pending_health=False
                await call(self.service,self.service.source_state,self.venue,'unavailable','Native catalog access was refused.')
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
            self.pending_books.pop(mid,None);self.pending_recalculations.discard(mid)
            changed=True
        self.metrics['material_quarantined_markets']=len(self.material_quarantine)
        if changed:
            # The outer admission marker survives ordinary catalog reannotation.
            # Membership/material is unchanged, retaining original books/clocks.
            if getattr(self.service,'database_mode',False):self.catalog_dirty=True
            else:self.service.catalog(self.venue,self.catalog)

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
        sports=native_scope(self.config);families=native_markets(self.config)
        from .bulk_native import enumerate_native
        selected,native_events,returned_markets=await enumerate_native(self)
        del native_events  # Selected raw rows remain in returned_markets; no unused parent graph.
        selection=dict(events=[e['id'] for e in selected],markets=list(dict.fromkeys(m['id'] for m in returned_markets)))
        projection=dict(candidate_events=len(selected),candidate_markets=len(selection['markets']),omitted_markets=0)
        self.metrics['catalog_projection']=dict(projection,state='complete_traversal',reason=None)
        cat = self.bulk_catalog
        from .native_recovery import retain_absent
        retained_absent=retain_absent(self.catalog,cat)
        # Recheck channels after merging retained moving-listing absences.
        from collections import defaultdict
        channels=defaultdict(set)
        for market in cat['markets']:
            if market.get('native_slug'):channels[market['native_slug']].add(market['id'])
        for market in cat['markets']:
            if len(channels.get(market.get('native_slug'),()))>1:
                market['subscription_evidence_exclusion']='ambiguous_native_subscription_identity'
        self.metrics["suspected_absent_retained"]=len(retained_absent)
        from .current_occurrence import annotate as occurrence
        occurrence(cat, self.venue)
        from .current_native_catalog import catalog_encoded_bytes
        actual_bytes=await owned_thread(catalog_encoded_bytes,cat)
        self.metrics['catalog_projection'].update(actual_bytes=actual_bytes,selected_events=len(cat['events']),
            selected_markets=len(cat['markets']),omitted_events=projection['candidate_events']-len(cat['events']),
            omitted_markets=projection['candidate_markets']-len(cat['markets']))
        self.metrics['metadata_budget_omitted_markets']=self.metrics['catalog_projection']['omitted_markets']
        # Acquisition is independent of matching, payout and financial eligibility.
        # Unknown semantics remain inspectable raw values with no derived authority.
        events_by_id={e['id']:e for e in cat['events']}
        eligible_markets=[]
        for market in cat['markets']:
            parent=events_by_id[market['event_id']]
            native=market.get('_native',{})
            start=parent.get('scheduled_start')
            closed=native.get('closed') is True or native.get('status') in ('closed','settled','finalized')
            if market.get('subscription_evidence_exclusion') in ('ambiguous_subscription_slug','ambiguous_native_subscription_identity'):
                market['subscription_exclusion']=market['subscription_evidence_exclusion']
            elif closed or start and coverage.stamp(start)<=datetime.now(timezone.utc):
                market['subscription_exclusion']='closed_or_started'
            else:
                eligible_markets.append(market)
        # Do not retain another source’s superseded catalog across HTTP discovery.
        inventory=getattr(getattr(getattr(self.service,'sink',None),'reducer',None),'inventory',{})
        overlap_priority=overlapping_markets(cat,[other for venue,other in inventory.items() if venue!=self.venue])
        del inventory
        chosen=balanced_markets(eligible_markets,len(eligible_markets),families,events=events_by_id,offset=self.subscription_cursor,priority=overlap_priority)
        self.metrics['known_peer_priority_markets']=len(overlap_priority)
        self.subscription_cursor+=1
        ids=[m['id'] for m in chosen]
        selected_ids=set(ids)
        for m in eligible_markets:
            if m['id'] not in selected_ids:m['subscription_exclusion']='subscription_limit'
        cat['selection'] = dict(ids=ids)
        parsed = {}
        from app.adapters import kalshi, polymarket_us
        events = {e['id']:e for e in cat['events']}
        page_index={p['body_sha256']:p for p in self.pages}
        last_proof=None;response=None
        for market in cat['markets']:
            # Large catalogs must not hold the event loop through thousands of
            # synchronous adapter calls while sockets and paid HTTP await I/O.
            self.guard()
            await asyncio.sleep(0)
            if market['id'] not in selected_ids: continue
            if market['id'] in retained_absent:
                if market['id'] in self.markets:parsed[market['id']]=self.markets[market['id']]
                continue
            parent = events[market['event_id']]
            proof = market['provenance'][0]
            try:
                if getattr(self,'checkpoint',None):
                    from .current_native_catalog import parse_retained_market
                    value=parse_retained_market(self.venue,market,parent)
                else:
                    if proof['body_sha256']!=last_proof:
                        page=page_index[proof['body_sha256']]
                        raw, data = coverage.decode_page(page)
                        response = coverage.response(self.venue, page, raw)
                        last_proof=proof['body_sha256']
                    value = (kalshi.parse_market(response, market['_native'], parent['id'], parent['native_aliases'].get('series_ticker','unknown'), typed_scope=True)
                             if self.venue=='kalshi' else polymarket_us.parse_market(response, market['_native'], parent['id']))
                parsed[market['id']] = value
            except (ValueError, KeyError, TypeError):
                market['parse_exclusion'] = 'native_market_parser_rejected'
        # Include selection and parser diagnostics in the exact reservation.
        from .current_native_catalog import catalog_encoded_bytes
        actual_bytes=await owned_thread(catalog_encoded_bytes,cat)
        self.metrics['catalog_projection']['actual_bytes']=actual_bytes
        if getattr(self,'checkpoint',None):
            from .bulk_checkpoint import save_census
            self.census_generation=await owned_thread(save_census,self.venue,selected,returned_markets,parsed)
        # Quiesce while the old producer/catalog still describe the same native
        # generation, before replacing membership or clearing source highwaters.
        from app.comparison.lifecycle import worker_selections
        selections=await owned_thread(worker_selections,self.venue,parsed,cat)
        await self.quiesce_catalog(parsed,cat,selections)
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
        self.metrics['native_identity_trace']=identity_trace(cat,self.venue,pages=[],selected=ids,
            selected_events=[e['id'] for e in selected],pass_number=self.metrics['discovery_passes'])
        trace_bytes=len(json.dumps(self.metrics['native_identity_trace'],separators=(',',':')).encode())
        self.metrics['identity_exclusions'],self.metrics['identity_exclusions_omitted']=identity_diagnostics(
            cat,ids,byte_cap=24*1024-trace_bytes-256)
        await call(self.service, self.service.catalog, self.venue, cat)
        from app.comparison.lifecycle import worker_selections
        delta=self.lifecycle.reconcile(selections,now)
        self.material_quarantine.clear()
        self.metrics['material_quarantined_markets']=0
        self.lifecycle_initialized=True
        await self.finish_subscription_transition()
        from collections import Counter
        self.metrics['subscription_changes']=dict(delta,actions=delta['actions'][:20],
            action_counts=dict(Counter(a['action'] for a in delta['actions'])),
            omitted_actions=max(0,len(delta['actions'])-20),complete_roster='current_acquisition_market')
        self.metrics['owned_subscriptions']=len(self.lifecycle.leases)
        for mid in set(self.pending_books)-set(self.lifecycle.leases):
            self.pending_books.pop(mid,None);self.pending_recalculations.discard(mid)
        selected_inventory_ids=set(selection['markets'])
        selected_sports={e['id']:e.get('competition') for e in selected}
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
                    limited=limited or any(m['id'] not in selected_inventory_ids and m['market_type']==family
                        and selected_sports.get(m['event_id'])==sport
                        for m in returned_markets)
                    status='offerings_returned' if family_markets else 'no_offerings_returned' if empty else 'not_checked'
                    reason=None if family_markets else 'query_empty' if empty else 'query_capacity' if limited else 'mapping_unresolved'
                    offered=(dict(games=len({m['event_id'] for m in family_markets}),markets=len(family_markets),quotes=None)
                        if family_markets or empty else dict(games=None,markets=None,quotes=None))
                    selected_event_ids={e['id'] for e in selected if e.get('competition',e.get('sport'))==sport}
                    measured=[m for m in returned_markets if m['market_type']==family and m['event_id'] in selected_event_ids]
                    unique=unique_metadata_counts(measured,self.venue) if measured or empty else dict(games=None,markets=None,quotes=None)
                    from app.comparison.offered_scope import native_inventory
                    inventory=native_inventory(self.findings,measured,set(parsed),started_at=coverage_started,
                        completed_at=utc(),venue=self.venue,sport=sport,family=family)
                    self.service.coverage.observe(sport,self.venue,family=family,checked_at=utc(),
                        inventory=inventory,status=status,offered=offered,reason=reason,completeness='partial',
                        unique_offered=unique,
                        offered_scope='complete_listing_and_metadata_traversal_price_boundary_unverified')
        if getattr(self,'checkpoint',None):
            from .native_recovery import save
            cat['acquisition_census_generation']=self.census_generation
            await owned_thread(save,self.venue,self.checkpoint.scope,cat,parsed)
            await owned_thread(self.checkpoint.finish)
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
                await call(self.service, self.service.source_state, self.venue, 'not_offered', 'No parseable pregame markets in the completed listing traversal.')

    async def stream(self, markets):
        from app.adapters.kalshi_stream import BookReconstructor
        from app.adapters.polymarket_us_stream import MarketStream, subscription
        from .native_semantics import current_purchase_book
        failures = malformed = 0
        highwater = self.source_highwater
        market_index={m.raw.ref.market_id:m for m in markets}
        self.stream_market_index=market_index
        while not self.closed and not self.failed and self.service.dispatch:
            engine = None
            reconstruction = None
            receiver = None
            stage = 'connect'
            checked_raw = None
            seen = set()
            isolated = set()
            self.stream_seen=seen;self.stream_isolated=isolated;self.stream_markets=markets
            try:
                self.guard()
                if self.connection_allowance_used() >= self.config['connections_per_source']:
                    raise BudgetStop('current_connection_cap')
                self.metrics['connections'] += 1
                self.lifecycle.begin_connection(self.metrics['connections'])
                self.confirmations.begin(self.metrics['connections'])
                self.synchronization.begin(self.metrics['connections'], market_index)
                if self.publication_handle:self.publication_handle.cancel()
                self.publication_handle=None;self.pending_books.clear();self.pending_since.clear();self.pending_recalculations.clear()
                await call(self.service, self.service.source_state, self.venue, 'resyncing', 'Waiting for a complete native book image.')
                credential = self.credential
                headers = {}
                metrics = self.metrics
                from .native_transport_probe import ProbedConnection
                class SignedConnection(ProbedConnection):
                    def __init__(connection,*args,**kwargs):
                        super().__init__(*args,probe_metrics=metrics,probe_generation=metrics["connections"],**kwargs)
                    async def ping(connection, data=None):
                        started=time.monotonic()
                        metrics['last_ping_sent_at']=utc()
                        previous=metrics.get('last_ping_monotonic')
                        metrics['ping_interval_observed_seconds']=None if previous is None else started-previous
                        metrics['last_ping_monotonic']=started
                        waiter=await super().ping(data)
                        def completed(future):
                            if future.cancelled() or future.exception() is not None:return
                            metrics['last_pong_received_at']=utc()
                            metrics['ping_completion_seconds']=time.monotonic()-started
                        waiter.add_done_callback(completed)
                        return waiter
                    async def handshake(connection, additional_headers=None, user_agent_header=None):
                        nonlocal headers
                        # Sign after DNS/TLS, immediately before the opening request.
                        signed_at = utc()
                        headers = credential.headers()
                        metrics['last_handshake'] = dict(signed_at=signed_at,
                            path=__import__('urllib.parse', fromlist=['urlsplit']).urlsplit(ENDPOINTS[self.venue]['ws']).path,
                            result='pending')
                        try:
                            await super().handshake(headers, user_agent_header)
                            metrics['last_handshake']['result'] = 'connected'
                        finally:
                            metrics['last_handshake']['completed_at'] = utc()
                class NoRedirect(connect):
                    def process_redirect(self, exc): return exc
                self.socket = await NoRedirect(ENDPOINTS[self.venue]['ws'], create_connection=SignedConnection,
                    max_size=256*1024, max_queue=64, compression=None, proxy=None,
                    open_timeout=5, close_timeout=1, ping_interval=20, ping_timeout=60)
                self.metrics.update(stream_connected=True,initial_images=0,missing_initial_images=len(markets),isolated_missing_images=0)
                self.metrics['invalid_current_market_ids']=[]
                self.reconcile_needed = False
                if self.venue == 'kalshi':
                    engine = BookReconstructor(markets, maximum_markets=None)
                    engine.source_highwater = highwater
                    command = engine.begin(self.metrics['connections'])
                    generation = engine.generation
                    request_id = None
                else:
                    engine = MarketStream(markets, None, duration=1, max_messages=1, max_connections=1, maximum_markets=None)
                    engine.source_time_high_water = highwater
                    engine.isolate_market_errors=bool(getattr(self.service,'database_mode',False))
                    request_id = str(uuid4())
                    generation = engine.begin_subscription(request_id)
                    command = subscription(tuple(engine.markets), request_id, maximum_markets=None)
                    if getattr(self.service,'database_mode',False):
                        from .native_subscriptions import plan,requests,commands
                        self.subscription_groups=plan({}, {}, market_index,set())['groups']
                        engine.market_requests=requests(self.subscription_groups,market_index)
                        self.metrics['subscription_groups']=len(self.subscription_groups)
                self.active_engine=engine
                requested=utc()
                pending={m.raw.ref.market_id:(command['id'],requested) for m in markets} if self.venue=='kalshi' else {}
                self.stream_snapshot_requests=pending
                stage = 'subscribe'
                commands_to_send=commands(self.subscription_groups,market_index) if self.venue=='polymarket_us' and self.subscription_groups else [command]
                for command_to_send in commands_to_send:
                    await asyncio.wait_for(self.socket.send(json.dumps(command_to_send)), 3)
                # Initial snapshots and ordered deltas maintain the subscribed books.
                # Recovery reconnects the affected subscription; no periodic image renewal.
                from .native_receive import NativeReceive
                receiver=NativeReceive(self.socket,self.metrics,on_failure=lambda:self.synchronization.revoke('transport_lost'))
                self.receiver=receiver
                if getattr(self.service,'database_mode',False):
                    from .native_reconstruction import Reconstruction
                    reconstruction=Reconstruction(self.venue,markets,self.metrics['connections'],request_id,highwater,self.metrics,
                        market_requests=engine.market_requests if self.venue=='polymarket_us' else None)
                    self.reconstruction=reconstruction
                self.initial_deadline = time.monotonic()+15
                while True:
                    stage = 'receive'
                    self.metrics['processing_inflight_frames']=0
                    self.metrics['processing_received_at']=None
                    checked_raw = None
                    self.guard()
                    receiver.require_active()
                    timeout = max(.01, self.initial_deadline-time.monotonic()) if len(seen|isolated)<len(markets) else 30
                    try:
                        prepared_frame=None
                        if reconstruction is None:
                            async with asyncio.timeout(timeout):body,received=await receiver.recv()
                        else:
                            prepared_frame=await reconstruction.recv(receiver,timeout=timeout)
                            body,received=prepared_frame['body'],prepared_frame['received']
                    except TimeoutError:
                        if len(seen|isolated)<len(markets): raise ValueError('initial_image_deadline')
                        continue  # quiet books age independently; socket ping owns transport failure
                    receiver.require_active()
                    self.metrics['processing_inflight_frames']=1
                    self.metrics['processing_received_at']=received.isoformat()
                    self.metrics['last_reconstructed_receipt_at']=received.isoformat()
                    self.metrics['heartbeat_roundtrip_seconds']=getattr(self.socket,'latency',None)
                    processing_started=time.perf_counter()
                    if self.reconcile_needed:raise CatalogResync()
                    raw = body.encode() if isinstance(body,str) else body
                    self.credential.check(raw, headers)
                    checked_raw = raw
                    self.client.budget.charge_bytes(len(raw))
                    self.metrics['bytes'] = self.budget_totals['bytes']+self.client.budget.bytes
                    self.metrics['frames'] += 1
                    stage = 'decode'
                    decode_started=time.perf_counter()
                    if prepared_frame is not None:
                        if prepared_frame.get('error') and prepared_frame['stage']=='decode':raise ValueError('malformed_native_frame')
                        data=prepared_frame.get('data',{})
                        if self.venue=='kalshi':engine.sid,engine.seq=prepared_frame['sid'],prepared_frame['seq']
                    else:data = native_payload.parse(raw)
                    self.metrics['frame_decode_ms']=(time.perf_counter()-decode_started)*1000
                    if not isinstance(data,dict): raise ValueError('malformed_native_frame')
                    if self.venue=='polymarket_us' and engine.market_requests is not None:
                        slug=data.get('marketData',{}).get('marketSlug')
                        if data.get('requestId') in engine.retired_requests:
                            continue
                        if slug and data.get('requestId')!=engine.market_requests.get(slug):
                            raise ValueError('native_reconstruction_failure')
                    stage = 'reconstruct'
                    reconstruct_started=time.perf_counter()
                    from app.adapters.polymarket_us_stream import MalformedMarketFrame
                    try:
                        if prepared_frame is not None:
                            if prepared_frame.get('malformed_slug'):raise MalformedMarketFrame(prepared_frame['malformed_slug'])
                            if prepared_frame.get('error'):raise ValueError('native_reconstruction_failure')
                            book=prepared_frame['book']
                        else:
                            book = (engine.feed(raw, generation, received) if self.venue=='kalshi'
                                    else engine.parse(raw.decode('utf-8'), request_id, generation=generation,received_at=received))
                    except MalformedMarketFrame as exc:
                        from .bulk_checkpoint import save_failure
                        market=engine.markets[exc.slug];mid=market.raw.ref.market_id
                        isolated.add(mid);seen.discard(mid);self.invalid_received[mid]=received.isoformat()
                        self.synchronization.invalidate(mid)
                        self.metrics['invalid_current_market_ids']=sorted(isolated)
                        self.pending_books.pop(mid,None);self.pending_since.pop(mid,None);self.pending_recalculations.discard(mid)
                        if mid in self.lifecycle.leases:self.lifecycle.leases[mid]['image_current']=False
                        await owned_thread(save_failure,self.venue,raw,received.isoformat(),self.metrics['connections'],'reconstruct')
                        await call(self.service,self.service.invalidate_market,self.venue,market.raw.ref.event_id,mid)
                        engine.responses.clear();engine.events.clear();engine.diagnostics.clear()
                        if prepared_frame is not None and prepared_frame.get('isolated_reason'):
                            self.metrics['isolated_regressed_images']=self.metrics.get('isolated_regressed_images',0)+1
                        self.metrics['isolated_malformed_images']=self.metrics.get('isolated_malformed_images',0)+1
                        self.metrics['isolated_missing_images']=len(isolated-seen)
                        continue
                    # Reused engines retain diagnostics for finite qualification;
                    # current mode keeps at most one input frame and no wire log.
                    if self.venue=='kalshi': engine.frames.clear()
                    else:
                        engine.responses.clear(); engine.events.clear(); engine.diagnostics.clear()
                    self.metrics['reconstruction_ms']=prepared_frame['processing_ms'] if prepared_frame is not None else (time.perf_counter()-reconstruct_started)*1000
                    self.synchronization.acknowledge(engine.sid if self.venue=='kalshi' else request_id,
                        engine.seq if self.venue=='kalshi' else None)
                    kind=data.get('type','market_data' if book is not None else 'control')
                    if kind in ('orderbook_snapshot','orderbook_delta','market_data'):
                        self.metrics[kind+'_frames']=self.metrics.get(kind+'_frames',0)+1
                        self.metrics[kind+'_bytes']=self.metrics.get(kind+'_bytes',0)+len(raw)
                    if book is None:
                        if self.metrics['frames']%64==0:await asyncio.sleep(0)
                        continue
                    if book.sync != BookSync.SYNCHRONIZED:
                        raise ValueError('incomplete_native_image')
                    if book.source_time_progress==SourceTimeProgress.REGRESSED:
                        raise ValueError('regressed_native_source_clock')
                    if book.raw.exchange_at is not None and book.raw.exchange_at>datetime.now(timezone.utc):
                        raise ValueError('future_native_source_clock')
                    if self.venue=='kalshi' and prepared_frame is None:
                        selected = market_index[book.raw.ref.market_id]
                        book = replace(book, state=selected.state)
                    if prepared_frame is not None and reconstruction.obsolete_book(prepared_frame):
                        self.metrics['obsolete_catalog_images_discarded']=self.metrics.get('obsolete_catalog_images_discarded',0)+1
                        continue
                    if book.state != MarketState.ACTIVE:
                        await call(self.service, self.service.source_state, self.venue, 'resyncing', 'Market lifecycle changed; rediscovery required.')
                        return
                    if book.raw.ref.market_id in self.subscription_blocked:continue
                    if book.raw.ref.market_id not in seen:self.initial_deadline=time.monotonic()+15
                    self.synchronization.image(book.raw.ref.market_id)
                    self.synchronization.delivered('reconstruction',[received.isoformat()])
                    seen.add(book.raw.ref.market_id)
                    isolated.discard(book.raw.ref.market_id)
                    self.metrics['invalid_current_market_ids']=sorted(isolated)
                    self.metrics['initial_images']=len(seen)
                    self.metrics['missing_initial_images']=len(markets)-len(seen)
                    if prepared_frame is None:
                        book = current_purchase_book(book)
                        from .native_book_value import book_value
                        value=book_value(book)
                    else:value=prepared_frame['value']
                    from .current_confirmation import validate
                    stage = 'confirm'
                    request=pending.pop(book.raw.ref.market_id,None) if data.get('type')=='orderbook_snapshot' else None
                    from .current_confirmation import ConfirmationUnavailable
                    try:
                        confirmation=self.confirmations.observe(value,data,raw,generation=self.metrics['connections'],
                            request_id=(request[0] if request else engine.request_id) if self.venue=='kalshi' else data.get('requestId',request_id),
                            requested_at=request[1] if request else None,sid=engine.sid if self.venue=='kalshi' else None,
                            sequence=engine.seq if self.venue=='kalshi' else None,
                            _content_sha256=prepared_frame.get('content_sha256') if prepared_frame is not None else None)
                    except ConfirmationUnavailable as exc:
                        # A provider send-clock refusal disqualifies freshness
                        # proof, not the already validated SID/sequence/book.
                        confirmation=None
                        self.metrics['unconfirmed_snapshot_images']=self.metrics.get('unconfirmed_snapshot_images',0)+1
                        self.metrics['last_confirmation_refusal']=dict(at=utc(),reason=str(exc),generation=self.metrics['connections'])
                        if getattr(self.service,'database_mode',False):
                            from .bulk_checkpoint import save_failure
                            await owned_thread(save_failure,self.venue,raw,received.isoformat(),self.metrics['connections'],'confirm')
                    if confirmation:
                        validate(confirmation,value['raw']['ref'],value,_content_sha256=prepared_frame.get('content_sha256') if prepared_frame is not None else None)
                        value['book_confirmation']=confirmation
                    tick = time.perf_counter()
                    stage = 'queue'
                    self.queue_book(value,_content_sha256=prepared_frame.get('content_sha256') if prepared_frame is not None else None,
                                    _encoded_bytes=prepared_frame.get('encoded_bytes') if prepared_frame is not None else None)
                    self.metrics['receipt_queue_ms'] = (time.perf_counter()-tick)*1000
                    self.metrics['source_receipt_ms'] = None if book.raw.exchange_at is None else (received-book.raw.exchange_at).total_seconds()*1000
                    self.metrics['books'] += 1
                    self.metrics['frame_processing_ms']=(time.perf_counter()-processing_started)*1000
                    failures = 0
                    # Match the socket reader's bounded 64-frame CPU turn.
                    # Yielding every frame let its 64-frame producer starve the
                    # ready reconstructions. guard() still checks every frame.
                    if self.metrics['frames']%64==0:await asyncio.sleep(0)
            except asyncio.CancelledError:
                self.synchronization.revoke('cancelled')
                raise
            except Exception as exc:
                self.synchronization.revoke('continuity_lost')
                from .current_transport_diagnostics import exception_kind
                known = {'initial_image_deadline', 'incomplete_native_image',
                         'regressed_native_source_clock', 'future_native_source_clock',
                         'malformed_native_frame','native_receive_backlog_capacity',
                         'native_reconstruction_failure','Unowned synchronization image',
                         'Stale/revoked native book generation','Retired/unowned native book',
                         'Complete active native image required','Latest native book byte bound',
                         'Future native price clock','Regressed native price clock',
                         'Snapshot confirmation identity conflict','Book confirmation subscription conflict',
                         'Transaction timestamp reconstruction conflict','Future confirmation clock',
                         'Snapshot predates its request','Confirmation clock regressed',
                         'Replayed confirmation payload','Confirmation content mismatch',
                         'Snapshot request/continuity proof missing','Invalid confirmation age at receipt'}
                # Developer-owned vocabulary only; never persist provider text,
                # handshake headers, credentials or a raw exception repr.
                self.metrics['last_stream_failure'] = dict(at=utc(), stage=stage,
                    reason=str(exc) if type(exc) is ValueError and str(exc) in known else
                           'catalog_resync' if isinstance(exc, CatalogResync) or self.reconcile_needed else
                           'native_stream_failure',
                    exception=exception_kind(exc), generation=self.metrics['connections'],
                    selected=len(markets), initial_images=len(seen))
                if stage=='confirm':
                    sending=data.get('sending_ts_ms')
                    self.metrics['last_stream_failure']['confirmation_clocks']=dict(
                        send_minus_request_ms=None if type(sending) is not int or not request else sending-datetime.fromisoformat(request[1]).timestamp()*1000,
                        receipt_minus_send_ms=None if type(sending) is not int else received.timestamp()*1000-sending)
                from websockets.exceptions import ConnectionClosed
                if isinstance(exc,ConnectionClosed):
                    self.metrics['last_stream_failure']['close_codes']=dict(
                        received=getattr(exc.rcvd,'code',None),sent=getattr(exc.sent,'code',None))
                self.metrics['resyncs'] += 1
                status = getattr(getattr(exc,'response',None), 'status_code', None)
                if status in (401,403):
                    self.metrics.setdefault('last_handshake', {})['result'] = 'http_'+str(status)
                    self.failed = True
                    self.service.issue(self.venue, 'authentication' if status==401 else 'entitlement', 'websocket_'+str(status))
                    await call(self.service, self.service.source_state, self.venue, 'unavailable', 'Native feed access was refused.')
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
                        await call(self.service, self.service.source_state, self.venue, 'unavailable', 'Provider retry delay exceeds this runtime allowance.')
                        return
                    self.backoff_until = time.monotonic()+delay
                if isinstance(exc, BudgetStop):
                    if str(exc) in HOURLY_CAPS:
                        self.hourly_pause=True
                        self.service.issue(self.venue,'resource',str(exc))
                        await call(self.service, self.service.source_state, self.venue, 'budget_delayed', 'Native hourly transport allowance reached; waiting for its next window.')
                        return
                    self.failed = True
                    self.service.issue(self.venue, 'resource', str(exc))
                    await call(self.service, self.service.source_state, self.venue, 'unavailable', 'Native runtime resource allowance reached.')
                    return
                if isinstance(exc, (ValueError,KeyError,TypeError)) and checked_raw is not None and stage in ('decode','reconstruct','confirm','queue') and getattr(self.service,'database_mode',False):
                    from .bulk_checkpoint import save_failure
                    await owned_thread(save_failure,self.venue,checked_raw,received.isoformat(),self.metrics['connections'],stage)
                    self.metrics['unusable_frames_retained']=self.metrics.get('unusable_frames_retained',0)+1
                if isinstance(exc,ValueError):malformed += 1
                failures += 1
                if not self.reconcile_needed and not isinstance(exc,CatalogResync):
                    self.service.issue(self.venue, 'malformed_source' if isinstance(exc,ValueError) else 'connection', type(exc).__name__)
                await call(self.service, self.service.source_state, self.venue, 'resyncing', 'Native connection recovery requires a fresh image.')
                if malformed>=3 and not getattr(self.service,'database_mode',False):
                    self.failed=True
                    await call(self.service,self.service.source_state,self.venue,'error','Repeated native feed failures; source paused.')
                    return
                if failures >= self.config['reconnect_failures']:
                    # A finite reconnect burst yields to the normal discovery pace.
                    # Hourly counters continue to bound every later attempt.
                    failures = 0
                    self.backoff_until = time.monotonic()+self.config['rediscovery_seconds']
                    await call(self.service, self.service.source_state, self.venue, 'resyncing',
                               'Native connection unavailable; waiting before the next bounded retry.')
            finally:
                self.synchronization.revoke(self.synchronization.reason or 'disconnected')
                self.metrics['stream_connected']=False
                self.metrics['processing_inflight_frames']=0
                self.metrics['processing_received_at']=None
                self.active_engine=None
                self.reconstruction=None
                self.subscription_groups={};self.subscription_transition=None;self.subscription_blocked.clear()
                self.retired_subscription_ids=[]
                if receiver:await receiver.close()
                self.receiver=None
                if reconstruction:await reconstruction.close()
                if self.publication_handle:self.publication_handle.cancel()
                self.publication_handle=None;self.pending_books.clear();self.pending_since.clear();self.pending_recalculations.clear()
                if self.publication_task and not self.publication_task.done():
                    self.publication_task.cancel()
                    await asyncio.gather(self.publication_task,return_exceptions=True)
                if self.socket:
                    await self.socket.close()
                    self.socket = None
            delay = max(self.config['backoff_seconds'][min(failures-1,4)], self.backoff_until-time.monotonic())
            self.metrics['retries'] += 1
            self.backoff_until=time.monotonic()+delay
            await asyncio.sleep(delay)

    async def stop_stream(self):
        self.synchronization.revoke('stopped')
        # Revoke callbacks before joining publication: a joined SQL worker can
        # take time, during which the old stream must not admit another image.
        task, self.stream_task = self.stream_task, None
        if task:task.cancel()
        if self.publication_handle:self.publication_handle.cancel()
        self.publication_handle=None;self.pending_books.clear();self.pending_since.clear();self.pending_recalculations.clear()
        if self.publication_task and not self.publication_task.done():
            self.publication_task.cancel()
            await asyncio.gather(self.publication_task,return_exceptions=True)
        if task:
            await asyncio.gather(task, return_exceptions=True)
        if self.socket:
            await self.socket.close()
            self.socket = None
        await self.drain_raw()
        if self.wake_task:
            await asyncio.gather(self.wake_task,return_exceptions=True)
            self.wake_task = None

    async def restore_catalog(self):
        from .native_recovery import load
        from app.comparison.lifecycle import worker_selections
        started=time.monotonic()
        restored=await owned_thread(load,self.venue,self.checkpoint.scope)
        if restored is None:return
        self.guard()
        cat,parsed,saved_at=restored
        selections=await owned_thread(worker_selections,self.venue,parsed,cat)
        await call(self.service,self.service.catalog,self.venue,cat)
        self.guard()
        self.catalog,self.markets=cat,parsed
        self.census_generation=cat.get('acquisition_census_generation')
        self.lifecycle.reconcile(selections,datetime.now(timezone.utc))
        self.lifecycle_initialized=True
        self.signature=self.lifecycle.signature()
        self.metrics.update(selected_markets=len(parsed),catalog_events=len(cat['events']),catalog_markets=len(cat['markets']),
            restored_catalog_at=saved_at,restore_seconds=time.monotonic()-started,restored_price_images=0)
        if parsed:self.stream_task=asyncio.create_task(self.stream(list(parsed.values())))

    async def run(self):
        limits = dict(discovery_requests=self.config['requests_per_source'], session_bytes=self.config['source_bytes'],
            frame_bytes=256*1024, dollars_per_discovery_request='0', dollars_per_connection='0', dollar_cap_per_source='0')
        spec = dict(mode='real', native_sources={self.venue:dict(state='enabled')}, native_transport=native_payload.BULK_TRANSPORT_CONTRACT,
                    http=dict(timeout=10), v1_comparison_policy='manual-comparison-2')
        try:
            try: self.credential = load_credentials([self.venue])[self.venue]
            except RuntimeError:
                self.service.issue(self.venue, 'authentication', 'dedicated_credential_missing_or_invalid')
                await call(self.service, self.service.source_state, self.venue, 'unavailable', 'Dedicated native feed credentials are unavailable.')
                return
            self.client = REST(ENDPOINTS[self.venue]['rest'], limits, self.receipt, 10,
                               PredictionBudget(limits), venue=self.venue, credential=self.credential)
            native_payload.configure_transport(self.client, spec)
            if getattr(self.service,'database_mode',False):
                from .bulk_checkpoint import Checkpoint
                self.checkpoint=Checkpoint(self.venue,dict(sports=native_scope(self.config),families=native_markets(self.config)))
            if getattr(self,'checkpoint',None):await self.restore_catalog()
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
                    code = str(exc) if isinstance(exc,BudgetStop) or type(exc) is ValueError and str(exc) in RETRYABLE_DISCOVERY else type(exc).__name__
                    self.metrics['last_discovery_failure'] = dict(at=utc(), reason=code if code in RETRYABLE_DISCOVERY | HOURLY_CAPS | DISCOVERY_CAPS else 'native_discovery_failure', consecutive=errors)
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
                    retryable=code in RETRYABLE_DISCOVERY
                    if retryable and not self.failed and errors >= 3:
                        self.pages=[]
                        errors=0
                        self.backoff_until=max(self.backoff_until,time.monotonic()+self.config['rediscovery_seconds'])
                        await call(self.service,self.service.source_state,self.venue,'resyncing',
                                   'Native discovery unavailable; waiting before the next bounded retry.')
                        await asyncio.sleep(max(0,self.backoff_until-time.monotonic()))
                        continue
                    if (retryable and not self.failed and errors<3 and self.stream_task is not None
                            and not self.stream_task.done()):
                        # Failed optional rediscovery does not invalidate the
                        # still-owned complete catalog or a healthy native socket.
                        # Same finite attempts/backoff; no new transport allowance.
                        self.pages=[]
                        self.metrics['discovery_deferrals']=self.metrics.get('discovery_deferrals',0)+1
                        self.metrics['last_discovery_deferral']=dict(at=utc(),reason=code)
                        await asyncio.sleep(max(self.config['backoff_seconds'][errors-1],self.backoff_until-time.monotonic()))
                        continue
                    await self.stop_stream()
                    if self.failed or errors >= 3 or isinstance(exc,BudgetStop) and not retryable:
                        self.failed = True
                        await call(self.service, self.service.source_state, self.venue, 'unavailable', 'Native discovery stopped after its bounded failures; independent sources continue.')
                        break
                    await call(self.service, self.service.source_state, self.venue, 'resyncing', 'Native discovery is unavailable; healthy sources continue.')
                    await asyncio.sleep(max(self.config['backoff_seconds'][errors-1],self.backoff_until-time.monotonic()))
                    continue
                await asyncio.sleep(max(self.config['rediscovery_seconds'], self.backoff_until-time.monotonic()))
        finally:
            self.lifecycle.revoke()
            await self.stop_stream()
            if self.client: await self.client.aclose()
            await self.finish_lifecycle()
            from .bulk_native import close_catalog_worker
            await close_catalog_worker(self)

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
        from .bulk_native import close_catalog_worker
        await close_catalog_worker(self)
