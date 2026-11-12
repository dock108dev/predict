"""Conservative, side-effect-free scheduling primitives for SGO.

A caller must persist reservations before dispatch and reconcile against the
provider's usage; this module deliberately does not dispatch or manage Stops.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import ceil, floor


@dataclass(frozen=True)
class EventDue:
    event_id: str
    starts_at: datetime
    last_received_at: datetime | None = None
    live: bool = False


@dataclass(frozen=True)
class SchedulePolicy:
    live: timedelta = timedelta(minutes=15)
    approaching: timedelta = timedelta(minutes=30)
    imminent: timedelta = timedelta(minutes=45)
    near: timedelta = timedelta(hours=3)
    distant: timedelta = timedelta(hours=12)
    approaching_window: timedelta = timedelta(hours=2)
    imminent_window: timedelta = timedelta(hours=12)
    near_window: timedelta = timedelta(hours=72)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def poll_slot(event: EventDue, now: datetime, policy: SchedulePolicy):
    until = event.starts_at - now
    rank, cadence = ((0, policy.live) if event.live else
                     (2, policy.approaching) if until <= policy.approaching_window else
                     (3, policy.imminent) if until <= policy.imminent_window else
                     (4, policy.near) if until <= policy.near_window else
                     (5, policy.distant))
    last = event.last_received_at
    if last is None:
        return rank, now
    due = last + cadence
    if not event.live and last < event.starts_at:
        # The first post-start poll can detect an explicit live transition.
        # After an omitted or pregame response, the normal cadence applies.
        due = min(due, event.starts_at)
        if event.starts_at <= now:
            rank = 1
    return rank, due


def due_events(events: list[EventDue], now: datetime, *, stopped: bool = False,
               paused: bool = False, policy: SchedulePolicy = SchedulePolicy()) -> list[EventDue]:
    """Select each due event once, prioritizing live, imminent, near, distant.

    Receipt time schedules polling only; it is never a quote's source time.
    """
    if not _aware(now):
        raise ValueError('now must be timezone-aware')
    if stopped or paused:
        return []
    if any(getattr(policy, x) <= timedelta(0) for x in ('live', 'approaching', 'imminent', 'near', 'distant')):
        raise ValueError('cadences must be positive')
    if (policy.approaching_window < timedelta(0) or policy.imminent_window < policy.approaching_window
            or policy.near_window < policy.imminent_window):
        raise ValueError('invalid schedule windows')
    result = []
    seen = set()
    for event in events:
        if not event.event_id or event.event_id in seen:
            raise ValueError('event ids must be nonempty and unique')
        seen.add(event.event_id)
        if not _aware(event.starts_at) or (event.last_received_at and not _aware(event.last_received_at)):
            raise ValueError('event clocks must be timezone-aware')
        if event.last_received_at and event.last_received_at > now:
            raise ValueError('receipt time cannot be in the future')
        rank, due = poll_slot(event, now, policy)
        if due <= now:
            result.append((rank, due, event.last_received_at or datetime.min.replace(tzinfo=now.tzinfo), event.event_id, event))
    return [item[-1] for item in sorted(result, key=lambda item: item[:-1])]


def response_object_charge(returned_objects: int) -> int:
    """Documented response minimum, without conflating requests and objects."""
    if isinstance(returned_objects, bool) or not isinstance(returned_objects, int) or returned_objects < 0:
        raise ValueError('returned objects must be a nonnegative integer')
    return max(1, returned_objects)


def available_objects(*, limit: int, used: int, held: int, reserve: int) -> int:
    """Objects available after durable outstanding reservations and reserve.

    Uncertain requests remain held until reconciled with authoritative account
    usage; a failed request is not automatically assumed free.
    """
    values = (limit, used, held, reserve)
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
        raise ValueError('account values must be nonnegative integers')
    return max(0, limit - used - held - reserve)


def daily_allowance(*, available: int, now: datetime, reset_at: datetime) -> int:
    """Pace an explicitly known remaining allowance through the account reset.

    An unknown reset is not inferred from calendar month or vendor examples.
    """
    if isinstance(available, bool) or not isinstance(available, int) or available < 0:
        raise ValueError('available must be a nonnegative integer')
    if not _aware(now) or not _aware(reset_at) or reset_at <= now:
        raise ValueError('a future, timezone-aware reset is required')
    days = max(1.0, (reset_at - now).total_seconds() / 86400)
    return floor(available / days)


REFRESH_TARGET = .65
PLANNED_FRACTION = .90
DISCOVERY_HOURS = (12, 24, 48, 72, 96)


def budgeted_policy(events: list[EventDue], now: datetime, daily_budget: int, *,
                    discovery_walk_objects: int = 0) -> tuple[SchedulePolicy, int]:
    """Budget the static slate, preserving kickoff and active refresh priority.

    Project current live events as live all day. Reserve capacity for the
    slowest repeat walk and keep ten percent for costs the slate misses.
    Source clocks and expiry remain independent of polling intervals.
    """
    if isinstance(daily_budget, bool) or not isinstance(daily_budget, int) or daily_budget < 0:
        raise ValueError('daily budget must be a nonnegative integer')
    if not _aware(now):
        raise ValueError('now must be timezone-aware')
    if type(discovery_walk_objects) is not int or discovery_walk_objects < 0:
        raise ValueError('invalid discovery estimate')
    tiers = [0, 0, 0, 0, 0]
    kickoff_polls = 0
    for event in events:
        if not _aware(event.starts_at):
            raise ValueError('event clocks must be timezone-aware')
        hours = (event.starts_at - now).total_seconds() / 3600
        tiers[0 if event.live else 1 if hours <= 2 else 2 if hours <= 12 else 3 if hours <= 72 else 4] += 1
        if not event.live and hours <= 24 and (event.last_received_at is None or event.last_received_at < event.starts_at):
            kickoff_polls += 1
    # Keep the normal 15-minute live target as we stretch distant, near and
    # imminent pregame polling. Kickoff remains an independent one-time poll.
    candidates = [
        SchedulePolicy(),
        SchedulePolicy(near=timedelta(hours=6), distant=timedelta(hours=24)),
        SchedulePolicy(near=timedelta(hours=8), distant=timedelta(hours=24)),
        SchedulePolicy(near=timedelta(hours=12), distant=timedelta(hours=24)),
        SchedulePolicy(imminent=timedelta(hours=1), near=timedelta(hours=12), distant=timedelta(hours=24)),
        SchedulePolicy(imminent=timedelta(hours=2), near=timedelta(hours=12), distant=timedelta(hours=24)),
        SchedulePolicy(imminent=timedelta(hours=2), near=timedelta(hours=12), distant=timedelta(hours=48)),
    ]
    combined_limit = daily_budget * PLANNED_FRACTION - discovery_walk_objects * 24 / DISCOVERY_HOURS[-1]
    normal_limit = min(daily_budget * REFRESH_TARGET, combined_limit)

    def cost(policy):
        intervals = (policy.live, policy.approaching, policy.imminent, policy.near, policy.distant)
        return kickoff_polls + sum(count * 86400 / interval.total_seconds()
                                   for count, interval in zip(tiers, intervals))

    for policy in candidates:
        projected = cost(policy)
        if projected <= normal_limit:
            if tiers[0]:
                for minutes in (5, 10):
                    faster = replace(policy, live=timedelta(minutes=minutes))
                    if cost(faster) <= normal_limit:
                        return faster, ceil(cost(faster))
            return policy, ceil(projected)
    if not discovery_walk_objects:
        return policy, ceil(projected)

    # On crowded slates, use the shared headroom and reduce pregame frequency
    # before relaxing the live cadence. The hard ledger guard still applies.
    for changes in (
        {},
        {'distant': timedelta(hours=96), 'near': timedelta(hours=24)},
        {'imminent': timedelta(hours=4), 'approaching': timedelta(minutes=45)},
        {'imminent': timedelta(hours=6), 'approaching': timedelta(hours=1)},
        *({'live': timedelta(minutes=minutes)} for minutes in (20, 30, 45, 60)),
    ):
        policy = replace(policy, **changes)
        projected = cost(policy)
        if projected <= combined_limit:
            break
    return policy, ceil(projected)


def discovery_interval(*, retained_events: int, daily_budget: int,
                       projected_refresh_objects: int = 0) -> timedelta:
    """Pace repeat walks against the same daily allowance as event refresh.

    This is a planning estimate, not an assertion that a moving traversal has
    exactly the retained number of events or proves a complete snapshot. Keep
    the existing 25% discovery allocation and 10% allowance for other costs.
    """
    if any(type(n) is not int or n < 0 for n in (retained_events, daily_budget, projected_refresh_objects)):
        raise ValueError('schedule counts must be nonnegative integers')
    allowance = min(daily_budget * .25, daily_budget * PLANNED_FRACTION - projected_refresh_objects)
    for hours in DISCOVERY_HOURS:
        if retained_events * 24 <= allowance * hours:
            return timedelta(hours=hours)
    return timedelta(hours=DISCOVERY_HOURS[-1])
