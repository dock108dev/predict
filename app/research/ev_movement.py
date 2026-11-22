"""Exact checkpoint measurements; no acquisition, inferred fills or fitted values."""

from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction as F

from app.comparison import current_pregame as math
from app.comparison.cashflows import exact_wire as wire
from app.storage.store import hashed, stamp

VERSION = "first-observed-24h-vs-tminus10-screen-ev-1"
IDENTITY_VERSION = "exact-event-book-outcome-settlement-bet-1"


def exact_bet_identity(record, event_identity=None):
    """Availability, source clocks and main/alternate role never change a bet."""
    event, market, quote = record["event"], record["market_identity"], record["quote"]
    source = quote["source"]
    family, side, _ = math.reference_key(record)
    selected_line = record["selection"].get("signed_line")
    if family != "moneyline" and selected_line is None:
        raise ValueError("experiment_exact_line_required")
    policy = record.get("result_policy")
    if source["provider"] == "sportsgameodds" and isinstance(policy, str):
        # This adapter suffix describes a missing opposing quote, not different
        # settlement semantics. Its appearance must not split exact continuity.
        policy = policy.split(":single:", 1)[0]
    scope = (record.get("comparison_source_metadata") or {}).get("scoring_scope") or {}
    from app.collection.sportsgameodds_current_rows import source_bookmaker

    body = dict(
        version=IDENTITY_VERSION,
        event=event_identity or dict(provider=source["provider"],
            source_event_id=source["native_event_id"], sport=event.get("sport"),
            league=event.get("competition"), home=event["home"], away=event["away"]),
        provider=source["provider"], book=source_bookmaker(record), venue=quote["venue"],
        family=family, period=market["period"], outcome=side,
        line=wire(F(selected_line)) if family != "moneyline" else None,
        settlement=dict(rules=market.get("rules"), result_policy=policy,
            period_boundary=record.get("period_boundary"),
            outcome_cardinality=record.get("outcome_cardinality"),
            explicit=record.get("settlement_semantics", record.get("settlement")),
            scoring_scope={k: scope.get(k) for k in ("overtime", "regulation", "conflicts")},
            overtime_evidence=sorted({r["overtime"] for r in scope.get("evidence", ())
                if r.get("overtime") in ("included", "excluded")})),
    )
    return dict(body, id=hashed(body))


def _role(record):
    value = (record.get("comparison_source_metadata") or {}).get("alternate")
    return dict(status="alternate" if value is True else "main" if value is False else "unknown",
                source="source_reported" if isinstance(value, bool) else "unknown",
                authority="sportsgameodds_byBookmaker" if isinstance(value, bool) else None,
                native_book_main_authority="unverified")


def _cashflow(payload, reference, policy):
    result = dict(probability=None, ev=None, expected_profit_usd=None,
                  policy=policy, reference_book=None, reason=None)
    if not reference or reference.get("probability") is None:
        result["reason"] = (reference or {}).get("reason") or "reference_unavailable"
        return result
    actual_policy = reference.get("selection_policy") or reference.get("policy_version")
    if actual_policy != policy:
        result["reason"] = "recorded_probability_policy_mismatch"
        return result
    p = F(reference["probability"])
    if not 0 < p < 1:
        raise ValueError("experiment_probability_invalid")
    result.update(probability=wire(p), reference_book=reference.get("book"))
    fee = (payload or {}).get("fee") or {}
    if fee.get("committed_usd") is None or fee.get("cashflows") is None:
        result["reason"] = "fee_cashflows_unavailable"
        return result
    committed = F(fee["committed_usd"])
    if committed <= 0 or set(fee["cashflows"]) != {"win", "loss"}:
        result["reason"] = "unsupported_cashflow_states_or_commitment"
        return result
    ev, _, _ = math.cashflow_values(reference, fee["cashflows"], committed)
    result.update(ev=wire(ev), expected_profit_usd=wire(committed * ev))
    return result


