"""Owned retained bootstrap and explicit complete-admission outcomes.

The immutable candidate is separate from the installed Current state. Reads
never create jobs or acknowledge source receipt. The synchronous source API is
unchanged; only this opt-in retained reader uses the cancellable future.
"""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic, perf_counter
from uuid import uuid4
from aiohttp.payload import BytesPayload

from .current_contract import MAX_BYTES, packed, quotes_of, serialize_steps, stamp

VERSION = 'predict-retained-prices-1'
PAGE_ROWS = 1
PAGE_BYTES = 256 * 1024
MAX_ROWS = 16000
JOB_SECONDS = 300
MAX_REBASES = 4


class PriceReader(BytesPayload):
    """A bounded page lease through EOF/disconnect/timeout/Stop."""
    def __init__(self, owner, body, request):
        if owner.closed or owner.readers>=owner.MAX_READERS:raise ValueError('Retained reader capacity')
        super().__init__(body,content_type='application/json')
        self.owner=owner;self.job=owner.latest;self.closed=False;self.writing_task=None
        self.task=getattr(request,'task',None);self.callback=lambda _:self.release()
        if self.task is not None:self.task.add_done_callback(self.callback)
        self.timer=asyncio.get_running_loop().call_later(10,self.abort)
        owner.payloads.add(self);owner.readers+=1
        owner.metrics['maximum_readers']=max(owner.metrics['maximum_readers'],owner.readers)

    def release(self):
        if self.closed:return
        self.closed=True;self.timer.cancel()
        if self.task is not None:self.task.remove_done_callback(self.callback)
        self.owner.readers-=1;self.owner.payloads.discard(self)
        self.task=None;self.job=None;self._value=b''

    def abort(self):
        task=self.writing_task;self.release()
        if task is not None and task is not asyncio.current_task() and not task.done():task.cancel()

    async def close(self):self.release()

    async def write(self, writer):await self.write_with_length(writer,None)

    async def write_with_length(self, writer, content_length):
        self.writing_task=asyncio.current_task()
        try:
            async with asyncio.timeout(10):
                length=len(self._value) if content_length is None else min(content_length,len(self._value))
                for offset in range(0,length,65536):
                    if self.closed or self.owner.closed or self.owner.latest is not self.job:
                        raise ConnectionResetError('Retained page revoked')
                    await writer.write(self._value[offset:offset+65536]);await asyncio.sleep(0)
        finally:self.release()


@dataclass(frozen=True)
class AdmissionOutcome:
    status: str
    generation_id: str
    input_epoch: int | None = None
    state_revision: int | None = None
    error: str | None = None

    def __bool__(self):
        # A queued future or rejection must never accidentally acknowledge.
        raise TypeError('Inspect the explicit admission status')


def progress():
    value=dict(discovery_status='validating_prices',discovered_prices=0,
        validated_prices=0,total_prices=None)
    for kind in ('singles','pairs'):
        value.update({name+'_'+kind:None if name in ('pending','total') else 0
            for name in ('discovered','ready','refused','pending','total')})
    return value


def rows_of(state):
    rows=[]
    from .u0_display import bounded_decimal
    for event in state['events']:
        for group in event['groups']:
            for outcome in group['outcomes']:
                for q in quotes_of(outcome):
                    original=q['original']
                    price=bounded_decimal(original['value']);units=original['units']
                    if (units not in ('decimal_odds','usd_per_contract','cents_per_contract') or
                        units=='decimal_odds' and price<=1 or units=='usd_per_contract' and not 0<=price<=1 or
                        units=='cents_per_contract' and not 0<=price<=100):
                        raise ValueError('Unsupported original numerical price')
                    if original['payout'] is not None and bounded_decimal(original['payout'])<=0:
                        raise ValueError('Invalid original payout')
                    clock=stamp(state['clock_at'])
                    if any(q['times'][k] is not None and stamp(q['times'][k])>clock for k in ('source_at','received_at','projected_at')):
                        raise ValueError('Original price clock ahead of input')
                    source=q['source']
                    rows.append(dict(id=q['id'],revision=q['revision'],venue=q['venue'],
                        native=dict(provider=source['provider'],event_id=source['native_event_id'],
                            market_id=source['native_market_id'],outcome_id=source['native_outcome_id'],
                            side=source['native_side'],quote_side=source['quote_side']),
                        original=deepcopy(original),times=deepcopy(q['times']),
                        event={k:event[k] for k in ('id','title','league','start_at')},
                        market=group['market'],period=group['period'],selection=outcome['label']))
    if len(rows)>MAX_ROWS or len({r['id'] for r in rows})!=len(rows):
        raise ValueError('Retained price inventory conflict')
    # Leave 8 KiB per page for the bounded policy/progress/identity envelope.
    if any(len(packed(rows[start:start+PAGE_ROWS]))>PAGE_BYTES-8192 for start in range(0,len(rows),PAGE_ROWS)):
        raise ValueError('Retained page row capacity')
    return rows


