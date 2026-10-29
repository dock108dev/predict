"""Automatic source-owning current provider, independent of browser lifetimes."""
import asyncio
from .current_ingress import operation, call
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import time
from uuid import uuid4
from .current_policy import load, validate, candidate, consume, ROOT, VERSION, APP_RUNNING_DURATION, aggregate_scope, native_scope, native_markets
from .local_ownership import LocalOwnership
from .current_sink import LatestStateSink, utc
from app.dashboard.current_state import unavailable
from app.dashboard.current_contract import packed


class CurrentService:
    allow_synthetic = False

    def __init__(self, config=None, *, directory=None, ownership=None, worker_factory=None, evidence=None, aggregate_factory=None, config_loader=None, retained_directory=None, database_mode=False, paused_sources=(), globally_stopped=False):
        self.config = load() if config is None else validate(config)
        from app.comparison.coverage import CoverageLedger
        self.coverage = CoverageLedger({v: native_scope(self.config) if v in ('kalshi','polymarket_us') else
            aggregate_scope(self.config) if self.config['aggregate_enabled'] else []
            for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')},
            {v:native_markets(self.config) if v in ('kalshi','polymarket_us') else self.config['families']
             for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')})
        self.directory = Path(directory) if directory else ROOT/'.local/predict-current'
        self.ownership = ownership or LocalOwnership()
        self.worker_factory = worker_factory
        self.evidence = evidence
        self.aggregate_factory = aggregate_factory
        self.config_loader = config_loader
        self.retained_directory = retained_directory
        self.retained_quota = None
        if retained_directory is not None:
            from .current_quota import QuotaLedger
            self.retained_quota = QuotaLedger(Path(retained_directory).parent)
        self.database = None
        if type(database_mode) is not bool:raise ValueError('Explicit current database mode required')
        self.database_mode = database_mode
        self.paused_sources = set(paused_sources)
        self.globally_stopped = globally_stopped
        self.runtime_id = str(uuid4())
        self.store = self.sink = None
        self.workers = {}
        self.tasks = {}
        self.client_cleanup_tasks = {}
        self.watchdog = None
        self.dispatch = False
        self.started = False
        self.closed = False
        self.closing = False
        self._source_close_started = False
        self.cleanup_complete = False
        self.cleanup_errors = []
        self.issues = []
        self.attempt = None
        self.digest = None
        self.deadline = None
        self.peak_rss = 0
        self.sampled_rss = None
        self.stop_reason = None
        from .current_clock import continuous
        self.clock_wall, self.clock_mono = time.time(), continuous()
        from .current_ingress import Ingress
        self.ingress = Ingress(self)
        self._control_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self.states = self.initial_state()['source_status']

    def initial_state(self):
        raw = unavailable()
        raw.update(runtime_id=self.runtime_id, state='connecting')
        for venue in ('kalshi','polymarket_us'):
            raw['source_status'][venue] = dict(state='connecting', reason_code='native_connecting', reason='Connecting to the native feed.', next_due_at=None)
        for venue in ('novig','prophetx'):
            raw['source_status'][venue] = dict(state='budget_delayed', reason_code='aggregate_connecting', reason='Shared aggregate cycle: ' + ', '.join(aggregate_scope(self.config)) + '; every 15 minutes, 09:00–23:00 Eastern, with evidenced quota.', next_due_at=None) if self.config['aggregate_enabled'] else dict(state='stopped', reason_code='aggregate_disabled', reason='Aggregate acquisition is disabled in startup configuration.', next_due_at=None)
        return raw

    async def start(self, store):
        if self.started: return
        self.started = True
        self.store = store
        if self.database_mode:
            from .current_database import DatabasePipeline, DatabaseIngressSink
            self.sink = DatabaseIngressSink(store,self.config,process_normalization=True)
            self.database = DatabasePipeline(self)
            await self.database.start()
        else:
            self.sink = LatestStateSink(store, self.initial_state(), self.config)
        self.sink.store = store
        await self._start_sources()

    async def _start_sources(self):
        if not self.issues:
            from .current_admin import retained_issues
            try:self.issues=retained_issues(self)
            except (ValueError,OSError,TypeError,RecursionError):
                self.issue('service','local_defect','issue_retention_invalid')
        if self.globally_stopped:
            for venue in ('kalshi','polymarket_us','novig','prophetx'):
                await call(self, self.source_state, venue, 'stopped', 'Collection explicitly stopped. Inspect Admin before guarded recovery.')
            return
        if not self.config['enabled']:
            # Retained prices remain inspectable while all dispatch is disabled.
            for venue in ('kalshi','polymarket_us'): await call(self, self.source_state, venue, 'unavailable', 'Acquisition is disabled in operational configuration; retained observations remain historical.')
            return
        try:
            self.ownership.acquire(self.runtime_id)
            self.digest, _ = candidate()
            self.attempt = consume(self.directory, self.runtime_id, self.config, self.digest)
        except (ValueError, OSError):
            if self.ownership.file: self.ownership.release()
            for venue in ('kalshi','polymarket_us','novig','prophetx'): await call(self, self.source_state, venue, 'unavailable', 'Native acquisition ownership or operational authority is unavailable.')
            self.issue('service','ownership','ownership_or_authority_unavailable')
            return
        self.deadline = float('inf') if self.config['duration_seconds']==APP_RUNNING_DURATION else time.monotonic()+self.config['duration_seconds']
        self.dispatch = True
        from .current_native import NativeWorker
        factory = self.worker_factory or NativeWorker
        for venue in ('kalshi','polymarket_us'):
            if venue in self.paused_sources:
                await call(self, self.source_state, venue, 'stopped', 'Source explicitly paused. This pause survives app and data restarts.')
                continue
            self.workers[venue] = factory(self,venue)
            self.tasks[venue] = asyncio.create_task(self.run_worker(venue), name='predict-current-'+venue)
        if self.config['aggregate_enabled'] and 'the_odds_api' not in self.paused_sources:
            from .current_aggregate import AggregateScheduler
            self.workers['the_odds_api']=(self.aggregate_factory or AggregateScheduler)(self)
            self.tasks['the_odds_api']=asyncio.create_task(self.run_worker('the_odds_api'),name='predict-current-aggregate')
        elif 'the_odds_api' in self.paused_sources:
            for venue in ('novig','prophetx'):
                await call(self, self.source_state, venue, 'stopped', 'Shared aggregate acquisition explicitly paused. Accounting and due times are preserved.')
        self.watchdog = asyncio.create_task(self.watch(), name='predict-current-resources')

    async def run_worker(self, venue):
        try:
            await self.workers[venue].run()
        except asyncio.CancelledError: raise
        except Exception as exc:
            self.issue(venue, 'local_defect', type(exc).__name__)
            if venue=='the_odds_api':
                try:await call(self, self.workers[venue].state, 'error', 'aggregate_worker_failed', 'Shared aggregate worker failed. Inspect each native worker status.')
                except Exception:self.cleanup_errors.append('aggregate_status_failed')
            else:await call(self, self.source_state, venue, 'error', 'Native worker failed; this source is paused.')

    def observation(self, venue, kind, value):
        if self.evidence:
            self.evidence(dict(source=venue, kind=kind, at=utc(), value=value))

    def issue(self, venue, category, code):
        from .current_admin import issue
        entry = issue(self, venue, category, code)
        venue, category, code = entry['provider'], entry['category'], entry['code']
        entry['issue_id'] = str(uuid4())
        existing = next((i for i in self.issues if (i['provider'],i['category'],i['code'],i['scope'],i['attempt_id'],i['affected_venues'])==(venue,category,code,entry['scope'],entry['attempt_id'],entry['affected_venues'])),None)
        if existing:
            existing['last_at']=entry['last_at']; existing['occurrences']+=1
        else: self.issues.append(entry)
        while len(self.issues)>self.config['issue_records'] or len(packed(self.issues))>self.config['issue_bytes']: self.issues.pop(0)
        self.observation(venue,'issue',entry)
        if self.attempt:
            try:
                path = self.directory/'issues.json'
                temp = self.directory/('issues-'+str(uuid4())+'.tmp')
                fd = os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(packed(self.issues)); stream.flush(); os.fsync(stream.fileno())
                os.replace(temp,path)
                fd=os.open(self.directory,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
            except OSError:
                if 'issue_persistence_failed' not in self.cleanup_errors:self.cleanup_errors.append('issue_persistence_failed')
            finally:
                try:temp.unlink(missing_ok=True)
                except OSError:pass

    def row(self, kind, venue, **value):
        return dict(type=kind, source=venue, session_id=self.runtime_id, observed_at=utc(), **value)

    @operation
    def source_state(self, venue, state, reason):
        if self.store is None or self.store.closed: return
        status = dict(state=state, reason_code='native_'+state, reason=reason, next_due_at=None)
        if self.states.get(venue)==status: return
        states = deepcopy(self.states); states[venue]=status
        try:
            (yield (self.row('source_health',venue,state='connected' if state=='available' else state), states))
            self.states = states
        except Exception as exc:
            # Preserve previous admitted prices and mark only affected source.
            self.issue(venue,'local_defect',type(exc).__name__)
            self.degrade(venue, 'Current reduction failed; fresh source images are required.')

    def degrade(self, venue, reason):
        from app.dashboard.current_contract import snapshot_inputs, quotes_of
        states = deepcopy(self.states)
        states[venue]=dict(state='resyncing',reason_code='reducer_resync',reason=reason,next_due_at=None)
        raw=snapshot_inputs(self.store._state)
        raw.update(source_status=states,state='degraded',state_revision=raw['state_revision']+1,clock_at=utc())
        for event in raw['events']:
            for group in event['groups']:
                for outcome in group['outcomes']:
                    for quote in quotes_of(outcome):
                        if quote['venue']==venue and quote['state']!='resyncing':
                            quote['state']='resyncing';quote['revision']+=1
        changed=any(x['quote']['venue']==venue and x['quote']['state']!='resyncing' for x in self.store.index(self.store._state).values())
        self.store.commit(raw)
        if changed:
            for prior in self.sink.revisions.values():
                if prior['source']==venue:prior['revision']+=1;prior['fingerprint']=None
        self.states=states

    @operation
    def catalog(self, venue, cat, *, prepared=None, catalog_delta=None):
        if not self.dispatch: raise asyncio.CancelledError()
        cats = prepared if prepared is not None else prepare_catalog(self.sink.reducer.inventory,venue,cat)
        generation=(self.sink.reducer.generation or 0)+1
        prior_books=set(self.sink.reducer.books)
        worker=self.workers.get(venue)
        transition=getattr(worker,'subscription_transition',None)
        invalidated=set() if not transition else transition['invalidated']
        if catalog_delta is not None and invalidated:
            keys={key for key in prior_books if key[0]==venue and key[2] in invalidated}
            catalog_delta=dict(retained=catalog_delta['retained']-keys,withdraw=catalog_delta['withdraw']|keys,
                               refresh=catalog_delta['refresh']-keys)
        (yield (self.row('coverage_inventory',venue,inventory=cats,generation=generation,catalog_delta=catalog_delta,
                                 defer_catalog_refresh=self.database_mode and catalog_delta is not None,
                                 previous_generation=self.sink.reducer.generation), self.states))
        if self.database_mode and catalog_delta:
            for key in catalog_delta['refresh'] & self.sink.reducer.books.keys():
                worker=self.workers.get(key[0])
                if worker and not worker.closed and self.dispatch:
                    worker.queue_derived(self.sink.reducer.books[key]['book'])
        affected={key[0] for key in prior_books-set(self.sink.reducer.books)}
        for source in affected:
            worker=self.workers.get(source)
            lost={key[2] for key in prior_books-set(self.sink.reducer.books) if key[0]==source}
            if source==venue and transition and lost<=invalidated:continue
            if worker and not worker.closed and hasattr(worker,'request_resync'):
                (yield from self.source_state.operation(self, source, 'resyncing', 'Catalog identity changed; waiting for a fresh native image.'))
                worker.request_resync()
        self.observation(venue,'catalog',dict(events=len(cat['events']),markets=len(cat['markets']),
            selected=len(cat.get('selection',{}).get('ids',[])),exclusions=self.sink.exclusions))

    def book(self, venue, book):
        self.books(venue,[book])

    @operation
    def invalidate_market(self,venue,event_id,market_id):
        if not self.dispatch:raise asyncio.CancelledError()
        yield (self.row('native_market_invalid',venue,event_id=event_id,market_id=market_id),self.states)

    @operation
    def books(self, venue, books):
        if not self.dispatch: raise asyncio.CancelledError()
        states=deepcopy(self.states)
        book=max(books,key=lambda b:b['raw']['received_at'])
        states[venue]=dict(state='available',reason_code='native_image',reason='Native book images received.',
                           source_at=book['raw'].get('exchange_at'),received_at=book['raw']['received_at'],next_due_at=None)
        inventory=self.sink.reducer.inventory.get(venue,{})
        self.coverage.observe_native_prices(venue,books,inventory,'pending')
        try:
            observations=[self.row('prediction_book',venue,book=b,packets=[]) for b in books]
            (yield (self.row('prediction_books',venue,observations=observations), states))
            self.states=states
        except Exception as exc:
            from app.diagnostics import failure
            failure(__name__, 'current_image_admission', exc)
            self.coverage.observe_native_prices(venue,books,inventory,'rejected')
            from .current_database import NativeAdmissionError
            if isinstance(exc,NativeAdmissionError):
                import logging
                diagnostic=dict(exc.diagnostic)
                worker=self.workers.get(venue)
                if worker:
                    diagnostic['connection_generation']=worker.metrics.get('connections')
                    worker.metrics['last_admission_rejection']=diagnostic
                logging.getLogger(__name__).warning('native_admission_rejected %s',json.dumps(diagnostic,sort_keys=True))
            self.issue(venue,'local_defect',type(exc).__name__)
            self.degrade(venue,'Current image was rejected; a fresh complete image is required.')
            raise ValueError('current_admission_rejected') from None
        self.observation(venue,'book',dict(market_id=book['raw']['ref']['market_id'],sequence=book['sequence'],
            source_at=book['raw'].get('exchange_at'),received_at=book['raw']['received_at'],projected_at=self.store._state['projected_at'],
            quotes=len(self.store.index(self.store._state))))
        inventory=self.sink.reducer.inventory.get(venue,{})
        self.coverage.observe_native_prices(venue,books,inventory,'admitted')
        parents={e['id']:e for e in inventory.get('events',[])}
        for value in books:
            parent=parents.get(value['raw']['ref']['event_id'])
            if parent and parent.get('competition') in self.coverage.configured[venue]:
                self.coverage.observe_book(parent['competition'],venue,received_at=value['raw']['received_at'],source_at=value['raw'].get('exchange_at'))

    async def watch(self):
        from .continuous import rss
        while self.dispatch:
            self.sampled_rss=rss()
            self.peak_rss=max(self.peak_rss,self.sampled_rss)
            if self.peak_rss>self.config['rss_bytes']:
                self.stop_reason='Updates stopped after reaching the app memory limit. Inspect recovery in Admin.'
                self.issue('service','resource','rss_cap'); await self.close(); return
            if time.monotonic()>=self.deadline:
                await self.close(); return
            await asyncio.sleep(1)

    async def pause(self, venue):
        async with self._control_lock:
            await self._pause(venue)

    async def _pause(self, venue):
        if venue in ('novig','prophetx'):venue='the_odds_api'
        if venue not in self.workers: raise ValueError('Source is not running')
        self.ingress.revoke(venue)
        self.workers[venue].closed=True
        if hasattr(self.workers[venue],'lifecycle'):self.workers[venue].lifecycle.revoke()
        self.tasks[venue].cancel()
        done,pending=await asyncio.wait({self.tasks[venue]},timeout=self.config['cleanup_seconds'])
        if pending:
            self.issue(venue,'cleanup','worker_cleanup_timeout')
            self.cleanup_errors.append(venue+':cleanup_timeout')
            return
        if not await self.cleanup_clients([venue]):
            if venue+':cleanup_failure' not in self.cleanup_errors:self.cleanup_errors.append(venue+':cleanup_failure')
            self.issue(venue,'cleanup','source_cleanup_unresolved')
            return
        if not await self.ingress.drain(self.config['cleanup_seconds'],venue):
            self.cleanup_errors.append(venue+':ingress_cleanup_timeout')
            return
        if venue=='the_odds_api':
            await call(self, self.workers[venue].state, 'stopped', 'aggregate_paused', 'Shared aggregate acquisition paused. Persisted quota and next-due survive reopening.')
        else:await call(self, self.source_state, venue, 'stopped', 'Native source paused. This pause survives app and data restarts.')

    async def cleanup_clients(self, venues):
        # Cancellation-resistant closures must never keep the operator request
        # waiting forever. Keep one closure per worker and retain ownership on
        # timeout, even if that closure subsequently finishes.
        for venue in venues:
            if venue not in self.client_cleanup_tasks:
                task=asyncio.create_task(self.workers[venue].close())
                task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
                self.client_cleanup_tasks[venue]=task
        done,pending=await asyncio.wait({self.client_cleanup_tasks[v] for v in venues},timeout=self.config['cleanup_seconds']) if venues else (set(),set())
        for task in pending:task.cancel()
        if pending and 'client_cleanup_timeout' not in self.cleanup_errors:self.cleanup_errors.append('client_cleanup_timeout')
        failed=any(not t.cancelled() and t.exception() is not None or t.cancelled() for t in done)
        if failed and 'worker_cleanup_failure' not in self.cleanup_errors:self.cleanup_errors.append('worker_cleanup_failure')
        return not pending and not failed

    async def close(self):
        async with self._control_lock:
            await self._close()

    async def _close(self):
        async with self._close_lock:
            if self.closed or self._source_close_started: return
            self._source_close_started=True
            self.dispatch=False;self.closing=True
            self.ingress.revoke()
            if self.database:self.database.closed=True
            # Revocation precedes task cancellation and client/socket cleanup.
            for worker in self.workers.values():
                worker.closed=True
                if hasattr(worker,'lifecycle'):worker.lifecycle.revoke()
            if self.store:await self.store.revoke_source_publication()
            current=asyncio.current_task()
            tasks=[t for t in self.tasks.values() if t is not current]
            if self.watchdog and self.watchdog is not current:tasks.append(self.watchdog)
            for task in tasks:task.cancel()
            done,pending=await asyncio.wait(tasks,timeout=self.config['cleanup_seconds']) if tasks else (set(),set())
            await self.cleanup_clients(list(self.workers))
            if not await self.ingress.drain(self.config["cleanup_seconds"]):self.cleanup_errors.append("ingress_cleanup_timeout")
            if self.ingress.catalog_preparer is not None:await self.ingress.catalog_preparer.close()
            if self.database and not await self.database.close():self.cleanup_errors.append('database_cleanup_timeout')
            if getattr(self.sink,'normalizer',None) is not None:
                from .bulk_checkpoint import owned_thread
                await owned_thread(self.sink.close)
            if pending:self.cleanup_errors.append('worker_cleanup_timeout')
            self.cleanup_errors=list(dict.fromkeys(self.cleanup_errors))[:16]
            for venue in (() if self.ingress.tasks else ('kalshi','polymarket_us','novig','prophetx')):
                await call(self, self.source_state, venue, 'stopped' if not self.cleanup_errors else 'error', (self.stop_reason or 'Updates stopped. Reopen for a fresh runtime.') if not self.cleanup_errors else 'Native cleanup unresolved; ownership remains held.')
            if self.store:
                self.store.leases.clear();self.store.clients.clear()
            self.cleanup_complete=not self.cleanup_errors
            if self.cleanup_complete:
                self.ownership.release()
                self.closed=True
            else:self.issue('service','cleanup','cleanup_safety_unresolved')
            self.closing=False
            self.observation('service','shutdown',dict(cleanup_complete=self.cleanup_complete,ownership_released=self.ownership.file is None))

    def status_accounting(self):
        """Read-only display facts, prepared away from the acquisition loop."""
        from .quota_status import projection
        with projection():
            ledger=self.workers['the_odds_api'].ledger if 'the_odds_api' in self.workers else self.retained_quota
            return dict(quota=ledger.snapshot() if ledger is not None else None,
                        recovery_reason=self.recovery_reason())

    async def status_accounting_async(self, projector):
        worker=self.workers.get('the_odds_api')
        ledger=worker.ledger if worker and hasattr(worker,'ledger') else self.retained_quota
        try:evidence=worker.window_loader() if worker else None
        except (ValueError,OSError):evidence=None
        prepared=await projector.read(str(ledger.directory) if ledger else None,
            ledger.failed if ledger else None,
            str(self.retained_quota.directory) if self.retained_quota else None,evidence)
        return dict(quota=prepared['quota'],recovery_reason=self.recovery_reason(prepared=prepared))

    def status(self, *, accounting=None):
        from .quota_status import projection
        with projection():
            return self._status(accounting)

    def _status(self, accounting=None):
        from .current_admin import project
        if accounting is None:accounting=self.status_accounting()
        for worker in self.workers.values():
            for attribute,label in (('pending_since','derived'),('raw_since','raw')):
                pending=getattr(worker,attribute,{})
                actual=getattr(worker,'pending_books' if label=='derived' else 'raw_pending',{})
                worker.metrics['pending_books' if label=='derived' else 'raw_backlog']=len(actual)
                for mid in set(pending)-set(actual):pending.pop(mid,None)
                in_flight=getattr(worker,label+'_inflight',{})
                arrivals=list(pending.values())+list(in_flight.values())
                worker.metrics[label+'_oldest_pending_seconds']=time.monotonic()-min(arrivals) if arrivals else 0
            roster=set(getattr(worker,'markets',{}))
            for label in ('raw','derived'):
                served=getattr(worker,label+'_served',{})
                for mid in set(served)-roster:served.pop(mid,None)
                worker.metrics[label+'_roster_served']=len(roster & served.keys())
                worker.metrics[label+'_roster_unserved']=len(roster-served.keys())
                worker.metrics[label+'_oldest_service_seconds']=time.monotonic()-min(served.values()) if served else None
            if getattr(worker,'receiver',None):worker.receiver.measure()
            if hasattr(worker,'synchronization'):
                worker.metrics['synchronization']=worker.synchronization.snapshot(worker.metrics,
                    enabled=self.dispatch and not worker.closed and not worker.failed)
        raw = dict(schema=VERSION,runtime_id=self.runtime_id,candidate_digest=self.digest,
            attempt_id=self.attempt['attempt_id'] if self.attempt else None,dispatch_enabled=self.dispatch,
            ownership_held=self.ownership.file is not None,cleanup_complete=self.cleanup_complete,
            cleanup_errors=list(self.cleanup_errors),config=self.config,source_status=self.states,
            metrics={v:deepcopy(w.metrics) for v,w in self.workers.items()},peak_rss_bytes=self.peak_rss,
            observation_retention=None,
            ingress=dict(owned=len(self.ingress.tasks),maximum=self.ingress.maximum,records=list(self.ingress.records)),
            sink=None if self.sink is None else dict(sequence=self.sink.sequence,**self.sink.metrics),
            exclusions=[] if self.sink is None else self.sink.exclusions,issues=deepcopy(self.issues),
            odds_api_requests=self.workers['the_odds_api'].metrics['requests'] if 'the_odds_api' in self.workers else 0,
            quota=accounting['quota'])

        result=project(self, raw, accounting=accounting)
        if self.database:result['database']=self.database.status()
        return result

    def recovery_reason(self, *, prepared=None):
        if self.closing:return 'cleanup_in_progress'
        if self.cleanup_errors:return 'cleanup_safety_unresolved'
        if self.store is None or self.store.closed:return 'store_closed'
        if prepared is not None and prepared['pending']:return prepared['pending']
        if self.retained_quota is not None and prepared is None:
            from .current_conservative import pending_reason
            from .quota_status import read
            try:reason=pending_reason(read(self.retained_quota))
            except (ValueError,OSError):return 'quota_ledger_unavailable'
            if reason:return reason
        if not self.config['enabled']:return 'configuration_disabled'
        if self.config_loader:
            try:
                if self.config_loader()!=self.config:return 'configuration_changed'
            except (ValueError,OSError):return 'configuration_invalid'
        if abs((time.time()-self.clock_wall)-(__import__('app.collection.current_clock',fromlist=['continuous']).continuous()-self.clock_mono))>120:return 'clock_continuity_unknown'
        worker=self.workers.get('the_odds_api')
        if worker and hasattr(worker,'ledger'):
            if prepared is not None:return prepared['ledger_reason']
            try:reason=worker.ledger.recovery_reason(worker.window_loader())
            except (ValueError,OSError):return 'reset_window_evidence_unverified'
            if reason:return reason
        return None

    async def refresh_aggregate(self,sports,identity,reference=False):
        from app.dashboard.current_state import SelectionError
        from .current_policy import SPORTS
        from .current_quota import QuotaStop
        if not isinstance(sports,list) or not sports or len(sports)!=len(set(sports)) or set(sports)-set(SPORTS):raise SelectionError(400,'scope_invalid','Choose supported sports for this refresh.')
        worker=self.workers.get('the_odds_api')
        if not self.dispatch or worker is None or worker.closed:raise SelectionError(409,'aggregate_stopped','Start a fresh runtime before refreshing a stopped source.')
        if candidate()[0]!=self.digest:raise SelectionError(409,'candidate_changed','Reopen Predict to load the current revision.')
        try:await worker.refresh(sports,identity,reference=reference)
        except QuotaStop as exc:raise SelectionError(409,str(exc),'Refresh blocked: '+str(exc).replace('_',' ')+'.') from None

    async def recover(self, runtime, digest):
        from app.dashboard.current_state import SelectionError
        async with self._control_lock:
            if runtime!=self.runtime_id or digest!=self.digest:
                raise SelectionError(409,'runtime_conflict','Status changed; inspect the current runtime before recovery.')
            try:
                reason=self.recovery_reason()
            except (ValueError,OSError):reason='reset_window_evidence_unverified'
            if reason:raise SelectionError(409,reason,'Recovery blocked: '+reason.replace('_',' ')+'.')
            actual,_=candidate()
            if actual!=self.digest:raise SelectionError(409,'candidate_changed','Application changed; reopen with the current candidate.')
            from .current_policy import validate
            validate(self.config)
            # Revoke and clean up before acquiring a new identity. No source
            # authority, quota, due time or reservations are reset.
            await self._close()
            if not self.cleanup_complete:raise SelectionError(409,'cleanup_safety_unresolved','Cleanup failed; ownership remains held.')
            reason=self.recovery_reason()
            if reason:raise SelectionError(409,reason,'Recovery blocked after cleanup: '+reason.replace('_',' ')+'.')
            if candidate()[0]!=self.digest:raise SelectionError(409,'candidate_changed','Application changed during cleanup; reopen with the current candidate.')
            self.runtime_id=str(uuid4());self.started=False;self.closed=False;self._source_close_started=False
            self.cleanup_complete=False;self.attempt=None;self.workers={};self.tasks={};self.client_cleanup_tasks={};self.watchdog=None
            self.states=self.initial_state()['source_status'];self.peak_rss=0;self.sampled_rss=None;self.stop_reason=None
            self.clock_wall,self.clock_mono=time.time(),__import__('app.collection.current_clock',fromlist=['continuous']).continuous()
            self.store.commit(self.initial_state())
            await self.start(self.store)
            if not self.dispatch:raise SelectionError(409,'ownership_or_authority_unavailable','Fresh runtime could not obtain exclusive ownership or authority.')
            return self.status()

    async def recover_accounting(self, runtime, digest, recovery_id, covered_attempts):
        """Explicit owned accounting control; native workers keep running."""
        from app.dashboard.current_state import SelectionError
        from .current_quota import QuotaStop
        from .current_account_recovery import observe_and_activate
        async with self._control_lock:
            if runtime!=self.runtime_id or digest!=self.digest:
                raise SelectionError(409,'runtime_conflict','Inspect the current runtime before accounting recovery.')
            if candidate()[0]!=digest:raise SelectionError(409,'candidate_changed','Reopen the current application revision.')
            if self.closing or self.closed or self.cleanup_errors or not self.dispatch or self.ownership.file is None:
                raise SelectionError(409,'cleanup_safety_unresolved','Accounting recovery requires a running owned service with safe cleanup.')
            if self.sampled_rss is not None and self.sampled_rss>=self.config['rss_bytes']:
                raise SelectionError(409,'rss_cap','The service reached its memory limit.')
            if self.config_loader and self.config_loader()!=self.config:
                raise SelectionError(409,'configuration_changed','Source configuration changed.')
            worker=self.workers.get('the_odds_api')
            task=self.tasks.get('the_odds_api')
            if worker is None or worker.closed or worker.acquisition_lock.locked() or task and not task.done():
                raise SelectionError(409,'recovery_active_transport','Wait for affected aggregate transport cleanup.')
            if self.states['novig'].get('reason_code')=='aggregate_paused':
                raise SelectionError(409,'aggregate_explicitly_paused','The owner paused this source.')
            if abs((time.time()-self.clock_wall)-(__import__('app.collection.current_clock',fromlist=['continuous']).continuous()-self.clock_mono))>120:
                raise SelectionError(409,'clock_continuity_unknown','Inspect the clock discontinuity.')
            async with worker.acquisition_lock:
                try:
                    await observe_and_activate(worker.ledger,self.ownership,digest,covered_attempts,recovery_id,
                                               window_loader=worker.window_loader)
                except QuotaStop as exc:
                    raise SelectionError(409,str(exc),'Accounting recovery blocked: '+str(exc).replace('_',' ')+'.') from None
                worker.prepared=False;worker.bootstrapped=False
            self.tasks['the_odds_api']=asyncio.create_task(worker.run(),name='predict-aggregate-recovered')
            return self.status()


def prepare_catalog(inventory, venue, cat, *, share_metadata=False):
    """Detached catalog preparation; caller owns ingress serialization."""
    def detach(value):
        if not share_metadata:return deepcopy(value)
        # Enrichment replaces row fields; immutable nested source metadata and
        # previous bindings are read-only. Detach every row that it can update.
        return dict(value,events=[dict(e) for e in value['events']],markets=[dict(m) for m in value['markets']])
    cats = {source:detach(value) for source,value in inventory.items() if source!=venue}
    cats[venue]=detach(cat)
    # Occurrence evidence supplies season/stage before predicate binding.
    # Each native source must remain usable without the other catalog.
    from .current_occurrence import annotate as occurrence
    from .v1_comparison import annotate
    occurrence(cats[venue],venue)
    proven={e['id'] for e in cats[venue]['events'] if e.get('current_occurrence_binding')}
    blocked=[m for m in cats[venue]['markets'] if m['event_id'] in proven
             and m.get('v1_raw_binding',{}).get('status')=='IDENTITY_BLOCKED']
    if blocked:
        annotate(dict(cats[venue],markets=blocked),venue,policy='manual-comparison-2',share_metadata=share_metadata)
    occurrence(cats[venue],venue)
    if 'kalshi' in cats and 'polymarket_us' in cats:
        from .admission_enrichment import share_games
        from .v1_comparison import annotate
        share_games(cats['polymarket_us'],cats['kalshi'],share_metadata=share_metadata)
        annotate(cats['polymarket_us'],'polymarket_us',policy='manual-comparison-2',share_metadata=share_metadata)
        occurrence(cats['polymarket_us'],'polymarket_us')
    return cats
