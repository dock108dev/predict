"""Share public desk arrival bursts and encode list packets once per read."""
import asyncio
from collections import OrderedDict
from gzip import compress
import json
from time import monotonic

from aiohttp import web

from app.storage.store import stamp


BURST_SECONDS = 0.5
MAX_DESK_READS = 16
MAX_CACHED_BYTES = 4 * 1024 * 1024
PUBLIC_LIST_FIELDS = frozenset({
    'basis', 'group', 'league', 'family', 'venue', 'ranked', 'phase', 'lines',
    'layout', 'view', 'offset', 'limit', 'summary', 'browse_odds', 'metric',
    'search', 'day', 'timezone', 'time_from', 'time_to', 'minimum', 'profit', 'positive',
})


def common_page(query, options):
    if (query.get('layout') != 'desk' or query.get('summary') != '1' or not options
            or query.get('phase') != 'pregame' or query.get('limit') not in ('12', '25')
            or options[2] or set(query) - PUBLIC_LIST_FIELDS
            or any(query.get(key) for key in ('search', 'day', 'time_from', 'time_to', 'minimum', 'profit'))):
        return None
    common = {key: value for key, value in query.items() if value}
    return ('list', tuple(sorted(common.items())))


def timing_header(timings):
    return ', '.join(f'{name};dur={duration:.3f}' for name, duration in timings.items())


class ReadBurst:
    """Bound distinct work while sharing in-flight and briefly reusable reads."""

    def __init__(self, clock=monotonic):
        self.clock = clock
        self.pending = {}
        self.ready = OrderedDict()
        self.active = set()
        self.closed = False

    async def read(self, key, load, *, reuse=BURST_SECONDS):
        arrived = self.clock()
        while not self.closed:
            if key in self.ready:
                expiry, value, _ = self.ready[key]
                if self.clock() < expiry:
                    self.ready.move_to_end(key)
                    return value, True
                del self.ready[key]
            if key not in self.pending:
                break
            value, deadline = await asyncio.shield(self.pending[key])
            # A request arriving after the first boundary cannot reuse an
            # in-flight response captured before that boundary.
            if arrived < deadline:
                return value, True
        if self.closed or len(self.active) >= MAX_DESK_READS:
            raise web.HTTPServiceUnavailable(reason='Price reads are busy')

        async def fill():
            try:
                value, deadline, size = await load()
                now = self.clock()
                expires = min(now + reuse, deadline)
                if key is not None and expires > now and size <= MAX_CACHED_BYTES:
                    self.ready[key] = (expires, value, size)
                    while (len(self.ready) > MAX_DESK_READS
                            or sum(entry[2] for entry in self.ready.values()) > MAX_CACHED_BYTES):
                        self.ready.popitem(last=False)
                return value, deadline
            finally:
                self.pending.pop(key, None)

        task = asyncio.create_task(fill())
        self.active.add(task)
        if key is not None:
            self.pending[key] = task

        def retire(completed):
            self.active.remove(completed)
            if self.pending.get(key) is completed:
                del self.pending[key]
            # If every client disconnected, still retrieve this task's error.
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(retire)
        value, _ = await asyncio.shield(task)
        return value, False

    async def close(self, _app):
        self.closed = True
        tasks = list(self.active)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def encode(page, *, at, started):
    raw = json.dumps(page, separators=(',', ':')).encode()
    packed = compress(raw, compresslevel=1, mtime=0) if len(raw) >= 2048 else None
    deadline = page.get('refresh_at')
    expires = started + max(0, (stamp(deadline) - at).total_seconds()) if deadline else float('inf')
    return (raw, packed), expires, len(raw) + len(packed or b'')


def gzip_allowed(value):
    wildcard = None
    for entry in value.lower().split(','):
        coding, _, parameters = entry.strip().partition(';')
        quality = 1 if not parameters else 0
        if parameters.strip().startswith('q='):
            try:
                quality = float(parameters.strip()[2:])
            except ValueError:
                pass
        if coding == 'gzip':
            return 0 < quality <= 1
        if coding == '*':
            wildcard = quality
    return wildcard is not None and 0 < wildcard <= 1


def packet_response(request, packet, timings, *, shared=False):
    raw, packed = packet
    headers = {'Server-Timing': timing_header(timings), 'Vary': 'Accept-Encoding'}
    if shared:
        headers['Server-Timing'] = 'desk_shared;dur=0'
    if packed and gzip_allowed(request.headers.get('Accept-Encoding', '')):
        headers['Content-Encoding'] = 'gzip'
        raw = packed
    return web.Response(body=raw, content_type='application/json', headers=headers)
