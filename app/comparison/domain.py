"""Strict canonical comparison vocabulary; no acquisition or label-based inference.

Predicate identity and payout applicability deliberately have separate keys. Exact
original numbers survive the wire representation, while keys use rational values.
"""
from dataclasses import dataclass
from fractions import Fraction
import re
from typing import Any, Mapping

VERSION = "comparison-domain-1"
LEAGUES = frozenset({"NFL", "NCAAF", "NBA", "NCAAB", "MLB", "NHL"})
VENUES = frozenset({"kalshi", "polymarket_us", "novig", "prophetx", "pinnacle"})
FAMILIES = frozenset({"moneyline", "team_binary", "spread", "total", "team_total"})
OPERATORS = frozenset({"gt", "ge", "lt", "le", "eq", "ne"})
PERIODS = frozenset({"full_game", "first_half", "first_quarter", "second_quarter",
                    "third_quarter", "fourth_quarter", "first_period", "second_period",
                    "third_period", "first_1", "first_3", "first_5", "first_7"})
EVIDENCE_CLASSES = frozenset({"authored", "retained", "primary_source", "manual_review"})
_EXACT = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\d+/[1-9]\d*)\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(name + " requires a nonempty exact string")
    return value


def _choice(value: Any, choices: frozenset, name: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError("Unsupported " + name)
    return value


def _object(value: Any, fields: set[str], name: str) -> Mapping:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(name + " has missing or unknown fields")
    return value


def _evidence(value: Any) -> tuple:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise ValueError("A bounded nonempty evidence list is required")
    return tuple(EvidenceReference.from_dict(item) for item in value)


@dataclass(frozen=True)
class ExactNumber:
    original: str

    def __post_init__(self):
        if (not isinstance(self.original, str) or len(self.original) > 128
                or not _EXACT.fullmatch(self.original)):
            raise ValueError("Exact decimal or rational string required; floats are prohibited")
        Fraction(self.original)

    @classmethod
    def parse(cls, value: Any) -> "ExactNumber":
        return cls(value)

    @property
    def value(self) -> Fraction:
        return Fraction(self.original)

    @property
    def key(self) -> tuple[int, int]:
        return self.value.numerator, self.value.denominator


@dataclass(frozen=True)
class EvidenceReference:
    ref: str
    sha256: str
    evidence_class: str

    def __post_init__(self):
        _text(self.ref, "Evidence ref")
        if not isinstance(self.sha256, str) or not _DIGEST.fullmatch(self.sha256):
            raise ValueError("Exact sanitized evidence digest required")
        _choice(self.evidence_class, EVIDENCE_CLASSES, "evidence class")

    @classmethod
    def from_dict(cls, value: Any) -> "EvidenceReference":
        d = _object(value, {"ref", "sha256", "evidence_class"}, "Evidence")
        return cls(**d)

    def to_dict(self) -> dict:
        return dict(ref=self.ref, sha256=self.sha256, evidence_class=self.evidence_class)


@dataclass(frozen=True)
class UnknownValue:
    reason: str
    missing_evidence: tuple[str, ...]

    def __post_init__(self):
        _text(self.reason, "Unknown reason")
        if not isinstance(self.missing_evidence, tuple) or not self.missing_evidence:
            raise ValueError("Unknown value requires named missing evidence")
        for item in self.missing_evidence:
            _text(item, "Missing evidence")

    def to_dict(self) -> dict:
        return dict(value=None, reason=self.reason, missing_evidence=list(self.missing_evidence))


@dataclass(frozen=True)
class EventReference:
    occurrence_id: str
    league: str
    home_id: str
    away_id: str
    identity_evidence: tuple[EvidenceReference, ...]

    def __post_init__(self):
        for name in ("occurrence_id", "home_id", "away_id"):
            _text(getattr(self, name), name)
        _choice(self.league, LEAGUES, "league")
        if self.home_id == self.away_id:
            raise ValueError("Distinct participant roles required")
        if (not isinstance(self.identity_evidence, tuple) or not self.identity_evidence
                or len(self.identity_evidence) > 32
                or any(not isinstance(x, EvidenceReference) for x in self.identity_evidence)):
            raise ValueError("Durable identity evidence required")

    @classmethod
    def from_dict(cls, value: Any) -> "EventReference":
        d = _object(value, {"occurrence_id", "league", "home_id", "away_id", "identity_evidence"}, "Event")
        return cls(d["occurrence_id"], d["league"], d["home_id"], d["away_id"], _evidence(d["identity_evidence"]))

    def to_dict(self) -> dict:
        return dict(occurrence_id=self.occurrence_id, league=self.league,
                    home_id=self.home_id, away_id=self.away_id,
                    identity_evidence=[x.to_dict() for x in self.identity_evidence])

    @property
    def key(self) -> tuple:
        return self.occurrence_id, self.league, self.home_id, self.away_id


@dataclass(frozen=True)
class Scope:
    period: str
    overtime: str
    completion: str

    def __post_init__(self):
        _choice(self.period, PERIODS, "period")
        _choice(self.overtime, frozenset({"included", "excluded", "unknown"}), "overtime scope")
        _text(self.completion, "Completion terms")
        if self.period != "full_game" and self.overtime == "included":
            raise ValueError("Partial periods cannot include later overtime")

    @classmethod
    def from_dict(cls, value: Any) -> "Scope":
        return cls(**_object(value, {"period", "overtime", "completion"}, "Scope"))

    def to_dict(self) -> dict:
        return dict(period=self.period, overtime=self.overtime, completion=self.completion)

    @property
    def key(self) -> tuple:
        return self.period, self.overtime, self.completion


@dataclass(frozen=True)
class ScorePredicate:
    domain: str
    operator: str
    threshold: ExactNumber
    subject_id: str | None = None

    def __post_init__(self):
        _choice(self.domain, frozenset({"home_margin", "combined_score", "team_score"}), "score domain")
        _choice(self.operator, OPERATORS, "score operator")
        if not isinstance(self.threshold, ExactNumber):
            raise ValueError("Exact threshold required")
        if self.threshold.value * 2 != int(self.threshold.value * 2):
            raise ValueError("Pilot supports integer and half-point lines only")
        if self.domain != "home_margin" and self.threshold.value < 0:
            raise ValueError("Nonnegative score threshold required")
        if self.domain == "team_score":
            _text(self.subject_id, "Team-score subject")
        elif self.subject_id is not None:
            raise ValueError("Only team-score predicates have a score subject")

    @classmethod
    def from_dict(cls, value: Any) -> "ScorePredicate":
        d = _object(value, {"domain", "operator", "threshold", "subject_id"}, "Predicate")
        return cls(d["domain"], d["operator"], ExactNumber.parse(d["threshold"]), d["subject_id"])

    def to_dict(self) -> dict:
        return dict(domain=self.domain, operator=self.operator,
                    threshold=self.threshold.original, subject_id=self.subject_id)

    @property
    def key(self) -> tuple:
        # Sporting score domains are integer-valued. Equality to a half point
        # is infeasible, so inclusive/strict wording shares the same predicate.
        operator = self.operator
        if self.threshold.value.denominator == 2:
            operator = {"ge": "gt", "le": "lt"}.get(operator, operator)
        return self.domain, operator, self.threshold.key, self.subject_id

    def evaluate(self, event: EventReference, home_score: int, away_score: int) -> bool:
        if any(type(x) is not int or x < 0 for x in (home_score, away_score)):
            raise ValueError("Nonnegative integer sporting scores required")
        if self.domain == "home_margin":
            score = home_score - away_score
        elif self.domain == "combined_score":
            score = home_score + away_score
        elif self.subject_id == event.home_id:
            score = home_score
        elif self.subject_id == event.away_id:
            score = away_score
        else:
            raise ValueError("Score subject is outside event")
        t = self.threshold.value
        return {"gt": score > t, "ge": score >= t, "lt": score < t,
                "le": score <= t, "eq": score == t, "ne": score != t}[self.operator]


@dataclass(frozen=True)
class EqualityDescriptor:
    treatment: str
    payout: ExactNumber | None
    refund_fees: str
    unknown_reason: str | None

    def __post_init__(self):
        _choice(self.treatment, frozenset({"predicate", "stake_refund", "fraction", "unknown", "not_feasible"}), "equality treatment")
        _choice(self.refund_fees, frozenset({"retained", "returned", "unknown", "not_applicable"}), "refund-fee treatment")
        if self.treatment == "fraction":
            if not isinstance(self.payout, ExactNumber) or not 0 <= self.payout.value <= 1:
                raise ValueError("Equality fraction requires exact payout in [0,1]")
        elif self.payout is not None:
            raise ValueError("Only fractional equality carries scalar face payout")
        if self.treatment == "unknown":
            _text(self.unknown_reason, "Unknown equality reason")
        elif self.unknown_reason is not None:
            raise ValueError("Known equality cannot carry unknown reason")
        if self.treatment != "stake_refund" and self.refund_fees != "not_applicable":
            raise ValueError("Fee refund applies only to a stake refund")

    @classmethod
    def from_dict(cls, value: Any) -> "EqualityDescriptor":
        d = _object(value, {"treatment", "payout", "refund_fees", "unknown_reason"}, "Equality")
        return cls(d["treatment"], ExactNumber.parse(d["payout"]) if d["payout"] is not None else None,
                   d["refund_fees"], d["unknown_reason"])

    def to_dict(self) -> dict:
        return dict(treatment=self.treatment, payout=self.payout.original if self.payout else None,
                    refund_fees=self.refund_fees, unknown_reason=self.unknown_reason)


@dataclass(frozen=True)
class NativeProvenance:
    venue: str
    event_id: str
    market_id: str
    instrument_id: str
    side_id: str
    original_wording: str
    evidence: tuple[EvidenceReference, ...]

    def __post_init__(self):
        _choice(self.venue, VENUES, "venue")
        for name in ("event_id", "market_id", "instrument_id", "side_id", "original_wording"):
            _text(getattr(self, name), "Native " + name)
        if (not isinstance(self.evidence, tuple) or not self.evidence or len(self.evidence) > 32
                or any(not isinstance(x, EvidenceReference) for x in self.evidence)):
            raise ValueError("Native provenance evidence required")

    @classmethod
    def from_dict(cls, value: Any) -> "NativeProvenance":
        d = _object(value, {"venue", "event_id", "market_id", "instrument_id", "side_id", "original_wording", "evidence"}, "Native provenance")
        return cls(**dict(d, evidence=_evidence(d["evidence"])))

    def to_dict(self) -> dict:
        return dict(venue=self.venue, event_id=self.event_id, market_id=self.market_id,
                    instrument_id=self.instrument_id, side_id=self.side_id,
                    original_wording=self.original_wording, evidence=[x.to_dict() for x in self.evidence])

    @property
    def key(self) -> tuple:
        return self.venue, self.event_id, self.market_id, self.instrument_id, self.side_id


@dataclass(frozen=True)
class PayoutReference:
    profile_id: str
    version: str
    rule_revision: str
    instrument_id: str
    side_id: str

    def __post_init__(self):
        for name in ("profile_id", "version", "rule_revision", "instrument_id", "side_id"):
            _text(getattr(self, name), "Payout " + name)

    @classmethod
    def from_dict(cls, value: Any) -> "PayoutReference":
        return cls(**_object(value, {"profile_id", "version", "rule_revision", "instrument_id", "side_id"}, "Payout reference"))

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in ("profile_id", "version", "rule_revision", "instrument_id", "side_id")}


