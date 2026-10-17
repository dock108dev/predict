"""Served client identity, complete authored resources, and v1 preview checks."""
import importlib.util
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from app.dashboard.scanner_client_api import mount
from tests.sc04_preview import create_app

ROOT = Path(__file__).resolve().parents[1]


class ClientBinding(unittest.IsolatedAsyncioTestCase):
    async def test_actual_served_asset_identity_and_no_cache(self):
        app = web.Application()
        mount(app)
        async with TestClient(TestServer(app)) as client:
            r = await client.get('/api/scanner/client')
            value = await r.json()
            self.assertTrue(value['assets_valid'])
            self.assertEqual(r.headers['Cache-Control'], 'no-store')
            self.assertEqual(value['protocol'], 'predict-opportunity-scanner-1')
            original = Path.read_bytes
            def changed(path):
                return b'changed-runtime' if path.name == 'scanner.js' else original(path)
            with patch.object(Path, 'read_bytes', changed):
                self.assertFalse((await (await client.get('/api/scanner/client')).json())['assets_valid'])

    async def test_preview_whole_universe_filters_two_legs_and_revision_409(self):
        async with TestClient(TestServer(create_app())) as client:
            page = await (await client.get('/api/scanner?minimum_size=229&limit=100')).json()
            self.assertEqual(page['total_matching'], 1)
            self.assertIn('0129', page['rows'][0]['id'])
            single = await (await client.get('/api/scanner?venues=kalshi&limit=100')).json()
            self.assertEqual(single['rows'], [])
            r = await client.get('/api/scanner?offset=100&expected_revision=0')
            self.assertEqual(r.status, 409)


class Resources(unittest.TestCase):
    def test_generated_binding_and_complete_fixture_inventory(self):
        assets = ROOT / 'app/dashboard/opportunity_static/current'
        runtime = json.loads((assets / 'scanner-runtime.json').read_text())
        for name, expected in runtime['assets'].items():
            self.assertEqual(sha256((assets / name).read_bytes()).hexdigest(), expected)
        fixture = json.loads((ROOT / 'tests/fixtures/sc04/workload.json').read_text())
        self.assertEqual(len(fixture['rows']), 130)
        self.assertEqual(len({r['occurrence_id'] for r in fixture['rows']}), 20)
        sides = {p['native_key'][-1] for r in fixture['rows'] for p in r['positions']}
        self.assertEqual(sides, {'YES', 'NO', 'Long', 'Short'})
        schema = json.loads((ROOT / 'docs/contracts/predict-opportunity-scanner-1.schema.json').read_text())
        self.assertEqual(set(fixture['page']), set(schema['required']))
