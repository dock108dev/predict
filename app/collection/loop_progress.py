"""Bounded event-loop scheduling evidence; no frames, locals or provider text."""
import asyncio
from collections import Counter, deque
from pathlib import Path
import sys
import threading
import time


class LoopProgress:
    def __init__(self):
        self.last = time.monotonic()
        self.maximum = 0.0
        self.samples = deque(maxlen=16)
        self.profile = Counter()
        self.thread_profile = Counter()
        self.profile_samples = 0
        self.stopped = threading.Event()
        self.owner = threading.get_ident()
        self.thread = threading.Thread(target=self.inspect, name='predict-loop-progress', daemon=True)
        self.task = None

    def start(self):
        self.thread.start()
        self.task = asyncio.create_task(self.tick(), name='predict-loop-progress')

    async def tick(self):
        while True:
            await asyncio.sleep(.1)
            now = time.monotonic()
            self.maximum = max(self.maximum, now-self.last-.1)
            self.last = now

    def inspect(self):
        started=time.monotonic()
        while not self.stopped.wait(.1 if self.profile_samples<1800 else 1):
            delay = time.monotonic()-self.last
            profiling=time.monotonic()-started>=120 and self.profile_samples<1800
            if delay < 1 and not profiling:
                continue
            frame = sys._current_frames().get(self.owner)
            stack = []
            while frame and len(stack) < 12:
                stack.append(f'{Path(frame.f_code.co_filename).name}:{frame.f_code.co_name}:{frame.f_lineno}')
                frame = frame.f_back
            if profiling:
                key=tuple(stack)
                if key in self.profile or len(self.profile)<512:
                    self.profile[key]+=1
                names={t.ident:t.name for t in threading.enumerate()}
                for ident,other in sys._current_frames().items():
                    if ident in (self.owner,threading.get_ident()):continue
                    trace=[]
                    while other and len(trace)<10:
                        trace.append(f'{Path(other.f_code.co_filename).name}:{other.f_code.co_name}:{other.f_lineno}')
                        other=other.f_back
                    key=(names.get(ident,'worker'),*trace)
                    if key in self.thread_profile or len(self.thread_profile)<512:self.thread_profile[key]+=1
                self.profile_samples+=1
            if delay>=1:
                self.samples.append(dict(delay_seconds=delay, stack=stack))

    def snapshot(self):
        return dict(maximum_delay_seconds=self.maximum, stalled_samples=list(self.samples),
                    profile_samples=self.profile_samples,
                    sampled_threads=[dict(count=n,stack=list(stack)) for stack,n in Counter(self.thread_profile.copy()).most_common(32)],
                    sampled_stacks=[dict(count=n,stack=list(stack)) for stack,n in Counter(self.profile.copy()).most_common(24)])

    async def close(self):
        self.stopped.set()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.thread.is_alive():
            await asyncio.to_thread(self.thread.join)
