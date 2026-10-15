"""Versioned compact Odds/EV/Arbs and dependency-local saved aging."""
from copy import deepcopy
from fractions import Fraction as F
from app.storage.store import hashed, encoded, stamp
from app.storage.current_games import utc
from app.dashboard.current_contract import quotes_of
from app.comparison.current_dependencies import references, link_reasons
from app.comparison.estimated_ev import temporal
from app.comparison.estimated_content import describe
from app.comparison.benchmark import TwoWayBenchmark

VERSION='predict-comparison-board-2'
MAX_RESPONSE=512*1024


def entries(state):
    return [(e,g,q) for e in state['events'] for g in e['groups'] if g['market']=='winner' and g['period']=='full_game'
            for o in g['outcomes'] for q in quotes_of(o)]


def quote_key(q):
    from .current_contract import quote_identity
    return quote_identity(q,q['binding']['selection']['outcome_id'])


def dependency(q,profiles):
    fields=('original','source','times','provenance','binding','native_contract','occurrence_match','comparison_input_refs','comparison_input_status')
    return hashed(dict(quote={k:q.get(k) for k in fields},profiles=references(q,profiles)))


def freshness(q, profiles, event, at, *, financial=True):
    reasons=list(link_reasons(q,at))
    if q['state'] not in ('available','budget_delayed'):reasons.append('source_unavailable')
    checks=temporal(q,profiles,at,event)
    if checks[0]!='current':reasons.append('source_'+checks[0])
    if financial:
        if any(isinstance(v,str) and v!='current' for v in checks[1:]):reasons.append('reference_stale_or_unknown')
        if any(v is True for v in checks):reasons.append('profile_or_pregame_boundary')
        try:
            values=references(q,profiles)
            for kind,p in values.items():
                if p is not None and p.get('expires_at') is not None and at>=stamp(p['expires_at']):reasons.append(kind+'_profile_expired')
            for c in describe(q,profiles,at=at).values():
                if not c['available']:reasons.extend(c['reasons'])
        except (ValueError,KeyError,TypeError) as exc:reasons.append(str(exc))
    else:
        if at>=stamp(event['start_at']):reasons.append('pregame_ended')
    return dict(status='historical' if reasons else 'current',reasons=sorted(set(reasons)),
        source_at=q['times']['source_at'],received_at=q['times']['received_at'])


def age(value, *, at=None, current=None, stopped=False, history=False):
    """Age each result's own dependencies; never inherit an event-wide stale bit."""
    v=deepcopy(value);instant=stamp(at or utc());p=v['state']['comparison_profiles']
    newest={quote_key(q):dependency(q,current['comparison_profiles']) for _,_,q in entries(current)} if current else None
    changed={};statuses=[]
    for e,g,q in entries(v['state']):
        r=q['calculations']['funded_estimate'];f=freshness(q,p,e,instant)
        changed[q['id']]=newest is not None and newest.get(q['id'])!=dependency(q,p)
        if changed[q['id']]:f['reasons'].append('dependency_changed_or_removed')
        if stopped:f['reasons'].append('updates_stopped')
        if history:f['reasons'].append('explicit_history')
        if v.get('engine_binding_changed'):f['reasons'].append('engine_binding_changed')
        f['reasons']=sorted(set(f['reasons']));f['status']='historical' if f['reasons'] else 'current'
        q['saved_status']=f['status'];r['freshness']=f
        if f['reasons']:
            r['ranking_eligible']=False
            for key in ('main_positive_eligible','positive_rule_sensitive_eligible'):
                if 'classification' in r:r['classification'][key]=False
        statuses.append(f['status'])
    byid={q['id']:q for _,_,q in entries(v['state'])}
    for e in v['state']['events']:
        for pair in e.get('funded_pairs',[]):
            reasons=[]
            for leg in pair['legs']:
                q=byid.get(leg['quote_id'])
                if q is None:reasons.append('leg_absent')
                else:reasons.extend(q['calculations']['funded_estimate']['freshness']['reasons'])
            pair['freshness']=dict(status='historical' if reasons else 'current',reasons=sorted(set(reasons)))
            if reasons:
                pair['ranking_eligible']=False
                for key in ('main_positive_eligible','positive_rule_sensitive_eligible'):
                    if 'classification' in pair:pair['classification'][key]=False
            statuses.append(pair['freshness']['status'])
    v.update(status='mixed' if len(set(statuses))>1 else statuses[0] if statuses else 'historical',read_at=instant.isoformat(),stopped=stopped)
    return v


