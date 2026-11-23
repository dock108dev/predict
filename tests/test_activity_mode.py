"""Controlled-clock discovery and retained activity intent with paid guards."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.collection.activity_mode import (
    DEFAULT_SETTINGS,
    eligible,
    project,
    validate_settings,
    monitor_schedule,
)
from app.collection.activity_collector import (
    ActivityCollector,
    ActivityBudgetDelayed,
    budget_admit,
)
from app.collection.sportsgameodds_adapter import Page
from app.collection.sportsgameodds_ledger import ObjectLedger

AT = datetime(2026, 11, 19, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "detail",
    [
        "INTERNAL_MARKER database internal.example.invalid SELECT private_column",
        "INTERNAL_MARKER private configuration /srv/private/settings.json",
    ],
)
def test_owner_settings_http_never_exposes_value_error_details(monkeypatch, detail):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from app.dashboard import activity_mode_api

    def reject(**kwargs):
        raise ValueError(detail)

    monkeypatch.setattr(activity_mode_api.activity_mode, "patch", reject)

    async def scenario():
        app = web.Application()
        activity_mode_api.mount(app)
        async with TestClient(TestServer(app)) as client:
            response = await client.patch(
                "/api/admin/activity-mode", json={"mode": "live"}
            )
            assert response.status == 400
            assert await response.text() == "Invalid activity mode or settings"

    asyncio.run(scenario())


def row(mode="monitor"):
    return dict(
        mode=mode,
        settings=dict(DEFAULT_SETTINGS, monitor_phase_seconds=0),
        revision=1,
        reason="selected",
        last_activity_at=AT if mode == "live" else None,
        live_until=AT + timedelta(minutes=15) if mode == "live" else None,
    )


def test_monitor_clock_boundaries_custom_phase_legacy_settings_and_dst():
    from zoneinfo import ZoneInfo

    settings = deepcopy(DEFAULT_SETTINGS)
    legacy = dict(settings)
    legacy.pop("monitor_phase_seconds")
    assert validate_settings(legacy) == settings
    assert validate_settings({"monitor_phase_seconds": 0}, partial=True) == {
        "monitor_phase_seconds": 0
    }
    for minute, second, due, next_minute in (
        (19, 59, False, 20),
        (20, 0, True, 20),
        (20, 30, True, 20),
        (21, 1, False, 50),
        (49, 59, False, 50),
        (50, 0, True, 50),
    ):
        at = AT + timedelta(minutes=minute, seconds=second)
        plan = monitor_schedule(settings, at=at)
        assert plan["due"] is due
        assert datetime.fromisoformat(plan["next_monitor_at"]).minute == next_minute
    claimed = (AT + timedelta(minutes=20)).isoformat()
    assert not monitor_schedule(
        settings, at=AT + timedelta(minutes=20, seconds=10), last_slot=claimed
    )["due"]
    assert (
        monitor_schedule(
            dict(settings, monitor_phase_seconds=300), at=AT + timedelta(minutes=4)
        )["next_monitor_at"]
        == (AT + timedelta(minutes=5)).isoformat()
    )
    eastern = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 20, tzinfo=eastern, fold=0)
    second = first.replace(fold=1)
    assert (
        monitor_schedule(settings, at=first)["current_slot_at"]
        != monitor_schedule(settings, at=second)["current_slot_at"]
    )
    assert monitor_schedule(
        settings,
        at=second,
        last_slot=monitor_schedule(settings, at=first)["current_slot_at"],
    )["due"]
    spring = datetime(2026, 3, 8, 1, 59, 59, tzinfo=eastern)
    following = datetime.fromisoformat(
        monitor_schedule(settings, at=spring)["next_monitor_at"]
    ).astimezone(eastern)
    assert (following.hour, following.minute) == (3, 20)
    rollback = monitor_schedule(
        settings,
        at=AT + timedelta(minutes=20),
        last_slot=(AT + timedelta(minutes=50)).isoformat(),
    )
    assert (
        not rollback["due"]
        and rollback["next_monitor_at"]
        == (AT + timedelta(hours=1, minutes=20)).isoformat()
    )


def test_monitor_restart_claims_recent_slot_once_and_skips_old_catchup():
    async def scenario():
        store, worker = Store(), Worker()
        store.value["settings"]["monitor_phase_seconds"] = 1200
        worker.events["near"]["starts_at"] = (AT + timedelta(minutes=30)).isoformat()
        owner = ActivityCollector(worker, store=store)
        worker.at = AT + timedelta(minutes=19)
        await owner.tick()
        assert not store.runs and not worker.calls
        worker.at = AT + timedelta(minutes=20, seconds=30)
        await owner.tick()
        assert (
            len(store.runs) == 1
            and store.runs[0]["monitor_slot_at"]
            == (AT + timedelta(minutes=20)).isoformat()
        )
        restarted = ActivityCollector(worker, store=store)
        worker.at += timedelta(seconds=10)
        calls = len(worker.calls)
        await restarted.tick()
        assert len(store.runs) == 1 and len(worker.calls) == calls
        worker.at = AT + timedelta(minutes=50)
        await restarted.tick()
        assert (
            len(store.runs) == 2
            and store.runs[-1]["monitor_slot_at"] == worker.at.isoformat()
        )
        # A legacy off-phase run has no durable slot claim and cannot suppress
        # the newly configured20-minute boundary.
        old = Store()
        old.value["settings"]["monitor_phase_seconds"] = 1200
        old.runs = [
            dict(
                id="legacy",
                kind="monitor",
                started_at=(AT + timedelta(minutes=19)).isoformat(),
                event_count=1,
            )
        ]
        worker = Worker()
        worker.at = AT + timedelta(minutes=20)
        await ActivityCollector(worker, store=old).tick()
        assert len(old.runs) == 2

    asyncio.run(scenario())


def test_monitor_idle_reports_actual_next_slot_without_dispatch_or_control_changes():
    async def scenario():
        store, worker = Store(), Worker()
        store.value['settings']['monitor_phase_seconds'] = 1200
        before=deepcopy(store.value)
        worker.phase='initializing'
        worker.at=AT+timedelta(minutes=19)
        owner=ActivityCollector(worker,store=store)
        await owner.tick()
        assert worker.phase=='waiting_for_cycle'
        assert worker.metrics['next_refresh_at']==(AT+timedelta(minutes=20)).isoformat()
        assert not worker.calls and not store.runs and not store.updates
        assert store.value==before and not worker.stopped and not worker.paused
        assert 'last_received_at' not in worker.metrics
        worker.at=AT+timedelta(minutes=20)
        await owner.tick()
        assert worker.calls and store.runs[0]['monitor_slot_at']==worker.at.isoformat()
        assert store.value==before and not worker.stopped and not worker.paused
    asyncio.run(scenario())


def test_active_monitor_overrun_coalesces_latest_slot_and_phase_edit_never_cancels():
    async def scenario():
        store, worker = Store(), Worker()
        store.value["settings"]["monitor_phase_seconds"] = 1200
        owner = ActivityCollector(worker, store=store)

        async def active(status):
            if (
                worker.at >= AT + timedelta(minutes=52)
                and owner.monitor["run"]["id"] == "1"
            ):
                await owner.save(owner.monitor, state="complete")
                owner.monitor = None

        owner.monitor_turn = active
        worker.at = AT + timedelta(minutes=20)
        await owner.tick()
        original = owner.monitor
        store.value["settings"]["monitor_phase_seconds"] = 300
        worker.at = AT + timedelta(minutes=21)
        await owner.tick()
        assert owner.monitor is original and not store.updates
        store.value["settings"]["monitor_phase_seconds"] = 1200
        worker.at = AT + timedelta(minutes=52)
        await owner.tick()
        assert len(store.runs) == 1 and owner.monitor is None
        worker.at += timedelta(seconds=1)
        await owner.tick()
        assert (
            len(store.runs) == 2
            and store.runs[-1]["monitor_slot_at"]
            == (AT + timedelta(minutes=50)).isoformat()
        )
        assert owner.monitor_due == AT + timedelta(hours=1, minutes=20)
        await owner.tick()
        assert len(store.runs) == 2

    asyncio.run(scenario())


def test_horizon_change_closes_partial_walk_and_waits_for_next_discovery_slot():
    async def scenario():
        store, worker = Store(), Worker()
        store.value["settings"]["monitor_phase_seconds"] = 1200
        worker.service.config["sports"] = ["NFL", "NBA"]
        worker.at = AT + timedelta(minutes=20)
        owner = ActivityCollector(worker, store=store)
        await owner.tick()
        assert len(worker.calls) == 1 and owner.monitor is not None
        store.value["settings"]["monitor_horizon_seconds"] = 7200
        store.value["revision"] = 2
        worker.at += timedelta(minutes=1)
        await owner.tick()
        assert len(worker.calls) == 1 and len(store.runs) == 1
        assert owner.monitor is None
        assert store.updates[-1][1]["state"] == "partial"
        assert store.updates[-1][1]["reason"] == "settings_changed"
        worker.at = AT + timedelta(minutes=50)
        await owner.tick()
        assert len(worker.calls) == 2 and len(store.runs) == 2
        assert store.runs[-1]["monitor_slot_at"] == worker.at.isoformat()
        assert store.runs[-1]["scope_end_at"] == (worker.at + timedelta(hours=2)).isoformat()

    asyncio.run(scenario())


def test_monitor_discovers_each_league_without_extra_saved_game_requests():
    async def scenario():
        store, worker = Store(), Worker()
        store.value["settings"]["monitor_phase_seconds"] = 1200
        worker.at = AT + timedelta(minutes=20)
        worker.service.config["sports"] = ["NFL", "NBA"]
        worker.events = {
            name: dict(
                event_id=name,
                league=league,
                phase="pregame",
                status={},
                starts_at=(AT + timedelta(minutes=minute)).isoformat(),
            )
            for name, league, minute in (
                ("a-far", "NFL", 240),
                ("z-near", "NBA", 25),
                ("y-sooner", "NFL", 24),
            )
        }
        owner = ActivityCollector(worker, store=store)
        for _ in range(6):
            await owner.tick()
        params = [params for _, params in worker.calls]
        assert len(params) == 2
        assert [p["leagueID"] for p in params] == ["NFL", "NBA"]
        assert all("eventIDs" not in p and not p.get("includeAltLines") for p in params)
        assert all(
            p["startsBefore"] == (worker.at + timedelta(hours=24)).isoformat()
            for p in params
            if "leagueID" in p
        )
        assert owner.monitor is None and len(store.runs) == 1
        assert store.updates[-1][1]["state"] == "complete"
        assert store.updates[-1][1]["event_count"] == 3

    asyncio.run(scenario())


def test_discovery_walks_all_cursor_pages_then_waits_for_the_next_slot():
    async def scenario():
        store, worker = Store(), Worker()
        original = worker._fetch

        async def fetch(params):
            page = await original(params)
            return Page(page.events if not params.get("cursor") else (), page.quotes,
                        "next-page" if not params.get("cursor") else None,
                        page.receipt_sha256)

        worker._fetch = fetch
        owner = ActivityCollector(worker, store=store)
        await owner.tick()
        assert owner.monitor is not None
        assert store.updates[-1][1]["progress"]["cursor"] == "next-page"
        await owner.tick()
        await owner.tick()
        assert len(worker.calls) == 2 and len(store.runs) == 1
        assert [params.get("cursor") for _, params in worker.calls] == [None, "next-page"]
        assert all(params["leagueID"] == "NFL" and "eventIDs" not in params
                   for _, params in worker.calls)
        assert owner.monitor is None and store.updates[-1][1]["state"] == "complete"
        assert store.updates[-1][1]["event_count"] == 1

    asyncio.run(scenario())


def test_passive_reads_expire_live_without_renewing_activity_or_source_clocks():
    value = row("live")
    before = deepcopy(value)
    assert project(value, at=AT + timedelta(minutes=14))["mode"] == "live"
    expired = project(value, at=AT + timedelta(minutes=15))
    assert expired["mode"] == "monitor" and expired["reason"] == "inactivity"
    assert value == before
    assert project(row(), at=AT)["mode"] == "monitor"


def test_configurable_pregame_windows_preserve_kickoff_and_status_boundaries():
    status = project(row("live"), at=AT)

    def event(name, seconds, **values):
        return dict(
            event_id=name,
            phase="pregame",
            starts_at=(AT + timedelta(seconds=seconds)).isoformat(),
            status={},
            **values,
        )

    events = [
        event("now", 0),
        event("near", 1),
        event("edge", 3600),
        event("far", 3601),
    ]
    events += [
        dict(events[1], event_id="inplay", phase="live"),
        dict(events[1], event_id="started", status={"started": True}),
    ]
    assert [e["event_id"] for e in eligible(events, status, at=AT)] == ["near", "edge"]
    assert eligible(events, project(row(), at=AT), at=AT) == []
    assert [
        e["event_id"]
        for e in eligible(events, project(row(), at=AT), kind="monitor", at=AT)
    ] == ["near", "edge", "far"]
    for invalid in (
        {"live_interval_seconds": True},
        {"inactivity_seconds": 0},
        {"unknown": 1},
    ):
        with pytest.raises(ValueError):
            validate_settings(invalid, partial=True)
    assert (
        validate_settings({"monitor_horizon_seconds": None}, partial=True)[
            "monitor_horizon_seconds"
        ]
        is None
    )


class Store:
    def __init__(self):
        self.value = row()
        self.runs = []
        self.updates = []

    def status(self, at):
        runs = {
            run["kind"]: dict(
                run,
                state=next(
                    (
                        values["state"]
                        for prior, values in reversed(self.updates)
                        if prior["id"] == run["id"]
                    ),
                    "running",
                ),
                event_count=0,
            )
            for run in self.runs
        }
        return project(self.value, at=at, runs=runs)

    def begin(self, kind, status, at):
        run = dict(
            id=str(len(self.runs) + 1),
            kind=kind,
            started_at=at.isoformat(),
            scope_start_at=at.isoformat(),
            scope_end_at=(
                at
                + timedelta(
                    seconds=status["settings"]["monitor_horizon_seconds"]
                    if kind == "monitor"
                    else status["settings"]["live_window_seconds"]
                )
            ).isoformat(),
            settings_revision=status["revision"],
        )
        self.runs.append(run)
        return run

    def update(self, run, **values):
        self.updates.append((deepcopy(run), values))


class Worker:
    def __init__(self):
        self.at = AT
        self.ledger = None
        self.window_id = None
        self.collection_run = None
        self.activity_status = None
        self.metrics = {}
        self.max_discovery_pages = 100
        self.service = SimpleNamespace(
            config={"sports": ["NFL"], "aggregate_sports": []}
        )
        self.events = {
            "near": dict(
                event_id="near",
                league="NFL",
                phase="pregame",
                starts_at=(AT + timedelta(minutes=20)).isoformat(),
                status={},
            )
        }
        self.calls = []
        self.stopped = False
        self.paused = False

    def now(self):
        return self.at

    def controls(self):
        return dict(stopped=self.stopped, source_paused=self.paused)

    def params(
        self,
        *,
        league=None,
        starts_after=None,
        cursor=None,
        event_ids=None,
        include_alternates=False,
    ):
        if league:
            return dict(
                leagueID=league,
                startsAfter=starts_after,
                limit=2,
                **({"cursor": cursor} if cursor else {}),
            )
        return dict(
            eventIDs=",".join(event_ids),
            limit=len(event_ids),
            includeAltLines=include_alternates,
        )

    async def _fetch(self, params):
        self.calls.append((deepcopy(self.collection_run), deepcopy(params)))
        return Page(
            tuple(
                e
                for e in self.events.values()
                if datetime.fromisoformat(e["starts_at"]) > self.at
                and (
                    not params.get("eventIDs")
                    or e["event_id"] in params["eventIDs"].split(",")
                )
                and (not params.get("leagueID") or e["league"] == params["leagueID"])
            ),
            (),
            None,
            "a" * 64,
        )


@pytest.mark.parametrize("empty", [False, True])
def test_live_intent_adds_no_saved_game_requests_or_empty_minute_runs(empty):
    async def scenario():
        store, worker = Store(), Worker()
        if empty:
            worker.events = {}
        owner = ActivityCollector(worker, store=store)
        await owner.tick()
        assert [r["kind"] for r in store.runs] == ["monitor"]
        monitor_due = owner.monitor_due
        store.value = row("live")
        store.value["revision"] = 2
        worker.at = AT + timedelta(seconds=30)
        await owner.tick()
        assert [r["kind"] for r in store.runs] == ["monitor"]
        assert owner.monitor_due == monitor_due
        intent = deepcopy(store.value)
        worker.at += timedelta(seconds=1)
        await owner.tick()
        assert len(worker.calls) == 1
        worker.at = AT + timedelta(seconds=90)
        await owner.tick()
        assert len(worker.calls) == 1 and len(store.runs) == 1
        store.value["settings"]["live_interval_seconds"] = 1
        store.value["settings"]["live_window_seconds"] = 120
        worker.at += timedelta(seconds=1)
        await owner.tick()
        assert len(worker.calls) == 1 and len(store.runs) == 1
        store.value = intent
        worker.at = AT + timedelta(minutes=15)
        await owner.tick()
        assert len(worker.calls) == 1 and store.value == intent
        worker.at = AT + timedelta(minutes=30)
        await owner.tick()
        assert [r["kind"] for r in store.runs].count("monitor") == 2
        assert len(worker.calls) == 2
        assert all(run["kind"] == "monitor" and "leagueID" in params
                   for run, params in worker.calls)
        assert (
            next(params for _, params in worker.calls if "leagueID" in params)[
                "startsBefore"
            ]
            == (AT + timedelta(hours=24)).isoformat()
        )
        assert worker.collection_run is None

    asyncio.run(scenario())


def test_live_and_mode_settings_cannot_clear_source_stop_or_pause():
    async def scenario():
        for stopped, paused in ((True, False), (False, True)):
            store, worker = Store(), Worker()
            store.value = row("live")
            worker.stopped = stopped
            worker.paused = paused
            await ActivityCollector(worker, store=store).tick()
            assert worker.calls == [] and store.runs == []
            assert (worker.stopped, worker.paused) == (stopped, paused)

    asyncio.run(scenario())


def test_operational_caps_include_held_exposure_without_resolving_it(tmp_path):
    ledger = ObjectLedger(tmp_path / "objects.sqlite3")
    ledger.create_window(
        "account:window",
        limit=100000,
        initial_used=0,
        reserve=10000,
        reset_at=AT + timedelta(days=30),
        requests_per_minute=100,
    )
    ledger.reserve(
        "account:window", "uncertain", objects=300, now=AT - timedelta(minutes=5)
    )
    with pytest.raises(ActivityBudgetDelayed):
        budget_admit(ledger, "account:window", 1, AT)
    assert ledger.status("account:window")["held"] == 300
    ledger.interrupt("uncertain", evidence="fixture interrupted transport")
    with pytest.raises(ActivityBudgetDelayed):
        budget_admit(ledger, "account:window", 1, AT)
    assert ledger.status("account:window")["interrupted"] == 300
    budget_admit(ledger, "account:window", 1, AT + timedelta(minutes=11))
    daily = ObjectLedger(tmp_path / "daily.sqlite3")
    daily.create_window(
        "account:window",
        limit=100000,
        initial_used=0,
        reserve=10000,
        reset_at=AT + timedelta(days=30),
        requests_per_minute=100,
    )
    daily.reserve(
        "account:window", "earlier", objects=16800, now=AT - timedelta(hours=2)
    )
    daily.resolve(
        "earlier",
        charged=16800,
        evidence="fixture accumulated earlier charges",
        now=AT - timedelta(hours=2),
    )
    with pytest.raises(ActivityBudgetDelayed):
        budget_admit(daily, "account:window", 1, AT)


def test_activity_live_never_enables_in_game_collection_even_with_legacy_flag():
    from app.collection.current_policy import DEFAULT
    from app.collection.sportsgameodds_worker import SportsGameOddsWorker

    service = SimpleNamespace(
        config=dict(DEFAULT, live_enabled=True),
        activity_mode_enabled=True,
        dispatch=True,
        globally_stopped=False,
        paused_sources=set(),
    )
    worker = SportsGameOddsWorker(
        service,
        now=lambda: AT,
        activity_reader=lambda **kw: project(row("live"), at=kw["at"]),
    )
    worker.collection_run = {"kind": "live"}
    worker.activity_status = project(row("live"), at=AT)
    worker.events = {
        "near": dict(
            event_id="near",
            phase="pregame",
            starts_at=(AT + timedelta(minutes=10)).isoformat(),
            status={},
        )
    }
    assert worker.request_in_scope({"eventIDs": "near"})
    worker.events["near"]["phase"] = "live"
    assert not worker.request_in_scope({"eventIDs": "near"})
    assert not worker.request_in_scope(
        {
            "leagueID": "NFL",
            "startsAfter": AT.isoformat(),
            "started": True,
            "live": True,
        }
    )


def test_live_revocation_during_account_wait_and_after_reservation_blocks_dispatch(
    tmp_path,
):
    from app.collection.current_policy import DEFAULT, PregameWindowClosed
    from app.collection.sportsgameodds_worker import SportsGameOddsWorker
    from app.collection.sportsgameodds_collector import GuardedPageCollector
    from unittest.mock import AsyncMock

    async def scenario(stage):
        state = row("live")
        worker = SportsGameOddsWorker(
            SimpleNamespace(
                config=deepcopy(DEFAULT),
                activity_mode_enabled=True,
                dispatch=True,
                globally_stopped=False,
                paused_sources=set(),
            ),
            now=lambda: AT,
            activity_reader=lambda **kw: project(state, at=kw["at"]),
        )
        worker.collection_run = {"kind": "live"}
        worker.events = {
            "near": dict(
                event_id="near",
                phase="pregame",
                starts_at=(AT + timedelta(minutes=10)).isoformat(),
                status={},
            )
        }
        ledger = ObjectLedger(tmp_path / (stage + ".sqlite3"))
        reset = AT + timedelta(days=30)
        ledger.create_window(
            "account:window",
            limit=100000,
            initial_used=0,
            reserve=10000,
            reset_at=reset,
            requests_per_minute=50,
        )
        waiting, release = asyncio.Event(), asyncio.Event()

        async def usage():
            if stage == "account":
                waiting.set()
                await release.wait()
            return dict(
                used=0, limit=100000, reset_at=reset, requests_per_minute=50, at=AT
            )

        checks = 0

        async def eligible(params):
            nonlocal checks
            checks += 1
            if stage == "reservation" and checks == 3:
                waiting.set()
                await release.wait()
            return await worker.request_in_scope_async(params)

        transport = SimpleNamespace(fetch=AsyncMock())
        collector = GuardedPageCollector(
            ledger,
            "account:window",
            transport,
            controls=worker.controls,
            account_usage=usage,
            eligible=eligible,
        )
        task = asyncio.create_task(
            collector.fetch(worker.params(event_ids=["near"]), "fixture", now=AT)
        )
        await asyncio.wait_for(waiting.wait(), 1)
        state["mode"] = "monitor"
        state["live_until"] = None
        release.set()
        with pytest.raises(PregameWindowClosed):
            await task
        transport.fetch.assert_not_awaited()
        assert ledger.status("account:window")["held"] == 0
        assert not worker.service.globally_stopped and not worker.service.paused_sources
        if stage == "reservation":
            with ledger._connect() as db:
                assert db.execute(
                    "SELECT status,charged FROM sgo_object_reservation"
                ).fetchone() == ("resolved", 0)

    asyncio.run(scenario("account"))
    asyncio.run(scenario("reservation"))


def test_current_archive_backlog_blocks_paid_dispatch_but_historical_gaps_do_not():
    async def scenario():
        store, worker = Store(), Worker()
        original = store.status
        store.status = lambda at: dict(
            original(at),
            retention=dict(staged_bytes=32 * 1024 * 1024, skipped_observations=10),
        )
        owner = ActivityCollector(worker, store=store)
        await owner.tick()
        assert worker.calls == [] and store.updates[-1][1]["state"] == "budget_delayed"
        assert store.updates[-1][1]["reason"] == "archive_backlog"
        worker.at += timedelta(seconds=30)
        store.status = lambda at: dict(
            original(at), retention=dict(staged_bytes=0, skipped_observations=10)
        )
        await owner.tick()
        assert len(worker.calls) == 1

    asyncio.run(scenario())


def test_sgo_envelope_tags_each_observation_without_renewing_source_timestamps():
    from app.collection.current_policy import DEFAULT
    from app.collection.sportsgameodds_worker import SportsGameOddsWorker
    from tests.test_sportsgameodds_adapter import parse, response

    page = parse(response())
    original = [deepcopy(q) for q in page.quotes]
    run = dict(
        id="fixture-run",
        kind="monitor",
        started_at=AT.isoformat(),
        scope_start_at=AT.isoformat(),
        scope_end_at=(AT + timedelta(hours=24)).isoformat(),
        settings_revision=1,
    )
    worker = SportsGameOddsWorker(
        SimpleNamespace(
            config=deepcopy(DEFAULT),
            dispatch=True,
            globally_stopped=False,
            paused_sources=set(),
            states={},
        )
    )
    prepared, _ = worker._prepare_page(page, DEFAULT["ingress_bytes"], run)
    envelope, _ = next(worker.admit.operation(worker, **prepared))
    assert (
        envelope["collection_mode"] == "monitor" and envelope["collection_run"] == run
    )
    assert all(r["quote"]["times"]["source_at"] for r in envelope["records"])
    assert list(page.quotes) == original


def test_prior_live_run_remains_partial_history_without_replacement_jobs():
    async def scenario():
        store, worker = Store(), Worker()
        store.value = row("live")
        store.value["settings"]["monitor_phase_seconds"] = 1200
        store.runs = [dict(id="prior-live", kind="live", started_at=AT.isoformat())]
        worker.at = AT + timedelta(minutes=1)
        intent = deepcopy(store.value)
        owner = ActivityCollector(worker, store=store)
        await owner.tick()
        live = [values for run, values in store.updates if run["kind"] == "live"]
        assert (
            live[-1]["state"] == "partial"
            and live[-1]["reason"] == "discovery_checkpoint_policy"
        )
        worker.at += timedelta(minutes=1)
        await owner.tick()
        assert len(store.runs) == 1 and not worker.calls
        assert store.value == intent

    asyncio.run(scenario())


def test_final_async_eligibility_rechecks_source_controls_and_releases_unused_reservation(
    tmp_path,
):
    from app.collection.current_policy import DEFAULT
    from app.collection.sportsgameodds_worker import SportsGameOddsWorker
    from app.collection.sportsgameodds_collector import GuardedPageCollector
    from unittest.mock import AsyncMock

    async def scenario(stage):
        state = row("live")
        backlog = {"bytes": 0}
        service = SimpleNamespace(
            config=deepcopy(DEFAULT),
            activity_mode_enabled=True,
            dispatch=True,
            globally_stopped=False,
            paused_sources=set(),
        )
        worker = SportsGameOddsWorker(
            service,
            now=lambda: AT,
            activity_reader=lambda **kw: dict(
                project(state, at=kw["at"]), staged_bytes=backlog["bytes"]
            ),
        )
        worker.collection_run = {"kind": "live"}
        worker.events = {
            "near": dict(
                event_id="near",
                phase="pregame",
                starts_at=(AT + timedelta(minutes=10)).isoformat(),
                status={},
            )
        }
        ledger = ObjectLedger(tmp_path / (stage + ".sqlite3"))
        reset = AT + timedelta(days=30)
        ledger.create_window(
            "account:window",
            limit=100000,
            initial_used=0,
            reserve=10000,
            reset_at=reset,
            requests_per_minute=50,
        )
        waiting, release = asyncio.Event(), asyncio.Event()
        checks = 0

        async def eligibility(params):
            nonlocal checks
            checks += 1
            if checks == 3:
                waiting.set()
                await release.wait()
                if stage == "error":
                    raise RuntimeError("fixture authority unavailable")
            return await worker.request_in_scope_async(params)

        async def usage():
            return dict(
                used=0, limit=100000, reset_at=reset, requests_per_minute=50, at=AT
            )

        transport = SimpleNamespace(fetch=AsyncMock())
        collector = GuardedPageCollector(
            ledger,
            "account:window",
            transport,
            controls=worker.controls,
            account_usage=usage,
            eligible=eligibility,
        )
        task = asyncio.create_task(
            collector.fetch(worker.params(event_ids=["near"]), "fixture", now=AT)
        )
        await asyncio.wait_for(waiting.wait(), 1)
        if stage == "stop":
            service.globally_stopped = True
        if stage == "pause":
            service.paused_sources.add("sportsgameodds")
        if stage == "archive":
            backlog["bytes"] = 32 * 1024 * 1024
        if stage == "cancel":
            task.cancel()
        else:
            release.set()
        with pytest.raises(
            asyncio.CancelledError if stage == "cancel" else RuntimeError
        ):
            await task
        transport.fetch.assert_not_awaited()
        with ledger._connect() as db:
            assert db.execute(
                "SELECT status,charged FROM sgo_object_reservation"
            ).fetchone() == ("resolved", 0)

    for stage in ("stop", "pause", "archive", "error", "cancel"):
        asyncio.run(scenario(stage))


def test_discovery_page_crossing_archive_threshold_blocks_the_next_league():
    from app.collection.current_policy import DEFAULT
    from app.collection.sportsgameodds_worker import SportsGameOddsWorker

    async def scenario():
        store = Store()
        store.value = row("live")
        stage = {"bytes": 31 * 1024 * 1024}
        original_status = store.status
        store.status = lambda at: dict(
            original_status(at), retention={"staged_bytes": stage["bytes"]}
        )
        calls = []
        service = SimpleNamespace(
            config=dict(deepcopy(DEFAULT), sports=["NFL", "NBA"], aggregate_sports=[]),
            activity_mode_enabled=True,
            dispatch=True,
            globally_stopped=False,
            paused_sources=set(),
        )
        worker = SportsGameOddsWorker(
            service,
            now=lambda: AT,
            activity_reader=lambda **kw: dict(
                project(store.value, at=kw["at"]), staged_bytes=stage["bytes"]
            ),
        )
        worker.events = {
            "near": dict(
                event_id="near",
                league="NFL",
                phase="pregame",
                starts_at=(AT + timedelta(minutes=10)).isoformat(),
                status={},
            )
        }

        async def fetch(params):
            assert await worker.request_in_scope_async(params)
            calls.append(params["leagueID"])
            stage["bytes"] = 32 * 1024 * 1024
            return Page(tuple(worker.events.values()), (), None, "a" * 64)

        worker._fetch = fetch
        owner = ActivityCollector(worker, store=store)
        await owner.tick()
        assert calls == ["NFL"]
        await owner.tick()
        assert calls == ["NFL"]
        assert store.updates[-1][0]["kind"] == "monitor"
        assert store.updates[-1][1]["reason"] == "archive_backlog"

    asyncio.run(scenario())


def test_discovery_budget_delay_resumes_same_run_without_live_jobs(monkeypatch):
    from app.collection import activity_collector as module

    async def scenario():
        store, worker = Store(), Worker()
        store.value = row("live")
        worker.service.config["sports"] = ["NFL", "NBA"]
        worker.ledger = object()
        worker.window_id = "fixture"
        params = worker.params
        worker.params = lambda **kw: dict(params(**kw), limit=1)
        slots = {"available": 0}

        def budget(ledger, window, requested, at):
            if slots["available"] < requested:
                raise ActivityBudgetDelayed(
                    "operational_object_budget", at + timedelta(seconds=1)
                )
            slots["available"] -= requested

        monkeypatch.setattr(module, "budget_admit", budget)
        owner = ActivityCollector(worker, store=store)
        await owner.tick()
        assert not worker.calls and len(store.runs) == 1
        assert store.updates[-1][1]["state"] == "budget_delayed"
        for seconds in (1, 2, 60, 120):
            worker.at = AT + timedelta(seconds=seconds)
            slots["available"] = 1
            await owner.tick()
        assert [params["leagueID"] for _, params in worker.calls] == ["NFL", "NBA"]
        assert all(run["kind"] == "monitor" for run, _ in worker.calls)
        assert len(store.runs) == 1 and store.updates[-1][1]["state"] == "complete"

    asyncio.run(scenario())


def test_operating_budget_reporting_dispatch_and_holds_share_the_policy(
    tmp_path, monkeypatch
):
    from app.collection import activity_mode

    assert activity_mode.operating_budget() == dict(
        units="returned_event_objects",
        objects_per_15_minutes=300,
        objects_per_day=16800,
        stricter_account_guards_apply=True,
    )
    monkeypatch.setattr(activity_mode, "OBJECTS_PER_15_MINUTES", 3)
    monkeypatch.setattr(activity_mode, "OBJECTS_PER_DAY", 9)
    monkeypatch.setattr(activity_mode, "retention_status", lambda db: {})

    class DB:
        def execute(self, sql):
            return (
                SimpleNamespace(fetchone=lambda: row())
                if sql == "SELECT * FROM activity_mode WHERE singleton"
                else []
            )

    status = activity_mode.read_status(DB(), at=AT)
    assert status["operating_budget"]["objects_per_15_minutes"] == 3
    assert status["operating_budget"]["objects_per_day"] == 9
    for name, amount, age in (
        ("rolling", 3, timedelta(minutes=5)),
        ("daily", 9, timedelta(hours=2)),
    ):
        ledger = ObjectLedger(tmp_path / (name + ".sqlite3"))
        ledger.create_window(
            "fixture",
            limit=100,
            initial_used=0,
            reserve=10,
            reset_at=AT + timedelta(days=30),
            requests_per_minute=100,
        )
        ledger.reserve("fixture", "uncertain", objects=amount, now=AT - age)
        with pytest.raises(ActivityBudgetDelayed):
            budget_admit(ledger, "fixture", 1, AT)
        assert ledger.status("fixture")["held"] == amount

    async def scenario():
        store, worker = Store(), Worker()
        owner = ActivityCollector(worker, store=store)

        async def delayed(status):
            raise ActivityBudgetDelayed(
                "operational_object_budget", AT + timedelta(minutes=1)
            )

        owner.monitor_turn = delayed
        await owner.tick()
        budget = worker.metrics["activity_budget"]
        assert budget["objects_per_15_minutes"] == 3
        assert budget["objects_per_day"] == 9
        assert budget["stricter_account_guards_apply"] is True
        assert not worker.calls
        assert store.updates[-1][1]["state"] == "budget_delayed"

    asyncio.run(scenario())


def test_legacy_monitor_phase_uses_the_same_default_as_validated_settings(monkeypatch):
    from app.collection import activity_mode

    monkeypatch.setitem(activity_mode.DEFAULT_SETTINGS, "monitor_phase_seconds", 300)
    legacy = dict(activity_mode.DEFAULT_SETTINGS)
    legacy.pop("monitor_phase_seconds")
    direct = activity_mode.monitor_schedule(legacy, at=AT)
    validated = activity_mode.monitor_schedule(
        activity_mode.validate_settings(legacy), at=AT
    )
    assert direct == validated
    assert direct["phase_seconds"] == 300