@dataclass(frozen=True)
class Quantity:
    amount: ExactNumber
    unit: str
    currency: str | None

    def __post_init__(self):
        if not isinstance(self.amount, ExactNumber) or self.amount.value < 0:
            raise ValueError("Nonnegative exact quantity required")
        _choice(self.unit, frozenset({"usd", "contracts", "usd_risk", "usd_payout"}), "quantity unit")
        if self.currency != (None if self.unit == "contracts" else "USD"):
            raise ValueError("Quantity currency conflicts with unit")

    def to_dict(self) -> dict:
        return dict(amount=self.amount.original, unit=self.unit, currency=self.currency)


@dataclass(frozen=True)
class Price:
    amount: ExactNumber
    unit: str
    payout_unit: str
    currency: str

    def __post_init__(self):
        if not isinstance(self.amount, ExactNumber):
            raise ValueError("Exact original price required")
        _choice(self.unit, frozenset({"usd_per_contract", "cents_per_contract", "decimal_odds", "american_odds"}), "price unit")
        _choice(self.payout_unit, frozenset({"usd_per_contract", "usd_per_usd_stake"}), "payout unit")
        if self.currency != "USD":
            raise ValueError("Pilot price currency must be USD")
        x = self.amount.value
        if self.unit == "usd_per_contract" and not 0 <= x <= 1:
            raise ValueError("Contract price outside [0,1]")
        if self.unit == "cents_per_contract" and not 0 <= x <= 100:
            raise ValueError("Contract cents price outside [0,100]")
        if self.unit == "decimal_odds" and x <= 1:
            raise ValueError("Decimal odds must exceed one")
        if self.unit == "american_odds" and abs(x) < 100:
            raise ValueError("American odds magnitude must be at least 100")
        contract = self.unit in {"usd_per_contract", "cents_per_contract"}
        if self.payout_unit != ("usd_per_contract" if contract else "usd_per_usd_stake"):
            raise ValueError("Price and payout units conflict")

    @classmethod
    def from_dict(cls, value: Any) -> "Price":
        d = _object(value, {"amount", "unit", "payout_unit", "currency"}, "Price")
        return cls(ExactNumber.parse(d["amount"]), d["unit"], d["payout_unit"], d["currency"])

    def to_dict(self) -> dict:
        return dict(amount=self.amount.original, unit=self.unit, payout_unit=self.payout_unit, currency=self.currency)


