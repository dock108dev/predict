"""Latest-only group projection. Unchanged groups share their calculation graphs.

All changed groups use the same strict serializer. No price history or replay
queue is retained; hashes and byte bounds describe only the current groups.
"""
from hashlib import sha256
from app.comparison.estimated_policy import load
from .current_contract import serialize, packed, quotes_of, age_basis, stamp, identity, MAX_BYTES, drain, serialize_steps, byte_count_steps


def signature(event,group,profiles=None,policy_revision=None):
    def quote(q):return {k:v for k,v in q.items() if k!='id'}
    g=dict({k:v for k,v in group.items() if k not in ('comparison_pairs','comparison_search')},outcomes=[dict(o,quotes={v:quote(q) for v,q in o['quotes'].items()},
        alternatives={v:[quote(q) for q in qs] for v,qs in o.get('alternatives',{}).items()}) for o in group['outcomes']])
    from app.comparison.current_dependencies import group_dependencies
    dependencies=group_dependencies(group,profiles or {})
    return sha256(packed([{k:v for k,v in event.items() if k!='groups'},g,dependencies,policy_revision or load().revision])).hexdigest()


def signatures(raw,policy_revision=None):
    return {(e['id'],g['id']):signature(e,g,raw.get('comparison_profiles'),policy_revision) for e in raw['events'] for g in e['groups']}


def aged(group,clock,old_clock,profiles=None,event=None):
    """Age scalar shells only; eligibility transitions require re-projection."""
    result=dict(group,outcomes=[]);changed=False
    for original in group['outcomes']:
        outcome=dict(original,quotes={},alternatives={});result['outcomes'].append(outcome)
        for venue,values in [(v,[q]) for v,q in original['quotes'].items()]+[(v,qs) for v,qs in original.get('alternatives',{}).items()]:
            output=[]
            for prior in values:
                q=dict(prior,calculations=dict(prior['calculations']));age_basis(q,clock)
                from app.comparison.current_dependencies import eligibility, temporal_revision, refresh_metadata_status
                refresh_metadata_status(q,clock)
                reasons=list(eligibility(q, profiles or {}, clock))
                if reasons!=prior.get('comparison_dependency_reasons',[]):changed=True
                q['comparison_dependency_reasons']=reasons
                q['comparison_temporal_revision']=temporal_revision(q,profiles or {},clock)
                if q['comparison_temporal_revision']!=prior.get('comparison_temporal_revision'):changed=True
                if 'funded_estimate' in prior['calculations']:
                    from app.comparison.estimated_ev import temporal
                    if temporal(q,profiles or {},clock,event)!=temporal(q,profiles or {},old_clock,event):changed=True
                future=lambda at,when:at is not None and stamp(at)>when
                confirmation=q.get('book_confirmation',{})
                if (q['stale']!=prior['stale'] or
                    future(q['times']['source_at'],clock)!=future(q['times']['source_at'],old_clock) or
                    future(confirmation.get('received_at'),clock)!=future(confirmation.get('received_at'),old_clock)):
                    changed=True
                if q.get('sharp_reference'):
                    from app.collection.current_benchmark import calculate
                    q['calculations']['ev']=calculate(q,clock)
                    if q['calculations']['ev']['eligible']!=prior['calculations']['ev']['eligible']:changed=True
                output.append(q)
            if venue in original['quotes'] and len(values)==1 and values[0] is original['quotes'][venue]:outcome['quotes'][venue]=output[0]
            else:outcome['alternatives'][venue]=output
    return result,changed


def project(raw,previous,known,sizes,*,allow_synthetic=False,borrow_profiles=False):
    try:return drain(project_steps(raw,previous,known,sizes,allow_synthetic=allow_synthetic,borrow_profiles=borrow_profiles))
    except (KeyError,TypeError,ArithmeticError,OverflowError,RecursionError):raise ValueError('Invalid normalized current catalog') from None