class AdmissionOwner:
    """One active candidate, one latest pending descriptor, sixteen readers.

    Rows and candidate are bounded by Current's 64 MiB cap. No additional files
    or unbounded history; terminal descriptors release raw/rows immediately.
    Driver and reader deadlines are finite. A disconnected reader releases only
    its lease: other readers still depend on the server-owned generation.
    """
    MAX_READERS=16

    def __init__(self, store):
        self.store=store;self.active=None;self.pending=None;self.latest=None
        self.driver=None;self.closed=False;self.readers=0;self.payloads=set();self.iterator=None
        self.metrics=dict(started=0,completed=0,rejected=0,superseded=0,stopped=0,
            rebased=0,units=0,maximum_unit_seconds=0,maximum_readers=0)

    def _finish(self, job, status, error=None):
        if job['future'].done():return
        success=status=='success'
        job.update(status='ready' if success else {'rejection':'rejected','supersession':'superseded','stopped':'stopped'}[status],
            error=error,input_epoch=self.store._input_epoch if success else None,
            state_revision=self.store._state['state_revision'] if success else None)
        job['future'].set_result(AdmissionOutcome(status,job['generation_id'],
            job['input_epoch'],job['state_revision'],error))
        job['raw']=None
        job['previous']=None
        if not success:job['rows']=[]
        self.metrics[{'success':'completed','rejection':'rejected','supersession':'superseded','stopped':'stopped'}[status]]+=1

    def supersede(self):
        for job in (self.active,self.pending):
            if job is not None:self._finish(job,'supersession','new_complete_admission')
        self.pending=None

    def submit(self, raw):
        loop=asyncio.get_running_loop()
        if self.closed or self.store.closed or self.store._stopping or self.store._source_stopping:
            raise ValueError('Retained admission owner is stopping')
        # Bound and own caller input before an await, hashing the exact graph.
        body=packed(raw)
        if len(body)>MAX_BYTES:raise ValueError('Retained candidate byte capacity')
        source_hash=sha256(body).hexdigest();del body
        from app.comparison.estimated_policy import load
        policy=load()
        identity=(source_hash,policy.revision,self.store._input_epoch)
        if self.latest is not None and self.latest['identity']==identity and self.latest['status'] in ('pending','ready'):
            return self.latest['future']
        owned=deepcopy(raw)
        # Invalid identifiers are rejected before assigning publication identity.
        runtime=owned.get('runtime_id')
        if not isinstance(runtime,str) or not 1<=len(runtime)<=160:raise ValueError('Bounded runtime required')
        stamp(owned['clock_at'])
        return self._enqueue(owned,source_hash,policy,identity)

    def _enqueue(self, owned, source_hash, policy, identity, *, lease=None, original_clock=None, rebases=0):
        """Private transfer of an already defensively owned candidate graph."""
        loop=asyncio.get_running_loop();runtime=owned['runtime_id']
        self.supersede()
        job=dict(raw=owned,identity=identity,runtime_id=runtime,mode=owned.get('mode'),
            generation_id='retained:'+sha256((runtime+source_hash+policy.revision+str(uuid4())).encode()).hexdigest()[:48],
            policy=policy,status='pending',error=None,input_epoch=None,state_revision=None,
            input_clock_at=original_clock or owned['clock_at'],progress=progress(),rows=[],future=loop.create_future(),
            previous=self.store._state,epoch=self.store._input_epoch,deadline=lease or monotonic()+JOB_SECONDS,
            rebases=rebases,economic_deadline=None,rebase_at=None,
            received_at=perf_counter(),first_prices_at=None,first_estimate_at=None,complete_at=None)
        self.latest=self.pending=job
        job['future'].add_done_callback(lambda future:self._cancelled(job) if future.cancelled() else None)
        if self.driver is None or self.driver.done():self.driver=loop.create_task(self._drive())
        return job['future']

    def _cancelled(self, job):
        job.update(status='stopped',error='cancelled',raw=None,rows=[],previous=None,input_epoch=None,state_revision=None)
        if self.pending is job:self.pending=None

    def valid(self, job):
        from app.comparison.estimated_policy import load
        return (not self.closed and not self.store.closed and not self.store._stopping and not self.store._source_stopping
            and not job['future'].done() and self.latest is job
            and self.store._state['runtime_id']==job['previous']['runtime_id']
            and self.store._state['state_revision']==job['previous']['state_revision']
            and self.store._input_epoch==job['epoch'] and load().revision==job['policy'].revision)

    async def _consume(self, steps, job):
        self.iterator=steps
        try:
            while self.valid(job):
                if monotonic()>=job['deadline']:raise TimeoutError('Retained admission deadline')
                if job['economic_deadline'] is not None and self.store.validation_clock()>=job['economic_deadline']:
                    job['rebase_at']=self.store.validation_clock();return None
                tick=perf_counter()
                try:next(steps)
                except StopIteration as done:return done.value
                finally:self.metrics['maximum_unit_seconds']=max(self.metrics['maximum_unit_seconds'],perf_counter()-tick)
                self.metrics['units']+=1
                await asyncio.sleep(0)
            return None
        finally:steps.close();self.iterator=None

    def _observe(self, job, kind, value):
        p=job['progress']
        if kind=='group':
            quotes=[q for o in value['outcomes'] for q in quotes_of(o)]
            ready=sum(bool(q.get('calculations',{}).get('funded_estimate',{}).get('model_available')) for q in quotes)
            p['discovered_singles']+=len(quotes);p['ready_singles']+=ready;p['refused_singles']+=len(quotes)-ready
            p['pending_singles']=p['total_singles']-p['ready_singles']-p['refused_singles']
            if ready and job['first_estimate_at'] is None:job['first_estimate_at']=perf_counter()
        else:
            pairs,search=value
            p['discovered_pairs']+=search['evaluated_pairs'];p['ready_pairs']+=len(pairs)
            p['refused_pairs']+=search['evaluated_pairs']-len(pairs)
            if search['truncated']:raise ValueError('Retained fair pair coverage truncated')

    def _prices(self, job, group_state):
        rows=rows_of(group_state)
        if len(job['rows'])+len(rows)>MAX_ROWS:raise ValueError('Retained price inventory capacity')
        existing={r['id'] for r in job['rows']}
        if any(r['id'] in existing for r in rows):raise ValueError('Retained price identity conflict')
        job['rows'].extend(rows)
        p=job['progress'];p['discovered_prices']=p['validated_prices']=len(job['rows'])
        if rows and job['first_prices_at'] is None:job['first_prices_at']=perf_counter()

    async def _drive(self):
        try:
            while self.pending is not None:
                job=self.pending;self.pending=None;self.active=job;self.metrics['started']+=1
                try:
                    state=await self._consume(serialize_steps(job['raw'],allow_synthetic=self.store.provider.allow_synthetic,
                        estimate_policy=job['policy'],prices_only=True,prices_progress=lambda state:self._prices(job,state)),job)
                    if state is None:continue
                    rows=rows_of(state);del state
                    if len(packed(rows))>MAX_BYTES:raise ValueError('Retained row byte capacity')
                    if {r['id'] for r in rows}!={r['id'] for r in job['rows']}:raise ValueError('Retained complete inventory conflict')
                    job['rows']=rows
                    p=job['progress'];p.update(discovery_status='prices_complete',discovered_prices=len(rows),
                        validated_prices=len(rows),total_prices=len(rows),total_singles=len(rows),pending_singles=len(rows))
                    # Give already waiting read-only clients a turn before finance.
                    await asyncio.sleep(.01)
                    from .current_incremental import project_steps
                    p['discovery_status']='evaluating'
                    from .current_deadlines import next_deadline
                    job['economic_deadline']=next_deadline(job['raw'])
                    result=await self._consume(project_steps(job['raw'],job['previous'],self.store._fingerprints,
                        self.store._group_bytes,allow_synthetic=self.store.provider.allow_synthetic,
                        progress=lambda kind,value:self._observe(job,kind,value)),job)
                    if result is None:continue
                    deadline=next_deadline(result[0])
                    if deadline is not None and self.store.validation_clock()>=deadline:
                        job['rebase_at']=self.store.validation_clock();continue
                    if not self.valid(job):continue
                    if p['ready_singles']+p['refused_singles']!=p['total_singles']:raise ValueError('Single inventory conflict')
                    # No await between validation, complete install and outcome.
                    installed=self.store._install_admission(*result,deadline,owned_generation=job)
                    if not installed:raise ValueError('regressing_admission')
                    p.update(discovery_status='complete',total_pairs=p['discovered_pairs'],pending_pairs=0)
                    job['complete_at']=perf_counter();self._finish(job,'success')
                except asyncio.CancelledError:
                    self._finish(job,'stopped','owner_cancelled');raise
                except Exception as exc:
                    self._finish(job,'rejection',str(exc)[:160])
                finally:
                    fresh=None
                    if job['rebase_at'] is not None and self.valid(job):
                        if job['rebases']<MAX_REBASES and monotonic()<job['deadline']:
                            fresh=dict(job['raw'],clock_at=job['rebase_at'].isoformat())
                            lease=job['deadline'];original_clock=job['input_clock_at'];rebases=job['rebases']+1
                        else:self._finish(job,'rejection','eligibility_rebase_capacity')
                    if not job['future'].done():self._finish(job,'supersession','eligibility_changed' if fresh is not None else 'identity_changed')
                    self.active=None
                    if fresh is not None:
                        self.metrics['rebased']+=1
                        source_hash=sha256(packed(fresh)).hexdigest()
                        self._enqueue(fresh,source_hash,job['policy'],(source_hash,job['policy'].revision,self.store._input_epoch),
                            lease=lease,original_clock=original_clock,rebases=rebases)
        finally:self.active=None

    def page(self, *, settings_generation=0, page=0, generation_id=None):
        if type(settings_generation) is not int or not 0<=settings_generation<=9007199254740991:
            raise ValueError('Bounded settings generation required')
        if type(page) is not int or not 0<=page<(MAX_ROWS+PAGE_ROWS-1)//PAGE_ROWS:
            raise ValueError('Bounded retained page required')
        job=self.latest
        if job is None or (job['status']=='ready' and (job['runtime_id']!=self.store._state['runtime_id'] or job['input_epoch']!=self.store._input_epoch or job['state_revision']!=self.store._state['state_revision'])):
            if page>0 or generation_id is not None:raise ValueError('Retained generation changed')
            self.store.require_economic()
            job=self._complete_prices()
        if (page>0 and generation_id is None) or generation_id is not None and generation_id!=job['generation_id']:
            raise ValueError('Retained generation changed')
        # Server policy changes revoke progress before any page can be read.
        from app.comparison.estimated_policy import load
        if load().revision!=job['policy'].revision and job['status'] in ('pending','ready'):
            if job['future'] is not None and not job['future'].done():self._finish(job,'supersession','policy_changed')
            else:job.update(status='superseded',rows=[],input_epoch=None,state_revision=None,error='policy_changed')
        rows=job['rows'];start=page*PAGE_ROWS
        value=dict(schema=VERSION,mode=job['mode'],runtime_id=job['runtime_id'],generation_id=job['generation_id'],
            settings_generation=settings_generation,estimate_policy=job['policy'].to_dict(),status=job['status'],
            input_clock_at=job['input_clock_at'],validation_at=datetime.now(timezone.utc).isoformat(),
            input_epoch=job['input_epoch'],state_revision=job['state_revision'],error=job['error'],
            progress=deepcopy(job['progress']),rows=deepcopy(rows[start:start+PAGE_ROWS]),
            pagination=dict(page=page,page_size=PAGE_ROWS,total_rows=len(rows),has_more=start+PAGE_ROWS<len(rows)))
        if len(packed(value))>PAGE_BYTES:raise ValueError('Retained page byte capacity')
        return value

    def _complete_prices(self):
        """Already admitted ordinary state; no job or fresh financial clock."""
        state=self.store._state
        from app.comparison.estimated_policy import EstimatePolicy
        rows=rows_of(state);p=progress()
        quotes=[q for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]
        ready=sum(bool(q.get('calculations',{}).get('funded_estimate',{}).get('model_available')) for q in quotes)
        searches=[e.get('funded_pair_search',{}) for e in state['events']]
        pairs=sum(s.get('evaluated_pairs',0) for s in searches)
        pair_ready=sum(len(e.get('funded_pairs',[])) for e in state['events'])
        p.update(discovery_status='complete',discovered_prices=len(rows),validated_prices=len(rows),total_prices=len(rows),
            discovered_singles=len(rows),total_singles=len(rows),ready_singles=ready,refused_singles=len(rows)-ready,pending_singles=0,
            discovered_pairs=pairs,total_pairs=pairs,ready_pairs=pair_ready,refused_pairs=pairs-pair_ready,pending_pairs=0)
        job=dict(runtime_id=state['runtime_id'],mode=state['mode'],generation_id='retained:'+str(uuid4()),status='ready',error=None,
            policy=EstimatePolicy.from_dict(state['estimate_policy']),input_clock_at=state['clock_at'],
            input_epoch=self.store._input_epoch,state_revision=state['state_revision'],rows=rows,progress=p,
            raw=None,previous=None,future=None,identity=None)
        self.latest=job
        return job

    async def close(self):
        self.closed=True
        for reader in tuple(self.payloads):reader.abort()
        for job in (self.active,self.pending):
            if job is not None:self._finish(job,'stopped','stop')
        self.pending=None
        if self.latest is not None:
            self.latest.update(status='stopped',rows=[],raw=None,input_epoch=None,state_revision=None,error='stop')
        if self.driver is not None and not self.driver.done():
            self.driver.cancel();await asyncio.gather(self.driver,return_exceptions=True)
