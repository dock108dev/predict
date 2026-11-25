"""Reconcile provider returns with frozen paper inputs without changing the replay."""

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from hashlib import sha256
import json
import logging
import sqlite3

from psycopg.types.json import Jsonb

from app.collection.sgo_capabilities import CORE_ODD_IDS, MARKET_TYPES, supported_odd
from app.collection.sportsgameodds_current_rows import display_venue, source_bookmaker
from app.comparison import current_pregame as valuation
from app.comparison.cashflows import exact_wire
from app.comparison.pregame_reference import target
from app.comparison.reference_scope import REQUEST_BOOKS
from app.comparison.sgo_reference import BEST_BOOKS, OPPOSITE
from app.storage.store import encoded, hashed, stamp


VERSION = "sgo-checkpoint-market-census-2"
BASELINE_MINIMUM = "1/25"
REFERENCE_EXCLUSIONS = {"reference_exact_pair_unavailable", "reference_two_trusted_books_required"}
CORE_OUTCOMES = {odd: (MARKET_TYPES[odd.split("-")[-2]], odd.split("-")[-1]) for odd in CORE_ODD_IDS}
EVENT_PAGINATION = "https://sportsgameodds.com/docs/guides/data-batches"
EVENT_ODDS_STATUS = "https://sportsgameodds.com/docs/endpoints/getEvents"
LOG = logging.getLogger(__name__)


def _members(value):
    return sorted(set(value.split(",")) - {""}) if isinstance(value, str) else []


def retrieval(scope, event_ids, next_cursor, receipt_sha256, *, cursor_known=True):
    """The provider paginates event objects. Venue-wide completeness stays unknown."""
    requested = _members(scope.get("eventIDs") or scope.get("eventID"))
    ids = sorted(event_ids)
    has_next = bool(next_cursor) if cursor_known else None
    missing = sorted(set(requested) - set(ids))
    valid_target = bool(ids and requested and not (set(ids) - set(requested)))
    state = "complete_requested_event_response" if valid_target else "unknown_completeness"
    traversal = "unknown" if has_next is None else "cursor_unfollowed" if has_next else "cursor_closed"
    if missing and has_next:
        traversal = "partial_retrieval"
    if valid_target and not missing:
        request_state = "all_requested_events_returned"
    elif missing and has_next:
        request_state = "partial_retrieval"
    elif missing and has_next is False:
        request_state = "requested_events_unreturned"
    else:
        request_state = "unknown_completeness"
    return dict(state=state, request_state=request_state, traversal=traversal, venue_market_state="unknown_completeness",
        pagination="events", pagination_documentation=EVENT_PAGINATION, requested_event_ids=requested,
        events_unreturned=missing, pages=[dict(receipt_sha256=receipt_sha256, returned_event_ids=ids,
            input_cursor_present=bool(scope.get("cursor")), next_cursor_present=has_next,
            next_cursor_sha256=sha256(next_cursor.encode()).hexdigest() if isinstance(next_cursor, str) else None)])


def summarize_coverage(coverage, *, derived=None):
    """Read the small saved coverage object without expanding checkpoint payloads."""
    if derived is not None:
        return dict(derived["summary"], version=derived["version"], evidence_revision=derived["evidence_revision"],
                    basis=derived["retrieval"]["basis"], offer_accounting_minimum_ev=derived["minimum_ev"])
    if not coverage:
        return None
    requested = coverage.get("requested") or {}
    books, odds = requested.get("bookmakers") or [], requested.get("odd_ids") or []
    proof = coverage.get("retrieval") or {}
    expected, returned = len(books) * len(odds), coverage.get("returned_cells")
    return dict(basis="frozen_normalized_checkpoint", retrieval_state=proof.get("state", "unknown_completeness"),
                request_state=proof.get("request_state", "unknown_completeness"), traversal=proof.get("traversal", "unknown"),
                venue_market_state="unknown_completeness", normalized_rows=(coverage.get("received") or {}).get("quotes"),
                requested_cells=expected if books and odds else None, returned_cells=returned,
                unreturned_cells=expected - returned if returned is not None and books and odds else None,
                alternate_lines_requested=requested.get("include_alt_lines"))


