"""Current overlap requires explicit provider edges; schedule is metadata."""
from copy import deepcopy
from datetime import datetime, timezone
from app.dashboard.session_projection import stable
from app.comparison.event_links import reviewed_links
VERSION='comparison-evidenced-overlap-2'


def associate(native,aggregate,*,links=None,clock=None):
    links=reviewed_links() if links is None else links
    clock=datetime.now(timezone.utc) if clock is None else clock
    candidates={}
    for r in native:
        e=r['event']
        if r['verified'] and r['market_identity']['family']=='moneyline' and r['market_identity']['period']=='full_game' and r['result_policy'].startswith('predict-direct-win-1:'):
            edge,_=links.resolve(r['quote']['source']['provider'],r['quote']['source']['native_event_id'],e['competition'],e['home'],e['away'],clock)
            if edge is not None:candidates.setdefault(edge.occurrence_id,{})[stable(r['market_identity']['event'])]=(r,edge)
    result=[]
    for original in aggregate:
        r=deepcopy(original)
        e=r['event']
        edge,reason=links.resolve('the_odds_api',r['quote']['source']['native_event_id'],e['competition'],e['home'],e['away'],clock)
        matches=candidates.get(edge.occurrence_id,{}) if edge is not None else {}
        if (len(matches)==1 and r['market_identity']['family']=='moneyline'
            and r['market_identity']['period']=='full_game' and r['selection']['predicate']=='win'):
            target,native_edge=next(iter(matches.values()))
            if target['event'].get('game_id')!=edge.occurrence_id:reason='native_occurrence_edge_conflict'
            else:
                schedule=e['scheduled_start']
                proof=stable(dict(version=VERSION,aggregate_edge=edge.id,native_edge=native_edge.id))
                r['event']=deepcopy(target['event']);r['event']['scheduled_start']=schedule
                r['market_identity']=deepcopy(target['market_identity']);r['market_identity']['scheduled_start']=schedule
                for field in ('period_boundary','result_policy','outcome_selections','outcome_cardinality','anchor_participant'):r[field]=deepcopy(target[field])
                r.pop('event_scope',None)
                r['orientation_evidence'].append(VERSION+':'+proof)
                r['quote']['rule_note']+=' Explicit reviewed provider-ID occurrence link; source schedule is versioned metadata. Exceptional settlement remains source-local.'
                # Carry only the immutable edge identities and their actual
                # common interval into current state, so expiry does not wait
                # for another provider packet. Source-local prices survive.
                ends=[x.effective_until for x in (edge,native_edge) if x.effective_until is not None]
                r['quote']['occurrence_link']=dict(version=VERSION,edges=sorted([edge.id,native_edge.id]),
                    effective_from=max(edge.effective_from,native_edge.effective_from),
                    effective_until=min(ends) if ends else None)
                reason=None
        elif edge is not None:reason='native_occurrence_not_uniquely_linked'
        if reason is not None:r['orientation_evidence'].append(VERSION+':'+reason)
        result.append(r)
    return result
