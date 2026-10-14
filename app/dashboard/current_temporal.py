"""Single owned temporal iterator, bounded supersession and atomic publication."""
import asyncio
from time import perf_counter
from .current_contract import stamp, snapshot_inputs


NO_INDEX=object()

def temporal_steps(previous, clock, policy_changed, known, sizes, allow_synthetic, *, indexed_deadline=NO_INDEX):
    """Age writable shells fairly, then drain the same financial projection."""
    from .current_incremental import aged, project_steps
    state=dict(previous,clock_at=clock.isoformat(),events=[])
    old_clock=stamp(previous['clock_at']);changed=policy_changed
    events={e['id']:dict(e,groups=[]) for e in previous['events']}
    groups={}
    from app.comparison.projection_batches import groups as fair_groups
    for batch in fair_groups(previous['events'],size=1):
        for event,group in batch:
            value,transition=aged(group,clock,old_clock,previous.get('comparison_profiles'),event)
            groups[(event['id'],group['id'])]=value;changed=changed or transition
            yield ('aged_group',group['id'])
    for original in previous['events']:
        event=events[original['id']]
        event['groups']=[groups[(original['id'],g['id'])] for g in original['groups']]
        state['events'].append(event)
    if changed:
        state['state_revision']+=1
        result=yield from project_steps(snapshot_inputs(state,copy_graph=False),previous,known,sizes,
            allow_synthetic=allow_synthetic,borrow_profiles=True)
    else:result=(state,known,sizes,set(),None)
    from .current_deadlines import next_deadline
    # Unchanged eligibility over the same immutable input cannot move a future
    # index. Reuse it until its actual boundary, then scan again.
    deadline=(indexed_deadline if not changed and indexed_deadline is not NO_INDEX
        and (indexed_deadline is None or clock<indexed_deadline) else next_deadline(result[0]))
    return (*result,deadline,changed)


class TemporalOwner:
    """One active job and one latest descriptor; harmless ticks coalesce.

    No staging/file authority is given to readers. Completion swaps all state
    owners together. Each job holds exactly the admitted immutable publication,
    whose epoch binds both legs and every native/profile/grid/matching revision.
    """
    def __init__(self,store):
        self.store=store;self.active=None;self.pending=None;self.driver=None
        self.closed=False;self.failure=None;self.iterator=None
        self.metrics=dict(started=0,completed=0,cancelled=0,units=0,
            maximum_unit_seconds=0,maximum_active=0,maximum_pending=0,slowest_unit=None)

    def request(self):
        store=self.store
        if self.closed or store.closed or (store._stopping or store._source_stopping):return
        from app.comparison.estimated_policy import load
        policy=load();key=(store._input_epoch,store._state['runtime_id'],policy.revision)
        if self.active is not None and self.active['key']==key:return
        if self.pending is not None and self.pending['key']==key:return
        if self.failure is not None and self.failure[0]==key:return
        self.failure=None
        if self.active is not None:self.active['cancelled']=True
        self.pending=dict(key=key,policy=policy,previous=store._state,
            known=store._fingerprints,sizes=store._group_bytes,clock=store.validation_clock(),
            indexed_deadline=store._economic_deadline,cancelled=False)
        self.metrics['maximum_pending']=1
        if self.driver is None or self.driver.done():self.driver=asyncio.create_task(self._drive())

    def invalidate(self):
        if self.active is not None:
            self.active['cancelled']=True
            # Admission is synchronous on this same loop. A paused obsolete
            # iterator must not retain a previous slate/staging until its timer
            # gets another turn behind incoming source packets.
            if self.iterator is not None and not self.iterator.gi_running:
                self.iterator.close();self.iterator=None
            for field in ('previous','known','sizes'):
                self.active[field]=None
        self.pending=None;self.failure=None

    def valid(self,job):
        from app.comparison.estimated_policy import load
        return (not self.closed and not self.store.closed and not self.store._stopping and not self.store._source_stopping and not job['cancelled']
            and self.store._input_epoch==job['key'][0] and self.store._state is job['previous']
            and load().revision==job['policy'].revision)

    async def _drive(self):
        try:
            while self.pending is not None:
                job=self.pending;self.pending=None;self.active=job
                self.metrics['started']+=1;self.metrics['maximum_active']=1
                steps=temporal_steps(job['previous'],job['clock'],job['policy'].to_dict()!=job['previous']['estimate_policy'],
                    job['known'],job['sizes'],self.store.provider.allow_synthetic,indexed_deadline=job['indexed_deadline'])
                self.iterator=steps
                try:
                    while self.valid(job):
                        tick=perf_counter();unit=('initial',)
                        try:unit=next(steps)
                        except StopIteration as done:
                            if self.valid(job):
                                result=done.value
                                # A second real boundary during this job revokes
                                # publication. Ordinary elapsed ticks never do.
                                if result[5] is not None and self.store.validation_clock()>=result[5]:
                                    self.request_after(job)
                                else:
                                    self.store._install_temporal(result)
                                    self.metrics['completed']+=1
                            break
                        finally:
                            seconds=perf_counter()-tick
                            if seconds>self.metrics['maximum_unit_seconds']:
                                self.metrics['maximum_unit_seconds']=seconds
                                self.metrics['slowest_unit']=unit[0] if steps.gi_frame is not None else 'complete_bound_and_index'
                        self.metrics['units']+=1
                        await asyncio.sleep(.001)
                    else:self.metrics['cancelled']+=1
                except asyncio.CancelledError:
                    self.metrics['cancelled']+=1;raise
                except Exception as exc:
                    self.failure=(job['key'],type(exc).__name__)
                    self.store._revoke_economic();self.store.publish()
                finally:
                    steps.close();self.iterator=None;self.active=None
                    job.clear()
        finally:self.active=None

    def request_after(self,job):
        self.active=None
        self.request()

    async def close(self):
        self.closed=True;self.invalidate()
        if self.driver is not None and not self.driver.done():
            self.driver.cancel();await asyncio.gather(self.driver,return_exceptions=True)
        self.pending=None
