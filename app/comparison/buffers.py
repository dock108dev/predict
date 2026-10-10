"""Reviewed adverse-price/age/depth gates over fixed comparison allocations.

No acquisition or account access. Existing depth owns liquidity consumption;
S02 owns all fee, capital and net cashflow arithmetic. Smaller supported depth
is a separately named size sensitivity, never the common ranking size.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Context, Decimal, localcontext, ROUND_CEILING
from fractions import Fraction
from math import gcd

from app.comparison.costs import DEFAULT_POLICY, DepthInputs, QuantityGridInputs, UnitSpec
from app.comparison.domain import EvidenceReference, ExactNumber
from app.depth import explicit_allocation
from app.fees.engine import digest, number


VERSION = "comparison-buffers-1"
ZERO = Decimal("0")


def _instant(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timezone-aware original source/calculation clock required")
    return value


def _exact(value):
    return ExactNumber.parse(value).value


def _wire(value):
    """Preserve an exact rational, including nonterminating percentages."""
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def age_gate(original_source_clock, *, phase, at, policy=DEFAULT_POLICY):
    """Only the original price clock can admit the future net path."""
    now = _instant(at)
    limit = policy.live_age_seconds if phase == "live" else policy.pregame_age_seconds
    if phase not in {"pregame", "live"}:
        reasons = ["comparison_phase_unknown"]
        age = None
    elif original_source_clock is None:
        reasons = ["source_quote_age_unknown"]
        age = None
    else:
        try:
            source = _instant(original_source_clock)
        except (ValueError, TypeError):
            source = None
        if source is None:
            age = None
            reasons = ["source_quote_age_unknown"]
        else:
            delta = now - source
            age = Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 1000000)
            reasons = (["source_quote_clock_future"] if age < 0 else
                       ["source_quote_too_old_for_future_net"] if age > limit else [])
    return dict(version=VERSION, eligible=not reasons, reasons=reasons,
                age_seconds=None if age is None else _wire(age), limit_seconds=limit,
                original_source_clock=original_source_clock.isoformat() if isinstance(original_source_clock, datetime) else original_source_clock,
                at=now.isoformat(), policy_revision=policy.revision,
                clock_basis="original_price_source_clock", gross_pinnacle_age_seconds=1800)


def adverse_price(unit: UnitSpec, grid: QuantityGridInputs, native_price, *, policy=DEFAULT_POLICY):
    """Reprice on the evidenced native zero-origin legal tick grid.

    Fixed-point tick and price are original wire integers. Dollar-face and
    Novig prices are normalized acquisition dollars per dollar face. A stake
    odds grid has no evidenced conversion in this contract and declines here.
    """
    if not isinstance(unit, UnitSpec) or not isinstance(grid, QuantityGridInputs):
        raise ValueError("typed native unit and legal grid required")
    result = dict(version=VERSION, available=False, native_price=native_price,
                  adverse_native_price=None, normalized_price=None,
                  adverse_normalized_price=None, movement_per_dollar_face=None,
                  policy_revision=policy.revision, reasons=[])
    if unit.unit == "stake_usd":
        result["reasons"].append("stake_price_payout_legal_grid_conversion_unavailable")
        return result
    if grid.legal_price_tick is None:
        result["reasons"].append("legal_price_grid_unknown")
        return result
    with localcontext(Context(prec=100)):
        price = Decimal(unit.probability_price(native_price))
        tick = number(grid.legal_price_tick)
        scale = Decimal(unit.price_scale) if unit.unit == "fixed_point_contracts" else Decimal(1)
        if unit.unit == "fixed_point_contracts" and tick != tick.to_integral_value():
            result["reasons"].append("fixed_point_legal_tick_not_wire_integer")
            return result
        tick /= scale
        result["normalized_price"] = str(price)
        if tick >= 1:
            result["reasons"].append("legal_price_grid_outside_acquisition_domain")
            return result
        if price % tick:
            result["reasons"].append("observed_price_off_legal_grid")
            return result
        movement = max(tick, number(policy.adverse_price_per_dollar_face))
        stressed = ((price + movement) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        if stressed >= 1:
            result["reasons"].append("adverse_legal_price_impossible")
            return result
        result.update(available=True, adverse_native_price=str(stressed * scale),
                      adverse_normalized_price=str(stressed),
                      movement_per_dollar_face=str(stressed - price),
                      legal_tick_per_dollar_face=str(tick),
                      assumption="adverse acquisition stress; no fill assurance")
    return result


@dataclass(frozen=True)
class DepthLevel:
    native_price: str
    available_native: str
    liquidity_id: str
    evidence: EvidenceReference

    def __post_init__(self):
        number(self.native_price)
        if number(self.available_native) <= ZERO:
            raise ValueError("positive original depth quantity required")
        if not isinstance(self.liquidity_id, str) or not self.liquidity_id.strip():
            raise ValueError("shared depth liquidity identity required")
        if not isinstance(self.evidence, EvidenceReference):
            raise ValueError("typed original depth evidence required")


@dataclass(frozen=True)
class DepthLeg:
    leg_id: str
    unit: UnitSpec
    grid: QuantityGridInputs
    depth: DepthInputs
    levels: tuple[DepthLevel, ...] | None
    partial_final: bool | None
    exclusive_group: str | None = None
    native_key: tuple[str, ...] | None = None

    def __post_init__(self):
        if not isinstance(self.leg_id, str) or not self.leg_id.strip():
            raise ValueError("exact depth leg identity required")
        if not isinstance(self.unit, UnitSpec) or not isinstance(self.grid, QuantityGridInputs) or not isinstance(self.depth, DepthInputs):
            raise ValueError("typed unit, grid and depth required")
        if self.levels is not None and (not isinstance(self.levels, tuple) or len(self.levels) > 1000 or not all(isinstance(x, DepthLevel) for x in self.levels)):
            raise ValueError("bounded typed immutable depth levels required")
        if self.partial_final is not None and type(self.partial_final) is not bool:
            raise ValueError("explicit native partial-final rule required")
        if self.native_key is not None and (not isinstance(self.native_key, tuple) or len(self.native_key) != 5 or any(not isinstance(x, str) or not x for x in self.native_key)):
            raise ValueError("exact immutable five-part depth native key required")


def _common_grid(a, b):
    """Existing zero-origin solver validates a chosen offset-native-grid point."""
    x, y = Fraction(a), Fraction(b)
    scale = x.denominator * y.denominator
    return str(Decimal(gcd(int(x * scale), int(y * scale))) / Decimal(scale))


def depth_allocation(legs, native_quantities, *, size_basis="common_comparison_ceiling"):
    """Validate fixed native quantities through the existing shared depth solver.

    Null fee/payout inputs deliberately prevent this mechanical audit from
    producing a net result. Fee/capital qualification remains with S02.
    """
    if (not isinstance(legs, tuple) or not 1 <= len(legs) <= 8 or len(legs) != len(native_quantities)
            or not all(isinstance(x, DepthLeg) for x in legs)):
        raise ValueError("one to eight typed depth legs and matching quantities required")
    if len({x.leg_id for x in legs}) != len(legs):
        raise ValueError("duplicate depth leg identity")
    if size_basis not in {"common_comparison_ceiling", "details_supported_size_sensitivity"}:
        raise ValueError("explicit common or supported-size depth basis required")
    reasons = []
    adapted = []
    quantities = []
    with localcontext(Context(prec=100)):
        for leg, q in zip(legs, native_quantities):
            problems = list(leg.grid.reasons(q)) + list(leg.depth.reasons(q))
            if leg.unit.unit == "stake_usd":
                problems.append("stake_price_payout_legal_grid_conversion_unavailable")
            if leg.levels is None:
                problems.append("price_ladder_unavailable")
            if leg.partial_final is None:
                problems.append("partial_final_rule_unknown")
            if leg.levels is not None:
                for level in leg.levels:
                    checked = adverse_price(leg.unit, leg.grid, level.native_price)
                    problems.extend(reason for reason in checked["reasons"] if reason != "adverse_legal_price_impossible")
            if leg.depth.size_basis != size_basis:
                problems.append("depth_size_basis_mismatch")
            reasons.extend(f"{leg.leg_id}:{r}" for r in problems)
            if problems:
                continue
            total = sum((number(x.available_native) for x in leg.levels), ZERO)
            if total != number(leg.depth.available_native):
                reasons.append(f"{leg.leg_id}:depth_ladder_available_quantity_conflict")
                continue
            minimum = leg.unit.dollar_face(leg.grid.minimum_native)
            increment = leg.unit.dollar_face(leg.grid.increment_native)
            quantities.append(leg.unit.dollar_face(q))
            adapted.append(dict(id=leg.leg_id, minimum=minimum,
                                increment=_common_grid(minimum, increment), partial_final=leg.partial_final,
                                exclusive_group=leg.exclusive_group, fee_policy=None, payouts={},
                                levels=[dict(price=leg.unit.probability_price(x.native_price),
                                             quantity=leg.unit.dollar_face(x.available_native),
                                             liquidity_id=x.liquidity_id, provenance=x.evidence.sha256)
                                        for x in leg.levels]))
        audit = None
        if not reasons:
            try:
                audit = explicit_allocation(dict(legs=adapted, states=["depth_validation_only"], complete=False), quantities)
            except ValueError as exc:
                reasons.append("depth_allocation_declined:" + str(exc))
    return dict(version=VERSION, depth_qualified=not reasons, reasons=reasons,
                size_basis=size_basis, native_quantities=list(native_quantities),
                normalized_quantities=quantities if not reasons else None,
                consumed_legs=None if audit is None else audit["legs"],
                engine="explicit-depth-1", fee_capital_qualified=False,
                net_result=None, current_executable=False,
                limitation="supplied original depth only; shared liquidity counted once; no fill assurance")


def supported_size(leg: DepthLeg):
    """Largest evidenced depth point; funding must still be requalified by S02."""
    if leg.depth.available_native is None or leg.grid.minimum_native is None or leg.grid.increment_native is None:
        return dict(version=VERSION, native_quantity=None, reasons=["supported_size_inputs_unavailable"],
                    size_basis="details_supported_size_sensitivity", ranking_replacement=False)
    with localcontext(Context(prec=100)):
        minimum, increment = number(leg.grid.minimum_native), number(leg.grid.increment_native)
        available = number(leg.depth.available_native)
        q = None if available < minimum else minimum + ((available - minimum) // increment) * increment
    checked = None if q is None else depth_allocation((replace(leg, depth=replace(leg.depth, size_basis="details_supported_size_sensitivity")),),
                                                     (str(q),), size_basis="details_supported_size_sensitivity")
    return dict(version=VERSION, native_quantity=None if q is None else str(q),
                reasons=["native_minimum_exceeds_depth"] if q is None else checked["reasons"],
                depth_qualified=False if checked is None else checked["depth_qualified"],
                size_basis="details_supported_size_sensitivity", ranking_replacement=False,
                funding_qualified=False)


def fixed_sensitivity(base_profits, conservative_profits, *, base_capital_usd,
                      conservative_capital_usd, base_quantities, conservative_quantities,
                      policy=DEFAULT_POLICY):
    """Pair supplied S02 cashflows on a common funded denominator.

    Funding added for the base case is an unused refundable sensitivity
    allowance. Its return does not change dollars of profit. Null state
    profits survive, and percentage improvement from changing capital fails.
    """
    if not base_profits or set(base_profits) != set(conservative_profits):
        raise ValueError("same explicit fixed-allocation state set required")
    if len(base_profits) > 1024:
        raise ValueError("bounded sensitivity state set required")
    bq, cq = tuple(map(_exact, base_quantities)), tuple(map(_exact, conservative_quantities))
    if not bq or bq != cq:
        raise ValueError("sensitivity requires frozen quantities/allocation")
    reasons = []
    capital = None
    if base_capital_usd is None or conservative_capital_usd is None:
        reasons.append("sensitivity_funded_capital_unknown")
    else:
        bc, cc = _exact(base_capital_usd), _exact(conservative_capital_usd)
        if min(bc, cc) <= 0:
            raise ValueError("positive actual funded capital required")
        capital = max(bc, cc)
        if capital > _exact(policy.ceiling_usd):
            reasons.append("comparison_capital_ceiling_exceeded")
    states = {}
    for state in base_profits:
        b = None if base_profits[state] is None else _exact(base_profits[state])
        c = None if conservative_profits[state] is None else _exact(conservative_profits[state])
        if b is None or c is None:
            reasons.append("fixed_allocation_state_profit_unknown:" + state)
        elif c > b:
            reasons.append("conservative_cost_improves_fixed_allocation_state:" + state)
        states[state] = dict(base_profit_usd=None if b is None else _wire(b),
                             conservative_profit_usd=None if c is None else _wire(c),
                             base_return_percent=None, conservative_return_percent=None)
    if not reasons:
        for row in states.values():
            row["base_return_percent"] = _wire(_exact(row["base_profit_usd"]) / capital * 100)
            row["conservative_return_percent"] = _wire(_exact(row["conservative_profit_usd"]) / capital * 100)
    result = dict(version=VERSION, available=not reasons, reasons=reasons, states=states,
                  native_quantities=list(base_quantities), denominator_usd=None if capital is None else _wire(capital),
                  base_actual_required_capital_usd=base_capital_usd,
                  conservative_actual_required_capital_usd=conservative_capital_usd,
                  base_refundable_sensitivity_allowance_usd=None if capital is None else _wire(capital - bc),
                  conservative_refundable_sensitivity_allowance_usd=None if capital is None else _wire(capital - cc),
                  ceiling_usd=policy.ceiling_usd, policy_revision=policy.revision,
                  denominator_basis="same_prefunded_fixed_allocation_capital_including_refundable_unused_allowance",
                  size_basis="fixed_allocation_sensitivity", current_executable=False)
    result["revision"] = digest(result)
    return result


def paired_net_costs(base, conservative, *, policy=DEFAULT_POLICY):
    """Reviewed S02 adapter; retain each dependency revision and local refusal."""
    from app.comparison.net_costs import VERSION as COST_VERSION
    if base.get("version") != COST_VERSION or conservative.get("version") != COST_VERSION:
        raise ValueError("reviewed versioned S02 results required")
    if (base.get("conditioning"), base.get("portfolio_basis"), base.get("partition_complete")) != (
            conservative.get("conditioning"), conservative.get("portfolio_basis"), conservative.get("partition_complete")):
        raise ValueError("same conditioning and portfolio basis required")
    if any(base["dependencies"].get(key) != conservative["dependencies"].get(key) for key in ("leg", "cashflows", "grid", "positions")):
        raise ValueError("same exact leg, payout partition, grid and position basis required")
    base_size, stress_size = base["size_basis"], conservative["size_basis"]
    if (_exact(base_size["native_quantity"]) != _exact(stress_size["native_quantity"]) or
            base_size.get("quantity_dollar_face") != stress_size.get("quantity_dollar_face")):
        raise ValueError("S02 sensitivity requires frozen quantity and native unit conversion")
    if (base_size.get("common_capital_ceiling_usd") != stress_size.get("common_capital_ceiling_usd") or
            _exact(base_size["common_capital_ceiling_usd"]) != _exact(policy.ceiling_usd)):
        raise ValueError("same reviewed common capital ceiling required")
    profits = lambda value: {key: row["net_profit_usd"] for key, row in value["states"].items()}
    bp, cp = profits(base), profits(conservative)
    if set(bp) != set(cp):
        raise ValueError("same explicit S02 state set required")
    known_states = [state for state in bp if bp[state] is not None and cp[state] is not None]
    unknown_states = [state for state in bp if state not in known_states]
    capital = lambda value: None if value["capital"] is None else value["capital"]["deployed_capital_usd"]
    # D04 exceptional unknowns never suppress qualified completed-state
    # sensitivity. Its scope remains explicitly conditional and those states
    # stay visible as null; they cannot establish all-modeled assurance.
    result = fixed_sensitivity({state: bp[state] for state in known_states} if known_states else bp,
                               {state: cp[state] for state in known_states} if known_states else cp,
                               base_capital_usd=capital(base),
                               conservative_capital_usd=capital(conservative),
                               base_quantities=(base_size["native_quantity"],),
                               conservative_quantities=(stress_size["native_quantity"],), policy=policy)
    for state in unknown_states:
        result["states"][state] = dict(base_profit_usd=bp[state], conservative_profit_usd=cp[state],
                                       base_return_percent=None, conservative_return_percent=None)
    for name, value in (("base", base), ("conservative", conservative)):
        if not value["available"]:
            result["reasons"].extend(name + ":" + reason for reason in value["reasons"])
            result["available"] = False
    if not result["available"]:
        for row in result["states"].values():
            row["base_return_percent"] = row["conservative_return_percent"] = None
    result.update(cost_revisions=dict(base=base["revision"], conservative=conservative["revision"]),
                  dependencies=dict(base=deepcopy(base["dependencies"]), conservative=deepcopy(conservative["dependencies"])),
                  conditioning=base["conditioning"], portfolio_basis=base["portfolio_basis"],
                  evaluated_state_ids=known_states, unknown_state_ids=unknown_states,
                  comparison_scope="conditional_known_states" if unknown_states or not base["partition_complete"] else "all_modeled_states",
                  all_modeled_outcome_qualified=not unknown_states and base["partition_complete"] and result["available"])
    result["revision"] = digest({k: v for k, v in result.items() if k != "revision"})
    return result


def calculate_buffered_costs(bound_leg, request, *, unit, native_quantity, native_price,
                             grid, fill_inputs, fills, original_source_clock, phase,
                             registry=None, engine_context=None, engine_registry=None,
                             positions=None, extra_funding=(), hold_returns_usd=None,
                             credits=(), depth_leg=None, include_exceptions=True,
                             policy=DEFAULT_POLICY):
    """Rebuild S01 at a legal adverse price and recompute S02 on frozen fills.

    No resizing, fee extrapolation or source clock refresh. A null depth input
    permits only a disclosed hypothetical estimate, never depth qualification.
    """
    from app.comparison.cashflows import cashflow_inputs
    from app.comparison.net_costs import calculate_net_costs
    from app.comparison.payouts import bind_profile
    at = _instant(request.calculation_time)
    age = age_gate(original_source_clock, phase=phase, at=at, policy=policy)
    movement = adverse_price(unit, grid, native_price, policy=policy)
    quantity = unit.dollar_face(native_quantity) if unit.unit != "stake_usd" else native_quantity
    base_scenario = cashflow_inputs((bound_leg,), (quantity,), at=at, include_exceptions=include_exceptions)
    kwargs = dict(native_quantity=native_quantity, grid=grid, fill_inputs=fill_inputs,
                  registry=registry, engine_context=engine_context, engine_registry=engine_registry,
                  positions=positions, extra_funding=extra_funding, hold_returns_usd=hold_returns_usd,
                  credits=credits, ceiling_usd=policy.ceiling_usd)
    base = calculate_net_costs(request, base_scenario, native_price=native_price, fills=fills, **kwargs)
    conservative = sensitivity = None
    reasons = list(age["reasons"]) + list(movement["reasons"])
    selected_rule = base["rule"].get("rule")
    if selected_rule is not None and UnitSpec(**selected_rule["unit"]) != unit:
        reasons.append("buffer_cost_native_unit_conflict")
        movement["available"] = False
    if movement["available"]:
        price = bound_leg.selection.price
        if price.unit not in {"usd_per_contract", "cents_per_contract"}:
            reasons.append("contract_price_representation_unavailable")
        else:
            with localcontext(Context(prec=100)):
                amount = Decimal(movement["adverse_normalized_price"]) * (100 if price.unit == "cents_per_contract" else 1)
            changed = replace(bound_leg.selection, price=replace(price, amount=ExactNumber.parse(str(amount))))
            rebuilt = bind_profile(changed, bound_leg.profile, at=at,
                                   rule_revision=bound_leg.profile.rule_revision, context=bound_leg.context)
            stress_scenario = cashflow_inputs((rebuilt,), (quantity,), at=at, include_exceptions=include_exceptions)
            stressed_fills = deepcopy(fills)
            for fill in stressed_fills:
                fill["price"] = movement["adverse_normalized_price"]
            conservative = calculate_net_costs(request, stress_scenario,
                                               native_price=movement["adverse_native_price"],
                                               fills=stressed_fills, **kwargs)
            sensitivity = paired_net_costs(base, conservative, policy=policy)
            reasons.extend(sensitivity["reasons"])
    depth = (dict(depth_qualified=False, reasons=["depth_inputs_unavailable"], size_basis="common_comparison_ceiling")
             if depth_leg is None else depth_allocation((depth_leg,), (native_quantity,)))
    if depth_leg is not None and (depth_leg.native_key != bound_leg.selection.native.key or depth_leg.unit != unit):
        depth["depth_qualified"] = False
        depth["reasons"].append("depth_native_selection_or_unit_attachment_conflict")
    available = sensitivity is not None and sensitivity["available"] and not reasons
    result = dict(version=VERSION, base=base, conservative=conservative, sensitivity=sensitivity,
                  age=age, movement=movement, depth=depth, reasons=list(dict.fromkeys(reasons)),
                  supported_size_sensitivity=None if depth_leg is None else supported_size(depth_leg),
                  hypothetical_estimate_available=available,
                  depth_qualified_ranking_available=available and depth["depth_qualified"],
                  size_basis="common_comparison_ceiling", default_capital_ceiling_usd=policy.ceiling_usd,
                  no_manual_stake_required=True, current_executable=False)
    result["revision"] = digest(result)
    return result
