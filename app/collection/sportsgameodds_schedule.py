"""Conservative, side-effect-free scheduling primitives for SGO.

A caller must persist reservations before dispatch and reconcile against the
provider's usage; this module deliberately does not dispatch or manage Stops.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import floor


@dataclass(frozen=True)
class EventDue:
    event_id: str
    starts_at: datetime
    last_received_at: datetime | None = None
    live: bool = False


@dataclass(frozen=True)
class SchedulePolicy:
    live: timedelta = timedelta(minutes=15)
    imminent: timedelta = timedelta(minutes=30)
    near: timedelta = timedelta(hours=3)
    distant: timedelta = timedelta(hours=12)
    imminent_window: timedelta = timedelta(hours=3)
    near_window: timedelta = timedelta(hours=72)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def due_events(events: list[EventDue], now: datetime, *, stopped: bool = False,
               paused: bool = False, policy: SchedulePolicy = SchedulePolicy()) -> list[EventDue]:
    """Select each due event once, prioritizing live, imminent, near, distant.

    Receipt time schedules polling only; it is never a quote's source time.
    """
    if not _aware(now):
        raise ValueError('now must be timezone-aware')
    if stopped or paused:
        return []
    if any(getattr(policy, x) <= timedelta(0) for x in ('live', 'imminent', 'near', 'distant')):
        raise ValueError('cadences must be positive')
    if policy.imminent_window < timedelta(0) or policy.near_window < policy.imminent_window:
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
        until = event.starts_at - now
        rank, cadence = ((0, policy.live) if event.live else
                         (1, policy.imminent) if until <= policy.imminent_window else
                         (2, policy.near) if until <= policy.near_window else
                         (3, policy.distant))
        if event.last_received_at is None or now - event.last_received_at >= cadence:
            result.append((rank, event.last_received_at or datetime.min.replace(tzinfo=now.tzinfo), event.event_id, event))
    return [item[-1] for item in sorted(result, key=lambda item: item[:3])]


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
