"""Serialized, bounded SQL ingress with loop-owned reducer adoption.

Generators prepare commands and resume only after the SQL commit. Cancellation
revokes adoption but never releases a running worker or its serialization lock.
"""
import asyncio
from functools import wraps
from threading import Event
from collections import deque
from time import monotonic


def prepare_catalog_change(inventory, source, catalog):
    from .current_service import prepare_catalog
    from .current_catalog_delta import changes
    prepared=prepare_catalog(inventory,source,catalog,share_metadata=True)
    return prepared,changes(inventory,prepared)


class CatalogPreparation:
    """One CPU rebuild in flight; no SQL, sockets, credentials or authority."""
    def __init__(self):
        from concurrent.futures import ProcessPoolExecutor
        from multiprocessing import get_context
        # Reclaim the full transient metadata arena after each infrequent rebuild.
        self.pool=ProcessPoolExecutor(max_workers=1,mp_context=get_context('spawn'),max_tasks_per_child=1)
        self.lock=asyncio.Lock()

    async def prepare(self,inventory,source,catalog):
        async with self.lock:
            future=asyncio.wrap_future(self.pool.submit(prepare_catalog_change,inventory,source,catalog))
            try:return await asyncio.shield(future)
            except asyncio.CancelledError:
                await asyncio.gather(future,return_exceptions=True)
                raise

    async def close(self):
        from .bulk_checkpoint import owned_thread
        await owned_thread(self.pool.shutdown,wait=True,cancel_futures=True)


def operation(fn):
    @wraps(fn)
    def synchronous(self, *args, **kwargs):
        service = getattr(self, 'service', self)
        steps = fn(self, *args, **kwargs)
        value = None
        while True:
            try:row, states = steps.send(value)
            except StopIteration as done:return done.value
            try:value = service.sink.commit(row, states)
            except Exception as exc:
                try:steps.throw(exc)
                except StopIteration as done:return done.value
                raise
    synchronous.operation = fn
    return synchronous


async def call(service, fn, *args, **kwargs):
    if not getattr(service, 'database_mode', False):
        return fn(*args, **kwargs)
    return await service.ingress.run(fn, *args, **kwargs)


class Ingress:
    def __init__(self, service):
        self.service = service
        self.lock = asyncio.Lock()
        self.tasks = {}
        self.sources = {}
        self.records = deque(maxlen=32)
        self.maximum = 8
        self.slots=asyncio.Semaphore(self.maximum)
        self.revocations={}
        self.catalog_preparer=None

    async def run(self, fn, *args, **kwargs):
        source="the_odds_api" if hasattr(fn.__self__,"service") else args[0] if args else None
        generation=(self.revocations.get(None,0),self.revocations.get(source,0))
        await self.slots.acquire()
        if generation!=(self.revocations.get(None,0),self.revocations.get(source,0)):
            self.slots.release()
            raise asyncio.CancelledError()
        revoked = Event()
        async def execute():
            started = monotonic()
            queue_seconds=prepare_seconds=commit_seconds=catalog_prepare_seconds=precompute_seconds=0.0
            precomputed=None
            try:
                operation_kwargs=kwargs
                if fn.__name__=='catalog':
                    from .bulk_checkpoint import owned_thread
                    # Price commits can proceed while immutable catalog metadata
                    # is prepared. A competing catalog requires a new base; never
                    # publish a detached replacement over a newer generation.
                    while True:
                        if revoked.is_set():raise asyncio.CancelledError()
                        base=self.service.sink.reducer
                        generation=base.generation
                        tick=monotonic()
                        if getattr(self.service.sink,'process_normalization',False):
                            if self.catalog_preparer is None:self.catalog_preparer=CatalogPreparation()
                            prepared,delta=await self.catalog_preparer.prepare(base.inventory,*args)
                        else:
                            prepared,delta=await owned_thread(prepare_catalog_change,base.inventory,*args)
                        catalog_prepare_seconds+=monotonic()-tick
                        if revoked.is_set():raise asyncio.CancelledError()
                        await self.lock.acquire()
                        if self.service.sink.reducer.generation==generation:break
                        self.lock.release()
                    operation_kwargs=dict(kwargs,prepared=prepared,catalog_delta=delta)
                else:
                    if fn.__name__=='books' and getattr(self.service.sink,'process_normalization',False):
                        from .bulk_checkpoint import owned_thread
                        tick=monotonic()
                        precomputed=await owned_thread(self.service.sink.precompute_books,*args,revoked)
                        precompute_seconds=monotonic()-tick
                        if revoked.is_set():raise asyncio.CancelledError()
                    await self.lock.acquire()
                try:
                    if revoked.is_set():raise asyncio.CancelledError()
                    queue_seconds=monotonic()-started-catalog_prepare_seconds-precompute_seconds
                    steps = fn.operation(fn.__self__, *args, **operation_kwargs)
                    value = None
                    while True:
                        tick=monotonic()
                        try:row, states = steps.send(value)
                        except StopIteration as done:return done.value
                        prepare_seconds+=monotonic()-tick
                        tick=monotonic()
                        try:
                            value = await self.service.sink.commit_async(row, states, revoked,
                                **(dict(precomputed=precomputed) if precomputed is not None else {}))
                            commit_seconds+=monotonic()-tick
                        except Exception as exc:
                            try:steps.throw(exc)
                            except StopIteration as done:return done.value
                            raise
                finally:
                    self.lock.release()
            finally:
                self.records.append(dict(operation=fn.__name__, seconds=monotonic()-started,
                                         revoked=revoked.is_set(),queue_seconds=queue_seconds,
                                         prepare_seconds=prepare_seconds,commit_seconds=commit_seconds,
                                         catalog_prepare_seconds=catalog_prepare_seconds,precompute_seconds=precompute_seconds))
        task = asyncio.create_task(execute(), name='predict-ingress-'+fn.__name__)
        self.tasks[task] = revoked
        self.sources[task] = "the_odds_api" if hasattr(fn.__self__,"service") else args[0] if args else None
        def finished(task):
            self.slots.release()
            self.tasks.pop(task, None)
            self.sources.pop(task, None)
            if not task.cancelled():task.exception()
        task.add_done_callback(finished)
        try:return await asyncio.shield(task)
        except asyncio.CancelledError:
            revoked.set()
            raise

    def revoke(self, source=None):
        self.revocations[source]=self.revocations.get(source,0)+1
        for task,revoked in self.tasks.items():
            if source is None or self.sources[task]==source:revoked.set()

    async def drain(self, seconds, source=None):
        self.revoke(source)
        tasks = [task for task in self.tasks if source is None or self.sources[task]==source]
        if not tasks:return True
        _, pending = await asyncio.wait(tasks, timeout=seconds)
        return not pending
