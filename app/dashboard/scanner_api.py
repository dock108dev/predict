"""SC02 GET scanner snapshots/compact incremental page replacements.

One shared process projection, one capture/evaluator worker, no settings loads,
provider calls or user/filter-specific financial caches. Started lazily by GET.
"""
import asyncio
from copy import deepcopy
from threading import Event
from time import perf_counter
from aiohttp import web

from app.comparison.scanner_projection import Projection, Filters
from app.comparison.calculation_control import cancellation
from app.storage.scanner_readiness import capture
from app.storage.store import connect
from app.storage.current_games import utc, engine_binding
from app.comparison.current_dependencies import digest, instant
from app.comparison.estimated_policy import load
from app.storage.scanner_publication import subscribe, lookup

INTERVAL_SECONDS = .25


class Scanner:
    def __init__(self, provider, *, connector=connect, clock=utc, summary_path=None):
        self.provider=provider; self.connector=connector; self.clock=clock
        self.projection=Projection(clock=clock); self.task=None; self.wake=Event()
        self.closed=False; self.unsubscribe=None; self.marker=None; self.deadline=None
        self.continuation=None
        from app.storage.scanner_preparation import PreparationCache
        self.preparation=PreparationCache()
        self.ticket_preparation=PreparationCache(max_entries=32,max_bytes=4*1024*1024)
        from pathlib import Path
        from app.storage.store import ROOT
        from app.comparison.scanner_summaries import SummaryWorker
        self.summaries=SummaryWorker(summary_path or Path(ROOT)/'.local/scanner-summary/episodes.sc06')
        self.projection.summary_observer=self.summaries.offer

    def stopped(self):
        return self.closed or self.provider.closed or self.provider.closing or not self.provider.dispatch

    def _withdraw_if_stopped(self):
        if not self.stopped():return False
        self.continuation=None
        self.projection.stop()
        return True

    def _capture(self):
        start=perf_counter()
        with self.connector() as db:
            frame,inputs,metadata=capture(db,config=deepcopy(self.provider.config),
                authority=self.provider.config.get('authority'),at=self.clock(),
                source_status=deepcopy(self.provider.states),cache=self.preparation,_shared_facts=True)
        # Both connection and repeatable-read transaction are closed before finance.
        return frame,inputs,metadata,(perf_counter()-start)*1000

    def _capture_selected(self, selected):
        """Fresh exact-member SQL validation; preparation never grants authority."""
        members=tuple(sorted({(value['quote']['source']['provider'],value['quote']['source']['native_event_id'])
                              for value in selected['inputs'].values()}))
        with self.connector() as db:
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                if db.execute('SELECT pg_database_size(current_database()) n').fetchone()['n']>=2*1024**3:
                    raise ValueError('ticket_sql_storage_guard')
                frame,inputs,_=capture(db,config=deepcopy(self.provider.config),
                    authority=self.provider.config.get('authority'),at=self.clock(),
                    source_status=deepcopy(self.provider.states),members=members,cache=self.ticket_preparation)
        return frame,inputs

    def _probe(self):
        from app.storage.scanner_publication import current_revision
        with self.connector() as db:
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                rows=current_revision(db)
        policy=load()
        from dataclasses import replace
        if hasattr(policy,'sizing_mode'):policy=replace(policy,sizing_mode='ceiling')
        marker=digest(dict(rows=rows,config=self.provider.config,states=self.provider.states,
                           engine=engine_binding(),policy=policy.to_dict(),
                           registry=self.preparation.registry(at=self.clock())))
        return marker,policy

    def _set_deadline(self, frame, metadata):
        future=[i['expires_at'] for i in frame['instruments'] if instant(i['expires_at'])>instant(self.clock())]
        if metadata.get('revalidate_at'):future.append(metadata['revalidate_at'])
        self.deadline=min(future,key=instant,default=None)

    def _ingest_capture(self, frame, inputs, metadata, elapsed, policy):
        kwargs=dict(capture_ms=elapsed,commit_observation=lookup(metadata['current_rows_revision']),policy=policy)
        if 'input_bytes_bound' in metadata:
            # The real capture owns detached SQL/cache-decoded values and has
            # already counted their encoded bytes. No other mutable owner keeps
            # them after this transfer. Fixture/legacy captures retain copying.
            self.projection._ingest_capture(frame,inputs,input_bytes_bound=metadata['input_bytes_bound'],**kwargs)
        else:self.projection.ingest(frame,inputs,**kwargs)

    def once(self):
        continuation,self.continuation=self.continuation,None
        if self._withdraw_if_stopped():return
        with cancellation(self.stopped):
            with self.projection.lock:
                current=(self.marker,self.projection.generation,self.projection.capture_revision)
                pending=bool(self.projection.pending) and not self.projection.stopped
            if (continuation is not None and continuation==current and self.marker is not None and pending
                    and (self.deadline is None or instant(self.clock())<instant(self.deadline))):
                # A successful previous POST proof supplies only detached work
                # inputs. Every continuation still obtains a fresh POST proof
                # before any newly evaluated value can be published.
                self._evaluate_current(self.marker);return
            marker,policy=self._probe()
            if self._withdraw_if_stopped():return
            if marker==self.marker and not self.projection.stopped and (self.deadline is None or instant(self.clock())<instant(self.deadline)):
                with self.projection.lock:pending=bool(self.projection.pending)
                if pending:self._evaluate_current(marker)
                else:self.projection.expire()
                return
            frame,inputs,metadata,elapsed=self._capture()
            if self._withdraw_if_stopped():return
            self.marker=marker
            self._set_deadline(frame,metadata)
            self._ingest_capture(frame,inputs,metadata,elapsed,policy)
            self._evaluate_current(marker)

    def _evaluate_current(self, marker):
        self.continuation=None
        self.projection.drain(publish=False)
        if self._withdraw_if_stopped():return
        latest,_=self._probe()
        if self._withdraw_if_stopped():return
        if latest!=marker:
            # Reconcile against the latest detached proof before publishing a
            # completed financial result. Unrelated pairs retain cached work.
            frame,inputs,metadata,elapsed=self._capture()
            if self._withdraw_if_stopped():return
            self._set_deadline(frame,metadata)
            _,policy=self._probe()
            if self._withdraw_if_stopped():return
            self._ingest_capture(frame,inputs,metadata,elapsed,policy)
            self.marker=None
        else:
            self.projection.publish()
            with self.projection.lock:
                if (self.marker==marker and self.projection.pending and not self.projection.stopped
                        and not self.stopped() and (self.deadline is None or instant(self.clock())<instant(self.deadline))):
                    self.continuation=(marker,self.projection.generation,self.projection.capture_revision)

    async def run(self):
        try:
            while not self.closed:
                self.wake.clear()
                try:await asyncio.to_thread(self.once)
                except Exception as exc:
                    self.continuation=None
                    if self.stopped():self.projection.stop()
                    else:
                        self.marker=None; self.projection.fail(type(exc).__name__+':'+str(exc)[:120])
                # One coalescing bit, not an unbounded callback/task queue.
                with self.projection.lock:
                    pending=bool(self.projection.pending) and not self.projection.stopped
                if pending and not self.stopped():
                    # Each bounded drain yields through to_thread. Continue useful
                    # work immediately while preserving event-loop cancellation.
                    await asyncio.sleep(0)
                    continue
                await asyncio.to_thread(self.wake.wait,INTERVAL_SECONDS)
        finally:
            self.projection.stop()

    def start(self):
        if self.task is None:
            self.unsubscribe=subscribe(lambda observation:self.wake.set())
            self.task=asyncio.create_task(self.run())

    async def close(self):
        self.closed=True; self.continuation=None; self.projection.stop(); self.wake.set()
        if self.task is not None:await self.task
        if self.unsubscribe:self.unsubscribe()
        await asyncio.to_thread(self.summaries.close)
        self.preparation.clear(); self.ticket_preparation.clear()


