import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.comparison.native_observation import adopt, clock, revision
from app.collection.native_trading import NativeTrading
from app.storage.store import stamp
from tests.test_liquidity_execution import admitted


def book():
    return dict(admitted((".25", 5000)), sequence=10)


@pytest.mark.parametrize(
    "reason", ["throttled", "native_book_capacity", "timeout", "stale", "source_paused"]
)
def test_failed_or_deferred_refresh_preserves_original_book(reason):
    previous = book()
    assert (
        adopt(previous, dict(previous, reason=reason, levels=[], sequence=11))
        is previous
    )


def test_repeated_payload_never_renews_expiry_or_replaces_original_clocks():
    previous = book()
    repeated = dict(
        previous, received_at="2026-11-27T23:50:00Z", valid_until="2026-11-27T23:50:30Z"
    )
    assert revision(previous) == revision(repeated)
    assert adopt(previous, repeated) is previous


def test_native_revision_regression_and_sequence_conflict_cannot_replace_book():
    previous = book()
    changed = dict(previous, levels=[dict(price=".30", quantity="5000")])
    assert adopt(previous, changed) is previous
    assert adopt(previous, dict(changed, sequence=9)) is previous
    assert (
        adopt(previous, dict(changed, sequence=11, source_at="2026-11-27T23:49:55Z"))
        is previous
    )
    newer = dict(changed, sequence=11, source_at="2026-11-27T23:49:57Z")
    assert adopt(previous, newer) is newer
    # Persisted JSON has exactly the same ordering behavior after restart.
    assert adopt(deepcopy(previous), newer) is newer


def test_wrong_instrument_does_not_move_book_and_ordered_halt_is_authoritative():
    previous = book()
    assert adopt(previous, dict(previous, outcome_id="wrong-side")) is previous
    halt = dict(
        previous,
        reason="native_market_halted",
        sequence=11,
        source_at="2026-11-27T23:49:57Z",
    )
    assert adopt(previous, halt) is halt
    assert adopt(halt, dict(halt, received_at="2026-11-27T23:50:00Z")) is halt
    stale = dict(halt, source_at="2026-11-27T23:49:55Z")
    assert adopt(previous, stale) is previous
    assert adopt(previous, dict(halt, sequence=9)) is previous
    # A second transport with no comparable sequence cannot reopen a halted
    # book using the same venue timestamp.
    assert adopt(halt, dict(halt, reason=None, sequence=None)) is halt


def test_first_exact_book_replaces_unobserved_inventory():
    incoming = book()
    placeholder = dict(
        incoming,
        reason="book_unobserved",
        levels=[],
        source_at=None,
        received_at="2026-11-27T23:50:00Z",
        sequence=None,
    )
    assert adopt(placeholder, incoming) is incoming


def test_polymarket_dashboard_uses_rest_when_stream_image_stops_advancing():
    from app.collection.native_trading_pmus_stream import DashboardMarketStream

    at = stamp("2026-11-27T23:50:00Z")
    now = [at]
    start = at + timedelta(minutes=10)
    binding = dict(book(), venue="polymarket_us", route="exact-slug", native_side="Long",
                   scheduled_start=start.isoformat(), terms_valid_until=start.isoformat(), reason=None)
    plan = {"side": binding}
    frame = dict(marketSlug="exact-slug", transactTime=at.isoformat(), state="MARKET_STATE_OPEN",
                 bids=[], offers=[dict(px=dict(value="0.50", currency="USD"), qty="20")])
    requests = []

    class REST:
        async def read_native(self, pending, _cutoff, *, batch):
            if pending:
                requests.append(set(pending))
            return {cid: dict(row, source_at=now[0].isoformat(), received_at=now[0].isoformat(),
                              sequence=None, levels=[dict(price="0.49", quantity="20")],
                              valid_until=(now[0]+timedelta(seconds=30)).isoformat())
                    for cid, row in pending.items()}

    async def run():
        trader = NativeTrading(None, now=lambda: now[0])
        trader.synchronized = lambda *_: {}
        stream = DashboardMarketStream(now=lambda: now[0], allowed=lambda: True)
        stream.task = asyncio.create_task(asyncio.Event().wait())
        try:
            stream._image(frame, b"original", at.isoformat())
            original = (await trader.read_exchanges(REST(), stream, plan, plan, start))["side"]
            assert original["levels"] == [dict(price="1/2", quantity="20")]
            assert requests == []
            now[0] += timedelta(seconds=3)
            stream._image(frame, b"repeated", now[0].isoformat())
            updated = (await trader.read_exchanges(REST(), stream, plan, plan, start))["side"]
            assert requests == [{"side"}]
            assert adopt(original, updated) is updated
            assert original["valid_until"] == (at+timedelta(seconds=30)).isoformat()
            # A new connection is allowed to supply fresh evidence, but the
            # rolling source high-water mark survives dropping its image.
            stream.images.clear()
            stream._image(frame, b"reconnect", now[0].isoformat())
            assert not stream.images
            stream._image(dict(frame, state="MARKET_STATE_HALTED"), b"halt", now[0].isoformat())
            halt = (await stream.read(plan, start, new_only=True))["side"]
            assert halt["reason"] == "native_market_halted"
            assert halt["valid_until"] == original["valid_until"]
            assert adopt(updated, halt) is updated  # REST already saw a later open image.
            stream._image(frame, b"delayed-open", now[0].isoformat())
            assert stream.images["exact-slug"]["reason"] == "native_market_halted"
        finally:
            await stream.close()

    asyncio.run(run())


