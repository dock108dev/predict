"""Shared funded single-trade evaluator without pair optimization or acquisition.

The fixed-allocation consumer owns charges and receipts. Search retains scalar
feasibility, then recalculates the chosen allocation. Exact rational state economics
precede display rounding and one deployed-capital haircut."""
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction

from .current_dependencies import digest, instant, references, link_reasons
from .costs import UnitSpec
from .domain import CanonicalSelection
from .estimated_content import describe, STATES as CONTENT_STATES
from .estimated_consumer import consume, _unit
from .estimated_policy import DEFAULT_POLICY, SCOPE, STATES, EstimateResult, probability_partition
from .net_costs import wire

VERSION = 'predict-funded-single-1'
MAX_PROBES = 64
MAX_NATIVE = Fraction(10**9)
MAX_LEVELS = 100
STATE_MAP = dict(zip(CONTENT_STATES, STATES))  # A is explicitly home, B away.


def cell(result, kind, name):
    value = result['components'][kind][name]['modeled_value']
    return None if value is None else Fraction(value)


def _scope(q, event, group, content, at):
    if event is None or group is None:
        raise ValueError('estimate_semantic_context_required')
    recipe = content['payout'].get('recipe', {})
    if (event['league'] != 'NFL' or group['market'] != 'winner' or group['period'] != 'full_game' or
            event.get('stage') not in (None, 'unknown', 'unverified', 'regular_season') or
            recipe.get('phase') != 'pregame' or q['comparison_input_refs']['phase'] != 'pregame' or
            recipe.get('overtime') == 'excluded'):
        raise ValueError('estimate_prior_scope_excluded')
    if at >= instant(event['start_at']):
        raise ValueError('estimate_prior_pregame_phase_ended')
    roles = {p['role']: p['id'] for p in event['participants']}
    selection = q['binding']['selection']
    if (not q['binding']['verified'] or selection['event_id'] != event['id'] or
            selection['group_id'] != group['id'] or recipe.get('home_id') != roles.get('home') or
            selection['participant'] not in (roles.get('home'), roles.get('away')) or
            selection['predicate'] not in ('win', 'not_win') or len(roles) != 2):
        raise ValueError('estimate_orientation_unresolved')
    assumptions = []
    if event.get('stage') in (None, 'unknown', 'unverified'):
        assumptions.append('regular_season assumed for this NFL model; actual stage unknown')
    if recipe.get('overtime') != 'included':
        assumptions.append('including overtime assumed; actual overtime scope unknown')
    return roles, assumptions


def _reference(q, values, roles, *, policy=None, benchmark=None, at=None):
    from .current_metrics import reference_set
    identity = values.get('identity', {}).get('payload', {})
    if identity.get('current_selection_binding') != q['binding']['selection']:
        raise ValueError('estimate_exact_identity_unbound')
    selected = CanonicalSelection.from_dict(identity['selection'])
    source = q['source']
    if (selected.event.league != 'NFL' or selected.event.home_id != roles['home'] or
            selected.event.away_id != roles['away'] or selected.scope.period != 'full_game' or
            selected.scope.overtime == 'excluded' or selected.family not in ('moneyline', 'team_binary') or
            selected.participant_id != q['binding']['selection']['participant'] or
            list(selected.native.key) != [q['venue'], *[source[k] for k in
                ('native_event_id', 'native_market_id', 'native_outcome_id', 'native_side')]]):
        raise ValueError('estimate_identity_orientation_conflict')
    if benchmark is not None:
        from .benchmark import resolve
        return resolve(benchmark, selected, policy, at, allow_last_known=getattr(policy, 'sizing_mode', None) is not None)
    ref = values.get('reference')
    if ref is None:
        raise ValueError('estimate_exact_pinnacle_reference_missing')
    payload = ref['payload']
    if payload.get('version') == 'comparison-two-way-benchmark-1':
        from .benchmark import resolve
        return resolve(payload,selected,policy,at,allow_last_known=getattr(policy, 'sizing_mode', None) is not None)
    if policy is not None and getattr(policy, 'benchmark_venue', 'pinnacle') != 'pinnacle':
        raise ValueError('selected_benchmark_missing; no substitution')
    from app.collection.current_comparison_inputs import PRODUCER_VERSION
    if payload.get('version') == PRODUCER_VERSION:
        payload = _ordinary_reference(q, payload, selected)
    reference = reference_set(payload)
    if len(reference.outcomes) != 2 or reference.conditioning != 'decisive_win_loss':
        raise ValueError('estimate_decisive_reference_required')
    by_role = {}
    for row in reference.outcomes:
        s = row.selection
        role = 'home' if s.participant_id == roles['home'] else 'away' if s.participant_id == roles['away'] else None
        if (role is None or role in by_role or s.event.key != selected.event.key or s.scope.key != selected.scope.key or
                s.predicate.domain != 'home_margin' or s.predicate.threshold.value != 0 or
                s.predicate.operator != ('gt' if role == 'home' else 'lt')):
            raise ValueError('estimate_reference_orientation_conflict')
        by_role[role] = Fraction(1) / row.decimal_odds.value
    weight = by_role['home'] / sum(by_role.values())
    return weight, reference


