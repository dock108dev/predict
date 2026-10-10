"""Evidenced native-side transformations; labels never supply mapping authority."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any

from .domain import (
    CanonicalSelection, EqualityDescriptor, EventReference, ExactNumber,
    NativeProvenance, Price, Scope, ScorePredicate, UnknownValue,
)
from .event_links import EventLinks

VERSION = "comparison-outcome-adapters-1"
MAX_FACTS = 512
_COMPLEMENT = {"gt": "le", "ge": "lt", "lt": "ge", "le": "gt", "eq": "ne", "ne": "eq"}
_REVERSE = {"gt": "lt", "ge": "le", "lt": "gt", "le": "ge", "eq": "eq", "ne": "ne"}
_FIELDS = {"schema_version", "event", "family", "scope", "native", "definition", "definition_sha256", "equality", "price"}
_DEFINITION = {"event_id", "market_id", "instrument_id", "side_id", "native_participant_id",
               "participant_id", "domain", "operator", "threshold", "signed_line", "position",
               "assertion", "complement_evidence", "review_class"}


def definition_digest(definition: dict) -> str:
    return sha256(json.dumps(definition, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def adapt(fact: dict, *, links: EventLinks, at: datetime) -> CanonicalSelection:
    """Map a reviewed original-side definition, after its D02 occurrence gate.

    A caller supplies structured participant/score facts and original source
    evidence. LONG/SHORT, title text and prices are never used to infer a team.
    Payout applicability remains a separate D04 binding.
    """
    if not isinstance(fact, dict) or set(fact) != _FIELDS or fact["schema_version"] != VERSION:
        raise ValueError("Exact versioned native outcome fact required")
    if not isinstance(links, EventLinks) or not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("D02 links and exact aware evaluation instant required")
    event = EventReference.from_dict(fact["event"])
    scope = Scope.from_dict(fact["scope"])
    native = NativeProvenance.from_dict(fact["native"])
    edge, reason = links.resolve(native.venue, native.event_id, event.league, event.home_id, event.away_id, at)
    if edge is None or edge.occurrence_id != event.occurrence_id:
        raise ValueError(reason or "Native side occurrence conflict")
    d = fact["definition"]
    if not isinstance(d, dict) or set(d) != _DEFINITION or fact["definition_sha256"] != definition_digest(d):
        raise ValueError("Reviewed exact native definition changed")
    for name in ("event_id", "market_id", "instrument_id", "side_id"):
        if d[name] != getattr(native, name):
            raise ValueError("Native side definition association conflict: " + name)
    if d["review_class"] not in {"structured_receipt", "manual_review", "authored"}:
        raise ValueError("Explicit native mapping review class required")
    if not isinstance(d["native_participant_id"], str) or not d["native_participant_id"]:
        raise ValueError("Structured native participant identity required")
    participant = d["participant_id"]
    if participant not in {event.home_id, event.away_id, "combined", "tie"}:
        raise ValueError("Unresolved native participant")
    position = d["position"]
    assertion = d["assertion"]
    if native.venue == "kalshi":
        if position not in {"YES", "NO"} or native.side_id != position.lower():
            raise ValueError("Exact Kalshi YES/NO side definition required")
        if assertion != ("complement" if position == "NO" else "predicate"):
            raise ValueError("Kalshi side assertion conflict")
    elif native.venue == "polymarket_us":
        if position not in {"LONG", "SHORT"} or assertion != "predicate":
            raise ValueError("US side requires its own structured participant predicate")
    elif position != "SPORTSBOOK" or assertion != "predicate":
        raise ValueError("Sportsbook direct-side predicate required")
    operator = d["operator"]
    if operator not in _COMPLEMENT:
        raise ValueError("Unsupported source score operator")
    if assertion == "complement":
        if not isinstance(d["complement_evidence"], str) or not d["complement_evidence"]:
            raise ValueError("Native complement meaning requires explicit evidence")
        operator = _COMPLEMENT[operator]
    elif d["complement_evidence"] is not None:
        raise ValueError("Direct predicate cannot inherit complement evidence")
    threshold = ExactNumber.parse(d["threshold"])
    domain = d["domain"]
    if domain == "participant_margin":
        if participant not in {event.home_id, event.away_id}:
            raise ValueError("Margin requires an exact event participant")
        domain = "home_margin"
        if participant == event.away_id:
            operator = _REVERSE[operator]
            n = -threshold.value
            threshold = ExactNumber(str(n.numerator) if n.denominator == 1 else str(n))
    elif domain not in {"home_margin", "combined_score", "team_score"}:
        raise ValueError("Unsupported source score domain")
    predicate = ScorePredicate(domain, operator, threshold, participant if domain == "team_score" else None)
    result = CanonicalSelection(
        event=event, family=fact["family"], scope=scope, participant_id=participant,
        signed_line=ExactNumber.parse(d["signed_line"]) if d["signed_line"] is not None else None,
        predicate=predicate, equality=EqualityDescriptor.from_dict(fact["equality"]), native=native,
        payout=None, price=Price.from_dict(fact["price"]),
        payout_unknown=UnknownValue("Exact payout profile not bound", ("Applicable instrument/rule profile from D04",)),
    )
    result.semantic_key()  # Unknown overtime/completion cannot silently join.
    return result


@dataclass(frozen=True)
class AdapterBatch:
    selections: tuple[CanonicalSelection, ...]
    rejected: tuple[dict, ...]
    duplicates: int


def adapt_many(facts: list[dict], *, links: EventLinks, at: datetime) -> AdapterBatch:
    """One exact native quote candidate; conflicting duplicate definitions retire it."""
    if not isinstance(facts, list) or len(facts) > MAX_FACTS:
        raise ValueError("Bounded native outcome fact list required")
    admitted = {}
    originals = {}
    conflicted = set()
    rejected = []
    duplicates = 0
    for index, fact in enumerate(facts):
        try:
            selection = adapt(fact, links=links, at=at)
        except (ValueError, TypeError, KeyError) as error:
            rejected.append(dict(index=index, reason=str(error)))
            continue
        key = selection.native.key
        if key in conflicted:
            rejected.append(dict(index=index, reason="Conflicting native instrument definition"))
        elif key in admitted:
            if originals[key] == fact:
                duplicates += 1
            else:
                admitted.pop(key)
                conflicted.add(key)
                rejected.append(dict(index=index, reason="Conflicting native instrument definition"))
        else:
            admitted[key] = selection
            originals[key] = fact
    return AdapterBatch(tuple(admitted.values()), tuple(rejected), duplicates)


def selection_record(selection: CanonicalSelection) -> dict[str, Any]:
    """Public data-input seam for current transport; does not compute metrics."""
    if not isinstance(selection, CanonicalSelection):
        raise ValueError("Typed canonical selection required")
    return dict(adapter_version=VERSION, comparison_input=selection.to_dict(),
                settlement_status="unbound" if selection.payout is None else "profile_attached")
