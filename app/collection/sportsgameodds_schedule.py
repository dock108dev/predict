"""Conservative, side-effect-free scheduling primitives for SGO.

A caller must persist reservations before dispatch and reconcile against the
provider's usage; this module deliberately does not dispatch or manage Stops.
"""
from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from itertools import accumulate
from math import ceil, floor


@dataclass(frozen=True)
class EventDue:
    event_id: str
    starts_at: datetime
    last_received_at: datetime | None = None
    live: bool = False
    started: bool = False

    @property
    def active(self) -> bool:
        return self.live or self.started


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
                     (2, policy.live) if event.started else
                     (3, policy.approaching) if until <= policy.approaching_window else
                     (4, policy.imminent) if until <= policy.imminent_window else
                     (5, policy.near) if until <= policy.near_window else
                     (6, policy.distant))
    last = event.last_received_at
    if last is None:
        return rank, now
    due = last + cadence
    if not event.active and last < event.starts_at:
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


def daily_retry_at(*, available, requested, now, reset_at, expirations):
    """First eligible whole-second retry from unchanged account evidence.

    Remaining days decrease as time passes. When a charge leaves the rolling
    window the allowance decreases by at most that charge, so headroom is
    monotone until another request or account observation changes the inputs.
    """
    clocks = [at for at, _ in expirations]
    exposure = list(accumulate((amount for _, amount in expirations), initial=0))
    low, high = 0, ceil((reset_at-now).total_seconds())
    while high-low > 1:
        middle = (low+high)//2
        at = now+timedelta(seconds=middle)
        rolling = exposure[-1]-exposure[bisect_right(clocks, at)]
        allowance = daily_allowance(available=available+rolling, now=at, reset_at=reset_at)
        if rolling+requested <= allowance:
            high = middle
        else:
            low = middle
    return min(reset_at, now+timedelta(seconds=high))


REFRESH_TARGET = .90
PLANNED_FRACTION = .90
DISCOVERY_HOURS = (12, 24, 48, 72, 96)


def projected_refresh_objects(events, now, policy, *, include_kickoff=True):
    """Forecast the next 24 hours as games move through bands and reach kickoff.

    A pregame game consumes no pregame refreshes after kickoff. Active games
    remain conservatively costed for the full horizon; no finish is invented.
    """
    total = 0.0
    horizon = timedelta(days=1).total_seconds()
    for event in events:
        if not _aware(event.starts_at):
            raise ValueError('event clocks must be timezone-aware')
        if event.active:
            total += horizon / policy.live.total_seconds()
            continue
        until = max(0, (event.starts_at-now).total_seconds())
        boundaries = (0, policy.approaching_window.total_seconds(),
                      policy.imminent_window.total_seconds(), policy.near_window.total_seconds(),
                      float('inf'))
        for low, high, cadence in zip(boundaries, boundaries[1:],
                (policy.approaching, policy.imminent, policy.near, policy.distant)):
            duration = max(0, min(horizon, until-low)-max(0, until-high))
            total += duration / cadence.total_seconds()
        if include_kickoff and until <= horizon and (
                event.last_received_at is None or event.last_received_at < event.starts_at):
            total += 1
    return ceil(total)


def budgeted_policy(events: list[EventDue], now: datetime, daily_budget: int, *,
                    discovery_walk_objects: int = 0, include_kickoff=True,
                    minimum_refresh=timedelta(minutes=1)) -> tuple[SchedulePolicy, int]:
    """Hourly pregame inside 24 hours; trial minute polling in the final 30.

    The owner selected a minute-poll trial despite the advertised three-minute
    feed frequency. Preserve the shared margin and guards; stretch only when
    that requested cadence cannot fit. Round upward to 30-second steps.
    Planning is a forecast, not new authority to spend or infer source clocks.
    """
    if type(daily_budget) is not int or daily_budget < 0:
        raise ValueError('daily budget must be a nonnegative integer')
    if not _aware(now):
        raise ValueError('now must be timezone-aware')
    if type(discovery_walk_objects) is not int or discovery_walk_objects < 0:
        raise ValueError('invalid discovery estimate')
    if minimum_refresh <= timedelta(0):
        raise ValueError('positive refresh floor required')
    discovery = discovery_interval(retained_events=discovery_walk_objects,
                                   daily_budget=daily_budget)
    discovery_cost = discovery_walk_objects * timedelta(days=1) / discovery
    refresh_limit = max(0, floor(daily_budget * PLANNED_FRACTION - discovery_cost)-1)
    floor_seconds = minimum_refresh.total_seconds()

    def cost(policy):
        return projected_refresh_objects(events, now, policy, include_kickoff=include_kickoff)

    for near, distant in ((3, 12), (6, 24), (12, 48), (24, 96)):
        policy = SchedulePolicy(live=max(timedelta(minutes=3),minimum_refresh),
                                approaching=minimum_refresh, imminent=timedelta(hours=1),
                                approaching_window=timedelta(minutes=30),
                                imminent_window=timedelta(hours=24),
                                near=timedelta(hours=near), distant=timedelta(hours=distant))
        projected = cost(policy)
        if projected <= refresh_limit:
            return policy, projected

    # If a crowded slate cannot fund both targets, preserve the final-minute
    # trial ahead of early repeat polls. Actual ledger guards still decide
    # dispatch; report any selected interval that differs from the request.
    for hours in (2, 4):
        policy = replace(policy, imminent=timedelta(hours=hours))
        projected = cost(policy)
        if projected <= refresh_limit:
            return policy, projected

    def stretched(scale):
        seconds = ceil(floor_seconds*scale/30)*30
        return replace(policy, live=timedelta(seconds=max(180,seconds)),
                       approaching=timedelta(seconds=seconds),
                       imminent=max(policy.imminent,timedelta(seconds=seconds)))

    low, high = 1.0, 2.0
    while high < 86400/floor_seconds and cost(stretched(high)) > refresh_limit:
        high *= 2
    for _ in range(32):
        middle = (low+high)/2
        if cost(stretched(middle)) <= refresh_limit:
            high = middle
        else:
            low = middle
    policy = stretched(high)
    return policy, cost(policy)


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
