"""Ordinary bounded SQL catch-up and per-game calculation owner."""
import asyncio
import base64
from copy import deepcopy
from hashlib import sha256
import json
from threading import RLock
from pathlib import Path
from time import monotonic
from app.storage.current_games import GameStore,calculate,utc
from app.storage.store import connect,Store
from app.comparison.estimated_policy import load
from .current_storage_policy import SQL_BYTE_CAP,sql_usage,require_disk_space


def catch_up_segments(store,journal,records=8, *, deadline=None):
    """One shared record budget over stable per-path SQL checkpoints."""
    paths=journal.paths() if hasattr(journal,'paths') else (journal.path,)
    keys=set();count=0;backlog=0
    for path in paths:
        if count<records and (deadline is None or monotonic()<deadline):
            options={} if deadline is None else dict(deadline=deadline)
            changed,n=store.catch_up(path,records=records-count,**options)
            keys.update(changed);count+=n
        cursor=store.db.execute('SELECT byte_offset FROM current_import_cursor WHERE path=%s',(str(path.resolve()),)).fetchone()
        size=path.stat().st_size if path.exists() else 0
        offset=cursor['byte_offset'] if cursor else 0
        if offset>size:raise ValueError('journal_truncated')
        backlog+=size-offset
    return keys,count,backlog


class DatabaseIngressSink:
    """Cheap native ownership reducer. Durable source-local projection is separate."""
    def __init__(self,store,raw,config):
        from app.dashboard.session_projection import SessionProjection
        self.reducer=SessionProjection();self.store=store;self.config=config
        self.sequence=0;self.metrics=dict(admitted_observations=0,rejected_observations=0)
        self.exclusions=[];self.revisions={}
    def commit(self,row,states):
        from app.dashboard.current_contract import packed,snapshot_inputs
        # Aggregate wire bytes are already journaled separately. Count their
        # bounded size without passing bytes through the JSON metadata encoder.
        body=row.get('body') if row['type']=='current_aggregate' else None
        metadata={k:v for k,v in row.items() if k!='body'} if body is not None else row
        if body is not None and not isinstance(body,bytes):raise ValueError('Current aggregate body type')
        if len(packed(metadata))+(len(body) if body is not None else 0)>self.config['ingress_bytes']:
            raise ValueError('Current ingress observation capacity')
        if row['type'] not in ('current_aggregate','current_aggregate_batches'):
            observations=row['observations'] if row['type']=='prediction_books' else [row]
            from copy import copy
            candidate=copy(self.reducer)
            for name in ('books','health','sizes','metadata'):setattr(candidate,name,dict(getattr(self.reducer,name)))
            candidate.invalid=set(self.reducer.invalid)
            for observation in observations:
                if observation['type']=='prediction_book':
                    book=observation['book'];ref=book['raw']['ref']
                    market=next((m for m in candidate.inventory.get(row['source'],{}).get('markets',[]) if m['id']==ref['market_id'] and m['event_id']==ref['event_id']),None)
                    if market is None or ref['venue']!=row['source'] or book['sync']!='synchronized' or book['quantity_unit']!='contracts':raise ValueError('Unadmitted current book identity or units')
                    if {o['outcome_id'] for o in book['outcomes']}!={side['id'] for side in market['sides']}:raise ValueError('Incomplete current outcome set')
                    from app.dashboard.current_contract import bounded_decimal,stamp
                    stamp(book['raw']['received_at']);stamp(book['raw'].get('exchange_at'),True)
                    for outcome in book['outcomes']:
                        for side in ('asks','bids'):
                            ladder=outcome[side]
                            if ladder is None:continue
                            if len(ladder['levels'])>4096:raise ValueError('Current book level bound')
                            for level in ladder['levels']:
                                if not 0<=bounded_decimal(level['price']['value'])<=1 or bounded_decimal(level['quantity']['value'])<=0 or level['quantity']['unit']!='contracts':raise ValueError('Invalid current native level')
                candidate.reduce_observation(observation)
            self.reducer=candidate
        raw=snapshot_inputs(self.store._state);raw.update(source_status=deepcopy(states),clock_at=utc(),projected_at=utc(),state_revision=raw['state_revision']+1)
        if getattr(self.store,'_source_stopping',False):self.store.admit_shutdown_health(states)
        else:self.store.commit(raw)
        self.sequence+=1;self.metrics['admitted_observations']+=1
        return dict(service_sequence=self.sequence)


