"""One finite owner, bounded capture queue, one calculation and one DB worker.

No automatic collection on construction/restart; injected transports only.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import json
import math
import os
from pathlib import Path
from time import monotonic
from uuid import uuid4
from app.dashboard.bounds import CaptureQueue
from app.reference.adapter import OddsAPIReferenceAdapter, Bounds
from app.reference.records import Receipt, QuoteRevision, ReferenceGap, wire, unwire, as_of, EVENT, packed
from app.reference.fixtures import terms
from app.pricing.baseline import calculate
from app.opportunities.service import evaluate
from app.opportunities.fixtures import inputs
from app.collection.synthetic import knowledge, PredictionTransport, ReferenceTransport, DiscoveryTransport

DEFAULTS=dict(seconds=900,receipts=1024,ingress_bytes=16*1024*1024,item_bytes=64*1024*1024,
    storage_bytes=1024*1024*1024,database_bytes=2*1024*1024*1024,queue_items=48,queue_bytes=4*1024*1024,
    reference_requests=64,retries=3,request_timeout=3,prediction_poll=5,reference_poll=30,
    discovery_poll=30,calculation_poll=30,calculations=64,reference_records=256,journal_bytes=32*1024*1024)


def checked(values):
    if set(values)-set(DEFAULTS):raise ValueError('unknown bound')
    result={**DEFAULTS,**values}
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in result.values()):raise ValueError('finite positive bounds required')
    if any(v>DEFAULTS[k] for k,v in result.items()):raise ValueError('bounded synthetic profile ceilings exceeded')
    for k in ('receipts','ingress_bytes','item_bytes','storage_bytes','database_bytes','queue_items','queue_bytes','reference_requests','retries','calculations','reference_records','journal_bytes'):
        if type(result[k]) is not int:raise ValueError('integer capacity required')
    return result


def compute(records,books,template,target,cutoff):
    estimate=calculate(as_of(records,cutoff),target=target,cutoff=cutoff,estimated_at=cutoff)
    audit=None
    if len(books)==2:
        data=deepcopy(template);data['estimate']=estimate.export()
        data['as_of']=data['evaluated_at']=cutoff
        data['market']['books']=[books[k] for k in sorted(books)]
        audit=evaluate(data)
    return estimate,audit


class Session:
    def __init__(self,repo,clock,output,limits=None,transports=None):
        self.repo=repo;self.clock=clock;self.output=Path(output);self.limits=checked(limits or {})
        self.sid=str(uuid4());self.state='idle';self.reason=None;self.failed=False
        self.stop_event=asyncio.Event();self.queue=CaptureQueue(self.limits['queue_items'],self.limits['queue_bytes'])
        self.dbworker=ThreadPoolExecutor(1,thread_name_prefix='e6-persistence')
        self.calcworker=ThreadPoolExecutor(1,thread_name_prefix='e6-calculation')
        self.source,self.assessment,self.target=knowledge()
        self.records=[self.source];self.books={};self.health={k:dict(state='idle') for k in ('kalshi','polymarket_us','reference','discovery')}
        self.generation=0;self.view=None;self.last_snapshot=None;self.delivered=0;self.persisted=0;self.raw_bytes=0
        self.journal_bytes=0;self.calculations=0;self.last_calculation=0;self.task=None;self.pending_calc=None
        self.started=None;self.finished=None;self.accepting=False;self.storage_error=None;self.producers_closed=False
        self.inflight=False;self.transports=transports;self.high_records=0;self.high_tasks=0;self.exported=None

    async def db(self,fn,*args):
        # No cancellation-based claim of DB shutdown: await the actual callable.
        return await asyncio.shield(asyncio.get_running_loop().run_in_executor(self.dbworker,fn,*args))

    def journal(self,row):
        body=(packed(row)+'\n').encode()
        if self.journal_bytes+len(body)>self.limits['journal_bytes']:raise OverflowError('fallback_journal_capacity')
        with (self.output/(self.sid+'.journal.jsonl')).open('ab') as f:
            f.write(body);f.flush();os.fsync(f.fileno())
        self.journal_bytes+=len(body)

    def stop_request(self,reason,failed=False):
        if not self.stop_event.is_set():self.reason=reason
        self.failed|=failed;self.accepting=False;self.state='stopping';self.view=None
        self.stop_event.set()

    def health_change(self,source,state,reason,receipt=None):
        old=self.health[source]
        self.health[source]=dict(state=state,reason=reason,detected_at=self.clock.now(),wall_at=datetime.now().astimezone().isoformat(),
            last_success_at=self.clock.now() if state=='connected' else old.get('last_success_at'),receipt=receipt)
        if state!='connected' or old.get('state')!='connected':
            self.generation+=1;self.view=None

    def offer(self,kind,value,source):
        item=dict(id=str(uuid4()),kind=kind,value=value,source=source,at=self.clock.now(),wall_at=datetime.now().astimezone().isoformat())
        n=len(packed(item).encode())
        self.delivered+=1;self.raw_bytes+=n
        # Write-ahead evidence also retains the first capacity-rejected delivery.
        try:self.journal(dict(type='delivered',item=item))
        except Exception as exc:
            self.storage_error='fallback durability unknown: '+type(exc).__name__;self.stop_request(self.storage_error,True);raise
        try:
            if not self.accepting or self.delivered>self.limits['receipts'] or self.raw_bytes>self.limits['ingress_bytes'] or n>self.limits['item_bytes']:
                raise OverflowError('receipt_or_byte_capacity')
            self.queue.put_nowait(item)
        except (asyncio.QueueFull,OverflowError):
            self.stop_request('capture_capacity_exhausted; delivery retained in journal',True)
            raise
        return item

    def reference_sink(self,record):
        self.offer('reference',wire(record),'reference')
        if isinstance(record,Receipt): self.health_change('reference','awaiting_validation','new snapshot',record.id)
        if isinstance(record,QuoteRevision):
            ready=record.quote is not None and None not in record.quote.decimal_odds and not record.reasons
            self.health_change('reference','connected' if ready else 'invalid','validated snapshot' if ready else 'rejected latest snapshot',record.receipt_id)
        if isinstance(record,ReferenceGap):
            state='connected' if record.recovery=='fresh_snapshot' else 'disconnected'
            self.health_change('reference',state,record.reason,record.receipt_id)
            if record.reason in ('quota_exhausted','entitlement_stop','phase_schedule_identity_stop','payload_work_limit','request_bound_reached'):
                self.stop_request(record.reason,True)

    async def start(self):
        if self.state!='idle':raise RuntimeError('already started')
        self.output.mkdir(parents=True,exist_ok=True)
        cutoff=self.clock.now()
        self.template=await self.db(lambda:inputs(estimate=calculate(as_of([self.source],cutoff),target=self.target,cutoff=cutoff,estimated_at=cutoff)))
        # One captured metadata boundary, predating this session's delivered books.
        prior=await self.db(self.repo.refs.records)
        if len(prior)>=self.limits['reference_records']-8:raise ValueError('saved reference ledger capacity; use fresh environment')
        self.records=list(prior) if prior else [self.source]
        await self.db(self.repo.start,self.sid,self.source,self.limits)
        if self.transports is None:
            books={b['observation']['quote']['raw']['ref']['venue']:b for b in self.template['market']['books']}
            self.transports={k:PredictionTransport(k,b,self.clock) for k,b in books.items()}
            self.transports.update(reference=ReferenceTransport(self.clock),discovery=DiscoveryTransport())
        self.accepting=True;self.state='running';self.started=monotonic()
        self.task=asyncio.create_task(self.run());return self.sid

    async def pause(self,seconds):
        try:await asyncio.wait_for(self.stop_event.wait(),seconds)
        except TimeoutError:pass

    async def prediction(self,venue):
        transport=self.transports[venue];retries=0;gap=None
        while not self.stop_event.is_set():
            try:
                book=await asyncio.wait_for(transport.snapshot(),self.limits['request_timeout'])
                if self.stop_event.is_set():break
                item=self.offer('prediction',book,venue)
                self.health_change(venue,'connected','fresh full snapshot',item['id'])
                if gap:
                    self.offer('health',dict(reason='observed_recovery',prior_gap=gap,receipt_id=item['id'],unseen_interval='unknown'),venue);gap=None
                retries=0
                await self.pause(self.limits['prediction_poll'])
            except (OSError,TimeoutError):
                self.health_change(venue,'disconnected','transport failure')
                gap=self.offer('health',dict(reason='disconnect',last_success_at=self.health[venue].get('last_success_at'),outage_start=None),venue)['id'] if gap is None else gap
                retries+=1
                if retries>self.limits['retries']:self.stop_request(venue+' retries exhausted',True);break
                await self.pause(min(2**(retries-1),4))

    async def reference(self):
        b=self.limits
        self.adapter=OddsAPIReferenceAdapter(transport=self.transports['reference'],clock=self.clock,sink=self.reference_sink,
            source=self.source,assessment=self.assessment,session_id=self.sid,failure_journal=self.output/(self.sid+'.reference-failure.jsonl'),
            bounds=Bounds(max_requests=b['reference_requests'],max_seconds=b['seconds']+1,max_retries=b['retries'],request_timeout=b['request_timeout'],
                poll_seconds=b['reference_poll'],backoff_seconds=2,max_backoff_seconds=8,max_response_bytes=65536,max_total_bytes=b['ingress_bytes']))
        iterator=self.adapter.observe(EVENT)
        try:
            async for _ in iterator:
                if self.stop_event.is_set():break
        finally:
            await iterator.aclose()
        if not self.stop_event.is_set():self.stop_request('reference producer ended before session deadline',True)

    async def discovery(self):
        failures=0
        while not self.stop_event.is_set():
            try:
                row=await asyncio.wait_for(self.transports['discovery'].discover(),self.limits['request_timeout'])
                if self.stop_event.is_set():break
                self.offer('discovery',row,'discovery')
                valid=(row.get('event')==EVENT and row.get('resolved') and row.get('present') and row.get('phase')=='pregame' and row.get('start')==terms().scheduled_start.isoformat() and datetime.fromisoformat(self.clock.now())<terms().scheduled_start)
                self.health_change('discovery','connected' if valid else 'invalid','declared event confirmed' if valid else 'scope/schedule/phase changed')
                if not valid:self.stop_request('discovery scope/schedule/phase changed',True);break
                failures=0;await self.pause(self.limits['discovery_poll'])
            except (OSError,TimeoutError):
                self.health_change('discovery','disconnected','discovery transport failure');failures+=1
                self.offer('health',self.health['discovery'],'discovery')
                if failures>self.limits['retries']:self.stop_request('discovery retries exhausted',True);break
                await self.pause(1)

    async def consume(self):
        while not self.producers_closed or not self.queue.empty():
            try:item=await asyncio.wait_for(self.queue.get(),.1)
            except TimeoutError:continue
            try:
                self.inflight=True
                await self.db(self.repo.persist,item);self.persisted+=1
                if item['kind']=='reference':
                    if len(self.records)<self.limits['reference_records']:self.records.append(unwire(item['value']))
                    self.high_records=max(self.high_records,len(self.records))
                    if len(self.records)>=self.limits['reference_records']:self.stop_request('reference ledger capacity',True)
                if item['kind']=='prediction':self.books[item['source']]=item['value']
            except Exception as exc:
                self.storage_error=type(exc).__name__+': '+str(exc)
                self.journal(dict(type='primary_failure',error=self.storage_error,item=item))
                self.stop_request('primary persistence failure',True)
                # Remaining deliveries are already in the finite write-ahead journal.
                break
            finally:self.inflight=False;self.queue.task_done()

    async def calculate_loop(self):
        while not self.stop_event.is_set():
            await self.pause(min(1,self.limits['calculation_poll']))
            if self.stop_event.is_set():break
            if monotonic()-self.last_calculation<self.limits['calculation_poll']:continue
            if len(self.books)<2 or self.inflight or not self.queue.empty():continue
            if self.calculations>=self.limits['calculations']:self.stop_request('calculation capacity',True);break
            cutoff=self.clock.now();generation=self.generation
            context=dict(policy='e6-session-health-1',cutoff=cutoff,health=deepcopy(self.status()['health']))
            context['eligible']=all(h['state']=='connected' for h in context['health'].values())
            records=tuple(self.records);books=deepcopy(self.books)
            result=await asyncio.get_running_loop().run_in_executor(self.calcworker,compute,records,books,self.template,self.target,cutoff)
            await self.db(self.repo.save_calculation,result,context)
            self.calculations+=1;self.last_calculation=monotonic()
            estimate,audit=result
            self.last_snapshot=dict(estimate=estimate.data,audit=None if audit is None else audit.data,cutoff=cutoff,session_context=context)
            if context['eligible'] and generation==self.generation and self.state=='running':self.view=self.last_snapshot

    async def run(self):
        async def guarded(coro):
            try:await coro
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.journal(dict(type='task_failure',error=type(exc).__name__+': '+str(exc)))
                self.stop_request('worker failure: '+type(exc).__name__,True)
        consumer=asyncio.create_task(guarded(self.consume()))
        calculation=asyncio.create_task(guarded(self.calculate_loop()))
        producers=[asyncio.create_task(guarded(self.prediction(k))) for k in ('kalshi','polymarket_us')]
        producers += [asyncio.create_task(guarded(self.reference())),asyncio.create_task(guarded(self.discovery()))]
        self.high_tasks=6
        try:
            try:await asyncio.wait_for(self.stop_event.wait(),self.limits['seconds'])
            except TimeoutError:self.stop_request('declared duration reached')
            self.journal(dict(type='stopping',reason=self.reason,wall_at=datetime.now().astimezone().isoformat()))
            try:await self.db(self.repo.lifecycle,'stopping',dict(reason=self.reason,delivered=self.delivered,persisted=self.persisted))
            except Exception as exc:
                self.failed=True
                self.journal(dict(type='primary_stopping_failure',error=type(exc).__name__))
            # Reference adapter is cancellation-safe and journals its terminal gap.
            # Keep its sink open for that bounded control record during shutdown.
            self.accepting=True
            for task in producers:task.cancel()
            await asyncio.gather(*producers,return_exceptions=True)
            self.accepting=False
            for transport in self.transports.values():await asyncio.wait_for(transport.aclose(),self.limits['request_timeout'])
            self.producers_closed=True
            await consumer
            await calculation
            terminal='failed' if self.failed else 'completed'
            await self.db(self.repo.lifecycle,terminal,dict(reason=self.reason,delivered=self.delivered,persisted=self.persisted,
                queued=self.queue.qsize(),journal_only=self.delivered-self.persisted))
            self.exported=await self.db(self.repo.export,self.sid)
        except Exception as exc:
            self.failed=True;self.reason='shutdown/storage failure: '+type(exc).__name__
            self.journal(dict(type='fallback_failure',reason=self.reason,delivered=self.delivered,persisted=self.persisted,durability='journal only; primary state may remain unfinished'))
        finally:
            self.producers_closed=True;self.accepting=False;self.view=None
            await asyncio.gather(consumer,calculation,return_exceptions=True)
            self.dbworker.shutdown(wait=True);self.calcworker.shutdown(wait=True)
            self.finished=monotonic();self.state='failed' if self.failed else 'completed'
            (self.output/(self.sid+'.result.json')).write_text(packed(self.status()))

    async def stop(self):
        if self.task and not self.task.done():self.stop_request('manual Stop');await asyncio.shield(self.task)
        return self.status()

    def status(self):
        health=deepcopy(self.health)
        for name,h in health.items():
            at=h.get('last_success_at')
            h['age_seconds']=None if not at else max(0,(datetime.fromisoformat(self.clock.now())-datetime.fromisoformat(at)).total_seconds())
            if h['state']=='connected' and h['age_seconds'] is not None and h['age_seconds']>(60 if name=='discovery' else 30):h['state']='stale'
        healthy=all(h['state']=='connected' for h in health.values())
        view=self.view if healthy and self.state=='running' else None
        if view and (datetime.fromisoformat(self.clock.now())-datetime.fromisoformat(view['cutoff'])).total_seconds()>30:view=None
        return dict(id=self.sid,state=self.state,reason=self.reason,synthetic=True,event=EVENT,health=health,
            delivered=self.delivered,persisted=self.persisted,journal_only=self.delivered-self.persisted,
            calculations=self.calculations,queue=self.queue.qsize(),queue_high_items=self.queue.high_items,
            queue_high_bytes=self.queue.high_bytes,reference_ledger_high=self.high_records,worker_tasks=self.high_tasks,
            ingress_bytes=self.raw_bytes,journal_bytes=self.journal_bytes,logical_storage_bytes=self.repo.used,
            database_high_bytes=self.repo.high_db_bytes,wall_seconds=None if self.started is None else (self.finished or monotonic())-self.started,
            producers_closed=self.producers_closed,limits=self.limits,view=view,exported=self.exported,
            storage_error=self.storage_error,simulation_time=self.clock.now())
