"""D09 versioned, offline cost inputs; no venue acquisition or UI net binding.

Research proposals cannot become numeric runtime schedules through selection.
Controlled examples use the existing shared fee algebra, never provider labels.
Private portfolio inputs are explicit and only a digest enters shared audits.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Context, Decimal, localcontext
from importlib.resources import files
import hashlib
import json
import re

from app.comparison.domain import EvidenceReference, ExactNumber
from app.fees.engine import generic_fee, number


VERSION = "comparison-cost-inputs-1"
ZERO = Decimal("0")
ACCOUNT_REF = re.compile(r"account:[A-Za-z0-9_-]{1,64}\Z")


def _number(value, *, minimum=None):
    ExactNumber.parse(value)
    # The shared engine's native-input bound keeps every conversion and bounded
    # 10,000-component sum exact under the 100-digit arithmetic context. Wider
    # D01 rational/derived numbers must not be rounded into monetary inputs.
    result = number(value)
    if minimum is not None and result < minimum:
        raise ValueError("cost number below supported minimum")
    return result


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("timezone-aware exact cost instant required")
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.utcoffset() is None:
        raise ValueError("timezone-aware exact cost instant required")
    return instant


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("required cost field: " + name)
    return value


def _bool(value, name):
    if type(value) is not bool:
        raise ValueError("explicit boolean required: " + name)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _account(value):
    if value is not None and (not isinstance(value, str) or not ACCOUNT_REF.fullmatch(value)):
        raise ValueError("opaque account reference required; no identity or credential fields")


@dataclass(frozen=True)
class UnitSpec:
    """Native quantity mapping; fixed-point scales are explicit instrument facts."""
    unit: str
    face_usd_per_native: str | None = None
    quantity_scale: str | None = None
    price_scale: str | None = None

    def __post_init__(self):
        if self.unit not in {"dollar_face_contracts", "novig_v3_cent_contracts",
                             "fixed_point_contracts", "stake_usd"}:
            raise ValueError("unsupported cost quantity unit")
        expected = {"dollar_face_contracts": "1", "novig_v3_cent_contracts": "0.01"}
        if self.unit in expected and self.face_usd_per_native != expected[self.unit]:
            raise ValueError("native face conversion conflict")
        if self.unit == "fixed_point_contracts":
            if self.face_usd_per_native != "1":
                raise ValueError("fixed-point contract requires explicit one-dollar face")
            self._scale(self.quantity_scale)
            self._scale(self.price_scale)
        elif self.quantity_scale is not None or self.price_scale is not None:
            raise ValueError("scales apply only to fixed-point native units")
        if self.unit == "stake_usd" and self.face_usd_per_native is not None:
            raise ValueError("sportsbook stake is not a face-payout unit")

    @staticmethod
    def _scale(value):
        if not isinstance(value, str) or not value.isdigit() or not 1 <= int(value) <= 10**9:
            raise ValueError("positive bounded instrument scale string required")
        return Decimal(value)

    def dollar_face(self, amount):
        value = _number(amount, minimum=ZERO)
        if self.unit == "stake_usd":
            raise ValueError("stake-to-payout conversion requires separate evidenced payout terms")
        if self.unit in {"novig_v3_cent_contracts", "fixed_point_contracts"} and value != value.to_integral_value():
            raise ValueError("native quantity must be an exact wire integer")
        with localcontext(Context(prec=100)):
            scale = self._scale(self.quantity_scale) if self.unit == "fixed_point_contracts" else Decimal("1")
            return str(value * _number(self.face_usd_per_native) / scale)

    def probability_price(self, amount):
        value = _number(amount)
        if self.unit == "fixed_point_contracts":
            if value != value.to_integral_value():
                raise ValueError("native price must be an exact wire integer")
            with localcontext(Context(prec=100)):
                value /= self._scale(self.price_scale)
        if not ZERO < value < 1:
            raise ValueError("normalized acquisition price must be between zero and one")
        return str(value)


@dataclass(frozen=True)
class FeeTerms:
    """An explicit fee algebra input, not a provider fee engine replacement."""
    basis: str
    rate: str | None
    grid_usd: str | None
    rounding: str | None
    aggregation: str | None
    role: str
    allow_fee_adjustment: bool = False

    def __post_init__(self):
        if self.basis not in {"notional", "quantity", "quadratic", "net_gain"}:
            raise ValueError("unsupported cost charge basis")
        if self.role not in {"maker", "taker"}:
            raise ValueError("explicit maker/taker assumption required")
        if self.rate is not None:
            _number(self.rate, minimum=ZERO)
        if self.grid_usd is not None and _number(self.grid_usd) <= ZERO:
            raise ValueError("positive USD rounding grid required")
        if self.rounding not in {None, "ceiling", "floor", "half_even", "half_up"}:
            raise ValueError("unknown cost rounding")
        if self.aggregation not in {None, "per_fill", "order", "cumulative_order_cap", "order_accumulator"}:
            raise ValueError("unknown fee aggregation")
        _bool(self.allow_fee_adjustment, "allow_fee_adjustment")

    def blockers(self):
        return tuple(reason for condition, reason in (
            (self.rate is None, "fee_rate_unknown"),
            (self.grid_usd is None or self.rounding is None, "fee_rounding_unknown"),
            (self.basis != "net_gain" and self.aggregation is None, "fee_aggregation_unknown"),
        ) if condition)

    def generic_policy(self):
        """Adapter to app.fees.engine.generic_fee for authored algebra only.

        The existing venue engine owns US order caps and Kalshi accumulators.
        Neither is approximated by ordinary per-fill/order rounding here.
        """
        if self.blockers():
            raise ValueError(",".join(self.blockers()))
        if self.aggregation in {"cumulative_order_cap", "order_accumulator"}:
            raise ValueError("provider-specific aggregation requires existing shared venue engine")
        return dict(basis=self.basis, rate=self.rate, grid=self.grid_usd,
                    rounding=self.rounding, aggregation=self.aggregation,
                    allow_fee_adjustment=self.allow_fee_adjustment)


@dataclass(frozen=True)
class CostRule:
    version: str
    venue: str
    product: str
    channel: str
    source_kind: str
    effective_from: str | None
    effective_to: str | None
    expires_at: str | None
    unit: UnitSpec
    terms: FeeTerms | None
    settlement_status: str
    mandatory_charges_known: bool
    evidence: tuple[EvidenceReference, ...]
    market_id: str | None = None
    event_id: str | None = None
    series_id: str | None = None
    account_ref: str | None = None
    source_url: str | None = None
    predecessor_version: str | None = None
    proposal_ref: str | None = None
    settlement_treatment: str = "separate_charge"
    settlement_terms: FeeTerms | None = None

    def __post_init__(self):
        for name in ("version", "venue", "product", "channel"):
            _text(getattr(self, name), name)
        if self.source_kind not in {"research_proposal", "controlled_scenario", "public_document", "account_terms"}:
            raise ValueError("unknown cost source kind")
        for value in (self.effective_from, self.effective_to, self.expires_at):
            if value is not None:
                _instant(value)
        if self.effective_from and self.effective_to and _instant(self.effective_from) >= _instant(self.effective_to):
            raise ValueError("empty fee interval")
        if not isinstance(self.unit, UnitSpec) or (self.terms is not None and not isinstance(self.terms, FeeTerms)):
            raise ValueError("typed unit and fee terms required")
        for name in ("market_id", "event_id", "series_id", "predecessor_version", "proposal_ref"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)
        if self.settlement_status not in {"declared_zero", "known_terms", "explicit_terms_required", "unknown"}:
            raise ValueError("explicit settlement charge status required")
        if self.settlement_status == "known_terms" and not isinstance(self.settlement_terms, FeeTerms):
            raise ValueError("typed settlement charge terms required")
        if self.settlement_status != "known_terms" and self.settlement_terms is not None:
            raise ValueError("settlement charge terms/status conflict")
        if self.settlement_treatment not in {"separate_charge", "already_withheld_from_payout"}:
            raise ValueError("explicit settlement cashflow treatment required")
        _bool(self.mandatory_charges_known, "mandatory_charges_known")
        _account(self.account_ref)
        if (not isinstance(self.evidence, tuple) or not self.evidence or len(self.evidence) > 32
                or not all(isinstance(e, EvidenceReference) for e in self.evidence)):
            raise ValueError("typed cost evidence required")
        if self.source_kind == "account_terms" and self.account_ref is None:
            raise ValueError("account terms require exact opaque account scope")
        if self.source_kind == "account_terms" and not any(
                e.evidence_class in {"retained", "manual_review"} for e in self.evidence):
            raise ValueError("sanitized account-term evidence required; authored terms remain scenarios")
        if self.source_kind == "public_document":
            if not self.source_url or not self.source_url.startswith("https://"):
                raise ValueError("primary public fee source URL required")
            if not any(e.evidence_class == "primary_source" for e in self.evidence):
                raise ValueError("pinned primary-source content required before numeric public binding")
        if self.source_kind in {"public_document", "account_terms"} and self.effective_from is None:
            # A date-only research notice remains a proposal; pinning a version
            # never manufactures its effective instant.
            raise ValueError("numeric fee binding requires exact effective instant")

    @classmethod
    def from_dict(cls, value):
        row = deepcopy(value)
        row["unit"] = UnitSpec(**row["unit"])
        row["terms"] = FeeTerms(**row["terms"]) if row.get("terms") is not None else None
        if row.get("settlement_terms") is not None:
            row["settlement_terms"] = FeeTerms(**row["settlement_terms"])
        row["evidence"] = tuple(EvidenceReference(**e) for e in row["evidence"])
        return cls(**row)

    def to_dict(self):
        from dataclasses import asdict
        return asdict(self)


@dataclass(frozen=True)
class CostRequest:
    venue: str
    product: str
    channel: str
    trade_time: str
    calculation_time: str
    role: str = "taker"
    portfolio_basis: str = "standalone"
    market_id: str | None = None
    event_id: str | None = None
    series_id: str | None = None
    account_ref: str | None = None
    pinned_version: str | None = None
    allow_controlled_scenario: bool = False

    def __post_init__(self):
        for name in ("venue", "product", "channel"):
            _text(getattr(self, name), name)
        _instant(self.trade_time)
        if _instant(self.calculation_time) < _instant(self.trade_time):
            raise ValueError("calculation time precedes hypothetical trade time")
        if self.role not in {"maker", "taker"} or self.portfolio_basis not in {"standalone", "incremental_existing_positions"}:
            raise ValueError("explicit liquidity and portfolio assumptions required")
        _bool(self.allow_controlled_scenario, "allow_controlled_scenario")
        _account(self.account_ref)


@dataclass(frozen=True)
class CostResolution:
    rule: CostRule | None
    reasons: tuple[str, ...]
    entry_rule_inputs_available: bool
    net_rule_inputs_available: bool
    qualification: str
    gross_inputs_preserved: bool = True
    positions_reference: dict | None = None

    def to_dict(self):
        rule = None if self.rule is None else self.rule.to_dict()
        if rule is not None and rule["account_ref"] is not None:
            rule["account_scope_sha256"] = _digest(dict(account_ref=rule["account_ref"]))
            rule["account_ref"] = None
        return dict(version=VERSION, rule=rule,
                    reasons=list(self.reasons), entry_rule_inputs_available=self.entry_rule_inputs_available,
                    net_rule_inputs_available=self.net_rule_inputs_available,
                    qualification=self.qualification, gross_inputs_preserved=True,
                    positions_reference=deepcopy(self.positions_reference))


class CostRegistry:
    def __init__(self, data):
        self._data = deepcopy(data)
        if data.get("schema") != 1 or data.get("version") != VERSION:
            raise ValueError("unsupported cost-input registry")
        self.rules = tuple(CostRule.from_dict(row) for row in data["rules"])
        if len({r.version for r in self.rules}) != len(self.rules):
            raise ValueError("duplicate fee rule version")

    @property
    def data(self):
        return deepcopy(self._data)

    def resolve(self, request: CostRequest, *, positions=None, outcome_names=()):
        if not isinstance(request, CostRequest):
            raise ValueError("typed cost request required")
        rows = []
        for rule in self.rules:
            if (rule.venue, rule.product, rule.channel) != (request.venue, request.product, request.channel):
                continue
            if rule.terms and rule.terms.role != request.role:
                continue
            if any(getattr(rule, key) is not None and getattr(rule, key) != getattr(request, key)
                   for key in ("account_ref", "market_id", "event_id", "series_id")):
                continue
            at = _instant(request.trade_time)
            if rule.effective_from and at < _instant(rule.effective_from):
                continue
            if rule.effective_to and at >= _instant(rule.effective_to):
                continue
            rows.append(rule)
        if not rows:
            return CostResolution(None, ("fee_channel_scope_or_interval_unavailable",), False, False, "unknown")
        # Account overrides market, then event, series, then product. A scoped
        # unknown/expired override blocks fallback to unrelated public terms.
        def priority(rule):
            return (rule.account_ref is not None, rule.market_id is not None,
                    rule.event_id is not None, rule.series_id is not None)
        best = max(priority(r) for r in rows)
        chosen = [r for r in rows if priority(r) == best]
        if request.pinned_version:
            pinned = [r for r in rows if r.version == request.pinned_version]
            if pinned and priority(pinned[0]) < best:
                return CostResolution(chosen[0] if len(chosen) == 1 else None,
                                      ("pinned_fee_version_conflicts_with_scoped_override",),
                                      False, False, "unknown")
            chosen = [r for r in chosen if r.version == request.pinned_version]
            if not chosen:
                return CostResolution(None, ("fee_channel_scope_or_interval_unavailable",), False, False, "unknown")
        if len(chosen) != 1:
            return CostResolution(None, ("fee_override_ambiguous",), False, False, "unknown")
        rule = chosen[0]
        blocked = []
        if rule.source_kind == "research_proposal":
            blocked.append("public_proposal_not_runtime_binding")
        if rule.effective_from is None:
            blocked.append("fee_effective_instant_unknown")
        if rule.expires_at and _instant(request.calculation_time) >= _instant(rule.expires_at):
            blocked.append("fee_inputs_expired")
        if rule.source_kind == "controlled_scenario" and not (request.allow_controlled_scenario and request.pinned_version):
            blocked.append("controlled_fee_scenario_requires_explicit_pin")
        if rule.terms is None:
            blocked.append("fee_terms_unknown")
        else:
            blocked.extend(rule.terms.blockers())
        entry_ok = not blocked
        if rule.settlement_status == "known_terms":
            blocked.extend("settlement_" + reason for reason in rule.settlement_terms.blockers())
        elif rule.settlement_status != "declared_zero":
            blocked.append("settlement_charge_inputs_required")
        if not rule.mandatory_charges_known:
            blocked.append("mandatory_channel_charges_unknown")
        position_reference = None
        if request.portfolio_basis == "incremental_existing_positions":
            if positions is None:
                blocked.append("scoped_existing_positions_required")
            elif not isinstance(positions, PositionInputs):
                raise ValueError("typed explicit positions required")
            else:
                positions.generic_context(request, outcome_names)
                position_reference = positions.public_reference()
        qualification = "hypothetical" if rule.source_kind == "controlled_scenario" else "source_inputs_only"
        return CostResolution(rule, tuple(dict.fromkeys(blocked)), entry_ok, not blocked,
                              qualification, positions_reference=position_reference)


def load_cost_registry():
    return CostRegistry(json.loads(files("app.fixtures").joinpath("comparison-costs-v1.json").read_text()))


@dataclass(frozen=True)
class FillInputs:
    """Observed fills and authored allocation hypotheses retain distinct labels."""
    basis: str
    complete_order_history: bool
    fill_count: int | None
    fragment_upper_bound: int | None
    order_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if self.basis not in {"observed_fills", "authored_fills", "hypothetical_one_order", "unknown_split"}:
            raise ValueError("explicit fill evidence basis required")
        _bool(self.complete_order_history, "complete_order_history")
        if self.basis == "hypothetical_one_order" and (not self.complete_order_history or self.fill_count != 1 or self.fragment_upper_bound != 1 or len(self.order_ids) != 1):
            raise ValueError("one hypothetical order requires one declared modeled fill")
        for value in (self.fill_count, self.fragment_upper_bound):
            if value is not None and (type(value) is not int or not 1 <= value <= 10000):
                raise ValueError("positive bounded fragment count required")
        if self.fill_count and self.fragment_upper_bound and self.fill_count > self.fragment_upper_bound:
            raise ValueError("fill count exceeds declared fragment bound")
        if self.basis == "unknown_split" and (self.complete_order_history or self.fill_count is not None):
            raise ValueError("unknown split is not complete observed fill history")
        if self.basis != "unknown_split" and (self.fill_count is None or not self.order_ids):
            raise ValueError("explicit fill count and order identities required")
        if not isinstance(self.order_ids, tuple) or len(self.order_ids) > 10000:
            raise ValueError("bounded immutable order identities required")
        for order_id in self.order_ids:
            _text(order_id, "order_id")
        if self.fill_count is not None and len(self.order_ids) > self.fill_count:
            raise ValueError("order count exceeds explicit fill count")
        if len(set(self.order_ids)) != len(self.order_ids):
            raise ValueError("duplicate order identity")

    def reasons(self, aggregation):
        if self.basis != "unknown_split":
            return () if self.complete_order_history else ("complete_order_history_required",)
        if aggregation == "per_fill" and self.fragment_upper_bound is None:
            return ("bounded_fragmentation_required",)
        if aggregation == "per_fill":
            return ()
        if aggregation == "order_accumulator":
            return ("complete_order_history_required",)
        # A supported US order cap is an entry bound, never an exact fill fee.
        if aggregation == "cumulative_order_cap":
            return ("supported_order_cap_bound_required",)
        return ("supported_fragmentation_bound_required",)


@dataclass(frozen=True)
class EstimateBounds:
    lower_usd: str
    upper_usd: str
    quantity_dollar_face: str
    kind: str
    evidence: EvidenceReference
    expires_at: str | None
    fragment_upper_bound: int | None = None

    def __post_init__(self):
        lower, upper = _number(self.lower_usd, minimum=ZERO), _number(self.upper_usd, minimum=ZERO)
        if upper < lower or _number(self.quantity_dollar_face) <= ZERO:
            raise ValueError("invalid quantity-qualified cost estimate bounds")
        if self.kind not in {"supported_entry_bound", "authored_scenario"}:
            raise ValueError("explicit estimate provenance required")
        if not isinstance(self.evidence, EvidenceReference):
            raise ValueError("typed bounded-cost evidence required")
        if self.expires_at is not None:
            _instant(self.expires_at)
        if self.fragment_upper_bound is not None and (type(self.fragment_upper_bound) is not int or not 1 <= self.fragment_upper_bound <= 10000):
            raise ValueError("positive bounded fragment count required")

    def reasons(self, *, calculation_time, quantity_dollar_face, aggregation):
        reasons = []
        if _number(quantity_dollar_face) != _number(self.quantity_dollar_face):
            reasons.append("cost_bound_quantity_mismatch")
        if self.expires_at and _instant(calculation_time) >= _instant(self.expires_at):
            reasons.append("cost_bound_expired")
        if aggregation == "per_fill" and self.fragment_upper_bound is None:
            reasons.append("bounded_fragmentation_required")
        return tuple(reasons)


@dataclass(frozen=True)
class NativeMarketFeeInputs:
    """Selected Novig v3 market.fee object; league notices are not metadata."""
    market_id: str
    api_regime: str
    coefficient: str
    maker_credit: str
    charged: str
    phase_at_match: str | None
    evidence: EvidenceReference

    def __post_init__(self):
        _text(self.market_id, "native fee market_id")
        if self.api_regime != "novig_v3":
            raise ValueError("this native fee contract is Novig v3 only; RFQ remains separate")
        _number(self.coefficient, minimum=ZERO)
        if not ZERO <= _number(self.maker_credit) <= 1:
            raise ValueError("bounded native maker credit fraction required")
        if self.charged not in {"ALWAYS", "WHEN_LIVE"}:
            raise ValueError("explicit native charge condition required")
        if self.phase_at_match not in {None, "OPEN_PREGAME", "OPEN_INGAME", "DELAYED", "FINAL", "CANCELED"}:
            raise ValueError("supported match-time phase required")
        if not isinstance(self.evidence, EvidenceReference):
            raise ValueError("typed selected-market fee evidence required")

    @property
    def charge_active(self):
        if self.charged == "ALWAYS":
            return True
        if self.phase_at_match is None:
            return None
        return self.phase_at_match == "OPEN_INGAME"

    def engine_metadata(self, market_id):
        if market_id != self.market_id:
            raise ValueError("selected native fee market scope conflict")
        if self.charge_active is None:
            raise ValueError("fee_match_phase_unknown")
        return dict(coefficient=self.coefficient, makerCredit=self.maker_credit, charged=self.charged)


@dataclass(frozen=True)
class QuantityGridInputs:
    minimum_native: str | None
    increment_native: str | None
    legal_price_tick: str | None
    evidence: EvidenceReference | None

    def __post_init__(self):
        for value in (self.minimum_native, self.increment_native, self.legal_price_tick):
            if value is not None and _number(value) <= ZERO:
                raise ValueError("positive evidenced native grid value required")
        if self.evidence is not None and not isinstance(self.evidence, EvidenceReference):
            raise ValueError("typed quantity-grid evidence required")
        if any(v is not None for v in (self.minimum_native, self.increment_native, self.legal_price_tick)) and self.evidence is None:
            raise ValueError("native grid values require provenance")

    def reasons(self, native_amount):
        value = _number(native_amount)
        reasons = []
        if self.minimum_native is None:
            reasons.append("quantity_minimum_unknown")
        elif value < _number(self.minimum_native):
            reasons.append("quantity_below_native_minimum")
        if self.increment_native is None:
            reasons.append("quantity_increment_unknown")
        elif self.minimum_native is not None:
            with localcontext(Context(prec=100)):
                if (value - _number(self.minimum_native)) % _number(self.increment_native) != ZERO:
                    reasons.append("quantity_off_native_grid")
        return tuple(reasons)

    @property
    def adverse_movement_floor(self):
        if self.legal_price_tick is None:
            return None
        return str(max(Decimal("0.01"), _number(self.legal_price_tick)))


@dataclass(frozen=True)
class DepthInputs:
    available_native: str | None
    evidence: EvidenceReference | None
    size_basis: str = "common_comparison_ceiling"

    def __post_init__(self):
        if self.size_basis not in {"common_comparison_ceiling", "details_supported_size_sensitivity"}:
            raise ValueError("explicit target or supported-size basis required")
        if self.available_native is not None:
            _number(self.available_native, minimum=ZERO)
            if not isinstance(self.evidence, EvidenceReference):
                raise ValueError("no fabricated depth; typed source evidence required")
        elif self.evidence is not None:
            raise ValueError("depth evidence cannot manufacture absent quantity")

    def reasons(self, native_amount):
        value = _number(native_amount)
        if value <= ZERO:
            raise ValueError("positive target native quantity required")
        if self.available_native is None:
            return ("depth_inputs_unavailable",)
        if value > _number(self.available_native):
            return ("target_size_depth_insufficient",)
        return ()


@dataclass(frozen=True)
class PositionInputs:
    account_ref: str
    market_id: str
    complete: bool
    net_before_usd: dict[str, str]
    evidence: EvidenceReference

    def __post_init__(self):
        _account(self.account_ref)
        if self.account_ref is None:
            raise ValueError("complete scoped positions require an opaque account reference")
        _text(self.market_id, "position market_id")
        _bool(self.complete, "positions complete")
        if not self.complete or not self.net_before_usd:
            raise ValueError("complete scoped baseline state cashflows required")
        if not isinstance(self.evidence, EvidenceReference):
            raise ValueError("typed position evidence required")
        for state, value in self.net_before_usd.items():
            _text(state, "position state")
            _number(value)
        object.__setattr__(self, "net_before_usd", deepcopy(self.net_before_usd))

    def generic_context(self, request: CostRequest, outcome_names):
        if (request.account_ref, request.market_id) != (self.account_ref, self.market_id):
            raise ValueError("existing-position scope conflict")
        if request.portfolio_basis != "incremental_existing_positions" or set(outcome_names) != set(self.net_before_usd):
            raise ValueError("complete incremental state basis required")
        return dict(account=self.account_ref, market=self.market_id, complete=True,
                    net_before=deepcopy(self.net_before_usd))

    def public_reference(self):
        # No account ref, baseline profits, balances, credentials or raw positions.
        return dict(kind="explicit_private_portfolio_input", sha256=_digest(dict(
            account=self.account_ref, market=self.market_id, net_before=self.net_before_usd)),
            evidence_ref=self.evidence.ref, complete=True)


def authored_fee(terms: FeeTerms, fills, *, positions=None, outcomes=None):
    """Shared algebra seam for controlled portable examples only (not S02 UI)."""
    if not isinstance(terms, FeeTerms) or not isinstance(fills, list) or len(fills) > 10000:
        raise ValueError("typed terms and bounded authored fill list required")
    for fill in fills:
        if not isinstance(fill, dict):
            raise ValueError("explicit authored fill required")
        _number(fill["price"])
        _number(fill["quantity"])
    if positions is not None:
        if not isinstance(positions, dict) or not isinstance(positions.get("net_before"), dict):
            raise ValueError("explicit authored position cashflows required")
        for value in positions["net_before"].values():
            _number(value)
    if outcomes is not None:
        if not isinstance(outcomes, dict):
            raise ValueError("explicit authored state cashflows required")
        for value in outcomes.values():
            _number(value)
    return generic_fee(fills, terms.generic_policy(), positions=positions, outcomes=outcomes)


@dataclass(frozen=True)
class CreditInputs:
    kind: str
    amount_usd: str | None
    timing: str
    contingent: bool
    eligibility: str
    evidence: EvidenceReference

    def __post_init__(self):
        if self.kind not in {"maker_rebate", "volume_rebate", "maker_credit_program", "position_fee_adjustment"}:
            raise ValueError("explicit credit kind required")
        if self.amount_usd is not None:
            _number(self.amount_usd, minimum=ZERO)
        if self.timing not in {"fill", "weekly", "settlement", "later"}:
            raise ValueError("explicit credit timing required")
        if self.eligibility not in {"known", "unknown", "hypothetical"}:
            raise ValueError("explicit credit eligibility required")
        _bool(self.contingent, "credit contingent")
        if not isinstance(self.evidence, EvidenceReference):
            raise ValueError("typed credit evidence required")

    @property
    def immediate_funding_credit_usd(self):
        # Authored maker results remain separate scenarios. Deterministic order
        # rounding refunds are FundingComponents, not program/volume credits.
        return "0"


@dataclass(frozen=True)
class FundingComponent:
    component_id: str
    amount_usd: str
    kind: str
    timing: str
    contingent: bool = False

    def __post_init__(self):
        _text(self.component_id, "funding component_id")
        _number(self.amount_usd, minimum=ZERO)
        if self.kind not in {"acquisition", "entry_fee", "refundable_hold", "consumed_allowance",
                             "later_credit", "deterministic_rounding_refund", "charge_withheld_from_payout"}:
            raise ValueError("explicit funding cashflow kind required")
        if self.timing not in {"entry", "outcome", "later"}:
            raise ValueError("explicit funding timing required")
        _bool(self.contingent, "contingent")
        if self.kind in {"acquisition", "entry_fee", "refundable_hold", "consumed_allowance", "deterministic_rounding_refund"}:
            if self.timing != "entry" or self.contingent:
                raise ValueError("immediate funding components require known entry timing")
        if self.kind == "later_credit" and self.timing != "later":
            raise ValueError("later credit cannot fund immediate capital")
        if self.kind == "charge_withheld_from_payout" and self.timing != "outcome":
            raise ValueError("withheld charge belongs to outcome cashflow")


@dataclass(frozen=True)
class CapitalInputs:
    components: tuple[FundingComponent, ...]
    ceiling_usd: str = "100"

    def __post_init__(self):
        if (not isinstance(self.components, tuple) or not self.components or len(self.components) > 10000
                or not all(isinstance(c, FundingComponent) for c in self.components)):
            raise ValueError("typed funding components required")
        if len({c.component_id for c in self.components}) != len(self.components):
            raise ValueError("funding component counted more than once")
        with localcontext(Context(prec=100)):
            fees = sum((_number(c.amount_usd) for c in self.components if c.kind == "entry_fee"), ZERO)
            refunds = sum((_number(c.amount_usd) for c in self.components if c.kind == "deterministic_rounding_refund"), ZERO)
        if refunds > fees:
            raise ValueError("deterministic entry rounding refunds exceed included entry fee debits")
        if _number(self.ceiling_usd) <= ZERO:
            raise ValueError("positive comparison capital ceiling required")
        if Decimal(self.deployed_usd) <= ZERO:
            raise ValueError("positive actual deployed capital required")

    @property
    def deployed_usd(self):
        with localcontext(Context(prec=100)):
            amount = ZERO
            for c in self.components:
                if c.kind in {"acquisition", "entry_fee", "refundable_hold", "consumed_allowance"}:
                    amount += _number(c.amount_usd)
                elif c.kind == "deterministic_rounding_refund":
                    amount -= _number(c.amount_usd)
            return str(amount)

    @property
    def reasons(self):
        return ("comparison_capital_ceiling_exceeded",) if Decimal(self.deployed_usd) > _number(self.ceiling_usd) else ()

    def basis(self):
        with localcontext(Context(prec=100)):
            return dict(ceiling_usd=self.ceiling_usd, deployed_capital_usd=self.deployed_usd,
                        residual_ceiling_usd=str(_number(self.ceiling_usd) - Decimal(self.deployed_usd)),
                        denominator="actual_deployed_capital", reasons=list(self.reasons),
                        excluded_credit_ids=[c.component_id for c in self.components if c.kind == "later_credit"],
                        outcome_charge_ids=[c.component_id for c in self.components if c.kind == "charge_withheld_from_payout"])


@dataclass(frozen=True)
class ComparisonCostPolicy:
    """Future reviewed policy inputs. This does not change gross age behavior."""
    version: str = "comparison-cost-policy-1"
    ceiling_usd: str = "100"
    role: str = "taker"
    portfolio_basis: str = "standalone"
    funding_basis: str = "already_prefunded"
    denominator: str = "actual_deployed_capital"
    optional_override_surface: str = "Details"
    pregame_age_seconds: int = 900
    live_age_seconds: int = 15
    gross_pinnacle_baseline_age_seconds: int = 1800
    adverse_price_per_dollar_face: str = "0.01"
    extra_arbitrary_reserve_usd: str = "0"
    contingent_funding_credit_usd: str = "0"

    def __post_init__(self):
        if _number(self.ceiling_usd) <= ZERO:
            raise ValueError("positive common comparison ceiling required")
        # Routine override changes size alone, never silently changes role or
        # funding/age policy. A policy transition receives a new contract.
        if (self.role, self.portfolio_basis, self.funding_basis, self.denominator) != (
                "taker", "standalone", "already_prefunded", "actual_deployed_capital"):
            raise ValueError("reviewed default cost assumptions required")
        if (self.pregame_age_seconds, self.live_age_seconds, self.gross_pinnacle_baseline_age_seconds) != (900, 15, 1800):
            raise ValueError("future net and existing gross age policies must remain distinct")
        if self.adverse_price_per_dollar_face != "0.01" or self.extra_arbitrary_reserve_usd != "0" or self.contingent_funding_credit_usd != "0":
            raise ValueError("reviewed stress and contingent funding policy required")

    def with_details_ceiling(self, amount):
        from dataclasses import replace
        return replace(self, ceiling_usd=amount)

    @property
    def revision(self):
        from dataclasses import asdict
        return _digest(asdict(self))

    def future_age_reasons(self, phase, source_age_seconds):
        if phase not in {"pregame", "live"}:
            return ("comparison_phase_unknown",)
        if type(source_age_seconds) is not int or source_age_seconds < 0:
            return ("source_quote_age_unknown",)
        limit = self.live_age_seconds if phase == "live" else self.pregame_age_seconds
        return ("source_quote_too_old_for_future_net",) if source_age_seconds > limit else ()


DEFAULT_POLICY = ComparisonCostPolicy()
