"""Serialized, bounded SQL ingress with loop-owned reducer adoption.

Generators prepare commands and resume only after the SQL commit. Cancellation
revokes adoption but never releases a running worker or its serialization lock.
"""
import asyncio
from functools import wraps
from threading import Event
from collections import deque
from time import monotonic


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

    async def run(self, fn, *args, **kwargs):
        if len(self.tasks) >= self.maximum:
            raise ValueError('current_ingress_capacity')
        revoked = Event()
        async def execute():
            started = monotonic()
            try:
                async with self.lock:
                    if revoked.is_set():raise asyncio.CancelledError()
                    steps = fn.operation(fn.__self__, *args, **kwargs)
                    value = None
                    while True:
                        try:row, states = steps.send(value)
                        except StopIteration as done:return done.value
                        try:
                            value = await self.service.sink.commit_async(row, states, revoked)
                        except Exception as exc:
                            try:steps.throw(exc)
                            except StopIteration as done:return done.value
                            raise
            finally:
                self.records.append(dict(operation=fn.__name__, seconds=monotonic()-started,
                                         revoked=revoked.is_set()))
        task = asyncio.create_task(execute(), name='predict-ingress-'+fn.__name__)
        self.tasks[task] = revoked
        self.sources[task] = "the_odds_api" if hasattr(fn.__self__,"service") else args[0] if args else None
        def finished(task):
            self.tasks.pop(task, None)
            self.sources.pop(task, None)
            if not task.cancelled():task.exception()
        task.add_done_callback(finished)
        try:return await asyncio.shield(task)
        except asyncio.CancelledError:
            revoked.set()
            raise

    def revoke(self, source=None):
        for task,revoked in self.tasks.items():
            if source is None or self.sources[task]==source:revoked.set()

    async def drain(self, seconds, source=None):
        self.revoke(source)
        tasks = [task for task in self.tasks if source is None or self.sources[task]==source]
        if not tasks:return True
        _, pending = await asyncio.wait(tasks, timeout=seconds)
        return not pending