def _line(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
        if number.is_finite() and abs(number) <= 1_000_000 and abs(number.as_tuple().exponent) <= 256:
            return exact_wire(Fraction(number))
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        return None
    return None


def _key(book, odd, line):
    return book, odd, _line(line)


def _normalized_state(quote):
    if quote.get("available") is True:
        return "available"
    reason = quote.get("unavailable_reason")
    if reason == "conflicting observations at exact line":
        return "conflicting"
    if quote.get("provider_available") is False or reason in ("provider unavailable", "event or market ended"):
        return "explicitly_unavailable"
    return "rejected"


def _scope_fields(scope, *, cursor_is_hash=False):
    result = {key: scope[key] for key in ("eventIDs", "eventID", "bookmakerID", "oddID", "limit",
        "includeAltLines", "includeOpposingOdds") if key in scope}
    if isinstance(scope.get("cursor"), str):
        cursor = scope["cursor"]
        result["cursor_sha256"] = cursor if cursor_is_hash else sha256(cursor.encode()).hexdigest()
    return result


def _scalar(value):
    return str(value)[:256] if isinstance(value, (str, int, Decimal)) and not isinstance(value, bool) else None


def _fields(value):
    return value if isinstance(value, dict) else {}


def _returned_rows(raw_event, normalized):
    """Trace source positions, including duplicate or conflicting alternate entries."""
    result = []
    for odd_id, odd in _fields(raw_event.get("odds")).items():
        odd = _fields(odd)
        family, side = MARKET_TYPES.get(_scalar(odd.get("betTypeID"))), _scalar(odd.get("sideID"))
        line_field = {"spread": "spread", "total": "overUnder"}.get(family)
        supported = supported_odd(odd)
        for book, main in _fields(odd.get("byBookmaker")).items():
            alternatives = _fields(main).get("altLines")
            entries = [main, *(alternatives if isinstance(alternatives, list) else [])]
            for index, entry in enumerate(entries):
                entry = _fields(entry)
                line = entry.get(line_field)
                fact = normalized.get(_key(book, odd_id, line))
                state = _normalized_state(fact) if fact else "unsupported" if not supported else "not_normalized"
                result.append(dict(bookmaker_id=book, venue=display_venue(book), odd_id=odd_id,
                    period=_scalar(odd.get("periodID")), family=family, outcome=side, line=_line(line),
                    original_line=_scalar(line), source_row="main" if not index else f"altLines/{index-1}",
                    state=state, price_american=_scalar(entry.get("odds")), source_at=_scalar(entry.get("lastUpdatedAt")),
                    provider_available=entry.get("available") if isinstance(entry.get("available"), bool) else None,
                    opposing_odd_id=_scalar(odd.get("opposingOddID"))))
    return result


def _requests(scope, rows, *, verified_target, no_provider_odds):
    requested_books, requested_odds = _members(scope.get("bookmakerID")), _members(scope.get("oddID"))
    cells = defaultdict(list)
    for row in rows:
        cells[row["bookmaker_id"], row["odd_id"]].append(row)
    result = []
    for book in sorted(set(requested_books) | set(REQUEST_BOOKS)):
        for odd in sorted(set(requested_odds) | CORE_ODD_IDS):
            values = cells.get((book, odd), [])
            states = Counter(row["state"] for row in values)
            family, outcome = CORE_OUTCOMES.get(odd, (None, None))
            requested = book in requested_books and odd in requested_odds
            if not requested:
                disposition = "returned_outside_declared_scope" if values else "not_requested"
            elif values:
                disposition = "returned"
            elif odd not in CORE_OUTCOMES:
                disposition = "unsupported"
            elif no_provider_odds:
                disposition = "no_provider_odds_observed"
            else:
                disposition = "requested_but_unreturned" if verified_target else "return_unverified"
            result.append(dict(bookmaker_id=book, venue=display_venue(book), odd_id=odd, family=family,
                outcome=outcome, requested=requested, state=disposition, rows=len(values), row_states=dict(states)))
    return result


def _event_odds(event, verified_target):
    status = _fields(event.get("status"))
    present, available = status.get("oddsPresent"), status.get("oddsAvailable")
    no_odds = verified_target and present is False and available is not True and not event.get("odds")
    return dict(state="no_provider_odds_observed" if no_odds else "unknown_if_no_rows",
                odds_present=present if isinstance(present, bool) else None,
                odds_available=available if isinstance(available, bool) else None,
                scope="this_provider_event_response", documentation=EVENT_ODDS_STATUS)


class ReferenceCensus:
    """Record each trusted book's evidence at the exact line selected by the screen."""

    def __init__(self, snapshot, rows, raw_rows, *, raw_verified, at):
        self.at = stamp(at)
        self.start = stamp(snapshot["event"]["scheduled_start"])
        self.event_id = snapshot["source_event"]["event_id"]
        self.inputs = valuation.ReferenceInputs({self.event_id: snapshot.get("references", ())})
        self.exact, self.families, self.raw_exact = defaultdict(list), defaultdict(set), defaultdict(set)
        self.scope = snapshot.get("request_scope") or {}
        self.books = _members(self.scope.get("bookmakerID"))
        self.odds = _members(self.scope.get("oddID"))
        self.raw_verified = raw_verified
        self.cache = {}
        for row in rows:
            if row["bookmaker_id"] not in BEST_BOOKS or row.get("partition") == "three_way":
                continue
            try:
                line = exact_wire(target(row["family"], row["outcome"], row["line"]))
            except (ValueError, TypeError, KeyError, ArithmeticError):
                continue
            self.exact[row["bookmaker_id"], row["family"], line].append(row)
            self.families[row["bookmaker_id"], row["family"]].add(row["outcome"])
        for row in raw_rows:
            if row["bookmaker_id"] not in BEST_BOOKS or row["state"] != "not_normalized":
                continue
            try:
                line = exact_wire(target(row["family"], row["outcome"], row["line"]))
            except (ValueError, TypeError, KeyError, ArithmeticError):
                continue
            self.raw_exact[row["bookmaker_id"], row["family"], line].add(row["outcome"])

    def _book(self, book, family, line, side, odds, eligible):
        rows = self.exact.get((book, family, line), [])
        present = {row["outcome"] for row in rows}
        required = {side, OPPOSITE[side]}
        missing = sorted(required - present)
        omitted = bool(self.books and book not in self.books or self.odds and
                       self.scope.get("includeOpposingOdds") is not True and any(odd not in self.odds for odd in odds))
        if book in eligible:
            reason = "qualifying_pair"
        elif self.raw_exact.get((book, family, line), set()) - present:
            reason = "normalization_or_projection_gap"
        elif missing and omitted:
            reason = "request_scope_omission"
        elif missing and len(missing) == 1:
            reason = "one_exact_side_unreturned"
        elif missing and required <= self.families.get((book, family), set()):
            reason = "exact_line_unreturned"
        elif missing:
            reason = "trusted_market_unreturned" if self.raw_verified else "unresolved_original_return"
        elif any(row["state"] == "explicitly_unavailable" for row in rows):
            reason = "explicit_withdrawal_or_unavailability"
        elif len(rows) != 2 or any(row["state"] == "conflicting" for row in rows):
            reason = "conflicting_source_rows"
        elif any(row["state"] == "rejected" for row in rows):
            reason = "invalid_or_missing_price_or_clock"
        elif any(not stamp(row["source_at"]) <= stamp(row["received_at"]) <= self.at < self.start for row in rows):
            reason = "reference_clock_conflict"
        elif rows[0]["opposing_odd_id"] != rows[1]["odd_id"] or rows[1]["opposing_odd_id"] != rows[0]["odd_id"]:
            reason = "opposing_identity_conflict"
        else:
            reason = "unresolved_reference_guard"
        return dict(bookmaker_id=book, reason=reason, missing_outcomes=missing,
                    states=sorted({row["state"] for row in rows}),
                    family_returned_outcomes=sorted(self.families.get((book, family), ())),
                    rows=[row["row_id"] for row in rows])

    def explain(self, record, original_reason):
        family, side, line = valuation.reference_key(record)
        source = record["quote"]["source"]
        opposing = (record.get("comparison_source_metadata") or {}).get("provider_opposing_odd_id")
        odds = [odd for odd in (source.get("native_outcome_id"), opposing) if odd]
        key = family, side, line, tuple(odds), original_reason
        if key not in self.cache:
            eligible = {row["book"] for row in valuation.reference_candidates(
                self.inputs, family=family, side=side, line=line, start=self.start, at=self.at)}
            line = exact_wire(line)
            details = [self._book(book, family, line, side, odds, eligible) for book in BEST_BOOKS]
            reasons = sorted({row["reason"] for row in details if row["reason"] != "qualifying_pair"})
            expected = 0 if original_reason == "reference_exact_pair_unavailable" else 1
            self.cache[key] = dict(reason=original_reason, normalized_reference_line=line,
                required_trusted_books=valuation.MIN_TRUSTED_BOOKS, qualifying_trusted_books=len(eligible),
                frozen_disposition_matches=len(eligible) == expected, causes=reasons, books=details,
                assessment="method_ineligible" if self.raw_verified and len(eligible) == expected
                    and "normalization_or_projection_gap" not in reasons else "reference_evidence_review")
        return self.cache[key]


def _original(snapshot):
    from app.collection import original_receipts

    digest = snapshot.get("receipt_sha256")
    value = original_receipts.lookup(digest)
    if value["state"] != "retained":
        return dict(state=value["state"], reason=value["reason"], receipt_sha256=digest), None
    batch = (snapshot.get("acquisition") or {}).get("batch") or {}
    scope = _scope_fields(batch.get("request_scope") or snapshot.get("request_scope") or {})
    received_at = stamp(snapshot["times"]["received_at"])
    retained = [row for row in value["captures"] if row["state"] == "retained"]
    matching = [row for row in retained if stamp(row["received_at"]) == received_at]
    selected = next((row for row in matching if _scope_fields(row["request_scope"], cursor_is_hash=True) == scope),
                    (matching or retained)[-1])
    try:
        metadata, body = original_receipts.read(selected["id"])
        payload = json.loads(body, parse_float=Decimal)
    except (KeyError, OSError, ValueError, EOFError, sqlite3.Error):
        return dict(state="unavailable", reason="original_receipt_read_failed", receipt_sha256=digest), None
    if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), list):
        return dict(state="unavailable", reason="invalid_original_response_shape", receipt_sha256=digest), None
    return dict(state="retained", id=metadata["id"], receipt_sha256=digest, received_at=metadata["received_at"],
        raw_bytes=metadata["raw_bytes"], parser_version=metadata["parser_version"],
        request_clock_matches=stamp(metadata["received_at"]) == received_at,
        request_scope_matches=_scope_fields(metadata["request_scope"], cursor_is_hash=True) == scope), payload