def offer_measurements(offer, *, offer_index=None, captured_at=None):
    record = offer["record"]
    payload = offer.get("calculation_payload")
    reference = (payload or {}).get("reference") or offer.get("screen_reference")
    coherent = (payload or {}).get("coherent_probability") or offer.get("coherent_reference")
    screen = _cashflow(payload, reference, math.REFERENCE_POLICY)
    baseline = _cashflow(payload, coherent, math.COHERENT_POLICY)
    quote = record["quote"]
    available = quote.get("state") == "available"
    reason = offer.get("reason") or (None if available else "price_withdrawn")
    # Unknown applicability/withdrawal never becomes a sign, including an old
    # numeric payload supplied alongside a now-unavailable source observation.
    if reason:
        for value in (screen, baseline):
            value.update(ev=None, expected_profit_usd=None, reason=reason)
    if payload and screen["ev"] is not None:
        asserted = (payload.get("raw") or {}).get("net_ev")
        if asserted is None or F(asserted) != F(screen["ev"]):
            raise ValueError("experiment_screen_cashflow_reproduction_mismatch")
    times = dict(quote.get("times") or {})
    times["calculated_at"] = (payload or {}).get("calculated_at")
    age = None
    if captured_at and times.get("source_at"):
        age = wire(F(str((stamp(captured_at)-stamp(times["source_at"])).total_seconds())))
    return dict(price=(quote.get("original") or {}).get("value"),
        price_units=(quote.get("original") or {}).get("units"),
        screen=screen, coherent=baseline, main=offer.get("main") or _role(record),
        times=times, source_age_seconds=age, available=available, reason=reason,
        calculation_version=(payload or {}).get("version"), offer_index=offer_index)


def _sign(value):
    if value is None:
        return None
    n = F(value)
    return "positive" if n > 0 else "negative" if n < 0 else "zero"


def retain_case(early_ev, late_ev):
    return any(v is not None and F(v) > 0 for v in (early_ev, late_ev))


def _cross(early, late, early_offer):
    if not early or not late:
        return dict(screen=None, coherent=None, reason="checkpoint_or_exact_bet_missing")
    payload = early_offer.get("calculation_payload")
    result = {}
    # Probability comes from the late witness. All cashflow/quantity/fee inputs
    # come from the early payload; calculate() is deliberately not called here.
    for label, policy in (("screen", math.REFERENCE_POLICY), ("coherent", math.COHERENT_POLICY)):
        late_value = late[label]
        reference = dict(probability=late_value["probability"], selection_policy=policy,
                         book=late_value.get("reference_book"), reason=late_value.get("reason"))
        result[label] = _cashflow(payload, reference, policy)
        if early.get("reason"):
            result[label].update(ev=None, expected_profit_usd=None, reason=early["reason"])
    result["reason"] = None
    return result


def _entries(checkpoint):
    if not checkpoint or checkpoint.get("status") not in (None, "captured", "complete"):
        return {}
    snapshot = checkpoint.get("snapshot") or checkpoint
    captured = (snapshot.get("times") or {}).get("known_at") or (snapshot.get("times") or {}).get("captured_at")
    result = {}
    for index, offer in enumerate(snapshot.get("offers", [])):
        identity = exact_bet_identity(offer["record"])
        if identity["id"] in result:
            raise ValueError("experiment_duplicate_exact_bet")
        result[identity["id"]] = (identity, offer,
            offer_measurements(offer, offer_index=index, captured_at=captured))
    return result


