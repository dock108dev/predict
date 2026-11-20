"""Personal tracking reads stored inputs and preserves their original clocks."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from unittest import IsolatedAsyncioTestCase

from app.dashboard import bet_journal_monitor as monitor
from app.storage.store import stamp
from tests.test_pregame_arbs import entry


NOW = stamp("2026-11-18T15:00:00Z")


class RecoveryJournalIsolation(IsolatedAsyncioTestCase):
    async def test_slow_journal_does_not_stall_recovery_or_overlap_and_close_drains(
        self,
    ):
        import asyncio
        from threading import Event
        from unittest.mock import AsyncMock
        from app.collection.pregame_owner import PregameOwner

        owner = PregameOwner(None)
        owner.research = SimpleNamespace(close=AsyncMock())
        started, release, recovered = Event(), Event(), Event()
        turns = []

        def turn():
            turns.append(1)
            if len(turns) >= 2:
                recovered.set()

        def slow_poll():
            started.set()
            release.wait(3)

        with (
            patch.object(owner, "turn", side_effect=turn),
            patch.object(monitor, "poll", side_effect=slow_poll) as sampling,
            patch(
                "app.collection.background_work.BACKGROUND.critical_acquisition_pressure",
                return_value=False,
            ),
        ):
            owner.task = asyncio.create_task(owner.run())
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                self.assertTrue(await asyncio.to_thread(recovered.wait, 1))
                owner.sample_journal()
                self.assertEqual(sampling.call_count, 1)
                closing = asyncio.create_task(owner.close())
                await asyncio.sleep(0)
                self.assertFalse(closing.done())
            finally:
                owner.closed = True
                owner.wake.set()
                release.set()
                await asyncio.wait_for(owner.close(), 2)
            await asyncio.wait_for(closing, 2)


class Journal:
    def __init__(self):
        self.observed = []
        self.received = []
        self.states = []

    def observe(self, kind, snapshot, *, at=None):
        self.observed.append((kind, deepcopy(snapshot), at))

    def quotes(self, rows, *, at=None):
        self.received.append((deepcopy(rows), at))

    def status(self, **fields):
        self.states.append(fields)


class Result(list):
    def fetchone(self):
        return self[0] if self else None


class Database:
    def __init__(self, *, entries=(), books=(), revision=1):
        self.entries = list(entries)
        self.books = list(books)
        self.revision = revision
        self.info = SimpleNamespace(host="fixture", port=55432, dbname="fixture")
        self.queries = []
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *args):
        self.entered -= 1

    def transaction(self):
        return self

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if "SELECT revision FROM current_pregame_revision" in query:
            return Result([dict(revision=self.revision)])
        if "FROM current_pregame_price p" in query:
            return Result(self.entries)
        if "FROM current_sgo_reference" in query:
            return Result([dict(facts=q) for q in self.books])
        return Result()


def market(*, net_ev="-0.1"):
    value = entry("novig", "home")
    value["payload"].update(
        source=dict(provider="fixture"),
        times=dict(
            source_at="2026-11-18T14:00:00Z", received_at="2026-11-18T14:01:00Z"
        ),
        posted=dict(value="+110", units="american_odds"),
        main=True,
        sportsbook_event_ids=["event"],
        reference=None,
    )
    value["record"] = dict(
        market_identity={"family": "spread"},
        event={
            "home": "home",
            "away": "away",
            "participants": {"Home": "home", "Away": "away"},
        },
        selection=value["payload"]["selection"],
    )
    value["calculation"] = dict(
        value["payload"],
        reference=dict(probability="0.5"),
        raw=dict(value["payload"]["raw"], net_ev=net_ev),
    )
    return value


def sportsbook():
    return dict(
        event_id="event",
        venue="fanduel",
        market="spread",
        side="away",
        line="1.5",
        phase="pregame",
        period="game",
        league="NBA",
        available=True,
        provider_available=True,
        starts_at="2026-11-19T00:00:00Z",
        source_at="2026-11-18T14:00:00Z",
        received_at="2026-11-18T14:01:00Z",
        price_american="-120",
        odd_id="away",
    )


def test_negative_ev_and_nonprofitable_sportsbook_leg_still_reach_close_tracking():
    original = market()
    db = Database(entries=[original], books=[sportsbook()])
    with patch(
        "app.storage.current_pregame.configured_routes",
        return_value={"novig": "fixture"},
    ):
        rows = monitor._quote_rows(db, NOW)
    assert len(rows) == 2
    assert rows[0]["raw"]["net_ev"] == "-0.1"
    assert rows[0]["reference"]["probability"] == "0.5"
    assert rows[1]["venue"] == "fanduel"
    assert rows[1]["posted"] == dict(value="-120", units="american_odds")
    assert rows[1]["fee"]["committed_usd"] == "100"
    assert rows[1]["fee"]["cashflows"]["win"]["net_receipt_usd"] == "550/3"
    assert rows[0]["times"] == original["payload"]["times"]
    assert rows[1]["times"] == original["payload"]["times"]
    assert all(
        not sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql, _ in db.queries
    )


def test_future_receipt_and_started_quote_cannot_become_pregame_close():
    for change in (
        dict(
            times=dict(
                source_at="2026-11-18T14:00:00Z", received_at="2026-11-18T16:00:00Z"
            )
        ),
        dict(kickoff=NOW.isoformat()),
        dict(
            times=dict(
                source_at="2026-11-18T14:02:00Z", received_at="2026-11-18T14:01:00Z"
            )
        ),
    ):
        value = market()
        value["payload"].update(change)
        db = Database(entries=[value])
        with patch(
            "app.storage.current_pregame.configured_routes",
            return_value={"novig": "fixture"},
        ):
            assert monitor._quote_rows(db, NOW) == []


def test_conflicting_simultaneous_sportsbook_prices_are_omitted():
    quote = sportsbook()
    db = Database(entries=[market()], books=[quote, dict(quote, price_american="+120")])
    with patch(
        "app.storage.current_pregame.configured_routes",
        return_value={"novig": "fixture"},
    ):
        rows = monitor._quote_rows(db, NOW)
    assert [row["venue"] for row in rows] == ["novig"]


def test_sample_releases_readonly_source_transaction_before_journal_writes():
    db = Database()
    journal = Journal()
    payload = market()["calculation"]
    from tests.test_bet_journal import arb_snapshot

    packet = dict(revision=3, quotes=[payload], ev=[payload], arbs=[arb_snapshot()])
    original = journal.observe

    def observe(*args, **kwargs):
        assert db.entered == 0
        original(*args, **kwargs)

    journal.observe = observe
    with patch.object(monitor, "_read", return_value=packet):
        result = monitor.sample(journal=journal, connector=lambda: db, at=NOW)
    assert result == dict(revision=3, quotes=1, ev=0, arbs=1, provider_requests=0)
    assert [kind for kind, _, _ in journal.observed] == ["arb"]
    assert "REPEATABLE READ READ ONLY" in db.queries[0][0]
    assert journal.received[0][0][0]["times"] == payload["times"]
    assert journal.states[-1]["monitor_error"] is None


def test_revision_gate_rate_limit_arb_cadence_and_snapshot_identity():
    elapsed = [0]
    instance = monitor.Monitor(timer=lambda: elapsed[0])
    db = Database()
    journal = Journal()
    calls = []

    def sample(**kwargs):
        calls.append(kwargs["include_arbs"])
        return dict(revision=db.revision)

    with patch.object(monitor, "sample", side_effect=sample):
        instance.poll(journal=journal, connector=lambda: db)
        elapsed[0] = 0.5
        instance.poll(journal=journal, connector=lambda: db)
        elapsed[0] = 1
        instance.poll(journal=journal, connector=lambda: db)
        assert calls == [True]
        db.revision = 2
        elapsed[0] = 2
        instance.poll(journal=journal, connector=lambda: db)
        assert calls == [True, False]
        elapsed[0] = 15
        instance.poll(journal=journal, connector=lambda: db)
        assert calls == [True, False, True]
        db.info.host = "different-snapshot"
        elapsed[0] = 16
        instance.poll(journal=journal, connector=lambda: db)
        assert calls == [True, False, True, False]


def test_monitor_failure_is_visible_without_disrupting_collection():
    journal = Journal()

    def unavailable():
        raise RuntimeError("sensitive database text")

    with patch("app.diagnostics.failure"):
        assert (
            monitor.Monitor().poll(journal=journal, connector=unavailable, at=NOW)
            is None
        )
    assert journal.states[-1]["monitor_state"] == "error"
    assert "sensitive" not in journal.states[-1]["monitor_error"]
    assert journal.observed == []
