"""Bounded ordinary admission -> shared calculation input producer.

No provider, file, account or clock access. The caller supplies one admitted
record, its exact current attachment and reviewed source-rule registry. Native
identity stays source-local unless admission already proved an occurrence link.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
from fractions import Fraction

from .current_dependencies import KINDS, VERSION as REFS_VERSION, digest, encoded, instant, profile, public_tree
from .costs import CostRule, DEFAULT_POLICY, QuantityGridInputs, UnitSpec
from .domain import (CanonicalSelection, EqualityDescriptor, EventReference, EvidenceReference,
                     ExactNumber, NativeProvenance, Price, Scope, ScorePredicate, UnknownValue)
from .payouts import (CompletionContext, NormalCondition, PayoutCell, PayoutProfile,
                      bind_profile, selection_digest)
from .pinnacle import ReferenceOutcome, ReferenceSet
from .net_costs import wire

VERSION = 'comparison-source-inputs-1'
RULES_VERSION = 'comparison-source-rules-1'
MAX_RULES = 64
MAX_CONTEXT_BYTES = 512 * 1024
SUPPORTED = {'moneyline', 'spread', 'total'}
SELECTED_VERSION = 'comparison-selected-applicability-1'


def observation(q):
    """Immutable original attachment; receipt time is not price freshness."""
    return dict(native_key=list(_native_key(q)), original=deepcopy(q['original']),
        source_at=q['times']['source_at'], received_at=q['times']['received_at'],
        provenance_sha256=q['provenance']['sha256'])


def selected_binding(q, registry, at):
    """Resolve a reviewed selected record, never a venue-wide qualification flag.

    Each independently evidenced facet has its own payload. Original attachment,
    half-open interval and content version prevent a sibling or changed receipt
    from borrowing a selected qualification. Missing facets remain local unknowns.
    """
    if registry is None:return None, None
    if (not isinstance(registry,dict) or registry.get('version')!=SELECTED_VERSION or
            not isinstance(registry.get('records'),list) or len(registry['records'])>64 or
            len(encoded(registry))>MAX_CONTEXT_BYTES):
        raise ValueError('source_selected_registry_invalid')
    public_tree(registry)
    candidates=[r for r in registry['records'] if r.get('native_key')==list(_native_key(q))]
    if not candidates:return None, None
    matching=[]
    for row in candidates:
        content={k:v for k,v in row.items() if k!='binding_version'}
        if row.get('binding_version')!=digest(content):
            return None, gap('contradictory','source_selected_binding_digest_conflict')
        if row.get('observation')!=observation(q):continue
        if row.get('quote_revision') is not None and row['quote_revision']!=q['revision']:continue
        matching.append(row)
    if not matching:return None, gap('applicability_unresolved','source_selected_observation_revision_unqualified')
    active=[r for r in matching if instant(r['effective_from'])<=at and
        (r.get('effective_until') is None and not r.get('facets') or
         r.get('effective_until') is not None and at<instant(r['effective_until']))]
    if not active:return None, gap('expired','source_selected_binding_expired_or_not_effective')
    if len(active)!=1:return None, gap('contradictory','source_selected_binding_not_unique')
    row=active[0]
    if set(row.get('facets',{})) - {'payout','fee','quantity','phase'}:
        return None, gap('contradictory','source_selected_facet_invalid')
    return row, None


def _facet(row,kind,q):
    facet=row.get('facets',{}).get(kind)
    if facet is None:raise ValueError('source_selected_'+kind+'_applicability_unqualified')
    refs=facet.get('evidence',[])
    if not refs or len(refs)>16:raise ValueError('source_selected_evidence_missing')
    parsed=[EvidenceReference.from_dict(e) for e in refs]
    if q['provenance']['real_source'] and any(e.evidence_class=='authored' for e in parsed):
        raise ValueError('source_selected_authored_evidence_unqualified')
    return facet


def selected_status(q, registry, at):
    """Independent retained facts for saved projections as well as admission."""
    row,problem=selected_binding(q,registry,at)
    if problem:return {kind:deepcopy(problem) for kind in ('payout','fee','quantity')}, None
    if row is None:return {}, None
    states={}
    for kind,fact in row.get('facts',{}).items():
        if kind not in ('payout','fee','quantity','phase'):continue
        states[kind]=gap(fact['status'],fact['reason'],fact.get('evidence',[]))
        if fact['status']=='available_and_bound':
            states[kind]=gap('available_but_unbound','source_selected_fact_is_not_numeric_qualification',fact.get('evidence',[]))
        states[kind]['selected_facts']=deepcopy(fact.get('values',{}))
        states[kind]['binding_version']=row['binding_version']
    return states, dict(version=SELECTED_VERSION,binding_version=row['binding_version'],
        native_key=row['native_key'],effective_from=row['effective_from'],
        effective_until=row['effective_until'],facts=deepcopy(row.get('facts',{})))


def gap(status, reason, evidence=()):
    return dict(status=status, reason=reason, evidence=[deepcopy(x) for x in evidence])


def _evidence(ref, sha, kind='retained'):
    return EvidenceReference(ref, sha, kind)


def _native_key(q):
    s=q['source']
    return (q['venue'], s['native_event_id'], s['native_market_id'],
            s['native_outcome_id'], s['native_side'])


def _phase(record, metadata, at):
    value=metadata.get('phase')
    if value in ('pregame', 'live', 'unknown'):
        return value
    native=record['event'].get('_native', {})
    if native.get('live') is True and native.get('ended') is not True:
        return 'live'
    if native.get('live') is False and native.get('ended') is False:
        return 'pregame'
    # Aggregate source timestamps precede the documented scheduled occurrence.
    # Once the start passes, no fabricated live observation replaces unknown.
    source=record['quote']['times'].get('source_at')
    start=record['event'].get('scheduled_start')
    if source is not None and start is not None and instant(source) <= at < instant(start):
        return 'pregame'
    return 'unknown'


def _rule(record, registry, at):
    if not isinstance(registry, dict) or registry.get('schema') != 1 or registry.get('version') != RULES_VERSION:
        return None, gap('absent', 'reviewed_source_rule_registry_missing')
    rows=registry.get('rules')
    if not isinstance(rows, list) or len(rows)>MAX_RULES or len(encoded(registry))>MAX_CONTEXT_BYTES:
        raise ValueError('source_rule_registry_capacity')
    public_tree(registry)
    q=record['quote'];m=record['market_identity']
    channel='aggregate' if q['source']['provider']=='the_odds_api' else 'native'
    matches=[r for r in rows if r.get('venue')==q['venue'] and r.get('channel')==channel
        and m['family'] in r.get('market_families', []) and r.get('period')==m['period']
        and (not r.get('leagues') or record['event']['competition'] in r['leagues'])]
    active=[]; expired=False
    for r in matches:
        if r.get('effective_from') is not None and at < instant(r['effective_from']):
            continue
        if ((r.get('effective_to') is not None and at >= instant(r['effective_to'])) or
                (r.get('expires_at') is not None and at>=instant(r['expires_at']))):
            expired=True;continue
        # Optional exact scoping cannot be widened by a generic sibling row.
        if r.get('native_key') is not None and tuple(r['native_key']) != _native_key(q):
            continue
        active.append(r)
    if len(active)>1:
        return None, gap('contradictory', 'source_rule_applicability_not_unique')
    if not active:
        return None, gap('expired' if expired else 'applicability_unresolved',
                         'source_rules_expired' if expired else 'source_channel_rule_not_established')
    return active[0], None


def _scope(record, rule, metadata):
    m=record['market_identity']
    if m['family'] not in SUPPORTED or m['period']!='full_game':
        raise ValueError('source_market_scope_unsupported')
    if m['family']!='moneyline' and Fraction(m['line']).denominator != 2:
        raise ValueError('integer_line_push_inputs_unqualified')
    payout=(rule or {}).get('payout') or {}
    if metadata.get('overtime') in ('included','excluded') and payout.get('overtime') in ('included','excluded') and metadata['overtime']!=payout['overtime']:
        raise ValueError('source_overtime_scope_conflict')
    overtime=metadata.get('overtime', payout.get('overtime', 'unknown'))
    if overtime not in ('included', 'excluded'):
        raise ValueError('source_overtime_scope_unresolved')
    return Scope(m['period'], overtime, 'conditional_completed_result')


def _selection(record, context, scope):
    q=context['quote'];e=context['event'];g=context['group'];o=context['outcome']
    s=q['source'];source=record['quote']['source'];r=record['selection'];original=q['original']
    if any(s[k]!=source[k] for k in ('provider','native_event_id','native_market_id','native_outcome_id','native_side')):
        raise ValueError('ordinary_source_native_attachment_conflict')
    if q['venue']!=record['quote']['venue'] or original!=record['quote']['original']:
        raise ValueError('ordinary_source_price_attachment_conflict')
    from app.dashboard.current_contract import binding_context
    if q['binding']['selection'] != binding_context(e,g,o):
        raise ValueError('ordinary_current_selection_attachment_conflict')
    signed_equal=(r['signed_line'] is None and o['signed_line'] is None) or (
        r['signed_line'] is not None and o['signed_line'] is not None and Fraction(r['signed_line'])==Fraction(o['signed_line']))
    if any(r[k]!=o[k] for k in ('participant','predicate')) or not signed_equal:
        raise ValueError('ordinary_current_predicate_attachment_conflict')
    roles={x['role']:x['id'] for x in e['participants']}
    event=record['event']
    if e['league']!=event['competition'] or roles != {'home':event['home'],'away':event['away']}:
        raise ValueError('ordinary_current_participant_role_conflict')
    if g['period']!=scope.period or {'winner':'moneyline','spread':'spread','total':'total'}.get(g['market'])!=record['market_identity']['family']:
        raise ValueError('ordinary_current_scope_attachment_conflict')
    sha=q['provenance']['sha256']
    ev=_evidence('admitted:'+s['provider']+':'+s['native_event_id']+':'+s['native_market_id'], sha,
                 'authored' if q['provenance']['mode']=='synthetic' else 'retained')
    # Preserve reviewed occurrence identity when admission provides it. Otherwise
    # namespace the durable provider ID; schedule is deliberately absent.
    occurrence='comparison-source-occurrence-1:'+digest([s['provider'],s['native_event_id'],e['league'],roles])
    if record['market_identity']['event'][0]=='comparison-reviewed-occurrence-1':
        occurrence=event['game_id']
    ref=EventReference(occurrence,e['league'],roles['home'],roles['away'],(ev,))
    family=record['market_identity']['family'];participant=r['participant']
    signed=None;line=record['market_identity']['line']
    if family=='moneyline':
        op={'win':'gt' if participant==ref.home_id else 'lt',
            'not_win':'le' if participant==ref.home_id else 'ge','draw':'eq'}.get(r['predicate'])
        if op is None:raise ValueError('ordinary_winner_predicate_unsupported')
        pred=ScorePredicate('home_margin',op,ExactNumber('0'))
        equality=EqualityDescriptor('unknown',None,'not_applicable','Exact tie settlement not established')
    elif family=='spread':
        signed=ExactNumber.parse(r['signed_line'])
        pred=ScorePredicate('home_margin','gt' if participant==ref.home_id else 'lt',
            ExactNumber(str(-signed.value if participant==ref.home_id else signed.value)))
        equality=EqualityDescriptor('not_feasible',None,'not_applicable',None)
    else:
        participant='combined'
        pred=ScorePredicate('combined_score',{'over':'gt','under':'lt'}[r['predicate']],ExactNumber.parse(line))
        equality=EqualityDescriptor('not_feasible',None,'not_applicable',None)
    native=NativeProvenance(q['venue'],s['native_event_id'],s['native_market_id'],s['native_outcome_id'],
        s['native_side'],r['label'],(ev,))
    price=Price(ExactNumber.parse(original['value']),original['units'],
        'usd_per_contract' if original['units'] in ('usd_per_contract','cents_per_contract') else 'usd_per_usd_stake','USD')
    selection=CanonicalSelection(ref,family,scope,participant,signed,pred,equality,native,None,price,
        UnknownValue('Applicable settlement profile not attached',('Reviewed source payout applicability',)))
    selection.semantic_key()
    return selection, ev


def _payout(selection, rule, at, metadata):
    terms=rule.get('payout') or {}
    stake=selection.price.payout_unit=='usd_per_usd_stake'
    if stake:
        if terms.get('win_return')!='exact_original_decimal_odds' or selection.price.unit!='decimal_odds':
            raise ValueError('source_stake_payout_unit_unqualified')
        win=wire(selection.price.amount.value)
    elif terms.get('decisive_face')=='1':win='1'
    else:raise ValueError('source_decisive_payout_unit_unqualified')
    refs=tuple(EvidenceReference.from_dict(x) for x in rule.get('source_refs', []))
    if not refs:raise ValueError('source_payout_rule_provenance_missing')
    # This producer models only the explicitly conditioned completed result.
    # It does not create source timing, cancellation or refund rules.
    unknown=lambda why:PayoutCell(None,'unknown',why)
    status='estimated' if terms.get('authority')=='explicit_hypothesis' else 'evidenced'
    known=lambda v:PayoutCell(ExactNumber(v),status,
        'Explicit completed-result payout hypothesis' if status=='estimated' else None)
    pred=selection.predicate;below=known(win if pred.operator in ('lt','le') else '0')
    above=known(win if pred.operator in ('gt','ge') else '0')
    equal=unknown('Exact tie or push payout not established')
    if selection.family!='moneyline':
        equal=unknown('Equality infeasible on admitted integer score half-line')
    elif terms.get('equal') is not None:
        equal=known(terms['equal'])
    condition=NormalCondition('conditional_completed_result',None,None,None,None)
    value=PayoutProfile('ordinary-payout:'+digest(list(selection.native.key)),
        VERSION+':'+rule['id'],VERSION+':'+digest(rule),selection.native.key,selection_digest(selection),
        selection.price.payout_unit,rule.get('effective_from') or at.isoformat(),rule.get('effective_to') or rule.get('expires_at'),
        refs,below,equal,above,unknown('Exceptional noncompleted settlement remains source-local unknown'),
        'not_applicable',condition)
    completion=CompletionContext(None,None,'UTC',refs)
    bind_profile(selection,value,at=at,rule_revision=value.rule_revision,context=completion)
    return value,completion


def _fee(rule, q, at, metadata):
    payload=deepcopy(rule.get('fee_payload'))
    if not isinstance(payload,dict) or not isinstance(payload.get('rule'),dict):
        raise ValueError('applicable_fee_payload_missing')
    fee=CostRule.from_dict(payload['rule'])
    if fee.venue!=q['venue'] or fee.channel!=rule.get('fee_channel',fee.channel):
        raise ValueError('source_fee_channel_conflict')
    if fee.event_id not in (None,q['source']['native_event_id']) or fee.market_id not in (None,q['source']['native_market_id']):
        raise ValueError('source_fee_instrument_conflict')
    for end in (fee.effective_to,fee.expires_at):
        if end is not None and at>=instant(end):raise ValueError('source_fee_inputs_expired')
    if fee.effective_from is not None and at<instant(fee.effective_from):
        raise ValueError('source_fee_not_effective')
    if fee.terms is None or fee.terms.blockers() or not fee.mandatory_charges_known or fee.settlement_status not in ('declared_zero','known_terms'):
        raise ValueError('mandatory_source_fee_terms_unresolved')
    if payload.get('engine_context') is not None:
        engine=payload['engine_context']
        engine.update(venue=fee.venue,product=fee.product,channel=fee.channel,
            market_id=q['source']['native_market_id'],event_id=q['source']['native_event_id'],
            trade_time=at.isoformat(),calculation_time=at.isoformat())
        if fee.venue=='kalshi':
            series=metadata.get('series_id')
            if not isinstance(series,str) or not series:
                raise ValueError('source_series_fee_scope_missing')
            engine['series_id']=series
            material=engine.get('kalshi_metadata')
            if material is None and engine.get('model_fee_type') and engine.get('model_fee_multiplier'):
                material=dict(source='modeled:'+rule['id'],series_id=series,event_id=q['source']['native_event_id'],
                    event_history_complete=True,series_changes=[dict(scheduled_ts=rule['effective_from'],
                        fee_type=engine['model_fee_type'],fee_multiplier=engine['model_fee_multiplier'])],event_changes=[])
                engine['kalshi_metadata']=material
            if not isinstance(material,dict):raise ValueError('source_kalshi_fee_metadata_missing')
            material.update(series_id=series,event_id=q['source']['native_event_id'])
            for change in material.get('series_changes',[]):
                if change.get('scheduled_ts')=='calculation_time':change['scheduled_ts']=at.isoformat()
        elif 'kalshi_metadata' in engine:
            engine.pop('kalshi_metadata')
    return payload,fee


def _quantity(rule, q, fee):
    raw=deepcopy(rule.get('quantity_grid'))
    if not isinstance(raw,dict):raise ValueError('native_quantity_grid_missing')
    ev=EvidenceReference.from_dict(raw['evidence']) if raw.get('evidence') else None
    grid=QuantityGridInputs(**dict(raw,evidence=ev))
    if grid.minimum_native is None or grid.increment_native is None or grid.legal_price_tick is None:
        raise ValueError('native_quantity_grid_incomplete')
    minimum=Fraction(grid.minimum_native);increment=Fraction(grid.increment_native)
    if minimum<=0 or increment<=0:raise ValueError('native_quantity_grid_invalid')
    unit=fee if isinstance(fee,UnitSpec) else fee.unit
    if unit.unit in ('fixed_point_contracts','novig_v3_cent_contracts') and (
            minimum.denominator!=1 or increment.denominator!=1):
        raise ValueError('source_native_wire_quantity_grid_conflict')
    if unit.unit=='stake_usd':
        if (Fraction(q['original']['value'])/Fraction(grid.legal_price_tick)).denominator!=1:
            raise ValueError('source_price_off_legal_grid')
        return dict(grid=raw,fill_inputs=dict(basis='hypothetical_one_order',complete_order_history=True,
            fill_count=1,fragment_upper_bound=1,order_ids=['hyp:standalone']),
            fills=[dict(fill_id='hyp:single-stake',order_id='hyp:standalone',role='taker',unit='contracts',quantity='1',price='1')],
            native_price=q['original']['value'],fill_partition_basis='modeled_one_order_standalone',
            assumption='Modeled standalone USD stake grid; native ladder/quantity minimum not attested',
            grid_qualification=rule.get('quantity_grid_authority','modeled_stake_grid_not_native_ladder'))
    original=q['original'];value=Fraction(original['value'])/(100 if original['units']=='cents_per_contract' else 1)
    native=value*(Fraction(unit.price_scale) if unit.unit=='fixed_point_contracts' else 1)
    if Fraction(unit.probability_price(wire(native)))!=value:
        raise ValueError('source_native_price_unit_conflict')
    if (native/Fraction(grid.legal_price_tick)).denominator!=1:
        raise ValueError('source_price_off_legal_grid')
    return dict(grid=raw,fill_inputs=dict(basis='hypothetical_one_order',complete_order_history=True,
        fill_count=1,fragment_upper_bound=1,order_ids=['hyp:standalone']),
        fills=[dict(fill_id='hyp:single-fill',order_id='hyp:standalone',role='taker',unit='contracts',
            quantity='1',price=wire(value))],native_price=wire(native),
        fill_partition_basis='modeled_one_order_standalone',
        assumption='One modeled taker order/fill at displayed price; no observed execution or depth',
        grid_qualification=rule.get('quantity_grid_authority','source_rule_subset'))


def apply_selected(result,record,context,at):
    """Upgrade only individually qualified authentic facets; no global bypass."""
    q=context['quote'];registry=context.get('selected_applicability')
    try:_selection(record,context,Scope(record['market_identity']['period'],'included','conditional_completed_result'))
    except (ValueError,KeyError,TypeError,ArithmeticError):
        for kind in ('payout','fee','quantity'):
            result['gaps'][kind]=gap('contradictory','source_selected_native_attachment_conflict')
        return
    row,problem=selected_binding(q,registry,at)
    states,audit=selected_status(q,registry,at)
    if problem:
        result['gaps'].update(states)
        return
    if row is None:return
    result['gaps'].update(states)
    def add(kind,payload,refs):
        key,value=profile(kind,payload,expires_at=row['effective_until'])
        result['profiles'][key]=value;result['comparison_input_refs']['refs'][kind]=key
        result['gaps'][kind]=gap('available_and_bound','selected_'+kind+'_applicability_bound',refs)
        result['gaps'][kind]['binding_version']=row['binding_version']
    metadata=record.get('comparison_source_metadata') or {}
    from .public_retail import receiving_metadata
    metadata=receiving_metadata(record, q, metadata)
    # Independent legal units/grids never depend on a fee being available.
    for kind in ('quantity','fee','payout','phase'):
        if kind not in row.get('facets',{}):continue
        try:
            facet=_facet(row,kind,q);value=deepcopy(facet['value'])
            if q['provenance']['real_source'] and (not row.get('material_sha256') or
                    row['material_sha256']!=metadata.get('material_sha256')):
                raise ValueError('source_selected_material_revision_unqualified')
            if kind=='quantity':
                unit=UnitSpec(**value['unit'])
                retail=value.get('quantity_grid_authority')=='selected_public_retail_decimal_contracts'
                if q['venue']=='polymarket_us' and retail:
                    from .public_retail import quantity_authority
                    quantity_authority(metadata,q,unit,value)
                if q['venue']=='polymarket_us' and not retail and unit.unit!='fixed_point_contracts':
                    raise ValueError('source_selected_US_reference_scales_required')
                if q['venue']=='polymarket_us' and not retail and q['provenance']['real_source']:
                    refdata=metadata.get('selected_reference_data') or {}
                    raw=refdata.get('values') or {}
                    if not refdata.get('present') or refdata.get('instrument_id')!=q['source']['native_outcome_id'] or refdata.get('market_id')!=q['source']['native_market_id']:
                        raise ValueError('source_selected_US_refdata_attachment_unqualified')
                    expected=dict(priceScale=unit.price_scale,fractionalQtyScale=unit.quantity_scale,
                        minimumTradeQty=value['quantity_grid']['minimum_native'],tickSize=value['quantity_grid']['legal_price_tick'])
                    for field,number in expected.items():
                        actual=raw.get(field,1 if field=='fractionalQtyScale' else None)
                        if actual is None or Fraction(str(actual))!=Fraction(number):
                            raise ValueError('source_selected_US_refdata_grid_conflict')
                    if value['quantity_grid']['increment_native']!='1':
                        raise ValueError('source_selected_US_wire_quantity_increment_unqualified')
                payload=_quantity(value,q,unit)
                payload.update(unit=value['unit'],selected_binding=audit)
                add(kind,payload,facet['evidence'])
            elif kind=='fee':
                value.update(venue=q['venue'],fee_channel=value['fee_payload']['rule']['channel'])
                fee=CostRule.from_dict(value['fee_payload']['rule'])
                if (fee.market_id!=q['source']['native_market_id'] or fee.event_id!=q['source']['native_event_id'] or
                        fee.source_kind in ('research_proposal','controlled_scenario') and q['provenance']['real_source']):
                    raise ValueError('source_selected_fee_scope_unqualified')
                payload,_=_fee(value,q,at,metadata)
                if q['provenance']['real_source'] and q['venue']=='kalshi' and str(
                        payload.get('engine_context',{}).get('kalshi_metadata',{}).get('source','')).startswith('modeled:'):
                    raise ValueError('source_selected_Kalshi_fee_history_unqualified')
                payload['selected_binding']=audit
                add(kind,payload,facet['evidence'])
            elif kind=='payout':
                if q['provenance']['real_source'] and value.get('payout',{}).get('authority')!='selected_evidenced_terms':
                    raise ValueError('source_selected_payout_terms_authority_unqualified')
                value.update(id=row['binding_version'],effective_from=row['effective_from'],
                    effective_to=row['effective_until'],source_refs=facet['evidence'])
                scope=_scope(record,value,metadata)
                selected,ev=_selection(record,context,scope)
                payout,completion=_payout(selected,value,at,metadata)
                add('payout',payout.to_dict(),facet['evidence'])
                payload=dict(selection=selected.to_dict(),completion_context=completion.to_dict(),
                    rule_revision=payout.rule_revision,current_selection_binding=deepcopy(q['binding']['selection']),
                    current_scope_binding=dict(current_event_id=context['event']['id'],occurrence_id=selected.event.occurrence_id,
                        period_boundary=context['group']['period_boundary'],result_policy=context['group'].get('result_policy','unspecified'),
                        scope=selected.scope.to_dict(),evidence=[ev.to_dict()]),selected_binding=audit,
                    conditioning='completed_decisive_results_only',source_scope='provider_local_without_new_cross_source_merge')
                add('identity',payload,[ev.to_dict()])
                if not q['binding']['verified']:
                    result['gaps']['identity']=gap('applicability_unresolved','source_local_occurrence_scope_unqualified')
            else:
                if value not in ('pregame','live'):raise ValueError('source_selected_phase_unqualified')
                result['comparison_input_refs']['phase']=value
                result['gaps']['phase']=gap('available_and_bound','selected_source_phase_bound',facet['evidence'])
        except (ValueError,KeyError,TypeError,ArithmeticError) as error:
            code=str(error) if str(error).startswith(('source_','native_','mandatory_','integer_','applicable_')) else 'source_selected_'+kind+'_payload_invalid'
            result['gaps'][kind]=gap('applicability_unresolved',code)
    from .public_retail import direct_site_case
    case = direct_site_case(q, at)
    if case is not None and all(result['gaps'].get(k, {}).get('status') == 'available_and_bound'
            for k in ('quantity', 'payout')):
        add('fee', case, case['sources'])
        result['gaps']['fee'].update(status='applicability_unresolved',
            reason='direct_site_cost_case_modeled_total_charges_unverified', direct_site_case=case)
    # Unit disagreement is local to quantity; it cannot remove the fee or payout.
    refs=result['comparison_input_refs']['refs']
    if refs['quantity'] and refs['fee'] and result['gaps']['fee']['status']=='available_and_bound':
        units=result['profiles'][refs['quantity']]['payload'].get('unit')
        if units is not None and units!=result['profiles'][refs['fee']]['payload']['rule']['unit']:
            result['gaps']['quantity']=gap('contradictory','source_selected_fee_quantity_unit_conflict')


def _reference(record, context, selected, at):
    sharp=context['quote'].get('sharp_reference'); rows=context.get('reference_records')
    if not isinstance(sharp,dict):raise ValueError('exact_pinnacle_opposition_absent')
    if not isinstance(rows,list) or len(rows)!=2:raise ValueError('pinnacle_native_provenance_unbound')
    from app.collection.current_benchmark import key
    expected=record['market_identity']
    if any(r['quote']['venue']!='pinnacle' or r['market_identity']!=expected for r in rows):
        raise ValueError('pinnacle_market_scope_conflict')
    rows=sorted(rows,key=key)
    index=sharp['selected']
    if type(index) is not int or index not in (0,1) or key(rows[index])!=key(record):
        raise ValueError('pinnacle_selected_side_conflict')
    if sharp['odds'] != [r['quote']['original']['value'] for r in rows] or sharp['source_at'] != [r['quote']['times']['source_at'] for r in rows]:
        raise ValueError('pinnacle_original_input_conflict')
    if any(r['quote']['provenance']['sha256']!=sharp['sha256'] for r in rows):
        raise ValueError('pinnacle_receipt_provenance_conflict')
    grouped='declared-reference-group:'+digest(expected)
    outcomes=[];source_keys=[]
    for r in rows:
        q=r['quote'];s=q['source'];desc=r['selection'];side=desc['predicate'];participant=desc['participant']
        home=participant==selected.event.home_id
        if selected.family=='moneyline':
            if side!='win':raise ValueError('pinnacle_decisive_opposition_unqualified')
            pred=ScorePredicate('home_margin','gt' if home else 'lt',ExactNumber('0'));signed=None
        elif selected.family=='spread':
            signed=ExactNumber.parse(desc['signed_line'])
            pred=ScorePredicate('home_margin','gt' if home else 'lt',
                ExactNumber(str(-signed.value if home else signed.value)))
        else:
            participant='combined';signed=None
            pred=ScorePredicate('combined_score',{'over':'gt','under':'lt'}[side],selected.predicate.threshold)
        native=NativeProvenance('pinnacle',s['native_event_id'],grouped,s['native_outcome_id'],s['native_side'],
            desc['label'],(_evidence('admitted:pinnacle:'+s['native_market_id'],q['provenance']['sha256'],
                'authored' if q['provenance']['mode']=='synthetic' else 'retained'),))
        odds=ExactNumber.parse(q['original']['value'])
        target=replace(selected,participant_id=participant,signed_line=signed,predicate=pred,native=native,
            price=Price(odds,'decimal_odds','usd_per_usd_stake','USD'))
        clocks=q.get('provider_clocks',{})
        outcomes.append(ReferenceOutcome(target,odds,clocks.get('book',q['times']['source_at']),
            clocks.get('market'),q['times']['received_at'],str(q['revision'])+':'+q['provenance']['sha256']))
        source_keys.append(dict(native_key=list(_native_key(q)),source_at=q['times']['source_at'],
                                received_at=q['times']['received_at']))
    ref=ReferenceSet(tuple(outcomes),sharp['sha256'],'decisive_win_loss')
    return dict(outcomes=[x.to_dict() for x in ref.outcomes],receipt_sha256=ref.receipt_sha256,
        conditioning=ref.conditioning,partition_evidence_sha256=None,source_at=[x.source_at for x in ref.outcomes],
        original_source_keys=source_keys,grouping_authority='declared exact admitted market_identity; not provider-native market ID')


def produce(record, context, *, at):
    """Return profiles/refs and fact-level gaps for one ordinary admitted quote.

    context: event/group/outcome/quote from catalog_from_normalized, source_rules,
    optional two reference_records. Input data and source clocks are never edited.
    Missing facts yield null refs; malformed/crossed inputs refuse this quote only.
    """
    if not isinstance(at,datetime) or at.tzinfo is None or at.utcoffset().total_seconds()!=0:
        raise ValueError('source_input_aware_UTC_evaluation_required')
    result=dict(version=VERSION,profiles={},comparison_input_refs=dict(version=REFS_VERSION,
        refs={kind:None for kind in KINDS},phase='unknown'),gaps={kind:gap('absent',kind+'_source_inputs_absent') for kind in KINDS})
    def add(kind,payload,expires=None,evidence=()):
        key,value=profile(kind,payload,expires_at=expires)
        result['profiles'][key]=value;result['comparison_input_refs']['refs'][kind]=key
        result['gaps'][kind]=gap('available_and_bound',kind+'_source_inputs_bound',evidence)
    if not isinstance(record,dict) or not isinstance(context,dict):raise ValueError('source_input_objects_required')
    metadata=record.get('comparison_source_metadata') or {}
    if len(encoded(metadata))>32768:raise ValueError('source_metadata_capacity')
    public_tree(metadata)
    refdata=metadata.get('selected_reference_data')
    if isinstance(refdata,dict):
        fields=('priceScale','fractionalQtyScale','minimumTradeQty','tickSize')
        result['gaps']['quantity']=dict(gap('available_but_unbound' if refdata.get('present') else 'absent',
            'selected_reference_data_requires_reviewed_applicability' if refdata.get('present') else 'selected_reference_data_absent'),
            selected_reference_data=deepcopy(refdata),missing_fields=[field for field in fields if field not in refdata.get('values',{})])
    add('buffer',asdict(DEFAULT_POLICY))
    add('probability',dict(version='comparison-benchmark-basis-1',method='pinnacle_proportional_no_vig'))
    try:
        if metadata.get('native_key') is not None and tuple(metadata['native_key'])!=_native_key(record['quote']):
            raise ValueError('source_metadata_native_key_conflict')
        for end in ('effective_until','effective_to'):
            if metadata.get(end) is not None and at>=instant(metadata[end]):raise ValueError('source_metadata_expired')
        if metadata.get('effective_from') is not None and at<instant(metadata['effective_from']):
            raise ValueError('source_metadata_not_effective')
        result['comparison_input_refs']['phase']=_phase(record,metadata,at)
        result['gaps']['phase']=gap('available_and_bound' if result['comparison_input_refs']['phase']!='unknown' else 'applicability_unresolved',
            'scheduled_pregame_or_observed_phase' if result['comparison_input_refs']['phase']!='unknown' else 'source_phase_unknown')
        rule,problem=_rule(record,context.get('source_rules'),at)
        if problem:
            result['gaps']['fee']=deepcopy(problem)
            if problem['status']=='expired':
                result['gaps']['payout']=gap('expired','payout_source_rules_expired')
                result['gaps']['quantity']=gap('expired','quantity_source_rules_expired')
            else:
                result['gaps']['payout']=gap('applicability_unresolved','selected_instrument_payout_terms_unqualified')
                result['gaps']['quantity']=gap('absent','legal_minimum_increment_tick_unavailable')
        scope=_scope(record,rule,metadata)
        selected,ev=_selection(record,context,scope)
    except (ValueError,KeyError,TypeError,ArithmeticError) as error:
        reason=str(error)
        # Stable sanitized producer codes only, never copied provider/private text.
        code=reason if reason.startswith(('source_','ordinary_','integer_')) and len(reason)<100 else 'ordinary_source_semantic_inputs_invalid'
        status='expired' if 'expired' in code else 'applicability_unresolved' if 'scope_' in code or 'unqualified' in code else 'contradictory'
        result['gaps']['identity']=gap(status,code)
        # An unresolved semantic/payout scope must not erase an independently
        # selected legal grid or fee. Crossed attachments still refuse all upgrades.
        if code not in ('ordinary_source_native_attachment_conflict','ordinary_source_price_attachment_conflict',
                        'source_metadata_native_key_conflict','source_metadata_expired','source_metadata_not_effective'):
            apply_selected(result,record,context,at)
        if isinstance(refdata,dict):
            result['gaps']['quantity']['selected_reference_data']=deepcopy(refdata)
            result['gaps']['quantity']['missing_fields']=[field for field in fields if field not in refdata.get('values',{})]
        from .public_event import apply as apply_event
        apply_event(result,record,context,at)
        return result
    if rule is not None:
        try:
            payout,completion=_payout(selected,rule,at,metadata)
            add('payout',payout.to_dict(),rule.get('effective_to') or rule.get('expires_at'),[x.to_dict() for x in payout.source_evidence])
            identity=dict(selection=selected.to_dict(),completion_context=completion.to_dict(),rule_revision=payout.rule_revision,
                current_selection_binding=deepcopy(context['quote']['binding']['selection']),
                current_scope_binding=dict(current_event_id=context['event']['id'],occurrence_id=selected.event.occurrence_id,
                    period_boundary=context['group']['period_boundary'],result_policy=context['group'].get('result_policy','unspecified'),
                    scope=selected.scope.to_dict(),evidence=[ev.to_dict()]),
                conditioning='completed_decisive_results_only',source_scope='provider_local_without_new_cross_source_merge')
            add('identity',identity,rule.get('effective_to') or rule.get('expires_at'),[ev.to_dict()])
        except (ValueError,KeyError,TypeError,ArithmeticError):
            result['gaps']['payout']=gap('applicability_unresolved','source_decisive_payout_inputs_unqualified')
            result['gaps']['identity']=gap('available_but_unbound','identity_available_payout_condition_unbound',[ev.to_dict()])
        try:
            fee,fee_rule=_fee(rule,context['quote'],at,metadata)
            add('fee',fee,rule.get('effective_to') or rule.get('expires_at'))
        except (ValueError,KeyError,TypeError,ArithmeticError) as error:
            code=str(error) if str(error).startswith(('source_','mandatory_','applicable_')) else 'source_fee_payload_invalid'
            result['gaps']['fee']=gap('expired' if 'expired' in code else 'applicability_unresolved',code)
        else:
            try:add('quantity',_quantity(rule,context['quote'],fee_rule),rule.get('effective_to') or rule.get('expires_at'))
            except (ValueError,KeyError,TypeError,ArithmeticError) as error:
                code=str(error) if str(error).startswith(('source_','native_','aggregate_')) else 'source_quantity_payload_invalid'
                result['gaps']['quantity']=gap('applicability_unresolved',code)
    else:
        result['gaps']['identity']=gap('available_but_unbound','identity_available_rule_scope_unbound',[ev.to_dict()])
    try:add('reference',_reference(record,context,selected,at))
    except (ValueError,KeyError,TypeError,ArithmeticError) as error:
        code=str(error) if str(error).startswith(('pinnacle_','exact_')) else 'pinnacle_source_input_invalid'
        result['gaps']['reference']=gap('available_but_unbound' if context['quote'].get('sharp_reference') else 'absent',code)
    # A named scenario is useful in authored qualification. Real receipts do
    # not establish its execution channel, native legal grid or mandatory costs.
    # Keep the proposed profiles visible, but withhold dependent net outputs.
    if rule is not None and context['quote']['provenance']['real_source']:
        evidence=rule.get('local_blockers', [])
        for kind, reason in (('payout','selected_instrument_payout_terms_unqualified'),
                             ('fee','execution_channel_and_mandatory_charges_unqualified'),
                             ('quantity','native_legal_grid_applicability_unqualified')):
            if result['comparison_input_refs']['refs'][kind] is not None:
                result['gaps'][kind]=gap('applicability_unresolved',reason,evidence)
    apply_selected(result,record,context,at)
    if isinstance(refdata,dict):
        result['gaps']['quantity']['selected_reference_data']=deepcopy(refdata)
        result['gaps']['quantity']['missing_fields']=[field for field in fields if field not in refdata.get('values',{})]
    from .public_event import apply as apply_event
    apply_event(result,record,context,at)
    return result
