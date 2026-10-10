"""Exact side/rule payout bindings and bounded mutually exclusive state inputs.

Lifecycle labels are aliases of one noncompleted terminal bucket. They are not
independent probability events. This module supplies cashflows, not probabilities.
"""
from dataclasses import dataclass, replace
from datetime import date, datetime
from fractions import Fraction
from hashlib import sha256
import json
from typing import Any
from zoneinfo import ZoneInfo

from .domain import CanonicalSelection, EvidenceReference, ExactNumber, PayoutReference
from .event_links import instant

VERSION = "comparison-payout-inputs-1"
MAX_PROFILES = 128
MAX_LEGS = 8
MAX_STATES = 64
EXCEPTION_ALIASES = ("cancelled", "abandoned", "postponed_terminal", "suspended_terminal", "other_noncompleted")


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def selection_digest(selection: CanonicalSelection) -> str:
    return _digest(selection.semantic_key())


@dataclass(frozen=True)
class CompletionContext:
    started_at: str | None
    rescheduled_date: str | None
    date_timezone: str
    evidence: tuple[EvidenceReference, ...]

    def __post_init__(self):
        if self.started_at is not None:
            instant(self.started_at)
        if self.rescheduled_date is not None:
            date.fromisoformat(self.rescheduled_date)
        if not isinstance(self.date_timezone, str) or not self.date_timezone:
            raise ValueError("Exact source calendar timezone required")
        ZoneInfo(self.date_timezone)
        if (not isinstance(self.evidence, tuple) or not self.evidence or len(self.evidence) > 32
                or any(not isinstance(x, EvidenceReference) for x in self.evidence)):
            raise ValueError("Completion scenario/observation evidence required")

    @classmethod
    def from_dict(cls, value: Any) -> "CompletionContext":
        if not isinstance(value, dict) or set(value) != {"started_at", "rescheduled_date", "date_timezone", "evidence"} or not isinstance(value["evidence"], list):
            raise ValueError("Exact completion-context shape required")
        return cls(value["started_at"], value["rescheduled_date"], value["date_timezone"],
                   tuple(EvidenceReference.from_dict(x) for x in value["evidence"]))

    def to_dict(self) -> dict:
        return dict(started_at=self.started_at, rescheduled_date=self.rescheduled_date,
                    date_timezone=self.date_timezone, evidence=[x.to_dict() for x in self.evidence])


@dataclass(frozen=True)
class NormalCondition:
    kind: str
    maximum: ExactNumber | None
    original_start: str | None
    original_scheduled_date: str | None
    date_timezone: str | None

    def __post_init__(self):
        if self.kind not in {"starts_within_hours", "rescheduled_within_days", "authored_completed_assumption", "conditional_completed_result"}:
            raise ValueError("Explicit normal-result rule condition required")
        if self.kind in {"authored_completed_assumption", "conditional_completed_result"}:
            if any(x is not None for x in (self.maximum, self.original_start, self.original_scheduled_date, self.date_timezone)):
                raise ValueError("Authored completion assumption cannot impersonate source timing")
        else:
            if not isinstance(self.maximum, ExactNumber) or self.maximum.value <= 0:
                raise ValueError("Exact positive source completion window required")
            instant(self.original_start)
            date.fromisoformat(self.original_scheduled_date)
            zone = ZoneInfo(self.date_timezone)
            if instant(self.original_start).astimezone(zone).date().isoformat() != self.original_scheduled_date:
                raise ValueError("Original source date conflicts with its exact timezone/instant")
            if self.kind == "rescheduled_within_days" and self.maximum.value.denominator != 1:
                raise ValueError("Calendar-day window requires integer source days")

    @classmethod
    def from_dict(cls, value: Any) -> "NormalCondition":
        if not isinstance(value, dict) or set(value) != {"kind", "maximum", "original_start", "original_scheduled_date", "date_timezone"}:
            raise ValueError("Exact normal-result condition shape required")
        return cls(**dict(value, maximum=ExactNumber.parse(value["maximum"]) if value["maximum"] is not None else None))

    def to_dict(self) -> dict:
        return dict(kind=self.kind, maximum=self.maximum.original if self.maximum else None,
                    original_start=self.original_start, original_scheduled_date=self.original_scheduled_date,
                    date_timezone=self.date_timezone)

    def evaluate(self, context: CompletionContext) -> tuple[bool | None, str | None]:
        if not isinstance(context, CompletionContext):
            raise ValueError("Explicit completion context required")
        if self.kind in {"authored_completed_assumption", "conditional_completed_result"}:
            return True, None
        if context.date_timezone != self.date_timezone:
            return None, "Completion calendar timezone differs from exact source rule"
        if self.kind == "starts_within_hours":
            if context.started_at is None:
                return None, "Exact first-start instant unavailable for 48-hour applicability"
            elapsed = instant(context.started_at) - instant(self.original_start)
            hours = Fraction(elapsed.days * 86400 + elapsed.seconds, 3600) + Fraction(elapsed.microseconds, 3600000000)
            if hours < 0:
                return None, "Earlier-than-original start requires exact source clause review"
            return (True, None) if hours <= self.maximum.value else (False, "Beyond source first-start window; exact fair-price payout unavailable")
        if context.rescheduled_date is None:
            return None, "Exact evidenced rescheduled calendar date unavailable; elapsed hours do not establish applicability"
        days = (date.fromisoformat(context.rescheduled_date) - date.fromisoformat(self.original_scheduled_date)).days
        if days < 0:
            return None, "Earlier-than-original reschedule requires exact source clause review"
        return (True, None) if days <= self.maximum.value else (False, "Beyond source rescheduled-date window; exact last-fair-price payout unavailable")


