"""Current pregame eligibility from source facts, never settlement inference."""
from .event_links import instant


def assess(event, at):
    status=event.get('status') or {}
    if not isinstance(status,dict):status=dict(status=status)
    facts=event.get('observed_identity_facts',[])
    states={str(v).lower() for v in [status.get('status'),event.get('state'),
        *(f.get('status') for f in facts)] if v not in (None,'')}
    # A later start is not enough to override an explicit source postponement.
    if states & {'postponed','delayed','suspended'}:
        return dict(state='postponed',eligible=False,reason='event_postponed')
    if states & {'cancelled','canceled','abandoned'}:
        return dict(state='cancelled',eligible=False,reason='event_cancelled')
    if status.get('ended') is True or states & {'completed','complete','final','finished'}:
        return dict(state='verified_completed',eligible=False,reason='event_source_completed')
    if status.get('live') is True or states & {'live','in_progress','inprogress'}:
        return dict(state='live',eligible=False,reason='event_live')
    start=event.get('scheduled_start',event.get('start_at'))
    if start is None:
        return dict(state='unknown',eligible=False,reason='event_schedule_unknown')
    if instant(start)<=instant(at):
        return dict(state='scheduled_start_passed',eligible=False,reason='pregame_ended')
    if status.get('closed') is True or states & {'unknown','unverified','tbd'}:
        return dict(state='unknown',eligible=False,reason='event_status_unknown')
    # A schedule can qualify pregame only; it says nothing about completion,
    # payouts, fees or the independently aged original book/quote clocks.
    return dict(state='scheduled',eligible=True,reason=None)


def quote_event(quote, event):
    return quote.get('occurrence_match',{}).get('original_event') or quote.get('event_lifecycle') or event


def witness(event):
    """Only explicit lifecycle restrictions need extra compact wire metadata."""
    value=event.get('status') or {}
    if not isinstance(value,dict):value=dict(status=value)
    normal={'scheduled','active','open'}
    status={k:v for k,v in value.items() if (k in ('live','ended','closed') and v is True)
        or k=='status' and v and str(v).lower() not in normal}
    facts=[dict(status=f['status']) for f in event.get('observed_identity_facts',[])
        if f.get('status') and str(f['status']).lower() not in normal]
    state=event.get('state')
    if not status and not facts and (not state or str(state).lower() in normal):return None
    return dict(scheduled_start=event['scheduled_start'],status=status,
        observed_identity_facts=facts,state=state)
