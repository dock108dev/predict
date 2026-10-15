"""Portable authored slate/loopback cases; no owner SQL, inputs or provider traffic."""

from copy import deepcopy
from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

from aiohttp import ClientSession
from aiohttp.test_utils import TestClient, TestServer

from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard import comparison_slate as slate
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner

AT = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def body():
    return dict(
        version=slate.VERSION,
        view="odds",
        filter="all",
        policy=DEFAULT_POLICY.to_dict(),
        games=[],
        boards=[],
        errors=[],
        stopped=False,
        as_of=AT.isoformat(),
        provider_requests=0,
        bounds=dict(maximum_games=500, maximum_page_games=50, maximum_bytes=slate.MAX_BYTES),
    )


class Database:
    def __init__(self):self.info=dict(state='available',error=None)
    def status(self):return deepcopy(self.info)


class SlateRead(TestCase):
    def read(self,**options):
        from contextlib import nullcontext
        from tests.test_current_board_reads import context
        c=context();db=MagicMock();db.transaction.return_value=nullcontext()
        with patch.object(slate,'ReadContext',return_value=c):
            return slate.read(db,DEFAULT_POLICY,view='odds',filter='all',stopped=False,**options)

    def test_current_rows_produce_v2_page_without_saved_queue(self):
        output,pending=self.read()
        self.assertEqual(output['version'],'predict-comparison-slate-2')
        self.assertEqual(output['bounds']['maximum_games'],500)
        self.assertEqual(output['bounds']['maximum_page_games'],50)
        self.assertTrue(output['boards'])
        self.assertTrue(output['coverage']['complete'])
        self.assertEqual(output['provider_requests'],0)
        self.assertEqual(pending,[])

    def test_changed_cross_page_revision_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError,'current_slate_changed'):
            self.read(expected_revision='retired-page-revision')

    def test_page_capacity_is_checked_before_inputs(self):
        for options in ({'offset':500},{'offset':-1},{'limit':51},{'limit':0}):
            with self.subTest(options=options),self.assertRaisesRegex(ValueError,'slate_page_capacity'):
                self.read(**options)

    def test_current_serialized_capacity_is_explicit(self):
        with patch.object(slate,'MAX_BYTES',1),self.assertRaisesRegex(ValueError,'slate_response_byte_capacity'):
            self.read()


class SlateLoopback(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.provider = InjectedTestProvider()
        self.provider.database_mode = True
        self.provider.closed = False
        self.provider.closing = False
        self.provider.dispatch = True
        self.provider.database = Database()
        self.provider.acquire = MagicMock(
            side_effect=AssertionError("Provider acquisition is forbidden")
        )
        self.db = MagicMock()
        connection = MagicMock()
        connection.__enter__.return_value = self.db
        self.connect_patch = patch(
            "app.dashboard.comparison_board_api.connect", return_value=connection
        )
        self.slate_patch = patch.object(slate, "read", return_value=(body(), []))
        self.connect = self.connect_patch.start()
        self.read = self.slate_patch.start()
        self.addCleanup(self.connect_patch.stop)
        self.addCleanup(self.slate_patch.stop)
        original = ClientSession._request

        async def loopback_only(session, method, url, **kwargs):
            if urlparse(str(url)).hostname not in ("127.0.0.1", "localhost", "::1"):
                raise AssertionError(
                    "External provider traffic is forbidden in this test"
                )
            return await original(session, method, url, **kwargs)

        self.network_patch = patch.object(ClientSession, "_request", new=loopback_only)
        self.network_patch.start()
        self.addCleanup(self.network_patch.stop)
        app = create_app(owner=owner(), sessions={}, current_provider=self.provider)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_loopback_shape_settings_storage_without_scheduling(self):
        self.provider.database.info = dict(
            state="unavailable", error="current_database_storage_cap", backlog_bytes=12
        )
        self.read.return_value = (body(), ["first", "second", "third"])
        response = await self.client.get(
            "/api/boards/slate?view=odds&filter=all&amount=500&buffer=0.01&benchmark_venue=novig"
        )
        self.assertEqual(response.status, 200)
        value = await response.json()
        self.assertEqual(value["storage"], self.provider.database.info)
        self.assertEqual(value["provider_requests"], 0)
        policy = self.read.call_args.args[1]
        self.assertEqual(str(policy.requested_amount_usd), "500")
        self.assertEqual(policy.benchmark_venue, "novig")
        self.assertFalse(hasattr(self.provider.database,'request'))
        self.provider.acquire.assert_not_called()
        self.db.execute.assert_not_called()  # The slate reader owns its SQL transaction.

    async def test_invalid_crossed_or_duplicate_queries_refuse_before_sql(self):
        for query in (
            "view=invalid",
            "filter=invalid",
            "game=mandatory-selection",
            "view=odds&view=ev",
            "amount=NaN",
            "benchmark_venue=unknown",
            "provider_refresh=true",
            "amount=" + ("1" * 257),
        ):
            response = await self.client.get("/api/boards/slate?" + query)
            self.assertEqual(response.status, 422, query)
        self.connect.assert_not_called()
        self.read.assert_not_called()
        self.provider.acquire.assert_not_called()

    async def test_cross_origin_read_refuses_before_sql(self):
        response = await self.client.get(
            "/api/boards/slate", headers={"Origin": "https://provider.invalid"}
        )
        self.assertEqual(response.status, 403)
        self.connect.assert_not_called()

    async def test_stopped_read_does_not_schedule(self):
        self.provider.dispatch = False
        self.read.return_value = (body(), ["first"])
        response = await self.client.get("/api/boards/slate?view=arbs&filter=all")
        self.assertEqual(response.status, 200)
        self.assertTrue(self.read.call_args.kwargs["stopped"])
        self.assertFalse(hasattr(self.provider.database,'request'))
        self.provider.acquire.assert_not_called()

    async def test_failure_is_bounded_and_public_without_provider_fallback(self):
        self.read.side_effect = ValueError("slate_response_byte_capacity")
        response = await self.client.get("/api/boards/slate")
        self.assertEqual(response.status, 409)
        self.assertEqual(
            (await response.json())["reason"], "slate_response_byte_capacity"
        )
        self.assertFalse(hasattr(self.provider.database,'request'))
        self.provider.acquire.assert_not_called()

    async def test_final_cap_includes_appended_storage_metadata(self):
        self.provider.database.info = dict(state="available", error="large-status" * 40)
        limit = len(slate.encoded(body())) + 10
        self.assertLessEqual(len(slate.encoded(body())), limit)
        with patch("app.dashboard.comparison_board_api.MAX_BYTES", limit):
            response = await self.client.get("/api/boards/slate")
        self.assertEqual(response.status, 409)
        self.assertEqual(
            (await response.json())["reason"], "board_response_byte_capacity"
        )
        self.assertFalse(hasattr(self.provider.database,'request'))
