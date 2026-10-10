"""Exact state-weighted benchmark estimates beside independently qualified EV.

D08 owns proportional no-vig weights; S02 owns net costs, S03 owns original
clock/depth gates, and settlement owns cashflow aggregation. Two-way market
weights cannot become tie, push or exceptional probability mass.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction

from app.comparison.buffers import age_gate
from app.comparison.cashflows import ScenarioCashflows, _digest, _shared_result, exact_wire
from app.comparison.domain import EvidenceReference, ExactNumber
from app.comparison.event_links import instant
from app.comparison.pinnacle import ReferenceSet, bind

VERSION = "comparison-net-ev-1"
PROBABILITY_VERSION = "comparison-state-probabilities-1"
KINDS = {"independent_model", "independently_qualified_states", "authored_sensitivity"}


@dataclass(frozen=True)
class ProbabilityInputs:
    """Independent state distribution, never the two-way benchmark weights.

    Complete means every state in one exact D04 terminal partition. Conditional
    means an explicit subset with its condition named. Authored sensitivity is
    inspectable arithmetic and can never enter ordinary ranking.
    """
    kind: str
    partition_revision: str
    coverage: str
    conditioning: str
    probabilities: tuple[tuple[str, ExactNumber], ...]
    evidence: tuple[EvidenceReference, ...]
    effective_from: str
    effective_until: str | None
    ranking_qualified: bool

    def __post_init__(self):
        if self.kind not in KINDS or self.coverage not in {"complete", "conditional"}:
            raise ValueError("Explicit probability kind and partition coverage required")
        if not isinstance(self.partition_revision, str) or not self.partition_revision:
            raise ValueError("Exact payout partition revision required")
        if not isinstance(self.conditioning, str) or not self.conditioning.strip():
            raise ValueError("Named probability conditioning required")
        if (not isinstance(self.probabilities, tuple) or not 1 <= len(self.probabilities) <= 64
                or any(not isinstance(pair, tuple) or len(pair) != 2 or not isinstance(pair[0], str)
                       or not pair[0] or not isinstance(pair[1], ExactNumber) for pair in self.probabilities)
                or len({key for key, _ in self.probabilities}) != len(self.probabilities)):
            raise ValueError("Bounded distinct exact state probabilities required")
        if (not isinstance(self.evidence, tuple) or not 1 <= len(self.evidence) <= 32
                or any(not isinstance(item, EvidenceReference) for item in self.evidence)):
            raise ValueError("Independent probability provenance required")
        if type(self.ranking_qualified) is not bool:
            raise ValueError("Explicit independent probability ranking qualification required")
        if self.ranking_qualified and (self.kind == "authored_sensitivity" or all(item.evidence_class == "authored" for item in self.evidence)):
            raise ValueError("Authored probability sensitivity has no ranking authority")
        start = instant(self.effective_from)
        if self.effective_until is not None and instant(self.effective_until) <= start:
            raise ValueError("Positive independent probability interval required")

    def to_dict(self):
        return dict(version=PROBABILITY_VERSION, kind=self.kind, partition_revision=self.partition_revision,
                    coverage=self.coverage, conditioning=self.conditioning,
                    probabilities={key: value.original for key, value in self.probabilities},
                    evidence=[item.to_dict() for item in self.evidence],
                    effective_from=self.effective_from, effective_until=self.effective_until,
                    ranking_qualified=self.ranking_qualified)

    @classmethod
    def from_dict(cls, value):
        fields = {"version", "kind", "partition_revision", "coverage", "conditioning", "probabilities",
                  "evidence", "effective_from", "effective_until", "ranking_qualified"}
        if (not isinstance(value, dict) or set(value) != fields or value["version"] != PROBABILITY_VERSION
                or not isinstance(value["probabilities"], dict) or not isinstance(value["evidence"], list)):
            raise ValueError("Versioned independent probability input required")
        return cls(**{key: value[key] for key in fields - {"version", "probabilities", "evidence"}},
                   probabilities=tuple((key, ExactNumber.parse(amount)) for key, amount in value["probabilities"].items()),
                   evidence=tuple(EvidenceReference.from_dict(item) for item in value["evidence"]))

    @property
    def revision(self):
        return _digest(self.to_dict())


def _expectation(buckets):
    # Each already-validated probability weights its own scenario profit. The
    # existing engine performs the aggregation in an exact common integer unit.
    contributions = tuple({"weighted_expectation": probability * profit} for probability, profit in buckets)
    result = _shared_result(tuple(Fraction(0) for _ in contributions), contributions,
                            ("weighted_expectation",), complete=False, reserve=Fraction(0))
    return Fraction(result["states"]["weighted_expectation"])


def _reviewed_reference(selection, reference, at):
    if not isinstance(reference, ReferenceSet):
        return dict(available=False, reason="exact_reference_inputs_unavailable")
    selected = selection
    # Inclusive winner/line sides can share a strict decisive bucket, while
    # their own equality payout remains in the scenario table and excluded here.
    if selected.predicate.operator in {"ge", "le"}:
        selected = replace(selected, predicate=replace(selected.predicate,
                           operator="gt" if selected.predicate.operator == "ge" else "lt"))
    out = bind(selected, reference, at)
    out["decisive_projection"] = selected.predicate.operator != selection.predicate.operator
    out["original_operator"] = selection.predicate.operator
    return out


def _reference_buckets(inputs, reference, binding, profits):
    buckets = []
    covered = set()
    for outcome, raw_weight in zip(reference.outcomes, binding["probabilities"]):
        predicate = outcome.selection.predicate
        threshold = predicate.threshold.value
        states = []
        for state in inputs.table.states:
            if state.terminal != "completed":
                continue
            interval = state.score_range
            admitted = (predicate.operator == "gt" and interval.lower is not None and interval.lower > threshold or
                        predicate.operator == "lt" and interval.upper is not None and interval.upper < threshold or
                        predicate.operator == "eq" and interval.lower == interval.upper and interval.lower is not None and interval.lower == threshold)
            if admitted:
                if state.state_id in covered:
                    raise ValueError("overlapping_reference_probability_regions")
                states.append(state.state_id)
                covered.add(state.state_id)
        if not states:
            raise ValueError("reference_probability_region_not_represented")
        values = [profits[state] for state in states]
        if any(value is None for value in values):
            raise ValueError("required_state_net_profit_unknown")
        if len(set(values)) != 1:
            raise ValueError("reference_weights_cannot_split_differing_score_cashflows")
        buckets.append(dict(state_ids=states, probability=str(Fraction(raw_weight)),
                            profit_usd=exact_wire(values[0]), reference_instrument=outcome.selection.native.instrument_id))
    return buckets, tuple(state for state in inputs.state_ids if state not in covered)


def _independent_buckets(inputs, probability, at, profits):
    if not isinstance(probability, ProbabilityInputs) or probability.partition_revision != inputs.table.revision:
        raise ValueError("independent_probability_partition_revision_conflict")
    if at < instant(probability.effective_from) or (probability.effective_until is not None and at >= instant(probability.effective_until)):
        raise ValueError("independent_probability_expired_or_not_effective")
    states = {state for state, _ in probability.probabilities}
    if not states <= set(inputs.state_ids):
        raise ValueError("probability_state_outside_feasible_partition")
    # Validate partition membership/completeness before accepting the sum.
    if probability.coverage == "complete" and (not inputs.partition_complete or states != set(inputs.state_ids)):
        raise ValueError("complete_probability_partition_incomplete")
    weights = tuple(value.value for _, value in probability.probabilities)
    if any(value < 0 or value > 1 for value in weights) or sum(weights, Fraction(0)) != 1:
        raise ValueError("probabilities_must_sum_exactly_one")
    if any(profits[state] is None for state in states):
        raise ValueError("required_state_net_profit_unknown")
    return [dict(state_ids=[state], probability=str(value.value), profit_usd=exact_wire(profits[state]))
            for state, value in probability.probabilities], tuple(state for state in inputs.state_ids if state not in states)


def estimated_net_ev(inputs: ScenarioCashflows, costs: dict, reference: ReferenceSet | None, *,
                     at: datetime, live: bool = False, execution_source_at: str | None = None,
                     probability: ProbabilityInputs | None = None, buffer: dict | None = None,
                     buffer_revision: str | None = None, funded_denominator: str | None = None) -> dict:
    """One selection's exact net return, with independent and benchmark bases.

    Base net ranking is a disclosed common-size hypothetical estimate. Original
    depth additionally qualifies the conservative ranking; absence of depth
    never claims a depth-qualified size or a likely fill.
    """
    if not isinstance(inputs, ScenarioCashflows) or not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("Reviewed scenario and aware EV evaluation instant required")
    inputs.validate()
    if type(live) is not bool:
        raise ValueError("Explicit pregame/live phase required")
    if probability is not None and not isinstance(probability, ProbabilityInputs):
        raise ValueError("Typed independent probability inputs required")
    if len(inputs.legs) != 1:
        raise ValueError("Selection EV requires one exact scenario leg")
    leg = inputs.legs[0]
    phase = "live" if live else "pregame"
    out = dict(version=VERSION, available=False, ranking_eligible=False, conservative_ranking_eligible=False,
               label=("model EV" if probability.kind == "independent_model" else "authored sensitivity EV" if probability.kind == "authored_sensitivity" else "independently qualified EV") if probability is not None else "estimated net benchmark EV",
               exact=None, expected_profit_usd=None, value=None, capital_denominator=None,
               reason=None, reasons=[], conditioning=None, probability_basis=None, fee_basis=None,
               size_basis=deepcopy(costs.get("size_basis")) if isinstance(costs, dict) else None,
               estimate_class="standalone_hypothetical_portfolio", depth_qualified=False,
               dependency_revisions=dict(scenario=inputs.revision, payout_table=inputs.table.revision,
                    leg=leg.bound_revision, profile=leg.profile_revision,
                    reference=reference.revision if isinstance(reference, ReferenceSet) else None,
                    costs=costs.get("revision") if isinstance(costs, dict) else None,
                    buffer=buffer.get("revision") if isinstance(buffer, dict) else buffer_revision,
                    probability=probability.revision if probability is not None else None,
                    execution_source_at=execution_source_at, evaluated_at=at.isoformat(),
                    funded_denominator=funded_denominator),
               gross_decisive_benchmark=None, details=dict(scenario=inputs.to_dict(),
                    qualification="Hypothetical fully acquired selected size; no fill, account fee, probability accuracy or realized-return promise"))
    def finish(reason=None):
        if reason is not None:
            out["reason"] = reason
            out["reasons"].append(reason)
        out["revision"] = _digest({key: value for key, value in out.items() if key != "revision"})
        return out

    # Preserve the subordinate old-age gross benchmark even when future net is
    # withheld by the stricter age or cost gates.
    from app.comparison.domain import CanonicalSelection
    selection = CanonicalSelection.from_dict(leg.selection)
    binding = _reviewed_reference(selection, reference, at)
    out["details"]["reference"] = deepcopy(binding)
    if binding.get("available"):
        try:
            buckets, excluded = _reference_buckets(inputs, reference, binding, dict(leg.profits))
            gross = _expectation(tuple((Fraction(row["probability"]), Fraction(row["profit_usd"])) for row in buckets))
            capital = leg.acquisition_cash
            out["gross_decisive_benchmark"] = dict(available=capital > 0, expected_profit_usd=exact_wire(gross),
                    return_percent=exact_wire(gross / capital * 100) if capital > 0 else None,
                    conditioning="completed_decisive_results_only" if len(reference.outcomes) == 2 else "completed_three_way_results_only",
                    excluded_state_ids=list(excluded), probabilities=buckets,
                    method="Pinnacle proportional no-vig", maximum_age_seconds=1800,
                    fee_basis="gross_excludes_fees", selected_odds=binding["selected_odds"])
        except ValueError as error:
            out["gross_decisive_benchmark"] = dict(available=False, reason=str(error))
    else:
        out["gross_decisive_benchmark"] = dict(available=False, reason=binding["reason"])

    if at < instant(leg.profile_effective_from) or (leg.profile_effective_until is not None and at >= instant(leg.profile_effective_until)):
        return finish("payout_profile_expired_or_not_effective")
    source_age = age_gate(execution_source_at, phase=phase, at=at)
    out["details"]["execution_age"] = source_age
    if not source_age["eligible"]:
        return finish(source_age["reasons"][0])
    if (not isinstance(costs, dict) or costs.get("version") != "comparison-net-costs-1"
            or costs.get("revision") != _digest({key: value for key, value in costs.items() if key != "revision"})):
        return finish("reviewed_cost_result_unavailable_or_revision_conflict")
    if not costs.get("available"):
        out["details"]["cost_reasons"] = costs.get("reasons", [])
        return finish("required_net_costs_unavailable")
    resolution = costs.get("rule")
    rule = resolution.get("rule") if isinstance(resolution, dict) else None
    if not isinstance(rule, dict):
        return finish("exact_fee_rule_unavailable")
    if (rule.get("effective_from") is not None and at < instant(rule["effective_from"]) or
            any(rule.get(key) is not None and at >= instant(rule[key]) for key in ("effective_to", "expires_at"))):
        return finish("fee_rule_expired_or_not_effective")
    cost_dependencies = costs.get("dependencies")
    if (not isinstance(cost_dependencies, dict) or cost_dependencies.get("cashflows") != inputs.table.revision
            or cost_dependencies.get("leg") != leg.bound_revision):
        return finish("cost_scenario_dependency_conflict")
    states = costs.get("states")
    if not isinstance(states, dict) or set(states) != set(inputs.state_ids):
        return finish("cost_state_partition_conflict")
    try:
        capital = Fraction(costs["capital"]["deployed_capital_usd"])
        if capital <= 0:
            return finish("positive_deployed_capital_required")
        if Fraction(costs["acquisition_usd"]) != leg.acquisition_cash:
            return finish("cost_acquisition_revision_conflict")
        valid_buffer = (isinstance(buffer, dict) and buffer.get("version") == "comparison-buffers-1"
                        and buffer.get("revision") == _digest({key: value for key, value in buffer.items() if key != "revision"})
                        and costs["revision"] in {part.get("revision") for part in (buffer.get("base"), buffer.get("conservative")) if isinstance(part, dict)})
        denominator = capital
        if funded_denominator is not None:
            if (not valid_buffer or not isinstance(buffer.get("sensitivity"), dict)
                    or buffer["sensitivity"].get("denominator_usd") is None
                    or Fraction(funded_denominator) != Fraction(buffer["sensitivity"]["denominator_usd"])):
                return finish("shared_sensitivity_funded_basis_unavailable")
            denominator = Fraction(funded_denominator)
            if denominator < capital or denominator > Fraction(costs["capital"]["ceiling_usd"]):
                return finish("shared_sensitivity_funded_basis_outside_capital_bounds")
        gross_receipts = dict(leg.receipts)
        profits = {}
        for state, row in states.items():
            gross_amount = None if row["gross_return_usd"] is None else Fraction(row["gross_return_usd"])
            if gross_amount != gross_receipts[state]:
                return finish("cost_payout_attachment_conflict")
            profits[state] = None if row["net_profit_usd"] is None else Fraction(row["net_profit_usd"])
            if profits[state] is not None and (row["net_return_usd"] is None or Fraction(row["net_return_usd"]) - capital != profits[state]):
                return finish("cost_profit_capital_basis_conflict")
        if probability is not None:
            buckets, excluded = _independent_buckets(inputs, probability, at, profits)
            conditioning = probability.conditioning
            probability_basis = probability.kind
            qualified = probability.ranking_qualified
            out["details"]["independent_probability"] = probability.to_dict()
        else:
            if not binding.get("available"):
                return finish(binding["reason"])
            ages = [age_gate(item.source_at, phase=phase, at=at) for item in reference.outcomes]
            out["details"]["reference_ages"] = ages
            if any(not age["eligible"] for age in ages):
                return finish("reference_" + next(age["reasons"][0] for age in ages if not age["eligible"]))
            buckets, excluded = _reference_buckets(inputs, reference, binding, profits)
            conditioning = "completed_decisive_results_only" if len(reference.outcomes) == 2 else "completed_three_way_results_only"
            probability_basis = "Pinnacle_proportional_no_vig_market_benchmark"
            qualified = True
        expected = _expectation(tuple((Fraction(row["probability"]), Fraction(row["profit_usd"])) for row in buckets))
        percent = expected / denominator * 100
        out.update(available=True, ranking_eligible=qualified, expected_profit_usd=exact_wire(expected),
                   exact=dict(numerator=str(percent.numerator), denominator=str(percent.denominator)),
                   value=exact_wire(percent), capital_denominator=exact_wire(denominator), conditioning=conditioning,
                   probability_basis=probability_basis, fee_basis=deepcopy(costs["rule"]),
                   estimate_class=costs.get("assumption", "standalone hypothetical portfolio"))
        out["details"].update(probability_buckets=buckets, excluded_state_ids=list(excluded),
                 unknown_probability_mass="excluded tie/push/exceptional mass remains unknown" if excluded else None,
                 state_costs=deepcopy(states), capital=deepcopy(costs["capital"]),
                 actual_required_capital_usd=exact_wire(capital),
                 refundable_sensitivity_allowance_usd=exact_wire(denominator - capital),
                 denominator_basis="actual_deployed_capital" if funded_denominator is None else "shared_prefunded_sensitivity_capital",
                 partition_class="complete_terminal_state_EV" if probability is not None and probability.coverage == "complete" else "conditional_EV")
        if isinstance(buffer, dict):
            out["depth_qualified"] = bool(valid_buffer and buffer.get("depth", {}).get("depth_qualified"))
            out["conservative_ranking_eligible"] = bool(qualified and valid_buffer and buffer.get("depth_qualified_ranking_available"))
            out["details"]["buffer_reasons"] = buffer.get("reasons", []) + buffer.get("depth", {}).get("reasons", [])
        else:
            out["details"]["buffer_reasons"] = ["depth_inputs_unavailable"]
        return finish()
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as error:
        return finish(str(error))
