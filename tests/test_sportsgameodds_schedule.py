from datetime import datetime, timedelta, timezone

import pytest

from app.collection.sportsgameodds_schedule import (
    EventDue, available_objects, daily_allowance, due_events, response_object_charge,
)

NOW = datetime(2026, 11, 10, 20, tzinfo=timezone.utc)


def test_due_priority_dedup_and_controls():
    events = [EventDue('distant', NOW + timedelta(days=5)),
              EventDue('near', NOW + timedelta(days=2)),
              EventDue('soon', NOW + timedelta(hours=1)),
              EventDue('live', NOW - timedelta(hours=1), live=True),
              EventDue('fresh', NOW + timedelta(hours=1), NOW - timedelta(minutes=29))]
    assert [e.event_id for e in due_events(events, NOW)] == ['live', 'soon', 'near', 'distant']
    assert due_events(events, NOW, stopped=True) == []
    assert due_events(events, NOW, paused=True) == []
    with pytest.raises(ValueError):
        due_events(events + [events[0]], NOW)


def test_source_timing_not_replaced_and_bad_clocks_fail_closed():
    event = EventDue('x', NOW + timedelta(hours=1), NOW + timedelta(seconds=1))
    with pytest.raises(ValueError):
        due_events([event], NOW)
    with pytest.raises(ValueError):
        due_events([EventDue('x', datetime(2026, 11, 10))], NOW)


def test_object_charge_reserve_and_unknown_exposure():
    assert response_object_charge(0) == 1
    assert response_object_charge(7) == 7
    assert available_objects(limit=2500, used=11, held=50, reserve=200) == 2239
    assert available_objects(limit=10, used=9, held=3, reserve=1) == 0
    for bad in (-1, True, 1.5):
        with pytest.raises(ValueError):
            response_object_charge(bad)


def test_pacing_requires_known_future_reset():
    assert daily_allowance(available=2300, now=NOW, reset_at=NOW + timedelta(days=23)) == 100
    assert daily_allowance(available=23, now=NOW, reset_at=NOW + timedelta(hours=2)) == 23
    with pytest.raises(ValueError):
        daily_allowance(available=100, now=NOW, reset_at=NOW)
