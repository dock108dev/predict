"""Bounded next eligibility boundary over the admitted immutable input graph.

This conservative index can revoke reusable jobs early, never extend authority.
It does not publish partial Current state or replace strict temporal projection.
"""
from datetime import timedelta
from .current_contract import stamp, quotes_of

INTERVALS={'expires_at','effective_from','model_effective_from','effective_to',
           'effective_until','scheduled_ts','observed_at','start_at','received_at',
           'confirmed_at','market_at','book_at','source_at'}
DERIVED={'calculations','comparison','contexts','funded_pairs','funded_pair_search',
         'comparison_pairs','comparison_search','display'}


def next_deadline(state):
    now=stamp(state['clock_at']);deadline=None
    def add(value,seconds=0):
        nonlocal deadline
        if value is None:return
        if isinstance(value,list):
            for item in value:add(item,seconds)
            return
        if not isinstance(value,str):return
        # Opaque provider metadata can use these names too. Financial inputs
        # have already passed their strict timestamp validators at admission.
        try:at=stamp(value)+timedelta(seconds=seconds)
        except (ValueError,TypeError):return
        if at>now and (deadline is None or at<deadline):deadline=at
    # Traverse immutable admitted inputs once, skipping large derived graphs.
    # The stack and visited identities are bounded by admitted graph capacity;
    # only one datetime survives indexing, not an expanded profile registry.
    seen=set();stack=[state]
    while stack:
        node=stack.pop()
        if isinstance(node,(dict,list)):
            if id(node) in seen:continue
            seen.add(id(node))
        if isinstance(node,dict):
            for key,value in node.items():
                if key in DERIVED:continue
                if key in INTERVALS:
                    add(value)
                    if key in {'source_at','market_at','book_at'}:
                        for limit in (900,1800):add(value,limit+.000001)
                if isinstance(value,(dict,list)):stack.append(value)
        elif isinstance(node,list):stack.extend(v for v in node if isinstance(v,(dict,list)))
    for event in state['events']:
        for group in event['groups']:
            for outcome in group['outcomes']:
                for quote in quotes_of(outcome):
                    basis=quote.get('book_confirmation',{}).get('confirmed_at') or quote['times']['source_at']
                    maximum=quote.get('freshness_policy',{}).get('maximum_age_seconds')
                    if maximum is not None:add(basis,maximum+.000001)
                    phase=quote.get('comparison_input_refs',{}).get('phase')
                    if phase=='live':
                        add(quote['times']['source_at'],15.000001)
                        from app.comparison.current_dependencies import references
                        reference=references(quote,state.get('comparison_profiles',{})).get('reference',{})
                        add(reference.get('payload',{}).get('source_at'),15.000001)
    return deadline
