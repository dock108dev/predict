"""Bound independent ordinary-source facets without acquiring provider data.

Native provenance and a display payout are not settlement authority. Retained
records can therefore bind identity/reference/policy while withholding net costs.
All source clocks remain originals; projecting an input never refreshes it.
"""
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction

from app.comparison.current_dependencies import (KINDS, VERSION, MAX_PROFILES,
    MAX_PROFILES_BYTES, encoded, profile, references)
from app.comparison.costs import DEFAULT_POLICY
from app.comparison.domain import CanonicalSelection
from app.dashboard.current_contract import quotes_of, binding_context

PRODUCER_VERSION = 'comparison-ordinary-source-bindings-1'
MAX_QUOTES = 16000
MAX_REFERENCES = 16000
FEE_GAPS = {
    'kalshi': 'selected_standard_direct_site_published_fee_terms_unqualified',
    'polymarket_us': 'selected_standard_direct_site_published_fee_terms_unqualified',
    'novig': 'selected_standard_direct_site_published_fee_terms_unqualified',
    'prophetx': 'selected_standard_direct_site_published_rate_rounding_and_charges_unqualified',
}


def status(value, reason, **facts):
    return dict(status=value, reason=reason, **facts)


def evidence(q):
    return dict(ref='ordinary-source-receipt:'+q['provenance']['sha256'],
                sha256=q['provenance']['sha256'], evidence_class='retained')


def selection(event, group, outcome, q):
    """Source-local selection with unknown rule scope; no opponent substitution."""
    roles={p['role']:p['id'] for p in event['participants']}
    participant=outcome['participant']
    family={'winner':'moneyline','spread':'spread','total':'total'}[group['market']]
    native=q['source'];ev=evidence(q)
    home=participant==roles['home']
    signed=outcome['signed_line'] if family=='spread' else None
    if family=='total':
        domain='combined_score';threshold=group['line'];participant='combined'
        operator={'over':'gt','under':'lt'}[outcome['predicate']]
    else:
        domain='home_margin';threshold='0'
        operator={'win':'gt' if home else 'lt', 'not_win':'le' if home else 'ge',
                  'draw':'eq','cover':'gt' if home else 'lt'}[outcome['predicate']]
        if family=='spread':threshold=str(-Fraction(signed) if home else Fraction(signed))
    equality=dict(treatment='unknown',payout=None,refund_fees='not_applicable',
                  unknown_reason='source_equality_payout_unqualified')
    if Fraction(threshold).denominator==2:
        equality.update(treatment='not_feasible',unknown_reason=None)
    value=dict(schema_version='comparison-domain-1',
        event=dict(occurrence_id=event['id'],league=event['league'],home_id=roles['home'],
                   away_id=roles['away'],identity_evidence=[ev]), family=family,
        scope=dict(period=group['period'],overtime='unknown',completion='unverified'),
        participant_id=participant,signed_line=signed,
        predicate=dict(domain=domain,operator=operator,threshold=threshold,subject_id=None),
        equality=equality,native=dict(venue=q['venue'],event_id=native['native_event_id'],
            market_id=native['native_market_id'],instrument_id=native['native_outcome_id'],
            side_id=native['native_side'],original_wording=outcome['label'],evidence=[ev]),
        payout=None,payout_unknown=dict(value=None,reason='exact_rule_completion_payout_unqualified',
            missing_evidence=['selected instrument payout terms','completion and exceptional cashflows']),
        price=dict(amount=q['original']['value'],unit=q['original']['units'],
            payout_unit='usd_per_contract' if q['original']['units'] in ('usd_per_contract','cents_per_contract') else 'usd_per_usd_stake',
            currency='USD'))
    return CanonicalSelection.from_dict(value).to_dict()


