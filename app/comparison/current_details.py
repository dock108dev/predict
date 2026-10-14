"""Compact published calculation shells and selected-only evidence expansion.

The existing evaluator remains authoritative. Graphs are rebuilt from the exact
selected profile/quote inputs and server policy, without reading any provider.
"""
from copy import deepcopy

VERSION = 'comparison-selected-details-1'
# Small values needed for board labels, size disclosure and benchmark selection.
SUMMARY_FIELDS = frozenset(('native_quantity','unused_ceiling_usd','unused_cash_usd',
    'expected_profit_usd','acquisition_usd','entry_fee_usd','net_entry_fee_usd',
    'rounding_refund_usd','fill_basis','fill_partition_basis','maximum_quantity_proven',
    'state_labels','target_ceiling_usd','deployed_capital_usd','size_evaluations'))


def compact_metric(metric):
    if not isinstance(metric,dict):return metric
    value=dict(metric)
    if isinstance(value.get('basis'),dict):
        value['basis']=dict(value['basis'])
        deps=value['basis'].get('dependency_revisions')
        if isinstance(deps,dict) and isinstance(deps.get('calculation'),dict):
            from .current_dependencies import digest
            value['basis']['dependency_revisions']=dict(deps,calculation=digest(deps['calculation']))
    details=metric.get('details')
    if isinstance(details,dict):
        summary={k:v for k,v in details.items() if k in SUMMARY_FIELDS or v is None or type(v) in (str,int,bool)}
        if isinstance(details.get('reference'),dict):
            summary['reference']={k:details['reference'][k] for k in ('selected_odds','opposing_odds') if k in details['reference']}
        if details.get('gross_decisive_benchmark') is not None:
            summary['gross_decisive_benchmark']=compact_metric(details['gross_decisive_benchmark'])
        summary['evidence_graph']='selected_details_required'
        value['details']=summary
    return value


def compact_group(group):
    from app.dashboard.current_contract import quotes_of
    for outcome in group['outcomes']:
        for q in quotes_of(outcome):
            q['comparison_details']=dict(version=VERSION,quote_id=q['id'],group_id=group['id'])
            from .estimated_ev import compact as compact_funded
            q['calculations']={k:compact_funded(v) if k=='funded_estimate' else compact_metric(v) for k,v in q['calculations'].items()}
            contexts=q.get('comparison',{}).get('contexts')
            if contexts:
                from .current_dependencies import encoded
                unique={};values=[];refs={}
                for key,value in contexts.items():
                    content=encoded(value)
                    if content not in unique:unique[content]=len(values);values.append(value)
                    refs[key]=unique[content]
                q['comparison']=dict(q['comparison'],contexts=refs,context_values=values)
    for pair in group.get('comparison_pairs',[]):
        pair['details']={k:v for k,v in pair['details'].items() if k in SUMMARY_FIELDS}
        pair['details']['evidence_graph']='selected_details_required'
        pair['details_ref']=dict(version=VERSION,group_id=group['id'],pair_id=pair['id'])