def common_odds(q):
    from .u0_display import quote_display
    result=quote_display(q['original']['value'],q['original']['units'],q['original']['payout'])
    result.pop('what_if',None)
    result['meaning']='common price format; original native predicate and exceptional payouts retained'
    return result


def price(q):
    return dict(quote_id=quote_key(q),quote_revision=q['revision'],selection=deepcopy(q['binding']['selection']),venue=q['venue'],
        native_side=q['source']['native_side'],source=deepcopy(q['source']),original=deepcopy(q['original']),
        common_odds=common_odds(q),times=deepcopy(q['times']),native_contract_id=q.get('native_contract',{}).get('id'))


def benchmark(bundle, at=None):
    b=bundle['benchmark'];fair=[];status='unavailable'
    if b is not None:
        reference=TwoWayBenchmark.from_dict(b)
        if reference.venue!=bundle['benchmark_venue']:
            raise ValueError('selected_benchmark_missing; no substitution')
        status='current' if reference.clock_status(stamp(at or utc()))=='current' else 'historical'
        for participant,probability in reference.fair_probabilities().items():
            fair.append(dict(participant=participant,decisive_probability=str(probability),fair_decimal_odds=str(1/probability)))
    return dict(freshness=status,venue=bundle['benchmark_venue'],method='proportional_no_vig',available=b is not None,
        revision=None if b is None else b['revision'],originals=[] if b is None else deepcopy(b['outcomes']),fair=fair,reason=bundle['benchmark_reason'],
        conditioning='decisive_home_or_away_win',actual_probability=None)


def details_id(value, *, quote=None,pair=None):
    return dict(context_id=value['calculation_context']['context_id'],quote_id=quote,pair_id=pair,
        policy_revision=value['policy']['revision'])


def financial_row(r):
    fields=('revision','dependency_revision','model_available','ranking_eligible','reasons','eligibility_reasons',
        'financial_metrics','funding','classification','model_versions','sizing_mode','requested_amount_usd','residual_funding_usd','buffer_usd','size_status','freshness')
    result={k:deepcopy(r[k]) for k in fields if k in r}
    b=r.get('benchmark',{})
    result['benchmark_identity']={k:deepcopy(b.get(k)) for k in ('venue','method','revision','available','reason','conditioning')}
    # Percentages for conditional EV have the same explicit deployed denominator.
    metrics=result.get('financial_metrics')
    capital=r.get('deployed_capital_usd')
    if metrics is not None:
        for source,target in (('conditional_net_ev_usd','conditional_net_return_percent'),('conditional_buffered_ev_usd','conditional_buffered_return_percent'),('buffered_complete_modeled_minimum_usd','buffered_complete_minimum_return_percent')):
            x=metrics.get(source);metrics[target]=None if x is None or not capital or F(capital)==0 else str(100*F(x)/F(capital))
    return result


