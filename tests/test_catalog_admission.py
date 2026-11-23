"""Overlapping owner navigation waits without increasing read concurrency."""

import asyncio
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.dashboard import research_api
from app.dashboard.request_guard import dashboard_guard


class CatalogAdmission(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.release = asyncio.Event()
        self.saturated = asyncio.Event()
        self.active = self.entered = self.peak = 0
        self.reads = SimpleNamespace(games=lambda query: dict(rows=[], provider_requests=0),
            cleanup=lambda: None, close=lambda *args: None)

        async def joined(_logger, _operation, fn, *args):
            if fn is not self.reads.games:
                return fn(*args)
            self.active += 1
            self.entered += 1
            self.peak = max(self.peak, self.active)
            if self.active == research_api.CATALOG_READ_CAPACITY:
                self.saturated.set()
            try:
                await self.release.wait()
                return fn(*args)
            finally:
                self.active -= 1

        for change in (patch.object(research_api, 'CatalogReads', return_value=self.reads),
                patch('app.owned_work.joined_thread', side_effect=joined)):
            change.start()
            self.addCleanup(change.stop)
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        research_api.mount(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def occupy_capacity(self):
        requests = [asyncio.ensure_future(self.client.get('/api/research/games'))
            for _ in range(research_api.CATALOG_READ_CAPACITY)]
        await asyncio.wait_for(self.saturated.wait(), timeout=1)
        return requests

    async def test_fifth_navigation_waits_then_succeeds_at_the_existing_capacity(self):
        requests = await self.occupy_capacity()
        queued = asyncio.ensure_future(self.client.get('/api/research/games'))
        await asyncio.sleep(0)
        self.assertFalse(queued.done())
        self.assertEqual(self.entered, research_api.CATALOG_READ_CAPACITY)
        self.release.set()
        responses = await asyncio.gather(*requests, queued)
        self.assertEqual([response.status for response in responses], [200]*5)
        self.assertEqual(self.entered, 5)
        self.assertEqual(self.peak, research_api.CATALOG_READ_CAPACITY)

    async def test_admission_timeout_is_actionable_and_does_not_enter_or_leak_a_slot(self):
        requests = await self.occupy_capacity()
        with patch.object(research_api, 'CATALOG_ADMISSION_WAIT_SECONDS', 0.02):
            response = await self.client.get('/api/research/games')
        self.assertEqual(response.status, 503)
        self.assertEqual(response.headers['Retry-After'], '1')
        self.assertEqual((await response.json())['error'], 'Stored data reads are busy. Retry shortly.')
        self.assertEqual(self.entered, research_api.CATALOG_READ_CAPACITY)
        self.release.set()
        self.assertTrue(all(response.status == 200 for response in await asyncio.gather(*requests)))
        self.assertEqual((await self.client.get('/api/research/games')).status, 200)
        self.assertEqual(self.peak, research_api.CATALOG_READ_CAPACITY)
