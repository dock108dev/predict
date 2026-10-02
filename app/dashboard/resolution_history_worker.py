"""Offline resolution indexing in an owned fresh process, never a detached thread.

The journal reader's existing 256 MiB cap remains in force. The deadline matches
ordinary isolated replay (25 seconds); cancellation terminates and reaps the
worker. Filesystem signatures invalidate even cached negative results.
"""
import asyncio
from collections import OrderedDict
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

MAX_BYTES = 16 * 1024 * 1024
SECONDS = 25


def signature(folder):
    folder = Path(folder)
    return [(str(p.relative_to(folder)), s.st_ino, s.st_mode, s.st_size,
             s.st_mtime_ns, s.st_ctime_ns)
            for p in sorted(folder.rglob('*')) for s in [p.lstat()]]


class ResolutionHistoryCache:
    def __init__(self):
        self.entries = OrderedDict()
        self.size = 0
        self.lock = asyncio.Lock()
        self.process = None
        self.last_accounting = None
        self.worker_count = self.cache_hits = 0

    async def load(self, paths):
        async with self.lock:
            result = {}; missing = {}; signatures = {}
            for sid, folder in paths.items():
                key = str(Path(folder).resolve())
                sig = signature(folder); signatures[sid] = (key, sig)
                old = self.entries.pop(key, None)
                if old:
                    self.size -= old[2]
                    if old[0] == sig:
                        self.entries[key] = old; self.size += old[2]
                        self.cache_hits += 1
                        result[sid] = deepcopy(old[1]); continue
                missing[sid] = key
            if missing:
                deadline=asyncio.get_running_loop().time()+SECONDS
                launch=asyncio.create_task(asyncio.create_subprocess_exec(sys.executable, '-m',
                    'app.dashboard.resolution_history_worker', stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd=Path(__file__).resolve().parents[2]))
                try:
                    proc=await asyncio.wait_for(asyncio.shield(launch),SECONDS)
                except BaseException:
                    # Cancellation cannot abandon a process whose creation is
                    # still completing. Take ownership, terminate and reap it.
                    proc=await launch
                    if proc.returncode is None:proc.kill()
                    await proc.wait()
                    raise
                self.process = proc
                self.worker_count += 1
                async def receive():
                    proc.stdin.write(json.dumps(missing).encode()); await proc.stdin.drain()
                    proc.stdin.close()
                    body = bytearray()
                    while chunk := await proc.stdout.read(65536):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES: raise ValueError('Resolution worker result bound')
                    await proc.wait()
                    if proc.returncode: raise ValueError('Resolution worker failed')
                    return json.loads(body)
                try:
                    output = await asyncio.wait_for(receive(), max(0,deadline-asyncio.get_running_loop().time()))
                    self.last_accounting = output['accounting']
                finally:
                    if proc.returncode is None: proc.kill()
                    await proc.wait()
                    self.process = None
                for sid, value in output['histories'].items():
                    if signature(paths[sid]) != signatures[sid][1]:
                        raise ValueError('Resolution history changed during indexing')
                    result[sid] = value
                    if 'error' in value: continue
                    size = len(json.dumps(value).encode())
                    if size <= MAX_BYTES:
                        while self.entries and (self.size + size > MAX_BYTES or len(self.entries) >= 64):
                            _, old = self.entries.popitem(last=False); self.size -= old[2]
                        self.entries[signatures[sid][0]] = (signatures[sid][1], deepcopy(value), size)
                        self.size += size
            return result

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.kill(); await self.process.wait()


def main():
    started=time.monotonic()
    import socket
    def offline(*args, **kwargs): raise ValueError('Resolution replay network forbidden')
    socket.socket.connect = offline
    from app.dashboard.session_history import resolution_history
    from app.collection.continuous import rss, LIMITS
    from app.collection.odds_http import BudgetStop
    paths = json.loads(sys.stdin.buffer.read(65537))
    histories = {}
    for sid, folder in paths.items():
        try:
            histories[sid] = resolution_history(folder)
        except (ValueError, OSError, KeyError, BudgetStop) as exc:
            histories[sid] = dict(error=type(exc).__name__, reason=str(exc))
        if rss() >= LIMITS['rss_bytes']: raise ValueError('Resolution worker memory cap')
    output = json.dumps(dict(histories=histories, accounting=dict(
        peak_rss_bytes=rss(), rss_limit_bytes=LIMITS['rss_bytes'], deadline_seconds=SECONDS,
        folders=len(paths), elapsed_seconds=time.monotonic()-started, network='forbidden'))).encode()
    if len(output) > MAX_BYTES: raise ValueError('Resolution worker result bound')
    sys.stdout.buffer.write(output)


if __name__ == '__main__': main()