def _ordinary_reference(q, payload, selected):
    """Adapt admitted original opposition through the existing typed producer.

    Provider outcome IDs stay originals; the producer explicitly declares its
    exact market grouping. Unknown execution rules remain unknown on selection.
    """
    from .source_inputs import _reference as produce_reference
    rows = payload['outcomes']
    if (len(rows) != 2 or payload['current_selection_binding'] != q['binding']['selection'] or
            payload['receipt_sha256'] != q['sharp_reference']['sha256'] or
            payload['original_odds'] != q['sharp_reference']['odds'] or
            payload['source_at'] != q['sharp_reference']['source_at']):
        raise ValueError('estimate_ordinary_reference_attachment_conflict')
    records = []
    occurrence = q['occurrence_match']
    expected_market = deepcopy(occurrence['original_market_identity'])
    # An exact provider event is independent of optional native associations.
    # Keep the unresolved occurrence intact; qualify only these two originals.
    original = occurrence['original_event']
    if (q['source']['provider'] != 'the_odds_api' or
            original['id'] != q['source']['native_event_id'] or
            original['home'] != selected.event.home_id or original['away'] != selected.event.away_id or
            expected_market['period'] != 'full_game' or expected_market['family'] != 'moneyline'):
        raise ValueError('estimate_ordinary_reference_occurrence_unqualified')
    candidates = [expected_market]
    if occurrence['method'] == 'shared_provider_event' and occurrence['status'] == 'matched':
        resolved = deepcopy(expected_market)
        resolved['event'] = ['predict-occurrence-1', selected.event.league,
            occurrence['occurrence_id'], selected.event.home_id, selected.event.away_id, None]
        candidates.append(resolved)
    for row in rows:
        names=[name for name,participant in original['participants'].items() if participant==row['selection']['participant']]
        from app.dashboard.session_projection import stable
        if (len(names)!=1 or row['source']['native_outcome_id']!=names[0] or
                row['source']['native_market_id']!=stable([original['id'],'h2h',None,names[0]]) or
                row['source']['native_side']!='bookmaker_outcome' or row['selection']['signed_line'] is not None):
            raise ValueError('estimate_ordinary_reference_native_role_conflict')
        if (row['market_identity'] not in candidates or
                row['source']['native_event_id'] != q['source']['native_event_id'] or
                row['source']['provider'] != 'the_odds_api' or
                row['receipt_sha256'] != payload['receipt_sha256'] or
                row['received_at'] != payload['original_received_at'] or
                row['selection']['predicate'] != 'win' or
                row['selection']['participant'] not in (original['home'], original['away'])):
            raise ValueError('estimate_ordinary_reference_scope_conflict')
        records.append(dict(market_identity=row['market_identity'], selection=row['selection'],
            quote=dict(venue='pinnacle', source=row['source'], original=dict(value=row['decimal_odds']),
                times=dict(source_at=row['source_at'], received_at=row['received_at']),
                provider_clocks=row['provider_clocks'], revision=digest(row),
                provenance=dict(sha256=row['receipt_sha256'], mode='current'))))
    target = q['binding']['selection']
    matches = [r for r in records if all(r['selection'][k] == target[k]
        for k in ('participant', 'predicate', 'signed_line'))]
    if len(matches) != 1:
        raise ValueError('estimate_ordinary_reference_selection_conflict')
    return produce_reference(matches[0], dict(quote=q, reference_records=records), selected, None)


