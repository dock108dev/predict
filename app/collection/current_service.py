"""Automatic source-owning current provider, independent of browser lifetimes."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import time
from uuid import uuid4
from .current_policy import load, candidate, consume, ROOT, VERSION
from .local_ownership import LocalOwnership
from .current_sink import LatestStateSink, utc
from app.dashboard.current_state import unavailable
from app.dashboard.current_contract import packed


class CurrentService:
    allow_synthetic = False

    def __init__(self, config=None, *, directory=None, ownership=None, worker_factory=None, evidence=None):
        self.config = load() if config is None else __import__('app.collection.current_policy',fromlist=['validate']).validate(config)
        self.directory = Path(directory) if directory else ROOT/'.local/predict-current'
        self.ownership = ownership or LocalOwnership()
        self.worker_factory = worker_factory
        self.evidence = evidence
        self.runtime_id = str(uuid4())
        self.store = self.sink = None
        self.workers = {}
        self.tasks = {}
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
        self._close_lock = asyncio.Lock()
        self.states = self.initial_state()['source_status']

    def initial_state(self):
        raw = unavailable()
        raw.update(runtime_id=self.runtime_id, state='connecting')
        for venue in ('kalshi','polymarket_us'):
            raw['source_status'][venue] = dict(state='connecting', reason_code='native_connecting', reason='Connecting to the native feed.', next_due_at=None)
        for venue in ('novig','prophetx'):
            raw['source_status'][venue] = dict(state='unavailable', reason_code='aggregate_u4_pending', reason='Shared aggregate prices await U4.', next_due_at=None)
        return raw

    async def start(self, store):
        if self.started: return
        self.started = True
        self.store = store
        self.sink = LatestStateSink(store, self.initial_state(), self.config)
        if not self.config['enabled']:
            for venue in ('kalshi','polymarket_us'): self.source_state(venue,'stopped','Native service is disabled in operational configuration.')
            return
        try:
            self.ownership.acquire(self.runtime_id)
            self.digest, _ = candidate()
            self.attempt = consume(self.directory, self.runtime_id, self.config, self.digest)
        except (ValueError, OSError):
            if self.ownership.file: self.ownership.release()
            for venue in ('kalshi','polymarket_us'): self.source_state(venue,'unavailable','Native acquisition ownership or operational authority is unavailable.')
            self.issue('service','ownership','ownership_or_authority_unavailable')
            return
        self.deadline = time.monotonic()+self.config['duration_seconds']
        self.dispatch = True
        from .current_native import NativeWorker
        factory = self.worker_factory or NativeWorker
        for venue in ('kalshi','polymarket_us'):
            self.workers[venue] = factory(self,venue)
            self.tasks[venue] = asyncio.create_task(self.run_worker(venue), name='predict-current-'+venue)
        self.watchdog = asyncio.create_task(self.watch(), name='predict-current-resources')

    async def run_worker(self, venue):
        try:
            await self.workers[venue].run()
        except asyncio.CancelledError: raise
        except Exception as exc:
            self.issue(venue, 'local_defect', type(exc).__name__)
            self.source_state(venue, 'error', 'Native worker failed; this source is paused.')

    def observation(self, venue, kind, value):
        if self.evidence:
            self.evidence(dict(source=venue, kind=kind, at=utc(), value=value))

    def issue(self, venue, category, code):
        # Code is generated locally, never exception/provider text. Keep a
        # bounded rolling record rather than appending an operational history.
        code = str(code)
        if not code.replace('_','').replace(':','').isalnum() or len(code)>120: code='sanitized_failure'
        entry = dict(schema='predict-site-issue-1', issue_id=str(uuid4()), provider=venue,
            site='https://docs.kalshi.com' if venue=='kalshi' else 'https://docs.polymarket.us' if venue=='polymarket_us' else 'local',
            runtime_id=self.runtime_id, attempt_id=self.runtime_id, candidate_digest=self.digest,
            first_at=utc(), last_at=utc(), category=category, code=code,
            scope=dict(sports=self.config['sports'],families=self.config['families']),
            impact='Affected native path unavailable or unqualified; other source continues.',
            credits=0, next_action='Inspect the affected source and the bounded sanitized status before a fresh runtime.',
            retry_policy=self.config['backoff_seconds'])
        existing = next((i for i in self.issues if (i['provider'],i['category'],i['code'])==(venue,category,code)),None)
        if existing: existing['last_at']=entry['last_at']
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
            except OSError:
                if 'issue_persistence_failed' not in self.cleanup_errors:self.cleanup_errors.append('issue_persistence_failed')

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
        if not self.dispatch: raise asyncio.CancelledError()
        states=deepcopy(self.states)
        states[venue]=dict(state='available',reason_code='native_image',reason='Native book images received.',
                           source_at=book['raw'].get('exchange_at'),received_at=book['raw']['received_at'],next_due_at=None)
        try:
            self.sink.commit(self.row('prediction_book',venue,book=book,packets=[]),states)
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
            self.peak_rss=max(self.peak_rss,rss())
            if self.peak_rss>self.config['rss_bytes']:
                self.issue('service','resource','rss_cap'); await self.close(); return
            if time.monotonic()>=self.deadline:
                await self.close(); return
            await asyncio.sleep(1)

    async def pause(self, venue):
        if venue not in self.workers: raise ValueError('Native source is not running')
        self.workers[venue].closed=True
        self.tasks[venue].cancel()
        done,pending=await asyncio.wait({self.tasks[venue]},timeout=self.config['cleanup_seconds'])
        if pending:
            self.issue(venue,'cleanup','worker_cleanup_timeout')
            self.cleanup_errors.append(venue+':cleanup_timeout')
            self.source_state(venue,'error','Source cleanup is unresolved; ownership remains held.')
            return
        try:await asyncio.wait_for(self.workers[venue].close(),self.config['cleanup_seconds'])
        except Exception:
            if venue+':cleanup_failure' not in self.cleanup_errors:self.cleanup_errors.append(venue+':cleanup_failure')
            self.issue(venue,'cleanup','source_cleanup_unresolved')
            self.source_state(venue,'error','Source cleanup is unresolved; ownership remains held.')
            return
        self.source_state(venue,'stopped','Native source paused. Reopen the app for a fresh recorded runtime.')

    async def close(self):
        async with self._close_lock:
            if self.closed: return
            self.dispatch=False;self.closing=True
            # Revocation precedes task cancellation and client/socket cleanup.
            for worker in self.workers.values(): worker.closed=True
            current=asyncio.current_task()
            tasks=[t for t in self.tasks.values() if t is not current]
            if self.watchdog and self.watchdog is not current:tasks.append(self.watchdog)
            for task in tasks:task.cancel()
            done,pending=await asyncio.wait(tasks,timeout=self.config['cleanup_seconds']) if tasks else (set(),set())
            results=[]
            try:
                results=await asyncio.wait_for(asyncio.gather(*(w.close() for w in self.workers.values()),return_exceptions=True),self.config['cleanup_seconds'])
            except TimeoutError:self.cleanup_errors.append('client_cleanup_timeout')
            self.cleanup_errors += ['worker_cleanup_failure' for r in results if isinstance(r,BaseException)]
            if pending:self.cleanup_errors.append('worker_cleanup_timeout')
            self.cleanup_errors=list(dict.fromkeys(self.cleanup_errors))[:16]
            for venue in ('kalshi','polymarket_us'):
                self.source_state(venue,'stopped' if not self.cleanup_errors else 'error',
                    'Native service stopped. Reopen for a fresh runtime.' if not self.cleanup_errors else 'Native cleanup unresolved; ownership remains held.')
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
        return dict(schema=VERSION,runtime_id=self.runtime_id,candidate_digest=self.digest,
            attempt_id=self.attempt['attempt_id'] if self.attempt else None,dispatch_enabled=self.dispatch,
            ownership_held=self.ownership.file is not None,cleanup_complete=self.cleanup_complete,
            cleanup_errors=list(self.cleanup_errors),config=self.config,source_status=self.states,
            metrics={v:deepcopy(w.metrics) for v,w in self.workers.items()},peak_rss_bytes=self.peak_rss,
            sink=None if self.sink is None else dict(sequence=self.sink.sequence,**self.sink.metrics),
            exclusions=[] if self.sink is None else self.sink.exclusions,issues=deepcopy(self.issues),odds_api_requests=0)
