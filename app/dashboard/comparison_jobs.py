"""One cooperative complete Comparison job and one latest pending descriptor.

Financial engines run on the service loop, in quote/leg/pair units. No worker
survives cancellation. Anonymous bounded scratch files hold encoded rows rather
than a second rebuilt slate. Strict Current admission remains synchronous.
"""
import asyncio
from dataclasses import dataclass
from fractions import Fraction
from tempfile import TemporaryFile
from time import perf_counter

from .current_contract import MAX_BYTES, packed


@dataclass(frozen=True)
class Fragment:
    offset: int
    length: int


@dataclass(frozen=True)
class CalculatedBody:
    body: object  # bytes for synchronous consumers; sealed owner for HTTP
    clock_at: str


def body_steps(state, policy, filters, encoded_bodies=None):
    """Identical complete metrics, with just one occurrence graph alive at once."""
    from app.comparison.effective_policy import event_steps
    from app.comparison.metrics import snapshot_metrics
    from app.comparison.shared_templates import shared
    if not shared(state.get('comparison_profiles')):
        # Legacy projections duplicate rows in their groups. Keep that complete
        # wire shape through the same bounded fragment assembly below.
        compact=False
    else:compact=True
    with TemporaryFile() as scratch, TemporaryFile() as output:
        def retain(value):
            body=packed(value);offset=scratch.tell()
            if offset+len(body)>MAX_BYTES:raise ValueError('Comparison scratch byte capacity exceeded')
            scratch.write(body)
            return Fragment(offset,len(body))
        base=snapshot_metrics(dict(state,events=[]),copy_graph=False,**filters)
        base['estimate_policy']=policy.to_dict()
        rows=[];pairs=[];funded=[];selections=[];searches=[];pair_searches=[]
        for original in state['events']:
            # League is an acquisition-free read scope. Do not reconstruct
            # excluded occurrences for a selected-game settings request.
            if filters.get('league') and original['league']!=filters['league']:continue
            # Honor filters only in the read projection, not the financial slate.
            # Every supported occurrence still completes; no capacity omission.
            event=yield from event_steps(state,original,policy)
            local=snapshot_metrics(dict(state,events=[event],estimate_policy=policy.to_dict()),
                copy_graph=False,**filters)
            for row in local['rows']:
                value=row.get('funded_estimate')
                metric=row['net_ev']
                number=(None if value.get('buffered_return_percent') is None else Fraction(value['buffered_return_percent'])) if value is not None else (
                    None if not metric.get('eligible') else Fraction(int(metric['exact']['numerator']),int(metric['exact']['denominator'])))
                rows.append(dict(id=row['id'],basis_id=row['basis_id'] or 'unavailable',number=number,
                    basis=dict(conditioning=value['conditioning']) if value is not None else metric['basis'],
                    venue=row['venue'],fragment=retain(row)))
            for pair in local['pairs']:
                metric=pair['buffered_minimum_return']
                number=None if not metric.get('eligible') else Fraction(int(metric['exact']['numerator']),int(metric['exact']['denominator']))
                pairs.append(dict(id=pair['id'],category=pair['category'],number=number,fragment=retain(pair)))
            funded.extend(retain(p) for p in local.get('funded_pairs',[]))
            selections.extend(retain(s) for s in local['selections'])
            searches.extend(retain(s) for s in local['searches'])
            pair_searches.extend(retain(s) for s in local.get('funded_pair_searches',[]))
            del local,event
            yield ('encoded_occurrence',original['id'])
        def order(row):return (row['number'] is None,-row['number'] if row['number'] is not None else Fraction(0),row['id'])
        buckets={}
        for row in rows:buckets.setdefault(row['basis_id'],[]).append(row)
        groups=[];flat=[]
        for category,values in sorted(buckets.items()):
            values.sort(key=order);flat.extend(v['fragment'] for v in values)
            groups.append(dict(basis_id=category,row_ids=[v['id'] for v in values],basis=values[0]['basis'],
                venues=sorted({v['venue'] for v in values})) if compact else dict(basis_id=category,rows=[v['fragment'] for v in values]))
        pair_groups=[];flat_pairs=[]
        for category in sorted({p['category'] for p in pairs}):
            values=sorted((p for p in pairs if p['category']==category),key=order)
            fragments=[v['fragment'] for v in values];flat_pairs.extend(fragments)
            pair_groups.append(dict(basis_id=category,pairs=fragments))
        base.update(groups=groups,rows=flat,selections=selections,searches=searches,pairs=flat_pairs,pair_groups=pair_groups)
        if any('funded_pairs' in e for e in state['events']):
            base.update(funded_pairs=funded,funded_pair_searches=pair_searches)
        def write(data):
            if output.tell()+len(data)>MAX_BYTES:raise ValueError('Comparison body byte capacity exceeded')
            output.write(data)
        def graph(node):
            if isinstance(node,Fragment):
                scratch.seek(node.offset);remaining=node.length
                while remaining:
                    block=scratch.read(min(65536,remaining))
                    if not block:raise ValueError('Incomplete Comparison fragment')
                    write(block);remaining-=len(block)
                    yield ('encode_block',len(block))
            elif isinstance(node,dict):
                write(b'{')
                for index,key in enumerate(sorted(node)):
                    if index:write(b',')
                    write(packed(key)+b':');yield from graph(node[key])
                write(b'}')
            elif isinstance(node,list):
                write(b'[')
                for index,value in enumerate(node):
                    if index:write(b',')
                    yield from graph(value)
                write(b']')
            else:write(packed(node))
        yield from graph(base)
        output.seek(0)
        body=output.read() if encoded_bodies is None else encoded_bodies.adopt_file(output,output.seek(0,2))
        return CalculatedBody(body,state['clock_at'])


