"""13A isolated, bounded synthetic benchmark. Run via scripts/capture-benchmark.

Never imports live source instances, reads credentials or connects to owner storage.
Fixture adapters only relabel synthetic book normalization; production algorithms
and SQL remain the original Pipeline.book/evaluate/depth and Controller._consume.
"""
import argparse
import asyncio
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import statistics
import time
from unittest.mock import patch
import uuid

import psycopg
from psycopg.rows import dict_row
from app.dashboard.controller import DEFAULTS
from app.dashboard.pipeline import Pipeline, serial
from app.dashboard.diagnostics import Measurements, MeasuredController, reconcile
from app.storage import Store
from app.arbitrage import book_observations
from app.depth import book_ladders
from app.arbitrage_example import synthetic_inputs
from app.matching import Matcher
from app.matching_example import synthetic
from app.moneyline import MoneylineMatcher, rule_binding
from app.storage.store import hashed
from app.models.core import (Venue, OrderBook, OutcomeBook, Ladder, BookLevel,
                             Probability, Quantity, Depth, MarketState, BookSync)
from decimal import Decimal

BUDGET = dict(schema='13a-v1', evidence_class='synthetic', markets_per_venue=[2,4],
    scenarios=['ordinary','burst24','overflow40','slow','depth'], repeats=2,
    max_seconds_per_session=60, max_offered_per_session=128, max_receipts_per_session=512,
    raw_storage_bytes_per_session=128*1024*1024, database_guard_bytes=256*1024*1024,
    max_supervisor_seconds=900, estimated_queue_bytes='canonical serialized fixture; excludes Python heap',
    slow_receipt_delay_seconds=0.05, overflow_receipt_delay_seconds=0.1, network_requests=0,
    historical_arrival_timing='unknown; no historical timing replay',
    storage_guard='checked after each serial worker operation; overshoot limited to one bounded operation',
    total_sessions=24, depth_requests_per_depth_session=1)


def fixture(markets):
    if markets not in (2,4):
        raise ValueError('two or four markets per venue only')
    parents, _, obs, contexts, rows = synthetic_inputs()
    # Future synthetic start avoids wall-clock-dependent closure of the old example.
    parents = Matcher()
    parents.ingest([synthetic(e,v,names=('Atlanta Falcons','Pittsburgh Steelers'),
        league='NFL',start='2099-09-13T17:00:00+00:00') for e,v in [('ka',Venue.KALSHI),('pm',Venue.POLYMARKET_US)]])
    expanded=[]; ctx={}; books=[]
    for i in range(markets):
        for row,o in zip(rows,obs):
            row=deepcopy(row); old=row['native_market_id']; mid=f'{old}-{i}'
            oldkey=row['key']; key=json.loads(oldkey);key[-1]=mid
            row['key']=json.dumps(key,separators=(',',':'));row['native_market_id']=mid
            for k in ('ticker','id'):
                if row['native'].get(k)==old:row['native'][k]=mid
            row['id']='native-market-'+hashed(row['key'])[:24]
            row['parent_observation_hash']=next(v['hash'] for v in parents.snapshot['observations'].values() if v['key']==row['parent_key'])
            row['raw']['ref']['market_id']=mid
            row['rule_binding']=rule_binding(row['native'],row['venue'],row['scope'],row['profile'])
            row['hash']=hashed({k:v for k,v in row.items() if k!='hash'})
            expanded.append(row)
            # Unknown fee applicability/settlement retained in benchmark contexts.
            for side in row['sides']:
                ctx[(row['key'],side['native_id'])]=dict(venue=row['venue'],environment='synthetic',market_id=mid,product='event_contract',settlement_status='UNKNOWN')
            ladder=Ladder(levels=tuple(BookLevel(price=Probability(value=Decimal(p)),
                quantity=Quantity(value=Decimal('3'),unit='contracts')) for p in ('0.2','0.3','0.4','0.5')),depth=Depth.PARTIAL)
            outcomes=tuple(OutcomeBook(outcome_id=s['native_id'],bids=replace(ladder,levels=tuple(reversed(ladder.levels))) if row['venue']=='kalshi' else None,
                asks=ladder if row['venue']!='kalshi' else None) for s in row['sides'])
            raw=replace(o.quote.raw,ref=replace(o.quote.raw.ref,market_id=mid),
                received_at=datetime(2026,9,14,tzinfo=timezone.utc),exchange_at=None,
                source='synthetic:13a',json_text=json.dumps(dict(fixture='13a',market=mid,levels=['0.2','0.3','0.4','0.5'])))
            books.append(OrderBook(raw=raw,quantity_unit='contracts',outcomes=outcomes,state=MarketState.ACTIVE,sync=BookSync.SYNCHRONIZED))
    matcher=MoneylineMatcher();matcher.update(parents,expanded)
    return parents,matcher,ctx,expanded,books