class DatabasePipeline:
    MAX_PENDING=4
    INGRESS_RECORDS=64
    INGRESS_SECONDS=1.0
    def __init__(self,service,selected):
        self.service=service;self.selected=selected;self.pending={};self.closed=False
        self.wake=asyncio.Event();self.queue_lock=RLock();self.generations={};self.generation_counter=0;self.active_scope=None
        self.task=None;self.error=None;self.failures=0;self.imported=0;self.backlog=None;self.busy=False
        self.sql_bytes=None;self.ingress_task=None;self.ingress_error=None;self.ingress_failures=0;self.ingress_busy=False
    async def start(self):
        self.ingress_task=asyncio.create_task(self.run_ingress(),name='predict-stored-ingress')
        self.task=asyncio.create_task(self.run(),name='predict-stored-games')
    def request(self,key,policy):
        with self.queue_lock:
            if self.closed:raise ValueError('saved_updates_stopped')
            ident=(key,policy.revision);scope=(key,getattr(policy,'benchmark_venue','pinnacle'))
            # New settings for the same visible occurrence supersede queued work.
            remove=[i for i,p in self.pending.items() if (i[0],getattr(p,'benchmark_venue','pinnacle'))==scope and i!=ident]
            if ident not in self.pending and len(self.pending)-len(remove)>=self.MAX_PENDING:raise ValueError('saved_calculation_queue_capacity')
            for i in remove:self.pending.pop(i)
            if ident not in self.pending:
                self.generation_counter+=1;self.generations[scope]=self.generation_counter
            self.pending[ident]=policy
            live={(k[0],getattr(p,'benchmark_venue','pinnacle')) for k,p in self.pending.items()}|{self.active_scope}
            self.generations={k:v for k,v in self.generations.items() if k in live}
        self.wake.set()
    def tick(self, *, ingress=True, import_only=False):
        from app.comparison.calculation_control import cancellation, CalculationStopped, checkpoint
        if self.closed:return 0
        with cancellation(lambda:self.closed), connect() as db:
            Store(db).migrate();s=GameStore(db)
            self.sql_bytes=sql_usage(db)
            if self.sql_bytes>=SQL_BYTE_CAP:raise ValueError('current_database_storage_cap')
            require_disk_space(Path(__file__).resolve().parents[2]/'.local/postgres')
            count=0
            if ingress:
                keys,count,self.backlog=catch_up_segments(s,self.service.journal,
                    records=self.INGRESS_RECORDS,deadline=monotonic()+self.INGRESS_SECONDS);self.imported+=count
                # Bootstrap allowlisted retained diagnostics without claiming wire bytes.
                if not getattr(self,'bootstrapped',False):
                    for path in self.service.retained_directory.glob('NFL.json'):
                        v=json.loads(path.read_text());body=json.dumps(v['replay']).encode()
                        r=dict(source='the_odds_api',kind='aggregate_batch',retained_at=v['received_at'],
                            value=dict(sport=v['sport'],received_at=v['received_at'],body_sha256=sha256(body).hexdigest(),body_b64=base64.b64encode(body).decode()))
                        keys.update(s.import_record(r))
                    self.bootstrapped=True
                for key in sorted(keys):
                    checkpoint()
                    s.project(key)
            if import_only:return count
            from app.storage.comparison_board import capture, saved
            policy=load()
            with self.queue_lock:jobs=dict(self.pending)
            # Selected/visible requests only. No calculation of an unselected slate.
            for key in self.selected[:self.MAX_PENDING]:jobs.setdefault((key,policy.revision),policy)
            for (key,_),p in jobs.items():
                if self.closed:break
                scope=(key,getattr(p,'benchmark_venue','pinnacle'))
                with self.queue_lock:
                    generation=self.generations.get(scope,0);self.active_scope=scope
                try:
                    snapshot=capture(s,key,p)
                except ValueError as exc:
                    if str(exc)=='board_occurrence_absent_or_ambiguous':
                        with self.queue_lock:self.pending.pop((key,p.revision),None)
                        continue
                    raise
                canonical=snapshot['projection']['inputs']['game_key']
                previous=saved(s,canonical,p)
                if previous and previous['input_version']==snapshot['input_version'] and not previous['superseded']:
                    with self.queue_lock:self.pending.pop((key,p.revision),None)
                    continue
                # Capture transaction has ended; finance never holds its locks.
                try:
                    with cancellation(lambda:self.closed):
                        result=calculate(snapshot)
                except CalculationStopped:
                    with self.queue_lock:self.active_scope=None
                    break
                with self.queue_lock:
                    allowed=not self.closed and generation==self.generations.get(scope,0)
                    _,published=s.publish(snapshot,result,allow_latest=allowed)
                    if self.pending.get((key,p.revision))==p:
                        if published:self.pending.pop((key,p.revision),None)
                        elif not self.closed:
                            # A changing native dependency may continuously
                            # refuse latest publication. Retain its exact job
                            # and generation, but let other visible jobs take
                            # their bounded turn before retrying it.
                            self.pending[(key,p.revision)]=self.pending.pop((key,p.revision))
                with self.queue_lock:self.active_scope=None
                break
        return count
    async def run(self):
        from app.comparison.calculation_control import CalculationStopped
        while not self.closed:
            try:
                self.busy=True;count=await asyncio.to_thread(self.tick,ingress=False)
                self.error=None;self.failures=0
            except CalculationStopped:
                if not self.closed:raise
                count=0
            except Exception as exc:
                self.error=type(exc).__name__+': '+str(exc)[:180];self.failures+=1
                if self.failures>=5:break
                count=0
            finally:self.busy=False
            try:await asyncio.wait_for(self.wake.wait(),timeout=0.05 if count else min(30,2**self.failures))
            except TimeoutError:pass
            self.wake.clear()
    async def run_ingress(self):
        from app.comparison.calculation_control import CalculationStopped
        while not self.closed:
            try:
                self.ingress_busy=True
                count=await asyncio.to_thread(self.tick,import_only=True)
                self.ingress_error=None;self.ingress_failures=0
                if count:self.wake.set()
            except CalculationStopped:
                if not self.closed:raise
                count=0
            except Exception as exc:
                self.ingress_error=type(exc).__name__+': '+str(exc)[:180];self.ingress_failures+=1
                if self.ingress_failures>=5:
                    self.closed=True;self.wake.set();break
                count=0
            finally:self.ingress_busy=False
            if not self.closed:await asyncio.sleep(0.05 if count else min(1,2**self.ingress_failures))
    async def close(self):
        with self.queue_lock:self.closed=True
        self.wake.set()
        # Do not cancel a thread while its SQL transaction owns a connection.
        tasks=[task for task in (self.task,self.ingress_task) if task is not None]
        if tasks:
            try:await asyncio.wait_for(asyncio.shield(asyncio.gather(*tasks)),timeout=self.service.config['cleanup_seconds'])
            except TimeoutError:return False
        return True
    def status(self):
        return dict(database='prediction_arb',socket='.local/pgsocket',schema='008_current_exact_clocks.sql',
            state='unavailable' if self.error or self.ingress_error else 'catching_up' if self.backlog else 'available',
            error=self.ingress_error or self.error,backlog_bytes=self.backlog,imported_records=self.imported,
            pending_calculations=len(self.pending),busy=self.busy or self.ingress_busy,sql_byte_cap=SQL_BYTE_CAP,sql_bytes=self.sql_bytes,
            observation_representation='parsed/redacted aggregate batches and reconstructed books',
            journal_byte_cap=getattr(self.service.journal,'total_byte_cap',self.service.journal.byte_cap),
            journal_segment_byte_cap=self.service.journal.byte_cap,finite_failure_limit=5)
