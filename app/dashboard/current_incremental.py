"""Latest-only group projection. Unchanged groups share their calculation graphs.

All changed groups use the same strict serializer. No price history or replay
queue is retained; hashes and byte bounds describe only the current groups.
"""
from hashlib import sha256
from .current_contract import serialize, packed, quotes_of, age_basis, stamp, identity, MAX_BYTES


def signature(event,group):
    def quote(q):return {k:v for k,v in q.items() if k!='id'}
    g=dict(group,outcomes=[dict(o,quotes={v:quote(q) for v,q in o['quotes'].items()},
        alternatives={v:[quote(q) for q in qs] for v,qs in o.get('alternatives',{}).items()}) for o in group['outcomes']])
    return sha256(packed([{k:v for k,v in event.items() if k!='groups'},g])).hexdigest()


def signatures(raw):
    return {(e['id'],g['id']):signature(e,g) for e in raw['events'] for g in e['groups']}


def aged(group,clock,old_clock):
    """Age scalar shells only; eligibility transitions require re-projection."""
    result=dict(group,outcomes=[]);changed=False
    for original in group['outcomes']:
        outcome=dict(original,quotes={},alternatives={});result['outcomes'].append(outcome)
        for venue,values in [(v,[q]) for v,q in original['quotes'].items()]+[(v,qs) for v,qs in original.get('alternatives',{}).items()]:
            output=[]
            for prior in values:
                q=dict(prior,calculations=dict(prior['calculations']));age_basis(q,clock)
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


def project(raw,previous,known,sizes,*,allow_synthetic=False):
    try:return _project(raw,previous,known,sizes,allow_synthetic=allow_synthetic)
    except (KeyError,TypeError,ArithmeticError,OverflowError,RecursionError):raise ValueError('Invalid normalized current catalog') from None


def _project(raw,previous,known,sizes,*,allow_synthetic):
    if not isinstance(raw['events'],list) or len(raw['events'])>200:raise ValueError('Current event capacity')
    # Explicit engine legs may span groups; preserve the full qualification path.
    if any(q.get('engine_inputs') for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)):
        value=serialize(raw,allow_synthetic=allow_synthetic)
        return value,signatures(raw),{(e['id'],g['id']):len(packed(g))+256*sum(len(quotes_of(o)) for o in g['outcomes']) for e in value['events'] for g in e['groups']},{e['id'] for e in value['events']},dict(projected_groups=sum(len(e['groups']) for e in value['events']),reused_groups=0)
    envelope={k:v for k,v in raw.items() if k!='events'}
    base=serialize(dict(envelope,events=[]),allow_synthetic=allow_synthetic)
    clock=stamp(base['clock_at']);old_clock=stamp(previous['clock_at'])
    same=base['runtime_id']==previous['runtime_id']
    old={(e['id'],g['id']):g for e in previous['events'] for g in e['groups']} if same else {}
    fingerprints={};bounds={};events={};dirty=set();projected=reused=0
    for event in raw['events']:
        event_id=event['id']
        if event_id in events:raise ValueError('Duplicate exact event')
        output=None;group_ids=set()
        for group in event['groups']:
            k=(event_id,group['id']);sig=signature(event,group);cached=old.get(k)
            if cached is not None and known.get(k)==sig:
                calculated,transition=aged(cached,clock,old_clock)
                if transition:cached=None
            else:cached=None
            if cached is None:
                value=serialize(dict(envelope,events=[dict(event,groups=[group])]),allow_synthetic=allow_synthetic)
                normalized=value['events'][0];calculated=normalized['groups'][0]
                metadata={name:v for name,v in normalized.items() if name!='groups'}
                projected+=1;dirty.add(metadata['id'])
                bound=len(packed(calculated))+256*sum(len(quotes_of(o)) for o in calculated['outcomes'])
            else:
                metadata={name:v for name,v in event.items() if name!='groups'}
                reused+=1;bound=sizes[k]
            if output is None:output=dict(metadata,groups=[])
            if calculated['id'] in group_ids:raise ValueError('Duplicate exact group')
            group_ids.add(calculated['id']);output['groups'].append(calculated)
            fingerprints[(output['id'],calculated['id'])]=sig;bounds[(output['id'],calculated['id'])]=bound
        if output is None:
            value=serialize(dict(envelope,events=[event]),allow_synthetic=allow_synthetic)
            output=value['events'][0];dirty.add(output['id'])
        if output['id'] in events:raise ValueError('Duplicate exact event')
        events[output['id']]=output
    previous_events={e['id']:e for e in previous['events']} if same else {}
    for eid,event in events.items():
        prior=previous_events.get(eid)
        if prior is not None and {g['id'] for g in prior['groups']}!={g['id'] for g in event['groups']}:dirty.add(eid)
    base['events']=sorted(events.values(),key=lambda e:(e['start_at'],e['id']))
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
    if sum(bounds.values())+len(packed(dict(base,events=[])))+sum(len(packed({k:v for k,v in e.items() if k!='groups'})) for e in base['events'])>MAX_BYTES:raise ValueError('Serialized current state byte capacity exceeded')
    return base,fingerprints,bounds,dirty,dict(projected_groups=projected,reused_groups=reused)
