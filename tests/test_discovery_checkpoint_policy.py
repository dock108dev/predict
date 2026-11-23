"""Recorded Live intent cannot select a retired automatic acquisition feed."""

import asyncio
import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from app.collection.activity_mode import DEFAULT_SETTINGS, project
from app.dashboard import current_pregame_api as api

AT = datetime(2026, 11, 22, tzinfo=timezone.utc)


@pytest.mark.parametrize("recorded_mode", ["monitor", "live"])
def test_effective_policy_preserves_recorded_settings_and_history(recorded_mode):
    row = dict(
        mode=recorded_mode,
        settings=dict(DEFAULT_SETTINGS, live_interval_seconds=90),
        revision=7,
        reason="selected",
        last_activity_at=AT,
        live_until=AT + timedelta(minutes=15),
    )
    runs = {"live": dict(id="historical", state="complete")}
    before = deepcopy((row, runs))
    status = project(row, at=AT, runs=runs)
    assert status["mode"] == status["requested_mode"] == recorded_mode
    assert status["effective_mode"] == "monitor"
    assert status["settings"] == row["settings"]
    assert status["runs"] == runs
    assert (row, runs) == before
    policy = status["acquisition_policy"]
    assert policy["data_type"] == "monitor"
    assert policy["initial_capture"] == "first_observed"
    assert policy["final_capture_seconds_before_start"] == 600
    assert policy["live_polling"] is False
    assert policy["separate_saved_game_refresh"] is False
    assert policy["discovery"] == dict(
        interval_seconds=1800,
        phase_seconds=1200,
        horizon_seconds=86400,
        continuous=True,
        known_games_billed=True,
    )


@pytest.mark.parametrize("path", ["/api/pregame", "/api/pregame/arbs"])
@pytest.mark.parametrize(
    "query,expected",
    [({}, "monitor"), ({"data_type": "live"}, "live"), ({"browse": "1"}, "all")],
)
def test_default_ev_and_arbs_use_monitor_and_allow_explicit_history(
    path, query, expected
):
    status = project(
        dict(
            mode="live",
            settings=deepcopy(DEFAULT_SETTINGS),
            revision=7,
            live_until=AT + timedelta(minutes=15),
        ),
        at=AT,
    )
    statements, selected = [], []
    db = SimpleNamespace(
        transaction=nullcontext, execute=lambda sql: statements.append(sql)
    )

    def read(connection, parameters, **kwargs):
        assert connection is db
        assert parameters["data_type"] == expected
        seconds = (
            DEFAULT_SETTINGS["live_window_seconds"]
            if expected == "live"
            else DEFAULT_SETTINGS["monitor_horizon_seconds"]
            if expected == "monitor"
            else None
        )
        assert parameters.get("_scope_seconds") == (str(seconds) if seconds else None)
        return dict(rows=[dict(legs=[])] if path.endswith("/arbs") else [], total=0)

    async def scenario():
        with (
            patch("app.collection.activity_mode.read_status", return_value=status),
            patch(
                "app.storage.pregame_cohorts.select",
                side_effect=lambda db, kind: selected.append(kind),
            ),
            patch("app.storage.current_pregame.read", side_effect=read),
            patch("app.storage.pregame_arbs.read", side_effect=read),
            patch("app.storage.pregame_quote_evidence.enrich", return_value=[]),
        ):
            request = SimpleNamespace(path=path, query=query)
            response = await api.response(request, connector=lambda: nullcontext(db))
            assert response.status == 200
            packet = json.loads(response.body)
            assert packet["data_type"] == expected
            assert packet["activity_mode"]["requested_mode"] == "live"
            assert packet["activity_mode"]["effective_mode"] == "monitor"

    asyncio.run(scenario())
    assert selected == [expected]
    assert all(sql.startswith("SET ") for sql in statements)
