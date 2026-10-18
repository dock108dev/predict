"""Explicit schedule metadata ordering; book clocks never rank event facts.

Legacy derived starts without their own witness cannot authorize reconciliation.
All projections are detached; stored source statements and quote clocks survive.
"""
from copy import deepcopy
from .store import hashed, exact_time

VERSION = 'predict-schedule-metadata-1'


def core(event):
    identity={k:event.get(k) for k in ('id','sport','competition','home','away',
        'participants','game_number','original_start','replacement_game_id','shared_provider_ids','source_participant_roles')}
    identity['native_witness_ids']=sorted({hashed({k:fact.get(k) for k in
        ('id','source_id','source_provider','main_game_event_ticker','home_team_id','away_team_id')})
        for fact in event.get('observed_identity_facts',[])})
    return hashed(identity)


def witness(event):
    value=event.get('schedule_metadata')
    if not isinstance(value,dict) or value.get('version')!=VERSION:return None
    try:
        if value['revision']!=hashed({k:v for k,v in value.items() if k!='revision'}):return None
        if exact_time(value['start'])!=exact_time(event['scheduled_start']):return None
        if value['native_event_id']!=event['id'] or not value['authority'] or not value['proofs']:return None
        if value.get('received_at') is None:
            if value.get('evidence_class')!='retained_exact_sql_snapshot':return None
            exact_time(value['observed_no_later_than'])
            if any(not p.get('snapshot_sha256') or not p.get('path') for p in value['proofs']):return None
        else:
            exact_time(value['received_at'])
            if any(not p.get('body_sha256') or not p.get('path') or
                   exact_time(p['received_at'])<exact_time(value['received_at']) for p in value['proofs']):return None
    except (KeyError,TypeError,ValueError):return None
    return value


def binding(event):
    return dict(version=VERSION,native_event_id=event['id'],core=core(event),
        original_start=event['scheduled_start'],metadata=deepcopy(witness(event)))


def before(old,new):
    """An earlier snapshot bounds observation time; it is not a source receipt."""
    upper=old.get('received_at') or old.get('observed_no_later_than')
    lower=new.get('received_at')
    return bool(upper and lower and exact_time(upper)<exact_time(lower))


def retained_binding(previous,event,contract,*,captured_at,path,snapshot_sha256,contract_revision):
    """Recover a lost binding only from an exact prior contract/event capture."""
    current=witness(event)
    if (current is None or not current.get('received_at') or core(previous)!=core(event)
            or previous.get('conflicting_duplicate') or previous.get('occurrence_conflict')
            or event.get('schedule_conflict') or current['authority'][0]!='kalshi'
            or 'schedule_binding' in contract.get('comparison_source_metadata',{})
            or exact_time(contract['market_identity']['scheduled_start'])!=exact_time(previous['scheduled_start'])
            or exact_time(previous['scheduled_start'])==exact_time(event['scheduled_start'])
            or exact_time(captured_at)>=exact_time(current['received_at'])):return None
    facts=previous.get('observed_identity_facts',[])
    if (not facts or any(not fact.get('id') or not fact.get('start_date') for fact in facts)
            or len({fact['id'] for fact in facts})!=1
            or any(exact_time(fact['start_date'])!=exact_time(previous['scheduled_start']) for fact in facts)
            or current['authority']!=['kalshi','milestone',facts[0]['id']]):return None
    metadata=dict(version=VERSION,native_event_id=previous['id'],authority=deepcopy(current['authority']),
        start=previous['scheduled_start'],received_at=None,observed_no_later_than=captured_at,
        evidence_class='retained_exact_sql_snapshot',proofs=[dict(path=path,snapshot_sha256=snapshot_sha256,
            event_revision=hashed(previous),contract_revision=contract_revision,
            native_identity_facts=deepcopy(facts))])
    metadata['revision']=hashed(metadata)
    return binding(dict(previous,schedule_metadata=metadata))


def choose(previous, incoming):
    """Select independently observed event metadata, or retain a bounded refusal."""
    if previous is None:return incoming
    old,new=witness(previous),witness(incoming)
    same=exact_time(previous['scheduled_start'])==exact_time(incoming['scheduled_start'])
    if old and new and old.get('received_at') and new.get('received_at') and old['authority']==new['authority'] and core(previous)==core(incoming):
        a,b=exact_time(old['received_at']),exact_time(new['received_at'])
        if b<a:return previous
        if b>a:return incoming
        if same and not previous.get('schedule_conflict'):return incoming
        reason='schedule_equal_metadata_conflict'
    elif same and not previous.get('schedule_conflict'):
        # An unproved repeated book cannot replace a retained metadata witness.
        return previous if old and not new else incoming
    elif new and not old and not previous.get('schedule_conflict'):
        # New authentic metadata may replace a legacy shared row, but older
        # contracts still need their own witness before their date can project.
        return incoming
    else:reason='schedule_metadata_order_unverified'
    value=deepcopy(previous)
    value['schedule_conflict']=dict(reason=reason,starts=sorted(set([
        previous['scheduled_start'],incoming['scheduled_start']])),
        witnesses=[deepcopy(old),deepcopy(new)])
    return value


def project(event, contract):
    """Reconcile a proved revision of the same event; preserve original binding."""
    try:return _project(event,contract)
    except (AttributeError,KeyError,TypeError,ValueError):
        # Malformed comparison metadata belongs to catalog's isolated validator;
        # one bad contract cannot turn a coherent SQL capture into a global fault.
        return deepcopy(contract)


def _project(event, contract):
    value=deepcopy(contract)
    if event.get('schedule_conflict'):return value
    market=value['market_identity']
    if exact_time(market['scheduled_start'])==exact_time(event['scheduled_start']):return value
    meta=value.get('comparison_source_metadata',{})
    prior=meta.get('schedule_binding',{})
    old=prior.get('metadata');new=witness(event)
    # Validate the retained earlier witness against the earlier derived start.
    original=dict(event,scheduled_start=market['scheduled_start'],schedule_metadata=old)
    if (prior.get('version')!=VERSION or prior.get('native_event_id')!=event['id']
            or prior.get('core')!=core(event) or witness(original) is None or new is None
            or old['authority']!=new['authority']
            or not before(old,new)):return value
    market['scheduled_start']=event['scheduled_start']
    meta['schedule_reconciliation']=dict(version=VERSION,reason='newer_same_source_event_metadata',
        original_derived_start=prior['original_start'],current_derived_start=event['scheduled_start'],
        original_metadata_revision=old['revision'],current_metadata=deepcopy(new))
    return value


def diagnostic(record):
    try:return _diagnostic(record)
    except (AttributeError,KeyError,TypeError,ValueError):return None


def _diagnostic(record):
    event=record['event'];market=record['market_identity'];source=record['quote']['source']
    if event.get('schedule_conflict'):reason=event['schedule_conflict']['reason']
    elif exact_time(market['scheduled_start'])!=exact_time(event['scheduled_start']):
        reason='schedule_binding_unverified'
    else:return None
    missing=dict(schedule_equal_metadata_conflict='Authoritative later correction resolving contradictory same-clock schedule witnesses',
        schedule_metadata_order_unverified='Common schedule authority, compatible occurrence facts and proven metadata order',
        schedule_binding_unverified='Original contract schedule witness and ordered current event witness')
    return dict(reason=reason,provider=source['provider'],native_event_id=source['native_event_id'],
        native_market_id=source['native_market_id'],native_outcome_id=source['native_outcome_id'],
        event_start=event['scheduled_start'],market_start=market['scheduled_start'],
        missing_fact=missing[reason])
