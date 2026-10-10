"""D04 scenario inputs adapted to the existing settlement portfolio engine.

The only arithmetic here is unit conversion and exact wire scaling. Partition
construction remains in D04, and portfolio aggregation remains in settlement.
Rules need not be identical: each state retains each leg's own payout.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from hashlib import sha256
import json
from math import lcm

from app.settlement import portfolio
from .domain import ExactNumber, Quantity
from .payouts import BoundLeg, JointTable, joint_states

VERSION = "comparison-cashflows-1"
MAX_SCALED_DIGITS = 90  # sum of eight legs stays exact in the shared 100-digit engine


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _number(value):
    if isinstance(value, ExactNumber):
        return value.value
    if isinstance(value, Fraction):
        return value
    return ExactNumber.parse(value).value


def exact_wire(value):
    """Emit exact dollars: terminating decimal when possible, otherwise rational."""
    if value is None:
        return None
    value = _number(value)
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        return str(value)
    places = max(twos, fives)
    integer = abs(value.numerator) * (10 ** places // value.denominator)
    digits = str(integer).zfill(places + 1)
    result = digits if places == 0 else (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")
    return ("-" if value < 0 else "") + result


@dataclass(frozen=True)
class ScenarioLeg:
    native_key: tuple[str, ...]
    bound_revision: str
    quantity: ExactNumber
    quantity_unit: str
    acquisition_cash: Fraction
    receipts: tuple[tuple[str, Fraction | None], ...]
    profits: tuple[tuple[str, Fraction | None], ...]
    reasons: tuple[tuple[str, str], ...]
    price: dict
    payout_reference: dict
    profile_revision: str
    profile_effective_from: str
    profile_effective_until: str | None
    selection: dict

    def to_dict(self):
        return dict(native_key=list(self.native_key), bound_revision=self.bound_revision,
                    quantity=self.quantity.original, quantity_unit=self.quantity_unit,
                    acquisition_cash=exact_wire(self.acquisition_cash),
                    receipts={key: exact_wire(value) for key, value in self.receipts},
                    profits={key: exact_wire(value) for key, value in self.profits},
                    reasons=dict(self.reasons), price=deepcopy(self.price),
                    payout_reference=deepcopy(self.payout_reference), profile_revision=self.profile_revision,
                    profile_effective_from=self.profile_effective_from, profile_effective_until=self.profile_effective_until,
                    selection=deepcopy(self.selection))


@dataclass(frozen=True)
class ScenarioCashflows:
    table: JointTable
    legs: tuple[ScenarioLeg, ...]
    revision: str

    def __post_init__(self):
        self.validate()

    def validate(self):
        if (not isinstance(self.table, JointTable) or not isinstance(self.legs, tuple)
                or not self.legs or any(not isinstance(leg, ScenarioLeg) for leg in self.legs)
                or tuple(leg.bound_revision for leg in self.legs) != self.table.leg_revisions
                or any(tuple(key for key, _ in leg.receipts) != self.state_ids for leg in self.legs)
                or self.revision != _digest(dict(version=VERSION, table=self.table.to_dict(),
                                                legs=[leg.to_dict() for leg in self.legs]))):
            raise ValueError("Scenario inputs have changed or carry a conflicting dependency revision")

    @property
    def state_ids(self):
        return tuple(state.state_id for state in self.table.states)

    @property
    def partition_complete(self):
        return self.table.coverage != "conditional_completed"

    def to_dict(self):
        self.validate()
        table = deepcopy(self.table.to_dict())
        return dict(version=VERSION, revision=self.revision, table_revision=self.table.revision,
                    state_ids=list(self.state_ids), partition_complete=self.partition_complete,
                    coverage=self.table.coverage, conditioning="all_modeled_terminal_states" if self.partition_complete else "completed_results_only",
                    universe=table["universe"], evaluated_at=self.table.evaluated_at,
                    leg_revisions=list(self.table.leg_revisions),
                    completion_conditions=table["completion_conditions"],
                    legs=[leg.to_dict() for leg in self.legs], states=table["states"],
                    calculation_basis="Gross returned USD and acquisition only; fees, holds, depth and probabilities are separate inputs")


def cashflow_inputs(legs: tuple[BoundLeg, ...], quantities: tuple[str | ExactNumber | Quantity, ...], *,
                    at: datetime, include_exceptions: bool = True, table: JointTable | None = None) -> ScenarioCashflows:
    """Bind one exact native quantity to each leg and validate the whole partition.

    Bare exact strings follow the evidenced profile unit: contracts or USD stake.
    Typed Quantity must explicitly use contracts or usd_risk, respectively. A
    caller-supplied table must equal the current D04 table, including its clock.
    """
    reviewed = joint_states(legs, at=at, include_exceptions=include_exceptions)
    if table is not None and (not isinstance(table, JointTable) or table != reviewed):
        raise ValueError("Joint table does not equal the applicable disjoint exhaustive D04 partition")
    if not isinstance(quantities, tuple) or len(quantities) != len(legs):
        raise ValueError("Exactly one evidenced native quantity per leg required")
    rows = []
    for index, (bound, quantity) in enumerate(zip(legs, quantities)):
        unit = "contracts" if bound.profile.payout_unit == "usd_per_contract" else "usd_risk"
        if isinstance(quantity, Quantity):
            if quantity.unit != unit:
                raise ValueError("Native quantity/payout unit conflict")
            quantity = quantity.amount
        elif not isinstance(quantity, ExactNumber):
            quantity = ExactNumber.parse(quantity)
        if quantity.value <= 0:
            raise ValueError("Positive acquired quantity required; zero legs cannot qualify a portfolio")
        price = bound.selection.price
        per_unit = (price.amount.value / (100 if price.unit == "cents_per_contract" else 1)) if unit == "contracts" else Fraction(1)
        acquisition = per_unit * quantity.value
        receipts, profits, reasons = [], [], []
        for state in reviewed.states:
            cell = state.payouts[index]
            receipt = None if cell.value is None else cell.value.value * quantity.value
            receipts.append((state.state_id, receipt))
            profits.append((state.state_id, None if receipt is None else receipt - acquisition))
            if cell.reason:
                reasons.append((state.state_id, cell.reason))
        rows.append(ScenarioLeg(bound.selection.native.key, bound.revision, quantity, unit,
                                acquisition, tuple(receipts), tuple(profits), tuple(reasons),
                                price.to_dict(), bound.selection.payout.to_dict(), bound.profile.revision,
                                bound.profile.effective_from, bound.profile.effective_until,
                                bound.selection.to_dict()))
    content = dict(version=VERSION, table=reviewed.to_dict(), legs=[row.to_dict() for row in rows])
    return ScenarioCashflows(reviewed, tuple(rows), _digest(content))


def _shared_result(cash, receipts, states, *, complete, reserve):
    """Use one exact common integer scale; no rational rounding before ranking."""
    values = [value for value in [*cash, reserve, *(value for row in receipts for value in row.values())] if value is not None]
    scale = lcm(*(value.denominator for value in values))
    scaled = lambda value: None if value is None else str(value.numerator * (scale // value.denominator))
    if any(len(scaled(value).lstrip("-")) > MAX_SCALED_DIGITS for value in values):
        raise ValueError("Exact common monetary scale exceeds bounded shared-engine precision")
    result = portfolio([dict(cash=scaled(cost), receipts={state: scaled(row[state]) for state in states})
                        for cost, row in zip(cash, receipts)], states, complete=complete, reserve=scaled(reserve))
    # Shared engine dollars were supplied in integer-scaled units. Restore each
    # dollar field; derive ratios from those exact shared-engine dollar outputs.
    money_fields = ("committed_cash", "acquisition_cash", "settlement_liability_funding", "return_denominator",
                    "minimum_known_return", "worst_case_return", "expected_net")
    for name in money_fields:
        result[name] = exact_wire(None if result[name] is None else Fraction(result[name]) / scale)
    result["states"] = {state: exact_wire(None if amount is None else Fraction(amount) / scale) for state, amount in result["states"].items()}
    denominator = None if result["return_denominator"] is None else Fraction(result["return_denominator"])
    for percentage, dollars in (("return_pct", "worst_case_return"), ("ev_pct", "expected_net")):
        amount = result[dollars]
        result[percentage] = exact_wire(Fraction(amount) / denominator * 100) if amount is not None and denominator else None
    result["arithmetic"] = "shared_settlement_portfolio_with_exact_integer_scale"
    return result


def evaluate_portfolio(inputs: ScenarioCashflows, *, cash: tuple | None = None, receipts: tuple | None = None,
                       reserve: str = "0", fee_basis: str = "gross_excludes_fees") -> dict:
    """Evaluate gross or S02-provided costs/receipts through shared settlement.

    Overrides are explicit ordered tuples, one entry per leg. They must cover
    exactly the reviewed states. Unknown amounts remain None, including a state
    omitted by an upstream cost qualification. No probability is inferred here.
    """
    if not isinstance(inputs, ScenarioCashflows):
        raise ValueError("Reviewed ScenarioCashflows required")
    inputs.validate()
    if not isinstance(fee_basis, str) or not fee_basis.strip():
        raise ValueError("Explicit fee basis required")
    if cash is None:
        cash = tuple(leg.acquisition_cash for leg in inputs.legs)
    if receipts is None:
        receipts = tuple(dict(leg.receipts) for leg in inputs.legs)
    if (not isinstance(cash, tuple) or not isinstance(receipts, tuple)
            or len(cash) != len(inputs.legs) or len(receipts) != len(inputs.legs)):
        raise ValueError("Exactly one cash/receipt mapping per leg required")
    states = inputs.state_ids
    if any(not isinstance(row, dict) or set(row) != set(states) for row in receipts):
        raise ValueError("Receipt set must exactly equal the reviewed state partition")
    costs = tuple(None if amount is None else _number(amount) for amount in cash)
    if any(amount is not None and amount < 0 for amount in costs):
        raise ValueError("Negative committed acquisition cash")
    rows = tuple({state: None if amount is None else _number(amount) for state, amount in row.items()} for row in receipts)
    reserved = _number(reserve)
    if reserved < 0:
        raise ValueError("Negative consumed reserve")
    full = _shared_result(costs, rows, states, complete=inputs.partition_complete, reserve=reserved)
    known = tuple(state for state in states if all(row[state] is not None for row in rows))
    conditional = _shared_result(costs, rows, known, complete=True, reserve=reserved) if known else None
    if conditional is not None:
        conditional.update(coverage_complete=False, conditioning="listed_known_states_only", state_ids=list(known),
                           qualification="Conditional calculation over the listed known states; no all-modeled-outcome claim")
    dependency = dict(scenario_revision=inputs.revision, table_revision=inputs.table.revision,
                      leg_revisions=list(inputs.table.leg_revisions), fee_basis=fee_basis,
                      cash=[exact_wire(amount) for amount in costs],
                      receipts=[{state: exact_wire(amount) for state, amount in row.items()} for row in rows],
                      reserve=exact_wire(reserved))
    return dict(version=VERSION, revision=_digest(dependency), dependency_revisions=dependency,
                partition_complete=inputs.partition_complete, coverage=inputs.table.coverage,
                fee_basis=fee_basis, full=full, conditional=conditional,
                all_modeled_outcome_profitable=full["mathematical_arbitrage"] and inputs.partition_complete,
                conditional_profitable=bool(conditional and conditional["mathematical_arbitrage"]),
                estimate_class="contains_estimated_payouts" if any(cell.status == "estimated" for state in inputs.table.states for cell in state.payouts) else "evidenced_or_local_unknown_payouts")
