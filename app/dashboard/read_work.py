"""Two bounded retained-read lanes; cancellation never releases a live worker.

Deadlines withdraw adoption immediately. Database statement deadlines and existing
calculation checkpoints end cooperative work. A noncooperative worker remains
charged to its lane until it returns, including after the bounded shutdown drain.
Daemon workers belong to this app process and cannot survive its termination.
"""
import asyncio
from aiohttp import web
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from threading import Event, RLock, Thread
from time import monotonic

from app.diagnostics import failure
from app.comparison.calculation_control import CalculationStopped, cancellation, checkpoint
from app.storage.slate_reads import process_bytes
from app.collection.current_policy import DEFAULT

QUEUE_SECONDS = 1.0
WORK_SECONDS = 5.0
CLEANUP_SECONDS = 1.0
TRACE = ContextVar('predict_read_trace', default=None)


class TimedResponse(web.Response):
    def __init__(self, *, trace, **kwargs):
        self.read_trace=trace
        super().__init__(**kwargs)

    async def write_eof(self, data=b''):
        try:
            await super().write_eof(data)
            self.read_trace.values['response']='complete'
        except BaseException:
            self.read_trace.values['response']='disconnected'
            raise
        finally:self.read_trace.mark('response_completion',self.read_trace.started)


class ReadDeadline(ValueError):
    pass


class Trace:
    def __init__(self, lane):
        self.lane = lane
        self.started = monotonic()
        self.values = dict(lane=lane, stages_ms={}, outcome='admitted')
        self.cancelled = Event()
        self.deadline = None

    def mark(self, name, start):
        self.values['stages_ms'][name] = round((monotonic()-start)*1000, 3)

    def stopped(self):
        return self.cancelled.is_set() or self.deadline is not None and monotonic() >= self.deadline


@contextmanager
def stage(name):
    trace = TRACE.get(); start = monotonic()
    checkpoint()
    try:yield
    finally:
        if trace:trace.mark(name, start)
    checkpoint()


def database_deadline(db):
    trace = TRACE.get()
    if trace and trace.deadline:
        checkpoint()
        milliseconds = max(1, int((trace.deadline-monotonic())*1000))
        db.execute('SELECT set_config(\'statement_timeout\',%s,false)', (str(milliseconds),))
        db.execute('SELECT set_config(\'lock_timeout\',%s,false)', (str(min(milliseconds, 1000)),))


class ReadWork:
    def __init__(self, *, queue_seconds=QUEUE_SECONDS, work_seconds=WORK_SECONDS):
        self.queue_seconds = queue_seconds; self.work_seconds = work_seconds
        self.locks = {lane: asyncio.Lock() for lane in ('ordinary', 'selected')}
        self.pending = dict(ordinary=0, selected=0)
        self.running = {}; self.reservations = {}; self.closed = False
        self.traces = deque(maxlen=64); self.memory_lock = RLock()

    def guard(self, additional_bytes=0):
        trace = TRACE.get()
        with self.memory_lock:
            reserved = sum(v for key,v in self.reservations.items() if key is not trace)
            if trace and trace.lane=='selected' and additional_bytes>128*1024*1024:
                raise ValueError('current_read_memory_capacity')
            if process_bytes()+reserved+additional_bytes >= DEFAULT['rss_bytes']:
                raise ValueError('current_read_memory_capacity')
            if trace:self.reservations[trace] = max(additional_bytes, self.reservations.get(trace, 0))

    def diagnostics(self):
        return dict(pending=dict(self.pending), running=len(self.running),
            reserved_bytes=sum(self.reservations.values()), closed=self.closed,
            bounds=dict(workers=2, selected_workers=1, ordinary_workers=1,
                selected_admitted=2, ordinary_admitted=3, admitted=5,
                queue_seconds=self.queue_seconds, worker_response_seconds=self.work_seconds,
                shutdown_drain_seconds=CLEANUP_SECONDS, diagnostic_records=64,
                selected_reservation_bytes=128*1024*1024,
                process_bytes=DEFAULT['rss_bytes']), records=list(self.traces))

    async def run(self, selected, fn, trace):
        lane = 'selected' if selected else 'ordinary'
        if self.closed or self.pending[lane] >= (2 if selected else 3):
            raise ReadDeadline('current_read_busy')
        self.pending[lane] += 1
        trace.mark('admission',trace.started)
        lock = self.locks[lane]; acquired = False; launched = False
        self.traces.append(trace.values)
        try:
            start = monotonic()
            await asyncio.wait_for(lock.acquire(), self.queue_seconds)
            acquired = True; trace.mark('queue', start)
            if self.closed:raise ReadDeadline('current_read_shutdown')
            self.guard(16*1024*1024)
            trace.deadline = monotonic()+self.work_seconds
            loop = asyncio.get_running_loop(); future = loop.create_future()
            def finish(result, error):
                # This callback alone releases live capacity and reservations.
                if thread.is_alive():
                    loop.call_later(.001,finish,result,error)
                    return
                self.running.pop(trace, None)
                with self.memory_lock:self.reservations.pop(trace, None)
                self.pending[lane] -= 1; lock.release()
                trace.mark('worker', trace.deadline-self.work_seconds)
                if trace.cancelled.is_set():trace.mark('cancellation_cleanup', cancelled_at[0])
                if not future.done():
                    future.set_result((result, error))
            def worker():
                result = None; error = None
                try:
                    with cancellation(trace.stopped):result = fn()
                except BaseException as exc:
                    error = exc
                    if not isinstance(exc, (CalculationStopped, asyncio.CancelledError)):
                        failure(__name__, 'retained_read_worker', exc)
                finally:
                    try:loop.call_soon_threadsafe(finish, result, error)
                    except RuntimeError:pass  # Process is exiting; daemon ownership ends with it.
            cancelled_at = [monotonic()]
            thread = Thread(target=copy_context().run, args=(worker,), daemon=True, name='predict-read-'+lane)
            self.running[trace] = thread
            try:thread.start()
            except BaseException:
                self.running.pop(trace, None)
                raise
            launched = True
            try:
                result, error = await asyncio.wait_for(asyncio.shield(future), self.work_seconds)
                if error is not None:raise error
                trace.values['outcome'] = 'complete'
                return result
            except (TimeoutError, asyncio.CancelledError):
                cancelled_at[0] = monotonic(); trace.cancelled.set()
                # Failures are returned as data; detached futures never emit raw
                # provider/storage exception text through asyncio diagnostics.
                raise
        except TimeoutError:
            if not launched:trace.mark('queue',start)
            trace.values['outcome'] = 'worker_timeout' if launched else 'queue_timeout'
            raise ReadDeadline('current_read_timeout' if launched else 'current_read_queue_timeout') from None
        except asyncio.CancelledError:
            trace.values['outcome'] = 'cancelled'; trace.cancelled.set()
            raise
        finally:
            if not launched:
                with self.memory_lock:self.reservations.pop(trace, None)
                self.pending[lane] -= 1
                if acquired:lock.release()

    async def close(self):
        self.closed = True
        for trace in self.running:trace.cancelled.set()
        deadline = monotonic()+CLEANUP_SECONDS
        while self.running and monotonic() < deadline:await asyncio.sleep(.01)
        # Live workers and their reservations stay owned, never falsely reclaimed.