@dataclass(frozen=True)
class PayoutCell:
    value: ExactNumber | None
    status: str
    reason: str | None

    def __post_init__(self):
        if self.status not in {"evidenced", "estimated", "unknown"}:
            raise ValueError("Explicit payout evidence status required")
        if self.status == "unknown":
            if self.value is not None or not isinstance(self.reason, str) or not self.reason:
                raise ValueError("Unknown payout requires null and a local reason")
        elif not isinstance(self.value, ExactNumber) or self.value.value < 0:
            raise ValueError("Known payout requires nonnegative exact value")
        if self.status == "estimated" and (not isinstance(self.reason, str) or not self.reason):
            raise ValueError("Estimated payout requires its stated assumption")
        if self.status == "evidenced" and self.reason is not None:
            raise ValueError("Evidenced scalar payout cannot carry an estimate reason")

    @classmethod
    def from_dict(cls, value: Any) -> "PayoutCell":
        if not isinstance(value, dict) or set(value) != {"value", "status", "reason"}:
            raise ValueError("Exact payout cell shape required")
        return cls(ExactNumber.parse(value["value"]) if value["value"] is not None else None,
                   value["status"], value["reason"])

    def to_dict(self) -> dict:
        return dict(value=self.value.original if self.value else None, status=self.status, reason=self.reason)


