"""Automatic source-owning current provider, independent of browser lifetimes."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import time
from uuid import uuid4
from .current_policy import load, validate, candidate, consume, ROOT, VERSION, APP_RUNNING_DURATION, aggregate_scope
from .local_ownership import LocalOwnership
from .current_sink import LatestStateSink, utc
from app.dashboard.current_state import unavailable
from app.dashboard.current_contract import packed


class CurrentService:
    allow_synthetic = False

    def __init__(self, config=None, *, directory=None, ownership=None, worker_factory=None, evidence=None, aggregate_factory=None, config_loader=None):
        self.config = load() if config is None else validate(config)
        self.directory = Path(directory) if directory else ROOT/'.local/predict-current'
        self.ownership = ownership or LocalOwnership()
        self.worker_factory = worker_factory
        self.evidence = evidence
        self.aggregate_factory = aggregate_factory
        self.config_loader = config_loader
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
        self.sink = LatestStateSink(store, self.initial_state(), self.config)
        if not self.issues:
            from .current_admin import retained_issues
            try:self.issues=retained_issues(self)
            except (ValueError,OSError,TypeError,RecursionError):
                self.issue('service','local_defect','issue_retention_invalid')
        if not self.config['enabled']:
            for venue in ('kalshi','polymarket_us','novig','prophetx'): self.source_state(venue,'stopped','Native service is disabled in operational configuration.')
            return
        try:
            self.ownership.acquire(self.runtime_id)
            self.digest, _ = candidate()
            self.attempt = consume(self.directory, self.runtime_id, self.config, self.digest)
        except (ValueError, OSError):
            if self.ownership.file: self.ownership.release()
            for venue in ('kalshi','polymarket_us','novig','prophetx'): self.source_state(venue,'unavailable','Native acquisition ownership or operational authority is unavailable.')
            self.issue('service','ownership','ownership_or_authority_unavailable')
            return
        self.deadline = float('inf') if self.config['duration_seconds']==APP_RUNNING_DURATION else time.monotonic()+self.config['duration_seconds']
        self.dispatch = True
        from .current_native import NativeWorker
        factory = self.worker_factory or NativeWorker
        for venue in ('kalshi','polymarket_us'):
            self.workers[venue] = factory(self,venue)
            self.tasks[venue] = asyncio.create_task(self.run_worker(venue), name='predict-current-'+venue)
        if self.config['aggregate_enabled']:
            from .current_aggregate import AggregateScheduler
            self.workers['the_odds_api']=(self.aggregate_factory or AggregateScheduler)(self)
            self.tasks['the_odds_api']=asyncio.create_task(self.run_worker('the_odds_api'),name='predict-current-aggregate')
        self.watchdog = asyncio.create_task(self.watch(), name='predict-current-resources')

    async def run_worker(self, venue):
        try:
            await self.workers[venue].run()
        except asyncio.CancelledError: raise
        except Exception as exc:
            self.issue(venue, 'local_defect', type(exc).__name__)
            if venue=='the_odds_api':
                try:self.workers[venue].state('error','aggregate_worker_failed','Shared aggregate worker failed; native sources continue.')
                except Exception:self.cleanup_errors.append('aggregate_status_failed')
            else:self.source_state(venue, 'error', 'Native worker failed; this source is paused.')

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

    def source_state(self, venue, state, reason):
        if self.store is None or self.store.closed: return
        status = dict(state=state, reason_code='native_'+state, reason=reason, next_due_at=None)
        if self.states.get(venue)==status: return
        states = deepcopy(self.states); states[venue]=status
        try:
            self.sink.commit(self.row('source_health',venue,state='connected' if state=='available' else state), states)
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

    def catalog(self, venue, cat):
        if not self.dispatch: raise asyncio.CancelledError()
        cats = deepcopy(self.sink.reducer.inventory)
        cats[venue]=deepcopy(cat)
        # Occurrence evidence supplies season/stage before predicate binding.
        # Each native source must remain usable without the other catalog.
        from .current_occurrence import annotate as occurrence
        from .v1_comparison import annotate
        occurrence(cats[venue],venue)
        proven={e['id'] for e in cats[venue]['events'] if e.get('current_occurrence_binding')}
        blocked=[m for m in cats[venue]['markets'] if m['event_id'] in proven
                 and m.get('v1_raw_binding',{}).get('status')=='IDENTITY_BLOCKED']
        if blocked:
            annotate(dict(cats[venue],markets=blocked),venue,policy='manual-comparison-2')
        occurrence(cats[venue],venue)
        if 'kalshi' in cats and 'polymarket_us' in cats:
            from .admission_enrichment import share_games
            from .v1_comparison import annotate
            share_games(cats['polymarket_us'],cats['kalshi'])
            annotate(cats['polymarket_us'],'polymarket_us',policy='manual-comparison-2')
        generation=(self.sink.reducer.generation or 0)+1
        prior_books=set(self.sink.reducer.books)
        self.sink.commit(self.row('coverage_inventory',venue,inventory=cats,generation=generation,
                                 previous_generation=self.sink.reducer.generation),self.states)
        affected={key[0] for key in prior_books-set(self.sink.reducer.books)}
        for source in affected:
            worker=self.workers.get(source)
            if worker and not worker.closed and hasattr(worker,'request_resync'):
                self.source_state(source,'resyncing','Catalog identity changed; waiting for a fresh native image.')
                worker.request_resync()
        self.observation(venue,'catalog',dict(events=len(cat['events']),markets=len(cat['markets']),
            selected=len(cat.get('selection',{}).get('ids',[])),exclusions=self.sink.exclusions))

    def book(self, venue, book):
        self.books(venue,[book])

    def books(self, venue, books):
        if not self.dispatch: raise asyncio.CancelledError()
        states=deepcopy(self.states)
        book=max(books,key=lambda b:b['raw']['received_at'])
        states[venue]=dict(state='available',reason_code='native_image',reason='Native book images received.',
                           source_at=book['raw'].get('exchange_at'),received_at=book['raw']['received_at'],next_due_at=None)
        try:
            observations=[self.row('prediction_book',venue,book=b,packets=[]) for b in books]
            self.sink.commit(self.row('prediction_books',venue,observations=observations),states)
            self.states=states
        except Exception as exc:
            from app.diagnostics import failure
            failure(__name__, 'current_image_admission', exc)
            self.issue(venue,'local_defect',type(exc).__name__)
            self.degrade(venue,'Current image was rejected; a fresh complete image is required.')
            raise ValueError('current_admission_rejected') from None
        self.observation(venue,'book',dict(market_id=book['raw']['ref']['market_id'],sequence=book['sequence'],
            source_at=book['raw'].get('exchange_at'),received_at=book['raw']['received_at'],projected_at=self.store._state['projected_at'],
            quotes=len(self.store.index(self.store._state))))

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
        self.workers[venue].closed=True
        self.tasks[venue].cancel()
        done,pending=await asyncio.wait({self.tasks[venue]},timeout=self.config['cleanup_seconds'])
        if pending:
            self.issue(venue,'cleanup','worker_cleanup_timeout')
            self.cleanup_errors.append(venue+':cleanup_timeout')
            self.workers[venue].state('error','aggregate_cleanup_unresolved','Shared cleanup is unresolved; ownership remains held.') if venue=='the_odds_api' else self.source_state(venue,'error','Source cleanup is unresolved; ownership remains held.')
            return
        if not await self.cleanup_clients([venue]):
            if venue+':cleanup_failure' not in self.cleanup_errors:self.cleanup_errors.append(venue+':cleanup_failure')
            self.issue(venue,'cleanup','source_cleanup_unresolved')
            self.workers[venue].state('error','aggregate_cleanup_unresolved','Shared cleanup is unresolved; ownership remains held.') if venue=='the_odds_api' else self.source_state(venue,'error','Source cleanup is unresolved; ownership remains held.')
            return
        if venue=='the_odds_api':
            self.workers[venue].state('stopped','aggregate_paused','Shared aggregate acquisition paused. Persisted quota and next-due survive reopening.')
        else:self.source_state(venue,'stopped','Native source paused. Reopen the app for a fresh recorded runtime.')

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
            if self.closed or (self.cleanup_errors and not self.dispatch): return
            self.dispatch=False;self.closing=True
            # Revocation precedes task cancellation and client/socket cleanup.
            for worker in self.workers.values(): worker.closed=True
            current=asyncio.current_task()
            tasks=[t for t in self.tasks.values() if t is not current]
            if self.watchdog and self.watchdog is not current:tasks.append(self.watchdog)
            for task in tasks:task.cancel()
            done,pending=await asyncio.wait(tasks,timeout=self.config['cleanup_seconds']) if tasks else (set(),set())
            await self.cleanup_clients(list(self.workers))
            if pending:self.cleanup_errors.append('worker_cleanup_timeout')
            self.cleanup_errors=list(dict.fromkeys(self.cleanup_errors))[:16]
            for venue in ('kalshi','polymarket_us','novig','prophetx'):
                self.source_state(venue,'stopped' if not self.cleanup_errors else 'error',
                    (self.stop_reason or 'Updates stopped. Reopen for a fresh runtime.') if not self.cleanup_errors else 'Native cleanup unresolved; ownership remains held.')
            if self.store:
                self.store.leases.clear();self.store.clients.clear()
            self.cleanup_complete=not self.cleanup_errors
            if self.cleanup_complete:
                self.ownership.release()
                self.closed=True
            else:self.issue('service','cleanup','cleanup_safety_unresolved')
            self.closing=False
            self.observation('service','shutdown',dict(cleanup_complete=self.cleanup_complete,ownership_released=self.ownership.file is None))

    def status(self):
        from .current_admin import project
        raw = dict(schema=VERSION,runtime_id=self.runtime_id,candidate_digest=self.digest,
            attempt_id=self.attempt['attempt_id'] if self.attempt else None,dispatch_enabled=self.dispatch,
            ownership_held=self.ownership.file is not None,cleanup_complete=self.cleanup_complete,
            cleanup_errors=list(self.cleanup_errors),config=self.config,source_status=self.states,
            metrics={v:deepcopy(w.metrics) for v,w in self.workers.items()},peak_rss_bytes=self.peak_rss,
            sink=None if self.sink is None else dict(sequence=self.sink.sequence,**self.sink.metrics),
            exclusions=[] if self.sink is None else self.sink.exclusions,issues=deepcopy(self.issues),
            odds_api_requests=self.workers['the_odds_api'].metrics['requests'] if 'the_odds_api' in self.workers else 0,
            quota=self.workers['the_odds_api'].ledger.snapshot() if 'the_odds_api' in self.workers else None)

        return project(self, raw)

    def recovery_reason(self):
        if self.closing:return 'cleanup_in_progress'
        if self.cleanup_errors:return 'cleanup_safety_unresolved'
        if self.store is None or self.store.closed:return 'store_closed'
        if not self.config['enabled']:return 'configuration_disabled'
        if self.config_loader:
            try:
                if self.config_loader()!=self.config:return 'configuration_changed'
            except (ValueError,OSError):return 'configuration_invalid'
        if abs((time.time()-self.clock_wall)-(__import__('app.collection.current_clock',fromlist=['continuous']).continuous()-self.clock_mono))>120:return 'clock_continuity_unknown'
        worker=self.workers.get('the_odds_api')
        if worker and hasattr(worker,'ledger'):
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
            self.runtime_id=str(uuid4());self.started=False;self.closed=False
            self.cleanup_complete=False;self.attempt=None;self.workers={};self.tasks={};self.client_cleanup_tasks={};self.watchdog=None
            self.states=self.initial_state()['source_status'];self.peak_rss=0;self.sampled_rss=None;self.stop_reason=None
            self.clock_wall,self.clock_mono=time.time(),__import__('app.collection.current_clock',fromlist=['continuous']).continuous()
            self.store.commit(self.initial_state())
            await self.start(self.store)
            if not self.dispatch:raise SelectionError(409,'ownership_or_authority_unavailable','Fresh runtime could not obtain exclusive ownership or authority.')
            return self.status()
