"""Bounded Polymarket subscription groups on one connection, without roster caps."""
from uuid import uuid4
from math import ceil
from app.adapters.polymarket_us import next_market_data


def plan(groups, previous, current, changed):
    affected=set(changed) | (set(previous)-set(current))
    retired={rid for rid,members in groups.items() if set(members)&affected}
    retained={rid:members for rid,members in groups.items() if rid not in retired}
    retained_ids={mid for members in retained.values() for mid in members}
    pending=sorted(set(current)-retained_ids)
    # A live trial rejected an 80-group subscription after ten groups. Eight
    # groups have admitted the complete roster; grow groups, never truncate it.
    # The existing full-cohort connection has verified >100 markets per request;
    # the public documentation's 100-market figure differs from that live route.
    if pending and len(retained)>=8:
        rid=min(retained,key=lambda rid:len(retained[rid]))
        pending=sorted(set(pending)|set(retained.pop(rid)));retired.add(rid)
    width=max(100,ceil(len(pending)/max(1,8-len(retained))))
    added={}
    for start in range(0,len(pending),width):
        added[str(uuid4())]=pending[start:start+width]
    invalidated={mid for rid in retired for mid in groups[rid]} | set(pending)
    return dict(groups={**retained,**added},added=added,retired=retired,invalidated=invalidated)


def requests(groups, markets):
    return {next_market_data(markets[mid])['slug']:rid for rid,members in groups.items() for mid in members}


def commands(groups, markets):
    from app.adapters.polymarket_us_stream import subscription
    return [subscription([next_market_data(markets[mid])['slug'] for mid in members],rid,maximum_markets=None)
            for rid,members in groups.items()]