def _reference_main_links(early, late):
    """Reference books have their own source roles, without offer/fee authority."""
    grouped = defaultdict(lambda: [{}, {}])
    complete = [bool(value) and value.get("status") in (None, "captured", "complete") for value in (early, late)]
    offer_books = {"kalshi", "polymarket", "novig", "prophetexchange", "prophetx"}
    for index, checkpoint in enumerate((early, late)):
        if not checkpoint or checkpoint.get("status") not in (None, "captured", "complete"):
            continue
        snapshot = checkpoint.get("snapshot") or checkpoint
        for raw_index, quote in enumerate(snapshot.get("raw_quotes", [])):
            if quote["venue"] in offer_books or quote.get("partition") == "three_way":
                continue
            key = (quote["venue"], quote["market"], quote["side"])
            line = wire(F(quote["line"])) if quote.get("line") is not None else None
            identity = hashed(["reference_source_role", snapshot.get("event", {}).get("id"), *key, line])
            alternate = quote.get("alternate")
            role = "alternate" if alternate is True else "main" if alternate is False else "unknown"
            main = dict(status=role, source="source_reported" if isinstance(alternate, bool) else "unknown",
                        authority="sportsgameodds_byBookmaker", native_book_main_authority="unverified")
            grouped[key][index][identity] = dict(id=identity, line=line, role=role,
                measurement=dict(price=quote.get("price_american"), price_units="american_odds", main=main,
                    screen=dict(probability=None, ev=None, policy=math.REFERENCE_POLICY, reason="reference_only_book"),
                    coherent=dict(probability=None, ev=None, policy=math.COHERENT_POLICY, reason="reference_only_book"),
                    times=dict(source_at=quote.get("source_at"), received_at=quote.get("received_at")),
                    available=quote.get("available"), reason=quote.get("unavailable_reason"),
                    raw_quote_index=raw_index, offer_index=None, reference_only=True))
    result, context = [], []
    for (book, family, outcome), (first, second) in sorted(grouped.items()):
        mains = [[v for v in values.values() if v["role"] == "main"] for values in (first, second)]
        result.append(dict(id=hashed(["reference_main", book, family, outcome]), book=book,
            family=family, period="full_game", outcome=outcome, reference_only=True,
            early_main_ids=[v["id"] for v in mains[0]], late_main_ids=[v["id"] for v in mains[1]],
            early_main_lines=[v["line"] for v in mains[0]], late_main_lines=[v["line"] for v in mains[1]],
            movement="unknown" if any(len(v) != 1 for v in mains) else
                     "unchanged" if mains[0][0]["id"] == mains[1][0]["id"] else "changed",
            links=[dict(id=identity, early_role=first.get(identity, {}).get("role"),
                late_role=second.get(identity, {}).get("role"),
                relationship="checkpoint_missing" if not all(complete) else
                "newly_observed" if identity not in first else "no_longer_observed" if identity not in second else
                "unknown_role" if "unknown" in (first[identity]["role"], second[identity]["role"]) else
                "unchanged_role" if first[identity]["role"] == second[identity]["role"] else
                "main_to_alternate" if first[identity]["role"] == "main" else "alternate_to_main")
                for identity in sorted(set(first) | set(second))]))
        for identity in sorted(set(first) | set(second)):
            a, b = first.get(identity), second.get(identity)
            context.append(dict(id=identity, book=book, family=family, period="full_game", outcome=outcome,
                line=(a or b)["line"], reference_only=True, retain_case=False,
                early=a["measurement"] if a else None, late=b["measurement"] if b else None,
                incomplete=a is None or b is None, transition="reference_only_context",
                identity=dict(provider="sportsgameodds", book=book, family=family, period="full_game",
                              outcome=outcome, line=(a or b)["line"])))
    return result, context