def mount(app, provider):
    scanner=Scanner(provider)
    async def close(app):await scanner.close()
    app.on_cleanup.append(close)
    scanner.summary_reading = False
    async def summaries(req):
        dimensions=set(Filters.__dataclass_fields__)
        if set(req.query)-dimensions or any(len(v)>256 for v in req.query.values()):
            return web.json_response(dict(error='summary_query_invalid'),status=400)
        if scanner.summary_reading:
            return web.json_response(dict(error='summary_read_capacity'),status=503)
        try:
            filters=Filters(**{k:tuple(v.split(',')) if k in ('venues','sports','leagues','markets','periods') else v
                              for k,v in req.query.items()})
            scanner.summary_reading=True
            task=asyncio.create_task(asyncio.to_thread(scanner.summaries.read,filters=filters,at=scanner.clock()))
            # A disconnected HTTP reader cannot release capacity while its
            # detached read still runs and thereby queue unlimited tasks.
            def finished(_):scanner.summary_reading=False
            task.add_done_callback(finished)
            value=await asyncio.shield(task)
            return web.json_response(value,headers={'Cache-Control':'no-store'})
        except (ValueError,TypeError,ZeroDivisionError):
            return web.json_response(dict(error='summary_query_invalid'),status=400)
    app.router.add_get('/api/scanner/summaries',summaries)
    async def handle(req):
        allowed={'venues','sports','leagues','markets','periods','category','minimum_edge','minimum_size',
                 'offset','limit','since','epoch','query_id','expected_revision'}
        if set(req.query)-allowed or any(len(v)>256 for v in req.query.values()) or len(req.query)>len(allowed):
            return web.json_response(dict(error='scanner_query_invalid',provider_requests=0),status=400)
        try:
            filters=Filters(**{k:tuple(v.split(',')) if k in ('venues','sports','leagues','markets','periods') else v
                               for k,v in req.query.items() if k in Filters.__dataclass_fields__})
            args={k:int(req.query[k]) for k in ('offset','limit','since','expected_revision') if k in req.query}
            args.update({k:req.query[k] for k in ('epoch','query_id') if k in req.query})
            scanner.start()
            if scanner.stopped():scanner.projection.stop()
            out=scanner.projection.view(filters=filters,**args)
            return web.json_response(out)
        except (ValueError,TypeError,ZeroDivisionError) as exc:
            return web.json_response(dict(error='scanner_query_invalid',reason=str(exc)[:160],provider_requests=0),
                                     status=409 if str(exc)=='scanner_page_revision_changed' else 400)
    async def transitions(req):
        dimensions = set(Filters.__dataclass_fields__)
        allowed = dimensions | {'cursor','server_id','epoch','scope'}
        if set(req.query)-allowed or any(len(v)>256 for v in req.query.values()):
            return web.json_response(dict(error='transition_query_invalid'),status=400)
        try:
            filters = Filters(**{k:tuple(v.split(',')) if k in ('venues','sports','leagues','markets','periods') else v
                                 for k,v in req.query.items() if k in dimensions})
            cursor = int(req.query['cursor']) if 'cursor' in req.query else None
            scanner.start()
            if scanner.stopped():scanner.projection.stop()
            p = scanner.projection
            p.expire()
            with p.lock:
                value = p.transitions.read(p,filters,cursor=cursor,**{k:req.query[k] for k in ('server_id','epoch','scope') if k in req.query})
            return web.json_response(value,headers={'Cache-Control':'no-store'})
        except (ValueError,TypeError,ZeroDivisionError):
            return web.json_response(dict(error='transition_query_invalid'),status=400)
    app.router.add_get('/api/scanner/transitions',transitions)
    app.router.add_get('/api/scanner',handle)
    from .scanner_ticket_api import mount as mount_tickets
    scanner.tickets=mount_tickets(app,scanner)
    return scanner
