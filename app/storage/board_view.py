"""Render captured publications and bounded pages without acquiring inputs."""
from copy import deepcopy
from .store import encoded, stamp
from app.dashboard.comparison_board import (
    freshness, age_observation, age_gross_comparison, odds_rows, compact_odds,
    compact_price_fields, expand_price_fields, MAX_RESPONSE,
)
from app.comparison.calculation_availability import summary, combine, result_availability


def _withdraw(board, reasons):
    if not reasons:return
    board.update(status='historical',delivery_state='pending' if 'current_dependencies_changed' in reasons else 'stopped' if 'updates_stopped' in reasons else 'unavailable')
    items=[]
    for row in board['rows']:
        row['ranking_eligible']=False
        classification=row.get('classification',{})
        for key in ('main_positive_eligible','positive_rule_sensitive_eligible'):classification[key]=False
        f=row.setdefault('freshness',dict(status='historical',reasons=[]));f.update(status='historical',reasons=sorted(set(f['reasons']+reasons)))
        if board['view']!='odds':
            if row.get('gross_decisive_benchmark',{}).get('available'):
                row['gross_decisive_benchmark']['state']='numeric_last_known'
            if row.get('conditional_trade_benchmark',{}).get('available'):
                row['conditional_trade_benchmark']['state']='numeric_last_known'
            row['availability']=result_availability(row,pair=board['view']=='arbs')
            items.append((board['game_key'],[l['venue'] for l in row.get('legs',[])] if board['view']=='arbs' else [row['venue']],row['availability']))
    if board['view']!='odds' and items:board['availability']=summary(items)


def board(frame, game_key, *, view, filter, read_token=None):
    error=next((e['reason'] for e in frame['status'].get('observation_errors',[]) if e['game_key']==game_key),None)
    if error:raise ValueError(error)
    row=frame['rows'].get(game_key)
    if row is None:
        raise ValueError('background_observation_unavailable')
    serialized=row.pop('_board_text',None)
    if serialized is not None:
        import json
        output=expand_price_fields(json.loads(serialized))
    else:output=expand_price_fields(deepcopy(row['facts']['boards'][view]))
    source_reasons=list(frame.get('observation_reasons',frame['reasons']))
    local=frame.get('dependency_reasons',{}).get(game_key,dict(all=[],observations={},comparisons={}))
    if view!='odds':local=local.get('financial',local)
    source_reasons=sorted(set([*source_reasons,*local['all']]))
    comparison_reasons=sorted(set([*source_reasons,*[reason for values in local['comparisons'].values() for reason in values]]))
    calculation_reasons=list(frame.get('calculation_reasons',[]))
    captured=row['facts'].get('context')
    if captured:
        # A newer sibling publication may advance the shared status before
        # this game's optional calculation catches up. Its own identity must
        # still bind the financial engine and policy shown by that status.
        if captured.get('engine_binding')!=frame['status'].get('engine_binding'):
            calculation_reasons.append('engine_binding_changed')
        if captured.get('policy_revision')!=frame['status']['policy']['revision']:
            calculation_reasons.append('policy_changed')
    if row['facts'].get('retained_financial_only'):
        calculation_reasons.append('captured_inputs_changed_before_publication')
    if any(local['observations'].values()) or any(local['comparisons'].values()):
        calculation_reasons.append('current_dependencies_changed')
    deadline=row['facts'].get('valid_until')
    if deadline and stamp(frame['at'])>=stamp(deadline):calculation_reasons.append('calculation_authority_boundary')
    states=frame.get('source_states',frame['owner'].get('states',{}))
    for q in output['prices']:
        event=q.get('event') or next(g for g in frame['status']['games'] if g['game_key']==game_key)
        from .current_rows import contract_id
        own_reasons=sorted(set([*source_reasons,*local['observations'].get(contract_id(dict(quote=q)),[])]))
        if view=='odds':age_observation(q,event,frame['at'],source_states=states,publication_reasons=own_reasons)
        else:
            state=states.get(q['venue'],{}).get('state',q['source_state'])
            f=freshness(dict(q,state=state),{},event,stamp(frame['at']),financial=False)
            f['reasons']=sorted(set(f['reasons']+own_reasons));f['status']='historical' if f['reasons'] else 'current'
            q['freshness']=f;q['source_state']=state
            health=states.get(q['venue'],{})
            q['source_health']=dict(q.get('source_health',{}),**{k:health[k] for k in ('state','reason_code','reason') if k in health})
    if view=='odds':
        for q in output['prices']:
            cid=contract_id(dict(quote=q))
            peer_reasons=sorted(set([*source_reasons,*local['observations'].get(cid,[]),*local['comparisons'].get(cid,[])]))
            for field in ('gross_comparison','current_comparison'):
                if field in q:
                    age_gross_comparison(q[field],frame['at'],source_states=states,
                        publication_reasons=peer_reasons,captured_rows=output['prices'])
    reasons=source_reasons+calculation_reasons
    if view=='odds':
        output['rows']=odds_rows(output['prices'])
        statuses={q['freshness']['status'] for q in output['prices']}
        output['status']='mixed' if len(statuses)>1 else next(iter(statuses),'historical')
        output['delivery_state']='pending' if any(q.get('observation_display',{}).get('state')=='pending' for q in output['prices']) or 'current_dependencies_changed' in comparison_reasons else 'stopped' if 'updates_stopped' in source_reasons else 'unavailable' if 'data_runtime_unhealthy' in source_reasons else 'complete'
    else:
        _withdraw(output,reasons)
        from app.comparison.bound_finance import age_benchmarks
        prices={p['quote_id']:p for p in output['prices']}
        for result in output['rows']:
            q=prices.get(result.get('price_ref') or result.get('quote_id'))
            if q is not None:
                event=q.get('event') or next(g for g in frame['status']['games'] if g['game_key']==game_key)
                from .native_authority import assessment
                source_proof=assessment(q,frame.get('native_authority',{}),stamp(frame['at']))
                cid=contract_id(dict(quote=q))
                metric_reasons=benchmark_reasons(local,cid,reasons,source_proof,q['venue'])
                age_benchmarks(result,q,event,stamp(frame['at']),reasons=metric_reasons,source_assessment=source_proof)
        from app.comparison.calculation_availability import result_availability
        for result in output['rows']:result['availability']=result_availability(result,pair=view=='arbs')
        output['availability']=summary([(game_key,[r['venue']] if view=='ev' else [l['venue'] for l in r.get('legs',[])],r['availability']) for r in output['rows']])
    estimate=deepcopy(row['facts'].get('estimate_availability',dict(state='evaluated',reason_codes=[])))
    if reasons:estimate.update(state='last_known' if estimate['state'] in ('evaluated','partial') else 'unavailable',reason_codes=sorted(set(estimate['reason_codes']+reasons)))
    output.update(filter=filter,read_at=frame['at'],sizing_scope='shared_default_selected_details',
        economic_revision=row['economic_revision'],calculated_at=row['calculated_at'],background_reasons=source_reasons if view=='odds' else reasons,
        observation_reasons=sorted(set([*source_reasons,*[reason for values in local['observations'].values() for reason in values]])),
        comparison_reasons=comparison_reasons,calculation_reasons=calculation_reasons,estimate_availability=estimate,
        collection=dict(healthy=frame['owner'].get('healthy',False),active=frame['owner'].get('active',False),
                        stopped=bool(frame['owner'].get('global_stopped',False)),
                        sources=frame.get('source_states',frame['owner'].get('states',{}))))
    if view!='odds' and filter!='all':
        key='positive_rule_sensitive_eligible' if filter=='hedges' else 'main_positive_eligible'
        output['rows']=[r for r in output['rows'] if r.get('classification',{}).get(key)]
    if not output['rows'] and reasons:output['empty_reason']='Latest results await background reconciliation' if 'current_dependencies_changed' in reasons else 'Only last-known estimates available; see All comparisons'
    if read_token:
        for price in output['prices']:
            if price.get('inputs_identity'):price['inputs_identity']['read_token']=read_token
        for result in output['rows']:
            if result.get('details'):result['details']['read_token']=read_token
    if view=='odds':compact_odds(output)
    else:compact_price_fields(output)
    if len(encoded(output))>MAX_RESPONSE:raise ValueError('board_compact_response_capacity')
    return output


