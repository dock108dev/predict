"""Isolated API bounds and single-owner checks; fresh socket-only database."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from aiohttp.test_utils import TestClient,TestServer
from app.collection.environment import Environment
from app.collection.server import create_app
from app.storage.store import Store
from app.collection.storage import PROVENANCE

class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='e6-api-');self.output=Path(self.tmp.name)
        self.env=await asyncio.to_thread(Environment.create)
        self.app=create_app(self.env,self.output)
        self.client=TestClient(TestServer(self.app));await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();await asyncio.to_thread(self.env.remove,self.output/'cleanup');self.tmp.cleanup()
    async def test_idle_and_no_auto_start(self):
        r=await self.client.get('/api/status');value=await r.json()
        self.assertEqual(value['state'],'idle')
        with self.env.connect() as db:self.assertEqual(db.execute('SELECT count(*) AS n FROM capture_session').fetchone()['n'],0)
    async def test_wrong_origin_and_invalid_bounds(self):
        response=await self.client.post('/api/start',json={'seconds':30},headers={'Origin':'https://example.invalid'})
        self.assertEqual(response.status,403)
        response=await self.client.post('/api/start',json={'seconds':901})
        self.assertEqual(response.status,422)
    async def test_single_owner_lock(self):
        with self.assertRaises(BlockingIOError):create_app(self.env,self.output)
    async def test_session_cap_survives_missing_result_files(self):
        with self.env.connect() as db:
            store=Store(db)
            for _ in range(8):store.start('synthetic','synthetic',PROVENANCE)
        response=await self.client.post('/api/start',json={'seconds':30})
        self.assertEqual(response.status,409)
    async def test_saved_path_validation(self):
        response=await self.client.get('/api/saved/not-a-session')
        self.assertEqual(response.status,400)
