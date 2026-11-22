"""Passive checkpoint API boundaries and revision-bound browser downloads."""

from contextlib import nullcontext
import json
from pathlib import Path
from types import ModuleType
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch
import sys

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.dashboard.research_api import mount
from app.dashboard.request_guard import dashboard_guard
import app.research


class ReadConnection:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def transaction(self):
        return nullcontext(self)

    def execute(self, statement):
        self.statements.append(statement)


class ExperimentAPI(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = json.loads(Path('tests/fixtures/experiment-workspace.json').read_text())
        self.statements = []
        self.owner = ModuleType('app.research.experiment')
        self.owner.catalog = Mock(return_value=self.fixture['listing'])
        self.owner.detail = Mock(return_value=self.fixture['detail'])
        self.owner.export_game = Mock(return_value=self.fixture['export'])
        patches = (
            patch.dict(sys.modules, {'app.research.experiment': self.owner}),
            patch.object(app.research, 'experiment', self.owner, create=True),
            patch('app.dashboard.research_api.connect', side_effect=lambda: ReadConnection(self.statements)),
        )
        for value in patches:
            value.start()
            self.addCleanup(value.stop)
        application = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        mount(application)
        self.client = TestClient(TestServer(application))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.query = dict(id='game-captured', revision=self.fixture['detail']['revision'])

    async def test_list_detail_and_complete_export_are_passive_captured_reads(self):
        response = await self.client.get('/api/research/experiment?include_context=1&limit=10&offset=0')
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())['cases'], self.fixture['listing']['cases'])
        self.assertEqual(self.owner.catalog.call_args.kwargs, dict(include_context=True, limit=10, offset=0))
        response = await self.client.get('/api/research/experiment', params=self.query)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())['revision'], self.query['revision'])
        response = await self.client.get('/api/research/experiment', params=dict(self.query, export='1'))
        self.assertEqual(response.status, 200)
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        value = await response.json()
        self.assertEqual(value, self.fixture['export'])
        self.assertEqual(value['dependencies'][0]['payload']['fee_input']['classification'], 'synthetic_fixture_fee')
        self.assertEqual(self.owner.export_game.call_args.kwargs, dict(revision=self.query['revision']))
        # Detail/export use the storage owner's own snapshot transaction; only
        # the catalog receives a transaction from the API wrapper.
        self.assertEqual(self.statements.count('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'), 1)
        self.assertEqual(self.statements.count("SET statement_timeout='10s'"), 3)
        self.assertTrue(all(statement.startswith('SET ') for statement in self.statements))

    async def test_changed_revision_returns_refresh_without_replacing_captured_evidence(self):
        self.owner.detail.side_effect = ValueError('experiment_revision_changed')
        response = await self.client.get('/api/research/experiment', params=self.query)
        self.assertEqual(response.status, 409)
        value = await response.json()
        self.assertTrue(value['refresh_required'])
        self.assertEqual(value['provider_requests'], 0)
        self.owner.export_game.assert_not_called()

    async def test_invalid_selection_never_opens_database_or_dispatches_acquisition(self):
        for query in (
            dict(id='game-captured'), dict(revision='a'*64), dict(export='1'),
            dict(self.query, revision='not-a-hash'), dict(self.query, include_context='1'),
            dict(include_context='false'), dict(limit='101'), dict(offset='-1'),
            dict(refresh_source='1'), dict(self.query, export='yes'),
        ):
            with self.subTest(query=query):
                response = await self.client.get('/api/research/experiment', params=query)
                self.assertEqual(response.status, 422, await response.text())
        self.assertEqual(self.statements, [])
        self.owner.catalog.assert_not_called()
        self.owner.detail.assert_not_called()
        self.owner.export_game.assert_not_called()

    async def test_unknown_game_has_safe_operator_reason(self):
        self.owner.detail.side_effect = ValueError('experiment_game_unknown')
        response = await self.client.get('/api/research/experiment', params=self.query)
        self.assertEqual(response.status, 422)
        self.assertIn('Unknown tracked experiment game', await response.text())
