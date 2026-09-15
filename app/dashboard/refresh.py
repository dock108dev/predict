"""Internal immutable handoff. Never deserialize user, wire, or saved-file input.

One snapshot/compute/result chain, no executor backlog. Capture retains the sole
mutable pipeline and DB connection. Compute owns its decoded objects and a finite
artifact compiler cache; only bytes cross the thread boundary.
"""
from hashlib import sha256
import pickle
from threading import Event
from time import monotonic

from app.arbitrage import Policy, wire
from app.dashboard.bounds import retained_bytes, DeadlineConnection
from app.dashboard.views import VENUES, side_labels, candidate_view
from app.storage.replay import detector_audit
from app.storage.store import Store, encoded

SNAPSHOT_BYTES=8*1024*1024
RESULT_BYTES=32*1024*1024
RETAINED_BYTES=64*1024*1024
class StopBudget:
    """Only lifecycle control crosses threads; set once before publishing Event."""
    def __init__(self):self.event=Event();self.at=None
    def stop(self,at):
        if not self.event.is_set():self.at=at;self.event.set()
    def deadline(self):return self.at+8.5 if self.event.is_set() else None



def freeze(state):
    counted={**state,'parents':vars(state['parents']),'matcher':vars(state['matcher']),'registry':vars(state['registry'])}
    if retained_bytes(counted)>RETAINED_BYTES:raise OverflowError('refresh snapshot memory bound')
    data=pickle.dumps(state,protocol=5)
    if len(data)>SNAPSHOT_BYTES:raise OverflowError('refresh snapshot byte bound')
    return data


def thaw_result(data):
    if len(data)>RESULT_BYTES:raise OverflowError('refresh result byte bound')
    return pickle.loads(data)


def compute(snapshot):
    entered=monotonic()
    state=pickle.loads(snapshot)
    unpacked=monotonic()
    t=state['evaluation_time'];rows=state['rows'];titles=state['titles']
    observations=state['observations']
    audit=detector_audit(state['parents'],state['matcher'],list(observations.values()),state['contexts'],
        evaluation_time=t,policy=Policy(max_receipt_age_seconds='10'),registry=state['registry'],
        quantity='1' if state['mode']=='live' else None,fill_grouping='single_fill_per_leg')
    detected=monotonic()
    labels=side_labels(rows)
    markets=[]
    for r in rows:
        quotes=[{**wire(o),'side_label':labels.get((r['key'],o.quote.outcome_id),o.quote.outcome_id)}
            for key,o in observations.items() if key[:2]==(r['venue'],r['native_market_id'])]
        markets.append(dict(key=r['key'],venue_key=r['venue'],venue=VENUES[r['venue']],
            event_id=r['native_event_id'],market_id=r['native_market_id'],title=titles[r['key']],
            event_title=state['event_titles'].get((r['venue'],r['native_event_id']),''),quotes=quotes,reasons=r['reasons']))
    view=dict(sequence=state['sequence'],at=t.isoformat(),markets=markets,
        candidates=[candidate_view(c,titles,labels) for c in audit['result']['candidates']],
        receipts=state['receipts'],raw_bytes=state['raw_bytes'],engine=audit['result']['engine'],
        freshness_seconds=10,mode=state['mode'],depth_available=state['depth_available'])
    viewed=monotonic()
    compiler=Store(None)
    artifacts={}
    values=[audit,view,*audit['result']['candidates']]
    for value,compiled in zip(values,compiler.compile_many(values)):
        artifacts[sha256(encoded(value)).hexdigest()]=compiled
    prepared=monotonic()
    result=dict(sid=state['sid'],view=view,audit=audit,artifacts=artifacts,
        receipt_ids=list(state['current_receipts'].values()),
        latest_input_at=max((o.quote.raw.received_at.isoformat() for o in observations.values()),default=None),
        oldest_input_at=min((o.quote.raw.received_at.isoformat() for o in observations.values()),default=None),
        sample=dict(start=state['start'],previous_start=state['previous_start'],
            inputs=state['inputs'],coalesced=max(0,state['inputs']-1),
            worker_entered=entered,decode_seconds=unpacked-entered,detector_seconds=detected-unpacked,
            view_seconds=viewed-detected,artifact_prepare_seconds=prepared-viewed,
            compute_seconds=prepared-entered,snapshot_bytes=len(snapshot),
            compiler_cache_bytes=compiler.tree_cache_bytes))
    size=retained_bytes(result)
    if size>RETAINED_BYTES:raise OverflowError('refresh result retained memory bound')
    result['sample']['result_retained_bytes']=size
    data=pickle.dumps(result,protocol=5)
    if len(data)>RESULT_BYTES:raise OverflowError('refresh result byte bound')
    return data


