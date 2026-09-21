"""Retained object accounting for the finite capture handoff."""
import asyncio
from dataclasses import fields, is_dataclass
from sys import getsizeof

QUEUE_ITEMS = 48  # 40 pending books plus bounded control/headroom.
QUEUE_BYTES = 1024 * 1024


def retained_bytes(value):
    """Recursive Python allocation sizes, including instance dictionaries.

    Shared referents count once per item (conservative across different items).
    This is retained object size, not process RSS or serialized payload size.
    """
    seen=set()
    def visit(v):
        if id(v) in seen:return 0
        seen.add(id(v));n=getsizeof(v)
        if isinstance(v,dict):n+=sum(visit(k)+visit(x) for k,x in v.items())
        elif isinstance(v,(list,tuple,set,frozenset)):n+=sum(visit(x) for x in v)
        elif is_dataclass(v):
            if hasattr(v,'__dict__'):n+=visit(vars(v))
            else:n+=sum(visit(getattr(v,f.name)) for f in fields(v))
        return n
    return visit(value)


class CaptureQueue(asyncio.Queue):
    def __init__(self,maxsize=QUEUE_ITEMS,byte_limit=QUEUE_BYTES):
        super().__init__(maxsize=maxsize);self.byte_limit=byte_limit;self.bytes=0
        self.high_bytes=0;self.high_items=0;self.sizes={};self.last_rejection=None
    def put_nowait(self,item):
        n=retained_bytes(item)
        if self.full() or self.bytes+n>self.byte_limit:
            self.last_rejection='queue_items' if self.full() else 'queue_bytes'
            raise asyncio.QueueFull
        super().put_nowait(item);self.sizes.setdefault(id(item),[]).append(n);self.bytes+=n
        self.high_bytes=max(self.high_bytes,self.bytes);self.high_items=max(self.high_items,self.qsize())
    def get_nowait(self):
        item=super().get_nowait();sizes=self.sizes[id(item)];self.bytes-=sizes.pop(0)
        if not sizes:del self.sizes[id(item)]
        return item

class DeadlineConnection:
    """Owned by the serial worker. Cancellation of an await is never DB cancellation."""
    def __init__(self,db):self.db=db;self.deadline=None
    def __getattr__(self,name):return getattr(self.db,name)
    def execute(self,*args,**kwargs):
        if self.deadline is not None:
            from time import monotonic
            remaining=self.deadline-monotonic()
            if remaining<=0:raise TimeoutError('worker budget exhausted')
            self.db.execute("SELECT set_config('statement_timeout',%s,false)",(str(max(1,min(1000,int(remaining*1000)))),))
        return self.db.execute(*args,**kwargs)
