"""Bounded per-worker queue conservation, including non-publication departures.

Counts queue tickets, not socket frames: replacement in a pending slot coalesces;
a new image behind an in-flight ticket admits another ticket. Old generations
roll into one cumulative bucket, never into the completion counter.
"""
from collections import Counter

REASONS = frozenset(('retirement','quiescence','resync','cancellation','invalidated','rejected','raw_persistence_failed'))


class QueueAccounting:
    def __init__(self, source):
        self.source=source
        self.pending={}
        self.inflight={}
        self.generations={}
        self.through=-1
        self.older=Counter()

    def bucket(self, generation):
        if generation<=self.through:return self.older
        bucket=self.generations.setdefault(generation,Counter())
        while len(self.generations)>8:
            old=min(self.generations)
            self.older.update(self.generations.pop(old));self.through=old
        return bucket

    def admit(self, key, generation):
        if key in self.pending:return
        self.pending[key]=generation
        self.bucket(generation)['admissions']+=1

    def claim(self, keys):
        for key in keys:
            if key in self.pending:self.inflight[key]=self.pending.pop(key)

    def depart(self, keys, reason=None, *, pending=False):
        if reason is not None and reason not in REASONS:raise ValueError('native_queue_departure_reason')
        owner=self.pending if pending else self.inflight
        for key in keys:
            if key not in owner:continue
            bucket=self.bucket(owner.pop(key))
            bucket['completions' if reason is None else 'withdrawals']+=1
            if reason is not None:bucket[reason]+=1

    def snapshot(self):
        pending=Counter(g if g>self.through else 'older' for g in self.pending.values())
        flight=Counter(g if g>self.through else 'older' for g in self.inflight.values())
        rows=[];total=Counter()
        for generation,counts in [('older',self.older),*sorted(self.generations.items())]:
            row=dict(generation=generation,admissions=counts['admissions'],completions=counts['completions'],
                withdrawals=counts['withdrawals'],reasons={k:counts[k] for k in sorted(REASONS)},
                pending=pending[generation],inflight=flight[generation])
            row['residual']=row['admissions']-row['completions']-row['withdrawals']-row['pending']-row['inflight']
            total.update({k:row[k] for k in ('admissions','completions','withdrawals','pending','inflight','residual')})
            rows.append(row)
        return dict(source=self.source,**total,generations=rows,older_through=self.through)
