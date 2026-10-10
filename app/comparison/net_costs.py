"""S02 current-size costs over S01 receipts; acquisition-free and exact.

The D09 rule gate precedes arithmetic. Public proposals are never a numeric
binding. Venue caps/accumulators use the retained shared engine, while explicitly
named controlled policies use its source-independent algebra. Public results
contain private-position digests, never accounts, raw portfolios or engine audits.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Context, Decimal, localcontext
from fractions import Fraction
import hashlib
import json

from app.comparison.costs import (
    CapitalInputs, CostRegistry, CostRequest, CreditInputs, FillInputs,
    FundingComponent, PositionInputs, QuantityGridInputs, authored_fee,
    load_cost_registry,
)
from app.comparison.domain import ExactNumber
from app.fees.engine import Registry, calculate, number
from app.fees.entry_bounds import us_taker_bound
from app.fees.precision_envelope import calculate_envelope


VERSION = "comparison-net-costs-1"
ZERO = Fraction(0)


def exact(value):
    return ExactNumber.parse(value).value


def wire(value):
    """Exact rational output; terminating values use ordinary decimal strings."""
    value = Fraction(value)
    denominator = value.denominator
    while denominator % 2 == 0:
        denominator //= 2
    while denominator % 5 == 0:
        denominator //= 5
    if denominator == 1:
        with localcontext(Context(prec=200)):
            return format(Decimal(value.numerator) / Decimal(value.denominator), "f")
    return f"{value.numerator}/{value.denominator}"


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _monetary(value):
    # Derived state profits sent to the shared monetary engine must be bounded
    # terminating decimals. Refuse rather than round an exact rational input.
    text = wire(exact(value))
    if "/" in text:
        raise ValueError("nonterminating_state_fee_base_requires_exact_engine_support")
    number(text)
    return text


def _parsed_fills(fills, request, fill_inputs):
    if not isinstance(fills, list) or not 1 <= len(fills) <= 10000:
        raise ValueError("bounded explicit fill list required")
    if fill_inputs.fill_count != len(fills):
        raise ValueError("fill_count_mismatch")
    if set(f.get("order_id") for f in fills) != set(fill_inputs.order_ids):
        raise ValueError("fill_order_identity_mismatch")
    seen = set()
    face = ZERO
    acquisition = ZERO
    normalized = []
    for fill in fills:
        if not isinstance(fill, dict) or not isinstance(fill.get("fill_id"), str) or not fill["fill_id"]:
            raise ValueError("explicit fill identity required")
        if fill["fill_id"] in seen:
            raise ValueError("duplicate_fill_identity")
        seen.add(fill["fill_id"])
        if fill.get("role") != request.role:
            raise ValueError("fill_role_conflict")
        if fill.get("market_id", request.market_id) != request.market_id:
            raise ValueError("fill_market_scope_conflict")
        p = exact(fill["price"])
        q = exact(fill["quantity"])
        number(fill["price"])
        number(fill["quantity"])
        if not 0 < p < 1 or q <= 0:
            raise ValueError("invalid normalized fill")
        if fill.get("unit") == "novig_v3_contracts" and request.venue == "novig":
            if q.denominator != 1:
                raise ValueError("native Novig quantity must be integral")
            q /= 100
        elif fill.get("unit") != "contracts":
            raise ValueError("unsupported_fill_unit")
        face += q
        acquisition += p * q
        normalized.append(dict(price=wire(p), quantity=wire(q)))
    return face, acquisition, normalized


def _venue_entry(rule, request, fills, fill_inputs, engine_context, engine_registry):
    """Delegate provider formulas; bind exact D09 terms to the selected engine."""
    if engine_context is None or not isinstance(engine_registry, Registry):
        raise ValueError("shared_venue_engine_binding_required")
    context = deepcopy(engine_context)
    for name in ("venue", "product", "market_id", "trade_time", "calculation_time"):
        if context.get(name) != getattr(request, name):
            raise ValueError("shared_engine_context_scope_conflict")
    if context.get("channel", request.channel) != request.channel:
        raise ValueError("shared_engine_context_channel_conflict")
    if context.get("action", "buy") != "buy":
        raise ValueError("only acquisition cost scenarios supported")
    selected = engine_registry.select(request.venue, request.product,
                                      request.trade_time, context.get("schedule_version"))
    if rule.terms.basis != "quadratic":
        raise ValueError("shared_engine_charge_basis_conflict")
    if request.venue == "kalshi":
        if (rule.terms.aggregation != "order_accumulator" or
                rule.terms.rounding != "ceiling" or rule.terms.grid_usd != "0.000001"):
            raise ValueError("kalshi_accumulator_terms_conflict")
        if exact(selected["coefficient"]) != exact(rule.terms.rate):
            raise ValueError("shared_engine_coefficient_conflict")
        if request.series_id != context.get("series_id") or request.event_id != context.get("event_id"):
            raise ValueError("kalshi_fee_native_scope_conflict")
    elif request.venue == "polymarket_us":
        aggregation = "cumulative_order_cap" if request.role == "taker" else "per_fill"
        if (rule.terms.aggregation != aggregation or
                rule.terms.rounding != "half_even" or rule.terms.grid_usd != "0.01" or
                selected.get("combo_coefficient") is not None):
            raise ValueError("us_single_order_cap_terms_conflict")
        selected_rate = selected["coefficient" if request.role == "taker" else "maker_coefficient"]
        if exact(selected_rate) != exact(rule.terms.rate):
            raise ValueError("shared_engine_coefficient_conflict")
    elif request.venue == "novig":
        if (rule.unit.unit != "novig_v3_cent_contracts" or context.get("api_regime") != "v3" or
                selected.get("api_regime") != "v3" or rule.terms.aggregation != "per_fill" or
                rule.terms.rounding != "half_up" or rule.terms.grid_usd != "0.00001"):
            raise ValueError("novig_v3_terms_required")
        if exact(context.get("market_fee", {}).get("coefficient")) != exact(rule.terms.rate):
            raise ValueError("shared_engine_coefficient_conflict")
    else:
        raise ValueError("unsupported shared venue entry adapter")
    context.update(fills=deepcopy(fills), complete_order_history=fill_inputs.complete_order_history,
                   outcomes={})
    # Outcome fees are independently bound to S01 state receipts below. The
    # engine's old default outcome assumptions cannot establish settlement fees.
    context.pop("refund_outcomes", None)
    audit = calculate(context, engine_registry)
    if audit["unsupported"] or audit["entry_fees"] is None:
        raise ValueError("shared_venue_engine_refused:" + ";".join(audit["unsupported"]))
    refunds = sum((exact(c["amount"]) for c in audit["credits"]
                   if c["kind"] == "order_rounding_refund" and c.get("conditional") is False), ZERO)
    return exact(audit["entry_notional"]), exact(audit["entry_fees"]), refunds, {
        "engine": audit["engine"], "schedule_sha256": audit["schedule_hash"],
        "context_sha256": audit["context_hash"], "registry_sha256": audit["registry_hash"],
        "rounding_qualification": audit["rounding_qualification"],
        "credits_excluded_from_funding": [c["kind"] for c in audit["credits"]
                                          if c["kind"] != "order_rounding_refund"],
    }


def _state_fees(terms, request, positions, profits, normalized):
    if terms.basis == "net_gain":
        baseline = (positions.generic_context(request, tuple(profits)) if positions else
                    dict(account="account:standalone_hypothesis", market=request.market_id or "standalone",
                         complete=True, net_before={s: "0" for s in profits}))
        result = authored_fee(terms, [], positions=baseline,
                              outcomes={s: "0" if exact(terms.rate) == 0 else _monetary(wire(v))
                                        for s, v in profits.items()})
        return {s: exact(v) for s, v in result["state_fees"].items()}
    result = authored_fee(terms, normalized)
    return {s: exact(result["entry_fee"]) for s in profits}


def calculate_net_costs(request, scenario, *, native_quantity, native_price, grid,
                        fill_inputs, fills, registry=None, engine_context=None,
                        engine_registry=None, positions=None, extra_funding=(),
                        hold_returns_usd=None, credits=(), ceiling_usd="100", leg_index=0):
    """Bind one S01 leg to exact costs. No quantity optimizer or acquisition.

    `scenario` is ScenarioCashflows or its versioned .to_dict() mapping. `fills`
    are explicit shared-engine fill records; Novig uses native cent contracts.
    Unknown-split inputs only support `entry_fee_bounds`, never exact costs.
    Holding a subset of known states does not assert complete-state availability.
    """
    if not isinstance(request, CostRequest) or not isinstance(grid, QuantityGridInputs):
        raise ValueError("typed request and evidenced grid required")
    if not isinstance(fill_inputs, FillInputs) or not isinstance(extra_funding, tuple):
        raise ValueError("typed fills and immutable extra funding required")
    if positions is not None and not isinstance(positions, PositionInputs):
        raise ValueError("typed private positions required")
    if not isinstance(credits, tuple) or not all(isinstance(c, CreditInputs) for c in credits):
        raise ValueError("typed immutable credits required")
    data = scenario.to_dict() if hasattr(scenario, "to_dict") else deepcopy(scenario)
    if not isinstance(data, dict) or data.get("version") != "comparison-cashflows-1":
        raise ValueError("versioned S01 cashflows required")
    if type(leg_index) is not int or not 0 <= leg_index < len(data.get("legs", [])):
        raise ValueError("exact scenario leg index required")
    leg = data["legs"][leg_index]
    states = data["state_ids"]
    if not states or len(states) != len(set(states)) or set(leg["receipts"]) != set(states):
        raise ValueError("complete unique S01 state basis required")
    native_key = leg["native_key"]
    if native_key[:3] != [request.venue, request.event_id, request.market_id]:
        raise ValueError("cost_scenario_native_scope_conflict")
    registry = registry or load_cost_registry()
    if not isinstance(registry, CostRegistry):
        raise ValueError("typed cost registry required")
    resolution = registry.resolve(request, positions=positions, outcome_names=tuple(states))
    result = dict(version=VERSION, available=False, entry_available=False,
                  complete_state_available=False, reasons=list(resolution.reasons),
                  rule=resolution.to_dict(), portfolio_basis=request.portfolio_basis,
                  assumption=("standalone hypothetical portfolio; no other market positions" if
                              request.portfolio_basis == "standalone" else "complete scoped incremental portfolio"),
                  size_basis=dict(native_quantity=native_quantity, native_price=native_price,
                                  common_capital_ceiling_usd=ceiling_usd),
                  acquisition_usd=leg.get("acquisition_cash"), entry_fee_usd=None,
                  rounding_refund_usd=None, net_entry_fee_usd=None, capital=None,
                  states={s: dict(gross_return_usd=leg["receipts"][s], hold_return_usd=None,
                                  settlement_fee_usd=None, net_return_usd=None,
                                  net_profit_usd=None, reasons=[]) for s in states},
                  conditioning=deepcopy(data.get("conditioning")),
                  partition_complete=data.get("partition_complete") is True,
                  selection_basis=dict(native_key=list(native_key),
                                       profile_revision=leg.get("profile_revision"),
                                       state_ids=list(states),
                                       completion_conditions=deepcopy(data.get("completion_conditions"))),
                  dependencies=dict(cashflows=data.get("table_revision"),
                                    leg=leg.get("bound_revision"),
                                    cost_registry=revision(registry.data),
                                    positions=resolution.positions_reference),
                  credits_excluded_from_funding=[c.kind for c in credits],
                  gross_inputs_preserved=True)
    rule = resolution.rule
    if not resolution.entry_rule_inputs_available or rule is None:
        result["revision"] = revision(result)
        return result
    reasons = result["reasons"]
    try:
        reasons.extend(grid.reasons(native_quantity))
        price = exact(rule.unit.probability_price(native_price)) if rule.unit.unit != "stake_usd" else None
        if rule.unit.unit != "stake_usd":
            face = exact(rule.unit.dollar_face(native_quantity))
            result["size_basis"]["quantity_dollar_face"] = wire(face)
            if exact(leg["quantity"]) != face or leg["quantity_unit"] != "contracts":
                reasons.append("cost_scenario_quantity_unit_conflict")
            if grid.legal_price_tick is None:
                reasons.append("legal_price_grid_unknown")
            elif price % (exact(grid.legal_price_tick) / (exact(rule.unit.price_scale)
                          if rule.unit.unit == "fixed_point_contracts" else 1)) != 0:
                reasons.append("acquisition_price_off_legal_grid")
            if fill_inputs.basis == "unknown_split":
                reasons.extend(fill_inputs.reasons(rule.terms.aggregation))
                reasons.append("exact_fill_allocation_required")
            else:
                fill_face, acquisition, normalized = _parsed_fills(fills, request, fill_inputs)
                if fill_face != face:
                    reasons.append("fill_quantity_mismatch")
                if leg.get("acquisition_cash") is None or exact(leg["acquisition_cash"]) != acquisition:
                    reasons.append("cost_scenario_acquisition_mismatch")
                tick = (exact(grid.legal_price_tick) / (exact(rule.unit.price_scale)
                        if rule.unit.unit == "fixed_point_contracts" else 1)) if grid.legal_price_tick else None
                if tick is not None and any(exact(f["price"]) % tick for f in normalized):
                    reasons.append("fill_acquisition_price_off_legal_grid")
                if any(exact(f["price"]) < price for f in normalized):
                    reasons.append("fill_price_below_bound_acquisition_quote")
        else:
            if leg["quantity_unit"] != "usd_risk" or exact(leg["quantity"]) != exact(native_quantity):
                reasons.append("cost_scenario_quantity_unit_conflict")
            acquisition = exact(native_quantity)
            if leg.get("acquisition_cash") is None or exact(leg["acquisition_cash"]) != acquisition:
                reasons.append("cost_scenario_acquisition_mismatch")
            normalized = []
        entry_blockers = [r for r in reasons if r not in {"settlement_charge_inputs_required"}]
        if entry_blockers:
            result["reasons"] = list(dict.fromkeys(reasons))
            result["revision"] = revision(result)
            return result
        if rule.terms.basis == "net_gain":
            fee, refund, engine_ref = ZERO, ZERO, dict(engine="generic-fees-1")
        elif request.venue in {"kalshi", "polymarket_us", "novig"}:
            engine_acquisition, fee, refund, engine_ref = _venue_entry(
                rule, request, fills, fill_inputs, engine_context, engine_registry)
            if engine_acquisition != acquisition:
                raise ValueError("shared_engine_acquisition_mismatch")
        elif rule.source_kind == "controlled_scenario":
            fee = exact(authored_fee(rule.terms, normalized)["entry_fee"])
            refund, engine_ref = ZERO, dict(engine="generic-fees-1")
        else:
            raise ValueError("qualified_venue_engine_binding_required")
        components = (FundingComponent("acquisition:" + leg["bound_revision"], _monetary(wire(acquisition)), "acquisition", "entry"),
                      FundingComponent("entry-fee:" + leg["bound_revision"], _monetary(wire(fee)), "entry_fee", "entry"),
                      FundingComponent("rounding-refund:" + leg["bound_revision"], _monetary(wire(refund)), "deterministic_rounding_refund", "entry"))
        if any(not isinstance(c, FundingComponent) or c.kind in {"acquisition", "entry_fee", "deterministic_rounding_refund"}
               for c in extra_funding):
            raise ValueError("acquisition_and_entry_fee_are_already_counted")
        capital = CapitalInputs(components + extra_funding, ceiling_usd)
        result.update(entry_available=True, acquisition_usd=wire(acquisition), entry_fee_usd=wire(fee),
                      rounding_refund_usd=wire(refund), net_entry_fee_usd=wire(fee-refund), capital=capital.basis())
        result["dependencies"].update(engine=engine_ref, grid=revision(asdict(grid)),
                                      fills=revision(dict(inputs=asdict(fill_inputs), fills=fills)))
        result["credits_excluded_from_funding"].extend(engine_ref.get("credits_excluded_from_funding", []))
        reasons.extend(capital.reasons)
        deployed = exact(capital.deployed_usd)
        hold_total = sum((exact(c.amount_usd) for c in extra_funding if c.kind == "refundable_hold"), ZERO)
        returns = hold_returns_usd or {}
        if returns and set(returns) != set(states):
            raise ValueError("complete_hold_return_state_basis_required")
        known_receipts = {s: exact(v) for s, v in leg["receipts"].items() if v is not None}
        returned_holds = {}
        for state in states:
            returned = exact(returns[state]) if state in returns and returns[state] is not None else (ZERO if hold_total == 0 else None)
            if returned is not None and (returned < 0 or returned > hold_total):
                raise ValueError("hold_return_exceeds_funded_hold")
            returned_holds[state] = returned
        # Only the unreturned part of a prefunded hold is consumed cash. A fully
        # refunded hold changes the denominator, never the commission base.
        profits = {s: v + returned_holds[s] - deployed for s, v in known_receipts.items()
                   if returned_holds[s] is not None}
        state_fees = {s: ZERO for s in profits}
        if resolution.net_rule_inputs_available:
            if rule.terms.basis == "net_gain":
                # Each known state has its own commission base. An unknown
                # exceptional receipt cannot establish a fee in that state,
                # but does not invalidate the decisive states' exact charges.
                state_fees = _state_fees(rule.terms, request, positions, profits, normalized)
            if rule.settlement_status == "known_terms":
                if rule.settlement_treatment == "already_withheld_from_payout":
                    if leg.get("settlement_charge_already_withheld") is not True:
                        reasons.append("withheld_settlement_charge_attachment_required")
                else:
                    additional = _state_fees(rule.settlement_terms, request, positions, profits, normalized)
                    state_fees = {s: state_fees[s] + additional[s] for s in state_fees}
        for state, output in result["states"].items():
            if state not in known_receipts:
                output["reasons"].append("scenario_receipt_unknown")
                continue
            returned = returned_holds[state]
            if returned is None:
                output["reasons"].append("refundable_hold_return_unknown")
                continue
            output["hold_return_usd"] = wire(returned)
            if reasons:
                output["reasons"].extend(reasons)
                continue
            settlement = state_fees[state]
            net_return = known_receipts[state] + returned - settlement
            output.update(settlement_fee_usd=wire(settlement), net_return_usd=wire(net_return),
                          net_profit_usd=wire(net_return-deployed))
        result["available"] = not reasons and any(s["net_profit_usd"] is not None for s in result["states"].values())
        result["complete_state_available"] = (result["available"] and result["partition_complete"] and
                                              all(s["net_profit_usd"] is not None for s in result["states"].values()))
    except (ValueError, KeyError) as error:
        reasons.append(str(error))
        result["available"] = result["complete_state_available"] = False
    result["reasons"] = list(dict.fromkeys(reasons))
    result["revision"] = revision(result)
    return result


def entry_fee_bounds(request, *, registry, fills, fill_inputs, engine_context=None,
                     engine_registry=None, quantity_dollar_face, bound=None):
    """Separate, quantity-bound entry sensitivity; never complete net authority."""
    resolution = registry.resolve(request)
    result = dict(version=VERSION, available=False, lower_usd=None, upper_usd=None,
                  exact_fee_usd=None, quantity_dollar_face=quantity_dollar_face,
                  qualification="conditional entry fee bound; independent costs/payout/depth gates remain",
                  reasons=list(resolution.reasons))
    rule = resolution.rule
    if rule is None or not resolution.entry_rule_inputs_available:
        return result
    try:
        if request.venue == "polymarket_us" and request.role == "taker":
            # The single-order cap is valid despite unknown counterparty split.
            if rule.terms.aggregation != "cumulative_order_cap" or rule.terms.basis != "quadratic":
                raise ValueError("us_single_order_cap_terms_conflict")
            orders = {}
            for fill in fills:
                if not isinstance(fill.get("order_id"), str) or not fill["order_id"]:
                    raise ValueError("order_cap_bound_requires_explicit_order_scope")
                if fill.get("role", "taker") != "taker":
                    raise ValueError("us_taker_bound_role_conflict")
                orders.setdefault(fill["order_id"], []).append(fill)
            bounds = [us_taker_bound(group, coefficient=rule.terms.rate) for group in orders.values()]
            if not bounds:
                raise ValueError("bounded explicit fill list required")
            value = dict(lower="0", upper=wire(sum((exact(b["upper"]) for b in bounds), ZERO)),
                         quantity=wire(sum((exact(b["quantity"]) for b in bounds), ZERO)))
        elif request.venue == "kalshi":
            if engine_context is None or engine_registry is None:
                raise ValueError("shared_venue_engine_binding_required")
            context = deepcopy(engine_context)
            context.update(fills=deepcopy(fills), complete_order_history=fill_inputs.complete_order_history)
            checked_context = dict(context, balance_precision="0.0001")
            _venue_entry(rule, request, fills, fill_inputs, checked_context, engine_registry)
            value = calculate_envelope(context, engine_registry,
                                       execution_split_known=fill_inputs.basis != "unknown_split")
            if not value["available"]:
                raise ValueError(value["reason"])
        elif bound is not None:
            blocked = bound.reasons(calculation_time=request.calculation_time,
                                    quantity_dollar_face=quantity_dollar_face,
                                    aggregation=rule.terms.aggregation)
            if blocked:
                raise ValueError(",".join(blocked))
            value = dict(lower=bound.lower_usd, upper=bound.upper_usd)
        else:
            raise ValueError("supported_fragmentation_bound_required")
        if "quantity" in value and exact(value["quantity"]) != exact(quantity_dollar_face):
            raise ValueError("cost_bound_quantity_mismatch")
        result.update(available=True, lower_usd=value["lower"], upper_usd=value["upper"])
    except (ValueError, KeyError) as error:
        result["reasons"].append(str(error))
    return result
