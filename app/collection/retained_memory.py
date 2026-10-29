"""Bounded retained-container size estimates; no values, identifiers or secrets."""
import asyncio
from dataclasses import fields,is_dataclass
import sys
import time


def measure(roots,limit=2000000):
    seen=set();result={};started=time.monotonic()
    for name,root in roots:
        stack=[root];size=count=0
        while stack and len(seen)<limit:
            obj=stack.pop();key=id(obj)
            if key in seen:continue
            seen.add(key);size+=sys.getsizeof(obj);count+=1
            if isinstance(obj,dict):
                try:stack.extend(tuple(obj.keys()));stack.extend(tuple(obj.values()))
                except RuntimeError:pass
            elif isinstance(obj,(list,tuple,set,frozenset)):stack.extend(tuple(obj))
            elif is_dataclass(obj) and not isinstance(obj,type):stack.extend(getattr(obj,f.name) for f in fields(obj))
        result[name]=dict(unique_bytes=size,objects=count,incomplete=bool(stack))
    return dict(roots=result,objects=len(seen),seconds=time.monotonic()-started,monotonic=time.monotonic(),method='unique retained Python containers; shared objects counted once; not RSS or allocator usage')


async def watch(runtime):
    while True:
        await asyncio.sleep(120)
        service=runtime.service
        # Walking millions of Python objects allocates a large id set and work
        # stack of its own. Repeating that on arbitrary pool threads inflated
        # the very RSS high-water this observer was supposed to explain.
        # Report owned cardinalities and exact encoded bytes without a heap walk.
        from .background_work import resident_bytes
        books=service.sink.reducer.books
        roots={'reducer_books':dict(entries=len(books),encoded_bytes=getattr(books,'encoded_bytes',None))}
        for name,worker in list(service.workers.items()):
            for attr in ('catalog_cache','markets','pages','pending_books','raw_pending'):
                value=getattr(worker,attr,None)
                roots[name+'_'+attr]=dict(entries=len(value) if value is not None else 0)
        runtime.retained_memory=dict(roots=roots,resident_bytes=resident_bytes(),monotonic=time.monotonic(),
            method='owned container counts and exact encoded book bytes; no recursive heap traversal')
        value=None
