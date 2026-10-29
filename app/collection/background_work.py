"""Nonblocking process memory admission for independent background owners.

Only one optional capture owns memory at a time. Its admission leaves a source
publication runway, so ordinary observations never queue behind a slow estimate.
Reservations belong to synchronous worker lifetimes, including cancelled awaits.
The existing fatal process high-water guard remains a separate owner.
"""
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import os
import ctypes
import sys
from pathlib import Path
import subprocess
import time
from threading import RLock

from .current_policy import DEFAULT

MIB = 1024 * 1024
OPTIONAL = ('estimates', 'scanner', 'coverage')
SOURCE_RUNWAY = 160 * MIB
INGRESS_HEADROOM = 32 * MIB


class _MachTaskBasicInfo(ctypes.Structure):
    _fields_=[('virtual_size',ctypes.c_uint64),('resident_size',ctypes.c_uint64),
        ('resident_size_max',ctypes.c_uint64),('user_time',ctypes.c_int*2),
        ('system_time',ctypes.c_int*2),('policy',ctypes.c_int),('suspend_count',ctypes.c_int)]


_MACH=ctypes.CDLL(None) if sys.platform=='darwin' else None


def _mach_resident_bytes():
    info=_MachTaskBasicInfo();count=ctypes.c_uint(ctypes.sizeof(info)//4)
    task=ctypes.c_uint.in_dll(_MACH,'mach_task_self_').value
    if _MACH.task_info(task,20,ctypes.byref(info),ctypes.byref(count))!=0:
        raise OSError('resident_sample_failed')
    if info.resident_size<=0:raise ValueError('resident_sample_invalid')
    return int(info.resident_size)


def resident_bytes():
    """Current resident bytes; peak RSS still owns the unchanged fatal guard."""
    try:
        path=Path('/proc/self/statm')
        if path.exists():
            with path.open() as stream:fields=stream.read(256).split()
            return int(fields[1])*os.sysconf('SC_PAGE_SIZE')
        if _MACH is not None:
            try:return _mach_resident_bytes()
            except (OSError,ValueError,AttributeError):pass
        value=subprocess.run(['/bin/ps','-o','rss=','-p',str(os.getpid())],
            capture_output=True,text=True,check=True,timeout=.25).stdout
        if len(value)>64:raise ValueError('resident_sample_capacity')
        count=int(value.strip())*1024
        if count<=0:raise ValueError('resident_sample_invalid')
        return count
    except (OSError,ValueError,IndexError,subprocess.SubprocessError):
        # A failed current sample cannot turn unknown memory into zero.
        from .continuous import rss
        return rss()


@dataclass(frozen=True)
class Lease:
    admitted: bool
    reason: str | None
    kind: str
    reserved_bytes: int
    resident_bytes: int

    def __bool__(self):
        return self.admitted

    def deferred(self):
        return dict(published=False,deferred=True,reason=self.reason,
            background_work=self.kind,reserved_bytes=self.reserved_bytes,
            resident_bytes=self.resident_bytes,provider_requests=0)


class BackgroundWork:
    def __init__(self, *, sampler=resident_bytes, limit_bytes=DEFAULT['rss_bytes'],
                 source_runway_bytes=SOURCE_RUNWAY, ingress_headroom_bytes=INGRESS_HEADROOM):
        self.sampler=sampler;self.limit=limit_bytes;self.runway=source_runway_bytes
        self.headroom=ingress_headroom_bytes;self.lock=RLock()
        self.active={};self.waiting=OrderedDict();self.counts={}
        self.last={};self.last_resident=None
        self.acquisition_pressure=lambda:False
        self.critical_acquisition_pressure=lambda:False

    def _fits(self, resident, amount, *, optional):
        # Resident memory may already include some in-flight allocation. Count
        # its entire outstanding lease nevertheless: growth attribution across
        # threads is unknown, and a live worker may still allocate its full bound.
        outstanding=sum(size for kind,size in self.active.items() if kind in OPTIONAL)
        return resident+amount+outstanding+self.headroom+(self.runway if optional else 0)<self.limit

    def capacity(self, kind, *, replacing=False):
        """Planning ceiling only; claim rechecks live RSS before every capture.

        A smaller batch contains fewer complete neighborhoods. Its full measured
        reservation and all padding remain charged at the ordinary multiplier.
        """
        if kind not in (*OPTIONAL,'observations'):
            raise ValueError('background_work_reservation_invalid')
        resident=self.sampler()
        if type(resident) is not int or resident<0:
            raise ValueError('background_resident_sample_invalid')
        with self.lock:
            outstanding=sum(size for name,size in self.active.items() if name in OPTIONAL and not (replacing and name==kind))
            available=self.limit-resident-outstanding-self.headroom-(self.runway if kind in OPTIONAL else 0)-1
            return max(0,min(available,self.runway if kind=='observations' else self.limit))

    @contextmanager
    def claim(self, kind, additional_bytes, *, source=False):
        if (kind not in (*OPTIONAL,'observations') or source!=(kind=='observations') or
                type(additional_bytes) is not int or additional_bytes<0):
            raise ValueError('background_work_reservation_invalid')
        resident=self.sampler()
        if type(resident) is not int or resident<0:raise ValueError('background_resident_sample_invalid')
        with self.lock:
            self.last_resident=resident
            reason=None
            if source:
                if self.acquisition_pressure():reason='native_acquisition_catching_up'
                elif kind in self.active:reason='background_source_busy'
                elif additional_bytes>self.runway:reason='background_source_capacity'
                elif not self._fits(resident,additional_bytes,optional=False):reason='background_memory_capacity'
            else:
                self.waiting[kind]=additional_bytes
                eligible=next((name for name,size in self.waiting.items() if self._fits(resident,size,optional=True)),None)
                # The optional fit already reserves the full source runway.
                # Requiring an idle source as well can phase-lock periodic
                # workers and starve Coverage indefinitely under healthy ingress.
                if self.acquisition_pressure():reason='native_acquisition_catching_up'
                elif any(name in self.active for name in OPTIONAL):
                    reason='background_work_busy'
                elif not self._fits(resident,additional_bytes,optional=True):reason='background_memory_capacity'
                elif eligible!=kind:reason='background_work_turn'
            admitted=reason is None
            if admitted:
                self.waiting.pop(kind,None)
                self.active[kind]=additional_bytes
            counts=self.counts.setdefault(kind,dict(admitted=0,deferred=0))
            counts['admitted' if admitted else 'deferred']+=1
            lease=Lease(admitted,reason,kind,additional_bytes,resident)
            self.last[kind]=dict(state='admitted' if admitted else 'deferred',reason=reason,
                reserved_bytes=additional_bytes,resident_bytes=resident)
        try:yield lease
        finally:
            if admitted:
                with self.lock:self.active.pop(kind,None)

    def resize(self, kind, additional_bytes):
        """Grow a live worker's charge before retaining additional input graphs."""
        resident=self.sampler()
        with self.lock:
            if kind not in self.active or type(additional_bytes) is not int or additional_bytes<0:
                raise ValueError('background_work_reservation_invalid')
            amount=max(self.active[kind],additional_bytes)
            other=sum(v for k,v in self.active.items() if k in OPTIONAL and k!=kind)
            if kind=='observations' and amount>self.runway:
                raise ValueError('background_source_capacity')
            if resident+amount+other+self.headroom+(self.runway if kind in OPTIONAL else 0)>=self.limit:
                raise ValueError('background_memory_capacity')
            self.active[kind]=amount

    def cancel(self, kind):
        """Remove a stopped owner's waiting turn; live leases stay charged."""
        with self.lock:self.waiting.pop(kind,None)

    def request(self, kind):
        """Keep a CPU turn across pre-capture yielding, without reserving memory.

        An unknown capture has zero planning demand until claim measures it.
        Claim still rechecks the real size and live RSS before any admission.
        Registering before cancellation prevents a frequently polling scanner
        from repeatedly passing estimate/coverage owners yielded by acquisition.
        """
        if kind not in OPTIONAL:raise ValueError('background_work_reservation_invalid')
        with self.lock:self.waiting.setdefault(kind,0)

    def requested(self, kind, fn):
        """Own the waiter until admission, explicit deferral, failure or no-op."""
        self.request(kind)
        try:value=fn()
        except AcquisitionDeferred:raise
        except BaseException:
            self.cancel(kind)
            raise
        # A normal no-op (unchanged coverage, another owner) may never claim.
        # It must not leave a zero-size waiter blocking the other owners.
        if not isinstance(value,dict) or not value.get('deferred'):self.cancel(kind)
        return value

    def diagnostics(self):
        with self.lock:
            return dict(active=dict(self.active),waiting=list(self.waiting),
                optional_owner=next((kind for kind in OPTIONAL if kind in self.active),None),
                reserved_bytes=sum(self.active.values()),resident_bytes=self.last_resident,
                last={key:dict(value) for key,value in self.last.items()},
                counts={key:dict(value) for key,value in self.counts.items()},
                optional_workers=1,source_workers=1,source_runway_bytes=self.runway,
                ingress_headroom_bytes=self.headroom,process_limit_bytes=self.limit)

    snapshot=diagnostics


BACKGROUND = BackgroundWork()


# Exactly three runtime owners call this lane, each awaiting its one turn before
# submitting another. Only callables queue, never captured source graphs. Sharing
# the thread also reuses its allocator heap across these mutually exclusive
# captures instead of retaining a separate high-water heap for every pool thread.
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import partial
import asyncio

_OPTIONAL_EXECUTOR = ThreadPoolExecutor(max_workers=1,thread_name_prefix='predict-optional')
_SOURCE_EXECUTOR = ThreadPoolExecutor(max_workers=1,thread_name_prefix='predict-observations')
_INGRESS_EXECUTOR = ThreadPoolExecutor(max_workers=1,thread_name_prefix='predict-ingress')


async def optional_thread(fn, *args, **kwargs):
    return await asyncio.get_running_loop().run_in_executor(
        _OPTIONAL_EXECUTOR,copy_context().run,partial(fn,*args,**kwargs))


async def source_thread(fn, *args, **kwargs):
    # One awaited observation owner; light heartbeat/control jobs never queue
    # behind this capture and never inherit its allocator heap.
    return await asyncio.get_running_loop().run_in_executor(
        _SOURCE_EXECUTOR,copy_context().run,partial(fn,*args,**kwargs))


async def ingress_thread(fn, *args, **kwargs):
    # The bounded ingress owner's serialization lock admits one SQL job here.
    return await asyncio.get_running_loop().run_in_executor(
        _INGRESS_EXECUTOR,copy_context().run,partial(fn,*args,**kwargs))


class AcquisitionDeferred(Exception):
    """Optional work yields without becoming failed or permanently stopped."""


def optional_cancelled(stopped):
    if stopped:return True
    # Admission yields to the derived queue. An already admitted complete
    # component can finish while normalization is a few seconds behind; aborting
    # it on every ordinary tail made the next attempt repeat all prior CPU work.
    # Actual socket/raw pressure still interrupts it, as does Stop above.
    if BACKGROUND.critical_acquisition_pressure():
        # A CPU-bound optional thread can itself delay the ingress event loop.
        # Briefly release the GIL before discarding its whole captured component.
        # Keep the same pressure threshold and a bounded two-second grace; persistent
        # backlog still cancels, and an already observed Stop never waits here.
        deadline=time.monotonic()+2
        while BACKGROUND.critical_acquisition_pressure() and time.monotonic()<deadline:
            time.sleep(.01)
        if BACKGROUND.critical_acquisition_pressure():raise AcquisitionDeferred('native_acquisition_catching_up')
    return False
