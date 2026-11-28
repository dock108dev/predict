"""Authored slate units and installed Dashboard HTTP boundary checks."""

from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

from aiohttp import ClientSession
from aiohttp.test_utils import TestClient, TestServer

from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard import comparison_slate as slate
from app.dashboard.multi_game_server import create_app
from app.storage.store import hashed
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner

AT = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


class SlateRead(TestCase):
    def read(self,**options):
        from contextlib import nullcontext
        from tests.test_current_board_reads import latest_frame
        db=MagicMock();db.transaction.return_value=nullcontext()
        with patch('app.storage.latest_board.snapshot',return_value=latest_frame()),patch('app.storage.latest_board.slate_authority',return_value=hashed(['authored-authority',False])),patch('app.storage.latest_board.calculate_current',side_effect=AssertionError('request finance forbidden')):
            return slate.read(db,DEFAULT_POLICY,view='odds',filter='all',stopped=False,**options)

    def test_current_rows_produce_v2_page_without_saved_queue(self):
        output,pending=self.read()
        self.assertEqual(output['version'],'predict-comparison-slate-2')
        self.assertEqual(output['bounds']['maximum_games'],len(output['games']))
        self.assertEqual(output['bounds']['maximum_page_games'],50)
        self.assertTrue(output['boards'])
        self.assertTrue(output['coverage']['complete'])
        self.assertEqual(output['provider_requests'],0)
        self.assertEqual(pending,[])

    def test_changed_cross_page_revision_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError,'current_slate_changed'):
            self.read(expected_revision='retired-page-revision')

    def test_page_capacity_is_checked_before_inputs(self):
        for options in ({'offset':-1},{'limit':51},{'limit':0}):
            with self.subTest(options=options),self.assertRaisesRegex(ValueError,'slate_page_capacity'):
                self.read(**options)

    def test_later_page_requires_frozen_read_token(self):
        with self.assertRaisesRegex(ValueError, 'current_slate_read_token_required'):
            self.read(offset=500)

    def test_current_serialized_capacity_is_explicit(self):
        with patch.object(slate,'MAX_BYTES',1),self.assertRaisesRegex(ValueError,'slate_response_byte_capacity'):
            self.read()


class DashboardLoopback(IsolatedAsyncioTestCase):
    path = "/api/research/dashboard"

    async def asyncSetUp(self):
        self.provider = InjectedTestProvider()
        self.provider.database_mode = True
        self.provider.dispatch = True
        self.provider.acquire = MagicMock(
            side_effect=AssertionError("Provider acquisition is forbidden")
        )
        self.db = MagicMock()
        self.db.execute.return_value.fetchone.return_value = {"at": AT}
        connection = MagicMock()
        connection.__enter__.return_value = self.db
        self.connect = self.enterContext(
            patch("app.dashboard.research_api.connect", return_value=connection)
        )
        self.read = self.enterContext(patch(
            "app.storage.native_trading.dashboard",
            return_value=dict(rows=[], offset=2, total=2),
        ))
        original = ClientSession._request

        async def loopback_only(session, method, url, **kwargs):
            if urlparse(str(url)).hostname not in ("127.0.0.1", "localhost", "::1"):
                raise AssertionError("External provider traffic is forbidden")
            return await original(session, method, url, **kwargs)

        self.enterContext(patch.object(ClientSession, "_request", new=loopback_only))
        app = create_app(owner=owner(), sessions={}, current_provider=self.provider)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addCleanup(self.provider.acquire.assert_not_called)

    async def test_read_forwards_scope_and_uses_bounded_sql_snapshot(self):
        from app.storage.native_trading import HORIZON

        response = await self.client.get(self.path, params={
            "sport": "NCAAB", "family": "spread", "venue": "novig",
            "view": "all", "offset": 2, "limit": 5,
        })
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {
            "schema": "predict-dashboard-1", "rows": [], "offset": 2, "total": 2,
            "read_at": AT.isoformat(), "provider_requests": 0,
            "scheduled_calculations": 0,
        })
        self.read.assert_called_once_with(
            self.db, at=AT, until=AT + HORIZON, sport="NCAAB", family="spread",
            venue="novig", view="all", offset=2, limit=5,
        )
        self.db.transaction.assert_called_once_with()
        self.assertEqual(
            [call.args[0] for call in self.db.execute.call_args_list],
            [
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
                "SET LOCAL statement_timeout='10s'",
                "SET LOCAL jit='off'",
                "SELECT transaction_timestamp() at",
            ],
        )

    async def test_invalid_or_duplicate_queries_refuse_before_sql(self):
        for query in (
            "view=invalid",
            "sport=unknown",
            "family=first-period",
            "venue=novig&venue=kalshi",
            "offset=-1",
            "limit=0",
            "limit=101",
            "provider_refresh=true",
        ):
            with self.subTest(query=query):
                response = await self.client.get(self.path + "?" + query)
                self.assertEqual(response.status, 422, query)
        self.connect.assert_not_called()
        self.read.assert_not_called()

    async def test_cross_origin_read_refuses_before_sql(self):
        response = await self.client.get(
            self.path, headers={"Origin": "https://provider.invalid"}
        )
        self.assertEqual(response.status, 403)
        self.connect.assert_not_called()
        self.read.assert_not_called()

    async def test_stopped_owner_can_read_saved_dashboard_without_scheduling(self):
        self.provider.dispatch = False
        response = await self.client.get(self.path)
        self.assertEqual(response.status, 200)
        value = await response.json()
        self.assertEqual((value["provider_requests"], value["scheduled_calculations"]), (0, 0))
        self.read.assert_called_once()

    async def test_storage_error_returns_public_failure_without_provider_fallback(self):
        self.read.side_effect = RuntimeError("fixture-private-database-detail")
        response = await self.client.get(self.path)
        self.assertEqual(response.status, 503)
        self.assertEqual(await response.json(), {"error": "Local data unavailable"})
        self.connect.assert_called_once_with()
        self.read.assert_called_once()