def _normalized_rows(snapshot):
    result = []
    event_id = snapshot.get("source_event", {}).get("event_id")
    for quote in snapshot.get("raw_quotes", ()):
        if quote.get("event_id") != event_id:
            continue
        book, odd, line = _key(quote["venue"], quote["odd_id"], quote["line"])
        result.append(dict(row_id=hashed([snapshot["receipt_sha256"], event_id, book, odd, line]),
            venue=display_venue(book), bookmaker_id=book, odd_id=odd, line=line,
            family=quote["market"], period=quote["period"], outcome=quote["side"], partition=quote.get("partition"),
            opposing_odd_id=quote.get("opposing_odd_id"), alternate=quote.get("alternate"),
            price_american=quote.get("price_american"), state=_normalized_state(quote),
            provider_available=quote.get("provider_available"), reason=quote.get("unavailable_reason"),
            source_at=quote.get("source_at"), received_at=quote["received_at"]))
    return result


def _offers(snapshot, by_source, reference, *, at, game_id, minimum):
    from .ev_movement import exact_bet_identity, offer_measurements, public_offer_reason

    result = []
    for index, offer in enumerate(snapshot.get("offers", ())):
        record = offer["record"]
        quote = record["quote"]
        native = quote["source"]
        provider_book = source_bookmaker(record)
        odd, line = native.get("native_outcome_id"), native.get("native_line")
        exact = by_source.get(_key(provider_book, odd, line)) or {}
        try:
            identity = exact_bet_identity(record, event_identity=game_id)
            screen = offer_measurements(offer, offer_index=index, captured_at=at)["screen"]
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            identity = {}
            screen = dict(ev=None, probability=None, reason=public_offer_reason(str(exc)) if isinstance(exc, ValueError) else "sizing_inputs_incomplete")
        ev, reason = screen["ev"], public_offer_reason(screen.get("reason"))
        if ev is None:
            disposition = reason or "ev_unavailable"
        else:
            disposition = "below_minimum_ev" if Fraction(ev) < minimum or Fraction(ev) <= 0 else "screen_passed"
        reference_gap = reference.explain(record, disposition) if reference and disposition in REFERENCE_EXCLUSIONS else None
        result.append(dict(offer_index=index, row_id=exact.get("row_id"), exact_bet_id=identity.get("id"),
            bookmaker_id=provider_book, odd_id=odd, venue=quote["venue"], family=record["market_identity"]["family"],
            period=record["market_identity"]["period"], outcome=identity.get("outcome") or exact.get("outcome"),
            line=_line(line), price_american=(quote.get("original") or {}).get("value"),
            price_state=exact.get("state", quote.get("state")), price_reason=exact.get("reason"),
            source_at=quote.get("times", {}).get("source_at"), received_at=quote.get("times", {}).get("received_at"),
            source_market_key=native.get("native_market_id"), venue_contract_id=native.get("venue_contract_id"), evaluated=ev is not None,
            screen_ev=ev, fair_probability=screen.get("probability"), disposition=disposition, reference_gap=reference_gap))
    return result


