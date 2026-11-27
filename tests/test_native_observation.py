from copy import deepcopy
from datetime import timedelta

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
