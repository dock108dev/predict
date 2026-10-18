"""Ordinary SQL mode cannot accidentally serve its empty injected-state fallback."""
import unittest
from aiohttp.test_utils import TestClient, TestServer
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner


class CurrentRouteRetirement(unittest.IsolatedAsyncioTestCase):
    async def test_sql_installation_explicitly_retires_old_state_reads(self):
        provider = InjectedTestProvider()
        provider.database_mode = True
        app = create_app(owner=owner(), sessions={}, current_provider=provider)
        async with TestClient(TestServer(app)) as client:
            for path in ('/api/current', '/api/current/details', '/api/current/prices',
                         '/api/current/updates', '/api/current/changes', '/api/comparison',
                         '/api/arbs', '/api/selections/old-token'):
                response = await client.get(path)
                self.assertEqual(response.status, 410, path)
                value = await response.json()
                self.assertEqual(value['error'], 'current_state_transport_retired')
                self.assertEqual(value['provider_requests'], 0)
            self.assertEqual((await client.get('/api/admin/status')).status, 200)
            self.assertEqual((await client.get('/')).status, 200)
            page = await client.get('/current/coverage')
            self.assertEqual(page.status, 200)
            self.assertIn('Coverage', await page.text())
            for asset in ('coverage.js','coverage.css','coverage-model.js','coverage-view.js'):
                self.assertEqual((await client.get('/current/assets/'+asset)).status, 200, asset)

    async def test_sql_coverage_routes_reach_the_new_retained_reader(self):
        import logging
        from types import SimpleNamespace
        from aiohttp import web
        from app.dashboard.request_guard import dashboard_guard
        app=web.Application(middlewares=[dashboard_guard(SimpleNamespace(database_mode=True),logger=logging.getLogger(__name__))])
        reached=[]
        async def retained(req):
            reached.append(req.path)
            return web.json_response(dict(schema='predict-broad-coverage-1',provider_requests=0))
        app.router.add_get('/api/coverage',retained)
        app.router.add_get('/current/coverage',retained)
        async with TestClient(TestServer(app)) as client:
            for path in ('/api/coverage','/current/coverage'):
                reply=await client.get(path)
                self.assertEqual(reply.status,200)
                self.assertEqual((await reply.json())['provider_requests'],0)
        self.assertEqual(reached,['/api/coverage','/current/coverage'])

    async def test_explicit_injected_mode_keeps_its_own_transport(self):
        app = create_app(owner=owner(), sessions={}, current_provider=InjectedTestProvider())
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/api/current')
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['schema'], 'predict-current-1')


class OrdinaryExecutionRetirement(unittest.TestCase):
    def test_retired_ordinary_workers_and_queue_are_absent(self):
        from app.collection import current_database
        from app.dashboard import comparison_slate
        self.assertFalse(hasattr(current_database,'catch_up_segments'))
        self.assertFalse(hasattr(current_database.DatabasePipeline,'request'))
        self.assertFalse(hasattr(current_database.DatabasePipeline,'MAX_PENDING'))
        self.assertFalse(hasattr(comparison_slate,'schedule'))


    def test_retired_game_cli_option_fails_before_service_construction(self):
        from unittest.mock import patch
        from app.dashboard.opportunity_board import main
        with patch('sys.argv',['predict','--game','the_odds_api:old']), \
             patch('app.collection.current_service.CurrentService') as service, \
             self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code,2)
        service.assert_not_called()

    def test_database_mode_requires_explicit_boolean_and_retires_game_selection(self):
        from app.collection.current_service import CurrentService
        from app.collection.current_policy import DEFAULT
        for mode in ([],None,1,'true'):
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'Explicit current database mode'):
                CurrentService(config=DEFAULT,database_mode=mode)
        with self.assertRaises(TypeError):CurrentService(config=DEFAULT,database_games=['the_odds_api:old'])


class CurrentModeWiring(unittest.IsolatedAsyncioTestCase):
    async def test_sql_mode_constructs_only_the_direct_owner_once(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import AsyncMock,patch
        from app.collection.current_service import CurrentService
        from app.collection.current_policy import DEFAULT
        from app.collection.current_database import DatabaseIngressSink
        with TemporaryDirectory() as root:
            service=CurrentService(config=dict(DEFAULT,enabled=False),directory=Path(root)/'service',database_mode=True)
            lifecycle=SimpleNamespace(start=AsyncMock())
            store=object()
            with patch('app.collection.current_database.DatabasePipeline',return_value=lifecycle) as owner, \
                 patch.object(service,'_start_sources',new_callable=AsyncMock) as sources:
                await service.start(store)
                await service.start(store)
            owner.assert_called_once_with(service)
            lifecycle.start.assert_awaited_once_with()
            sources.assert_awaited_once_with()
            self.assertIsInstance(service.sink,DatabaseIngressSink)
            self.assertIs(service.sink.store,store)
            for name in ('journal','bootstrap_task','retain','database_games'):
                self.assertFalse(hasattr(service,name))
