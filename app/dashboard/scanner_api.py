"""Shared background scanner owner and database-only app reader."""
import asyncio
from app.diagnostics import failure
from .local_security import public_reason
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
    def __init__(self, provider, *, connector=connect, clock=utc, summary_path=None, durable=False):
        self.provider=provider; self.connector=connector; self.clock=clock
        self.projection=Projection(clock=clock); self.task=None; self.wake=Event()
        self.closed=False; self.unsubscribe=None; self.marker=None; self.deadline=None
        self.continuation=None
        self.durable=durable; self.restored=False; self.persisted=None; self.error=None
        self.admission_status=None
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
        self.readiness_publication=None
        config=deepcopy(self.capture_config if self.durable else self.provider.config)
        with self.connector() as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            if self.durable:
                from app.collection.runtime_status import read_runtime
                capture_owner=read_runtime(db)
            frame,inputs,metadata=capture(db,config=config,
                authority=config.get('authority'),at=self.clock(),
                source_status=None if self.durable else deepcopy(self.provider.states),
                cache=self.preparation,_shared_facts=True,resource_guard=getattr(self,'capture_guard',None))
            if self.durable and config==capture_owner['config']:
                self.readiness_publication=(metadata['publication_proof'],capture_owner['revision'])
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
                remote=getattr(self.provider,'remote_runtime',False)
                config=deepcopy(self.capture_config if remote else self.provider.config)
                frame,inputs,_=capture(db,config=config,
                    authority=config.get('authority'),at=self.clock(),
                    source_status=None if remote else deepcopy(self.provider.states),members=members,cache=self.ticket_preparation)
        return frame,inputs

    def _probe(self):
        from app.storage.scanner_publication import current_revision
        with self.connector() as db:
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                rows=current_revision(db)
                if self.durable:
                    from app.collection.runtime_status import read_runtime
                    runtime=read_runtime(db)
                    self.runtime_revision=runtime['revision']
                    self.database_proof=rows
                    self.capture_config=runtime['config']
                    self.capture_states=runtime['states']
        policy=load()
        from dataclasses import replace
        if hasattr(policy,'sizing_mode'):policy=replace(policy,sizing_mode='ceiling')
        marker=digest(dict(rows=rows,config=self.capture_config if self.durable else self.provider.config,
                           states=self.capture_states if self.durable else self.provider.states,
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
        # The independent durable data owner shares its capture budget with
        # boards and coverage. Fixture/local readers keep their existing lane.
        if not self.durable or self.stopped():return self._once_worker()
        from app.collection.background_work import BACKGROUND
        from app.storage.scanner_readiness import capture_reservation
        with self.connector() as db:
            required=capture_reservation(db)
            if not self.restored:
                old=db.execute('SELECT octet_length(payload::text) n FROM scanner_latest WHERE singleton').fetchone()
                required=max(required,(int(old['n'])*8 if old else 0)+16*1024*1024)
        with BACKGROUND.claim('scanner',required) as lease:
            self.admission_status=dict(state='admitted' if lease else 'deferred',reason=lease.reason,
                reserved_bytes=required,resident_bytes=lease.resident_bytes)
            if not lease:
                self.projection.expire()
                return lease.deferred()
            self.capture_guard=lambda amount:BACKGROUND.resize('scanner',amount)
            try:return self._once_worker()
            except ValueError as exc:
                if str(exc) != 'background_memory_capacity':raise
                # A resize refusal is temporary admission, not corrupt capture.
                # Keep the last dated frame; live readers independently check its
                # authority. Retry from a new SQL snapshot on the next turn.
                self.marker=None;self.continuation=None
                self.projection.fail('background_memory_capacity')
                self.preparation.clear()
                self.admission_status.update(state='deferred',reason=str(exc))
                return dict(published=False,deferred=True,reason=str(exc),provider_requests=0)
            finally:self.capture_guard=None

    def _once_worker(self):
        if self.durable and not self.restored:
            from app.storage.scanner_latest import restore
            with self.connector() as db:
                old=db.execute('SELECT payload FROM scanner_latest WHERE singleton').fetchone()
            if old:restore(self.projection,old['payload'],economics_only=True)
            self.restored=True
        self._once()
        if self.durable and self.stopped():
            # Stopped publications carry only withdrawal/censored history. They
            # cannot restore action authority, but must reach app-absent readers.
            from app.storage.scanner_latest import publish
            self.marker,_=self._probe()
            with self.connector() as db:
                publish(db,self,proof=self.database_proof,runtime_revision=self.runtime_revision)
        elif self.durable and self.marker is not None:
            from app.storage.scanner_latest import publish
            latest,_=self._probe()
            if latest==self.marker:
                with self.connector() as db:
                    if not publish(db,self,proof=self.database_proof,runtime_revision=self.runtime_revision):
                        self.marker=None
        if self.durable and self.marker is None and not self.stopped() and getattr(self,'readiness_publication',None):
            # Live ingress may invalidate current financial authority while a
            # complete frozen readiness capture is being prepared. Preserve its
            # measured scope separately, never its rows, receipts or tickets.
            from app.storage.scanner_latest import publish
            proof,revision=self.readiness_publication
            with self.connector() as db:
                publish(db,self,proof=proof,runtime_revision=revision,capture_only=True)

    def _once(self):
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
            if self.durable:
                # Preserve this complete dated capture, withdraw current finance,
                # and yield. Recapturing immediately doubles residency and can
                # chase continuously changing inputs forever in one worker turn.
                self.marker=None
                with self.projection.lock:
                    self.projection.receipts.clear()
                    self.projection._publish({}, 'captured_inputs_changed')
                return
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
        from app.collection.background_work import optional_thread
        try:
            while not self.closed:
                self.wake.clear()
                deferred=False
                try:
                    turn=await (optional_thread(self.once) if self.durable else asyncio.to_thread(self.once))
                    deferred=isinstance(turn,dict) and turn.get('deferred',False)
                    self.error=None
                except Exception as exc:
                    failure(__name__, 'scanner_reconciliation', exc)
                    self.error=type(exc).__name__
                    self.continuation=None
                    if self.stopped():self.projection.stop()
                    else:
                        self.marker=None; self.projection.fail('scanner_reconciliation_failed')
                    if self.durable:
                        try:
                            with self.connector() as db:
                                db.execute('DELETE FROM scanner_latest WHERE runtime_id=%s',(self.provider.runtime_id,))
                        except Exception as secondary:
                            # Heartbeat/dependency/expiry guards remain independent.
                            failure(__name__, 'scanner_failure_withdrawal', secondary)
                # One coalescing bit, not an unbounded callback/task queue.
                with self.projection.lock:
                    pending=bool(self.projection.pending) and not self.projection.stopped
                if pending and not self.stopped() and not deferred:
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
        if self.durable:
            from app.collection.background_work import BACKGROUND
            BACKGROUND.cancel('scanner')
        if self.task is not None:await self.task
        if self.unsubscribe:self.unsubscribe()
        await asyncio.to_thread(self.summaries.close)
        self.preparation.clear(); self.ticket_preparation.clear()


class ScannerReader(Scanner):
    """Hydrate compact publications; never run shared finance in the app."""
    def __init__(self,provider,*,connector=connect,clock=utc):
        from app.storage.scanner_preparation import PreparationCache
        from app.storage.scanner_latest import SummaryReader
        self.provider=provider; self.connector=connector; self.clock=clock
        self.projection=Projection(clock=clock); self.closed=False; self.closing=False
        self.preparation=PreparationCache(max_entries=1)
        self.ticket_preparation=PreparationCache(max_entries=32,max_bytes=4*1024*1024)
        self.summaries=SummaryReader(self); self.value=None; self.loaded=None
        self.healthy=False; self.authority_until=None
        self.unavailable_reason=None; self.collection_stopped=False

    def stopped(self):
        return (self.closed or self.collection_stopped or not self.healthy or self.authority_until is None
                or instant(self.clock())>=instant(self.authority_until))

    def _withdraw_if_stopped(self):
        """Deny stale authority without inventing an acknowledged collection Stop."""
        if not self.stopped():return False
        self.loaded=None
        with self.projection.lock:
            if self.closed or self.collection_stopped:
                self.projection.stop()
            elif (self.projection.state!='unavailable' or self.projection.stopped
                  or self.projection.rows or self.projection.receipts or self.projection.cache
                  or self.projection.targets or self.projection.pending or self.projection.inputs):
                # stopped() also guards unavailable proofs and dead heartbeats.
                # Those failures clear every financial authority just as Stop
                # does, while retaining their distinct customer-visible state.
                self.projection.stopped=False
                self.projection.fail('background_results_unavailable')
                self.projection.state='unavailable'
        return True

    def refresh(self):
        # Ticket workers and HTTP share this reader. Serialize capture/restore
        # with the projection's existing lock so an older read cannot replace a
        # newer publication, without introducing a second lock ordering.
        with self.projection.lock:
            self._refresh()

    def _refresh(self):
        from dataclasses import replace
        from datetime import timedelta
        from app.collection.runtime_status import read_runtime, HEARTBEAT_SECONDS
        from app.storage.scanner_latest import restore
        from app.storage.scanner_publication import current_revision
        try:
            with self.connector() as db:
                with db.transaction():
                    db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    runtime=read_runtime(db)
                    row=db.execute('SELECT * FROM scanner_latest WHERE singleton').fetchone()
                    proof=current_revision(db)
            policy=load()
            if hasattr(policy,'sizing_mode'):policy=replace(policy,sizing_mode='ceiling')
            marker=digest(dict(rows=proof,config=runtime['config'],states=runtime['states'],
                engine=engine_binding(),policy=policy.to_dict(),registry=self.preparation.registry(at=self.clock())))
            value=None if row is None else row['payload']
            if value is not None:
                from app.comparison.readiness_encoding import expand
                value['frame']=expand(value['frame'])
            self.value=value
            self.capture_config=runtime['config']
            self.collection_stopped=bool(runtime.get('global_stopped',False))
            valid=(runtime['active'] and not self.collection_stopped
                   and row is not None and row['runtime_id']==runtime['runtime_id']
                   and runtime.get('calculations',{}).get('scanner','running')=='running'
                   and row['runtime_revision']==runtime['revision'] and value['source_marker']==marker
                   and (value['deadline'] is None or instant(self.clock())<instant(value['deadline'])))
            self.healthy=bool(valid)
            self.unavailable_reason=None if valid else 'background_publication_binding_unavailable'
            self.authority_until=((instant(runtime['heartbeat_at'])+timedelta(seconds=HEARTBEAT_SECONDS)).isoformat()
                                  if runtime['heartbeat_at'] else None)
            if not valid:
                if value and value.get('capture_only') and row['runtime_id']==runtime['runtime_id']:
                    # Keep the exact capture clock and full scope visible, but
                    # fail() below clears all financial/action authority.
                    if self.projection.capture_revision!=value['capture_revision']:
                        self.projection.fail('captured_inputs_changed')
                    self.projection.frame=deepcopy(value['frame'])
                    self.projection.frame['capture_only']=True
                    self.projection.capture_revision=value['capture_revision']
                    self.projection.last_capture_ms=value['last_capture_ms']
                    self.projection.published_at=row['published_at']
                self.loaded=None; self._withdraw_if_stopped()
                return
            identity=(row['runtime_id'],row['publication'],row['runtime_revision'],value['source_marker'],row['published_at'])
            if identity!=self.loaded or self.projection.stopped:
                restore(self.projection,value)
                self.value=value; self.loaded=identity
        except Exception as exc:
            failure(__name__, 'scanner_publication_read', exc)
            self.healthy=False; self.loaded=None; self.collection_stopped=False
            self._withdraw_if_stopped()
            self.unavailable_reason='background_read_'+type(exc).__name__

    def start(self):
        self.refresh()

    def _selection_snapshot(self,selected):
        try:
            return self._selection_capture(selected)
        except Exception as exc:
            failure(__name__, 'scanner_selection_capture', exc)
            # An unavailable selected SQL proof cannot preserve a ready ticket
            # or leak storage exception text through the binding endpoint.
            self.healthy=False; self.loaded=None; self.collection_stopped=False
            self._withdraw_if_stopped()
            return self.projection.frame,{}

    def _selection_capture(self,selected):
        self.refresh()
        if self.stopped() or not self.value:return self.projection.frame,{}
        pair=next((p for p in self.projection.frame['pairs'] if p['id']==selected['pair_id']),None)
        if pair is None:return self.projection.frame,{}
        members=tuple(sorted({tuple(self.value['members'][k]) for k in pair['legs']}))
        with self.connector() as db:
            config=deepcopy(self.capture_config)
            frame,inputs,_=capture(db,config=config,
                authority=config.get('authority'),at=self.clock(),
                source_status=None,members=members,cache=self.ticket_preparation)
        return frame,inputs

    def _capture_selected(self,selected):
        self.refresh()
        if self.stopped():raise ValueError('data_runtime_unavailable')
        return super()._capture_selected(selected)

    async def close(self):
        self.closed=True; self.healthy=False; self.projection.stop()
        self.preparation.clear(); self.ticket_preparation.clear()


def mount(app, provider):
    scanner=ScannerReader(provider) if getattr(provider,'remote_runtime',False) else Scanner(provider)
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
            scanner._withdraw_if_stopped()
            out=scanner.projection.view(filters=filters,**args)
            return web.json_response(out)
        except (ValueError,TypeError,ZeroDivisionError) as exc:
            reason=public_reason(exc,allowed={'scanner_page_revision_changed','scanner_category_unsupported',
                'scanner_filter_invalid'},fallback='scanner_query_invalid',operation='scanner_query',logger=__name__)
            return web.json_response(dict(error='scanner_query_invalid',reason=reason,provider_requests=0),
                                     status=409 if reason=='scanner_page_revision_changed' else 400)
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
            scanner._withdraw_if_stopped()
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
