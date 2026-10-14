"""Portable authored slate/loopback cases; no owner SQL, inputs or provider traffic."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
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


class FrozenTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return AT


def game(key, start="2026-10-16T00:15:00+00:00"):
    return dict(game_key=key, start_at=start, title=key, participants=[])


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
        bounds=dict(maximum_games=200, maximum_bytes=slate.MAX_BYTES),
    )


class Database:
    MAX_PENDING = 2

    def __init__(self):
        self.closed = False
        self.pending = {}
        self.calls = []
        self.info = dict(state="available", error=None, backlog_bytes=0)

    def status(self):
        return deepcopy(self.info)

    def request(self, key, policy):
        if self.closed:
            raise AssertionError("Closed local queue must not receive work")
        if len(self.pending) >= self.MAX_PENDING:
            raise ValueError("saved_calculation_queue_capacity")
        self.calls.append((key, policy))
        self.pending[key, policy.revision] = policy


class SlateRead(TestCase):
    def harness(self, games, values=None, failed=()):
        context = SimpleNamespace(
            engine="current-engine", catalog=lambda: dict(games=games)
        )
        values = values or {}
        store = object()
        bundles = [dict(game_key=g["game_key"]) for g in games]
        captured = []

        def selected(actual_store, bundle, policy, *, context):
            self.assertIs(actual_store, store)
            if bundle["game_key"] in failed:
                raise ValueError("private input details are not public errors")
            return bundle

        def restored(actual_store, key, policy, *, context):
            self.assertIs(actual_store, store)
            return deepcopy(values.get(key))

        def response(bundle, value, policy, **settings):
            captured.append((bundle, value, settings))
            return dict(
                game_key=bundle["game_key"],
                saved=value,
                original_source_at="2026-10-13T12:00:00+00:00",
            )

        patches = [
            patch.object(slate, "datetime", FrozenTime),
            patch.object(slate, "GameStore", return_value=store),
            patch.object(slate, "ReadContext", return_value=context),
            patch.object(slate, "discover", side_effect=lambda actual_store,**kwargs:[b for b in bundles if b['game_key']==kwargs['game']]),
            patch.object(slate, "view_bundle", side_effect=selected),
            patch.object(slate, "saved", side_effect=restored),
            patch.object(slate, "response", side_effect=response),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        return context, captured, mocks

    def test_all_upcoming_ordered_with_one_shared_read_context(self):
        games = [
            game("later", "2026-10-18T00:00:00+00:00"),
            game("old", "2026-10-13T00:00:00+00:00"),
            game("first"),
        ]
        context, _, mocks = self.harness(games)
        output, pending = slate.read(
            object(), DEFAULT_POLICY, view="odds", filter="all", stopped=False
        )
        self.assertEqual([g["game_key"] for g in output["games"]], ["first", "later"])
        self.assertEqual([b["game_key"] for b in output["boards"]], ["first", "later"])
        self.assertEqual(pending, ["first", "later"])
        self.assertEqual(output["as_of"], AT.isoformat())
        self.assertEqual(output["provider_requests"], 0)
        self.assertEqual(
            output["bounds"], dict(maximum_games=200, maximum_bytes=8388608)
        )
        self.assertEqual(mocks[2].call_count, 1)
        for mock in mocks[3:6]:
            for call in mock.call_args_list:
                self.assertIs(call.kwargs["context"], context)
        self.assertEqual([call.kwargs['game'] for call in mocks[3].call_args_list],['first','later'])
        self.assertTrue(all(call.kwargs['cache'] is False for call in mocks[3].call_args_list))
        self.assertTrue(
            all(b["original_source_at"] != output["as_of"] for b in output["boards"])
        )

    def test_engine_changes_withdraw_authority_without_mutating_saved_inputs(self):
        values = dict(
            old=dict(engine_binding="predecessor", superseded=False),
            current=dict(engine_binding="current-engine", superseded=False),
            pending=dict(engine_binding="current-engine", superseded=True),
        )
        original = deepcopy(values)
        _, captured, _ = self.harness([game(k) for k in values], values)
        _, pending = slate.read(
            object(), DEFAULT_POLICY, view="arbs", filter="positive", stopped=False
        )
        flags = {b["game_key"]: v["engine_binding_changed"] for b, v, _ in captured}
        self.assertEqual(flags, dict(old=True, current=False, pending=False))
        self.assertEqual(pending, ["pending"])
        self.assertEqual(values, original)

    def test_one_bad_game_preserves_healthy_independent_boards(self):
        self.harness([game("healthy"), game("failed")], failed={"failed"})
        output, pending = slate.read(
            object(), DEFAULT_POLICY, view="ev", filter="all", stopped=True
        )
        self.assertEqual([b["game_key"] for b in output["boards"]], ["healthy"])
        self.assertEqual(
            output["errors"],
            [dict(game_key="failed", reason="game_inputs_unavailable")],
        )
        self.assertEqual(pending, ["healthy"])
        self.assertTrue(output["stopped"])

    def test_unknown_kickoff_is_retained_without_inventing_a_date(self):
        for start in (None, "unknown", "2026-10-16T00:00:00"):
            item = game("unknown", start)
            self.assertTrue(slate.upcoming(item, AT))
            self.assertEqual(item["start_at"], start)
        self.assertFalse(slate.upcoming(game("at-kickoff", AT.isoformat()), AT))

    def test_game_capacity_refuses_before_building_financial_boards(self):
        _, _, mocks = self.harness([game(str(i)) for i in range(201)])
        with self.assertRaisesRegex(ValueError, "slate_game_capacity"):
            slate.read(
                object(), DEFAULT_POLICY, view="odds", filter="all", stopped=False
            )
        mocks[3].assert_not_called()
        mocks[6].assert_not_called()

    def test_total_serialized_capacity_is_explicit(self):
        self.harness([game("bounded")])
        with (
            patch.object(slate, "encoded", return_value=b"x" * 10),
            patch.object(slate, "MAX_BYTES", 9),
        ):
            with self.assertRaisesRegex(ValueError, "slate_response_byte_capacity"):
                slate.read(
                    object(), DEFAULT_POLICY, view="odds", filter="all", stopped=False
                )
        with (
            patch.object(slate, "encoded", return_value=b"x" * 9),
            patch.object(slate, "MAX_BYTES", 9),
        ):
            output, _ = slate.read(
                object(), DEFAULT_POLICY, view="odds", filter="all", stopped=False
            )
            self.assertEqual(len(output["boards"]), 1)


class SlateQueue(TestCase):
    def test_duplicate_work_coalesces_and_existing_queue_capacity_wins(self):
        database = Database()
        database.pending["existing", DEFAULT_POLICY.revision] = DEFAULT_POLICY
        slate.schedule(database, ["existing", "new", "over-capacity"], DEFAULT_POLICY)
        self.assertEqual([key for key, _ in database.calls], ["new"])
        self.assertEqual(len(database.pending), database.MAX_PENDING)

    def test_closed_and_refused_local_queue_receive_no_more_work(self):
        database = Database()
        database.closed = True
        slate.schedule(database, ["one"], DEFAULT_POLICY)
        self.assertEqual(database.calls, [])
        database.closed = False
        with patch.object(
            database, "request", side_effect=ValueError("capacity")
        ) as request:
            slate.schedule(database, ["one", "two"], DEFAULT_POLICY)
            self.assertEqual(request.call_count, 1)


class SlateLoopback(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.provider = InjectedTestProvider()
        self.provider.database_games = []
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

    async def test_loopback_shape_settings_storage_and_local_scheduling(self):
        self.provider.database.info = dict(
            state="unavailable", error="current_database_storage_cap", backlog_bytes=12
        )
        self.read.return_value = (body(), ["first", "second", "third"])
        response = await self.client.get(
            "/api/boards/slate?view=odds&filter=all&amount=500&buffer=0.01&benchmark_venue=novig"
        )
        self.assertEqual(response.status, 202)
        value = await response.json()
        self.assertEqual(value["storage"], self.provider.database.info)
        self.assertEqual(value["provider_requests"], 0)
        policy = self.read.call_args.args[1]
        self.assertEqual(str(policy.requested_amount_usd), "500")
        self.assertEqual(policy.benchmark_venue, "novig")
        self.assertEqual(
            [key for key, _ in self.provider.database.calls], ["first", "second"]
        )
        self.provider.acquire.assert_not_called()
        self.db.execute.assert_called_once_with(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )

    async def test_invalid_crossed_or_duplicate_queries_refuse_before_sql(self):
        for query in (
            "view=invalid",
            "filter=invalid",
            "game=mandatory-selection",
            "result_id=old",
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
        self.assertEqual(response.status, 202)
        self.assertTrue(self.read.call_args.kwargs["stopped"])
        self.assertEqual(self.provider.database.calls, [])
        self.provider.acquire.assert_not_called()

    async def test_failure_is_bounded_and_public_without_provider_fallback(self):
        self.read.side_effect = ValueError("slate_response_byte_capacity")
        response = await self.client.get("/api/boards/slate")
        self.assertEqual(response.status, 409)
        self.assertEqual(
            (await response.json())["reason"], "slate_response_byte_capacity"
        )
        self.assertEqual(self.provider.database.calls, [])
        self.provider.acquire.assert_not_called()

    async def test_final_cap_includes_appended_storage_metadata(self):
        self.provider.database.info = dict(state="available", error="large-status" * 40)
        limit = len(slate.encoded(body())) + 10
        self.assertLessEqual(len(slate.encoded(body())), limit)
        with patch.object(slate, "MAX_BYTES", limit):
            response = await self.client.get("/api/boards/slate")
        self.assertEqual(response.status, 409)
        self.assertEqual(
            (await response.json())["reason"], "slate_response_byte_capacity"
        )
        self.assertEqual(self.provider.database.calls, [])
