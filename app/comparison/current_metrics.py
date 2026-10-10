"""Typed DATA/SOFTWARE adapters for the existing current projection.

Only bound profiles produce net estimates. Ordinary unbound data keeps prices,
gross benchmarks and exact local refusal reasons. No account or network access.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

from .current_dependencies import eligibility, references, digest
from .domain import CanonicalSelection, ExactNumber, EvidenceReference
from .payouts import PayoutProfile, CompletionContext, bind_profile
from .costs import (CostRule, CostRequest, CostRegistry, VERSION as COST_VERSION, ComparisonCostPolicy,
                    QuantityGridInputs, FillInputs, DEFAULT_POLICY)
from .cashflows import cashflow_inputs, exact_wire
from .net_costs import calculate_net_costs
from .buffers import calculate_buffered_costs, DepthLeg, DepthLevel
from .costs import DepthInputs

VERSION = 'comparison-current-metrics-1'
MAX_SIZE_EVALUATIONS = 64
MAX_NATIVE_QUANTITY = 1000000


def state_labels(descriptors, event):
    """Readable labels from explicit state meaning, never from technical IDs."""
    participants={p['role']:p['name'] for p in (event or {}).get('participants',[])}
    home=participants.get('home','Home team');away=participants.get('away','Away team')
    labels={}
    for state in descriptors:
        bounds=state.get('score_range');domain=state.get('score_domain')
        label='Unknown state'
        if state['terminal']=='noncompleted':label='Game not completed'
        elif state['terminal']=='completed' and bounds:
            lower,upper=bounds['lower'],bounds['upper']
            if domain=='home_margin' and lower is None and upper==-1:label=away+' wins'
            elif domain=='home_margin' and lower==upper==0:label='Tie'
            elif domain=='home_margin' and lower==1 and upper is None:label=home+' wins'
            else:
                score={'home_margin':home+' score margin','combined_score':'Combined score',
                    'team_score':'Selected team score'}.get(domain,'Completed score')
                if lower==upper:label=score+' = '+str(lower)
                elif lower is None:label=score+' ≤ '+str(upper)
                elif upper is None:label=score+' ≥ '+str(lower)
                else:label=score+' '+str(lower)+' to '+str(upper)
        labels[state['state_id']]=label
    return labels


def gross_metric(natural):
    from app.dashboard.current_contract import exact_wire as metric_wire, display_decimal
    gross=natural.get('gross_decisive_benchmark') or {}
    value=gross.get('return_percent')
    exact=metric_wire(Fraction(value)) if gross.get('available') and value is not None else None
    return dict(eligible=exact is not None,exact=exact,value=None if exact is None else exact['decimal_approx'],
        display_value=None if exact is None else display_decimal(exact['decimal_approx'],2,True)+' %',
        reason=gross.get('reason'),label='gross decisive benchmark',details=deepcopy(gross))


def calculation_instant(quotes,profiles,current_at):
    """Stable input boundary; current eligibility is checked separately.

    Receipt/projected clocks describe evaluation inputs, never price freshness.
    Unchanged graphs retain their evaluation instant across clock-only ticks.
    """
    from .current_dependencies import instant
    times=[]
    for q in quotes:
        times.extend(instant(q['times'][field]) for field in ('received_at','projected_at') if q['times'][field] is not None)
        for kind,value in references(q,profiles).items():
            payload=value['payload'];intervals=[payload]
            if kind=='fee':
                intervals.append(payload.get('rule',{}))
                selected=payload.get('engine_context',{}).get('schedule_version')
                intervals.extend(s for s in payload.get('engine_registry',{}).get('schedules',[]) if s.get('version')==selected)
                metadata=payload.get('engine_context',{}).get('kalshi_metadata',{})
                times.extend(instant(change['scheduled_ts']) for kind in ('series_changes','event_changes')
                    for change in metadata.get(kind,[]) if change.get('scheduled_ts') is not None and
                    instant(change['scheduled_ts'])<=current_at)
            for interval in intervals:
                if interval.get('effective_from'):times.append(instant(interval['effective_from']))
            if kind=='reference':times.extend(instant(o['received_at']) for o in payload.get('outcomes',[]))
    return max(times)


def missing(q, reason, *, details=None):
    return dict(eligible=False, exact=None, value=None, display_value=None, reason=reason,
        estimate_class='unavailable', label='estimated net benchmark EV',
        basis=dict(conditioning=None, probability_basis=None,
            size_basis=dict(policy=DEFAULT_POLICY.version, ceiling_usd=DEFAULT_POLICY.ceiling_usd),
            fee_basis=None, capital_denominator=None,
            dependency_revisions=dict(quote=q['revision'], refs=deepcopy(q.get('comparison_input_refs')))),
        details=details or {})


def evidence(value):
    return None if value is None else EvidenceReference.from_dict(value)


def typed_quote(q, profiles, at, *, event=None, group=None, outcome=None):
    values = references(q, profiles)
    identity = values['identity']['payload']
    if identity.get('current_selection_binding') != q['binding']['selection']:
        raise ValueError('comparison_current_selection_attachment_conflict')
    selection = CanonicalSelection.from_dict(identity['selection'])
    if event is None or group is None or outcome is None:
        raise ValueError('comparison_current_semantic_context_required')
    association=identity.get('current_scope_binding')
    expected=dict(current_event_id=event['id'],occurrence_id=selection.event.occurrence_id,
        period_boundary=group['period_boundary'],result_policy=group.get('result_policy','unspecified'),
        scope=selection.scope.to_dict())
    if not isinstance(association,dict) or set(association)!={*expected,'evidence'} or any(
            association[k]!=v for k,v in expected.items()):
        raise ValueError('comparison_evidenced_occurrence_scope_attachment_required')
    provenance=tuple(EvidenceReference.from_dict(v) for v in association['evidence'])
    if not provenance or (q['provenance']['mode']!='synthetic' and all(p.evidence_class=='authored' for p in provenance)):
        raise ValueError('comparison_occurrence_scope_evidence_unqualified')
    roles={p['role']:p['id'] for p in event['participants']}
    if (selection.event.league!=event['league'] or selection.event.home_id!=roles.get('home') or
            selection.event.away_id!=roles.get('away') or selection.scope.period!=group['period'] or
            {'team_binary':'winner','moneyline':'winner','spread':'spread','total':'total'}.get(selection.family)!=group['market']):
        raise ValueError('comparison_current_market_scope_conflict')
    native_line=None if selection.signed_line is None else selection.signed_line.value
    displayed_line=None if outcome['signed_line'] is None else Fraction(outcome['signed_line'])
    if group['market']!='total' and native_line!=displayed_line:
        raise ValueError('comparison_current_signed_line_conflict')
    predicate=selection.predicate
    if group['market']=='winner':
        home=selection.participant_id==selection.event.home_id
        expected={'win':'gt' if home else 'lt','not_win':'le' if home else 'ge','draw':'eq'}.get(outcome['predicate'])
        if predicate.domain!='home_margin' or predicate.operator!=expected or predicate.threshold.value!=0:
            raise ValueError('comparison_current_predicate_conflict')
    elif group['market']=='spread' and (outcome['predicate']!='cover' or predicate.domain!='home_margin' or
            predicate.operator!=('gt' if selection.participant_id==selection.event.home_id else 'lt') or
            predicate.threshold.value!=(-native_line if selection.participant_id==selection.event.home_id else native_line)):
        raise ValueError('comparison_current_predicate_conflict')
    elif group['market']=='total' and (native_line is not None or displayed_line!=Fraction(group['line']) or
            predicate.domain!='combined_score' or
            predicate.operator!={'over':'gt','under':'lt'}.get(outcome['predicate']) or
            predicate.threshold.value!=Fraction(group['line'])):
        raise ValueError('comparison_current_predicate_conflict')
    source = q['source']
    native = selection.native
    if ((native.venue,native.event_id,native.market_id,native.instrument_id,native.side_id.lower()) !=
        (q['venue'],source['native_event_id'],source['native_market_id'],source['native_outcome_id'],source['native_side'].lower())):
        raise ValueError('comparison_native_selection_scope_conflict')
    original = q['original']
    if original['units'] != selection.price.unit:
        raise ValueError('comparison_native_price_unit_conflict')
    selection = replace(selection, price=replace(selection.price, amount=ExactNumber.parse(original['value'])))
    payout = PayoutProfile.from_dict(values['payout']['payload'])
    bound = bind_profile(selection, payout, at=at, rule_revision=identity['rule_revision'],
        context=CompletionContext.from_dict(identity['completion_context']))
    participant=None if group['market']=='total' and selection.participant_id=='combined' or (
        outcome['predicate']=='draw' and selection.participant_id=='tie') else selection.participant_id
    if participant != q['binding']['selection']['participant']:
        raise ValueError('comparison_current_participant_conflict')
    fee = values['fee']['payload']
    rule = CostRule.from_dict(fee['rule'])
    registry = CostRegistry(dict(schema=1,version=COST_VERSION, rules=[rule.to_dict()]))
    request = CostRequest(venue=rule.venue,product=rule.product,channel=rule.channel,
        trade_time=at.isoformat(),calculation_time=at.isoformat(),role='taker',portfolio_basis='standalone',
        market_id=native.market_id,event_id=native.event_id,series_id=rule.series_id or
            fee.get('engine_context',{}).get('series_id'),
        pinned_version=rule.version,allow_controlled_scenario=rule.source_kind=='controlled_scenario')
    quantity = deepcopy(values['quantity']['payload'])
    if rule.unit.unit != 'stake_usd':
        amount = selection.price.amount.value / (100 if selection.price.unit == 'cents_per_contract' else 1)
        if rule.unit.unit == 'fixed_point_contracts':amount *= Fraction(rule.unit.price_scale)
        quantity['native_price'] = exact_wire(amount)
    grid = QuantityGridInputs(**dict(quantity['grid'], evidence=evidence(quantity['grid']['evidence'])))
    fills = FillInputs(**dict(quantity['fill_inputs'], order_ids=tuple(quantity['fill_inputs']['order_ids'])))
    kwargs = dict(grid=grid, fill_inputs=fills, registry=registry)
    if fee.get('engine_registry') is not None:
        from app.fees.engine import Registry
        kwargs['engine_registry'] = Registry(fee['engine_registry'])
    if fee.get('engine_context') is not None:
        context = deepcopy(fee['engine_context'])
        context.update(trade_time=at.isoformat(),calculation_time=at.isoformat())
        kwargs['engine_context'] = context
    return bound, request, rule, quantity, kwargs, values


def depth_leg(q, rule, quantity, grid, native_key):
    value = quantity.get('depth')
    if value is None:return None
    info = DepthInputs(**dict(value['inputs'], evidence=evidence(value['inputs']['evidence'])))
    levels = None if value['levels'] is None else tuple(DepthLevel(**dict(row,
        evidence=evidence(row['evidence']))) for row in value['levels'])
    return DepthLeg(q['id'], rule.unit, grid, info, levels, value['partial_final'],value.get('exclusive_group'),native_key)


def _size(bound, request, rule, quantity, kwargs, at, ceiling, policy):
    """Bounded maximum native-grid size for disclosed single-order hypotheses.

    Observed fills and arbitrary fragment sets cannot be scaled to another size.
    They retain a precise local refusal rather than invented fill evidence.
    """
    grid = kwargs['grid']
    if grid.minimum_native is None or grid.increment_native is None:
        raise ValueError('quantity_grid_unavailable')
    minimum, increment = Fraction(grid.minimum_native), Fraction(grid.increment_native)
    templates = quantity['fills']
    if kwargs['fill_inputs'].basis not in ('authored_fills','hypothetical_one_order') or len(templates) != 1:
        raise ValueError('common_size_fill_allocation_unqualified')
    native_price = quantity['native_price']
    normalized = Fraction(rule.unit.probability_price(native_price)) if rule.unit.unit != 'stake_usd' else None
    quote_cost = bound.selection.price.amount.value / (100 if bound.selection.price.unit == 'cents_per_contract' else 1)
    if rule.unit.unit != 'stake_usd' and normalized != quote_cost:
        raise ValueError('native_quote_price_conversion_conflict')
    per_native = Fraction(1) if rule.unit.unit == 'stake_usd' else normalized * Fraction(rule.unit.dollar_face('1'))
    if per_native <= 0:raise ValueError('positive_native_acquisition_required')
    upper = min(Fraction(MAX_NATIVE_QUANTITY), Fraction(ceiling)/per_native)
    count = max(-1, (upper-minimum)//increment)
    evaluations = 0
    from .buffers import adverse_price
    movement = adverse_price(rule.unit,grid,native_price,policy=policy)
    stressed_bound = None
    if movement['available'] and bound.selection.price.unit in {'usd_per_contract','cents_per_contract'}:
        stressed_selection = replace(bound.selection,price=replace(bound.selection.price,
            amount=ExactNumber(exact_wire(Fraction(movement['adverse_normalized_price']) *
                (100 if bound.selection.price.unit == 'cents_per_contract' else 1)))))
        stressed_bound = bind_profile(stressed_selection,bound.profile,at=at,
            rule_revision=bound.profile.rule_revision,context=bound.context)
    def evaluate(index):
        nonlocal evaluations
        evaluations += 1
        native = exact_wire(minimum + index*increment)
        face = native if rule.unit.unit == 'stake_usd' else rule.unit.dollar_face(native)
        scenario = cashflow_inputs((bound,), (face,), at=at)
        fills = deepcopy(templates)
        for row in fills:
            row['quantity'] = native if row.get('unit') == 'novig_v3_contracts' else face
        costs = calculate_net_costs(request, scenario, native_quantity=native, native_price=native_price,
            fills=fills, ceiling_usd=ceiling, **kwargs)
        costs['_size_required_capital'] = None if costs['capital'] is None else costs['capital']['deployed_capital_usd']
        if stressed_bound is not None:
            stressed_scenario = cashflow_inputs((stressed_bound,), (face,),at=at)
            stress_fills=deepcopy(fills)
            for row in stress_fills:row['price']=movement['adverse_normalized_price']
            stress_costs=calculate_net_costs(request,stressed_scenario,native_quantity=native,
                native_price=movement['adverse_native_price'],fills=stress_fills,ceiling_usd=ceiling,**kwargs)
            if stress_costs['capital'] is not None and costs['capital'] is not None:
                costs['_size_required_capital']=exact_wire(max(Fraction(costs['_size_required_capital']),
                    Fraction(stress_costs['capital']['deployed_capital_usd'])))
        return native, fills, scenario, costs
    if count < 0:raise ValueError('capital_ceiling_below_native_minimum')
    first = evaluate(0)
    if not first[3]['entry_available']:
        first[3].pop('_size_required_capital',None)
        return (*first,evaluations,False)
    if first[3]['_size_required_capital'] is None or Fraction(first[3]['_size_required_capital'])>Fraction(ceiling):
        raise ValueError('capital_ceiling_below_adverse_funded_native_minimum')
    low, high, best = 0, int(count), first
    while low <= high and evaluations < MAX_SIZE_EVALUATIONS:
        middle = (low+high)//2
        result = evaluate(middle)
        capital = result[3]['capital']
        funded = capital is not None and Fraction(result[3]['_size_required_capital']) <= Fraction(ceiling)
        if funded and result[3]['entry_available']:
            best = result
            low = middle+1
        else:high = middle-1
    cap_partial = upper == MAX_NATIVE_QUANTITY and Fraction(ceiling)/per_native > MAX_NATIVE_QUANTITY
    best[3].pop('_size_required_capital',None)
    return (*best,evaluations,low>high and not cap_partial)


def reference_set(value):
    from .pinnacle import ReferenceOutcome, ReferenceSet
    outcomes = tuple(ReferenceOutcome(selection=CanonicalSelection.from_dict(row['selection']),
        decimal_odds=ExactNumber.parse(row['decimal_odds']),book_at=row['book_at'],market_at=row['market_at'],
        received_at=row['received_at'],revision=row['revision']) for row in value['outcomes'])
    result = ReferenceSet(outcomes,value['receipt_sha256'],value['conditioning'],value.get('partition_evidence_sha256'))
    if value['source_at'] != [row.source_at for row in outcomes]:
        raise ValueError('reference_original_clock_association_conflict')
    return result


def calculate_quote(q, profiles, at, *, ceiling=None, event=None, group=None, outcome=None):
    values=references(q,profiles)
    independent=values.get('probability',{}).get('payload',{}).get('version')=='comparison-state-probabilities-1'
    kinds=('identity','payout','fee','quantity','buffer','probability') if independent else (
        'identity','payout','reference','fee','quantity','buffer','probability')
    reasons = list(eligibility(q,profiles,at,kinds=kinds))
    if q['state'] != 'available' and not (q['source']['provider']=='the_odds_api' and q['state']=='budget_delayed'):reasons.append('execution_source_unavailable')
    if not q['binding']['verified']:reasons.append('selection_binding_unverified')
    if reasons:
        details=dict(input_status=deepcopy(q.get('comparison_input_status',{})),
            bound_input_kinds=sorted(values),input_revisions=deepcopy(q.get('comparison_input_refs')))
        return missing(q,'; '.join(reasons),details=details), missing(q,'; '.join(reasons),details=details)
    try:
        at=calculation_instant((q,),profiles,at)
        bound, request, rule, quantity, kwargs, values = typed_quote(q,profiles,at,event=event,group=group,outcome=outcome)
        size = ceiling or DEFAULT_POLICY.ceiling_usd
        if Fraction(size) <= 0 or Fraction(size) > 100000:
            raise ValueError('comparison_ceiling_outside_bounds')
        policy = replace(ComparisonCostPolicy(**values['buffer']['payload']),ceiling_usd=size)
        native, fills, scenario, costs, evaluations, complete = _size(bound,request,rule,quantity,kwargs,at,size,policy)
        details = dict(costs=costs,scenario=scenario.to_dict(),size_evaluations=evaluations,
            maximum_quantity_proven=complete,native_quantity=native,unused_ceiling_usd=None,
            fill_basis=kwargs['fill_inputs'].basis,fill_partition_basis=quantity.get('fill_partition_basis'))
        if not costs['available']:return missing(q,'; '.join(costs['reasons']),details=details), missing(q,'cost_inputs_unavailable')
        if not complete:return missing(q,'maximum_common_size_not_proven',details=details),missing(q,'maximum_common_size_not_proven')
        depth = depth_leg(q,rule,quantity,kwargs['grid'],bound.selection.native.key)
        buffer = calculate_buffered_costs(bound,request,unit=rule.unit,native_quantity=native,
            native_price=quantity['native_price'],fills=fills,original_source_clock=q['times']['source_at'],
            phase=q['comparison_input_refs']['phase'],depth_leg=depth,policy=policy,**kwargs)
        from .net_ev import estimated_net_ev, ProbabilityInputs
        reference = reference_set(values['reference']['payload']) if 'reference' in values else None
        probability_policy = values['probability']['payload']
        probability = None if probability_policy == {'version':'comparison-benchmark-basis-1',
            'method':'pinnacle_proportional_no_vig'} else ProbabilityInputs.from_dict(probability_policy)
        natural = estimated_net_ev(scenario,costs,reference,at=at,
            live=q['comparison_input_refs']['phase']=='live',execution_source_at=q['times']['source_at'],
            probability=probability,buffer=buffer)
        result = adapt_ev(natural,q,size,rule,values,details)
        result['details']['state_labels']=state_labels([dict(s,
            score_domain=bound.selection.predicate.domain) for s in scenario.to_dict()['states']],event)
        stress = buffer.get('conservative')
        conservative = missing(q,'; '.join(buffer.get('reasons',[])) or 'depth_qualified_conservative_unavailable',details=buffer)
        if stress is not None and buffer.get('depth_qualified_ranking_available'):
            changed=replace(bound.selection,price=replace(bound.selection.price,
                amount=ExactNumber(exact_wire(Fraction(buffer['movement']['adverse_normalized_price']) *
                    (100 if bound.selection.price.unit == 'cents_per_contract' else 1)))))
            rebuilt=bind_profile(changed,bound.profile,at=at,rule_revision=bound.profile.rule_revision,context=bound.context)
            stress_scenario=cashflow_inputs((rebuilt,),(scenario.legs[0].quantity,),at=at)
            stress_natural = estimated_net_ev(stress_scenario,stress,reference,at=at,
                live=q['comparison_input_refs']['phase']=='live',execution_source_at=q['times']['source_at'],
                probability=probability,buffer=buffer,funded_denominator=buffer['sensitivity']['denominator_usd'])
            conservative = adapt_ev(stress_natural,q,size,rule,values,dict(buffer=buffer))
            conservative['details']['state_labels']=deepcopy(result['details']['state_labels'])
            base_sensitivity=estimated_net_ev(scenario,costs,reference,at=at,
                live=q['comparison_input_refs']['phase']=='live',execution_source_at=q['times']['source_at'],
                probability=probability,buffer=buffer,funded_denominator=buffer['sensitivity']['denominator_usd'])
            conservative['details']['paired_base']=base_sensitivity
        result['details']['buffer'] = buffer
        result['details']['quantity_grid']=deepcopy(quantity.get('grid'))
        result['details']['quantity_grid_qualification']=quantity.get('grid_qualification')
        result['details']['source_input_status']=deepcopy(q.get('comparison_input_status',{}))
        if rule.source_kind=='controlled_scenario':
            result['label']='hypothetical net benchmark EV'
            result['estimate_class']='named_fee_and_grid_hypothesis'
            result['details']['fee_qualification']='Named fee/channel scenario; actual account applicability is not attested'
            result['basis']['fee_basis']['version']=rule.version
        result['details']['unused_ceiling_usd'] = exact_wire(Fraction(size)-Fraction(costs['capital']['deployed_capital_usd']))
        return result,conservative
    except (ValueError,KeyError,TypeError,ArithmeticError) as error:
        return missing(q,str(error)),missing(q,str(error))


def adapt_ev(natural,q,ceiling,rule,values,details):
    from app.dashboard.current_contract import display_decimal
    if not natural.get('available'):
        result=missing(q,natural.get('reason') or '; '.join(natural.get('reasons',[])) or 'net_inputs_unavailable',
            details=dict(natural=deepcopy(natural),gross_decisive_benchmark=gross_metric(natural)))
        return result
    exact = natural['exact']
    percent = Fraction(int(exact['numerator']),int(exact['denominator']))
    # Decimal approximation is for display only, exact fractions rank the metric.
    from app.dashboard.current_contract import exact_wire as metric_wire
    wire = metric_wire(percent)
    result = dict(eligible=natural.get('ranking_eligible',True),exact=wire,value=wire['decimal_approx'],
        display_value=display_decimal(wire['decimal_approx'],2,True)+' %',reason=natural.get('reason'),
            label=natural.get('label','estimated net benchmark EV'),estimate_class=natural.get('estimate_class','hypothetical_net_benchmark'),
        basis=dict(conditioning=natural['conditioning'],probability_basis=natural['probability_basis'],
            size_basis=dict(policy=values['buffer']['payload']['version'],
                policy_revision=replace(ComparisonCostPolicy(**values['buffer']['payload']),ceiling_usd=ceiling).revision,
                ceiling_usd=ceiling,role='taker',portfolio='standalone'),
        fee_basis=dict(scope='standalone',role='taker',qualification=rule.source_kind),
            capital_denominator=natural['capital_denominator'],
            dependency_revisions=dict(quote=q['revision'],profiles={k:digest(v) for k,v in values.items()},
                calculation=natural.get('dependency_revisions'))),
        details=dict(details,natural=natural))
    cost=details.get('costs',{})
    result['details'].update(expected_profit_usd=natural['expected_profit_usd'],
        state_costs=deepcopy(cost.get('states',natural.get('details',{}).get('state_costs'))),
        capital=deepcopy(cost.get('capital',natural.get('details',{}).get('capital'))),
        acquisition_usd=cost.get('acquisition_usd'),entry_fee_usd=cost.get('entry_fee_usd'),
        net_entry_fee_usd=cost.get('net_entry_fee_usd'),rounding_refund_usd=cost.get('rounding_refund_usd'),
        reference=deepcopy(natural.get('details',{}).get('reference')),
        gross_decisive_benchmark=gross_metric(natural),
        buffer_reasons=deepcopy(details.get('buffer',{}).get('reasons',[])))
    result['depth_qualified']=natural.get('depth_qualified',False)
    reference=result['details'].get('reference')
    if reference and reference.get('original_odds'):
        reference['opposing_odds']=reference['original_odds'][1-reference['selected_index']]
        reference['original_clocks']=[v['selected'] for v in reference['source_clocks']]
    return result


def calculate_group_pairs(group, profiles, at, *, ceiling=None, event=None):
    """Bounded S05 consumer. Reference/probability inputs never gate arbs."""
    from app.dashboard.current_contract import quotes_of, exact_wire as metric_wire, display_decimal
    from .net_arbs import ArbLeg, ArbLimits, search_arbs
    required=('identity','payout','fee','quantity','buffer')
    candidates=[];quotes={};labels={};diagnostics=[];policies=set()
    for outcome in group['outcomes']:
        for quote in quotes_of(outcome):
            reasons=list(eligibility(quote,profiles,at,kinds=required))
            if quote['state']!='available':reasons.append('execution_source_unavailable')
            if not quote['binding']['verified']:reasons.append('selection_binding_unverified')
            if reasons:
                diagnostics.append(dict(quote_id=quote['id'],reasons=reasons));continue
            try:
                bound,request,rule,quantity,kwargs,values=typed_quote(quote,profiles,
                    calculation_instant((quote,),profiles,at),event=event,group=group,outcome=outcome)
                policy=replace(ComparisonCostPolicy(**values['buffer']['payload']),
                    ceiling_usd=ceiling or DEFAULT_POLICY.ceiling_usd)
                depth=depth_leg(quote,rule,quantity,kwargs.pop('grid'),bound.selection.native.key)
                kwargs.pop('fill_inputs')
                if depth is None:raise ValueError('arb_depth_inputs_unavailable')
                candidates.append(ArbLeg(bound,depth,request,kwargs,quote['times']['source_at'],
                    quote['comparison_input_refs']['phase'],quantity.get('fill_partition_basis')))
                policies.add(policy.revision)
                quotes[bound.selection.native.key]=quote
                labels[bound.selection.native.key]=outcome['label']
            except (ValueError,KeyError,TypeError,ArithmeticError) as error:
                diagnostics.append(dict(quote_id=quote['id'],reasons=[str(error)]))
    if len(policies)>1:
        return [],dict(version='comparison-current-arbs-1',limits=ArbLimits().to_dict(),
            reasons=['incomparable_buffer_policies'],diagnostics=diagnostics,results=0)
    evaluated_at=calculation_instant(tuple(quotes.values()),profiles,at) if candidates else at
    search=search_arbs(tuple(candidates),at=evaluated_at,limits=ArbLimits(),
        policy=policy if candidates else replace(DEFAULT_POLICY,ceiling_usd=ceiling or DEFAULT_POLICY.ceiling_usd))
    pairs=[]
    for result in search['results']:
        readable=state_labels(result['state_descriptors'],event)
        keys=tuple(tuple(k) for k in result['native_keys'])
        legs=[dict(quote_id=quotes[k]['id'],revision=quotes[k]['revision'],venue=k[0],
            native_key=list(k),selection=labels[k],native_side=quotes[k]['source']['native_side'],
            odds=quotes[k]['display']['american'],
            quantity=result['native_quantities'][index]) for index,k in enumerate(keys)]
        value=result['minimum_return_percent'];exact=None if value is None else metric_wire(Fraction(value))
        metric=dict(eligible=result['available'] and exact is not None,exact=exact,
            value=None if exact is None else exact['decimal_approx'],
            display_value=None if exact is None else display_decimal(exact['decimal_approx'],2,True)+' %',
            reason='; '.join(result['reasons']) or None,label='buffered minimum return',
            estimate_class=result['estimate_class'],basis=dict(conditioning=result['conditioning'],
                size_basis='best evaluated fixed allocation',capital_denominator=result['denominator_usd'],
                dependency_revisions=result['dependency_revisions']),details=deepcopy(result))
        details=dict(deepcopy(result),state_labels=readable)
        pairs.append(dict(id=result['opportunity_id'],revision=result['revision'],legs=legs,
            category=result['category'],limiting_states=result['limiting_states'],state_labels=readable,
            limiting_state_labels=[readable[s] for s in result['limiting_states']],truncated=search['truncated'],
            gross=deepcopy(result['gross']),buffered_minimum_return=metric,details=details))
    summary={k:deepcopy(v) for k,v in search.items() if k!='results'}
    summary['diagnostics']=[*diagnostics,*summary['diagnostics']]
    return pairs,summary


def apply_group_metrics(group, profiles, at, *, event=None, ceiling=None):
    """Assemble the same current metrics for admission and optional-size reads.

    Mutates only the caller-owned group. Engines retain their distinct gross,
    modeled, net and depth contracts; this boundary owns their placement.
    """
    from app.dashboard.current_contract import quotes_of
    from .public_retail import direct_site_estimate
    size = DEFAULT_POLICY.ceiling_usd if ceiling is None else ceiling
    for outcome in group['outcomes']:
        for quote in quotes_of(outcome):
            quote['calculations']['net_ev'],quote['calculations']['conservative']=calculate_quote(
                quote,profiles,at,ceiling=size,event=event,group=group,outcome=outcome)
            quote['calculations']['direct_site_estimate']=direct_site_estimate(quote,profiles,at,size)
    group['comparison_pairs'],group['comparison_search']=calculate_group_pairs(
        group,profiles,at,ceiling=size,event=event)
