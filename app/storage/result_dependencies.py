"""Complete captured calculation units, distinct from quote-only price proofs.

Discovery always sees the full resolved occurrence. Winner groups share a unit
because funded-pair search crosses those groups. Other financial pair searches
are group-local. Same-outcome comparisons can cross group boundaries, so their
connected groups are joined before slicing. Reference selection retains its full
candidate universe: receipt ordering can change the selected pair.
"""
from copy import deepcopy

from .store import hashed, stamp
from .current_rows import contract_id
from . import observation_publication as publication
from app.dashboard.comparison_board import entries

VERSION = 'predict-result-dependencies-1'


def partitions(bundle):
    """Partition only AFTER complete occurrence resolution and input discovery."""
    values=list(entries(bundle['state_inputs']))
    groups={g['id']:g for _,g,_ in values}
    parents={key:key for key in groups}
    def root(key):
        while parents[key]!=key:
            parents[key]=parents[parents[key]];key=parents[key]
        return key
    def join(a,b):
        a,b=root(a),root(b)
        if a!=b:parents[max(a,b)]=min(a,b)
    winners=[key for key,g in groups.items() if g['market']=='winner' and g['period']=='full_game']
    for key in winners[1:]:join(winners[0],key)
    # This is the same supported predicate identity used by gross comparison.
    # Include even presently ineligible quotes: an eligibility transition must
    # not create a comparison across supposedly independent calculation units.
    from app.comparison.same_outcome import quote_identity
    predicates={}
    for event,group,q in values:
        identity=quote_identity(q,group,event)
        if identity['supported']:
            key=hashed(identity['key'])
            if key in predicates:join(group['id'],predicates[key])
            else:predicates[key]=group['id']
    result={}
    for key in sorted(groups):result.setdefault(root(key),[]).append(key)
    return [dict(id=hashed([VERSION,bundle['game_key'],ids]),groups=ids)
            for ids in sorted(result.values())]


def slice_bundle(bundle, unit):
    """Detach the complete groups; never truncate candidates within a group."""
    selected=set(unit['groups'])
    state=deepcopy(bundle['state_inputs'])
    for event in state['events']:
        event['groups']=[g for g in event['groups'] if g['id'] in selected]
    state['events']=[e for e in state['events'] if e['groups']]
    if not state['events']:raise ValueError('result_unit_removed')
    from app.comparison.shared_templates import ProfilePool
    reachable={key for _,_,q in entries(state) for key in q.get('comparison_input_refs',{}).get('refs',{}).values() if key}
    state['comparison_profiles']=ProfilePool(state['comparison_profiles']).finish(reachable)
    ids={contract_id(dict(quote=q)) for _,_,q in entries(state)}
    # Reference records remain available for provenance; the already discovered
    # profiles retain the exact complete pair chosen from the full universe.
    records=[r for r in bundle['records'] if r['quote']['venue']=='pinnacle' or contract_id(r) in ids]
    return dict(bundle,state_inputs=state,records=records,result_unit=deepcopy(unit),
                input_version=hashed([bundle['input_version'],unit]))


def roster(frame, selector):
    """Conservative completeness proof for ALL candidates in the neighborhood.

    New, removed, newly eligible or corrected contracts invalidate discovery.
    Prices in unrelated groups do not. A reference's receipt/provenance selects
    between complete reference pairs, so every reference candidate binds its own
    price, clocks and receipt, including unselected and currently invalid pairs.
    This deliberately over-invalidates references until a typed selection-index
    proof can establish narrower absence/completeness without normalization.
    """
    events={r[0] for r in publication.neighborhood(frame,selector)}
    return hashed(sorted((cid,row.get('contract_dependency',row['contract_revision']),
        row.get('scoring_dependency'),
        [publication.own(frame,cid),row['received_at']] if row['venue']=='pinnacle' else None)
        for cid,row in frame['offers'].items() if row['event_id'] in events))


def capture(frame, full_bundle, unit, *, complete=None, complete_roster=None, sliced=None):
    sliced=sliced if sliced is not None else slice_bundle(full_bundle,unit)
    saved=publication.manifest(frame,sliced)
    publication.bind_references(frame,saved,sliced)
    # Each selected group's all outcomes, alternatives and candidate legs are
    # observations. Peer price proofs from the full discovered universe are
    # imported, not recomputed from a truncated bundle.
    complete=complete if complete is not None else publication.manifest(frame,full_bundle)
    for cid in saved['selections']:
        saved['eligible'][cid]=complete['eligible'].get(cid,[])
        saved['candidates'][cid]=complete['candidates'][cid]
    neighbors={r[0] for r in publication.neighborhood(frame,saved['selector'])}
    peers={cid:publication.own(frame,cid) for cid,row in frame['offers'].items()
        if row['event_id'] in neighbors and any(
            row['venue'] not in ('pinnacle',selected['venue'])
            and publication._same_candidate(publication.selection(frame,row),selected)
            for selected in saved['selections'].values())}
    from .latest_board import next_boundary
    saved['result_unit']=dict(version=VERSION,**deepcopy(unit),
        receipt_presence={cid:bool(frame['offers'][cid].get('received_at')) for cid in saved['observations'] if cid in frame['offers']},
        peer_inputs=peers,captured_at=full_bundle['as_of'],valid_until=next_boundary(sliced,full_bundle['as_of']),
        roster=complete_roster if complete_roster is not None else roster(frame,saved['selector']))
    return saved


def reasons(frame, saved, *, at):
    checks=publication.reasons(frame,saved)
    unit=saved.get('result_unit')
    if (not unit or unit.get('version')!=VERSION
            or unit.get('roster')!=roster(frame,saved['selector'])):
        checks['all']=sorted(set(checks['all']+['result_candidate_universe_changed']))
    if unit:
        if any(publication.own(frame,cid)!=value for cid,value in unit.get('peer_inputs',{}).items()):
            checks['all'].append('result_candidate_input_changed')
        if unit.get('valid_until') and stamp(at)>=stamp(unit['valid_until']):
            checks['all'].append('result_temporal_boundary')
        for cid in saved['observations']:
            row=frame['offers'].get(cid)
            if row and (bool(row.get('received_at'))!=unit.get('receipt_presence',{}).get(cid)
                    or (row.get('source_at') and row.get('received_at') and stamp(row['source_at'])>stamp(row['received_at']))
                    or (row.get('received_at') and stamp(row['received_at'])>stamp(at))):
                checks['observations'][cid]=sorted(set(checks['observations'].get(cid,[])+['result_receipt_clock_invalid']))
    return checks