def offer_rows(checkpoint, *, game_id, minimum, at):
    """Export the offered prices and screens from one frozen paper input."""
    snapshot = checkpoint["snapshot"]
    normalized = {(row["bookmaker_id"], row["odd_id"], row["line"]): row for row in _normalized_rows(snapshot)}
    return _offers(snapshot, normalized, None, at=at, game_id=game_id, minimum=Fraction(minimum))


def from_checkpoint(checkpoint, checkpoint_id, *, include_rows=True, minimum=BASELINE_MINIMUM):
    """Build an auditable view of one immutable checkpoint and its original response."""
    snapshot = checkpoint["snapshot"]
    event_id = snapshot.get("source_event", {}).get("event_id")
    digest = snapshot.get("receipt_sha256")
    scope = snapshot.get("request_scope") or {}
    normalized = _normalized_rows(snapshot)
    by_source = {(row["bookmaker_id"], row["odd_id"], row["line"]): row for row in normalized}
    facts = {_key(q["venue"], q["odd_id"], q["line"]): q for q in snapshot.get("raw_quotes", ()) if q.get("event_id") == event_id}
    original, payload = _original(snapshot)
    raw_rows, market_groups, event = [], [], {}
    if payload is not None:
        events = {row["eventID"]: row for row in payload["data"] if isinstance(row, dict) and isinstance(row.get("eventID"), str)}
        batch_scope = ((snapshot.get("acquisition") or {}).get("batch") or {}).get("request_scope")
        response = retrieval(scope, [event_id] if batch_scope and event_id in events else
                             [] if batch_scope else events, payload.get("nextCursor"), digest)
        if batch_scope:
            response["physical_request"] = retrieval(batch_scope, events, payload.get("nextCursor"), digest)
        if event := events.get(event_id, {}):
            raw_rows = _returned_rows(event, facts)
            market_groups = [dict(odd_id=odd, supported=supported_odd(body),
                bookmaker_ids=sorted(_fields(_fields(body).get("byBookmaker")))) for odd, body in _fields(event.get("odds")).items()]
        else:
            response["state"] = "unknown_completeness"
        response["basis"] = "verified_original_response"
    else:
        coverage = snapshot.get("coverage") or {}
        response = coverage.get("retrieval")
        if response is None:
            has_next = (snapshot.get("acquisition") or {}).get("next_cursor_present")
            verified = isinstance(has_next, bool)
            response = retrieval(scope, [event_id] if event_id and verified else [], has_next, digest, cursor_known=verified)
        response = dict(response, basis="frozen_normalized_checkpoint")
    verified_target = (bool(event) and original.get("request_scope_matches") is not False
                       and original.get("request_clock_matches") is not False
                       and response["request_state"] == "all_requested_events_returned")
    event_odds = _event_odds(event, verified_target)
    if raw_rows:
        event_odds["state"] = "provider_rows_observed"
    cells = _requests(scope, raw_rows if payload is not None else normalized, verified_target=verified_target,
                      no_provider_odds=event_odds["state"] == "no_provider_odds_observed")
    clocks = snapshot.get("times") or {}
    at = clocks.get("inputs_cutoff") or clocks.get("known_at") or checkpoint.get("known_at")
    reference = ReferenceCensus(snapshot, normalized, raw_rows, raw_verified=verified_target, at=at)
    minimum = Fraction(minimum)
    offers = _offers(snapshot, by_source, reference, at=at, game_id=checkpoint.get("game_id"), minimum=minimum)
    dispositions = Counter(offer["disposition"] for offer in offers)
    accounting = dict(unavailable=dispositions["price_withdrawn"],
        reference_ineligible=sum(dispositions[key] for key in REFERENCE_EXCLUSIONS),
        below_minimum=dispositions["below_minimum_ev"], screen_passed=dispositions["screen_passed"])
    accounting["other"] = len(offers) - sum(accounting.values())
    gaps = [offer["reference_gap"] for offer in offers if offer["reference_gap"]]
    causes = Counter(cause for gap in gaps for cause in gap["causes"])
    book_causes = Counter(book["reason"] for gap in gaps for book in gap["books"])
    states = Counter(row["state"] for row in normalized)
    raw_states = Counter(row["state"] for row in raw_rows)
    request_states = Counter(cell["state"] for cell in cells)
    fallback = (summarize_coverage(snapshot.get("coverage")) or {}) if payload is None else {}
    unreturned = request_states["requested_but_unreturned"] if verified_target else fallback.get("unreturned_cells")
    returned = request_states["returned"] if verified_target else fallback.get("returned_cells")
    result = dict(version=VERSION, checkpoint_id=checkpoint_id, event_id=event_id,
        source="sportsgameodds", as_of=clocks.get("received_at"), reference_input_cutoff=at, minimum_ev=exact_wire(minimum),
        original_response=original, retrieval=response, event_odds=event_odds, requested_scope=_scope_fields(scope),
        summary=dict(retrieval_state=response["state"], traversal=response["traversal"],
            request_state=response["request_state"],
            venue_market_state=response["venue_market_state"], requested_cells=sum(cell["requested"] for cell in cells),
            returned_cells=returned, unreturned_cells=unreturned,
            no_provider_odds_cells=request_states["no_provider_odds_observed"] if verified_target else None,
            counts_basis="verified_original_response" if verified_target else fallback.get("basis"),
            alternate_lines_requested=scope.get("includeAltLines"),
            request_states=dict(request_states), normalized_rows=len(normalized),
            normalized_states=dict(states), original_rows=len(raw_rows) if payload is not None else None,
            original_states=dict(raw_states), observed_offers=len(offers), evaluated_offers=sum(o["evaluated"] for o in offers),
            screen_passed_offers=dispositions["screen_passed"], offer_dispositions=dict(dispositions), offer_accounting=accounting,
            reference_exclusions=sum(dispositions[key] for key in REFERENCE_EXCLUSIONS), reference_causes=dict(causes),
            reference_accounting=dict(exact_pair_missing=dispositions["reference_exact_pair_unavailable"],
                insufficient_trusted_books=dispositions["reference_two_trusted_books_required"],
                method_ineligible=sum(gap["assessment"] == "method_ineligible" for gap in gaps)),
            reference_book_causes=dict(book_causes), reference_disposition_mismatches=sum(not g["frozen_disposition_matches"] for g in gaps)),
        provider_requests=0, orders_submitted=0)
    if include_rows:
        stored_coverage = snapshot.get("coverage") or {}
        result.update(request_cells=cells, market_groups=market_groups, original_rows=raw_rows, normalized_rows=normalized,
            projection_rejections=stored_coverage.get("rejected_projection", []), offers=offers)
    result["evidence_revision"] = hashed([VERSION, checkpoint_id, original, response, event_odds, result["minimum_ev"], result["summary"]])
    return result