def synthetic_observations(book, **context):
    assert book.raw.source=='synthetic:13a'
    return book_observations(book,**{**context,'environment':'synthetic','evidence_class':'synthetic'})


class MeasuredDB:
    def __init__(self, db, metrics):self.db=db;self.metrics=metrics
    def __getattr__(self,n):return getattr(self.db,n)
    def execute(self,*a,**kw):
        with self.metrics.timed('sql.execute'):
            return self.db.execute(*a,**kw)
    @contextmanager
    def transaction(self,*a,**kw):
        with self.metrics.timed('transaction.inclusive'):
            with self.db.transaction(*a,**kw):yield


class DiagnosticPipeline(Pipeline):
    def __init__(self,mode,limits,database,metrics,connector,markets,delay=0,fail_side=None):
        super().__init__(mode,limits,database)
        self.metrics=metrics;self.connector=connector;self.market_count=markets
        self.delay=delay;self.fail_side=fail_side;self.side_attempt=0

    def start(self):
        with patch('app.dashboard.pipeline.connect',self.connector):
            sid=super().start()
        self.db=MeasuredDB(self.db,self.metrics);self.store=Store(self.db)
        for name in ('receipt','calculation','metadata','put','event'):
            original=getattr(self.store,name)
            def wrapped(*a,_name=name,_fn=original,**kw):
                binding=None
                if _name in ('receipt','calculation','event'):
                    ident=a[1]
                    if _name=='event':
                        ident=str(uuid.uuid4());kw['event_id']=ident
                    binding=dict(kind=_name,id=ident,item_id=self.metrics.active,returned=False)
                    self.metrics.bindings.append(binding)
                with self.metrics.timed('store.'+_name):
                    if _name=='receipt':
                        if self.delay:
                            with self.metrics.timed('injected.receipt_delay'):time.sleep(self.delay)
                        self.side_attempt+=1
                        if self.fail_side==self.side_attempt:raise RuntimeError('injected receipt rollback')
                    from app.storage.replay import replay
                    def measured_replay(*a,**kw):
                        with self.metrics.timed('calculation.validation_replay'):
                            return replay(*a,**kw)
                    with patch('app.storage.replay.replay',measured_replay) if _name=='calculation' else nullcontext():
                        value=_fn(*a,**kw)
                if binding is not None:binding['returned']=True
                return value
            setattr(self.store,name,wrapped)
        return sid

    def synthetic_bootstrap(self):
        self.parents,self.matcher,self.contexts,self.rows,self.fixture_books=fixture(self.market_count)
        self.titles={r['key']:r['native']['title'] for r in self.rows}
        self.event_titles={}
        # Synthetic metadata setup; no venue discovery. Seed all books through the
        # original per-book pipeline, with separately identified bootstrap writes.
        for i,b in enumerate(self.fixture_books):
            self.metrics.active=f'bootstrap:{i}'
            self.book(b)
        return self.evaluate()

    def _save_observation(self,*a,**kw):
        with self.metrics.timed('receipt.normalize_and_persist'):
            return super()._save_observation(*a,**kw)

    def book(self,book):
        with patch('app.dashboard.pipeline.book_observations',synthetic_observations):
            return super().book(book)

    def evaluate(self):
        from app.storage.replay import detector_audit
        def measured(*a,**kw):
            with self.metrics.timed('detector.compute'):
                return detector_audit(*a,**kw)
        with self.metrics.timed('evaluate.total'), patch('app.dashboard.pipeline.detector_audit',measured):
            return super().evaluate()

    def depth(self,cid):
        # Synthetic mode normally holds AcquisitionLadders; benchmark holds books.
        # Convert those books with synthetic scope before using unchanged depth.
        books=self.books
        self.books={}
        for key,b in books.items():
            for n,l in enumerate(book_ladders(b,environment='synthetic',evidence_class='synthetic',source_time_semantics='unknown',locks_clear=None,units_verified=False)):
                self.books[(key,n)]=l
        try:return super().depth(cid)
        finally:self.books=books


