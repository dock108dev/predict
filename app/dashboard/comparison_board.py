"""Versioned compact Odds/EV/Arbs and dependency-local saved aging."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F
from app.storage.store import hashed, encoded, stamp
from app.storage.current_games import utc
from app.dashboard.current_contract import quotes_of
from app.comparison.current_dependencies import references, link_reasons
from app.comparison.estimated_ev import temporal
from app.comparison.estimated_content import describe
from app.comparison.benchmark import TwoWayBenchmark
from app.comparison.calculation_availability import result_availability, summary, refusal

VERSION='predict-comparison-board-2'
MAX_RESPONSE=512*1024


def entries(state):
    from app.comparison.sporting_scope import supported
    return [(e,g,q) for e in state['events'] for g in e['groups']
            if supported(e['league'],'moneyline' if g['market']=='winner' else g['market'],g['period'])
            for o in g['outcomes'] for q in quotes_of(o)]


def quote_key(q):
    from .current_contract import quote_identity
    return quote_identity(q,q['binding']['selection']['outcome_id'])


def dependency(q,profiles):
    fields=('original','source','times','provenance','binding','native_contract','occurrence_match','comparison_input_refs','comparison_input_status')
    return hashed(dict(quote={k:q.get(k) for k in fields},profiles=references(q,profiles)))


def freshness(q, profiles, event, at, *, financial=True):
    # Observation age is owned by original source/receipt clocks. Optional
    # profiles and reference/link applicability only govern derived metrics.
    if not financial:
        from app.comparison.source_clock import assess
        clocks=assess(q,at)
        reasons=list(clocks['reasons']);times=q['times'];source=times.get('source_at');receipt=times.get('received_at')
        if q['state'] not in ('available','budget_delayed'):reasons.append('source_unavailable')
        if at>=stamp(event['start_at']):reasons.append('pregame_ended')
        return dict(status='historical' if reasons else 'current',reasons=sorted(set(reasons)),source_at=source,received_at=receipt,
            currentness_basis=clocks['basis'],currentness_at=clocks['clock_at'],current_until=clocks['current_until'])
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
        r['availability']=result_availability(r)
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
            pair['availability']=result_availability(pair,pair=True)
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
    depth=q.get('depth');total=None if depth is None else len(depth);book=q.get('observed_book')
    observed_depth=dict(available=bool(depth),levels=deepcopy((depth or [])[:8]),total_levels=total,
        truncated=total is not None and total>8,quantity_units=q['original']['quantity_units'],price_units=q['original']['units'],
        source_at=book['source_at'] if book else q['times'].get('source_at'),
        received_at=book['received_at'] if book else q['times'].get('received_at'),
        clock_basis='current_native_book' if book else 'original_quote_frame',book_revision=None if book is None else book['revision'],
        reason=None if depth else 'depth_not_retained' if depth is None else 'observed_book_has_no_retained_asks',
        meaning='Original asks; no fill or size assurance')
    result=dict(quote_id=quote_key(q),quote_revision=q['revision'],selection=deepcopy(q['binding']['selection']),venue=q['venue'],
        source_state=q['state'],native_side=q['source']['native_side'],source=deepcopy(q['source']),original=deepcopy(q['original']),
        common_odds=common_odds(q),times=deepcopy(q['times']),native_contract_id=q.get('native_contract',{}).get('id'),
        observed_depth=observed_depth,source_health=dict(state=q['state'],reason_code=None,reason=None))
    for field in ('freshness_policy','occurrence_link','occurrence_match','book_confirmation','provider_clocks','observation_time_evidence','observed_book'):
        if field in q:result[field]=deepcopy(q[field])
    result['common_odds']['meaning']='Normal-payout price before costs'
    result['common_odds']={key:value for key,value in result['common_odds'].items()
        if key in ('supported','american','cents','equivalent','reason','meaning')}
    if 'occurrence_match' in result:
        # Full native/event copies remain available in exact local Original
        # inputs. Repeating them for every line would consume the board budget.
        result['occurrence_match']={key:deepcopy(value) for key,value in q['occurrence_match'].items()
            if key in ('version','occurrence_id','method','estimated','status','conflicts','revision')}
    result['observation_revision']=hashed({field:q.get(field) for field in ('source','original','times','state','depth','native_contract','occurrence_match','book_confirmation','provider_clocks','observed_book')})
    return result


def financial_price(q):
    """Financial rows reference their original frame without repeated book audits."""
    value=price(q)
    for key in ('occurrence_match','observed_depth','provider_clocks','book_confirmation','freshness_policy','observed_book'):
        value.pop(key,None)
    return value


def age_observation(row, event, at, *, source_states=None, publication_reasons=()):
    """Describe a captured price without changing its original facts or clocks."""
    instant=stamp(at) if isinstance(at,str) else at
    row.setdefault('captured_source_state',row.get('source_state','unknown'))
    row.setdefault('captured_source_health',deepcopy(row.get('source_health',{})))
    health=(source_states or {}).get(row['venue'],{})
    state=health.get('state',row.get('source_state','unknown'))
    row['source_state']=state
    row['source_health']={k:deepcopy(health.get(k)) for k in ('state','reason_code','reason')} if health else deepcopy(row.get('source_health',{}))
    source=freshness(dict(row,state=state),{},event,instant,financial=False)
    source_reasons=list(source['reasons'])
    if row['captured_source_state'] not in ('available','budget_delayed'):
        source_reasons.append('captured_source_unavailable')
    # Runtime controls are source facts, rather than assertions that a clock aged.
    source_reasons.extend(code for code in publication_reasons if code in ('updates_stopped','data_runtime_unhealthy'))
    if state not in ('available','budget_delayed') and row['source_health'].get('reason_code'):
        source_reasons.append(row['source_health']['reason_code'])
    publication=sorted(set(publication_reasons)-{'updates_stopped','data_runtime_unhealthy'})
    source_reasons=sorted(set(source_reasons));reasons=sorted(set(source_reasons+publication))
    unknown=any(code in source_reasons for code in ('source_unknown','source_future','source_future_at_receipt','comparison_input_metadata_unknown'))
    display='unknown' if unknown else 'last_known' if source_reasons else 'pending' if publication else 'current'
    times=row['times']
    def elapsed(key):
        return None if times.get(key) is None else (instant-stamp(times[key])).total_seconds()
    deadline=None
    if not unknown and source.get('current_until') is not None:
        deadline=min(stamp(source['current_until']),stamp(event['start_at'])).isoformat()
    row['freshness']=dict(source,status='historical' if reasons else 'current',reasons=reasons)
    row['observation_display']=dict(state=display,reason_codes=reasons,source_reason_codes=source_reasons,
        publication_reason_codes=publication,read_at=instant.isoformat(),source_age_seconds=elapsed('source_at'),
        received_age_seconds=elapsed('received_at'),current_until=deadline,
        currentness_basis=source.get('currentness_basis'),currentness_at=source.get('currentness_at'),
        confirmation_age_seconds=None if not row.get('book_confirmation') else
            (instant-stamp(row['book_confirmation']['confirmed_at'])).total_seconds())
    return row


def age_gross_comparison(value, at, *, source_states=None, publication_reasons=(), captured_rows=()):
    """Age both frozen inputs; newer peer facts never enter the subtraction."""
    instant=stamp(at) if isinstance(at,str) else at
    if value.get('selection_valid_until') and instant>=stamp(value['selection_valid_until']):
        publication_reasons=[*publication_reasons,'comparison_selection_boundary']
    if value.get('input_refs') and not value.get('inputs'):
        byid={q['quote_id']:q for q in captured_rows}
        value['inputs']=[comparison_input(byid[ref['quote_id']]) for ref in value['input_refs']
            if ref['quote_id'] in byid and byid[ref['quote_id']]['quote_revision']==ref['quote_revision']]
    if value.get('inputs'):value.pop('input_refs',None)
    inputs=value.get('inputs',[])
    for item in inputs:
        # Publications from before this additive metadata can be safely completed
        # only from their own exact stored price, never current ingress quotes.
        original=next((q for q in captured_rows if q.get('quote_id')==item.get('quote_id')
            and q.get('quote_revision')==item.get('quote_revision') and q.get('original')==item.get('original')
            and q.get('times')==item.get('times')),None)
        if original:
            for field in ('source_state','source_health','captured_source_state','captured_source_health','freshness_policy','event','book_confirmation'):
                if field not in item and field in original:item[field]=deepcopy(original[field])
        if not item.get('event') or 'source_state' not in item:
            item['freshness']=dict(status='historical',reasons=['comparison_input_metadata_unknown'],**item.get('times',{}))
            item['observation_display']=dict(state='unknown',reason_codes=sorted(set(['comparison_input_metadata_unknown',*publication_reasons])),
                source_reason_codes=['comparison_input_metadata_unknown'],publication_reason_codes=sorted(set(publication_reasons)),
                read_at=instant.isoformat(),source_age_seconds=None if item['times'].get('source_at') is None else (instant-stamp(item['times']['source_at'])).total_seconds(),
                received_age_seconds=None if item['times'].get('received_at') is None else (instant-stamp(item['times']['received_at'])).total_seconds(),current_until=None)
        else:age_observation(item,item['event'],instant,source_states=source_states,publication_reasons=publication_reasons)
    states={item.get('observation_display',{}).get('state','unknown') for item in inputs}
    value['display_status']='unavailable' if not value['available'] else 'unknown' if len(inputs)!=2 or 'unknown' in states else 'last_known' if 'last_known' in states else 'pending' if 'pending' in states else 'current'
    input_reasons={code for item in inputs for code in item.get('observation_display',{}).get('reason_codes',[])}
    # An unavailable selection has no captured pair. Its diagnostic records why
    # background selection rejected inputs; aging cannot erase that explanation.
    value['reason_codes']=sorted(input_reasons if value['available'] else
        input_reasons|set(value.get('reason_codes',[]))|set(publication_reasons))
    value['read_at']=instant.isoformat()
    clocks=[item.get('times',{}).get('source_at') for item in inputs]
    value['source_time_skew_seconds']=abs((stamp(clocks[0])-stamp(clocks[1])).total_seconds()) if len(clocks)==2 and all(clocks) else None
    return value


def gross_comparison(q,group,event,state,at,*,source_states=None,include_display=True,current_only=False):
    """Existing exact normal-payout price arithmetic over safe source identity."""
    from .current_contract import price as original_price, exact_wire, display_decimal
    result=dict(available=False,value=None,unit='cents',exact=None,comparison_quote_id=None,inputs=[],
        metric='lowest_current' if current_only else 'lowest_observed',
        meaning=('Lowest current compatible other venue price' if current_only else 'Lowest other venue price')+' minus selected price; gross source comparison before fees, sizing and exceptional settlement',
        reason='No other observed venue with the same supported selection and scope',reason_code='comparison_peer_missing')
    if include_display:age_gross_comparison(result,at)
    from app.comparison.same_outcome import quote_identity as same_outcome
    selected_identity=same_outcome(q,group,event)
    display=group.get('display_group')
    if q.get('occurrence_match',{}).get('status')!='matched':
        result.update(reason='Game occurrence identity is unresolved',reason_code='comparison_occurrence_unresolved');return result
    if not selected_identity['supported'] and q.get('native_contract',{}).get('same_outcome') is not None:
        scope=q['native_contract'].get('scope_evidence',{})
        code=(scope.get('reason') or selected_identity['reason']) if scope.get('status') in ('unknown','contradictory') else selected_identity['reason']
        result.update(reason='Matching contract facts unresolved: '+code,reason_code=code,
            reason_codes=sorted(set([code,selected_identity['reason']])),
            missing_fields=sorted(set([*selected_identity.get('missing_fields',[]),*scope.get('missing_fields',[])])));return result
    if not selected_identity['supported'] and (not display or display.get('overtime')=='unknown'):
        scope=q.get('native_contract',{}).get('scope_evidence',{})
        code=scope.get('reason','scoring_overtime_missing')
        result['reason_code']=code
        result['reason']={'scoring_overtime_missing':'Scoring scope missing: overtime inclusion',
            'scoring_overtime_facts_conflict':'Conflicting overtime inclusion facts',
            'scope_review_identity_conflict':'Scoring-scope review does not match this game or native outcome',
            'scope_review_terms_changed':'Scoring-scope review does not match the stored market terms',
            'scope_review_terms_conflict':'Stored copies of the reviewed market terms conflict',
            'scope_review_evidence_unavailable':'Retained scoring-scope evidence is unavailable or changed',
            'scope_review_not_effective':'Scoring-scope review is not effective for this frame',
            'scope_registry_unavailable':'Scoring-scope registry is unavailable or invalid',
            'scope_registry_binding_conflict':'Scoring-scope registry has a conflicting native binding',
            'scope_registry_identity_missing':'Required game or native identity facts are missing',
            'scope_registry_identity_conflict':'Scoring-scope binding conflicts with this game or native outcome',
            'scope_registry_terms_missing':'Required native market descriptions or terms are missing',
            'scope_registry_terms_changed':'Stored market terms have changed since their applicability review',
            'scope_registry_terms_conflict':'Stored copies of native market descriptions or terms conflict',
            'scope_registry_evidence_unavailable':'Retained governing scoring evidence is unavailable or changed',
            'scope_registry_not_effective':'Scoring applicability review is not effective for this frame'}.get(code,'Scoring scope unresolved: '+code)
        result['missing_fields']=scope.get('missing_fields',['overtime']);return result
    if link_reasons(q,at):
        result.update(reason='Game occurrence mapping is outside its supported effective period',reason_code='comparison_mapping_unavailable');return result
    if not q['binding']['verified'] or not common_odds(q)['supported'] or q['original']['payout_units']!='USD':
        result.update(reason='Supported native price and verified selection required',reason_code='comparison_native_unsupported');return result
    if not selected_identity['supported']:
        result.update(reason='Matching contract facts unresolved: '+selected_identity['reason'],reason_code=selected_identity['reason'],
            missing_fields=selected_identity.get('missing_fields',[]));return result
    selection=q['binding']['selection'];keys=('participant','predicate','signed_line','result_interpretation')
    candidates=[(g,other,same_outcome(other,g,e)) for e,g,other in entries(state)
           if e['id']==event['id'] and g['market']==group['market'] and g['period']==group['period'] and other['venue']!=q['venue']]
    possible=[(g,other) for g,other,other_identity in candidates
           if (other_identity['supported'] and other_identity['key']==selected_identity['key'])
           or all(other['binding']['selection'].get(k)==selection.get(k) for k in keys)]
    peers=[other for g,other,other_identity in candidates if other_identity['supported'] and other_identity['key']==selected_identity['key']
           and other['binding']['verified'] and other.get('occurrence_match',{}).get('status')=='matched'
           and other['original']['payout_units']=='USD' and common_odds(other)['supported']]
    if possible and not peers:
        result.update(reason='Other-venue observations exist but their matching scope or native selection is unsupported or conflicting',
            reason_code='comparison_peer_matching_unsupported')
    if current_only:
        boundaries=[]
        for candidate in [q,*peers]:
            for key in ('effective_from','effective_until'):
                boundary=candidate.get('occurrence_link',{}).get(key)
                if boundary and stamp(boundary)>at:boundaries.append(stamp(boundary))
            for key in ('source_at','received_at'):
                clock=candidate['times'].get(key)
                if clock and stamp(clock)>at:boundaries.append(stamp(clock))
            from app.comparison.source_clock import evidence
            clock=evidence(candidate)[0]
            if clock:
                expiry=stamp(clock)+timedelta(seconds=candidate.get('freshness_policy',{}).get('maximum_age_seconds',900))
                # Source-age policy includes the exact maximum-age instant.
                # Client clocks have millisecond resolution. Move the selection
                # boundary to its next millisecond; each input still expires by
                # its exact source-age rule on both server and client.
                if expiry>=at:boundaries.append(expiry+timedelta(milliseconds=1))
        if stamp(event['start_at'])>at:boundaries.append(stamp(event['start_at']))
        result['selection_valid_until']=min(boundaries).isoformat() if boundaries else None
        def noncurrent_reasons(item):
            health=(source_states or {}).get(item['venue'],{})
            reasons=freshness(dict(item,state=health.get('state',item['state'])),{},event,at,financial=False)['reasons']
            return sorted(set([*reasons,*(['captured_source_unavailable'] if item['state'] not in ('available','budget_delayed') else [])]))
        def current(item):
            return item['state'] in ('available','budget_delayed') and not noncurrent_reasons(item)
        if not current(q):
            peer_reasons=[result['reason_code']] if not peers else []
            result.update(reason='Selected observation is not current under its original source clock and source health',
                reason_code='comparison_selected_not_current',reason_codes=sorted(set([*noncurrent_reasons(q),*peer_reasons])));return result
        compatible=bool(peers)
        rejected=sorted({reason for item in peers for reason in [*noncurrent_reasons(item),*link_reasons(item,at)]})
        peers=[item for item in peers if current(item) and not link_reasons(item,at)]
        if compatible:
            result.update(reason='No compatible current other-venue observation under original source clocks and source health',
                reason_code='comparison_peers_not_current',reason_codes=rejected)
    else:peers=[item for item in peers if not link_reasons(item,at)]
    if not peers:return result
    other=min(peers,key=lambda item:(original_price(item),quote_key(item)))
    exact=exact_wire((original_price(other)-original_price(q))*100)
    result.update(available=True,value=exact['decimal_approx'],exact=exact,display_value=display_decimal(exact['decimal_approx'],1,True)+'c',
        comparison_quote_id=quote_key(other),comparison_venue=other['venue'],reason=None,
        inputs=[dict(quote_id=quote_key(item),quote_revision=item['revision'],venue=item['venue'],native_side=item['source']['native_side'],
                     selection=deepcopy(item['binding']['selection']),original=deepcopy(item['original']),times=deepcopy(item['times'])) for item in (q,other)])
    result.pop('reason_code',None)
    if include_display:
        for captured,item in zip(result['inputs'],(q,other)):
            input_group=next((g for g,candidate,_ in candidates if candidate is item),group)
            captured.update(source=deepcopy(item['source']),native_contract_id=item.get('native_contract',{}).get('id'),
                native_contract_summary={key:deepcopy(value) for key,value in item.get('native_contract',{}).items()
                    if key in ('wording','same_outcome')},same_outcome=same_outcome(item,input_group,event),market={key:deepcopy(input_group[key]) for key in ('market','period','period_boundary','line')},source_state=item['state'],source_health=deepcopy((source_states or {}).get(item['venue'],dict(state=item['state'],reason_code=None,reason=None))),
                freshness_policy=deepcopy(item.get('freshness_policy',{})),event={key:deepcopy(event[key]) for key in ('id','title','start_at','sport','league')})
            if item.get('book_confirmation'):captured['book_confirmation']=deepcopy(item['book_confirmation'])
        age_gross_comparison(result,at,source_states=source_states)
    return result


def benchmark(bundle, at=None):
    b=bundle.get('benchmark');fair=[];status='unavailable';reason=bundle.get('benchmark_reason')
    if b is not None:
        try:
            reference=TwoWayBenchmark.from_dict(b)
            if reference.venue!=bundle['benchmark_venue']:
                raise ValueError('selected_benchmark_missing; no substitution')
            status='current' if reference.clock_status(stamp(at or utc()))=='current' else 'historical'
            for participant,probability in reference.fair_probabilities().items():
                fair.append(dict(participant=participant,decisive_probability=str(probability),fair_decimal_odds=str(1/probability)))
        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
            b=None;fair=[];status='unavailable';reason=str(exc)[:160] or 'optional_benchmark_unavailable'
    return dict(freshness=status,venue=bundle['benchmark_venue'],method='proportional_no_vig',available=b is not None,
        revision=None if b is None else b['revision'],originals=[] if b is None else deepcopy(b['outcomes']),fair=fair,reason=reason,
        conditioning='decisive_home_or_away_win',actual_probability=None)


def details_id(value, *, quote=None,pair=None):
    return dict(context_id=value['calculation_context']['context_id'],quote_id=quote,pair_id=pair,
        policy_revision=value['policy']['revision'])


def financial_row(r):
    fields=('revision','dependency_revision','model_available','ranking_eligible','reasons','eligibility_reasons',
        'availability','evaluation_frame','financial_metrics','funding','classification','model_versions','sizing_mode','requested_amount_usd','residual_funding_usd','buffer_usd','size_status','freshness')
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


def comparison_input(row):
    """Detached original frame from the same captured board, never newer rows."""
    fields=('quote_id','quote_revision','venue','native_side','selection','original','times','source','native_contract_id',
        'native_contract_summary','same_outcome','market','source_state','source_health','captured_source_state',
        'captured_source_health','freshness_policy','event','freshness','observation_display','book_confirmation')
    return {key:deepcopy(row[key]) for key in fields if key in row}


def expand_odds(board):
    """Resolve a bounded wire frame locally; no ingress or provider reads."""
    if board.get('comparison_input_encoding')!='same-board-price-refs-1':return board
    prices={q['quote_id']:q for q in board['prices']}
    for original in prices.values():
        original.setdefault('captured_source_health',deepcopy(original.get('source_health',{})))
        summary=original.get('native_contract_summary',{})
        refs=summary.get('wording_refs')
        if refs is not None:
            try:summary['wording']={label:deepcopy(board['native_wordings'][index]) for label,index in refs}
            except (KeyError,IndexError,TypeError):raise ValueError('comparison_wording_reference_conflict')
    for row in board['prices']:
        for field in ('gross_comparison','current_comparison'):
            value=row.get(field,{})
            if not value.get('available'):continue
            if value.get('inputs'):
                value.pop('input_refs',None)
                continue
            refs=value.get('input_refs',[])
            if len(refs)!=2 or any(ref['quote_id'] not in prices or prices[ref['quote_id']]['quote_revision']!=ref['quote_revision'] for ref in refs):
                raise ValueError('comparison_captured_reference_conflict')
            value['inputs']=[comparison_input(prices[ref['quote_id']]) for ref in refs]
            value.pop('input_refs',None)
    return board


def compact_odds(board):
    """Store exact frozen source inputs once within this bounded board frame."""
    if board.get('view')!='odds':return board
    prices={q['quote_id']:q for q in board['prices']}
    for row in board['prices']:
        snapshot=row.get('native_contract_summary',{})
        wording=snapshot.pop('wording',None)
        if wording is not None:
            pool=board.setdefault('native_wordings',[]);wording_refs=[]
            for label,text in wording.items():
                try:index=pool.index(text)
                except ValueError:index=len(pool);pool.append(deepcopy(text))
                wording_refs.append([label,index])
            snapshot['wording_refs']=wording_refs
        if snapshot.get('same_outcome'):
            snapshot['same_outcome']={key:deepcopy(value) for key,value in snapshot['same_outcome'].items()
                if key in ('predicate','equality','scoring')}
        if (row.get('captured_source_state') in ('available','budget_delayed')
                and row.get('source_health')==row.get('captured_source_health')):
            row.pop('captured_source_health',None)
        for field in ('gross_comparison','current_comparison'):
            value=row.get(field,{})
            if not value.get('available'):continue
            refs=[];compatible=True
            for item in value.get('inputs',[]):
                original=prices.get(item['quote_id'])
                # Older self-contained captures may differ from a price still
                # retained beside them. Keep those immutable inputs; a reference
                # may share only the exact scalar frame and capture assessment.
                if original is None or any(original.get(key)!=item.get(key) for key in ('quote_revision','original','times','selection')):
                    compatible=False;break
                for key,default in (('captured_source_state','source_state'),('captured_source_health','source_health')):
                    if item.get(key,item.get(default))!=original.get(key,original.get(default)):
                        compatible=False;break
                if not compatible:break
                refs.append(dict(quote_id=item['quote_id'],quote_revision=item['quote_revision']))
            if not compatible:
                value.pop('input_refs',None)
                continue
            if refs:
                value['input_refs']=refs;value['inputs']=[]
                if field=='gross_comparison':value['meaning']='Peer minus selected, before costs'
                else:value.pop('meaning',None)  # Only the gross tooltip renders this shared explanation.
    board['comparison_input_encoding']='same-board-price-refs-1'
    board['rows']=odds_rows(board['prices'])
    return board


def odds_rows(prices):
    """Compact local index; exact source/comparison frames live once in prices."""
    return [dict(quote_id=q['quote_id'],quote_revision=q['quote_revision'],price_ref=q['quote_id'],venue=q['venue'],
        selection={key:deepcopy(q['selection'].get(key)) for key in ('participant','predicate','signed_line','result_interpretation')},
        market={key:deepcopy(q.get('market',{}).get(key)) for key in ('market','period')}) for q in prices]


def compact_financial(board):
    """Reuse an original only when every captured scalar source fact agrees."""
    prices={q['quote_id']:q for q in board['prices']}
    for row in board['rows']:
        for item in row.get('legs',[row]):
            original=prices.get(item.get('quote_id'))
            if original is None or any(original.get(key)!=item.get(key) for key in ('quote_revision','selection','source','original','times')):continue
            item['price_ref']=item['quote_id']
            for key in ('selection','source_state','native_side','source','original','common_odds','times','native_contract_id','source_health','observation_time_evidence','observation_revision'):
                item.pop(key,None)
    return board


def expand_financial(board):
    prices={q['quote_id']:q for q in board['prices']}
    for row in board['rows']:
        for item in row.get('legs',[row]):
            if 'price_ref' not in item:continue
            original=prices.get(item['price_ref'])
            if original is None or original['quote_revision']!=item['quote_revision']:raise ValueError('financial_captured_reference_conflict')
            saved=deepcopy(item);item.clear();item.update(deepcopy(original));item.update(saved)
    return board


def response(bundle, value, policy, *, view='odds', filter='positive', at=None, stopped=False, history=False):
    if view not in ('odds','ev','arbs') or filter not in ('positive','all','hedges'):raise ValueError('board_view_or_filter_invalid')
    instant=stamp(at or utc());state=bundle['state_inputs'];e=state['events'][0]
    saved=None if value is None else age(value,at=instant.isoformat(),current=state,stopped=stopped,history=history)
    out=dict(version=VERSION,view=view,filter=filter,game_key=bundle['game_key'],input_version=bundle['input_version'],
        policy=policy.to_dict(),benchmark=benchmark(bundle,instant.isoformat()),as_of=bundle['as_of'],read_at=instant.isoformat(),
        calculation_context=bundle.get('calculation_context') if saved is None else saved['calculation_context'],
        result_as_of=None if saved is None else saved['as_of'],calculated_at=None if saved is None else saved.get('calculated_at'),
        delivery_state='stopped' if stopped else 'complete' if view=='odds' else 'pending' if saved is None or saved.get('superseded') else 'complete',
        status='historical' if stopped else 'prices_only' if saved is None else saved['status'],
        prices=[],rows=[],empty_reason=None,provider_requests=0,limits=dict(maximum_response_bytes=MAX_RESPONSE))
    for event,group,q in entries(state):
        row=price(q);row['freshness']=freshness(q,state['comparison_profiles'],event,instant,financial=False)
        health=bundle.get('source_status',{}).get(q['venue'],bundle.get('source_status',{}).get(q['source']['provider'],{}))
        if health:row['source_health']={field:deepcopy(health.get(field)) for field in ('state','reason_code','reason')}
        row['event']={field:deepcopy(event[field]) for field in ('id','title','start_at','sport','league')}
        from app.comparison.same_outcome import quote_identity as same_outcome
        row['same_outcome']=same_outcome(q,group,event)
        if view=='odds':row['native_contract_summary']={key:deepcopy(value) for key,value in q.get('native_contract',{}).items()
            if key in ('wording','same_outcome')}
        row['market']={field:deepcopy(group[field]) for field in ('id','market','period','line','anchor_participant') if field in group}
        if view=='odds':row['gross_comparison']=gross_comparison(q,group,event,state,instant,source_states=bundle.get('source_status',{}))
        if view=='odds':row['current_comparison']=gross_comparison(q,group,event,state,instant,source_states=bundle.get('source_status',{}),current_only=True)
        if view=='odds':
            publication_reasons=['updates_stopped'] if stopped else []
            age_observation(row,event,instant,source_states=bundle.get('source_status',{}),publication_reasons=publication_reasons)
            age_gross_comparison(row['gross_comparison'],instant,source_states=bundle.get('source_status',{}),publication_reasons=publication_reasons,captured_rows=[row])
            age_gross_comparison(row['current_comparison'],instant,source_states=bundle.get('source_status',{}),publication_reasons=publication_reasons,captured_rows=[row])
        row['inputs_identity']=dict(game_key=bundle['game_key'],input_version=bundle['input_version'],quote_id=row['quote_id'],
            quote_revision=row['quote_revision'],observation_revision=row['observation_revision'],context_id=out['calculation_context']['context_id'])
        if view!='odds':
            for field in ('same_outcome','market','event','observed_depth','occurrence_match','book_confirmation','provider_clocks'):
                row.pop(field,None)
        out['prices'].append(row)
    availability_items=[];failures=[]
    if view=='odds':out['rows']=odds_rows(out['prices'])
    elif saved:
        originals={q['id']:q for _,_,q in entries(saved['state'])}
        if view=='ev':
            for _,_,q in entries(saved['state']):
                r=q['calculations']['funded_estimate'];row=dict(financial_price(q),**financial_row(r),details=details_id(saved,quote=q['id']))
                availability_items.append((bundle['game_key'],[q['venue']],row['availability']))
                if filter=='all' or row.get('classification',{}).get('main_positive_eligible'):out['rows'].append(row)
        else:
            for event in saved['state']['events']:
                for r in event.get('funded_pairs',[]):
                    if len({originals[l['quote_id']]['venue'] for l in r['legs']})!=2:continue
                    row=dict(financial_row(r),pair_id=r['id'],details=details_id(saved,pair=r['id']),legs=[])
                    funding={leg['quote_id']:leg for leg in r.get('funding',{}).get('legs',[])}
                    for index,l in enumerate(r['legs']):
                        exact=funding.get(l['quote_id'],l)
                        row['legs'].append(dict(financial_price(originals[l['quote_id']]),native_quantity=exact['native_quantity'],native_unit=exact['native_unit'],
                            acquisition_usd=exact['acquisition_usd'],upfront_fee_usd=exact['net_upfront_fee_usd']))
                    availability_items.append((bundle['game_key'],[l['venue'] for l in row['legs']],row['availability']))
                    c=row.get('classification',{})
                    if filter=='all' or filter=='positive' and c.get('main_positive_eligible') or filter=='hedges' and c.get('positive_rule_sensitive_eligible'):out['rows'].append(row)
            for event in saved['state']['events']:
                for diagnostic in event.get('funded_pair_search',{}).get('diagnostics',[]):
                    state,codes=refusal([diagnostic['reason']])
                    availability_items.append((bundle['game_key'],[],dict(state=state,reason_codes=codes,current_opportunity_eligible=False)))
    out['availability']=summary(availability_items,evaluated=saved is not None and view!='odds',failures=failures)
    if not out['rows']:out['empty_reason']='Calculation pending' if saved is None else 'No positive EV found' if view=='ev' and filter=='positive' else 'No estimated arbitrage found' if view=='arbs' and filter=='positive' else 'No eligible comparisons found'
    if not out['rows'] and view!='odds':
        outcome=out['availability']['outcome']
        if outcome in ('not_evaluated','unavailable','partial','last_known_only'):
            out['empty_reason']={'not_evaluated':'Calculations not evaluated','unavailable':'Calculations unavailable',
                'partial':'Some comparisons unavailable; no current positive result',
                'last_known_only':'Only last-known estimates available; see All comparisons'}[outcome]
    if view=='odds':compact_odds(out)
    else:compact_financial(out)
    if len(encoded(out))>MAX_RESPONSE:raise ValueError('board_compact_response_capacity')
    return out


def details(value, *, quote=None,pair=None,at=None,current=None,stopped=False,history=False):
    v=age(value,at=at,current=current,stopped=stopped,history=history)
    rows={q['id']:q for _,_,q in entries(v['state'])}
    if bool(quote)==bool(pair):raise ValueError('one_exact_saved_selection_required')
    q=rows.get(quote);p=next((p for e in v['state']['events'] for p in e.get('funded_pairs',[]) if p['id']==pair),None)
    if not q and not p:raise ValueError('exact_saved_selection_absent')
    selected = p or q['calculations']['funded_estimate']
    # Keep the server-supplied percentage companions identical to the board.
    # This adds presentation fields to the copied frame without repricing it.
    selected['financial_metrics'] = financial_row(selected)['financial_metrics']
    return dict(version='predict-board-details-2',game_key=v['game_key'],calculation_context=v['calculation_context'],
        as_of=v['as_of'],read_at=v['read_at'],calculated_at=v.get('calculated_at'),status=v['status'],policy=v['policy'],quote=q,pair=p,
        original_inputs_identity=dict(game_key=v['game_key'].split(':benchmark:',1)[0],input_version=v['input_version'],context_id=v['calculation_context']['context_id'],policy_revision=v['policy']['revision']),
        leg_quotes=[rows[l['quote_id']] for l in p['legs']] if p else [],profiles=v['state']['comparison_profiles'],
        representation=v['representation'])