def eligibility(q, reference, at, event):
    """Availability and ranking are separate; no source clocks are renewed."""
    reasons = list(link_reasons(q, at))
    if q['state'] not in ('available', 'budget_delayed'):
        reasons.append('execution_source_unavailable')
    source = q['times']['source_at']; receipt = q['times']['received_at']
    if source is None or receipt is None:
        reasons.append('source_clock_unknown')
    elif instant(source) > instant(receipt) or instant(source) > at or instant(receipt) > at:
        reasons.append('source_clock_future')
    elif (at - instant(source)).total_seconds() > 900:
        reasons.append('source_price_expired')
    for row in reference.outcomes:
        if row.source_at is None:
            reasons.append('reference_source_clock_unknown')
        elif any(instant(c)>instant(row.received_at) or instant(c)>at for c in (row.book_at,row.market_at) if c is not None) or instant(row.received_at)>at:
            reasons.append('reference_clock_future')
        elif (at - instant(row.source_at)).total_seconds() > 1800:
            reasons.append('reference_expired')
    if at >= instant(event['start_at']):
        reasons.append('estimate_prior_pregame_phase_ended')
    return sorted(set(reasons))


def temporal(q, profiles, at, event):
    """Only eligibility boundaries affect clock-only reuse, never elapsed age."""
    values=references(q,profiles)
    rows=values.get('reference',{}).get('payload',{}).get('outcomes',[])
    def clock(source,receipt,limit):
        if source is None or receipt is None:return 'unknown'
        if instant(source)>instant(receipt):return 'future_at_receipt'
        if instant(source)>at or instant(receipt)>at:return 'future'
        return 'expired' if (at-instant(source)).total_seconds()>limit else 'current'
    result=[clock(q['times']['source_at'],q['times']['received_at'],900)]
    # Legacy reference payloads may carry only the original aggregate clocks.
    # Missing per-outcome authority remains unknown, rather than throwing during
    # aging/Stop or inventing a source/receipt timestamp.
    result.extend(clock(row.get('market_at') or row.get('book_at'),row.get('received_at'),1800) for row in rows)
    result.append(event is not None and at>=instant(event['start_at']))
    for kind in ('identity','reference','quantity'):
        profile=values.get(kind)
        result.append(None if profile is None else profile['expires_at'] is not None and at>=instant(profile['expires_at']))
    return result


def _grid(q, values, unit, content, at):
    profile = values.get('quantity')
    if profile is not None:
        status = q['comparison_input_status']['quantity']
        if profile['expires_at'] is not None and at >= instant(profile['expires_at']):
            raise ValueError('estimate_quantity_inputs_expired')
        payload = profile['payload']; grid = payload['grid']
        if payload.get('unit') is not None and UnitSpec(**payload['unit']) != unit:
            raise ValueError('estimate_quantity_unit_conflict')
        if status['status'] == 'available_and_bound' and grid.get('minimum_native') is not None and grid.get('increment_native') is not None:
            return dict(grid, qualification=payload.get('grid_qualification', 'bound_native_grid'))
        if status['status'] != 'available_and_bound' and not (status['status'] in ('available_but_unbound','applicability_unresolved','absent') and unit.unit == 'stake_usd' and
                q['source']['provider'] == 'the_odds_api' and q['original']['units'] == 'decimal_odds'):
            raise ValueError(status['reason'])
    meta = content['fee'].get('recipe', {}).get('metadata', {})
    retail = meta.get('selected_public_retail_data', {})
    scales = meta.get('selected_reference_data', {})
    if retail.get('minimumTradeQty') is not None:
        return dict(minimum_native=retail['minimumTradeQty'], increment_native=retail['minimumTradeQty'],
            legal_price_tick=retail.get('orderPriceMinTickSize'), qualification='selected_retail_decimal_grid')
    if scales.get('present') and scales.get('values', {}).get('minimumTradeQty') is not None:
        return dict(minimum_native=scales['values']['minimumTradeQty'], increment_native='1',
            legal_price_tick=scales['values'].get('tickSize'), qualification='selected_fixed_point_grid')
    quantum = '1' if unit.unit in ('fixed_point_contracts', 'novig_v3_cent_contracts') else '0.000001'
    return dict(minimum_native=quantum, increment_native=quantum, legal_price_tick=None,
        qualification='declared_grid_hypothetical; native minimum/increment/tick unknown')


