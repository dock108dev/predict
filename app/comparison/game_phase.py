"""Price-only lifecycle evidence. Trading state is not a settlement result."""
from datetime import timedelta
from app.storage.store import stamp
from .source_clock import evidence

# Reuse the established live-input freshness ceiling (current_dependencies).
LIVE_SECONDS = 15
ODDSLINK_LIVE_SECONDS = 30
PREGAME_SPORTSBOOK_SECONDS = 15 * 60
LOOKBACK_HOURS = 24


def sgo_event_status(status):
    return dict(
        ended=status.get('ended') is True or status.get('completed') is True,
        live=status.get('live') is True,
        status='cancelled' if status.get('cancelled') is True else
               'suspended' if status.get('suspended') is True else
               'delayed' if status.get('delayed') is True else
               'started' if status.get('started') is True and not status.get('live') else None,
    )


def original_price_phase(record, at):
    event, quote = record['event'], record['quote']
    if quote['source']['provider'] == 'sportsgameodds' and 'status' not in event:
        retained = (record.get('comparison_source_metadata') or {}).get('provider_event_status')
        if isinstance(retained, dict):
            event = dict(event, status=sgo_event_status(retained))
    return price_phase(event, quote, at)


def sporting_phase(event):
    status=event.get('status') or {}
    if not isinstance(status,dict):status={'status':status}
    if (status.get('identity_conflict') or event.get('occurrence_conflict')
            or event.get('conflicting_duplicate') or event.get('schedule_conflict')):
        return dict(state='unknown',reason='event_lifecycle_identity_conflict',basis='conflicting_source_game_id')
    states={str(x).lower() for x in (status.get('status'),event.get('state'),*(f.get('status') for f in event.get('observed_identity_facts',[]))) if x}
    if states & {'cancelled','canceled','abandoned'}:
        return dict(state='cancelled',reason='event_cancelled',basis='explicit_source_state')
    if status.get('ended') is True or states & {'completed','complete','final','finished'}:
        return dict(state='final',reason='event_source_completed',basis='explicit_source_state')
    if states & {'suspended','postponed','delayed'}:
        return dict(state='suspended',reason='event_suspended' if 'suspended' in states else 'event_postponed',
                    basis='explicit_source_state')
    if status.get('closed') is True or states & {'closed','unknown','unverified','tbd'}:
        return dict(state='unknown',reason='event_status_unknown',basis='explicit_source_state')
    rescheduled = ('rescheduled' in states or event.get('schedule_status') == 'rescheduled' or
                   bool(event.get('replacement_game_id')))
    if rescheduled and not _linked_reschedule(event):
        return dict(state='unknown',reason='event_reschedule_unlinked',basis='replacement_identity_unverified')
    if status.get('live') is True or states & {'live','in_progress','inprogress'}:
        return dict(state='live',reason=None,basis='explicit_source_state')
    if states & {'started','incomplete'}:
        return dict(state='unknown',reason='post_start_game_state_unverified',basis='explicit_source_state')
    if rescheduled:
        return dict(state='unknown',reason=None,basis='linked_reschedule')
    return dict(state='unknown',reason=None,basis='source_state_absent')


def _linked_reschedule(event):
    earlier = list(event.get('previous_starts_at') or ())
    if original := event.get('original_start'):
        earlier.append(original)
    if (not earlier or not event.get('id') or not event.get('scheduled_start')
            or event.get('competition') == 'MLB' and event.get('game_number') not in (1, 2)):
        return False
    from app.storage.schedule_metadata import witness

    try:
        return any(stamp(value) != stamp(event['scheduled_start']) for value in earlier) and witness(event) is not None
    except (AttributeError, TypeError, ValueError):
        return False


def sporting_clock(event):
    status = event.get('status')
    return (status.get('observed_at') if isinstance(status, dict) else None) or (
        event.get('schedule_metadata') or {}).get('received_at')


def scheduled_phase(event, at):
    """Classify authority of the occurrence's start and explicit source state."""
    at = stamp(at)
    phase = sporting_phase(event)
    if clock := sporting_clock(event):
        try:
            if stamp(clock) > at:
                return dict(state='unknown', reason='event_state_future', basis='source_state_clock')
        except (AttributeError, TypeError, ValueError):
            return dict(state='unknown', reason='event_status_unknown', basis='source_state_clock')
    if phase['reason'] is not None:
        return phase
    start = event.get('scheduled_start', event.get('start_at'))
    if not start:
        return dict(state='unknown', reason='event_schedule_unknown', basis='missing_schedule')
    if stamp(start) > at:
        if phase['state'] == 'live':
            return dict(phase, reason='event_started_before_schedule')
        return dict(state='scheduled', reason=None,
                    basis='linked_reschedule' if phase['basis'] == 'linked_reschedule' else 'source_schedule')
    return phase


def price_phase(event, quote, at):
    at=stamp(at)
    phase=scheduled_phase(event, at)
    if phase['reason'] is not None:return phase
    if phase['state'] == 'scheduled':return phase
    start=stamp(event.get('scheduled_start',event.get('start_at')))
    clock,_,errors=evidence(quote)
    receipt=quote.get('times',{}).get('received_at')
    post_start=bool(clock and receipt and not errors and start<=stamp(clock)<=stamp(receipt)<=at)
    status_at = sporting_clock(event)
    explicit=phase['state']=='live' and (not status_at or start <= stamp(status_at))
    aggregate=quote.get('source',{}).get('provider')=='the_odds_api'
    # Odds API explicitly documents non-completed events after commence_time
    # as in-play. Require a market update after kickoff, not an old book clock.
    market_clock = None
    if aggregate:
        market_clock=quote.get('provider_clocks',{}).get('market')
        post_start=post_start and bool(market_clock and start<=stamp(market_clock)<=stamp(receipt))
    if post_start and (explicit or aggregate):
        # The public board is a polled, cached aggregate. Its retail price
        # allowance is independent of the native execution-book freshness cap.
        from .public_sportsbook_estimate import SOURCE
        maximum_age = ODDSLINK_LIVE_SECONDS if quote.get('source', {}).get('provider') == SOURCE else LIVE_SECONDS
        deadline=stamp(clock)+timedelta(seconds=maximum_age)
        return dict(state='live',reason=None if at<=deadline else 'live_price_expired',
            basis='post_start_market_update' if aggregate else 'explicit_source_live_and_current_book',
            observed_at=market_clock if aggregate else status_at,current_until=deadline.isoformat())
    return dict(state='unknown',reason='post_start_game_state_unverified',basis='schedule_alone_is_insufficient')