class FixtureController(MeasuredController):
    def __init__(self,*a,scenario,**kw):
        super().__init__(*a,**kw);self.scenario=scenario

    async def _demo(self):
        # All scheduling is invented. No subscription or wire message counter.
        if self.scenario in ('stop_backlog','stop_depth','overload','byte_limit','receipt_limit','storage_limit','rollback','database_failure','finalization_failure'):
            return await self.repair_scenario()
        spec=schedule(self.scenario)
        depth_task=None
        for index,step in enumerate(spec):
            if self.stop_event.is_set():break
            await asyncio.sleep(step['quiet_seconds'])
            if self.stop_event.is_set():break
            if step['kind']=='depth':
                depth_task=asyncio.create_task(self.depth(self.view['candidates'][0]['id']));continue
            for _ in range(step['count']):
                n=len(self.metrics.items)
                b=self.worker.fixture_books[n%len(self.worker.fixture_books)]
                b=replace(b,raw=replace(b.raw,received_at=datetime.now(timezone.utc),
                    json_text=json.dumps(dict(fixture='13a',item=n,market=b.raw.ref.market_id))))
                item=('disconnect',('kalshi','synthetic disconnect')) if step['kind']=='disconnect' else ('book',b)
                size=len(json.dumps(serial(asdict(b)),sort_keys=True).encode()) if item[0]=='book' else 64
                self.offer_identified(f'item:{n:04}',item,size)
                if self.scenario=='overflow40' and n==0:
                    while 'worker_started_at' not in self.metrics.items[0] and not self.stop_event.is_set():
                        await asyncio.sleep(.001)
        if depth_task:
            await asyncio.gather(depth_task,return_exceptions=True)
        if not self.stop_event.is_set():
            # Fixed quiet period, not an altered drain loop.
            await asyncio.sleep(3)
            self.request_stop('Synthetic fixture finite input exhausted')

    async def repair_scenario(self):
        scenario=self.scenario
        def inject():
            p=self.worker
            if scenario=='receipt_limit':p.limits={**p.limits,'receipts':p.receipts+1}
            if scenario=='storage_limit':p.limits={**p.limits,'storage_bytes':p.raw_bytes+1}
            if scenario=='rollback':p.fail_side=p.side_attempt+2
            if scenario=='database_failure':
                with p.connector(p.database) as db:db.execute('SELECT pg_terminate_backend(%s)',(p.db.info.backend_pid,))
            if scenario=='finalization_failure':
                def broken(*a,**kw):raise RuntimeError('injected finalization failure')
                p.store.finish=broken
            if scenario=='stop_depth':
                original=p.depth
                def depth(cid):time.sleep(.3);return original(cid)
                p.depth=depth
        await self.work(inject)
        if scenario=='stop_depth':
            request=asyncio.create_task(self.depth(self.view['candidates'][0]['id']))
            await asyncio.sleep(.05)
            self.request_stop('Synthetic Stop during depth',initiator='owner')
            await asyncio.shield(request)
            return
        if scenario=='byte_limit':self.queue.byte_limit=128
        count=56 if scenario=='overload' else 41 if scenario=='stop_backlog' else 4
        for n in range(count):
            b=self.worker.fixture_books[n%len(self.worker.fixture_books)]
            b=replace(b,raw=replace(b.raw,received_at=datetime.now(timezone.utc),json_text=json.dumps(dict(fixture='13a',item=n,market=b.raw.ref.market_id))))
            self.offer_identified(f'item:{n:04}',('book',b),len(json.dumps(serial(asdict(b))).encode()))
        self.request_stop('Synthetic explicit Stop with backlog',initiator='owner')