def selected(state, quote_id, *, ceiling=None, buffer=None, pair_id=None, objective=None, pair_revision=None):
    from app.dashboard.current_contract import quotes_of, snapshot_inputs, serialize
    from .shared_templates import subset
    from .effective_policy import effective_policy
    for event in state['events']:
        for group in event['groups']:
            matches=[(o,q) for o in group['outcomes'] for q in quotes_of(o) if q['id']==quote_id]
            if not matches:continue
            paired='funded_pairs' in event
            profiles=subset(state.get('comparison_profiles',{}),dict(outcomes=[o for g in event['groups'] for o in g['outcomes']]))
            selected_profiles=subset(profiles,group)
            raw=snapshot_inputs(dict(state,comparison_profiles=selected_profiles,events=[dict(event,groups=[group])]))
            policy=effective_policy(state['estimate_policy'],ceiling=ceiling,buffer=buffer)
            funded=any('funded_estimate' in q.get('calculations',{}) for o in group['outcomes'] for q in quotes_of(o))
            result=serialize(raw,allow_synthetic=state['mode']=='synthetic',estimate_policy=policy,details=True,funded=funded,paired=False,supported=any('supported_size_evaluation' in q.get('calculations',{}).get('funded_estimate',{}) for o in group['outcomes'] for q in quotes_of(o)))
            e=result['events'][0];g=next(g for g in e['groups'] if g['id']==group['id'])
            o,q=next((o,q) for o in g['outcomes'] for q in quotes_of(o) if q['id']==quote_id)
            from .current_dependencies import references
            from .estimated_content import describe
            from .current_dependencies import instant
            estimate_content=describe(q,profiles,at=instant(state['clock_at']))
            from .funded_explanation import explanation
            single=q['calculations'].get('funded_estimate')
            if single and single.get('model_available'):
                single['explanation']=explanation(single)
                from fractions import Fraction
                from .net_costs import wire
                for row in single.get('states',{}).values():row['buffered_profit_usd']=None if row['profit_usd'] is None else wire(Fraction(row['profit_usd'])-Fraction(single['buffer_usd']))
                supported=single.get('supported_size_result')
                if supported and supported.get('model_available'):supported['explanation']=explanation(supported)
            pair_details=[]
            if paired:
                from .estimated_pair import Leg,evaluate,assemble
                by_quote={q['id']:(g,q) for g in event['groups'] for o in g['outcomes'] for q in quotes_of(o)}
                if pair_id is not None and policy.to_dict()==state['estimate_policy']:
                    # Complete admission already discovered every native pair.
                    # Expand only the pinned pair through the same evaluator.
                    pairs=[p for p in event['funded_pairs'] if p['id']==pair_id]
                else:
                    pairs,_=assemble(event,profiles,instant(state['clock_at']),policy=policy,
                        selected_quote_id=quote_id,selected_pair_id=pair_id)
                for pair in pairs:
                    if not any(leg['quote_id']==quote_id for leg in pair['legs']) or (pair_id and pair['id']!=pair_id):continue
                    legs=[Leg(by_quote[leg['quote_id']][1],by_quote[leg['quote_id']][0],profiles,e,instant(state['clock_at']),policy=policy) for leg in pair['legs']]
                    full=evaluate(legs,policy=policy,details=True,objective=objective or pair['objective'])
                    if (objective is None or objective==pair['objective']) and full['revision']!=pair['revision']:raise ValueError('Selected pair inputs changed')
                    if pair_revision and pair_revision!=full['revision']:raise ValueError('Selected pair result changed')
                    full['explanation']=explanation(full,pair=True)
                    if pair_id and getattr(policy,'sizing_mode',None) != 'requested_trade':
                        alternate=evaluate(legs,policy=policy,details=True,objective='all_modeled_states_max_min' if full['objective']=='decisive_max_min' else 'decisive_max_min')
                        alternate['explanation']=explanation(alternate,pair=True)
                        full['objective_alternative']=alternate
                    pair_details.append(dict(full,runtime_id=state['runtime_id'],state_revision=state['state_revision']))
            if pair_id and not pair_details:raise ValueError('Exact selected pair unavailable')
            q=deepcopy(q)
            # Original alternatives retain shells; only the selected quote expands.
            for candidate in e['groups']:compact_group(candidate)
            return dict(estimate_content=estimate_content,leg_estimate_content={key:describe(by_quote[key][1],profiles,at=instant(state['clock_at'])) for key in {leg['quote_id'] for pair in pair_details for leg in pair['legs']}} if pair_id else {},funded_pairs=pair_details,leg_quotes={key:{k:deepcopy(v) for k,v in by_quote[key][1].items() if k in ('id','revision','venue','source','original','times','binding','native_contract','occurrence_match','sharp_reference','rule_note','provenance')} for key in {leg['quote_id'] for pair in pair_details for leg in pair['legs']}} if paired else {},event={k:v for k,v in e.items() if k not in ('groups','funded_pairs','funded_pair_search')},
                group={k:v for k,v in g.items() if k!='outcomes'},
                outcome={k:v for k,v in o.items() if k not in ('quotes','alternatives')},
                quote=q,comparisonQuotes=o['quotes'],alternatives=o.get('alternatives',{}),
                comparison_inputs=deepcopy(references(q,profiles)),estimate_policy=policy.to_dict(),
                runtime_id=state['runtime_id'],state_revision=state['state_revision'],clock_at=state['clock_at'],mode=state['mode'])
    raise ValueError('Selected contract unavailable')
