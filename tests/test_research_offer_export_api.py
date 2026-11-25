"""Dated offer attachments begin before every frozen game has been read."""

import asyncio
from contextlib import nullcontext
import json
from threading import Event
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from app.dashboard.request_guard import dashboard_guard
from app.dashboard.research_workspace_api import BASE, mount
from app.storage.store import hashed


@pytest.mark.parametrize(
    "sizing", [None, dict(sizing_mode="fixed_profit", target_profit_usd="10")],
    ids=["legacy", "fixed-profit"],
)
def test_dated_offer_export_streams_partial_body_and_preserves_canonical_digest(sizing):
    run = "a" * 64
    fields = dict(date="2026-11-24", as_of="2026-11-24T23:51:46Z", minimum_ev="1/25",
                  report_revision="b" * 64, run_id=run, orders_submitted=0, provider_requests=0)
    if sizing is not None:
        fields["sizing"] = sizing
    games = [dict(game_id="one", offers=[]), dict(game_id="two", offers=[dict(line="-3/2")])]
    started, release = Event(), Event()
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def transaction(self):
            return nullcontext()

        def execute(self, statement):
            statements.append(statement)

    def read_game(_db, game, minimum, selected, *, sizing):
        assert minimum == fields["minimum_ev"]
        assert selected == {}
        assert sizing == fields.get("sizing")
        if game["game_id"] == "two":
            started.set()
            assert release.wait(5)
        return game

    async def check():
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        mount(app)
        with patch("app.dashboard.research_workspace_api.connect", side_effect=Connection), \
                patch("app.research.workspace.offer_export_plan", return_value=(fields, games, {})), \
                patch("app.research.workspace.offer_export_game", side_effect=read_game):
            async with TestClient(TestServer(app)) as client:
                try:
                    async with asyncio.timeout(3):
                        response = await client.get(f"{BASE}/runs/{run}/offers")
                        assert response.status == 200
                        assert response.headers["Content-Disposition"].endswith('predict-mens-d1-offers-2026-11-24-aaaaaaaaaaaa.json"')
                        assert await asyncio.to_thread(started.wait, 2)
                        prefix, _ = await response.content.readchunk()
                        first_game, _ = await response.content.readchunk()
                        assert prefix.endswith(b',"games":[')
                        assert json.loads(first_game) == games[0]
                        assert not response.content.at_eof()
                        other = await client.get(f"{BASE}/runs/{run}/offers")
                        second_prefix, _ = await other.content.readchunk()
                        assert second_prefix == prefix
                finally:
                    release.set()
                async with asyncio.timeout(3):
                    value = json.loads(prefix + first_game + await response.read())
                    assert json.loads(second_prefix + await other.read()) == value
                digest = value.pop("evidence_sha256")
                assert value == dict(fields, games=games)
                assert digest == hashed(value)
                assert statements.count("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY") == 6

    asyncio.run(check())
