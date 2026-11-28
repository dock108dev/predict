"""Forward committed native revisions to visible, scoped Dashboard tabs."""

import asyncio
from datetime import datetime, timezone
import json
from threading import Event

import psycopg
from aiohttp import web

from app.collection.current_aggregate_policy import MARKET_FAMILIES
from app.collection.current_policy import SPORTS
from app.comparison.snapshot_fee_outcome import VENUES
from app.diagnostics import failure
from app.owned_work import joined_thread
from app.storage.native_trading import DASHBOARD_UPDATES_CHANNEL

from .local_security import HEADERS, PublicRequestError


MAX_STREAMS = 4
READY = b'data: {"ready":true}\n\n'
STREAM_HEADERS = {"Content-Type": "text/event-stream", **HEADERS}


class DashboardUpdates:
    def __init__(self, connector):
        self.connector = connector
        self.stopping = Event()
        self.clients = {}
        self.listener = None
        self.ready = False

    def receive(self, loop):
        # A dedicated autocommit session listens once for all open tabs.
        with self.connector() as db:
            db.execute(f"LISTEN {DASHBOARD_UPDATES_CHANNEL}")
            loop.call_soon_threadsafe(self.connected)
            while not self.stopping.is_set():
                notices = [entry.payload for entry in db.notifies(timeout=0.5, stop_after=24)]
                if notices:
                    loop.call_soon_threadsafe(self.publish, notices)

    @staticmethod
    def offer(queue, event):
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(event)

    def connected(self):
        if self.stopping.is_set():
            return
        self.ready = True
        for queue in self.clients:
            self.offer(queue, READY)

    def publish(self, notices):
        if self.stopping.is_set():
            return
        pending = {}
        # NOTIFY reaches the listener after commit. Timestamp the observation
        # separately from the calculation, request and source clocks.
        observed = datetime.now(timezone.utc).isoformat()
        for payload in notices:
            try:
                notice = json.loads(payload)
            except ValueError:
                continue
            if (not isinstance(notice, dict) or set(notice) != {"sport", "family", "venue", "revision"}
                    or notice["sport"] not in SPORTS
                    or notice["family"] not in MARKET_FAMILIES.values() or notice["venue"] not in VENUES
                    or not isinstance(notice["revision"], str) or len(notice["revision"]) != 64):
                continue
            for queue, (_, filters) in self.clients.items():
                if all(notice[key] == value for key, value in filters.items()):
                    pending[queue] = b"data: " + json.dumps(dict(notice, commit_observed_at=observed)).encode() + b"\n\n"
        for queue, event in pending.items():
            self.offer(queue, event)

    async def listen(self):
        loop = asyncio.get_running_loop()
        while not self.stopping.is_set():
            try:
                await joined_thread(__name__, "dashboard_update_listener", self.receive, loop)
            except psycopg.Error as error:
                if self.ready:
                    failure(__name__, "dashboard_update_listener", error)
                self.ready = False
                await asyncio.sleep(1)

    async def stream(self, request):
        filters = dict(request.query)
        if (set(filters) - {"sport", "family", "venue"} or filters.get("sport") not in (None, *SPORTS)
                or filters.get("family") not in (None, *MARKET_FAMILIES.values())
                or filters.get("venue") not in (None, *VENUES)):
            raise PublicRequestError("Unknown Dashboard update filter.")
        if request.method == "HEAD":
            return web.Response(headers=STREAM_HEADERS)
        for queue, (subscriber, _) in tuple(self.clients.items()):
            if subscriber.transport is None or subscriber.transport.is_closing():
                self.clients.pop(queue)
                self.offer(queue, None)
        if self.stopping.is_set() or len(self.clients) >= MAX_STREAMS:
            raise web.HTTPServiceUnavailable(headers={"Retry-After": "2"})
        queue = asyncio.Queue(maxsize=1)
        self.clients[queue] = request, filters
        if self.listener is None:
            self.listener = asyncio.create_task(self.listen())
        elif self.ready:
            self.offer(queue, READY)
        response = web.StreamResponse(headers=STREAM_HEADERS)
        try:
            await response.prepare(request)
            while request.transport is not None and not request.transport.is_closing():
                try:
                    event = await asyncio.wait_for(queue.get(), 10)
                except TimeoutError:
                    event = b": connection heartbeat\n\n"
                if event is None:
                    break
                async with asyncio.timeout(2):
                    await response.write(event)
        except (ConnectionError, TimeoutError):
            pass
        finally:
            self.clients.pop(queue, None)
        return response

    async def close(self, _):
        self.stopping.set()
        for queue in self.clients:
            self.offer(queue, None)
        if self.listener is not None:
            self.listener.cancel()
            try:
                await self.listener
            except asyncio.CancelledError:
                pass
