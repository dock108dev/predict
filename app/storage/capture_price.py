"""Incremental native price capture with complete structural dependency closure.

The last immutable input owns the plan; no extra history/cache or authority is
introduced. SQL membership and contract/event revisions must match exactly.
Only changed native records are transferred. Unknown quote changes, references,
policy/controls and structural/temporal changes fall back to complete capture.
Changed groups use the same full validator and output projector as cold capture.
"""
from copy import deepcopy
from time import monotonic
from uuid import uuid4

from .store import hashed, stamp
from .current_rows import CurrentRowStore, contract_id
from .capture_structure import structure, topology, slots, restore_events


def begin(binding):
    return dict(version=2,binding=hashed(binding),records={},audit_heads={},catalogs=[])


def remember_frame(basis,frame,at):
    for r in frame['records']:
        q=r['quote'];s=q['source']
        basis['records'][contract_id(r)]=dict(proof=hashed(structure(r)),source=hashed(s),
            event=[s['provider'],s['native_event_id']],evidence=q['provenance'].get('sha256'))
    from .comparison_board import _records
    for r in _records(frame['records'],at):
        source=r['quote']['source']
        basis['audit_heads'][hashed([source['provider'],source['native_event_id']])]=contract_id(r)
    basis['temporal']=temporal(at)


def temporal(at):
    # A previously inapplicable edge can become active even when no existing
    # quote carries that link. Bind the complete reviewed edge universe.
    from app.comparison.occurrence_matching import OccurrenceResolver
    instant=stamp(at)
    return [[e.id,e.active(instant),stamp(e.observed_at)<=instant,stamp(e.effective_from)<=instant]
        for e in OccurrenceResolver().links.edges]


def remember_catalog(basis,context,catalog):
    state=context._catalog_inputs.get(catalog['game_key'])
    if state is None:return
    by_source={hashed(r['quote']['source']):r for r in catalog['records']}
    basis['catalogs'].append(dict(game=catalog['game_key'],
        envelope={k:v for k,v in state.items() if k!='events'},events=topology(state['events'],by_source)))


