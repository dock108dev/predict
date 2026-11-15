"""Storage policy for pregame research and replaceable game-day prices."""

from datetime import timedelta

from .store import exact_time, stamp

NON_PREGAME_FLAGS = ('started', 'live', 'ended', 'completed', 'closed', 'cancelled', 'canceled')


def pregame(starts_at, received_at, *, source_at=None, phase=None, status=None, event=None):
    """Only archive an observation Predict received before the known start."""
    if not starts_at or not received_at or phase not in (None, 'pregame', 'scheduled'):
        return False
    if status and (not isinstance(status, dict) or any(status.get(flag) is True for flag in NON_PREGAME_FLAGS)):
        return False
    if event is not None:
        from app.comparison.game_phase import sporting_phase

        event_status = event.get('status')
        if isinstance(event_status, dict) and any(event_status.get(flag) is True for flag in NON_PREGAME_FLAGS):
            return False
        state = sporting_phase(event)
        if state['reason'] or state['state'] == 'live':
            return False
    try:
        receipt = exact_time(received_at)
        return receipt < exact_time(starts_at) and (source_at is None or exact_time(source_at) <= receipt)
    except (TypeError, ValueError):
        return False


def sgo_pregame(facts):
    context = facts.get('event_context')
    if context:
        phase, status = context.get('phase'), context.get('status')
    else:
        phase, status = facts.get('phase'), facts.get('event_status')
    return phase == 'pregame' and pregame(facts.get('starts_at'), facts.get('received_at'),
                                         source_at=facts.get('source_at'), phase=phase, status=status)


def sgo_working_expiry(starts_at, received_at):
    """Allow restarts and last-known display during the game-day window."""
    return max(stamp(starts_at) + timedelta(days=1), stamp(received_at) + timedelta(hours=6))
