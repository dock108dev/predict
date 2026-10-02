"""Exact predicate inventory and atomic two-source operating reservations.

Source receipts remain authority. Selection cannot create quotes or coverage.
"""
from collections import defaultdict
from app.dashboard.session_projection import stable
from .v1_comparison import predicates
from .v1_coverage import PAIRED

POLICY='v1-counterpart-completion-1'

def key(binding, predicate):
    # Exactly the same key as ordinary raw comparison admission.
    identity={k:v for k,v in binding['identity'].items() if k not in ('line','roles')}
    return stable([identity,predicate])

def inventory(catalogs):
    groups=defaultdict(list)
    for venue,cat in catalogs.items():
        events={e['id']:e for e in cat['events']}
        for market in cat['markets']:
            binding=market.get('v1_raw_binding') or {}
            if binding.get('status')!='BOUND_RAW_PREDICATE':continue
            event=events.get(market['event_id'])
            if not event:continue
            for side,predicate,_ in predicates(binding):
                groups[key(binding,predicate)].append(dict(source=venue,event_id=event['id'],market_id=market['id'],
                    side_id=side,predicate=predicate,identity=binding['identity'],binding_sha256=binding['sha256'],
                    native_metadata_sha256=binding['native_metadata_sha256'],provenance=market['provenance'],
                    metadata_exclusion=market.get('exclusion') or event.get('exclusion')))
    pairs=[]
    for token,legs in groups.items():
        if len({l['source'] for l in legs})<2:continue
        i=legs[0]['identity'];cid='/'.join((i['competition'],i['period'],i.get('category') or i['family']))
        pairs.append(dict(id=token,cell_id=cid,identity=i,predicate=legs[0]['predicate'],legs=legs))
    return sorted(pairs,key=lambda p:(p['cell_id'] in PAIRED,p['identity']['period']!='first_half',p['cell_id'],p['id']))

def reserve(catalogs, at):
    """Round robin by cell, reserve both legs or neither before source compaction."""
    from .continuous import select_inventory
    from .catalog_metadata import compact
    from copy import deepcopy
    eligible={v:set(select_inventory(deepcopy(c),at,cap=10000)[0]) for v,c in catalogs.items()}
    groups=defaultdict(list)
    for pair in inventory(catalogs):
        if all(l['market_id'] in eligible[l['source']] for l in pair['legs']):groups[pair['cell_id']].append(pair)
    selected={v:set() for v in catalogs};accepted=[]
    # Trial the actual compact representation and unchanged resident bound.
    for index in range(max(map(len,groups.values()),default=0)):
        for cid in sorted(groups,key=lambda c:(c in PAIRED,c)):
            if index>=len(groups[cid]):continue
            pair=groups[cid][index];trial={v:set(ids) for v,ids in selected.items()}
            for leg in pair['legs']:trial[leg['source']].add(leg['market_id'])
            if all(len(ids)<=(40 if v=='kalshi' else 64) for v,ids in trial.items()):
                selected=trial;accepted.append(pair['id'])
    pair_by_id={p['id']:p for ps in groups.values() for p in ps}
    # Compact once per source, then drop the lowest-priority whole pair until
    # every reserved leg survives the actual unchanged resident bound.
    while accepted:
        selected={v:set() for v in catalogs}
        for token in accepted:
            for leg in pair_by_id[token]['legs']:selected[leg['source']].add(leg['market_id'])
        fits=True
        for v,c in catalogs.items():
            probe=deepcopy(c)
            for m in probe['markets']:m['counterpart_priority']=m['id'] in selected[v]
            compact(probe,v)
            if not selected[v]<={m['id'] for m in probe['markets']}:fits=False;break
        if fits:break
        accepted.pop()
    if not accepted:selected={v:set() for v in catalogs}
    for v,c in catalogs.items():
        for m in c['markets']:m['counterpart_priority']=m['id'] in selected[v]
        c['counterpart_reservation']=dict(policy=POLICY,source=v,market_ids=sorted(selected[v]),pair_ids=accepted)
    return accepted