def reference_payload(q, reference_records):
    """Retain the exact two originals admitted by the ordinary benchmark seam.

    Aggregate outcome-specific market IDs stay distinct. A legacy typed net
    reference consumer must qualify that provider grouping before reusing it.
    """
    ref=q.get('sharp_reference')
    if ref is None:return None
    payload=dict(version=PRODUCER_VERSION,bookmaker='pinnacle',
        conditioning='decisive_win_loss',receipt_sha256=ref['sha256'],
        source_at=deepcopy(ref['source_at']),selected=ref['selected'],
        original_odds=deepcopy(ref['odds']),selected_odds=ref['odds'][ref['selected']],
        current_selection_binding=deepcopy(q['binding']['selection']),
        provider_clocks=deepcopy(ref.get('provider_clocks')),outcomes=[],
        original_received_at=ref['received_at'])
    target=q['binding']['selection'];native=q['source']
    # Period boundary prose is not an identity. Use the admitted original pair's
    # selected outcome and exact line to select its disjoint opposition instead.
    candidates=[r for r in reference_records if r['quote']['venue']=='pinnacle'
        and r['quote']['provenance']['sha256']==ref['sha256']
        and (native['provider']!='the_odds_api' or r['quote']['source']['native_event_id']==native['native_event_id'])
        and r['market_identity']['period']=='full_game'
        and r['market_identity']['family']=={'win':'moneyline','cover':'spread','over':'total','under':'total'}.get(target['predicate'])]
    selected=[r for r in candidates if r['selection']['participant']==target['participant']
        and r['selection']['predicate']==target['predicate']
        and (r['selection']['signed_line'] is None and target['signed_line'] is None or
             r['selection']['signed_line'] is not None and target['signed_line'] is not None and
             Fraction(r['selection']['signed_line'])==Fraction(target['signed_line']))
        and r['quote']['original']['value']==ref['selected_odds']]
    if len(selected)!=1:return payload
    chosen=selected[0];key=chosen['market_identity']
    pair=[r for r in candidates if r['market_identity']==key]
    if len(pair)!=2:return payload
    from .current_benchmark import key as benchmark_key
    pair=sorted(pair,key=benchmark_key)
    if [r['quote']['original']['value'] for r in pair]!=ref['odds']:
        return payload
    for r in pair:
        rq=r['quote']
        payload['outcomes'].append(dict(source=deepcopy(rq['source']),selection=deepcopy(r['selection']),
            decimal_odds=rq['original']['value'],source_at=rq['times']['source_at'],
            received_at=rq['times']['received_at'],provider_clocks=deepcopy(rq.get('provider_clocks')),
            receipt_sha256=rq['provenance']['sha256'],market_identity=deepcopy(r['market_identity']),
            orientation_evidence=deepcopy(r['orientation_evidence'])))
    return payload


def prospective_reference_review(q):
    """Disclosure of an already bound selected review; no price or eligibility input."""
    if q.get('sharp_reference') is None or q['venue']!='polymarket_us':return None
    from .current_occurrence import selected_proof
    from app.dashboard.current_contract import stamp
    proof=selected_proof();source=q['source'];target=proof['sources']['polymarket_us']
    market=target['markets'].get(source['native_market_id'],{})
    outcome=market.get('outcomes',{}).get(source['native_outcome_id'])
    selection=q['binding']['selection']
    if (source['native_event_id']!=target['event_id'] or outcome is None or
            not q['binding']['verified'] or selection['participant']!=outcome['participant'] or selection['predicate']!=outcome['predicate']):return None
    if any(q['times'].get(k) is None or not stamp(proof['applicability']['start'])<=stamp(q['times'][k])<stamp(proof['applicability']['end']) for k in ('source_at','received_at')):return None
    return dict(status='bound_prospective_manual_review',occurrence_id=proof['event']['game_id'],
        evidence_sha256=proof['evidence'][0]['sha256'],effective_from=proof['applicability']['start'],
        effective_until=proof['applicability']['end'],historical_applicability=False,
        venue='Tottenham Hotspur Stadium; NFL2026 regular-season Week5',
        rules='NFL full-game includes overtime; Pinnacle two-way tie void differs from native0.50; exceptional rules differ',
        rule_version='Unversioned official page reviewed October9; no historical effective date established')