def _path(q, unit, grid):
    """Observed quantities use original native units; stake ladders use USD.

    Source admission has already bounded/decorated depth. A caller cannot change
    its units by supplying a ladder with a different quote shape.
    """
    stake = unit.unit == 'stake_usd'
    scale = Fraction(unit.quantity_scale) if unit.unit == 'fixed_point_contracts' else 1
    base = Fraction(q['original']['value']) / (100 if q['original']['units'] == 'cents_per_contract' else 1)
    levels = q.get('depth') or []
    if not isinstance(levels, list) or len(levels) > MAX_LEVELS:
        raise ValueError('estimate_depth_level_bound')
    converted = []
    for row in levels:
        price = Fraction(row['price']) / (100 if q['original']['units'] == 'cents_per_contract' else 1)
        quantity = Fraction(row['quantity'])
        if quantity <= 0 or (price <= 1 if stake else not 0 < price < 1):
            raise ValueError('estimate_depth_units_conflict')
        if converted and (price > converted[-1][0] if stake else price < converted[-1][0]):
            raise ValueError('estimate_depth_price_path_not_ordered')
        converted.append((price, quantity))
    if (stake and base <= 1) or (not stake and not 0 < base < 1):
        raise ValueError('estimate_price_units_conflict')
    tick = grid.get('legal_price_tick')
    if tick is not None:
        for price in [base, *[p for p, n in converted]]:
            native_price = price * (Fraction(unit.price_scale) if unit.unit == 'fixed_point_contracts' else 1)
            # USD stake ticks in the old quantity profile describe the scenario's
            # probability grid, not decimal odds or an execution ladder.
            if not stake and (native_price / Fraction(tick)).denominator != 1:
                raise ValueError('estimate_price_off_legal_grid')
    per_native = Fraction(1) if stake else Fraction(unit.face_usd_per_native) / scale
    last = converted[-1][0] if converted else base
    minimum_cost = Fraction(1) if stake else min([base, *[p for p, n in converted]]) * per_native
    return dict(stake=stake, levels=converted, last=last, per_native=per_native, minimum_cost=minimum_cost)


def _fills(path, quantity, venue, *, residual_impact=Fraction(0)):
    remaining = quantity; result = []; supported = Fraction(0)
    for index, (price, size) in enumerate(path['levels']):
        amount = min(remaining, size)
        if amount:
            result.append((price, amount, 'observed_level', index)); supported += amount; remaining -= amount
        if not remaining:
            break
    if remaining:
        price = path['last']
        if residual_impact:
            price = price - residual_impact if path['stake'] else price + residual_impact
            if path['stake'] and price <= 1:
                raise ValueError('estimate_residual_odds_stress_out_of_domain')
            if not path['stake'] and price >= 1:
                raise ValueError('estimate_residual_price_stress_out_of_domain')
        result.append((price, remaining, 'modeled_residual', len(path['levels'])))
    order = 'model:ev05:single-order'
    if path['stake']:
        return dict(stake_fills=[dict(fill_id='ev05:'+str(i), order_id=order, stake_usd=wire(n),
            decimal_odds=wire(p), basis=b) for p, n, b, i in result]), supported
    fills = [dict(fill_id='ev05:'+str(i), order_id=order, role='taker',
        unit='novig_v3_contracts' if venue == 'novig' else 'contracts', price=wire(p),
        quantity=wire(n if venue == 'novig' else n*path['per_native']), event_status_at_match='OPEN_PREGAME')
        for p, n, b, i in result]
    return dict(fills=fills), supported


def _profits(component):
    capital = component['deployed_capital_usd']
    values = {}; rows = {}
    for state in CONTENT_STATES:
        parts = dict(receipt_usd=cell(component, 'payout', 'receipt_usd:'+state),
            returned_hold_usd=cell(component, 'payout', 'hold_return_usd:'+state),
            fee_refund_usd=cell(component, 'fee', 'fee_refund_usd:'+state),
            separately_payable_charge_usd=cell(component, 'fee', 'settlement_fee_usd:'+state))
        profit = None if capital is None or any(v is None for v in parts.values()) else (
            parts['receipt_usd']+parts['returned_hold_usd']+parts['fee_refund_usd']-
            Fraction(capital)-parts['separately_payable_charge_usd'])
        target = STATE_MAP[state]; values[target] = profit
        rows[target] = {k:None if v is None else wire(v) for k, v in parts.items()}
        rows[target].update(profit_usd=None if profit is None else wire(profit),
            receipt_charge_treatment='attached_net_receipt' if component['settlement_already_withheld'] else 'gross_receipt')
    return values, rows


def _expected(profits, probabilities):
    return None if any(profits[s] is None and p > 0 for s, p in probabilities.items()) else sum(
        (p*profits[s] for s, p in probabilities.items() if p > 0), Fraction(0))