class RefreshStore(Store):
    def active(self,sid):
        # Controller exclusively owns lifecycle and waits for this worker before
        # finish. This worker only reads session scope; taking the capture row's
        # writer lock would serialize independent receipt and view transactions.
        row=self.db.execute('SELECT * FROM capture_session WHERE id=%s',(sid,)).fetchone()
        if not row or row['state']!='running':raise ValueError('session is not running')
        return row


class RefreshWriter:
    """One owning compute thread and one connection, closed on that same thread."""
    def __init__(self,connector,database,sid,mode,limits,stop_budget,metrics=None):
        self.connector=connector;self.database=database;self.sid=sid
        self.mode=mode;self.limits=limits;self.stop_budget=stop_budget
        self.metrics=metrics;self.pipeline=None

    def run(self,snapshot):
        from app.dashboard.pipeline import Pipeline
        from app.dashboard.bounds import DeadlineConnection
        entered=monotonic()
        state=pickle.loads(snapshot)
        if state['sid']!=self.sid:raise ValueError('refresh session mismatch')
        if self.stop_budget.deadline() is not None and monotonic()>=self.stop_budget.deadline():
            raise TimeoutError('compute drain budget exhausted')
        prepared=compute(snapshot);computed=monotonic()
        if self.pipeline is None:
            p=Pipeline(self.mode,self.limits,self.database);p.sid=self.sid
            db=self.connector(self.database)
            db.execute('SET statement_timeout=3000');db.execute('SET lock_timeout=1000')
            p.db=RefreshConnection(db,self.stop_budget);p.store=RefreshStore(p.db);self.pipeline=p
        p=self.pipeline;p.set_deadline(self.stop_budget.deadline())
        saved=p.persist_refresh(prepared)
        if self.metrics is not None:
            self.metrics.bindings.append(dict(kind='calculation',id='dashboard:'+str(state['sequence']),
                item_id='refresh:'+str(state['sequence']),returned=True))
            size=p.db.execute('SELECT pg_database_size(current_database()) n').fetchone()['n']
            if size>256*1024*1024:raise OverflowError('disposable database size guard')
        if saved:saved['sample'].update(compute_worker_wait_seconds=entered-state['start'],
            compute_and_prepare_seconds=computed-entered,compute_finished_at=computed)
        # The event-loop/capture side receives only immutable bytes.
        return pickle.dumps(saved,protocol=5)

    def close(self):
        if self.pipeline:self.pipeline.close_resources()


class RefreshConnection(DeadlineConnection):
    def __init__(self,db,budget):super().__init__(db);self.budget=budget
    def execute(self,*args,**kwargs):
        self.deadline=self.budget.deadline()
        return super().execute(*args,**kwargs)


def complete_sample(sample,submitted,computed,published,accepted):
    sample=dict(sample)
    sample.update(snapshot_seconds=submitted-sample['start'],
        scheduling_wait_seconds=sample['worker_entered']-submitted,
        compute_handoff_seconds=computed-sample['worker_entered'],
        persistence_wait_and_publication_seconds=published-computed,
        publication_seconds=published-(sample['start']+sample['latency']),
        published=accepted,completion_at=published)
    for label in ('input','oldest_input'):
        age=sample.get(label+'_to_persistence_seconds')
        sample[label+'_to_publication_seconds']=age+sample['publication_seconds'] if age is not None else None
    sample['latency']=published-sample['start']
    return sample