@dataclass(frozen=True)
class CanonicalSelection:
    event: EventReference
    family: str
    scope: Scope
    participant_id: str
    signed_line: ExactNumber | None
    predicate: ScorePredicate
    equality: EqualityDescriptor
    native: NativeProvenance
    payout: PayoutReference | None
    price: Price
    payout_unknown: UnknownValue | None = None

    def __post_init__(self):
        for name, kind in (("event", EventReference), ("scope", Scope), ("predicate", ScorePredicate),
                           ("equality", EqualityDescriptor), ("native", NativeProvenance), ("price", Price)):
            if not isinstance(getattr(self, name), kind):
                raise ValueError("Typed " + name + " required")
        _choice(self.family, FAMILIES, "family")
        _text(self.participant_id, "Canonical participant")
        if self.family == "total":
            if self.participant_id != "combined" or self.predicate.domain != "combined_score":
                raise ValueError("Combined total must use combined score")
        elif self.participant_id not in {self.event.home_id, self.event.away_id, "tie"}:
            raise ValueError("Participant is outside canonical event")
        if self.family == "team_total":
            if (self.participant_id not in {self.event.home_id, self.event.away_id}
                    or self.predicate.domain != "team_score" or self.predicate.subject_id != self.participant_id):
                raise ValueError("Team total requires selected team score")
        elif self.family in {"moneyline", "team_binary", "spread"}:
            if self.predicate.domain != "home_margin":
                raise ValueError("Winner/spread must use canonical home margin")
        if self.family == "spread":
            if not isinstance(self.signed_line, ExactNumber) or self.participant_id == "tie":
                raise ValueError("Spread requires exact signed participant handicap")
            expected = -self.signed_line.value if self.participant_id == self.event.home_id else self.signed_line.value
            if self.predicate.threshold.value != expected:
                raise ValueError("Signed handicap conflicts with canonical threshold")
        elif self.signed_line is not None:
            raise ValueError("Signed handicap belongs only to spreads")
        if self.family in {"moneyline", "team_binary"} and self.predicate.threshold.value != 0:
            raise ValueError("Winner predicate threshold must be zero")
        if self.participant_id == "tie" and self.predicate.operator not in {"eq", "ne"}:
            raise ValueError("Tie selection requires equality or its explicit complement")
        if self.payout is None:
            if not isinstance(self.payout_unknown, UnknownValue):
                raise ValueError("Missing payout profile requires local unknown evidence")
        elif (not isinstance(self.payout, PayoutReference) or self.payout_unknown is not None
              or (self.payout.instrument_id, self.payout.side_id) != (self.native.instrument_id, self.native.side_id)):
            raise ValueError("Payout reference conflicts with exact native selection")

    @classmethod
    def from_dict(cls, value: Any) -> "CanonicalSelection":
        d = _object(value, {"schema_version", "event", "family", "scope", "participant_id", "signed_line",
                            "predicate", "equality", "native", "payout", "price", "payout_unknown"}, "Selection")
        if d["schema_version"] != VERSION:
            raise ValueError("Unsupported comparison schema version")
        u = d["payout_unknown"]
        unknown = None
        if u is not None:
            _object(u, {"value", "reason", "missing_evidence"}, "Unknown payout")
            if u["value"] is not None or not isinstance(u["missing_evidence"], list):
                raise ValueError("Unknown payout must retain null and missing evidence")
            unknown = UnknownValue(u["reason"], tuple(u["missing_evidence"]))
        return cls(EventReference.from_dict(d["event"]), d["family"], Scope.from_dict(d["scope"]),
                   d["participant_id"], ExactNumber.parse(d["signed_line"]) if d["signed_line"] is not None else None,
                   ScorePredicate.from_dict(d["predicate"]), EqualityDescriptor.from_dict(d["equality"]),
                   NativeProvenance.from_dict(d["native"]), PayoutReference.from_dict(d["payout"]) if d["payout"] is not None else None,
                   Price.from_dict(d["price"]), unknown)

    def to_dict(self) -> dict:
        return dict(schema_version=VERSION, event=self.event.to_dict(), family=self.family,
                    scope=self.scope.to_dict(), participant_id=self.participant_id,
                    signed_line=self.signed_line.original if self.signed_line else None,
                    predicate=self.predicate.to_dict(), equality=self.equality.to_dict(),
                    native=self.native.to_dict(), payout=self.payout.to_dict() if self.payout else None,
                    price=self.price.to_dict(), payout_unknown=self.payout_unknown.to_dict() if self.payout_unknown else None)

    def semantic_key(self) -> tuple:
        """Same sporting predicate; does not assert equivalent settlement/cashflows."""
        if self.scope.overtime == "unknown" or self.scope.completion in {"unknown", "unverified"}:
            raise ValueError("Unresolved sporting scope cannot establish a semantic match")
        return VERSION, self.event.key, self.scope.key, self.predicate.key

    def cashflow_key(self) -> tuple:
        """Exact profile/equality association, independent of current price."""
        equality = self.equality
        payout = self.payout
        return (self.semantic_key(), equality.treatment, equality.payout.key if equality.payout else None,
                equality.refund_fees, equality.unknown_reason,
                tuple(payout.to_dict().items()) if payout else None,
                self.price.payout_unit, self.payout_unknown)