def test_novig_reads_next_event_while_previous_event_write_waits(monkeypatch):
    at = stamp("2026-11-27T23:50:00Z")
    plan = {
        event: dict(venue="novig", event_id=event, market_id=event)
        for event in ("first", "second")
    }
    monkeypatch.setattr(
        "app.collection.native_trading.novig_bindings",
        lambda event, *_args, **_kwargs: {event["eventId"]: plan[event["eventId"]]},
    )
    monkeypatch.setattr(
        "app.collection.native_trading.book_depth",
        lambda *_args, **_kwargs: {"reason": "timeout"},
    )

    async def run():
        writer_started = asyncio.Event()
        release_writer = asyncio.Event()
        second_read = asyncio.Event()
        writes = []
        trader = NativeTrading(None, now=lambda: at)
        trader.enabled = lambda _venue=None: True
        trader.protected = lambda: False

        async def save(batch):
            writes.append(list(batch))
            if "first" in batch:
                writer_started.set()
                await release_writer.wait()

        class Novig:
            async def read_event_metadata(self, event, cutoff, *, lifecycle):
                if event == "second":
                    await writer_started.wait()
                    second_read.set()
                return {"eventId": event, "status": "OPEN_PREGAME"}, {}, None

            async def read_event(self, event, cutoff, *, moneyline):
                return SimpleNamespace(markets={}, reason=None)

            async def read_book(self, market, cutoff):
                return None

        trader.save = save
        # Minimal normalized bindings for the catalog fallback.
        for binding in plan.values():
            binding["_binding"] = {}
        turn = asyncio.create_task(
            trader.read_novig(Novig(), plan, at + timedelta(seconds=6))
        )
        try:
            await asyncio.wait_for(second_read.wait(), timeout=2)
            assert writes == [["first"]]
        finally:
            release_writer.set()
            assert await turn
        assert writes == [["first"], ["second"]]

    asyncio.run(run())


def test_one_venue_turn_keeps_both_sides_and_does_not_advance_another_venue():
    at = stamp("2026-11-27T23:50:00Z")
    trader = NativeTrading(None, now=lambda: at)
    start = at + timedelta(hours=1)
    event = {"scheduled_start": start.isoformat(), "competition": "NBA"}
    for venue in ("kalshi", "polymarket_us"):
        for side in ("long", "short"):
            trader.bindings[f"{venue}-{side}"] = dict(
                venue=venue,
                event_id="event",
                market_id="market",
                terms_valid_until=(at + timedelta(seconds=50)).isoformat(),
                _record={"event": event},
            )
    trader.references["polymarket_us-long"] = at + timedelta(minutes=5)
    assert set(trader._book_plan("kalshi")[0]) == {"kalshi-long", "kalshi-short"}
    plan, streaming = trader._book_plan("polymarket_us")
    assert set(plan) == set(streaming) == {"polymarket_us-long", "polymarket_us-short"}
    assert trader._book_plan("kalshi")[0] == {}
    assert trader._identity_scope("polymarket_us", {}) is None
    for side in ("long", "short"):
        trader.bindings[f"polymarket_us-{side}"]["terms_valid_until"] = at.isoformat()
    assert trader._book_plan("polymarket_us") == ({}, {})
    assert trader._identity_scope("polymarket_us", {}) == ("NBA", start)
    assert trader._identity_scope("polymarket_us", {("NBA", start): at}) is None


def test_due_book_turn_prioritizes_usable_references_and_keeps_cold_cohorts():
    at = stamp("2026-11-27T23:50:00Z")
    trader = NativeTrading(None, now=lambda: at)
    for cohort, starts in (("hot", 1), ("near", 1), ("distant", 3)):
        for count in range(20):
            cid = f"{cohort}-{count:02}"
            trader.bindings[cid] = dict(
                venue="kalshi", event_id=cid, market_id=cid,
                terms_valid_until=(at + timedelta(minutes=1)).isoformat(),
                _record={"event": {"scheduled_start": (at + timedelta(hours=starts)).isoformat()}},
            )
            if cohort == "hot":
                trader.references[cid] = at + timedelta(minutes=1)
                trader.attempted[("kalshi", cid, cid)] = at - timedelta(seconds=4)
    plan, _ = trader._book_plan("kalshi")
    actual = {cohort: sum(cid.startswith(cohort) for cid in plan)
              for cohort in ("hot", "near", "distant")}
    assert actual == {"hot": 8, "near": 4, "distant": 4}


def test_cache_clock_is_independent_of_receive_time_and_age():
    previous = book()
    previous.pop("source_at")
    previous["receipts"] = [
        dict(
            received_at="2026-11-27T23:49:58Z",
            headers={"date": "Fri, 27 Nov 2026 23:49:55 GMT", "age": "2"},
        )
    ]
    incoming = deepcopy(previous)
    incoming["receipts"][0]["received_at"] = "2026-11-27T23:50:00Z"
    incoming["receipts"][0]["headers"]["age"] = "4"
    assert clock(previous) == clock(incoming)
    assert adopt(previous, incoming) is previous
