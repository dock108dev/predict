"""Validated immutable observations, not matching or execution decisions."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import json
from functools import lru_cache


def text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def optional_text(value: str | None, name: str) -> None:
    if value is not None:
        text(value, name)


def typed(value: object, cls: type, name: str) -> None:
    if not isinstance(value, cls):
        raise ValueError(f"{name} must be {cls.__name__}")


def aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def decimal_value(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")


def parse_decimal(value: str | int | Decimal) -> Decimal:
    """Explicit wire conversion, rejecting floats/bools instead of rounding them."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("expected decimal text, int or Decimal; floats are unsafe")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid decimal") from exc
    decimal_value(result, "value")
    return result


class Venue(StrEnum):
    KALSHI = "kalshi"
    POLYMARKET_US = "polymarket_us"
    PROPHETX = "prophetx"
    NOVIG = "novig"
    SYNTHETIC = "synthetic"


class MarketState(StrEnum):
    UNKNOWN = "unknown"
    PREOPEN = "preopen"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    SETTLED = "settled"
    CANCELED = "canceled"


class MarketType(StrEnum):
    UNKNOWN = "unknown"
    MONEYLINE = "moneyline"


class SettlementCompatibility(StrEnum):
    UNKNOWN = "unknown"
    EXACT = "exact"
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"


class Depth(StrEnum):
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    FULL = "full"


class BookSync(StrEnum):
    """Adapter-qualified reconstruction of its declared image, not freshness/depth/history."""

    UNKNOWN = "unknown"
    UNSYNCHRONIZED = "unsynchronized"
    SYNCHRONIZED = "synchronized"


class ReceiptFreshness(StrEnum):
    """Recency of the accepted local receipt; not exchange-clock freshness."""

    UNKNOWN = "unknown"
    RECENT = "recent"
    STALE = "stale"


class SourceTimeProgress(StrEnum):
    """Source timestamp relative to the adapter's prior high-water mark, not latency."""

    UNKNOWN = "unknown"
    MISSING = "missing"
    FIRST = "first"
    ADVANCED = "advanced"
    REPEATED = "repeated"
    REGRESSED = "regressed"


class EvidenceKind(StrEnum):
    UNKNOWN = "unknown"
    SYNTHETIC = "synthetic"
    DOCUMENTATION = "documentation"
    OBSERVATION = "observation"


@dataclass(frozen=True, kw_only=True)
class Probability:
    """Dimensionless payout fraction [0,1], never native cents or odds."""

    value: Decimal

    def __post_init__(self) -> None:
        decimal_value(self.value, "price")
        if not Decimal(0) <= self.value <= Decimal(1):
            raise ValueError("probability must be between 0 and 1 inclusive")


@dataclass(frozen=True, kw_only=True)
class Quantity:
    """Explicit unit, e.g. contracts, USD_stake, payout_cents, unknown."""

    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        decimal_value(self.value, "quantity")
        if self.value < 0:
            raise ValueError("quantity must be nonnegative")
        text(self.unit, "quantity unit")