def bounded_page(header, boards, errors, *, offset, limit, evaluated, storage=None, rendered_count=None):
    """Largest contiguous game prefix fitting the unchanged complete wire bound."""
    games=header['games'];maximum=min(limit,len(games)-offset)
    if rendered_count is not None:maximum=min(maximum,rendered_count)
    def build(count):
        keys={g['game_key'] for g in games[offset:offset+count]}
        selected=[b for b in boards if b['game_key'] in keys]
        failures=[e for e in errors if e['game_key'] in keys]
        end=offset+count;complete=end>=len(games)
        value=dict(header,boards=selected,errors=failures,
            coverage=dict(total_games=len(games),offset=offset,limit=limit,returned_games=count,
                next_offset=None if complete else end,complete=complete))
        if storage is not None:value['storage']=storage
        value['availability']=combine([b['availability'] for b in selected],games=count,
            failures=[(e['game_key'],'calculation_read_failed') for e in failures],evaluated=evaluated)
        return value,len(encoded(value))
    value,size=build(maximum)
    if size<=8*1024*1024:return value,size
    low=1;high=maximum-1;best=None
    while low<=high:
        middle=(low+high)//2;candidate,length=build(middle)
        if length<=8*1024*1024:
            best=(candidate,length);low=middle+1
        else:high=middle-1
    if best is None:raise ValueError('slate_response_byte_capacity')
    return best




def benchmark_reasons(local,cid,reasons,source_proof,venue):
    result=[r for r in reasons if r not in ('calculation_authority_boundary','current_dependencies_changed','captured_inputs_changed_before_publication','background_calculations_unavailable')]
    if venue in ('kalshi','polymarket_us') and source_proof is None:result.append('native_stream_authority_unavailable')
    identities=local.get('benchmark_identity',{})
    selected=(identities[cid] if source_proof is not None and cid in identities else local['observations'].get(cid,[]))
    return sorted(set(result+local['all']+selected+local.get('benchmarks',{}).get(cid,[])))
