"""Ordinary SQL mode cannot accidentally serve its empty injected-state fallback."""
import unittest
from aiohttp.test_utils import TestClient, TestServer
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner


class CurrentRouteRetirement(unittest.IsolatedAsyncioTestCase):
    async def test_sql_installation_explicitly_retires_old_state_reads(self):
        provider = InjectedTestProvider()
        provider.database_games = ['the_odds_api:authored']
        app = create_app(owner=owner(), sessions={}, current_provider=provider)
        async with TestClient(TestServer(app)) as client:
            for path in ('/api/current', '/api/current/details', '/api/current/prices',
                         '/api/current/updates', '/api/current/changes', '/api/comparison',
                         '/api/arbs', '/api/coverage', '/api/selections/old-token',
                         '/current/coverage'):
                response = await client.get(path)
                self.assertEqual(response.status, 410, path)
                value = await response.json()
                self.assertEqual(value['error'], 'current_state_transport_retired')
                self.assertEqual(value['provider_requests'], 0)
            self.assertEqual((await client.get('/api/admin/status')).status, 200)
            self.assertEqual((await client.get('/')).status, 200)

    async def test_explicit_injected_mode_keeps_its_own_transport(self):
        app = create_app(owner=owner(), sessions={}, current_provider=InjectedTestProvider())
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/api/current')
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['schema'], 'predict-current-1')
