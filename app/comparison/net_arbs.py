"""S05 bounded two-leg modeled portfolios; shared cashflow/cost/depth engines.

All search limits are declared before work. Candidate pair orientation is unique;
sampled/truncated allocation searches never claim a global optimum or execution.
No probability model, provider requests, stake entry or owner state is involved.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from fractions import Fraction
from itertools import combinations, product

from app.comparison.buffers import age_gate, adverse_price, depth_allocation, fixed_sensitivity
from app.comparison.cashflows import ScenarioCashflows, cashflow_inputs, evaluate_portfolio
from app.comparison.costs import DEFAULT_POLICY, CostRequest, FillInputs, UnitSpec
from app.comparison.domain import ExactNumber
from app.comparison.net_costs import VERSION as COST_VERSION, calculate_net_costs, revision, wire
from app.comparison.payouts import BoundLeg, bind_profile


VERSION = "comparison-net-arbs-1"


@dataclass(frozen=True)
class ArbLimits:
    max_candidate_pairs: int = 256
    max_allocation_evaluations: int = 1024
    max_results: int = 128
    max_points_per_leg: int = 128

    def __post_init__(self):
        for name, ceiling in (("max_candidate_pairs", 4096), ("max_allocation_evaluations", 100000),
                              ("max_results", 1024), ("max_points_per_leg", 1024)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("bounded positive search limit required: " + name)

    def to_dict(self):
        return dict(candidate_pairs=self.max_candidate_pairs,
                    allocation_evaluations=self.max_allocation_evaluations,
                    returned_results=self.max_results, points_per_leg=self.max_points_per_leg)


@dataclass(frozen=True)
class ArbLeg:
    bound_leg: BoundLeg
    depth_leg: object
    request: CostRequest
    cost_kwargs: dict
    original_source_clock: str | None
    phase: str
    fill_partition_basis: str | None = None

    def __post_init__(self):
        from app.comparison.buffers import DepthLeg
        if not isinstance(self.bound_leg, BoundLeg) or not isinstance(self.depth_leg, DepthLeg):
            raise ValueError("bound payout leg and evidenced depth required")
        if not isinstance(self.request, CostRequest) or not isinstance(self.cost_kwargs, dict):
            raise ValueError("typed cost request and explicit cost terms required")
        if self.depth_leg.native_key != self.bound_leg.selection.native.key:
            raise ValueError("arb_depth_native_attachment_conflict")
        if self.bound_leg.selection.native.key[:3] != (self.request.venue, self.request.event_id, self.request.market_id):
            raise ValueError("arb_cost_native_attachment_conflict")
        if self.fill_partition_basis not in {None, "authored_complete_depth_fills"}:
            raise ValueError("explicit supported hypothetical fill partition required")
        object.__setattr__(self, "cost_kwargs", deepcopy(self.cost_kwargs))


def _same_cost_basis(base, conservative):
    if any(c.get("version") != COST_VERSION for c in (base, conservative)):
        raise ValueError("reviewed S02 cost results required")
    if base["selection_basis"] != conservative["selection_basis"]:
        raise ValueError("arb_same_native_payout_state_basis_required")
    for key in ("portfolio_basis", "conditioning", "partition_complete"):
        if base[key] != conservative[key]:
            raise ValueError("arb_same_conditioning_portfolio_basis_required")
    if Fraction(base["size_basis"]["native_quantity"]) != Fraction(conservative["size_basis"]["native_quantity"]):
        raise ValueError("arb_frozen_allocation_required")
    if base["dependencies"].get("positions") != conservative["dependencies"].get("positions"):
        raise ValueError("arb_same_private_portfolio_basis_required")


def _cost_summary(cost):
    """Public per-leg amounts only, retaining null unknown state charges."""
    summary = {key: deepcopy(cost.get(key)) for key in (
        "acquisition_usd", "entry_fee_usd", "net_entry_fee_usd", "rounding_refund_usd")}
    capital = cost.get("capital")
    summary["capital"] = None if capital is None else {
        key: deepcopy(capital.get(key)) for key in (
            "ceiling_usd", "deployed_capital_usd", "residual_ceiling_usd", "denominator", "reasons")}
    summary["states"] = {state: {key: deepcopy(row.get(key)) for key in (
        "gross_return_usd", "hold_return_usd", "settlement_fee_usd", "net_return_usd",
        "net_profit_usd", "reasons")} for state, row in cost["states"].items()}
    return summary


def evaluate_arb_allocation(inputs, base_costs, conservative_costs, depth_result,
                            native_quantities, *, policy=DEFAULT_POLICY):
    """Evaluate an exact fixed two-leg allocation supplied by reviewed S01–S03.

    Prices alone never define complementary payouts. Complete and conditional
    state categories are distinct, with zero and negative diagnostics retained.
    """
    if not isinstance(inputs, ScenarioCashflows) or len(inputs.legs) != 2:
        raise ValueError("reviewed exact two-leg cashflows required")
    if (not isinstance(base_costs, tuple) or not isinstance(conservative_costs, tuple) or
            len(base_costs) != 2 or len(conservative_costs) != 2 or len(native_quantities) != 2):
        raise ValueError("two ordered fee/allocation inputs required")
    keys = tuple(leg.native_key for leg in inputs.legs)
    if keys[0][0] == keys[1][0] or "pinnacle" in (keys[0][0], keys[1][0]):
        raise ValueError("distinct execution venues required; Pinnacle is a reference")
    if keys[0] == keys[1]:
        raise ValueError("duplicate arb instrument")
    reasons = []
    if depth_result.get("depth_qualified") is not True:
        reasons.extend("depth:" + r for r in depth_result.get("reasons", ["depth_unqualified"]))
    if tuple(map(Fraction, depth_result.get("native_quantities", ()))) != tuple(map(Fraction, native_quantities)):
        raise ValueError("arb_depth_allocation_quantity_conflict")
    for index, (base, conservative) in enumerate(zip(base_costs, conservative_costs)):
        _same_cost_basis(base, conservative)
        if tuple(base["selection_basis"]["native_key"]) != keys[index]:
            raise ValueError("arb_cost_leg_orientation_conflict")
        if set(base["states"]) != set(inputs.state_ids) or set(conservative["states"]) != set(inputs.state_ids):
            raise ValueError("arb_joint_state_cost_basis_conflict")
        if Fraction(base["size_basis"]["native_quantity"]) != Fraction(native_quantities[index]):
            raise ValueError("arb_cost_allocation_quantity_conflict")
        if not base["available"] or not conservative["available"]:
            reasons.extend(f"leg-{index}:" + r for r in (*base["reasons"], *conservative["reasons"]))
    cost_cash = lambda rows: tuple(None if c["capital"] is None else c["capital"]["deployed_capital_usd"] for c in rows)
    cost_receipts = lambda rows: tuple({s: c["states"][s]["net_return_usd"] for s in inputs.state_ids} for c in rows)
    gross = evaluate_portfolio(inputs)
    base = evaluate_portfolio(inputs, cash=cost_cash(base_costs), receipts=cost_receipts(base_costs),
                              fee_basis="reviewed S02 base costs")
    conservative = evaluate_portfolio(inputs, cash=cost_cash(conservative_costs),
                                      receipts=cost_receipts(conservative_costs),
                                      fee_basis="reviewed S02 legal-price buffered costs")
    # Unknown terminal receipts can withhold full liability/denominator proof.
    # A conditional estimate uses the same known-state capital basis explicitly.
    capital = lambda value: (value["full"]["return_denominator"] or
                              (value["conditional"]["return_denominator"] if value["conditional"] else None))
    bc, cc = capital(base), capital(conservative)
    denominator = None if bc is None or cc is None else max(Fraction(bc), Fraction(cc))
    if denominator is not None and denominator > Fraction(policy.ceiling_usd):
        reasons.append("comparison_capital_ceiling_exceeded")
    full_known = conservative["full"]["worst_case_return"] is not None and inputs.partition_complete
    selected = conservative["full"] if full_known else conservative["conditional"]
    category = "all_modeled_outcomes" if full_known else "conditional_known_states"
    profits = {} if selected is None else selected["states"]
    known = {s: Fraction(v) for s, v in profits.items() if v is not None}
    minimum = min(known.values()) if known else None
    limiting = sorted(s for s, v in known.items() if v == minimum)
    sensitivity = None
    paired = [s for s in inputs.state_ids if base["full"]["states"][s] is not None and conservative["full"]["states"][s] is not None]
    if paired and bc is not None and cc is not None:
        sensitivity = fixed_sensitivity({s: base["full"]["states"][s] for s in paired},
                                        {s: conservative["full"]["states"][s] for s in paired},
                                        base_capital_usd=bc, conservative_capital_usd=cc,
                                        base_quantities=native_quantities, conservative_quantities=native_quantities,
                                        policy=policy)
        reasons.extend(sensitivity["reasons"])
    elif not paired:
        reasons.append("arb_no_known_joint_state_cashflows")
    ratio = None if minimum is None or not denominator else minimum / denominator * 100
    positive = minimum is not None and minimum > 0 and not reasons
    one_leg = [dict(native_key=list(key), deployed_capital_usd=row["capital"]["deployed_capital_usd"] if row["capital"] else None,
                   state_profits_usd={s: row["states"][s]["net_profit_usd"] for s in inputs.state_ids},
                   category="one_leg_acquired_exposure", fully_acquired_pair=False)
               for key, row in zip(keys, conservative_costs)]
    result = dict(version=VERSION, opportunity_id=revision(dict(native_keys=sorted(keys))),
                  available=not reasons and minimum is not None, reasons=list(dict.fromkeys(reasons)),
                  category=category, conditioning="all modeled terminal states" if full_known else "listed known joint states only",
                  native_keys=[list(k) for k in keys], native_quantities=list(native_quantities),
                  minimum_return_usd=None if minimum is None else wire(minimum),
                  minimum_return_percent=None if ratio is None or reasons else wire(ratio),
                  denominator_usd=None if denominator is None else wire(denominator),
                  denominator_basis="same_prefunded_fixed_allocation_capital",
                  limiting_states=limiting, unknown_states=[s for s in inputs.state_ids if conservative["full"]["states"][s] is None],
                  state_descriptors=[dict(state_id=state.state_id, terminal=state.terminal,
                    score_domain=inputs.legs[0].selection["predicate"]["domain"],
                    score_range=None if state.score_range is None else dict(
                        lower=state.score_range.lower, upper=state.score_range.upper))
                    for state in inputs.table.states],
                  state_profits_usd=deepcopy(conservative["full"]["states"]),
                  modeled_profitable=positive, all_modeled_outcome_profitable=positive and full_known,
                  conditional_profitable=positive and not full_known,
                  base=base, conservative=conservative, gross=gross, sensitivity=sensitivity,
                  depth=deepcopy(depth_result), one_leg_exposures=one_leg,
                  cost_summaries=dict(base=[_cost_summary(cost) for cost in base_costs],
                                      conservative=[_cost_summary(cost) for cost in conservative_costs]),
                  dependency_revisions=dict(scenario=inputs.revision,
                    base_costs=[c["revision"] for c in base_costs], conservative_costs=[c["revision"] for c in conservative_costs]),
                  estimate_class="fully acquired hypothetical portfolio; no synchronized fill or realized profit assurance",
                  assumptions=["taker execution", "standalone hypothetical portfolio", "declared complete hypothetical fill partition"])
    result["revision"] = revision(result)
    return result


def _quantity_points(leg, limits, policy):
    depth = leg.depth_leg
    if leg.fill_partition_basis is None:
        return (), False, ["bounded_fragmentation_required"]
    if depth.unit.unit == "stake_usd":
        return (), False, ["stake_price_payout_legal_grid_conversion_unavailable"]
    if depth.grid.minimum_native is None or depth.grid.increment_native is None or depth.depth.available_native is None:
        return (), False, ["arb_native_size_depth_grid_unavailable"]
    if not depth.levels:
        return (), False, ["arb_price_ladder_unavailable"]
    minimum, increment = Fraction(depth.grid.minimum_native), Fraction(depth.grid.increment_native)
    price = Fraction(depth.unit.probability_price(depth.levels[0].native_price))
    face_per_native = Fraction(depth.unit.dollar_face("1"))
    maximum = min(Fraction(depth.depth.available_native), Fraction(policy.ceiling_usd) / (price * face_per_native))
    if maximum < minimum:
        return (), False, ["arb_native_minimum_exceeds_depth_or_capital"]
    count = int((maximum - minimum) // increment) + 1
    sampled = count > limits.max_points_per_leg
    if sampled:
        indices = {0, count-1}
        if limits.max_points_per_leg > 1:
            indices.update(i * (count-1) // (limits.max_points_per_leg-1) for i in range(limits.max_points_per_leg))
        else:
            indices = {count-1}
    else:
        indices = set(range(count))
    return tuple(wire(minimum + i * increment) for i in sorted(indices)), sampled, []


def _allocation(legs, quantities, *, at, policy):
    from app.depth import consume
    depth = depth_allocation(tuple(leg.depth_leg for leg in legs), quantities)
    normalized = tuple(leg.depth_leg.unit.dollar_face(q) for leg, q in zip(legs, quantities))
    if not depth["depth_qualified"]:
        raise ValueError(",".join(depth["reasons"]))
    base_bound = []
    stressed = []
    movements = []
    fill_groups = []
    for i, leg in enumerate(legs):
        consumed = consume([dict(price=leg.depth_leg.unit.probability_price(level.native_price),
                                  quantity=leg.depth_leg.unit.dollar_face(level.available_native),
                                  provenance=level.evidence.sha256) for level in leg.depth_leg.levels],
                           normalized[i], partial_final=leg.depth_leg.partial_final)
        changes = []
        for fill in consumed:
            native_price = (wire(Fraction(fill["price"]) * Fraction(leg.depth_leg.unit.price_scale))
                            if leg.depth_leg.unit.unit == "fixed_point_contracts" else fill["price"])
            change = adverse_price(leg.depth_leg.unit, leg.depth_leg.grid, native_price, policy=policy)
            if not change["available"]:
                raise ValueError(",".join(change["reasons"]))
            changes.append(change)
        original = leg.bound_leg.selection.price
        if original.unit not in {"usd_per_contract", "cents_per_contract"}:
            raise ValueError("arb_contract_price_representation_unavailable")
        scale = 100 if original.unit == "cents_per_contract" else 1
        total = Fraction(normalized[i])
        base_amount = sum((Fraction(fill["price"]) * Fraction(fill["quantity"]) for fill in consumed), Fraction(0)) / total * scale
        stress_amount = sum((Fraction(change["adverse_normalized_price"]) * Fraction(fill["quantity"])
                             for fill, change in zip(consumed, changes)), Fraction(0)) / total * scale
        for amount, collection in ((base_amount, base_bound), (stress_amount, stressed)):
            selection = replace(leg.bound_leg.selection, price=replace(original, amount=ExactNumber(wire(amount))))
            collection.append(bind_profile(selection, leg.bound_leg.profile, at=at,
                              rule_revision=leg.bound_leg.profile.rule_revision, context=leg.bound_leg.context))
        movements.append(changes)
        fill_groups.append(consumed)
    base_inputs = cashflow_inputs(tuple(base_bound), normalized, at=at)
    stress_inputs = cashflow_inputs(tuple(stressed), normalized, at=at)
    if base_inputs.state_ids != stress_inputs.state_ids:
        raise ValueError("arb_adverse_partition_changed")
    base_costs, conservative = [], []
    for i, (leg, q, movements_for_leg) in enumerate(zip(legs, quantities, movements)):
        fills = [dict(fill_id="authored-arb-fill-" + str(index), order_id="authored-arb-order", role=leg.request.role,
                      price=fill["price"],
                      quantity=wire(Fraction(fill["quantity"]) * 100) if leg.depth_leg.unit.unit == "novig_v3_cent_contracts" else fill["quantity"],
                      unit="novig_v3_contracts" if leg.depth_leg.unit.unit == "novig_v3_cent_contracts" else "contracts")
                 for index, fill in enumerate(fill_groups[i])]
        kwargs = deepcopy(leg.cost_kwargs)
        for forbidden in ("native_quantity", "native_price", "grid", "fill_inputs", "fills", "ceiling_usd", "leg_index"):
            if forbidden in kwargs:
                raise ValueError("arb_cost_kwargs_conflict:" + forbidden)
        request = replace(leg.request, calculation_time=at.isoformat())
        if kwargs.get("engine_context") is not None:
            kwargs["engine_context"]["calculation_time"] = request.calculation_time
        base_costs.append(calculate_net_costs(request, base_inputs, native_quantity=q,
            native_price=leg.depth_leg.levels[0].native_price, grid=leg.depth_leg.grid,
            fill_inputs=FillInputs("authored_fills", True, len(fills), len(fills), ("authored-arb-order",)),
            fills=fills, ceiling_usd=policy.ceiling_usd, leg_index=i, **kwargs))
        for fill, movement in zip(fills, movements_for_leg):
            fill["price"] = movement["adverse_normalized_price"]
        conservative.append(calculate_net_costs(request, stress_inputs, native_quantity=q,
            native_price=movements_for_leg[0]["adverse_native_price"], grid=leg.depth_leg.grid,
            fill_inputs=FillInputs("authored_fills", True, len(fills), len(fills), ("authored-arb-order",)),
            fills=fills, ceiling_usd=policy.ceiling_usd, leg_index=i, **kwargs))
    result = evaluate_arb_allocation(base_inputs, tuple(base_costs), tuple(conservative), depth, quantities, policy=policy)
    result["buffers"] = movements
    result["revision"] = revision({k: v for k, v in result.items() if k != "revision"})
    return result


def search_arbs(legs, *, at, limits=None, policy=DEFAULT_POLICY):
    """Search a declared finite domain; retain best evaluated allocation per pair."""
    limits = limits or ArbLimits()
    if not isinstance(limits, ArbLimits) or not isinstance(legs, tuple) or len(legs) > 512:
        raise ValueError("declared bounds and immutable candidate legs required")
    if not all(isinstance(leg, ArbLeg) for leg in legs):
        raise ValueError("reviewed ArbLeg candidates required")
    if not isinstance(at, datetime) or at.utcoffset() is None:
        raise ValueError("aware current calculation instant required")
    identities = {}
    diagnostics = []
    for leg in legs:
        key = leg.bound_leg.selection.native.key
        if key[0] == "pinnacle":
            diagnostics.append(dict(native_key=list(key), reasons=["pinnacle_reference_not_execution_leg"]))
            continue
        age = age_gate(leg.original_source_clock, phase=leg.phase, at=at, policy=policy)
        if not age["eligible"]:
            diagnostics.append(dict(native_key=list(key), reasons=age["reasons"]))
            continue
        signatures = identities.setdefault(key, {})
        # Private fields participate in a digest only. Include every relevant
        # cost input so conflicting private/fee assumptions cannot pick a winner
        # by input order; registry objects serialize their retained data.
        cost_identity = {}
        for name, value in leg.cost_kwargs.items():
            if name in {"registry", "engine_registry"} and value is not None:
                cost_identity[name] = value.data
            elif name == "positions" and value is not None:
                cost_identity[name] = value.public_reference()
            elif name in {"extra_funding", "credits"}:
                cost_identity[name] = [asdict(item) for item in value]
            else:
                cost_identity[name] = value
        signatures.setdefault(revision(dict(bound=leg.bound_leg.revision,
                                             price=leg.bound_leg.selection.price.to_dict(),
                                             depth=asdict(leg.depth_leg), request=asdict(leg.request),
                                             fill_partition_basis=leg.fill_partition_basis,
                                             cost_inputs_sha256=revision(cost_identity))), leg)
    unique = []
    for key, variants in sorted(identities.items()):
        if len(variants) != 1:
            diagnostics.append(dict(native_key=list(key), reasons=["conflicting_duplicate_arb_instrument"]))
        else:
            unique.append(next(iter(variants.values())))
    pairs = 0
    evaluations = 0
    theoretical_pairs = 0
    pair_truncated = False
    allocation_truncated = False
    returned_truncated = False
    results = []
    for pair in combinations(unique, 2):
        if pair[0].request.venue == pair[1].request.venue:
            continue
        theoretical_pairs += 1
        if pairs >= limits.max_candidate_pairs:
            pair_truncated = True
            continue
        pairs += 1
        try:
            domains = [_quantity_points(leg, limits, policy) for leg in pair]
            problems = [r for domain in domains for r in domain[2]]
            if problems:
                raise ValueError(",".join(problems))
            allocation_truncated |= any(domain[1] for domain in domains)
            best = None
            pair_evaluations = 0
            declined = 0
            allocation_reasons = []
            for quantities in product(*(domain[0] for domain in domains)):
                if evaluations >= limits.max_allocation_evaluations:
                    allocation_truncated = True
                    break
                evaluations += 1
                pair_evaluations += 1
                try:
                    current = _allocation(pair, quantities, at=at, policy=policy)
                except (ValueError, KeyError) as error:
                    declined += 1
                    if str(error) not in allocation_reasons and len(allocation_reasons) < 32:
                        allocation_reasons.append(str(error))
                    continue
                if best is None or _order(current) < _order(best):
                    best = current
            if best is not None:
                best.update(search_label="best evaluated allocation", allocation_evaluations=pair_evaluations,
                            declined_allocation_count=declined,
                            global_optimum_established=False)
                best["revision"] = revision({k: v for k, v in best.items() if k != "revision"})
                results.append(best)
                results.sort(key=_order)
                if len(results) > limits.max_results:
                    returned_truncated = True
                    results.pop()
            if allocation_reasons:
                diagnostics.append(dict(native_keys=[list(leg.bound_leg.selection.native.key) for leg in pair],
                                        reasons=allocation_reasons, declined_allocation_count=declined))
        except (ValueError, KeyError) as error:
            diagnostics.append(dict(native_keys=[list(leg.bound_leg.selection.native.key) for leg in pair], reasons=[str(error)]))
    results.sort(key=_order)
    result = dict(version=VERSION, limits=limits.to_dict(), candidate_pairs=pairs,
                  theoretical_candidate_pairs=theoretical_pairs, allocation_evaluations=evaluations,
                  returned_results=min(len(results), limits.max_results),
                  truncated=pair_truncated or allocation_truncated or returned_truncated,
                  truncation=dict(candidate_pairs=pair_truncated, allocation_evaluations=allocation_truncated,
                                  returned_results=returned_truncated),
                  results=results[:limits.max_results], diagnostics=diagnostics,
                  policy_revision=policy.revision,
                  limitations=["best evaluated allocation only", "related candidates cannot sum shared liquidity",
                               "modeled complete hypothetical fills; actual fragmentation and execution remain unqualified"])
    result["revision"] = revision(result)
    return result


def _order(result):
    value = result.get("minimum_return_percent")
    dollars = result.get("minimum_return_usd")
    return (not result["available"], result["category"] != "all_modeled_outcomes", value is None,
            -Fraction(value) if value is not None else 0, -Fraction(dollars) if dollars is not None else 0,
            result["opportunity_id"], tuple(map(Fraction, result["native_quantities"])))