def for_checkpoint(db, checkpoint_id, *, include_rows=True, minimum=BASELINE_MINIMUM):
    """Read one selected checkpoint without acquisition or mutations."""
    from . import experiment

    index = experiment._closure(db, [checkpoint_id])
    row = index[checkpoint_id]
    if row["kind"] != "checkpoint":
        raise ValueError("market_census_checkpoint_required")
    checkpoint = experiment._value(row, index)
    return from_checkpoint(dict(checkpoint, game_id=row["game_id"]), checkpoint_id,
                           include_rows=include_rows, minimum=minimum)


def read_summaries(db, checkpoint_ids):
    ids = sorted({identity for identity in checkpoint_ids if identity})
    if not ids:
        return {}
    return {row["checkpoint_id"]: row["payload"] for row in db.execute("""SELECT checkpoint_id,payload
        FROM public.research_market_census WHERE format_version=%s AND checkpoint_id=ANY(%s)""", (VERSION, ids))}


def campaign_checkpoints(db, now):
    """Prioritize already-published days of campaigns that are still running."""
    from .paper_campaigns import EASTERN, index

    today = now.astimezone(EASTERN).date()
    active = [campaign['id'] for campaign in index(db, active_only=True)
              if campaign['end_date'] >= str(today)]
    if not active:
        return []
    rows = db.execute("""SELECT game->>'checkpoint_id' AS id, MIN(day.game_date) AS first_day
        FROM public.paper_campaign_day day
        JOIN public.research_workspace_run run ON run.id=day.run_id
        CROSS JOIN LATERAL jsonb_array_elements(run.payload#>'{report,games}') AS game
        WHERE day.campaign_id=ANY(%s) AND game->>'checkpoint_id' IS NOT NULL
        GROUP BY game->>'checkpoint_id' ORDER BY first_day,id""", (active,))
    return [row["id"] for row in rows]


