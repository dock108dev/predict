"""Price-only lifecycle evidence. Trading state is not a settlement result."""
from datetime import timedelta
from app.storage.store import stamp
from .source_clock import evidence

# Reuse the established live-input freshness ceiling (current_dependencies).
LIVE_SECONDS = 15
LOOKBACK_HOURS = 24


def sgo_event_status(status):
    return dict(
        ended=status.get('ended') is True or status.get('completed') is True,
        closed=status.get('cancelled') is True,
        live=status.get('live') is True and status.get('started') is True,
        status='delayed' if status.get('delayed') is True else None,
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
    if status.get('identity_conflict'):
        return dict(state='unknown',reason='event_lifecycle_identity_conflict',basis='conflicting_source_game_id')
    states={str(x).lower() for x in (status.get('status'),event.get('state'),*(f.get('status') for f in event.get('observed_identity_facts',[]))) if x}
    if status.get('ended') is True or states & {'completed','complete','final','finished'}:
        return dict(state='final',reason='event_source_completed',basis='explicit_source_state')
    if states & {'suspended','postponed','delayed'}:
        return dict(state='suspended',reason='event_suspended',basis='explicit_source_state')
    if status.get('closed') is True or states & {'cancelled','canceled','abandoned'}:
        return dict(state='unknown',reason='event_closed_or_cancelled',basis='explicit_source_state')
    if status.get('live') is True or states & {'live','in_progress','inprogress'}:
        return dict(state='live',reason=None,basis='explicit_source_state')
    return dict(state='unknown',reason=None,basis='source_state_absent')


def price_phase(event, quote, at):
    at=stamp(at)
    phase=sporting_phase(event)
    if phase['reason'] is not None:return phase
    start=event.get('scheduled_start',event.get('start_at'))
    if not start:return dict(state='unknown',reason='event_schedule_unknown',basis='missing_schedule')
    start=stamp(start)
    if start>at:
        return dict(state='scheduled',reason=None,basis='source_schedule')
    clock,clock_basis,errors=evidence(quote)
    receipt=quote.get('times',{}).get('received_at')
    post_start=bool(clock and receipt and not errors and start<=stamp(clock)<=stamp(receipt)<=at)
    explicit=phase['state']=='live'
    aggregate=quote.get('source',{}).get('provider')=='the_odds_api'
    # Odds API explicitly documents non-completed events after commence_time
    # as in-play. Require a market update after kickoff, not an old book clock.
    if aggregate:
        market_clock=quote.get('provider_clocks',{}).get('market')
        post_start=post_start and bool(market_clock and stamp(market_clock)>=start)
    if post_start and (explicit or aggregate):
        deadline=stamp(clock)+timedelta(seconds=LIVE_SECONDS)
        return dict(state='live',reason=None if at<=deadline else 'live_price_expired',
            basis='post_start_market_update' if aggregate else 'explicit_source_live_and_current_book',
            observed_at=receipt,current_until=deadline.isoformat())
    return dict(state='unknown',reason='post_start_game_state_unverified',basis='schedule_alone_is_insufficient')