@dataclass(frozen=True, kw_only=True)
class Money:
    """Signed amount in a declared currency; no implicit currency conversion."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        decimal_value(self.amount, "money")
        if not isinstance(self.currency, str) or len(self.currency) != 3 or not (
            self.currency.isascii() and self.currency.isalpha() and self.currency.isupper()
        ):
            raise ValueError("currency must be a three-letter uppercase code")


@dataclass(frozen=True, kw_only=True)
class NativeRef:
    venue: Venue
    event_id: str
    market_id: str | None = None

    def __post_init__(self) -> None:
        typed(self.venue, Venue, "venue")
        text(self.event_id, "event_id")
        optional_text(self.market_id, "market_id")


def reject_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant: {value}")


@lru_cache(maxsize=4)
def _validate_json_text(value: str) -> None:
    """Cache validation only; decode() still returns a fresh mutable object."""
    json.loads(value, parse_float=Decimal, parse_constant=reject_constant)


@dataclass(frozen=True, kw_only=True)
class RawPayload:
    """Original JSON text is immutable; decoding returns a separate object.

    A source can be a URI, endpoint or feed/channel label. Receipt and exchange
    times have different meanings. No ordering or latency inference is made.
    """

    ref: NativeRef
    source: str
    received_at: datetime
    json_text: str
    exchange_at: datetime | None = None
    kind: EvidenceKind = EvidenceKind.UNKNOWN

    def __post_init__(self) -> None:
        typed(self.ref, NativeRef, "ref")
        typed(self.kind, EvidenceKind, "evidence kind")
        text(self.source, "source")
        text(self.json_text, "json_text")
        aware(self.received_at, "received_at")
        if self.exchange_at is not None:
            aware(self.exchange_at, "exchange_at")
        _validate_json_text(self.json_text)

    @property
    def source_age_at_receipt(self):
        """Signed receipt minus exchange time (microsecond resolution), not latency.

        None means missing source time. Negative values expose clock disagreement.
        An old last-change time does not invalidate an otherwise valid quiet image.
        """
        return None if self.exchange_at is None else self.received_at - self.exchange_at

    def receipt_age(self, as_of: datetime):
        """Caller-chosen evaluation time; no implicit freshness threshold."""
        aware(as_of, "as_of")
        return as_of - self.received_at

    def decode(self) -> object:
        return json.loads(self.json_text, parse_float=Decimal, parse_constant=reject_constant)


def market_raw(raw: RawPayload) -> None:
    typed(raw, RawPayload, "raw")
    if raw.ref.market_id is None:
        raise ValueError("market observation requires a native market_id")


def tuple_of(values: tuple, cls: type, name: str) -> None:
    typed(values, tuple, name)
    for value in values:
        typed(value, cls, name)


@dataclass(frozen=True, kw_only=True)
class Event:
    raw: RawPayload
    title: str
    participants: tuple[str, ...] = ()
    sport: str | None = None
    league: str | None = None
    scheduled_start: datetime | None = None
    canonical_id: str | None = None

    def __post_init__(self) -> None:
        typed(self.raw, RawPayload, "raw")
        if self.raw.ref.market_id is not None:
            raise ValueError("event source must use an event-level reference")
        text(self.title, "title")
        tuple_of(self.participants, str, "participants")
        for participant in self.participants:
            text(participant, "participant")
        for name in ("sport", "league", "canonical_id"):
            optional_text(getattr(self, name), name)
        if self.scheduled_start is not None:
            aware(self.scheduled_start, "scheduled_start")


@dataclass(frozen=True, kw_only=True)
class Outcome:
    native_id: str
    label: str
    canonical_id: str | None = None

    def __post_init__(self) -> None:
        text(self.native_id, "outcome_id")
        text(self.label, "outcome label")
        optional_text(self.canonical_id, "canonical_id")


@dataclass(frozen=True, kw_only=True)
class Market:
    raw: RawPayload
    title: str
    outcomes: tuple[Outcome, ...]
    market_type: MarketType = MarketType.UNKNOWN
    state: MarketState = MarketState.UNKNOWN
    period: str | None = None
    canonical_id: str | None = None

    def __post_init__(self) -> None:
        market_raw(self.raw)
        text(self.title, "title")
        tuple_of(self.outcomes, Outcome, "outcomes")
        ids = [outcome.native_id for outcome in self.outcomes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate native outcome IDs")
        typed(self.market_type, MarketType, "market_type")
        typed(self.state, MarketState, "market state")
        optional_text(self.period, "period")
        optional_text(self.canonical_id, "canonical_id")


@dataclass(frozen=True, kw_only=True)
class QuoteSide:
    price: Probability
    quantity: Quantity | None = None

    def __post_init__(self) -> None:
        typed(self.price, Probability, "price")
        if self.quantity is not None:
            typed(self.quantity, Quantity, "quantity")


@dataclass(frozen=True, kw_only=True)
class Quote:
    raw: RawPayload
    outcome_id: str
    bid: QuoteSide | None = None
    ask: QuoteSide | None = None
    state: MarketState = MarketState.UNKNOWN

    def __post_init__(self) -> None:
        market_raw(self.raw)
        text(self.outcome_id, "outcome_id")
        typed(self.state, MarketState, "market state")
        for side in (self.bid, self.ask):
            if side is not None:
                typed(side, QuoteSide, "quote side")
        if self.bid and self.ask and self.bid.quantity and self.ask.quantity:
            if self.bid.quantity.unit != self.ask.quantity.unit:
                raise ValueError("quote sides must use the same declared quantity unit")


@dataclass(frozen=True, kw_only=True)
class BookLevel:
    price: Probability
    quantity: Quantity

    def __post_init__(self) -> None:
        typed(self.price, Probability, "price")
        typed(self.quantity, Quantity, "quantity")
        if self.quantity.value <= 0:
            raise ValueError("snapshot levels require positive size; zero is not a level")


@dataclass(frozen=True, kw_only=True)
class Ladder:
    """Empty levels means an observed empty side, not an unavailable side."""

    levels: tuple[BookLevel, ...]
    depth: Depth = Depth.UNKNOWN

    def __post_init__(self) -> None:
        tuple_of(self.levels, BookLevel, "levels")
        typed(self.depth, Depth, "depth")
        prices = [level.price.value for level in self.levels]
        if len(prices) != len(set(prices)):
            raise ValueError("snapshot levels must aggregate duplicate prices explicitly")


@dataclass(frozen=True, kw_only=True)
class OutcomeBook:
    """A native outcome ladder; do not synthesize complementary asks here."""

    outcome_id: str
    bids: Ladder | None = None
    asks: Ladder | None = None

    def __post_init__(self) -> None:
        text(self.outcome_id, "outcome_id")
        for ladder, reverse in ((self.bids, True), (self.asks, False)):
            if ladder is not None:
                typed(ladder, Ladder, "ladder")
                prices = [level.price.value for level in ladder.levels]
                if prices != sorted(prices, reverse=reverse):
                    raise ValueError("bids must descend and asks ascend; adapter must normalize")


@dataclass(frozen=True, kw_only=True)
class OrderBook:
    """Whole observed image, not a native delta or proof of executable liquidity."""

    raw: RawPayload
    quantity_unit: str
    outcomes: tuple[OutcomeBook, ...]
    state: MarketState = MarketState.UNKNOWN
    sync: BookSync = BookSync.UNKNOWN
    receipt_freshness: ReceiptFreshness = ReceiptFreshness.UNKNOWN
    source_time_progress: SourceTimeProgress = SourceTimeProgress.UNKNOWN
    sequence: str | None = None

    def __post_init__(self) -> None:
        market_raw(self.raw)
        text(self.quantity_unit, "quantity_unit")
        tuple_of(self.outcomes, OutcomeBook, "outcome books")
        typed(self.state, MarketState, "market state")
        typed(self.sync, BookSync, "book sync")
        typed(self.receipt_freshness, ReceiptFreshness, "receipt freshness")
        typed(self.source_time_progress, SourceTimeProgress, "source time progress")
        optional_text(self.sequence, "sequence")
        ids = [outcome.outcome_id for outcome in self.outcomes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate outcome books")
        for outcome in self.outcomes:
            for ladder in (outcome.bids, outcome.asks):
                if ladder is not None:
                    for level in ladder.levels:
                        if level.quantity.unit != self.quantity_unit:
                            raise ValueError("level quantity unit differs from book unit")


@dataclass(frozen=True, kw_only=True)
class SettlementProfile:
    raw: RawPayload
    rules_text: str | None = None
    official_source: str | None = None
    includes_overtime: bool | None = None
    tie_behavior: str | None = None
    postponement_behavior: str | None = None
    cancellation_behavior: str | None = None

    def __post_init__(self) -> None:
        market_raw(self.raw)
        for name in ("rules_text", "official_source", "tie_behavior",
                     "postponement_behavior", "cancellation_behavior"):
            optional_text(getattr(self, name), name)
        if self.includes_overtime is not None and type(self.includes_overtime) is not bool:
            raise ValueError("includes_overtime must be bool or None")


@dataclass(frozen=True, kw_only=True)
class SettlementComparison:
    """Compatibility belongs to a pair, never to a venue or profile globally."""

    left: NativeRef
    right: NativeRef
    compatibility: SettlementCompatibility = SettlementCompatibility.UNKNOWN
    rationale: str | None = None

    def __post_init__(self) -> None:
        for ref in (self.left, self.right):
            typed(ref, NativeRef, "comparison reference")
            if ref.market_id is None:
                raise ValueError("comparison requires two market references")
        typed(self.compatibility, SettlementCompatibility, "compatibility")
        optional_text(self.rationale, "rationale")
        if self.compatibility != SettlementCompatibility.UNKNOWN and self.rationale is None:
            raise ValueError("a non-unknown comparison requires a rationale")