def response(bundle, value, policy, *, view='odds', filter='positive', at=None, stopped=False, history=False):
    if view not in ('odds','ev','arbs') or filter not in ('positive','all','hedges'):raise ValueError('board_view_or_filter_invalid')
    instant=stamp(at or utc());state=bundle['state_inputs'];e=state['events'][0]
    saved=None if value is None else age(value,at=instant.isoformat(),current=state,stopped=stopped,history=history)
    out=dict(version=VERSION,view=view,filter=filter,game_key=bundle['game_key'],input_version=bundle['input_version'],
        policy=policy.to_dict(),benchmark=benchmark(bundle,instant.isoformat()),as_of=bundle['as_of'],read_at=instant.isoformat(),
        calculation_context=bundle.get('calculation_context') if saved is None else saved['calculation_context'],
        result_as_of=None if saved is None else saved['as_of'],
        delivery_state='stopped' if stopped else 'complete' if view=='odds' else 'pending' if saved is None or saved.get('superseded') else 'complete',
        status='historical' if stopped else 'prices_only' if saved is None else saved['status'],
        prices=[],rows=[],empty_reason=None,provider_requests=0,limits=dict(maximum_response_bytes=MAX_RESPONSE))
    for event,group,q in entries(state):
        row=price(q);row['freshness']=freshness(q,state['comparison_profiles'],event,instant,financial=False)
        row['inputs_identity']=dict(game_key=bundle['game_key'],input_version=bundle['input_version'],quote_id=row['quote_id'],context_id=out['calculation_context']['context_id'])
        out['prices'].append(row)
    if view=='odds':out['rows']=deepcopy(out['prices'])
    elif saved:
        originals={q['id']:q for _,_,q in entries(saved['state'])}
        if view=='ev':
            for _,_,q in entries(saved['state']):
                r=q['calculations']['funded_estimate'];row=dict(price(q),**financial_row(r),details=details_id(saved,quote=q['id']))
                if filter=='all' or row.get('classification',{}).get('main_positive_eligible'):out['rows'].append(row)
        else:
            for event in saved['state']['events']:
                for r in event.get('funded_pairs',[]):
                    if len({originals[l['quote_id']]['venue'] for l in r['legs']})!=2:continue
                    row=dict(financial_row(r),pair_id=r['id'],details=details_id(saved,pair=r['id']),legs=[])
                    funding={leg['quote_id']:leg for leg in r.get('funding',{}).get('legs',[])}
                    for index,l in enumerate(r['legs']):
                        exact=funding.get(l['quote_id'],l)
                        row['legs'].append(dict(price(originals[l['quote_id']]),native_quantity=exact['native_quantity'],native_unit=exact['native_unit'],
                            acquisition_usd=exact['acquisition_usd'],upfront_fee_usd=exact['net_upfront_fee_usd']))
                    c=row.get('classification',{})
                    if filter=='all' or filter=='positive' and c.get('main_positive_eligible') or filter=='hedges' and c.get('positive_rule_sensitive_eligible'):out['rows'].append(row)
    if not out['rows']:out['empty_reason']='Calculation pending' if saved is None else 'No positive EV found' if view=='ev' and filter=='positive' else 'No estimated arbitrage found' if view=='arbs' and filter=='positive' else 'No eligible comparisons found'
    if len(encoded(out))>MAX_RESPONSE:raise ValueError('board_compact_response_capacity')
    return out


def details(value, *, quote=None,pair=None,at=None,current=None,stopped=False,history=False):
    v=age(value,at=at,current=current,stopped=stopped,history=history)
    rows={q['id']:q for _,_,q in entries(v['state'])}
    if bool(quote)==bool(pair):raise ValueError('one_exact_saved_selection_required')
    q=rows.get(quote);p=next((p for e in v['state']['events'] for p in e.get('funded_pairs',[]) if p['id']==pair),None)
    if not q and not p:raise ValueError('exact_saved_selection_absent')
    return dict(version='predict-board-details-2',game_key=v['game_key'],calculation_context=v['calculation_context'],
        as_of=v['as_of'],read_at=v['read_at'],status=v['status'],policy=v['policy'],quote=q,pair=p,
        original_inputs_identity=dict(game_key=v['game_key'].split(':benchmark:',1)[0],input_version=v['input_version'],context_id=v['calculation_context']['context_id'],policy_revision=v['policy']['revision']),
        leg_quotes=[rows[l['quote_id']] for l in p['legs']] if p else [],profiles=v['state']['comparison_profiles'],
        representation=v['representation'])
