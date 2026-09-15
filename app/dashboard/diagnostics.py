"""Opt-in 13A measurements. No collector, queue, drain or status policy changes.

Only the isolated benchmark imports these wrappers. Payloads are never logged.
All durations use a monotonic clock; estimated bytes are serialized fixture bytes,
not an estimate of Python heap use. Database readback, not return counts, proves
commit. Timings are inclusive and must not be added across nested stages.
"""
import asyncio
from collections import deque
from contextlib import contextmanager
from time import perf_counter
from functools import wraps

from app.dashboard.controller import Controller
from app.dashboard.bounds import CaptureQueue


class Measurements:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.origin = perf_counter()
        self.stages = []
        self.items = []
        self.queue_samples = []
        self.bindings = []
        self.active = 'bootstrap'
        self.next_item = None
        self.pending = deque()
        self.estimates = {}

    def now(self):
        return perf_counter() - self.origin

    @contextmanager
    def timed(self, stage):
        if not self.enabled:
            yield
            return
        start = self.now()
        outcome = 'returned'
        try:
            yield
        except BaseException:
            outcome = 'raised'
            raise
        finally:
            self.stages.append(dict(stage=stage, item_id=self.active,
                                    start=start, seconds=self.now()-start, outcome=outcome))

    def sample(self):
        t = self.now()
        self.queue_samples.append(dict(at=t, entries=len(self.pending),
            estimated_bytes=sum(r['estimated_bytes'] for r in self.pending),
            oldest_seconds=t-self.pending[0]['offered_at'] if self.pending else 0))


class MeasuredQueue(CaptureQueue):
    def __init__(self, metrics):
        super().__init__()
        self.metrics = metrics

    def get_nowait(self):
        item = super().get_nowait()
        m = self.metrics
        row = m.pending.popleft()
        row['dequeued_at'] = m.now()
        row['queue_wait_seconds'] = row['dequeued_at'] - row['offered_at']
        m.next_item = row
        m.sample()
        return item


class MeasuredController(Controller):
    def __init__(self, metrics, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = metrics

    async def _run(self):
        # start() creates a new queue; replace it before any producer runs.
        self.queue = MeasuredQueue(self.metrics)
        await super()._run()

    def offer_identified(self, item_id, item, estimated_bytes):
        m = self.metrics
        if any(r['id'] == item_id for r in m.items):
            raise ValueError('duplicate diagnostic item ID')
        if len(m.items) >= 128:
            raise ValueError('diagnostic item bound')
        row = dict(id=item_id, kind=item[0], offered_at=m.now(),
                   estimated_bytes=estimated_bytes, processed=False)
        was_accepting = self.accepting
        accepted = super().offer(item)
        row.update(accepted=accepted, rejection=None if accepted else
                   ('queue_full' if was_accepting and self.queue.full() else 'acceptance_closed'))
        m.items.append(row)
        if accepted:
            m.pending.append(row)
        m.sample()
        return accepted

    async def work(self, fn, *args):
        m = self.metrics
        row = m.next_item if fn.__name__ in ('book', 'disconnect', 'synthetic_tick', 'event') else None
        if row:
            m.next_item = None
        submitted = m.now()
        @wraps(fn)
        def measured():
            m.active = row['id'] if row else fn.__name__
            if m.enabled:
                m.stages.append(dict(stage='executor_wait.'+fn.__name__,item_id=m.active,start=submitted,seconds=m.now()-submitted,outcome='started'))
            if row:
                row['worker_started_at'] = m.now()
                row['worker_wait_seconds'] = m.now()-submitted
            with m.timed('worker.'+fn.__name__):
                result = fn(*args)
            if row:
                row['processed'] = True
                row['completed_at'] = m.now()
            return result
        return await super().work(measured)


def reconcile(metrics, receipts, calculations, events, observations):
    """Readback rows come from a fresh connection after pipeline finalization.

    Failed item methods may have committed receipts before evaluation failed.
    Their durable subset is retained; they remain explicitly unprocessed items.
    """
    receipts = set(receipts)
    calculations = set(calculations)
    events = set(events)
    bindings = []
    bound = set()
    for b in metrics.bindings:
        b = dict(b)
        universe = {'receipt': receipts, 'calculation': calculations, 'event': events}[b['kind']]
        b['committed'] = b['id'] in universe
        bindings.append(b)
        if b['kind'] == 'receipt' and b['committed']:
            bound.add(b['id'])
    items = []
    for row in metrics.items:
        row = dict(row)
        row['writes'] = [b for b in bindings if b['item_id'] == row['id']]
        row['disposition'] = ('rejected' if not row['accepted'] else
                              'processed' if row['processed'] else 'explicitly_unprocessed')
        items.append(row)
    accepted = sum(r['accepted'] for r in items)
    processed = sum(r['processed'] for r in items)
    counts = dict(offered=len(items), accepted=accepted, rejected=len(items)-accepted,
                  processed=processed, unprocessed=accepted-processed,
                  retained_per_side_observations=observations,
                  committed_receipts=len(receipts), attempted_receipt_writes=sum(b['kind']=='receipt' for b in bindings),
                  wire_messages=None, upstream_offered=None, upstream_lost=None)
    gates = dict(item_equation=counts['offered']==accepted+counts['rejected'],
                 accepted_equation=accepted==processed+counts['unprocessed'],
                 all_receipts_bound=bound==receipts,
                 unique_items=len({r['id'] for r in items})==len(items),
                 processed_have_committed_writes=all(any(b['committed'] for b in r['writes']) for r in items if r['processed']))
    return dict(counts=counts, items=items, bindings=bindings, gates=gates)
