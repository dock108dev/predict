from datetime import datetime, timedelta, timezone

import pytest

from app.collection.sportsgameodds_schedule import (
    EventDue, available_objects, budgeted_policy, daily_allowance, discovery_interval, due_events, response_object_charge,
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


def test_near_term_slate_refreshes_more_frequently_than_distant_games():
    events = [EventDue('tonight', NOW + timedelta(hours=10), NOW - timedelta(minutes=45)),
              EventDue('later', NOW + timedelta(hours=30), NOW - timedelta(minutes=45))]
    assert [e.event_id for e in due_events(events, NOW)] == ['tonight']


def test_approaching_games_are_prioritized_and_costed():
    events = [EventDue('approaching', NOW + timedelta(hours=1), NOW - timedelta(minutes=30)),
              EventDue('later', NOW + timedelta(hours=6), NOW - timedelta(minutes=30))]
    policy, projected = budgeted_policy(events, NOW, 1000)
    assert [e.event_id for e in due_events(events, NOW, policy=policy)] == ['approaching']
    assert projected == 48 + 32 + 2


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


def test_slate_budget_slows_distant_games_before_imminent_and_keeps_live_priority():
    events = ([EventDue(f'i{i}', NOW + timedelta(hours=6)) for i in range(63)] +
              [EventDue(f'n{i}', NOW + timedelta(hours=24)) for i in range(182)] +
              [EventDue(f'd{i}', NOW + timedelta(days=5)) for i in range(267)])
    policy, projected = budgeted_policy(events, NOW, 4500)
    assert policy.live == timedelta(minutes=15)
    assert policy.imminent == timedelta(minutes=45)
    assert policy.near == timedelta(hours=12)
    assert policy.distant == timedelta(hours=24)
    assert projected == 2892
    assert projected <= 4500 * .65
    live = EventDue('live', NOW - timedelta(hours=1), NOW - timedelta(minutes=15), live=True)
    imminent = EventDue('soon', NOW + timedelta(hours=1), NOW - timedelta(minutes=45))
    assert [e.event_id for e in due_events([imminent, live], NOW, policy=policy)] == ['live', 'soon']


def test_first_post_start_poll_prioritizes_transition_and_does_not_retry_immediately():
    kickoff = EventDue('kickoff', NOW, NOW - timedelta(minutes=1))
    live = EventDue('live', NOW - timedelta(hours=1), NOW - timedelta(minutes=15), live=True)
    pregame = EventDue('pregame', NOW + timedelta(hours=1), NOW - timedelta(minutes=31))
    assert [e.event_id for e in due_events([pregame, kickoff, live], NOW)] == ['live', 'kickoff', 'pregame']
    assert due_events([EventDue('kickoff', NOW, NOW)], NOW + timedelta(seconds=1)) == []


def test_due_kickoffs_use_the_poll_deadline_within_the_urgent_tier():
    early = EventDue('early', NOW - timedelta(minutes=10), NOW - timedelta(minutes=12))
    late = EventDue('late', NOW - timedelta(minutes=1), NOW - timedelta(minutes=20))
    assert due_events([late, early], NOW) == [early, late]


def test_budget_policy_reports_overflow_without_weakening_live_cadence():
    events = [EventDue('live', NOW, live=True)]
    policy, projected = budgeted_policy(events, NOW, 10)
    assert policy.live == timedelta(minutes=15)
    assert projected == 96
    assert projected > 10 * .65


def test_live_cadence_uses_only_available_refresh_headroom():
    events = [EventDue('live', NOW, live=True)]
    fast, fast_cost = budgeted_policy(events, NOW, 500)
    medium, medium_cost = budgeted_policy(events, NOW, 250)
    normal, normal_cost = budgeted_policy(events, NOW, 150)
    assert (fast.live, fast_cost) == (timedelta(minutes=5), 288)
    assert (medium.live, medium_cost) == (timedelta(minutes=10), 144)
    assert (normal.live, normal_cost) == (timedelta(minutes=15), 96)
    assert [e.event_id for e in due_events(
        [EventDue('live', NOW, NOW - timedelta(minutes=5), live=True)], NOW, policy=fast)] == ['live']


def test_discovery_budget_adapts_to_retained_slate():
    assert discovery_interval(retained_events=512, daily_budget=4687) == timedelta(hours=12)
    assert discovery_interval(retained_events=991, daily_budget=4687) == timedelta(hours=24)
    assert discovery_interval(retained_events=985, daily_budget=4731,
                              projected_refresh_objects=3200) == timedelta(hours=24)
    assert discovery_interval(retained_events=985, daily_budget=4731,
                              projected_refresh_objects=3830) == timedelta(hours=72)


def test_combined_projection_protects_headroom_on_crowded_slate():
    tiers = [(25, -1), (19, 1), (41, 6), (265, 48), (635, 144)]
    events = [EventDue(f'{hours}:{i}', NOW + timedelta(hours=hours), live=hours < 0)
              for count, hours in tiers for i in range(count)]
    policy, refresh = budgeted_policy(events, NOW, 4736, discovery_walk_objects=985)
    discovery = discovery_interval(retained_events=985, daily_budget=4736, projected_refresh_objects=refresh)
    assert policy.live == timedelta(minutes=15)
    assert policy.distant > timedelta(hours=48)
    assert refresh + 985 * timedelta(days=1) / discovery <= 4736 * .9