def apply_summary(census, derived):
    if derived is None:
        return census
    summary = summarize_coverage(None, derived=derived)
    if census["minimum_ev"] != derived["minimum_ev"]:
        for field in ("screen_passed_offers", "offer_dispositions", "offer_accounting"):
            summary[field] = census["summary"][field]
        summary["offer_accounting_minimum_ev"] = census["minimum_ev"]
    return dict(census, summary=summary, retrieval=derived["retrieval"], event_odds=derived["event_odds"],
                published_evidence_revision=derived["evidence_revision"])


def _defer(db, checkpoint_id, delay, reason):
    db.execute("""INSERT INTO public.research_market_census_retry(format_version,checkpoint_id,retry_after,reason)
        VALUES (%s,%s,clock_timestamp()+%s,%s) ON CONFLICT (format_version,checkpoint_id)
        DO UPDATE SET retry_after=EXCLUDED.retry_after,reason=EXCLUDED.reason""",
        (VERSION, checkpoint_id, delay, reason))


def tick(db, priority=()):
    """Publish one bounded, retained-original summary without issuing any collection requests."""
    from app.storage import paper_result_queue as queue

    if queue._late_capture_due(db, queue.utc()):
        return None
    row = db.execute("""SELECT record.id FROM public.ev_experiment_record record
        JOIN public.ev_experiment_game game ON game.id=record.game_id
        LEFT JOIN unnest(%s::text[]) WITH ORDINALITY AS prioritized(id,position) ON prioritized.id=record.id
        WHERE record.kind='checkpoint' AND record.checkpoint='late' AND game.provider='sportsgameodds'
          AND game.event->>'league'='NCAAB'
          AND NOT EXISTS (SELECT 1 FROM public.research_market_census census
            WHERE census.checkpoint_id=record.id AND census.format_version=%s)
          AND NOT EXISTS (SELECT 1 FROM public.research_market_census_retry retry
            WHERE retry.checkpoint_id=record.id AND retry.format_version=%s AND retry.retry_after>clock_timestamp())
        ORDER BY prioritized.position NULLS LAST,record.recorded_at DESC,record.id LIMIT 1""",
        (list(priority), VERSION, VERSION)).fetchone()
    if row is None:
        return None
    checkpoint_id = row["id"]
    try:
        census = for_checkpoint(db, checkpoint_id, include_rows=False)
    except (TypeError, KeyError, ValueError, ArithmeticError, AttributeError) as error:
        LOG.warning("Market census pending for %s (%s)", checkpoint_id, type(error).__name__)
        _defer(db, checkpoint_id, timedelta(hours=1), "checkpoint_derivation_failed")
        return None
    original = census["original_response"]
    if not (original.get("request_clock_matches") is True and original.get("request_scope_matches") is True
            and census["summary"]["counts_basis"] == "verified_original_response"):
        _defer(db, checkpoint_id, timedelta(hours=1), "exact_original_response_unverified")
        return None
    size = len(encoded(census))
    try:
        with db.transaction():
            queue._admit(db, size)
            published = db.execute("""INSERT INTO public.research_market_census
                (format_version,checkpoint_id,evidence_revision,payload_bytes,payload)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT (format_version,checkpoint_id) DO NOTHING RETURNING checkpoint_id""",
                (VERSION, checkpoint_id, census["evidence_revision"], size, Jsonb(census))).fetchone()
            db.execute("DELETE FROM public.research_market_census_retry WHERE format_version=%s AND checkpoint_id=%s",
                       (VERSION, checkpoint_id))
    except queue.PublicationDeferred:
        return None
    return published["checkpoint_id"] if published else None
