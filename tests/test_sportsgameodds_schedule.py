from datetime import datetime, timedelta, timezone

import pytest

from app.collection.sportsgameodds_schedule import (
    EventDue, available_objects, budgeted_policy, daily_allowance, daily_retry_at, discovery_interval, due_events, projected_refresh_objects, response_object_charge,
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
    assert [e.event_id for e in due_events(events, NOW, policy=policy)] == ['approaching', 'later']
    assert policy.approaching == timedelta(minutes=3)
    # One remaining hour, then kickoff; the later game crosses both bands.
    assert projected == 20 + 80 + 2


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


def test_daily_retry_uses_guard_when_time_to_reset_shrinks_or_old_charges_age_out():
    reset = NOW+timedelta(days=2, seconds=1)
    assert daily_retry_at(available=19, requested=9, now=NOW, reset_at=reset,
                          expirations=[(NOW+timedelta(hours=12), 1)]) == NOW+timedelta(seconds=1)

    reset = NOW+timedelta(days=2)
    expiring = [(NOW+timedelta(seconds=12), 2), (NOW+timedelta(hours=12), 78)]
    assert daily_retry_at(available=80, requested=1, now=NOW, reset_at=reset,
                          expirations=expiring) == NOW+timedelta(seconds=12)
    assert daily_retry_at(available=1, requested=2, now=NOW, reset_at=reset, expirations=[]) == reset


def test_busy_slate_spends_headroom_on_near_start_prices_before_distant_polls():
    events = ([EventDue(f'i{i}', NOW + timedelta(hours=6)) for i in range(63)] +
              [EventDue(f'n{i}', NOW + timedelta(hours=24)) for i in range(182)] +
              [EventDue(f'd{i}', NOW + timedelta(days=5)) for i in range(267)])
    policy, projected = budgeted_policy(events, NOW, 4500)
    assert policy.near == timedelta(hours=24)
    assert policy.distant == timedelta(hours=96)
    assert timedelta(minutes=3) <= policy.approaching < policy.imminent
    assert projected <= 4500 * .9
    # The previous 45-minute tier was not a target, just a fixed candidate.
    assert policy.imminent < timedelta(minutes=60)


def test_projection_follows_bands_and_stops_pregame_at_kickoff():
    from app.collection.sportsgameodds_schedule import SchedulePolicy
    policy = SchedulePolicy(approaching=timedelta(minutes=3), imminent=timedelta(minutes=6))
    soon = EventDue('soon', NOW+timedelta(hours=1))
    later = EventDue('later', NOW+timedelta(hours=6))
    assert projected_refresh_objects([soon], NOW, policy, include_kickoff=False) == 20
    assert projected_refresh_objects([later], NOW, policy, include_kickoff=False) == 80
    assert projected_refresh_objects([EventDue('started',NOW)], NOW, policy,
                                     include_kickoff=False) == 0
    # Live is conservatively budgeted all day; no finish time is invented.
    assert projected_refresh_objects([EventDue('live',NOW,live=True)], NOW, policy) == 96


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


def test_small_budget_slows_polling_instead_of_projecting_an_unaffordable_rate():
    events = [EventDue('live', NOW, live=True)]
    policy, projected = budgeted_policy(events, NOW, 10)
    assert policy.live > timedelta(minutes=15)
    assert projected <= 10 * .9


def test_refresh_floor_and_headroom_adapt_without_exceeding_shared_budget():
    events = [EventDue('live', NOW, live=True)]
    fast, fast_cost = budgeted_policy(events, NOW, 1000)
    medium, medium_cost = budgeted_policy(events, NOW, 500)
    slow, slow_cost = budgeted_policy(events, NOW, 150)
    assert fast.live == timedelta(minutes=3)
    assert fast.live < medium.live < slow.live
    for cost, budget in ((fast_cost,1000),(medium_cost,500),(slow_cost,150)):
        assert cost <= budget * .9
    amateur, _ = budgeted_policy(events, NOW, 10000,minimum_refresh=timedelta(minutes=10))
    assert amateur.live == timedelta(minutes=10)
    with pytest.raises(ValueError):
        budgeted_policy(events,NOW,1000,minimum_refresh=timedelta(0))


def test_pregame_only_budget_does_not_reserve_a_kickoff_poll():
    events = [EventDue('pregame', NOW + timedelta(hours=1))]
    policy, live_cost = budgeted_policy(events, NOW, 1000)
    pregame, pregame_cost = budgeted_policy(events, NOW, 1000, include_kickoff=False)
    assert pregame == policy and pregame_cost == live_cost - 1


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
    assert policy.live >= timedelta(minutes=3)
    assert policy.distant >= timedelta(hours=48)
    assert refresh + 985 * timedelta(days=1) / discovery <= 4736 * .9


def test_captured_busy_pregame_shape_improves_forty_five_minutes_within_allowance():
    # Six-league server shape: game day, tomorrow, then a large cold catalog.
    events = ([EventDue(f'today{i}',NOW+timedelta(hours=6),NOW) for i in range(76)] +
              [EventDue(f'tomorrow{i}',NOW+timedelta(hours=30),NOW) for i in range(45)] +
              [EventDue(f'near{i}',NOW+timedelta(hours=60),NOW) for i in range(160)] +
              [EventDue(f'cold{i}',NOW+timedelta(days=10),NOW) for i in range(564)])
    policy, refresh = budgeted_policy(events,NOW,5891,discovery_walk_objects=850,include_kickoff=False)
    discovery=discovery_interval(retained_events=850,daily_budget=5891,projected_refresh_objects=refresh)
    assert policy.approaching < timedelta(minutes=10)
    assert policy.imminent < timedelta(minutes=20)
    assert refresh+850*timedelta(days=1)/discovery <= 5891*.9
