"""Ordinary SQL mode cannot accidentally serve its empty injected-state fallback."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from aiohttp.test_utils import TestClient, TestServer

from app.dashboard.multi_game_server import create_app
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner


class CurrentRouteRetirement(unittest.IsolatedAsyncioTestCase):
    async def test_sql_installation_explicitly_retires_old_state_reads(self):
        committed = dict(dispatch_enabled=False, runtime_id='fixture-runtime',
                         data_runtime=dict(healthy=True, global_stopped=True))
        provider = SimpleNamespace(database_mode=True, status=Mock(return_value=committed))
        app = create_app(owner=owner(), current_provider=provider)
        async with TestClient(TestServer(app)) as client:
            for path in ('/api/current', '/api/current/details', '/api/current/prices',
                         '/api/current/updates', '/api/current/changes', '/api/comparison',
                         '/api/arbs', '/api/selections/old-token'):
                response = await client.get(path)
                self.assertEqual(response.status, 410, path)
                value = await response.json()
                self.assertEqual(value['error'], 'current_state_transport_retired')
                self.assertEqual(value['provider_requests'], 0)
                self.assertEqual(value['current_api'], '/api/research/dashboard')
                self.assertEqual(value['current_url'], '/')
            provider.status.assert_not_called()
            status = await client.get('/api/admin/status')
            self.assertEqual(status.status, 200)
            self.assertEqual(await status.json(), committed)
            dashboard = await client.get('/')
            self.assertEqual(dashboard.status, 200)
            self.assertIn('/view/current/dashboard.js', await dashboard.text())
            redirect = await client.get('/current/coverage', allow_redirects=False)
            self.assertEqual(redirect.status, 302)
            self.assertEqual(redirect.headers['Location'], '/data?evidence=mens-d1')
            data = await client.get(redirect.headers['Location'])
            self.assertEqual(data.status, 200)
            self.assertIn('id="data-mens-d1"', await data.text())
            page = await client.get('/settings')
            self.assertEqual(page.status, 200)
            self.assertIn('id="storage"', await page.text())
            for module in ('dashboard.js', 'data-workbench.js', 'mens-d1-coverage.js', 'settings.js'):
                self.assertEqual((await client.get('/view/current/' + module)).status, 200, module)
            for asset in ('coverage.js','coverage.css','coverage-model.js','coverage-view.js'):
                self.assertEqual((await client.get('/current/assets/' + asset)).status, 404, asset)

    async def test_installed_coverage_route_reaches_the_retained_reader_and_export(self):
        from app.dashboard import mens_d1_coverage_api as coverage

        app = create_app(owner=owner(), current_provider=SimpleNamespace(database_mode=True))
        database = Mock()
        database.transaction.return_value = nullcontext()
        day = '2026-11-23'
        value = dict(date=day, provider_requests=0, orders_submitted=0)
        async with TestClient(TestServer(app)) as client:
            with (patch.object(coverage, 'connect', return_value=nullcontext(database)),
                  patch.object(coverage, 'coverage_view', return_value=value) as retained):
                path = '/api/workspace/mens-d1'
                for query in (dict(date=day), dict(date=day, export='1')):
                    response = await client.get(path, params=query)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(await response.json(), value)
                self.assertIn(f'predict-mens-d1-{day}.json', response.headers['Content-Disposition'])
        self.assertEqual(retained.call_count, 2)
        retained.assert_called_with(database, day, None, None)
        database.execute.assert_any_call('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')

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