@dataclass(frozen=True)
class PayoutProfile:
    profile_id: str
    version: str
    rule_revision: str
    native_key: tuple[str, ...]
    selection_sha256: str
    payout_unit: str
    effective_from: str
    effective_until: str | None
    source_evidence: tuple[EvidenceReference, ...]
    below: PayoutCell
    equal: PayoutCell
    above: PayoutCell
    noncompleted: PayoutCell
    refund_fees: str
    normal_condition: NormalCondition

    def __post_init__(self):
        for name in ("profile_id", "version", "rule_revision"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError("Versioned payout profile identity required")
        if (not isinstance(self.native_key, tuple) or len(self.native_key) != 5
                or any(not isinstance(x, str) or not x for x in self.native_key)):
            raise ValueError("Exact venue/event/market/instrument/side profile association required")
        if (not isinstance(self.selection_sha256, str) or len(self.selection_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.selection_sha256)):
            raise ValueError("Exact semantic selection digest required")
        if self.payout_unit not in {"usd_per_contract", "usd_per_usd_stake"}:
            raise ValueError("Payout unit required")
        start = instant(self.effective_from)
        if self.effective_until is not None and instant(self.effective_until) <= start:
            raise ValueError("Positive payout rule interval required")
        if (not isinstance(self.source_evidence, tuple) or not self.source_evidence
                or len(self.source_evidence) > 32
                or any(not isinstance(x, EvidenceReference) for x in self.source_evidence)):
            raise ValueError("Bounded sanitized payout clause evidence required")
        for name in ("below", "equal", "above", "noncompleted"):
            if not isinstance(getattr(self, name), PayoutCell):
                raise ValueError("Typed ordinary and exceptional payout cells required")
            if self.payout_unit == "usd_per_contract":
                cell = getattr(self, name)
                if cell.value is not None and cell.value.value > 1:
                    raise ValueError("Contract face payout outside [0,1]")
        if self.refund_fees not in {"retained", "returned", "unknown", "not_applicable"}:
            raise ValueError("Explicit fee-refund applicability required")
        if not isinstance(self.normal_condition, NormalCondition):
            raise ValueError("Exact normal-result lifecycle condition required")
        if (self.normal_condition.kind == "authored_completed_assumption"
                and any(x.evidence_class != "authored" for x in self.source_evidence)):
            raise ValueError("Authored completion assumption cannot override retained source conditions")

    @classmethod
    def from_dict(cls, value: Any) -> "PayoutProfile":
        required = {"schema_version", "profile_id", "version", "rule_revision", "native_key",
                    "selection_sha256", "payout_unit", "effective_from", "effective_until",
                    "source_evidence", "below", "equal", "above", "noncompleted", "refund_fees", "normal_condition"}
        if not isinstance(value, dict) or set(value) != required or value["schema_version"] != VERSION:
            raise ValueError("Exact versioned payout profile required")
        if not isinstance(value["native_key"], list) or not isinstance(value["source_evidence"], list):
            raise ValueError("Profile associations and evidence lists required")
        fields = {name: value[name] for name in required - {"schema_version", "native_key", "source_evidence", "below", "equal", "above", "noncompleted", "normal_condition"}}
        return cls(**fields, native_key=tuple(value["native_key"]),
                   source_evidence=tuple(EvidenceReference.from_dict(x) for x in value["source_evidence"]),
                   normal_condition=NormalCondition.from_dict(value["normal_condition"]),
                   **{name: PayoutCell.from_dict(value[name]) for name in ("below", "equal", "above", "noncompleted")})

    def to_dict(self) -> dict:
        return dict(schema_version=VERSION, profile_id=self.profile_id, version=self.version,
                    rule_revision=self.rule_revision, native_key=list(self.native_key),
                    selection_sha256=self.selection_sha256, payout_unit=self.payout_unit,
                    effective_from=self.effective_from, effective_until=self.effective_until,
                    source_evidence=[x.to_dict() for x in self.source_evidence],
                    **{name: getattr(self, name).to_dict() for name in ("below", "equal", "above", "noncompleted")},
                    refund_fees=self.refund_fees, normal_condition=self.normal_condition.to_dict())

    @property
    def revision(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class BoundLeg:
    selection: CanonicalSelection
    profile: PayoutProfile
    revision: str
    context: CompletionContext
    normal_eligible: bool | None
    normal_reason: str | None

    def __post_init__(self):
        if not isinstance(self.selection, CanonicalSelection) or not isinstance(self.profile, PayoutProfile):
            raise ValueError("Exact typed bound leg required")
        ref = self.selection.payout
        if (ref is None or self.selection.native.key != self.profile.native_key
                or selection_digest(self.selection) != self.profile.selection_sha256
                or (ref.profile_id, ref.version, ref.rule_revision) !=
                   (self.profile.profile_id, self.profile.version, self.profile.rule_revision)
                or self.selection.price.payout_unit != self.profile.payout_unit
                or self.profile.normal_condition.evaluate(self.context) != (self.normal_eligible, self.normal_reason)
                or self.revision != _digest([selection_digest(self.selection), list(self.selection.native.key), self.profile.revision, self.context.to_dict()])):
            raise ValueError("Bound leg/profile revision conflict")

    def normal_payout(self, part: str) -> PayoutCell:
        return getattr(self.profile, part) if self.normal_eligible is True else PayoutCell(None, "unknown", self.normal_reason)


def bind_profile(selection: CanonicalSelection, profile: PayoutProfile, *, at: datetime,
                 rule_revision: str, context: CompletionContext) -> BoundLeg:
    """Requires the caller's current effective instrument rule, never a sibling."""
    if not isinstance(selection, CanonicalSelection) or not isinstance(profile, PayoutProfile):
        raise ValueError("Typed selection and payout profile required")
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("Aware payout applicability instant required")
    if (selection.native.key != profile.native_key or selection_digest(selection) != profile.selection_sha256
            or profile.rule_revision != rule_revision or selection.price.payout_unit != profile.payout_unit):
        raise ValueError("Exact instrument/selection/unit/effective rule binding conflict")
    if at < instant(profile.effective_from) or (profile.effective_until is not None and at >= instant(profile.effective_until)):
        raise ValueError("Payout profile expired or not effective")
    equality = selection.equality
    if equality.treatment == "fraction":
        if profile.equal.value is None or profile.equal.value.value != equality.payout.value:
            raise ValueError("Fractional equality profile conflicts with native descriptor")
    if equality.treatment == "stake_refund":
        if profile.payout_unit != "usd_per_usd_stake" or profile.equal.value is None or profile.equal.value.value != 1:
            raise ValueError("Stake refund must return one dollar per dollar stake")
        if equality.refund_fees != profile.refund_fees:
            raise ValueError("Refund-fee applicability conflicts with source descriptor")
    reference = PayoutReference(profile.profile_id, profile.version, profile.rule_revision,
                                selection.native.instrument_id, selection.native.side_id)
    bound = replace(selection, payout=reference, payout_unknown=None)
    eligible, reason = profile.normal_condition.evaluate(context)
    revision = _digest([selection_digest(bound), list(bound.native.key), profile.revision, context.to_dict()])
    return BoundLeg(bound, profile, revision, context, eligible, reason)


class ProfileRegistry:
    """Immutable shared references rather than large clause copies in every quote."""
    def __init__(self, profiles=()):
        profiles = tuple(profiles)
        if len(profiles) > MAX_PROFILES or any(not isinstance(p, PayoutProfile) for p in profiles):
            raise ValueError("Bounded typed payout profiles required")
        self.profiles = {(p.profile_id, p.version): p for p in profiles}
        if len(self.profiles) != len(profiles):
            raise ValueError("Duplicate payout profile version")

    def get(self, reference: PayoutReference) -> PayoutProfile:
        profile = self.profiles.get((reference.profile_id, reference.version))
        if (profile is None or profile.rule_revision != reference.rule_revision
                or profile.native_key[3:] != (reference.instrument_id, reference.side_id)):
            raise ValueError("Unknown/stale or sibling payout profile reference")
        return profile


@dataclass(frozen=True)
class ScoreRange:
    lower: int | None
    upper: int | None

    def __post_init__(self):
        if any(x is not None and type(x) is not int for x in (self.lower, self.upper)):
            raise ValueError("Integer score interval required")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("Contradictory sporting score interval")

    def contains(self, value: int) -> bool:
        return (self.lower is None or self.lower <= value) and (self.upper is None or value <= self.upper)


@dataclass(frozen=True)
class JointState:
    state_id: str
    terminal: str
    score_range: ScoreRange | None
    aliases: tuple[str, ...]
    payouts: tuple[PayoutCell, ...]


@dataclass(frozen=True)
class JointTable:
    states: tuple[JointState, ...]
    leg_revisions: tuple[str, ...]
    revision: str
    coverage: str
    payout_units: tuple[str, ...]
    evaluated_at: str
    completion_conditions: tuple[dict, ...]

    def to_dict(self) -> dict:
        return dict(schema_version=VERSION, revision=self.revision, coverage=self.coverage,
                    universe="integer_completed_scores_or_noncompleted_terminal" if self.coverage != "conditional_completed" else "integer_completed_scores_only",
                    evaluated_at=self.evaluated_at,
                    completion_conditions=list(self.completion_conditions),
                    leg_revisions=list(self.leg_revisions), payout_units=list(self.payout_units),
                    states=[dict(state_id=s.state_id, terminal=s.terminal,
                                 score_range=dict(lower=s.score_range.lower, upper=s.score_range.upper) if s.score_range else None,
                                 aliases=list(s.aliases), payouts=[p.to_dict() for p in s.payouts]) for s in self.states])


def validate_states(states: tuple[JointState, ...], *, minimum: int | None, legs: int,
                    include_exceptions: bool) -> None:
    """Independent structural partition gate: disjoint integer ranges and terminals."""
    if not isinstance(states, tuple) or not states or len(states) > MAX_STATES or len({s.state_id for s in states}) != len(states):
        raise ValueError("Bounded unique joint states required")
    ordinary = [s for s in states if s.terminal == "completed"]
    exceptions = [s for s in states if s.terminal == "noncompleted"]
    if len(ordinary) + len(exceptions) != len(states) or len(exceptions) != int(include_exceptions):
        raise ValueError("Exactly one noncompleted bucket; overlapping labels cannot be outcomes")
    if not ordinary or ordinary[0].score_range is None or ordinary[0].score_range.lower != minimum:
        raise ValueError("Sporting partition does not start at feasible domain boundary")
    for index, state in enumerate(ordinary):
        interval = state.score_range
        if interval is None or state.aliases or (minimum == 0 and interval.lower is not None and interval.lower < 0):
            raise ValueError("Feasible sporting score interval required")
        if index:
            previous = ordinary[index - 1].score_range
            if previous.upper is None or interval.lower != previous.upper + 1:
                raise ValueError("Overlapping or incomplete sporting partitions")
    if ordinary[-1].score_range.upper is not None:
        raise ValueError("Sporting partition does not exhaust feasible domain")
    if exceptions and (exceptions[0].score_range is not None or exceptions[0].aliases != EXCEPTION_ALIASES):
        raise ValueError("Lifecycle labels must alias the single terminal bucket")
    if any(len(s.payouts) != legs or any(not isinstance(p, PayoutCell) for p in s.payouts) for s in states):
        raise ValueError("Each joint state requires every leg payout, retaining unknowns")


def joint_states(legs: tuple[BoundLeg, ...], *, at: datetime, include_exceptions: bool = True) -> JointTable:
    if (not isinstance(legs, tuple) or not 1 <= len(legs) <= MAX_LEGS
            or any(not isinstance(leg, BoundLeg) for leg in legs)
            or len({leg.selection.native.key for leg in legs}) != len(legs)):
        raise ValueError("Bounded distinct bound legs required")
    if type(include_exceptions) is not bool:
        raise ValueError("Explicit exceptional-state coverage required")
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("Aware joint-state applicability instant required")
    for leg in legs:
        if at < instant(leg.profile.effective_from) or (leg.profile.effective_until is not None and at >= instant(leg.profile.effective_until)):
            raise ValueError("Payout profile expired or not effective for joint states")
    first = legs[0].selection
    domain_key = (first.event.key, first.scope.key, first.predicate.domain, first.predicate.subject_id)
    if any((leg.selection.event.key, leg.selection.scope.key, leg.selection.predicate.domain,
            leg.selection.predicate.subject_id) != domain_key for leg in legs):
        raise ValueError("Joint partition unavailable for differing event/scope/score domains")
    minimum = None if first.predicate.domain == "home_margin" else 0
    cuts = set()
    for leg in legs:
        t = leg.selection.predicate.threshold.value
        floor = t.numerator // t.denominator
        if t.denominator == 1:
            cuts.update((floor, floor + 1))
        else:
            cuts.add(floor + 1)
    cuts = sorted(c for c in cuts if minimum is None or c > minimum)
    states = []
    lower = minimum
    for upper in [c - 1 for c in cuts] + [None]:
        interval = ScoreRange(lower, upper)
        representative = lower if lower is not None else upper if upper is not None else 0
        payouts = []
        for leg in legs:
            t = leg.selection.predicate.threshold.value
            name = "below" if representative < t else "above" if representative > t else "equal"
            payouts.append(leg.normal_payout(name))
        states.append(JointState("completed:" + str(lower) + ":" + str(upper), "completed", interval, (), tuple(payouts)))
        if upper is not None:
            lower = upper + 1
    if include_exceptions:
        states.append(JointState("noncompleted", "noncompleted", None, EXCEPTION_ALIASES,
                                 tuple(leg.profile.noncompleted for leg in legs)))
    validate_states(tuple(states), minimum=minimum, legs=len(legs), include_exceptions=include_exceptions)
    all_evidenced = all(p.status == "evidenced" for state in states for p in state.payouts)
    has_unknown = any(p.status == "unknown" for state in states for p in state.payouts)
    coverage = ("complete_partition_evidenced_payouts" if all_evidenced else "complete_partition_local_unknowns" if has_unknown else "complete_partition_estimated_payouts") if include_exceptions else "conditional_completed"
    revision = _digest([VERSION, [leg.revision for leg in legs], include_exceptions,
                        [(s.state_id, [p.to_dict() for p in s.payouts]) for s in states]])
    return JointTable(tuple(states), tuple(leg.revision for leg in legs), revision, coverage,
                      tuple(leg.profile.payout_unit for leg in legs), at.isoformat(),
                      tuple(dict(condition=leg.profile.normal_condition.to_dict(), context=leg.context.to_dict(),
                                 normal_eligible=leg.normal_eligible, reason=leg.normal_reason) for leg in legs))