def compare_checkpoints(early, late):
    first, second = _entries(early), _entries(late)
    a_snapshot = (early or {}).get("snapshot") or early or {}
    b_snapshot = (late or {}).get("snapshot") or late or {}
    a_start = (a_snapshot.get("event") or {}).get("scheduled_start")
    b_start = (b_snapshot.get("event") or {}).get("scheduled_start")
    rescheduled = bool(a_start and b_start and stamp(a_start) != stamp(b_start))
    first_known = (early or {}).get("known_at")
    late_known = (late or {}).get("known_at")
    late_target = (late or {}).get("target_at")
    timing_reason = None
    if first_known and late_known and stamp(first_known) >= stamp(late_known):
        timing_reason = "checkpoint_observation_order_unestablished"
    elif first_known and late_target and stamp(first_known) >= stamp(late_target):
        timing_reason = "late_discovery_no_pre_target_baseline"
    context, cases, groups = [], [], defaultdict(list)
    for identity_id in sorted(set(first) | set(second)):
        identity, source, _ = first.get(identity_id) or second[identity_id]
        a = first.get(identity_id, (None, None, None))[2]
        b = second.get(identity_id, (None, None, None))[2]
        sa, sb = _sign(a["screen"]["ev"]) if a else None, _sign(b["screen"]["ev"]) if b else None
        retained = retain_case(a["screen"]["ev"] if a else None, b["screen"]["ev"] if b else None)
        incomplete = sa is None or sb is None or rescheduled or timing_reason is not None
        transition = "rescheduled_incomplete" if rescheduled else "timing_incomplete" if timing_reason else "incomplete_positive" if retained and incomplete else (
            f"{sa}_to_{sb}" if sa is not None and sb is not None else "incomplete")
        ar, br = a["main"]["status"] if a else None, b["main"]["status"] if b else None
        role_unknown = any(v and v["main"].get("source") != "source_reported" for v in (a, b))
        captures_complete = all(value and value.get("status") in (None, "captured", "complete") for value in (early, late))
        relationship = ("checkpoint_missing" if not captures_complete else "newly_observed" if a is None else "no_longer_observed" if b is None else
            "unknown_role" if role_unknown or "unknown" in (ar, br) else "unchanged_role" if ar == br else
            "main_to_alternate" if ar == "main" else "alternate_to_main")
        missing = []
        for label, measurement in (("early", a), ("late", b)):
            if measurement is None:
                checkpoint = early if label == "early" else late
                why = (checkpoint or {}).get("reason") or (checkpoint or {}).get("last_reason") or "exact_bet_or_checkpoint_missing"
                missing.append(dict(checkpoint=label, reason=why))
            elif measurement["screen"]["ev"] is None:
                missing.append(dict(checkpoint=label, reason=measurement["screen"].get("reason") or "screen_ev_unavailable"))
        if rescheduled:
            missing.append(dict(checkpoint="comparison", reason="rescheduled_settlement_continuity_unverified"))
        if timing_reason:
            missing.append(dict(checkpoint="comparison", reason=timing_reason))
        cross = _cross(a, b, first.get(identity_id, (None, {}))[1]) if not (rescheduled or timing_reason) else dict(
            screen=None, coherent=None, reason="rescheduled_settlement_continuity_unverified" if rescheduled else timing_reason)
        row = dict(id=identity_id, identity=identity, game=source["record"]["event"].get("title"),
            **{key: identity[key] for key in ("book", "family", "period", "outcome", "line")},
            early=a, late=b, retain_case=retained, transition=transition, incomplete=incomplete,
            missing_reasons=missing, role_link=relationship,
            early_offer_late_reference=cross)
        context.append(row)
        if retained:
            cases.append(row)
        group_key = hashed({k: v for k, v in identity.items() if k not in ("id", "line")})
        groups[group_key].append(row)
    links = []
    for key, rows in sorted(groups.items()):
        a_main = [r["id"] for r in rows if r["early"] and r["early"]["main"]["status"] == "main"
                  and r["early"]["main"].get("source") == "source_reported"]
        b_main = [r["id"] for r in rows if r["late"] and r["late"]["main"]["status"] == "main"
                  and r["late"]["main"].get("source") == "source_reported"]
        representative = rows[0]
        links.append(dict(id=key, book=representative["book"], family=representative["family"],
            period=representative["period"], outcome=representative["outcome"],
            early_main_ids=a_main, late_main_ids=b_main,
            early_main_lines=[r["line"] for r in rows if r["id"] in a_main],
            late_main_lines=[r["line"] for r in rows if r["id"] in b_main],
            movement="unknown" if len(a_main) != 1 or len(b_main) != 1 else "unchanged" if a_main == b_main else "changed",
            links=[dict(id=r["id"], early_role=r["early"]["main"]["status"] if r["early"] else None,
                late_role=r["late"]["main"]["status"] if r["late"] else None,
                early_source=r["early"]["main"].get("source") if r["early"] else None,
                late_source=r["late"]["main"].get("source") if r["late"] else None,
                relationship=r["role_link"]) for r in rows]))
    reference_links, reference_context = _reference_main_links(early, late)
    links.extend(reference_links)
    return dict(version=VERSION, cases=cases, context=context, main_line_links=links,
        reference_context=reference_context,
        schedule_comparison=dict(early_start=a_start, late_start=b_start, rescheduled=rescheduled,
                                 settlement_continuity="unverified" if rescheduled else "unchanged_schedule"),
        timing_comparison=dict(early_known_at=first_known, late_known_at=late_known,
                               late_target_at=late_target, reason=timing_reason),
        counts=dict(retained_cases=len(cases), context_bets=len(context),
            reference_context_bets=len(reference_context),
            early_bets=len(first), late_bets=len(second), incomplete_cases=sum(r["incomplete"] for r in cases),
            transitions=dict(Counter(r["transition"] for r in cases))),
        policy_versions=dict(primary=math.REFERENCE_POLICY, coherent=math.COHERENT_POLICY,
                             calculation=math.VERSION, identity=IDENTITY_VERSION))