def _refusal(q, policy, reason):
    value = dict(version=VERSION, model_available=False, ranking_eligible=False,
        conditioning='unavailable', reasons=[reason], quote_id=q['id'], quote_revision=q['revision'],
        policy_revision=policy.revision, buffered_profit_usd=None, buffered_return_percent=None)
    if getattr(policy,'sizing_mode',None) is not None:
        from .financial_metrics import unavailable
        unavailable(value,policy,reason)
    return dict(value, revision=digest(value))


def evaluate(q, profiles, *, at, event, group, policy=DEFAULT_POLICY, native_quantity=None,
             extra_funding=(), hold_returns_usd=None, state_cashflows=None,
             settlement_charge_already_withheld=False, details=False, supported_result=True, benchmark=None):
    """Size on the declared grid, or inspect an explicit fixed allocation.

    A fixed allocation never optimizes away a loss. All price/fill/state changes
    reenter consume. Buffer/prior sensitivities reuse the same state allocation.
    """
    try:
        if state_cashflows is not None and native_quantity is None:
            raise ValueError('estimate_absolute_cashflows_require_fixed_allocation')
        content = describe(q, profiles, at=at)
        for item in content.values():
            if not item['available']:
                raise ValueError('; '.join(item['reasons']) or 'estimate_content_unavailable')
        roles, scope_assumptions = _scope(q, event, group, content, at)
        values = references(q, profiles)
        for kind in ('identity','reference'):
            profile=values.get(kind)
            if profile is not None and profile['expires_at'] is not None and at>=instant(profile['expires_at']):
                raise ValueError('estimate_'+kind+'_inputs_expired')
        reference_reason = None
        try:
            weight, reference = _reference(q, values, roles, policy=policy, benchmark=benchmark, at=at)
            if getattr(policy, 'sizing_mode', None) is not None:
                ref_reasons = eligibility(q, reference, at, event)
                invalid = [v for v in ref_reasons if v.startswith('reference_') and v != 'reference_expired']
                if invalid:
                    raise ValueError('; '.join(invalid))
        except (ValueError, KeyError, TypeError) as error:
            if getattr(policy, 'sizing_mode', None) is None:
                raise
            weight, reference, reference_reason = None, None, str(error)
        rank_reasons = eligibility(q, reference, at, event) if reference is not None else eligibility(q, type('EmptyReference', (), {'outcomes': ()})(), at, event)
        if any('future' in r or 'clock_unknown' in r for r in rank_reasons):
            raise ValueError('; '.join(rank_reasons))
        if link_reasons(q, at):
            raise ValueError('; '.join(link_reasons(q, at)))
        unit = _unit(q, content['fee']); grid = _grid(q, values, unit, content, at)
        minimum, increment = Fraction(grid['minimum_native']), Fraction(grid['increment_native'])
        if minimum <= 0 or increment <= 0:
            raise ValueError('estimate_quantity_grid_invalid')
        if unit.unit in ('fixed_point_contracts', 'novig_v3_cent_contracts') and (minimum.denominator != 1 or increment.denominator != 1):
            raise ValueError('estimate_native_integer_grid_required')
        path = _path(q, unit, grid)
        from .current_metrics import calculation_instant
        evaluated_at = calculation_instant((q,), profiles, at)
        from .estimated_consumer import AllocationInputs
        allocation_inputs=AllocationInputs(q,profiles,evaluated_at)
        # Recipes must apply at the actual retained calculation boundary too.
        funding = dict(extra_funding=extra_funding, hold_returns_usd=hold_returns_usd,
            state_cashflows=state_cashflows, settlement_charge_already_withheld=settlement_charge_already_withheld)
        budget = Fraction(policy.capital_ceiling_usd); probes = 0
        def allocation(quantity, *, rich=False, impact=Fraction(0), cashflows=state_cashflows):
            nonlocal probes
            probes += 1
            fills, support = _fills(path, quantity, q['venue'], residual_impact=impact)
            result = consume(q, profiles, at=evaluated_at, native_quantity=wire(quantity),
                **fills, **dict(funding, state_cashflows=cashflows), retain_profiles=rich,_inputs=allocation_inputs)
            return result, fills, support
        def feasible(quantity):
            component, _, _ = allocation(quantity)
            capital = component['deployed_capital_usd']
            if capital is None:
                raise ValueError('; '.join(component['reasons']['fee']) or 'estimate_funding_unresolved')
            return Fraction(capital) <= budget, capital
        upper = min(MAX_NATIVE, budget/path['minimum_cost'])
        count = int((upper-minimum)//increment)
        search = dict(minimum_native=wire(minimum), increment_native=wire(increment),
            acquisition_upper_native=wire(upper), maximum_probes=MAX_PROBES,
            maximum_quantity_proven=False, limitation=None, next_grid_capital_usd=None,
            monotonic_basis='positive ordered acquisition plus existing nonnegative rounded/capped entry algebra')
        if native_quantity is not None:
            chosen = Fraction(native_quantity)
            if chosen < minimum or ((chosen-minimum)/increment).denominator != 1:
                raise ValueError('estimate_fixed_quantity_off_grid')
            ok, _ = feasible(chosen)
            if not ok:
                raise ValueError('estimate_fixed_allocation_exceeds_ceiling')
            search['limitation'] = 'explicit fixed allocation; maximum size not requested'
        else:
            if count < 0 or not feasible(minimum)[0]:
                raise ValueError('estimate_funded_ceiling_below_minimum')
            low, high, best = 0, count, 0
            while low <= high and probes < MAX_PROBES-2:
                middle = (low+high)//2
                if feasible(minimum+middle*increment)[0]:
                    best = middle; low = middle+1
                else:
                    high = middle-1
            chosen = minimum+best*increment
            if low <= high:
                search['limitation'] = 'bounded search exhausted; best feasible grid point only'
            elif upper == MAX_NATIVE and budget/path['minimum_cost'] > MAX_NATIVE:
                search['limitation'] = 'native search bound; largest quantity within bound only'
            else:
                next_ok, next_capital = feasible(chosen+increment)
                search['next_grid_capital_usd'] = next_capital
                search['maximum_quantity_proven'] = not next_ok
                if next_ok:
                    raise ValueError('estimate_maximum_grid_proof_failed')
        sizing_probes=probes
        component, fills, supported = allocation(chosen, rich=details)
        capital = Fraction(component['deployed_capital_usd'])
        if capital <= 0 or capital > budget:
            raise ValueError('estimate_funding_preservation_failure')
        profits, states = _profits(component)
        probabilities = None if weight is None else probability_partition(weight, scope=SCOPE, policy=policy)
        expected = None if probabilities is None else _expected(profits, probabilities)
        conditional_probabilities = None if weight is None else {'a_wins':weight, 'b_wins':1-weight}
        conditional = None if conditional_probabilities is None else _expected(profits, conditional_probabilities)
        conditioning = 'modeled_complete' if expected is not None else 'modeled_conditional' if conditional is not None else 'unavailable'
        profit = expected if expected is not None else conditional
        supported_component = None
        supported_capital = None
        if supported:
            supported_component, _, _ = allocation(supported)
            supported_capital = supported_component['deployed_capital_usd']
        separately_supported = None
        if supported_result and path['levels'] and supported < chosen:
            legal = minimum + ((supported-minimum)//increment)*increment if supported >= minimum else Fraction(0)
            if not legal:
                separately_supported = _refusal(q, policy, 'observed_depth_below_legal_minimum')
            elif state_cashflows is not None:
                separately_supported = _refusal(q, policy, 'supported_allocation_absolute_cashflows_require_separate_inputs')
            else:
                separately_supported = evaluate(q, profiles, at=at, event=event, group=group, policy=policy,
                    native_quantity=wire(legal), extra_funding=extra_funding, hold_returns_usd=hold_returns_usd,
                    settlement_charge_already_withheld=settlement_charge_already_withheld,
                    details=details, supported_result=False, benchmark=benchmark)
                if separately_supported.get('model_available'):
                    supported_capital = separately_supported['deployed_capital_usd']
                else:
                    supported_capital = None
        status = 'supported_size' if supported == chosen else 'modeled_size' if supported else 'size_unverified'
        typed = EstimateResult(policy, wire(capital), None if profit is None else wire(profit), conditioning,
            status, supported_capital)
        result = typed.to_dict()
        result.update(evaluator_version=VERSION, model_available=profit is not None,
            ranking_eligible=profit is not None and not rank_reasons, eligibility_reasons=rank_reasons,
            condition=None if expected is not None else 'decisive_home_or_away_win' if conditional is not None else None,
            conditional_probabilities=None if conditional_probabilities is None else {s:wire(p) for s,p in conditional_probabilities.items()},
            conditional_decisive_profit_usd=None if conditional is None else wire(conditional),
            probabilities=None if probabilities is None else {s:wire(p) for s,p in probabilities.items()}, states=states,
            missing_positive_probability_states=[] if probabilities is None else [s for s,p in probabilities.items() if p>0 and profits[s] is None],
            native_quantity=wire(chosen), native_unit=asdict(unit), supported_native_quantity=wire(supported),
            modeled_native_quantity=wire(chosen-supported), acquisition_usd=component['acquisition_usd'],
            net_entry_fee_usd=None if cell(component,'fee','net_entry_fee_usd') is None else wire(cell(component,'fee','net_entry_fee_usd')),
            size_search=dict(search, evaluations=sizing_probes), grid=grid,
            evaluated_at=evaluated_at.isoformat(), as_of_basis='last_known_inputs_evaluated_together' if rank_reasons else 'current_inputs_evaluated_together',
            actual_facts=dict(charges=None, settlement=None, execution_support=None,
                native_grid=grid['qualification'] if grid['qualification'] in ('bound_native_grid','selected_retail_decimal_grid','selected_fixed_point_grid','selected_public_retail_decimal_contracts') else None),
            assumptions=[*scope_assumptions, 'EV01 provisional priors; not calibrated NFL rates',
                'standalone taker direct-site funded model; actual additional mandatory charges unknown',
                'unknown fee refunds retained unless selected terms return them',
                'one declared order; hypothetical fills consume displayed levels in order',
                *(['residual size at last visible price; price impact unknown'] if supported<chosen else [])],
            prior_scope=list(SCOPE), orientation=dict(a_wins=roles['home'], b_wins=roles['away']),
            reasons=component['reasons'])
        # Allocation stays fixed for every buffer/prior/payout scenario. Payout
        # changes reenter the consumer because their commission bases change.
        sensitivity = dict(allocation='fixed_chosen_quantity_and_fills',
            buffer=[dict(rate=rate, profit_usd=None if profit is None else wire(profit-capital*Fraction(rate)))
                for rate in ('0','0.0025','0.005','0.01')], prior=[])
        for tie in ('0','0.01'):
            for terminal in ('0','0.005'):
                from dataclasses import replace
                prior = replace(policy, tie=tie, terminal_noncompletion=terminal)
                ev = None if weight is None else _expected(profits, probability_partition(weight, scope=SCOPE, policy=prior))
                sensitivity['prior'].append(dict(tie=tie, terminal_noncompletion=terminal,
                    buffered_profit_usd=None if ev is None else wire(ev-capital*Fraction(policy.buffer_rate))))
        if details:
            details_payout = component['profiles']
            from .shared_templates import resolve
            payout_details = resolve(details_payout, component['profile_refs']['payout'])['payload']['details']
        else:
            payout_details = component['payout_details']
        terminal_range = payout_details.get('terminal_range_usd')
        sensitivity['terminal_payout'] = []
        if terminal_range and state_cashflows is None:
            receipts = {s:component['components']['payout']['receipt_usd:'+s]['modeled_value'] for s in CONTENT_STATES}
            for receipt in terminal_range:
                altered, _, _ = allocation(chosen, cashflows=dict(receipts, terminal_noncompletion=receipt))
                stressed, _ = _profits(altered); ev = None if probabilities is None else _expected(stressed, probabilities)
                sensitivity['terminal_payout'].append(dict(receipt_usd=receipt,
                    buffered_profit_usd=None if ev is None else wire(ev-capital*Fraction(policy.buffer_rate))))
        sensitivity['residual_price_impact'] = None
        if supported < chosen:
            try:
                altered, _, _ = allocation(chosen, impact=Fraction('0.01'))
                stressed, _ = _profits(altered); ev = None if probabilities is None else _expected(stressed, probabilities)
                stress_capital = altered['deployed_capital_usd']
                sensitivity['residual_price_impact'] = dict(kind='repriced_fixed_quantity; no resizing',
                    impact='0.01', impact_unit='decimal_odds_decrease' if path['stake'] else 'USD_price_increase', deployed_capital_usd=stress_capital,
                    fits_ceiling=stress_capital is not None and Fraction(stress_capital)<=budget,
                    buffered_profit_usd=None if ev is None or stress_capital is None else wire(ev-Fraction(stress_capital)*Fraction(policy.buffer_rate)))
            except (ValueError, KeyError, TypeError, ArithmeticError) as error:
                sensitivity['residual_price_impact'] = dict(reason=str(error))
        sensitivity['legacy_adverse_price_stress'] = 'separate existing conservative metric; no automatic deduction'
        if supported_result:
            result['supported_size_evaluation'] = 'ev07-supported-1'
            if separately_supported is not None:
                result['supported_size_result'] = separately_supported if details else compact(separately_supported)
            result['material_note'] = ('Conditional on a home or away win; other settlement outcomes lack complete weights. '
                if conditioning == 'modeled_conditional' else 'Fees and provisional tie/completion payouts included. ') + (
                'Remaining size assumed at last visible price.' if status == 'modeled_size' else
                'Size unverified at the quoted price.' if status == 'size_unverified' else 'Observed levels cover this allocation.')
        result['sensitivity'] = sensitivity
        def weighted_column(name):
            entries={s:None if states[s][name] is None else Fraction(states[s][name]) for s in STATES}
            amount=None if probabilities is None else _expected(entries,probabilities)
            return None if amount is None else wire(amount)
        result['cost_breakdown']=dict(acquisition_usd=component['acquisition_usd'],net_upfront_fee_usd=result['net_entry_fee_usd'],
            refundable_holds_usd=wire(sum((Fraction(c.amount_usd) for c in extra_funding if c.kind=='refundable_hold'),Fraction(0))),
            consumed_allowances_usd=wire(sum((Fraction(c.amount_usd) for c in extra_funding if c.kind=='consumed_allowance'),Fraction(0))),
            expected_separately_payable_charge_usd=weighted_column('separately_payable_charge_usd'),
            expected_fee_refund_usd=weighted_column('fee_refund_usd'),buffer_usd=result['buffer_usd'],
            already_withheld_treatment='inside attached receipts; never deducted again')
        from app.dashboard.current_contract import exact_wire, display_decimal
        result['display'] = {k:None if result[k] is None else display_decimal(exact_wire(Fraction(result[k]))['decimal_approx'],2,True)
            for k in ('fee_adjusted_expected_profit_usd','buffered_profit_usd','buffered_return_percent')}
        dependencies = dict(evaluator=VERSION, quote=q['revision'], observation=component['dependencies']['observation'],
            occurrence=q.get('occurrence_match'), identity=q['binding'], native_contract=q.get('native_contract'),
            refs=q['comparison_input_refs'], reference=None if reference is None else reference.revision, policy=policy.to_dict(), prior_scope=list(SCOPE),
            content=component['dependencies']['content'], allocation=component['dependency_revision'],
            grid=grid, path=[(wire(p),wire(n)) for p,n in path['levels']], state=states,
            eligibility=rank_reasons, evaluated_at=evaluated_at.isoformat())
        result['dependency_revision'] = digest(dependencies)
        result['allocation_evaluations'] = probes
        if getattr(policy, 'sizing_mode', None) is not None:
            from .financial_metrics import single_metrics
            single_metrics(result, policy, reference, weight, component, unit, path, chosen, reference_reason, q)
        from .calculation_availability import frame
        result['evaluation_frame'] = frame((q,), reference, at)
        result['revision'] = digest({k:(compact(v) if k=='supported_size_result' else v) for k,v in result.items() if k != 'revision'})
        if details:
            result.update(dependencies=dependencies, components=component, fills=fills,
                extra_funding=[asdict(c) for c in extra_funding], source_times=deepcopy(q['times']),
                reference_inputs=[] if reference is None else [row.to_dict() for row in reference.outcomes])
        return result
    except (ValueError, KeyError, TypeError, ArithmeticError) as error:
        return _refusal(q, policy, str(error))


def compact(result):
    """Chosen-allocation shell; full inputs and sensitivities reopen in Details."""
    fields = ('version','evaluator_version','revision','dependency_revision','model_available','ranking_eligible',
        'conditioning','condition','eligibility_reasons','reasons','native_quantity','deployed_capital_usd',
        'unused_cash_usd','buffer_usd','fee_adjusted_expected_profit_usd','buffered_profit_usd',
        'unbuffered_return_percent','buffered_return_percent','size_status','supported_native_quantity',
        'modeled_native_quantity','supported_capital_usd','policy_revision','evaluated_at','as_of_basis','display',
        'supported_size_evaluation','supported_size_result','material_note','evaluation_frame')
    from .financial_metrics import SUCCESSOR_FIELDS
    fields += SUCCESSOR_FIELDS
    return {k:(compact(result[k]) if k=='supported_size_result' else result[k]) for k in fields if k in result}