def attach(snapshot, *, reference_records=(), selected_applicability=None):
    """Return latest bounded shared profiles and attach quote-level references.

    Call after catalog_from_normalized, inside the same atomic admission. Inputs
    are public admitted records only. Capacity deferral is quote-local and never
    rejects a healthy price or erases its original source evidence.
    """
    if not isinstance(snapshot,dict) or not isinstance(reference_records,(list,tuple)) or len(reference_records)>MAX_REFERENCES:
        raise ValueError('Bounded ordinary comparison attachment required')
    from app.comparison.source_inputs import selected_status
    from app.comparison.current_dependencies import instant
    if selected_applicability is None:
        import json
        from pathlib import Path
        selected_applicability=json.loads((Path(__file__).resolve().parents[1]/'fixtures/comparison-selected-applicability-v1.json').read_text())
        from app.comparison.public_retail import registry
        selected_applicability=registry(selected_applicability)
    existing=snapshot.get('comparison_profiles',{})
    profiles={}
    buffer_key,buffer=profile('buffer',asdict(DEFAULT_POLICY))
    quotes=[(e,g,o,q) for e in snapshot['events'] for g in e['groups']
            for o in g['outcomes'] for q in quotes_of(o)]
    if len(quotes)>MAX_QUOTES:raise ValueError('Bounded ordinary quote attachment required')
    quotes.sort(key=lambda row:(row[0]['id'],row[1]['id'],row[2]['id'],row[3]['venue'],
        row[3]['source']['native_event_id'],row[3]['source']['native_market_id'],
        row[3]['source']['native_outcome_id']))
    reference_index={}
    for record in reference_records:
        quote=record['quote']
        if quote['venue']=='pinnacle':
            reference_index.setdefault((quote['provenance']['sha256'],
                quote['source']['native_event_id']),[]).append(record)
    # Preserve every existing live dependency, including authored test contexts.
    # Drop only unreachable history from this latest atomic snapshot.
    for _,_,_,q in quotes:
        references(q,existing)
        for key in q.get('comparison_input_refs',{}).get('refs',{}).values():
            if key is not None:profiles[key]=existing[key]
    def bind(kind,payload,refs,states):
        key,value=profile(kind,payload)
        if key not in profiles and (len(profiles)>=MAX_PROFILES or
                len(encoded(dict(profiles,**{key:value})))>MAX_PROFILES_BYTES):
            states[kind]=status('available_but_unbound','comparison_profile_capacity_deferred')
            return
        profiles[key]=value;refs[kind]=key
    for e,g,o,q in quotes:
        if q['provenance']['mode']=='synthetic':continue
        old=deepcopy(q.get('comparison_input_refs'))
        refs=old['refs'] if old else {kind:None for kind in KINDS}
        states=dict(identity=status('available_and_bound','source_native_selection_bound'),
            payout=status('applicability_unresolved','exact_rule_completion_payout_unqualified'),
            fee=status('applicability_unresolved',FEE_GAPS.get(q['venue'],
                'execution_channel_and_mandatory_fee_terms_unqualified')),
            quantity=status('absent','legal_minimum_increment_tick_unavailable',
                observed_quantity_unit=q['original']['quantity_units']),
            reference=status('absent','exact_pinnacle_opposition_unavailable'),
            probability=status('absent','exact_conditional_reference_unavailable'),
            buffer=status('available_and_bound','reviewed_100_usd_standalone_taker_policy'),
            phase=status('applicability_unresolved','source_phase_not_attested'),
            depth=status('available_and_bound' if q.get('depth') else 'absent',
                'observed_native_book_only' if q.get('depth') else 'observed_depth_unavailable',
                levels=len(q.get('depth',[])),fill_assumption='hypothetical_one_order',observed_fills=False))
        states.update(deepcopy(q.get('comparison_input_status',{})))
        from app.comparison.public_retail import saved_facets
        upgrade=saved_facets(q,e,g,o,selected_applicability,instant(snapshot['clock_at']))
        if upgrade is not None:
            for kind,key in upgrade['comparison_input_refs']['refs'].items():
                if key is None:continue
                item=upgrade['profiles'][key]
                if key in profiles or len(profiles)<MAX_PROFILES and len(encoded(dict(profiles,**{key:item})))<=MAX_PROFILES_BYTES:
                    profiles[key]=item;refs[kind]=key
                    states[kind]=upgrade['gaps'][kind]
                else:
                    states[kind]=status('available_but_unbound','comparison_profile_capacity_deferred')
            for kind,item in upgrade['gaps'].items():
                if upgrade['comparison_input_refs']['refs'].get(kind) is None:states[kind]=item
        selected_states,selected_audit=selected_status(q,selected_applicability,instant(snapshot['clock_at']))
        from app.comparison.public_retail import observation_audit
        retail_audit=observation_audit(q)
        # Full producer-qualified facets win. Saved projections bind independently
        # retained partial facts without promoting them into numeric rule authority.
        for kind,item in selected_states.items():
            if item.get('status')=='expired' or states.get(kind,{}).get('status')!='available_and_bound':states[kind]=item
        if upgrade is not None and refs['fee'] is not None and profiles[refs['fee']]['payload'].get('version')=='comparison-direct-site-retail-case-1':
            if upgrade['comparison_input_refs']['refs']['fee']==refs['fee']:
                states['fee']=deepcopy(upgrade['gaps']['fee'])
        if retail_audit is not None:
            states['quantity']['public_retail']=retail_audit
            from app.comparison.public_retail import entry_example, retained, fresh_retained
            states['fee']['public_entry_example']=entry_example(fresh_retained() if retail_audit.get('retained_observation_bound') else retained())
            from app.comparison.public_retail import charge_audit
            charges=charge_audit(q)
            if charges is not None:states['fee']['charge_completeness']=charges
            if not retail_audit.get('retained_observation_bound') and q['provenance']['sha256']!=retail_audit['metadata']['response_sha256']:
                states['quantity']['reason']='public_retail_historical_applicability_unqualified'
            elif q.get('sharp_reference') is None:
                states['probability']=status('absent','public_retail_exact_reference_probability_absent')
        if refs['buffer'] is None:
            states['buffer']=status('available_and_bound','reviewed_100_usd_standalone_taker_policy')
            bind('buffer',buffer['payload'],refs,states)
        if refs['identity'] is None:
            try:
                if q['binding']['selection']!=binding_context(e,g,o):
                    raise ValueError('Exact ordinary quote binding conflict')
                typed=selection(e,g,o,q)
                payload=dict(version=PRODUCER_VERSION,selection=typed,
                    current_selection_binding=deepcopy(q['binding']['selection']),
                    current_scope_binding=dict(current_event_id=e['id'],occurrence_id=e['id'],
                        period_boundary=g['period_boundary'],result_policy=g.get('result_policy','unspecified'),
                        scope=typed['scope'],evidence=[evidence(q)]),
                    source=deepcopy(q['source']),original_clocks=deepcopy(q['times']),
                    provider_clocks=deepcopy(q.get('provider_clocks')),
                    native_predicate=deepcopy(q.get('native_predicate')),
                    occurrence_link=deepcopy(q.get('occurrence_link')),
                    orientation_evidence=deepcopy(q['binding']['evidence']),
                    occurrence_qualification='source_local' if q['binding']['verified'] else 'unverified_source_local',
                    rule_revision=None,completion_context=None)
                if selected_audit is not None:payload['selected_binding']=selected_audit
                states['identity']=status('available_and_bound','source_native_selection_bound')
                bind('identity',payload,refs,states)
                if not q['binding']['verified']:
                    states['identity']=status('applicability_unresolved','source_local_occurrence_scope_unqualified')
            except (ValueError,KeyError,TypeError,ArithmeticError):
                states['identity']=status('contradictory','source_native_selection_attachment_conflict')
        from app.comparison.public_event import audit as event_audit
        event_facts=event_audit(q,selected_applicability,instant(snapshot['clock_at']),
            roles={p['role']:p['id'] for p in e['participants']})
        previous_event=states['identity'].get('public_event')
        if event_facts is not None and previous_event is not None and previous_event['status']=='contradictory' and previous_event['binding_version']==event_facts['binding_version']:
            event_facts=previous_event
        if event_facts is not None:
            states['identity']['public_event']=event_facts
            if refs['identity'] is not None:
                previous=profiles[refs['identity']]
                payload=deepcopy(previous['payload']);payload['public_event']=event_facts
                key,item=profile('identity',payload,expires_at=previous['expires_at'])
                if key==refs['identity'] or len(profiles)<MAX_PROFILES and len(encoded(dict(profiles,**{key:item})))<=MAX_PROFILES_BYTES:
                    profiles[key]=item;refs['identity']=key
                else:
                    states['identity']=status('available_but_unbound','comparison_profile_capacity_deferred',public_event=event_facts)
        sharp=q.get('sharp_reference')
        candidates=reference_records
        if sharp and q['source']['provider']=='the_odds_api':
            candidates=reference_index.get((sharp['sha256'],q['source']['native_event_id']),[])
        ref=reference_payload(q,candidates)
        if sharp is None:
            from app.comparison.reference_gap import assessment
            retained_gap=assessment(q)
            if retained_gap is not None:
                states['reference']=status('applicability_unresolved',
                    'retained_pinnacle_candidate_occurrence_edge_unqualified',
                    retained_candidate=retained_gap)
        previous_reference=profiles.get(refs['reference'],{}).get('payload',{})
        # A first retained projection may know both prices/clocks but lack the
        # original opposition IDs. A later replay can attach those originals
        # without replacing any fully qualified core reference or its history.
        complete_partial=(ref is not None and len(ref['outcomes'])==2 and
            previous_reference.get('version')==PRODUCER_VERSION and
            len(previous_reference.get('outcomes',[]))!=2 and
            {k:v for k,v in ref.items() if k!='outcomes'}==
            {k:v for k,v in previous_reference.items() if k!='outcomes'})
        if ref is not None and (refs['reference'] is None or complete_partial):
            states['reference']=status('available_and_bound' if len(ref['outcomes'])==2 else 'available_but_unbound',
                'original_pinnacle_opposition_bound' if len(ref['outcomes'])==2 else 'reference_native_opposition_ids_unavailable')
            bind('reference',ref,refs,states)
        if ref is not None and refs['probability'] is None:
            odds=ref['original_odds'];weights=[1/Fraction(v) for v in odds];total=sum(weights)
            probability=dict(version='comparison-benchmark-basis-1',method='pinnacle_proportional_no_vig',
                conditioning='decisive_win_loss',probabilities=[str(v/total) for v in weights],
                selected=ref['selected'],unknown_mass=['exceptional', 'tie' if g['market']=='winner' else 'push']
                    if g['market']=='winner' or Fraction(g['line']).denominator==1 else ['exceptional'],
                reference_receipt_sha256=ref['receipt_sha256'],source_at=deepcopy(ref['source_at']))
            states['probability']=status('available_and_bound','conditional_decisive_weights_only')
            bind('probability',probability,refs,states)
        q['comparison_input_refs']=dict(version=VERSION,refs=refs,phase=old['phase'] if old else 'unknown')
        review=prospective_reference_review(q) if refs['reference'] is not None else None
        if review is not None:states['reference']['prospective_review']=review
        states['fee']['trading_scope']='standard_direct_site_retail'
        q['comparison_input_status']=states
    reachable={key for _,_,_,q in quotes
        for key in q.get('comparison_input_refs',{}).get('refs',{}).values() if key is not None}
    result={key:value for key,value in profiles.items() if key in reachable}
    # A selected modeled successor retains the dated prior cost refusal/profile.
    # Ordinary snapshots continue to use the existing bounded history policy.
    if any(v['payload'].get('version')=='comparison-direct-site-retail-case-1' for v in result.values()):
        for key,value in existing.items():
            if key not in result and len(result)<MAX_PROFILES and len(encoded(dict(result,**{key:value})))<=MAX_PROFILES_BYTES:
                result[key]=value
    return result