def reproduce_checkpoint(snapshot):
    """Verify frozen source/fee calculation and both probability policies offline."""
    from .calculation import freeze, reproduce, probability

    verified = 0
    references = snapshot.get("references") or []
    by_event = defaultdict(list)
    for row in references:
        by_event[row.get("event_id") or row.get("facts", {}).get("event_id")].append(row)
    inputs = math.ReferenceInputs(dict(by_event), books=math.COHERENT_POLICIES[math.EXPANSION_POLICY])
    for offer in snapshot.get("offers", []):
        payload = offer.get("calculation_payload")
        value = offer_measurements(offer)
        record = offer["record"]
        at = stamp((payload or {}).get("calculated_at") or
                   (snapshot.get("times") or {}).get("inputs_cutoff") or
                   (snapshot.get("times") or {}).get("known_at"))
        screen = (payload or {}).get("reference") or offer.get("screen_reference")
        if screen and screen.get("probability") is not None and references:
            if math.reference(record, inputs, at=at) != screen:
                raise ValueError("experiment_screen_reference_reproduction_mismatch")
        coherent = (payload or {}).get("coherent_probability") or offer.get("coherent_reference")
        if coherent and coherent.get("probabilities"):
            if references and math.qualified_coherent_reference(record, inputs, at=at) != coherent:
                raise ValueError("experiment_coherent_reference_reproduction_mismatch")
            probability(dict(coherent, starts_at=record["event"]["scheduled_start"]))
        if not payload:
            continue
        reproduce(freeze(payload, record=record, fee_input=offer.get("fee_input")))
        if value["screen"]["ev"] is not None:
            verified += 1
    return dict(offers=len(snapshot.get("offers", [])), numeric_screen_results=verified,
                provider_requests=0, version=VERSION)


def score_comparison(comparison, outcome):
    """Observed, selected-case probability scores; never settlement or fills."""
    from .records import resolved_side, scores

    data = (outcome or {}).get("data", outcome or {})
    values = defaultdict(list)
    excluded = Counter()
    for case in comparison["cases"]:
        identity = case["identity"]
        line = identity["line"]
        if identity["family"] == "spread" and identity["outcome"] == "away":
            line = wire(-F(line))
        side, reason = (None, "no_sporting_outcome_yet") if "final" not in data else resolved_side(
            dict(family=identity["family"], period=identity["period"], line=line), data)
        if reason:
            excluded[reason] += 1
            continue
        actual = int(side == identity["outcome"])
        for checkpoint in ("early", "late"):
            for policy in ("screen", "coherent"):
                observation = case[checkpoint]
                p = observation[policy]["probability"] if observation else None
                if p is None:
                    excluded[checkpoint + ":" + policy + ":probability_unavailable"] += 1
                else:
                    values[(checkpoint, policy)].append(dict(case_id=case["id"], actual=actual, **scores(p, actual)))
    reports = []
    for checkpoint in ("early", "late"):
        for policy in ("screen", "coherent"):
            rows = values[(checkpoint, policy)]
            reports.append(dict(checkpoint=checkpoint, policy=policy, records=len(rows),
                distinct_events=1 if rows else 0,
                mean_brier=wire(sum(F(r["brier"]) for r in rows)/len(rows)) if rows else None,
                observations=rows))
    return dict(scope="retained_cases_selected_by_screen_positive_at_either_checkpoint; selection_biased; within_game_dependence",
        retained_cases=len(comparison["cases"]), reports=reports, exclusions=dict(excluded),
        sporting_outcome_only=True, venue_settlement=None, actual_fills=None)


