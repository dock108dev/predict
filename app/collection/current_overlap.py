"""Exact schedule/participant association into a reviewed native normal domain.

This is gross comparison evidence. Provider event IDs, original clocks, prices
and exceptional-settlement limitations remain source-local and unchanged.
"""
from copy import deepcopy
from app.dashboard.current_contract import stamp
from app.dashboard.session_projection import stable
VERSION='predict-exact-scheduled-overlap-1'


def associate(native,aggregate):
    def key(record):
        e=record['event']
        return (e['competition'],stamp(e['scheduled_start']),e['home'],e['away'])
    candidates={}
    for r in native:
        if r['verified'] and r['market_identity']['family']=='moneyline' and r['market_identity']['period']=='full_game' and r['result_policy'].startswith('predict-direct-win-1:'):
            candidates.setdefault(key(r),{})[stable(r['market_identity']['event'])]=r
    provider_events={}
    for r in aggregate:provider_events.setdefault(key(r),set()).add(r['event']['id'])
    result=[]
    for original in aggregate:
        r=deepcopy(original);matches=candidates.get(key(r),{})
        e=r['event']
        # Provider-slot fallback identities cannot establish a cross-source match.
        supported=not any(str(e[role]).startswith('the_odds_api:') for role in ('home','away'))
        if (supported and len(matches)==1 and len(provider_events[key(r)])==1 and r['market_identity']['family']=='moneyline'
            and r['market_identity']['period']=='full_game' and r['selection']['predicate']=='win'):
            target=next(iter(matches.values()))
            proof=stable(dict(version=VERSION,aggregate_event=deepcopy(e),native_event=deepcopy(target['event']),
                              aggregate_source=deepcopy(r['quote']['source']),native_evidence=target['orientation_evidence']))
            r['event']=deepcopy(target['event'])
            r['market_identity']=deepcopy(target['market_identity'])
            for field in ('period_boundary','result_policy','outcome_selections','outcome_cardinality','anchor_participant'):r[field]=deepcopy(target[field])
            r.pop('event_scope',None)
            r['orientation_evidence'].append(VERSION+':'+proof)
            r['quote']['rule_note']+=' Exact league, resolved home/away identities and UTC start associate with the unique reviewed native normal-win event. Aggregate original schedule/exceptional settlement remains unverified.'
        result.append(r)
    return result
