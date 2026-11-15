"""Current pregame eligibility from source facts, never settlement inference."""
from .game_phase import scheduled_phase


def assess(event, at):
    phase = scheduled_phase(event, at)
    state, reason = phase['state'], phase['reason']
    if state == 'live':
        return dict(state=state, eligible=False, reason='event_live')
    if state == 'unknown' and reason is None:
        return dict(state='scheduled_start_passed', eligible=False, reason='pregame_ended')
    if state == 'suspended':
        return dict(state='postponed', eligible=False, reason='event_postponed')
    return dict(state='verified_completed' if state == 'final' else state,
                eligible=state == 'scheduled', reason=reason)


def quote_event(quote, event):
    return quote.get('occurrence_match',{}).get('original_event') or quote.get('event_lifecycle') or event


def witness(event):
    """Only explicit lifecycle restrictions need extra compact wire metadata."""
    value=event.get('status') or {}
    if not isinstance(value,dict):value=dict(status=value)
    normal={'scheduled','active','open'}
    status={k:v for k,v in value.items() if (k in ('live','ended','closed','identity_conflict') and v is True)
        or k=='status' and v and str(v).lower() not in normal}
    facts=[dict(status=f['status']) for f in event.get('observed_identity_facts',[])
        if f.get('status') and str(f['status']).lower() not in normal]
    state=event.get('state')
    optional = {k: event[k] for k in ('id','competition','original_start','previous_starts_at','game_number','schedule_status',
        'replacement_game_id','schedule_metadata','schedule_conflict','occurrence_conflict','conflicting_duplicate')
        if k in event}
    if not (status or facts or optional.keys() & {'schedule_status', 'replacement_game_id', 'schedule_conflict',
            'occurrence_conflict', 'conflicting_duplicate'}) and (not state or str(state).lower() in normal):return None
    if clock := value.get('observed_at'):
        status['observed_at'] = clock
    return dict(scheduled_start=event['scheduled_start'],status=status,
        observed_identity_facts=facts,state=state,**optional)
