"""E1 immutable reference/pricing/signal contracts, not a pricing or strategy engine.

JSON replay is isolated from capture-bundle-1 and never opens a database.
Core units and settlement validation remain owned by their existing modules.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from hashlib import sha256
import json
import types
from typing import Literal, get_args, get_origin, get_type_hints

from app.models import core
from app.models.core import (Probability, Quantity, Money, Venue, MarketType,
                             aware, decimal_value, parse_decimal, reject_constant)
from app.settlement import validate as validate_settlement


class Status(StrEnum):
    AVAILABLE = 'available'
    DEGRADED = 'degraded'
    UNAVAILABLE = 'unavailable'
    RESEARCH_ONLY = 'research_only'
    CONDITIONAL = 'conditional'


def _check(value, annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is types.UnionType:
        for option in args:
            try:
                _check(value, option)
                return
            except ValueError:
                pass
        raise ValueError('value does not match declared union')
    if origin is Literal:
        if value not in args or type(value) not in {type(x) for x in args}:
            raise ValueError('invalid literal')
    elif origin is tuple:
        if type(value) is not tuple:
            raise ValueError('immutable tuple required')
        if len(args) == 2 and args[1] is Ellipsis:
            for item in value:
                _check(item, args[0])
        else:
            if len(value) != len(args):
                raise ValueError('wrong tuple length')
            for item, kind in zip(value, args):
                _check(item, kind)
    elif annotation is datetime:
        aware(value, 'timestamp')
    elif annotation is Decimal:
        decimal_value(value, 'decimal')
    elif annotation in (str, bool, int, type(None)):
        if type(value) is not annotation or (annotation is str and not value.strip()):
            raise ValueError('invalid scalar')
    elif not isinstance(value, annotation):
        raise ValueError('wrong model type')


class Contract:
    def __post_init__(self):
        hints = get_type_hints(type(self))
        for field in fields(self):
            try:
                _check(getattr(self, field.name), hints[field.name])
            except ValueError as exc:
                raise ValueError(f'{type(self).__name__}.{field.name}: {exc}') from exc


def json_object(value):
    parsed = json.loads(value, parse_float=Decimal, parse_constant=reject_constant)
    if not isinstance(parsed, dict):
        raise ValueError('JSON object required')
    return parsed


@dataclass(frozen=True, kw_only=True)
class MarketTerms(Contract):
    """Ordered canonical outcomes; settlement is the existing assessed profile.

    None line is not applicable for moneyline. Missing rule profile is unknown.
    Event matching and rule assessment are separate upstream responsibilities.
    """
    canonical_event_id: str | None
    canonical_market_id: str | None
    league: str
    scheduled_start: datetime
    market_type: MarketType
    period: str | None
    phase: Literal['pregame', 'live', 'unknown']
    outcomes: tuple[str, str]
    line: Decimal | None
    rules_profile_json: str | None

    def __post_init__(self):
        super().__post_init__()
        if self.outcomes[0] == self.outcomes[1]:
            raise ValueError('two distinct outcomes required')
        if self.market_type == MarketType.MONEYLINE and self.line is not None:
            raise ValueError('moneyline has no line')
        if self.rules_profile_json is not None:
            validate_settlement(json_object(self.rules_profile_json))

    @property
    def complete(self):
        if (not self.canonical_event_id or not self.canonical_market_id or not self.period
                or self.phase == 'unknown' or self.market_type == MarketType.UNKNOWN
                or self.rules_profile_json is None):
            return False
        from app.settlement import compare_profiles
        p = json_object(self.rules_profile_json)
        return compare_profiles(p, p)['status'] == 'EXACT'


@dataclass(frozen=True, kw_only=True)
class ReferenceQuote(Contract):
    receipt_id: str
    provider: str
    underlying_source: str | None
    source_family: str | None
    # Complete known lineage, using Venue.value for any prediction venue.
    # None means lineage has not been assessed; () is explicitly external-only.
    copied_from: tuple[str, ...] | None
    identity_evidence: tuple[str, ...]
    native_event_id: str
    native_market_id: str
    native_outcome_ids: tuple[str, str]
    terms: MarketTerms
    # Native DECIMAL ODDS, gross return / stake, ordered like terms.outcomes.
    # Both slots always exist; missing side is null, never its complement.
    decimal_odds: tuple[Decimal | None, Decimal | None]
    source_at: datetime | None
    received_at: datetime
    source_time_semantics: Literal['snapshot', 'last_change', 'unknown']
    raw_source: str
    raw_json: str
    mode: Literal['synthetic', 'historical', 'live']
    coverage: str
    permitted_use_evidence: str | None
    limits: Quantity | None
    unknowns: tuple[str, ...]

    def __post_init__(self):
        super().__post_init__()
        json_object(self.raw_json)
        if self.native_outcome_ids[0] == self.native_outcome_ids[1]:
            raise ValueError('duplicate native outcome identity')
        for value in self.decimal_odds:
            if value is not None and value <= 1:
                raise ValueError('decimal odds must exceed one')
        if (None in self.decimal_odds or self.source_at is None or self.source_family is None
                or self.underlying_source is None or self.copied_from is None
                or self.limits is None or self.permitted_use_evidence is None
                or not self.terms.complete) and not self.unknowns:
            raise ValueError('missing reference facts require explicit unknown reasons')

    @property
    def raw_sha256(self):
        return sha256(self.raw_json.encode()).hexdigest()


@dataclass(frozen=True, kw_only=True)
class SourceDecision(Contract):
    quote: ReferenceQuote
    included: bool
    reasons: tuple[str, ...]

    def __post_init__(self):
        super().__post_init__()
        if not self.reasons:
            raise ValueError('source decision requires a reason')


def reference_decisions(quotes, *, target: Venue, terms: MarketTerms,
                        cutoff: datetime, max_receipt_age: timedelta,
                        mode: str) -> tuple[SourceDecision, ...]:
    """Contract eligibility only. No de-vig, weights, consensus or provider IO.

    Latest eligible receipt wins per family; receipt ID breaks exact-time ties.
    Record all exclusions. Source timestamps can never override receipt cutoff.
    """
    core.typed(target, Venue, 'target')
    aware(cutoff, 'cutoff')
    if max_receipt_age <= timedelta(0):
        raise ValueError('positive receipt-age bound required')
    quotes = tuple(quotes)
    core.tuple_of(quotes, ReferenceQuote, 'references')
    if len({q.receipt_id for q in quotes}) != len(quotes):
        raise ValueError('duplicate receipt IDs; replay must not alias observations')
    families, decisions = set(), []
    for q in sorted(quotes, key=lambda x: (x.received_at, x.receipt_id), reverse=True):
        reasons = []
        if q.received_at > cutoff:
            reasons.append('received_after_cutoff')
        if cutoff - q.received_at > max_receipt_age:
            reasons.append('stale_receipt')
        if q.source_at is not None and q.source_at > cutoff:
            reasons.append('source_after_cutoff_clock_uncertainty')
        if q.mode != mode:
            reasons.append('mode_mismatch')
        if q.terms != terms:
            reasons.append('incompatible_market_terms')
        if not q.terms.complete:
            reasons.append('unknown_market_terms')
        if q.source_family is None or q.underlying_source is None or not q.identity_evidence or q.copied_from is None:
            reasons.append('unverified_source_identity_or_lineage')
        if target.value in (q.provider, q.underlying_source, q.source_family, *(q.copied_from or ())):
            reasons.append('target_venue_or_known_copy')
        if q.provider == 'the_odds_api' and (q.mode != 'synthetic' or
                'synthetic:paired-snapshot-assessed' not in q.identity_evidence):
            reasons.append('unverified_reference_pairing')
        if q.provider == 'the_odds_api' and 'assessment_not_effective' in q.unknowns:
            reasons.append('reference_assessment_not_effective')
        if None in q.decimal_odds:
            reasons.append('missing_paired_outcome')
        if not reasons and q.source_family in families:
            reasons.append('duplicate_source_family')
        if not reasons:
            families.add(q.source_family)
        decisions.append(SourceDecision(quote=q, included=not reasons,
                                        reasons=tuple(reasons) or ('eligible_contract_input',)))
    return tuple(decisions)


@dataclass(frozen=True, kw_only=True)
class FairPrice(Contract):
    estimate_id: str
    target_venue: Venue
    terms: MarketTerms
    outcome_id: str
    estimated_at: datetime
    as_of: datetime
    mode: Literal['synthetic', 'historical', 'live']
    decisions: tuple[SourceDecision, ...]
    method: str
    version: str
    probability: Probability | None
    status: Status
    max_receipt_age_seconds: int
    freshness: str
    uncertainty: tuple[str, ...]

    def __post_init__(self):
        super().__post_init__()
        if self.estimated_at < self.as_of or self.as_of >= self.terms.scheduled_start:
            raise ValueError('estimate must follow cutoff; E1 covers pregame only')
        if self.outcome_id not in self.terms.outcomes:
            raise ValueError('estimate outcome not in market')
        expected = reference_decisions((d.quote for d in self.decisions), target=self.target_venue,
            terms=self.terms, cutoff=self.as_of, mode=self.mode,
            max_receipt_age=timedelta(seconds=self.max_receipt_age_seconds))
        if self.decisions != expected:
            raise ValueError('source decisions do not satisfy receipt/identity/terms contract')
        if self.probability is not None and not self.input_receipt_ids:
            raise ValueError('probability requires eligible inputs')
        if self.status == Status.UNAVAILABLE and self.probability is not None:
            raise ValueError('unavailable probability must be null')
        if self.status in (Status.AVAILABLE, Status.DEGRADED) and self.probability is None:
            raise ValueError('estimate status requires probability')
        if not self.uncertainty:
            raise ValueError('uncertainty must be described, not invented confidence')

    @property
    def input_receipt_ids(self):
        return tuple(d.quote.receipt_id for d in self.decisions if d.included)


@dataclass(frozen=True, kw_only=True)
class Economics(Contract):
    """No calculator: exact outputs from existing engines or later strategies.

    dollars_per_contract is USD / one acquired contract; total is USD over
    quantity. ROI is total / capital_denominator (not a probability gap).
    """
    quantity: Quantity | None
    dollars_per_contract: Money | None
    total_dollars: Money | None
    roi: Decimal | None
    capital_denominator: Money | None
    denominator_basis: str
    unknowns: tuple[str, ...]

    def __post_init__(self):
        super().__post_init__()
        values = (self.dollars_per_contract, self.total_dollars, self.capital_denominator)
        if any(x is not None and x.currency != 'USD' for x in values):
            raise ValueError('E1 economic results use USD; no implicit conversion')
        if self.quantity is not None and self.quantity.unit != 'contracts':
            raise ValueError('economic quantity requires verified contracts')
        if self.unknowns and any(x is not None for x in (self.dollars_per_contract, self.total_dollars, self.roi)):
            raise ValueError('unknown material economics cannot have final net values')
        if self.quantity is None and any(x is not None for x in (self.dollars_per_contract, self.total_dollars, self.roi)):
            raise ValueError('unknown size cannot have final net values')
        if self.roi is not None and (self.total_dollars is None or self.capital_denominator is None
                                    or self.capital_denominator.amount <= 0):
            raise ValueError('ROI requires total and positive stated capital denominator')
        if self.total_dollars is None and not self.unknowns:
            raise ValueError('unavailable net economics require reasons')


@dataclass(frozen=True, kw_only=True)
class Signal(Contract):
    signal_id: str
    canonical_market_id: str
    as_of: datetime
    mode: Literal['synthetic', 'historical', 'live']
    status: Status
    evidence_ids: tuple[str, ...]
    settlement_profiles_json: tuple[str, ...]
    settlement_assumptions: tuple[str, ...]
    # Immutable snapshots of existing fee-engine input contexts; never generic rates.
    fee_inputs_json: tuple[str, ...]
    economics: Economics
    limitations: tuple[str, ...]

    def __post_init__(self):
        super().__post_init__()
        if not self.evidence_ids or not self.settlement_assumptions:
            raise ValueError('signals require evidence and explicit settlement assumptions')
        for p in self.settlement_profiles_json:
            profile = json_object(p)
            validate_settlement(profile)
            from app.settlement import compare_profiles
            if compare_profiles(profile, profile)['status'] != 'EXACT' and not self.economics.unknowns:
                raise ValueError('unknown settlement outcomes require unknown economics')
        for c in self.fee_inputs_json:
            json_object(c)
        if (not self.fee_inputs_json or not self.settlement_profiles_json) and not self.economics.unknowns:
            raise ValueError('missing fees/settlement must remain unknown')
        if self.economics.unknowns and self.status not in (Status.UNAVAILABLE, Status.RESEARCH_ONLY):
            raise ValueError('unknown net economics are unavailable or research-only')


@dataclass(frozen=True, kw_only=True)
class Arbitrage(Signal):
    # Full existing detector/depth audit; no duplicated worst-case arithmetic.
    engine_audit_json: str
    result_basis: Literal['worst_case_net'] = 'worst_case_net'

    def __post_init__(self):
        super().__post_init__()
        json_object(self.engine_audit_json)


@dataclass(frozen=True, kw_only=True)
class Mispricing(Signal):
    fair_price_id: str
    target_venue: Venue
    probability_gap: Decimal | None
    result_basis: Literal['expected_net'] = 'expected_net'

    def __post_init__(self):
        super().__post_init__()
        if self.probability_gap is not None and not -1 <= self.probability_gap <= 1:
            raise ValueError('probability gap is a signed fraction, not percent or USD')


@dataclass(frozen=True, kw_only=True)
class LeadLag(Signal):
    target_venue: Venue
    movement_receipt_ids: tuple[str, ...]
    window_start: datetime
    window_end: datetime
    lag_seconds: Decimal | None
    clock_cadence_uncertainty: str
    trade_value_model: str | None
    result_basis: Literal['observed_movement'] = 'observed_movement'

    def __post_init__(self):
        super().__post_init__()
        if not self.window_start <= self.window_end <= self.as_of:
            raise ValueError('movement window must precede signal cutoff')
        if self.lag_seconds is not None and self.lag_seconds < 0:
            raise ValueError('lag cannot be negative')
        if self.trade_value_model is None and self.economics.total_dollars is not None:
            raise ValueError('movement alone has no modeled net trade value')


@dataclass(frozen=True, kw_only=True)
class MakerValue(Signal):
    fair_price_id: str
    target_venue: Venue
    limit_price: Probability
    fill_probability: Probability | None
    fill_assumptions: tuple[str, ...]
    adverse_selection: str
    inventory_exposure: str
    result_basis: Literal['net_conditional_on_fill'] = 'net_conditional_on_fill'

    def __post_init__(self):
        super().__post_init__()
        if not self.fill_assumptions:
            raise ValueError('maker requires fill assumptions')


# Small allowlisted tagged codec: preserves decimal scale, raw text and types.
# Existing capture/detector formats are not modified or silently upgraded.
_MODELS = {c.__name__: c for c in (
    MarketTerms, ReferenceQuote, SourceDecision, FairPrice, Economics,
    Arbitrage, Mispricing, LeadLag, MakerValue,
    core.Probability, core.Quantity, core.Money, core.NativeRef, core.RawPayload,
    core.BookLevel, core.Ladder, core.OutcomeBook, core.OrderBook)}
_ENUMS = {c.__name__: c for c in (
    Status, Venue, MarketType, core.EvidenceKind, core.MarketState, core.Depth,
    core.BookSync, core.ReceiptFreshness, core.SourceTimeProgress)}


def _wire(value):
    if isinstance(value, Enum):
        return {'enum': type(value).__name__, 'value': value.value}
    if is_dataclass(value) and type(value).__name__ in _MODELS:
        return {'type': type(value).__name__, 'fields': {f.name: _wire(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, Decimal):
        decimal_value(value, 'wire decimal')
        return {'decimal': str(value)}
    if isinstance(value, datetime):
        aware(value, 'wire timestamp')
        return {'datetime': value.isoformat()}
    if isinstance(value, tuple):
        return {'tuple': [_wire(x) for x in value]}
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError('unsupported E1 wire value')


def _unwire(value):
    if not isinstance(value, dict):
        if value is None or type(value) in (str, int, bool):
            return value
        raise ValueError('unsupported E1 scalar')
    if set(value) == {'decimal'}:
        if not isinstance(value['decimal'], str):
            raise ValueError('decimal wire values must be strings')
        return parse_decimal(value['decimal'])
    if set(value) == {'datetime'}:
        return datetime.fromisoformat(value['datetime'])
    if set(value) == {'tuple'}:
        return tuple(_unwire(x) for x in value['tuple'])
    if set(value) == {'enum', 'value'} and value['enum'] in _ENUMS:
        return _ENUMS[value['enum']](value['value'])
    if set(value) == {'type', 'fields'} and value['type'] in _MODELS:
        return _MODELS[value['type']](**{k: _unwire(v) for k, v in value['fields'].items()})
    raise ValueError('unsupported E1 wire object')


def dumps(value):
    from app.fees.engine import digest
    payload = _wire(value)
    return json.dumps({'format': 'edge-contracts-1', 'payload': payload,
                       'sha256': digest(payload)}, indent=2, sort_keys=True)


def loads(value):
    from app.fees.engine import digest
    envelope = json.loads(value, parse_constant=reject_constant)
    if envelope['format'] != 'edge-contracts-1' or digest(envelope['payload']) != envelope['sha256']:
        raise ValueError('E1 envelope identity/version mismatch')
    return _unwire(envelope['payload'])