def capture(db,previous,*,at,binding,event_ids,diagnostics=None,_frame_dependencies=None):
    """Return a validated replacement or None for the complete capture owner.

    Caller holds the repeatable-read publication transaction. Decoded previous
    inputs are private; original immutable SQL inputs and selected leases stay
    untouched. No pointer or current value is published by this function.
    """
    from .ordinary_publication import dependencies
    from .comparison_snapshot import captured_price
    from app.comparison.event_links import digest
    from app.dashboard.current_contract import drain,serialize_steps,price_clock_status
    from app.dashboard.comparison_board import entries
    from app.comparison.estimated_policy import DEFAULT_POLICY
    def refuse(reason):
        if diagnostics is not None:diagnostics['fallback']=reason
        return None
    start=monotonic();basis=previous.get('_price_basis')
    if (not basis or basis.get('version')!=2 or basis['binding']!=hashed(binding)
            or previous['issues'] or stamp(at)<stamp(previous['captured_at'])):return refuse('basis_or_clock')
    if basis.get('temporal')!=temporal(at):return refuse('registry_boundary')
    dep=dependencies(db,event_ids) if _frame_dependencies is None else _frame_dependencies
    old=previous['dependencies']
    if dep.keys()!=old.keys():return refuse('offer_membership')
    if any(dep[k][1]!=old[k][1] for k in dep):return refuse('contract_revision')
    if any(dep[k][2]!=old[k][2] for k in dep):return refuse('event_revision')
    changed={k for k in dep if dep[k]!=old[k]}
    by_id={contract_id(r['original_record']):r for r in previous['quotes']}
    if not changed<=by_id.keys():return refuse('reference_or_unselected')
    if any(by_id[k]['venue'] not in ('kalshi','polymarket_us') for k in changed):return refuse('non_native')
    if any(stamp(g['start_at'])<=stamp(at) for g in previous['games']):return refuse('kickoff')
    for row in previous['quotes']:
        link=row['original_record']['quote'].get('occurrence_link') or {}
        if any(v and stamp(previous['captured_at'])<stamp(v)<=stamp(at)
               for k,v in link.items() if k in ('effective_from','effective_until')):return refuse('link_boundary')
    frame=CurrentRowStore(db).capture(include_depth=False,event_ids=event_ids,contract_ids=sorted(changed))
    fresh={contract_id(r):r for r in frame['records']}
    if fresh.keys()!=changed or str(frame['epoch'])!=previous['epoch']:return refuse('epoch_or_expiry')
    # Receipt/status observation clocks advance on every admitted batch. They
    # belong in the new envelope, not in the structural authority identity.
    # Quote execution changes only with the source state; each retained quote
    # still owns its original book/confirmation clocks and evidence.
    authority=lambda states:{k:v.get('state') for k,v in states.items()}
    if authority(frame['source_status'])!=authority(previous['sources']):return refuse('source_authority')
    if any(k not in basis['records'] or hashed(structure(r))!=basis['records'][k]['proof'] for k,r in fresh.items()):return refuse('quote_structure')
    # Keep a complete evidence map, including source events not selected for
    # display. The resolver's deterministic last record per source event owns
    # each occurrence audit witness; changing that witness invalidates all peers.
    for cid,r in fresh.items():
        basis['records'][cid]['evidence']=r['quote']['provenance'].get('sha256')
    evidence={}
    for cid in basis['audit_heads'].values():
        value=basis['records'][cid];evidence[tuple(value['event'])]=value['evidence']
    affected=set(changed);records={}
    for cid,row in by_id.items():
        r=row['original_record'];q=r['quote']
        if cid in fresh:
            value=fresh[cid]
            # The whole contract/event and the complete non-price quote proof
            # matched. Replace fresh quote evidence; retain only the exact
            # resolver-owned projection, never old clocks or confirmation.
            q=dict(value['quote'],**{k:q[k] for k in ('occurrence_match','occurrence_link') if k in q})
            status=frame['source_status'].get(q['venue'],frame['source_status'].get(q['source']['provider'],{}))
            if status.get('state') not in (None,'available','budget_delayed'):q['state']=status['state']
            r=dict(r,quote=q,comparison_source_metadata=dict(r.get('comparison_source_metadata',{})))
            meta=value.get('comparison_source_metadata',{})
            if 'observed_at' in meta:r['comparison_source_metadata']['observed_at']=meta['observed_at']
        audit=q.get('occurrence_match')
        if audit and any(m.get('evidence_sha256')!=evidence.get((m['provider'],m['native_event_id'])) for m in audit['members']):
            audit=deepcopy(audit)
            for member in audit['members']:
                key=(member['provider'],member['native_event_id'])
                if key not in evidence:return refuse('audit_closure')
                member['evidence_sha256']=evidence[key]
            audit['revision']=digest({k:v for k,v in audit.items() if k!='revision'})
            r=dict(r,quote=dict(q,occurrence_match=audit));affected.add(cid)
        records[hashed(r['quote']['source'])]=r
    games={g['game_key']:g for g in previous['games']};replacement={};groups=0
    affected_sources={basis['records'][cid]['source'] for cid in affected}
    for catalog in basis['catalogs']:
        selected=[]
        for event in catalog['events']:
            dirty=[g for g in event['groups'] if any(owner[index]['source'] in affected_sources
                for _,_,_,owner,index in slots([dict(event,groups=[g])]))]
            if dirty:selected.append(dict(event,groups=deepcopy(dirty)))
        if not selected:continue
        needed={owner[index]['source'] for _,_,_,owner,index in slots(selected)}
        if not needed<=records.keys():return refuse('group_closure')
        executions={key:dict(records[key],quote={k:v for k,v in records[key]['quote'].items()
            if k not in ('sharp_reference','comparison_input_refs','comparison_input_status','engine_inputs')}) for key in needed}
        state=dict(catalog['envelope'],clock_at=at,projected_at=at,events=restore_events(selected,executions))
        validated=drain(serialize_steps(state,prices_only=True,estimate_policy=DEFAULT_POLICY))
        game=games[catalog['game']]
        for event,group,q in entries(validated):
            r=records[hashed(q['source'])]
            row=captured_price(event,group,q,r,game,game['league'])
            replacement[row['id']]=row
        groups+=sum(len(e['groups']) for e in selected)
    if not {by_id[k]['id'] for k in affected}<=replacement.keys():return refuse('missing_output')
    if not replacement.keys()<={r['id'] for r in previous['quotes']}:return refuse('output_membership')
    result=dict(previous,id=uuid4().hex,captured_at=at,dependencies=dep,
        quotes=[replacement.get(r['id'],r) for r in previous['quotes']],sources=frame['source_status'],
        capture_seconds=round(monotonic()-start,3))
    # Retained benchmark quote shells also carry derived age fields. Reassess
    # those at the new evaluation time without changing any evidence clock.
    for row in result['quotes']:
        if row['id'] not in replacement and row.get('benchmark_quote'):
            price_clock_status(row['benchmark_quote'],stamp(at))
    result['_price_capture']=dict(path='incremental',read_records=len(fresh),
        validated_groups=groups,replaced_rows=len(replacement),reused_rows=len(result['quotes'])-len(replacement))
    return result
