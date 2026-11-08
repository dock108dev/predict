"""Explicit bounded current subscriptions; complete catalog discovery is unchanged."""
from collections import defaultdict,deque,Counter
from datetime import datetime

# The 512-market live population consumed nearly the entire 15-second price
# window before capture (derived p95 12–14 seconds). Keep discovery complete,
# but bound each active cohort; the other instruments remain explicitly deferred.
MAX_ACTIVE=256
ROTATE_SECONDS=20


def select(markets,catalog,now,offset,*,limit=MAX_ACTIVE):
    events={e['id']:e for e in catalog.get('events',[])}
    metadata={m['id']:m for m in catalog.get('markets',[])}
    cells=defaultdict(lambda:defaultdict(list))
    def distance(eid):
        try:
            value=events[eid].get('scheduled_start')
            if not isinstance(value,str):raise ValueError()
            start=datetime.fromisoformat(value.replace('Z','+00:00'))
            if start.tzinfo is None:raise ValueError()
            return abs((start-now).total_seconds()),eid
        except (KeyError,TypeError,ValueError):return float('inf'),eid
    for market in markets:
        mid=market.raw.ref.market_id;eid=market.raw.ref.event_id
        event=events.get(eid,{})
        cells[(event.get('competition','unknown'),metadata.get(mid,{}).get('market_type','unknown'))][eid].append(market)
    queues={}
    for cell,groups in sorted(cells.items()):
        groups={eid:deque(sorted(rows,key=lambda m:m.raw.ref.market_id)) for eid,rows in groups.items()}
        ordered=[]
        while groups:
            for eid in sorted(groups,key=distance):
                ordered.append(groups[eid].popleft())
                if not groups[eid]:del groups[eid]
        queues[cell]=deque(ordered)
    fair=[]
    while queues:
        for cell in list(queues):
            fair.append(queues[cell].popleft())
            if not queues[cell]:del queues[cell]
    if len(fair)<=limit:chosen=fair
    else:
        primary=fair[:limit//2];remaining=fair[len(primary):]
        width=limit-len(primary);start=(offset*width)%len(remaining)
        chosen=primary+[remaining[(start+i)%len(remaining)] for i in range(width)]
    return chosen,describe(markets,catalog,chosen,offset)


def describe(markets,catalog,chosen,offset):
    events={e['id']:e for e in catalog.get('events',[])}
    metadata={m['id']:m for m in catalog.get('markets',[])}
    selected={m.raw.ref.market_id for m in chosen};counts=Counter();cells=set()
    for m in markets:
        mid=m.raw.ref.market_id
        cell=(events.get(m.raw.ref.event_id,{}).get('competition','unknown'),metadata.get(mid,{}).get('market_type','unknown'))
        cells.add(cell);counts[cell,mid in selected]+=1
    detail=[dict(league=cell[0],family=cell[1],active=counts[cell,True],deferred=counts[cell,False]) for cell in sorted(cells)]
    return dict(policy='fair-current-subscriptions-1',eligible_markets=len(markets),active_markets=len(chosen),
        deferred_markets=len(markets)-len(chosen),rotation_seconds=ROTATE_SECONDS,rotation=offset,cells=detail,
        meaning='Half the slots prioritize nearby games fairly across leagues/families; remaining slots rotate the rest. Deferred markets have observation gaps, not current coverage.')