def schedule(scenario):
    if scenario=='overflow40':return [dict(kind='book',quiet_seconds=.1,count=1),dict(kind='book',quiet_seconds=0,count=40)]
    if scenario=='burst40':return [dict(kind='book',quiet_seconds=.1,count=40)]
    if scenario=='burst24':return [dict(kind='book',quiet_seconds=.1,count=24)]
    rate=4 if scenario=='ordinary' else 10
    result=[dict(kind='book',quiet_seconds=1/rate,count=1) for _ in range(16)]
    result.insert(8,dict(kind='disconnect',quiet_seconds=.2,count=1))
    if scenario=='depth':result.insert(4,dict(kind='depth',quiet_seconds=0,count=0))
    return result


def summary(stages):
    result={}
    for name in sorted({r['stage'] for r in stages}):
        values=sorted(r['seconds'] for r in stages if r['stage']==name)
        result[name]=dict(n=len(values),total=sum(values),mean=statistics.mean(values),
            p50=statistics.median(values),p95=values[min(len(values)-1,int(.95*len(values)))],maximum=max(values))
    return result


async def trial(connector,markets,scenario,enabled=True):
    m=Measurements(enabled)
    ctl=FixtureController(m,lambda mode,limits:DiagnosticPipeline(mode,limits,'prediction_arb_13a',m,connector,markets,
        delay=.05 if scenario=='slow' else .1 if scenario=='overflow40' else 0),scenario=scenario)
    # Guard actual PostgreSQL size between bounded worker jobs.
    work=ctl.work
    async def guarded(fn,*a):
        value=await work(fn,*a)
        with m.timed('diagnostic.storage_guard'):
            with connector('prediction_arb_13a') as db:
                size=db.execute('SELECT pg_database_size(current_database()) n').fetchone()['n']
        if size>BUDGET['database_guard_bytes']:raise RuntimeError('disposable database size guard')
        return value
    ctl.work=guarded
    start=time.perf_counter()
    await ctl.start('synthetic',dict(seconds=60,markets=markets,receipts=512))
    try:
        await asyncio.wait_for(ctl.task,75)
        with connector('prediction_arb_13a') as db:
            sid=ctl.sid
            receipts=db.execute('SELECT id FROM receipt WHERE session_id=%s',(sid,)).fetchall()
            calculations=db.execute('SELECT id FROM calculation WHERE session_id=%s',(sid,)).fetchall()
            events=db.execute('SELECT id FROM coverage_event WHERE session_id=%s',(sid,)).fetchall()
            n=db.execute('SELECT count(*) n FROM quote_observation WHERE session_id=%s',(sid,)).fetchone()['n']
            state=db.execute('SELECT state,environment,evidence_class FROM capture_session WHERE id=%s',(sid,)).fetchone()
            size=db.execute('SELECT pg_database_size(current_database()) n').fetchone()['n']
            links=db.execute('SELECT calculation_id,receipt_id FROM calculation_receipt WHERE session_id=%s',(sid,)).fetchall()
            from app.storage.replay import replay
            saved=Store(db)
            durable={r['id']:r for r in db.execute('SELECT * FROM receipt WHERE session_id=%s',(sid,)).fetchall()}
            exact_bindings=0
            for calculation in db.execute('SELECT * FROM calculation WHERE session_id=%s',(sid,)).fetchall():
                audit=saved.get(calculation['audit_hash']);replay(audit)
                if audit['engine']=='detector-capture-1':
                    from app.storage.replay import observation_load
                    from app.storage.workflow import packet
                    used=set()
                    for observation in audit['input']['observations']:
                        pkt=packet(observation_load(observation))
                        matches=[]
                        for rid in calculation['receipt_ids']:
                            r=durable[rid]
                            if (r['venue'],r['market_id'],r['received_text'],r['raw_hash'])!=(pkt['venue'],pkt['market_id'],pkt['received_at'],sha256(pkt['raw']).hexdigest()):continue
                            if saved.get(r['normalized_hash'])['quotes']==pkt['normalized']['quotes']:matches.append(rid)
                        assert len(matches)==1,'exact input receipt identity'
                        used.update(matches);exact_bindings+=1
                    assert used==set(calculation['receipt_ids']),'no unrelated detector receipt bindings'
            accounting=reconcile(m,[r['id'] for r in receipts],[r['id'] for r in calculations],[r['id'] for r in events],n)
        elapsed=time.perf_counter()-start
        out=dict(markets_per_venue=markets,scenario=scenario,instrumentation_enabled=enabled,
            session_id=sid,elapsed_seconds=elapsed,stop_reason=ctl.reason,error=ctl.error,
            saved_state=state,remaining_queue=ctl.queue.qsize(),database_bytes=size,
            accounting=accounting,stages=m.stages,stage_summary=summary(m.stages),queue=m.queue_samples,
            calculation_receipt_bindings=links)
        out['replay_verified']=len(calculations)
        out['exact_detector_receipt_bindings_verified']=exact_bindings
        out['receipt_throughput']=sum(r['kind']=='book' and r['processed'] for r in m.items)/(max((r['completed_at'] for r in m.items if r['kind']=='book' and r['processed']),default=1)-min((r['worker_started_at'] for r in m.items if r['kind']=='book' and r['processed']),default=0))
        out['refreshes']=[{**r,'run_start':r['start']-m.origin,'during_collection':r['start']<ctl.stop_clock} for r in [*ctl.worker.refreshes,*ctl.refresh_samples]]
        out['tree_cache_retained_bytes']=ctl.worker.store.tree_cache_bytes
        out['retained_queue_bytes_high_water']=ctl.queue.high_bytes
        out['shutdown_seconds']=ctl.finalized_at-ctl.stop_clock
        out['producer_close_seconds']=ctl.producers_closed_at-ctl.stop_clock
        out['queue_high_water']=max((r['entries'] for r in m.queue_samples),default=0)
        out['queue_bytes_high_water']=max((r['estimated_bytes'] for r in m.queue_samples),default=0)
        out['oldest_item_age_max']=max([r['oldest_seconds'] for r in m.queue_samples]+[
            m.now()-r['offered_at'] for r in m.pending],default=0)
        items=m.items
        out['input_span_seconds']=items[-1]['offered_at']-items[0]['offered_at'] if len(items)>1 else 0
        out['input_rate_items_per_second']=(len(items)-1)/out['input_span_seconds'] if out['input_span_seconds'] else None
        out['gates_pass']=all(accounting['gates'].values()) and ctl.error is None
        if scenario=='overflow40':
            out['burst_preserved']=accounting['counts']['processed']==41 and accounting['counts']['rejected']==0 and accounting['counts']['unprocessed']==0
            out['gates_pass'] &= out['burst_preserved']
        out['shutdown_accounting']=ctl.worker.shutdown
        return out
    finally:await ctl.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--socket',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--faults',action='store_true');parser.add_argument('--repair',action='store_true');parser.add_argument('--smoke',action='store_true');parser.add_argument('--tests',action='store_true')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    socket=Path(args.socket).resolve()
    if socket.name!='socket' or not socket.parent.name.startswith('13a-'):
        raise ValueError('isolated 13a socket required')
    def connector(database='prediction_arb'):
        if not database.startswith('prediction_arb'):raise ValueError('project database required')
        return psycopg.connect(host=str(socket),port=55439,user='prediction_arb',dbname=database,
            autocommit=True,row_factory=dict_row,connect_timeout=5)
    with psycopg.connect(host=str(socket),port=55439,user='prediction_arb',dbname='postgres',autocommit=True) as db:
        db.execute('CREATE DATABASE prediction_arb_13a');db.execute('CREATE DATABASE prediction_arb')
    with connector('prediction_arb_13a') as db:
        Store(db).migrate()
        environment=dict(python=platform.python_version(),platform=platform.platform(),machine=platform.machine(),
            postgres=db.execute('SELECT version() v').fetchone()['v'],
            settings=db.execute("SELECT name,setting FROM pg_settings WHERE name IN ('fsync','synchronous_commit','full_page_writes','shared_buffers','max_connections')").fetchall())
    environment['timing_note']='Detailed timing enabled vs disabled retains identity ledger, SQL wrapper, scope adapters and storage guard in both arms.'
    micro=Measurements();t=time.perf_counter()
    for _ in range(10000):
        with micro.timed('micro'):pass
    environment['timing_context_seconds_per_call']=(time.perf_counter()-t)/10000
    (out/'environment.json').write_text(json.dumps(environment,indent=2)+'\n')
    if args.tests:
        import unittest
        from app import storage
        import app.dashboard.pipeline as pipeline
        import app.storage.store as store
        # Imported integration test aliases are resolved inside this patch.
        with patch.object(storage,'connect',connector),patch.object(pipeline,'connect',connector),patch.object(store,'connect',connector):
            suite=unittest.defaultTestLoader.discover('integration_tests')
            result=unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():raise SystemExit(1)
        return
    fixtures={str(n):dict(books=[serial(asdict(b)) for b in fixture(n)[-1]],rows=fixture(n)[3],
        schedules={s:schedule(s) for s in BUDGET['scenarios']}) for n in (2,4)}
    body=json.dumps(fixtures,sort_keys=True,indent=2)+'\n'
    (out/'fixtures.json').write_text(body)
    runs=[]
    matrix=[(n,s,True) for n in (2,4) for s in BUDGET['scenarios'] for _ in range(2)]
    matrix += [(n,'ordinary',False) for n in (2,4) for _ in range(2)]
    if args.repair:matrix += [(n,'burst40',True) for n in (2,4) for _ in range(2)]
    if args.smoke:matrix=[(4,'burst40',True),(4,'ordinary',True)] if args.repair else [(2,'overflow40',True)]
    if args.faults:matrix=[(n,s,True) for n in (2,4) for s in ('stop_backlog','stop_depth','overload','byte_limit','receipt_limit','storage_limit','rollback','database_failure','finalization_failure')]
    for n,s,enabled in matrix:
        print(f'Running synthetic {n} markets/venue {s} timing={enabled}',flush=True)
        result=asyncio.run(trial(connector,n,s,enabled));runs.append(result)
        (out/'measurements.json').write_text(json.dumps(dict(fixture_sha256=sha256(body.encode()).hexdigest(),
            budget=BUDGET,runs=runs),indent=2)+'\n')
        print(json.dumps(dict(gates=result['gates_pass'],counts=result['accounting']['counts'],elapsed=result['elapsed_seconds'])),flush=True)
        if args.faults:
            expected='interrupted' if s in ('overload','byte_limit') else 'failed' if s in ('receipt_limit','storage_limit','rollback') else 'running' if s in ('database_failure','finalization_failure') else 'complete'
            assert all(result['accounting']['gates'].values()),'fault accounting'
            assert result['saved_state']['state']==expected,'fault terminal outcome'
            assert result['shutdown_seconds']<=10 and result['producer_close_seconds']<=2,'fault shutdown bound'
        elif not result['gates_pass']:raise SystemExit('Capture accounting gate failed; evidence saved')
    print('Bounded accounting checks passed; view cadence requires separate gate analysis.',flush=True)

if __name__=='__main__':main()