def build_snapshot(db, page, *, request_scope, dispatch_at, known_at):
    """Compute directly from this received page, not an asynchronous working row."""
    from app.collection.sportsgameodds_current_rows import current_rows, event_record
    from app.normalization.college_registry import sgo_registry
    from app.storage.current_pregame import CalculationContext
    from app.storage.sportsgameodds_reference import prepare_page

    if len(page.events) != 1:
        raise ValueError("experiment_single_event_required")
    at = stamp(known_at)
    rows, excluded = current_rows(page, page.receipt_sha256, include_unpriced=True)
    references = prepare_page(page)
    source = page.events[0]
    event = event_record(source, page.receipt_sha256, source["received_at"], sgo_registry())
    from app.storage.sgo_schedule_review import canonical_roles

    reviewed = canonical_roles(source["event_id"],
        (event["competition"], stamp(event["scheduled_start"]), event["home"], event["away"]), at=at)
    role_conflict = reviewed[2:] != (event["home"], event["away"])
    game_key = "ev-experiment:" + hashed([event["competition"], event["home"], event["away"], source["event_id"]])
    inputs = math.ReferenceInputs({source["event_id"]: references}, books=math.COHERENT_POLICIES[math.EXPANSION_POLICY])
    fee_context = CalculationContext(db, at)
    fee_context.db = db
    offers = []
    cached = {}
    for record in rows:
        if record["quote"]["venue"] not in ("kalshi", "polymarket_us", "novig", "prophetx"):
            continue
        reason, payload, fee = None, None, None
        screen, coherent = None, None
        try:
            if role_conflict:
                raise ValueError("experiment_canonical_role_review_conflict")
            if record["quote"]["source"]["provider"] != fee_context.price_routes.get(record["quote"]["venue"]):
                raise ValueError("acquisition_route_outside_primary_venue_scope")
            clocks = record["quote"]["times"]
            if any(stamp(clocks[key]) > at for key in ("source_at", "received_at") if clocks.get(key)):
                raise ValueError("experiment_future_offer_input")
            key = math.reference_key(record)
            if key not in cached:
                pair = []
                for function in (math.reference, math.qualified_coherent_reference):
                    try:
                        pair.append(function(record, inputs, at=at))
                    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                        pair.append(dict(reason=str(exc), probability=None, probabilities=None))
                cached[key] = pair
            screen, coherent = cached[key]
            if record["quote"]["state"] != "available":
                raise ValueError("price_withdrawn")
            if unsupported := math.posted_settlement_reason(record):
                raise ValueError(unsupported)
            fee = fee_context.fee(record, at)
            if not fee.get("available"):
                raise ValueError(fee.get("reason") or "fee_applicability_unavailable")
            payload = math.calculate(record, screen if screen.get("probability") is not None else None,
                                     fee, at=at, game_key=game_key)
            payload["coherent_probability"] = coherent
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            reason = str(exc) or "calculation_unavailable"
        offers.append(dict(record=record, calculation_payload=payload, fee_input=fee,
                           screen_reference=screen, coherent_reference=coherent,
                           main=_role(record), reason=reason))
    requested_books = sorted(set(str(request_scope.get("bookmakerID", "")).split(",")) - {""})
    received_books = sorted({q["venue"] for q in page.quotes})
    requested_odds = sorted(set(str(request_scope.get("oddID", "")).split(",")) - {""})
    received_odds = sorted({q["odd_id"] for q in page.quotes})
    surfaces = defaultdict(list)
    for q in page.quotes:
        if q.get("line") is not None:
            surfaces[(q["venue"], q["market"], q["side"])].append(F(q["line"]))
    coverage = dict(requested=dict(bookmakers=requested_books, odd_ids=requested_odds,
                    include_alt_lines=request_scope.get("includeAltLines") is True),
        received=dict(bookmakers=received_books, odd_ids=received_odds, quotes=len(page.quotes),
                      alternate_quotes=page.alternate_rows),
        supported=dict(offer_quotes=len(offers), reference_quotes=len(references)),
        missing=dict(bookmakers=sorted(set(requested_books)-set(received_books)),
                     odd_ids=sorted(set(requested_odds)-set(received_odds))),
        incomplete=bool(page.next_cursor or page.conflicting_alternate_lines or page.ignored_bookmaker_groups
                        or set(requested_books)-set(received_books) or set(requested_odds)-set(received_odds)),
        complete_market=False, scope="available_supported_surface_returned_by_provider; no_unseen_lines_inferred",
        rejected_projection=[list(r) for r in excluded],
        conflicting_alternate_lines=page.conflicting_alternate_lines,
        ignored_bookmaker_groups=page.ignored_bookmaker_groups,
        line_ranges=[dict(book=book, family=family, outcome=side, minimum=wire(min(lines)),
                         maximum=wire(max(lines)), distinct_lines=len(set(lines)))
                     for (book, family, side), lines in sorted(surfaces.items())])
    return dict(version=VERSION, event=event, source_event=source, offers=offers,
        references=references, raw_quotes=list(page.quotes), coverage=coverage,
        request_scope=deepcopy(request_scope), receipt_sha256=page.receipt_sha256,
        times=dict(dispatch_at=dispatch_at, received_at=source["received_at"], known_at=known_at,
                   captured_at=known_at, source_times=sorted({q["source_at"] for q in page.quotes if q.get("source_at")})),
        policy_versions=dict(screen=math.REFERENCE_POLICY, coherent=math.COHERENT_POLICY,
                             calculation=math.VERSION, experiment=VERSION))
