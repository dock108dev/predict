"""Deterministic fair finite work queues with atomic publication.

One item per event per round. All admitted work completes before a revision is
published; a prefix-only or silently carried-over calculation is not current.
The event-loop owner remains synchronous."""
from collections import deque

BATCH_ITEMS = 32


def batches(items, event_key, *, size=BATCH_ITEMS):
    if type(size) is not int or not 1<=size<=BATCH_ITEMS:
        raise ValueError('Bounded projection batch required')
    groups={}
    for item in items:groups.setdefault(event_key(item),deque()).append(item)
    queue=deque(groups.values());batch=[]
    while queue:
        group=queue.popleft();batch.append(group.popleft())
        if group:queue.append(group)
        if len(batch)==size:
            yield batch;batch=[]
    if batch:yield batch


def groups(events, *, size=BATCH_ITEMS):
    items=[(e,g) for e in events for g in e['groups']]
    yield from batches(items,lambda item:item[0]['id'],size=size)