class Superseded(Exception):
    pass


class ComparisonJobs:
    """Bound requests, coalesce identical work, and shut down the actual iterator."""
    MAX_WAITERS=16

    def __init__(self):
        self.active=None;self.pending=None;self.driver=None;self.completed=None
        self.waiters=0;self.closed=False;self.completed_timer=None
        self.metrics=dict(started=0,completed=0,cancelled=0,coalesced=0,units=0,
            maximum_unit_seconds=0,maximum_active=0,maximum_pending=0)

    def _clear_completed(self):
        if self.completed_timer is not None:self.completed_timer.cancel();self.completed_timer=None
        if self.completed is not None:
            body=getattr(self.completed[1],'body',self.completed[1])
            if hasattr(body,'release'):body.release()
        self.completed=None

    def _reader_result(self,value):
        body=getattr(value,'body',value)
        if hasattr(body,'retain'):
            if body.closed:raise Superseded('Completed calculation expired')
            body.retain()
        return value

    def invalidate(self):
        self._clear_completed()
        for job in (self.active,self.pending):
            if job is not None:job['cancelled']=True

    async def read(self,key,factory,valid,alive=None):
        if self.closed:raise Superseded('Current store closed')
        if self.waiters>=self.MAX_WAITERS:raise Superseded('Calculation request capacity')
        if self.completed is not None and self.completed[0]==key and valid():return self._reader_result(self.completed[1])
        self.waiters+=1
        job=None
        try:
            for existing in (self.active,self.pending):
                if existing is not None and existing['key']==key and not existing['cancelled']:
                    job=existing;self.metrics['coalesced']+=1;break
            if job is None:
                self._clear_completed()
                job=dict(key=key,factory=factory,valid=valid,future=asyncio.get_running_loop().create_future(),
                         cancelled=False,waiters=0)
                if self.active is not None:self.active['cancelled']=True
                if self.pending is not None:
                    self.pending['cancelled']=True
                    if self.pending['waiters']==0:self.pending['future'].cancel()
                    else:self.pending['future'].set_exception(Superseded('Newer calculation requested'))
                    self.pending['factory']=None;self.pending['valid']=None
                self.pending=job;self.metrics['maximum_pending']=1
                if self.driver is None or self.driver.done():self.driver=asyncio.create_task(self._drive())
            job['waiters']+=1
            # A disconnected HTTP reader releases its ownership even when the
            # server's generic request handler is not configured to cancel it.
            # asyncio.wait never propagates a reader cancellation to coalesced
            # readers' shared future.
            while True:
                done,_=await asyncio.wait({job['future']},timeout=.05 if alive else None)
                if alive is not None and not alive():raise asyncio.CancelledError()
                if done:return self._reader_result(job['future'].result())
        finally:
            self.waiters-=1
            if job is not None:
                job['waiters']-=1
                if job['waiters']==0 and not job['future'].done():job['cancelled']=True

    async def _drive(self):
        while self.pending is not None:
            job=self.pending;self.pending=None;self.active=job
            self.metrics['started']+=1;self.metrics['maximum_active']=1
            steps=None
            try:
                steps=job['factory']()
                while True:
                    if self.closed or job['cancelled'] or not job['valid']():
                        raise Superseded('Calculation inputs or selection changed')
                    tick=perf_counter()
                    try:next(steps)
                    except StopIteration as done:
                        body=done.value
                        if not job['valid']():
                            owner=getattr(body,'body',body)
                            if hasattr(owner,'release'):owner.release()
                            raise Superseded('Calculation inputs changed before delivery')
                        self.completed=(job['key'],body)
                        owner=getattr(body,'body',body)
                        if hasattr(owner,'expires_at'):
                            self.completed_timer=asyncio.get_running_loop().call_later(
                                owner.manager.CACHE_SECONDS,self._clear_completed)
                        job['future'].set_result(body);self.metrics['completed']+=1
                        break
                    self.metrics['units']+=1
                    self.metrics['maximum_unit_seconds']=max(self.metrics['maximum_unit_seconds'],perf_counter()-tick)
                    # Timer readiness and selected Details have an opportunity
                    # between every measured safe financial unit.
                    # A short timer gives already-ready transports multiple
                    # turns to drain their bodies between financial units.
                    await asyncio.sleep(.001)
            except BaseException as error:
                self.metrics['cancelled']+=1
                if not job['future'].done():
                    if job['waiters']==0:job['future'].cancel()
                    else:job['future'].set_exception(error)
                if isinstance(error,asyncio.CancelledError):raise
            finally:
                if steps is not None:steps.close()
                # No obsolete generator, occurrence, prepared legs or scratch
                # file remains behind a cancelled async wrapper.
                job['factory']=None;job['valid']=None;self.active=None
                body=None

    async def close(self):
        self.closed=True;self.invalidate()
        if self.driver is not None and not self.driver.done():
            self.driver.cancel();await asyncio.gather(self.driver,return_exceptions=True)
        if self.pending is not None:
            if not self.pending['future'].done():self.pending['future'].set_exception(Superseded('Current store closed'))
            self.pending=None