def project_steps(raw,previous,known,sizes,*,allow_synthetic=False,borrow_profiles=False,progress=None):
    if not isinstance(raw['events'],list) or len(raw['events'])>200:raise ValueError('Current event capacity')
    # Explicit engine legs may span groups; preserve the full qualification path.
    if any(q.get('engine_inputs') for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)):
        value=yield from serialize_steps(raw,allow_synthetic=allow_synthetic)
        if progress is not None:
            for e in value['events']:
                for g in e['groups']:progress('group',g)
                progress('pairs',(e['funded_pairs'],e['funded_pair_search']))
        return value,signatures(raw,value['estimate_policy']['revision']),{(e['id'],g['id']):len(packed(g))+256*sum(len(quotes_of(o)) for o in g['outcomes']) for e in value['events'] for g in e['groups']},{e['id'] for e in value['events']},dict(projected_groups=sum(len(e['groups']) for e in value['events']),reused_groups=0)
    envelope={k:v for k,v in raw.items() if k!='events'}
    policy=load()
    # Only internal temporal reconstruction can borrow a registry already
    # admitted and privately owned by this exact publication. Public source
    # admission and serializer consumers still take their defensive copies.
    if borrow_profiles:
        if raw.get('runtime_id')!=previous['runtime_id'] or raw.get('comparison_profiles') is not previous.get('comparison_profiles'):
            raise ValueError('Temporal registry ownership changed')
        base=serialize(dict({k:v for k,v in envelope.items() if k!='comparison_profiles'},events=[]),allow_synthetic=allow_synthetic,estimate_policy=policy)
        if 'comparison_profiles' in previous:base['comparison_profiles']=previous['comparison_profiles']
    else:base=yield from serialize_steps(dict(envelope,events=[]),allow_synthetic=allow_synthetic,estimate_policy=policy)
    clock=stamp(base['clock_at']);old_clock=stamp(previous['clock_at'])
    same=base['runtime_id']==previous['runtime_id'] and base['estimate_policy']==previous.get('estimate_policy')
    old={(e['id'],g['id']):g for e in previous['events'] for g in e['groups']} if same else {}
    fingerprints={};bounds={};events={};dirty=set();projected=reused=0
    from app.comparison.projection_batches import groups as fair_groups
    from time import perf_counter
    seen_events=set();seen_groups={}
    for event in raw['events']:
        event_id=event['id']
        if event_id in seen_events:raise ValueError('Duplicate exact event')
        seen_events.add(event_id);seen_groups[event_id]=set()
    batch_metrics=[]
    for batch in fair_groups(raw['events'],size=1):
        tick=perf_counter()
        for event,group in batch:
            event_id=event['id']
            k=(event_id,group['id']);sig=signature(event,group,raw.get('comparison_profiles'),policy.revision);cached=old.get(k)
            if cached is not None and known.get(k)==sig:
                calculated,transition=aged(cached,clock,old_clock,raw.get('comparison_profiles'),event)
                if transition:cached=None
            else:cached=None
            if cached is None:
                from app.comparison.shared_templates import shared, subset
                local_envelope=envelope
                if shared(raw.get('comparison_profiles')):
                    local_envelope=dict(envelope,comparison_profiles=subset(raw['comparison_profiles'],group))
                value=yield from serialize_steps(dict(local_envelope,events=[dict(event,groups=[group])]),allow_synthetic=allow_synthetic,estimate_policy=policy,paired=False)
                normalized=value['events'][0];calculated=normalized['groups'][0]
                metadata={name:v for name,v in normalized.items() if name!='groups'}
                projected+=1;dirty.add(metadata['id'])
                bound=len(packed(calculated))+256*sum(len(quotes_of(o)) for o in calculated['outcomes'])
            else:
                metadata={name:v for name,v in event.items() if name!='groups'}
                reused+=1;bound=sizes[k]
            output=events.setdefault(event_id,dict(metadata,groups=[]))
            group_ids=seen_groups[event_id]
            if calculated['id'] in group_ids:raise ValueError('Duplicate exact group')
            group_ids.add(calculated['id']);output['groups'].append(calculated)
            fingerprints[(output['id'],calculated['id'])]=sig;bounds[(output['id'],calculated['id'])]=bound
            if progress is not None:progress('group',calculated)
        batch_metrics.append(dict(groups=len(batch),events=len({e['id'] for e,g in batch}),seconds=perf_counter()-tick))
        yield ('projected_group',k)
    for event in raw['events']:
        if not event['groups']:
            value=serialize(dict(envelope,events=[event]),allow_synthetic=allow_synthetic,estimate_policy=policy)
            events[event['id']]=value['events'][0];dirty.add(event['id'])
        else:
            outputs={g['id']:g for g in events[event['id']]['groups']}
            events[event['id']]['groups']=[outputs[g['id']] for g in event['groups']]
    previous_events={e['id']:e for e in previous['events']} if same else {}
    for eid,event in events.items():
        prior=previous_events.get(eid)
        if prior is not None and {g['id'] for g in prior['groups']}!={g['id'] for g in event['groups']}:dirty.add(eid)
    base['events']=sorted(events.values(),key=lambda e:(e['start_at'],e['id']))
    from app.comparison.estimated_pair import assembly_steps
    for event in base['events']:
        prior=previous_events.get(event['id'])
        if event['id'] not in dirty and prior is not None and 'funded_pairs' in prior:
            event['funded_pairs']=prior['funded_pairs'];event['funded_pair_search']=prior['funded_pair_search']
        else:
            event['funded_pairs'],event['funded_pair_search']=yield from assembly_steps(event,raw.get('comparison_profiles',{}),clock,policy=policy)
        if progress is not None:progress('pairs',(event['funded_pairs'],event['funded_pair_search']))
    instruments={};quote_ids=set();quote_count=0
    for e in base['events']:
        for g in e['groups']:
            for o in g['outcomes']:
                for q in quotes_of(o):
                    source=q['source'];instrument=identity('instrument',[q['venue'],*[source[k] for k in ('provider','native_event_id','native_market_id','native_outcome_id','native_side','quote_side')]])
                    if instrument in instruments and instruments[instrument]!=o['id']:raise ValueError('Native instrument bound to conflicting selections')
                    instruments[instrument]=o['id']
                    if q['id'] in quote_ids:raise ValueError('Duplicate exact quote')
                    quote_ids.add(q['id']);quote_count+=1
    if len(bounds)>2000 or quote_count>16000:raise ValueError('Catalog capacity exceeded')
    envelope_bytes=yield from byte_count_steps(dict(base,events=[]))
    if sum(bounds.values())+envelope_bytes+sum(len(packed({k:v for k,v in e.items() if k!='groups'})) for e in base['events'])>MAX_BYTES:raise ValueError('Serialized current state byte capacity exceeded')
    metrics=dict(projected_groups=projected,reused_groups=reused)
    from app.comparison.shared_templates import shared
    if shared(raw.get('comparison_profiles')):metrics['batches']=batch_metrics
    return base,fingerprints,bounds,dirty,metrics
