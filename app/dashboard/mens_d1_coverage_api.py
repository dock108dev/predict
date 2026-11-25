"""Daily coverage and adjudications over retained source and checkpoint evidence."""

import asyncio
from collections import Counter
from datetime import timedelta
from urllib.parse import urlencode

from aiohttp import web

from app.owned_work import joined_thread
from app.research import experiment, issue_dispositions, market_census, paper_campaigns, paper_evidence, workspace
from app.storage.store import connect, encoded, stamp
from .local_security import HEADERS, PublicRequestError, read_json
from .pipeline import serial


BASE = "/api/workspace/mens-d1"


def _saved(db, day, run_id):
    retained = list(db.execute("""SELECT r.id,r.game_date,r.definition_version,r.observed_at,r.summary,
               r.supersedes,r.report_revision,
               d.payload->>'designation' designation,d.payload#>>'{policy,scope}' scope,
               d.payload#>>'{policy,minimum_ev}' minimum_ev,d.payload->>'campaign_id' campaign_id,
               COALESCE(d.payload->>'sizing_mode','kelly') sizing_mode
        FROM public.research_workspace_run r JOIN public.research_workspace_definition d
        ON d.version=r.definition_version WHERE r.game_date=%s::date
        ORDER BY r.observed_at DESC,r.id""", (day,)))
    campaigns = paper_campaigns.index(db, active_only=True)
    primary_modes = {campaign['id']: paper_campaigns.modes(campaign)[0] for campaign in campaigns}
    runs = [row for row in retained if primary_modes.get(row['campaign_id']) == row['sizing_mode']]
    if campaigns:
        featured_id = campaigns[0]['id']
        runs.sort(key=lambda row: row['campaign_id'] != featured_id)
    selected = next((row for row in retained if row["id"] == run_id), None) if run_id else next(
        (row for row in runs if row["scope"] == "mens-d1"), None)
    if run_id and selected is None:
        raise PublicRequestError("The saved run belongs to another game date or is unavailable.")
    if selected is None:
        return runs, None, {}
    report = db.execute("""SELECT payload->'report' report FROM public.research_workspace_run
        WHERE id=%s""", (selected["id"],)).fetchone()["report"]
    return runs, selected, report


def _checkpoint_rows(db, day, provider_ids):
    return list(db.execute("""SELECT g.*,t.state task_state,t.target_at,t.deadline_at,t.last_reason,
        t.attempts,t.refusals,t.claimed_at,t.updated_at task_updated_at,t.last_refused_at,t.schedule_id task_schedule_id,
        o.state outcome_task_state,o.target_at outcome_target_at,o.deadline_at outcome_deadline_at,
        r.recorded_at checkpoint_persisted_at,
        COALESCE(r.payload#>>'{summary,received_at}',
                 metadata.payload#>>'{value,received_at}',
                 r.payload#>>'{value,$ev_checkpoint_envelope,metadata,received_at}',
                 r.payload#>>'{value,received_at}') checkpoint_received_at,
        COALESCE(metadata.payload#>>'{value,requested_at}',
                 r.payload#>>'{value,$ev_checkpoint_envelope,metadata,requested_at}',
                 r.payload#>>'{value,requested_at}') checkpoint_requested_at,
        COALESCE(r.payload#>>'{summary,known_at}', metadata.payload#>>'{value,known_at}',
                 r.payload#>>'{value,$ev_checkpoint_envelope,metadata,known_at}',
                 r.payload#>>'{value,known_at}') checkpoint_known_at,
        COALESCE(metadata.payload#>>'{value,schedule_id}',
                 r.payload#>>'{value,$ev_checkpoint_envelope,metadata,schedule_id}',
                 r.payload#>>'{value,schedule_id}') checkpoint_schedule_id,
        r.payload#>'{summary,coverage}' checkpoint_coverage
        FROM public.ev_experiment_game g
        LEFT JOIN public.ev_experiment_task t ON t.game_id=g.id AND t.checkpoint='late'
        LEFT JOIN public.ev_experiment_task o ON o.game_id=g.id AND o.checkpoint='outcome'
        LEFT JOIN public.ev_experiment_record r ON r.id=g.late_id
        LEFT JOIN public.ev_experiment_record metadata
          ON metadata.id=r.payload#>>'{value,$ev_checkpoint_envelope,metadata,$ev_checkpoint_ref}'
        WHERE g.provider='sportsgameodds' AND g.event->>'league'='NCAAB'
        AND (g.source_event_id=ANY(%s) OR
             ((g.event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date=%s::date)
        ORDER BY (g.event->>'starts_at')::timestamptz,g.id""", (sorted(provider_ids), day)))


def _capture(row, as_of, derived=None):
    if not row or row["task_state"] is None:
        return dict(state="no_task", reason="No retained T−10 capture task")
    state, reason = row["task_state"], row["last_reason"]
    target, deadline = row["target_at"], row["deadline_at"]
    if state in ("pending", "claimed") and stamp(as_of) > stamp(deadline):
        state, reason = "missed", reason or "capture_window_closed"
    elif state == "pending":
        state = "upcoming" if stamp(as_of) < stamp(target) else "due"
    if row["late_id"] and row["checkpoint_schedule_id"] and row["checkpoint_schedule_id"] != row["schedule_id"]:
        reason = reason or "historical_capture_schedule_changed"
        if state == "captured":
            state = "superseded_by_reschedule"
    return dict(state=state, reason=reason, target_at=target, deadline_at=deadline,
                task_schedule_id=row["task_schedule_id"], attempts=row["attempts"], refusals=row["refusals"],
                first_provider_observed_at=row["first_observed_at"],
                schedule_source_received_at=row["event"].get("source_metadata_received_at"),
                claimed_at=row["claimed_at"], task_updated_at=row["task_updated_at"], last_refused_at=row["last_refused_at"],
                frozen_id=row["late_id"], frozen_schedule_id=row["checkpoint_schedule_id"],
                frozen_requested_at=row["checkpoint_requested_at"], frozen_received_at=row["checkpoint_received_at"],
                frozen_known_at=row["checkpoint_known_at"],
                frozen_persisted_at=row["checkpoint_persisted_at"], frozen_coverage=row["checkpoint_coverage"],
                market_summary=market_census.summarize_coverage(row["checkpoint_coverage"], derived=derived))


def _provider_row(row):
    event = row["event"]
    return dict(provider_event_id=row["source_event_id"], title=event.get("title"),
                starts_at=event["starts_at"], match_state="provider_only",
                match_reason="No reviewed daily-slate link exists for this retained odds-provider game.")


def _provider_result_disposition(game, checkpoint, as_of):
    if game.get("occurrence_id") or game.get("source_game_id") or game.get("result_state") == "provider_final":
        return
    now = stamp(as_of)
    starts = game.get("starts_at")
    active_followup = (checkpoint and checkpoint["outcome_task_state"] in ("pending", "claimed")
                       and stamp(checkpoint["outcome_deadline_at"]) >= now)
    if active_followup or starts and stamp(starts) > now:
        game.update(result_state="provider_pending", result_reason="Provider final due after scheduled start")
        if active_followup:
            game["provider_result_target_at"] = checkpoint["outcome_target_at"]
    else:
        game.update(result_state="provider_result_unresolved", result_reason="No final retained from the odds provider")


def _row_id(row):
    if row.get("occurrence_id"):
        return row["occurrence_id"]
    return f'source:{row["source_game_id"]}' if row.get("source_game_id") else f'provider:{row["provider_event_id"]}'


def _saved_game(game, run, tickets, derived=None):
    if game is None:
        return None
    base = f'/api/research/workspace/runs/{run["id"]}/evidence/{game["game_id"]}'
    qualifying = {variant:len(rows) for variant, rows in tickets.items()} if game["status"] in ("captured", "reconstructed") else None
    return dict(**game, qualifying=qualifying, market_summary=market_census.summarize_coverage(game.get("coverage"), derived=derived),
                evidence_export=base + "?export=1", original_response_export=base + "?raw=1" if game["checkpoint_id"] else None)


def _facets(row, in_scope):
    scope, match = row.get("scope_state"), row.get("match_state")
    source = row.get("source_game_id") is not None
    other_date = row.get("day_applicability") == "other_date"
    facets = []
    if source and not row.get("removed") and not row.get("result_only") and row.get("gender") in ("men", "male", "mens", "m"):
        facets.append("source_mens")
    if other_date:
        facets.append("other_date")
    elif scope in ("eligible", "excluded", "unresolved") and source:
        if scope != "eligible" or in_scope:
            facets.append({"eligible":"expected","excluded":"excluded","unresolved":"membership_unresolved"}[scope])
    retained = row.get("retained_scope") or {}
    if not other_date and retained.get("state") in ("eligible", "excluded", "unresolved"):
        facets.append("retained_" + retained["state"])
    provider_scope = (row.get("provider_membership") or {}).get("state")
    if not other_date and provider_scope in ("eligible", "excluded", "unresolved"):
        facets.append("provider_scope_" + provider_scope)
    if match in ("source_only", "provider_only", "provider_conflict", "identity_conflict", "schedule_conflict", "site_conflict", "no_market", "result_only"):
        facets.append(match)
    if in_scope and row.get("operational_schedule_state") == "resolved_source_schedule_disagreement":
        facets.append("schedule_corroborated")
    if in_scope and match in ("matched", "no_market"):
        facets.append("matched")
    capture, saved = row["capture"], row.get("saved") or {}
    # Include the original task disposition even if a later calculation recovered the response.
    if in_scope:
        facets.append("result_ledger")
        if (capture["state"] == "captured" and capture.get("frozen_id")) or saved.get("status") == "captured":
            facets.append("frozen")
        if capture["state"] == "captured" and capture.get("frozen_id"):
            facets.append("current_market_evidence")
        if capture["state"] in ("upcoming", "due", "claimed", "missed", "failed", "refused", "cancelled", "superseded_by_reschedule", "no_task"):
            facets.append(capture["state"])
    if saved.get("status") == "reconstructed":
        facets.append("reconstructed")
    if saved.get("evaluated_offers") is not None:
        facets.append("evaluated")
        if saved.get("observed_offer_count") is not None:
            facets.append("observed_offers")
        if saved.get("observed_offer_count") == 0:
            facets.append("zero_offers")
        if (saved.get("qualifying") or {}).get("all_venues") == 0:
            facets.append("zero_qualifiers")
        if any(reason.startswith("reference_") and count for reason, count in (saved.get("exclusions") or {}).items()):
            facets.append("reference_gaps")
    for variant in ("best_venue", "all_venues"):
        if (saved.get("qualifying") or {}).get(variant, 0):
            facets.append("qualifying_" + variant)
    if in_scope and scope == "eligible":
        result = row.get("result_state")
        facets.append({"final":"final", "conflicting":"conflicting", "pending":"result_pending"}.get(result, "result_unresolved"))
    if not other_date and (row.get("provider_results") or [{}])[0].get("status") == "final":
        facets.append("provider_final")
    if row.get("result_state") in ("provider_pending", "provider_result_unresolved"):
        facets.append(row["result_state"])
    return facets


def _operational_schedule(game):
    raw = game.get("match_state")
    game["raw_occurrence_match_state"] = raw
    game["raw_occurrence_match_reason"] = game.get("match_reason")
    schedule = game.get("occurrence_schedule") or {}
    if schedule.get("state") == "official_provider_clock_corroborated":
        game["operational_schedule_state"] = "resolved_source_schedule_disagreement"
        game["match_state"] = "matched" if (game.get("provider_evidence") or {}).get("market_observed") else "no_market"
        game["match_reason"] = "official_and_provider_start_corroborated_original_source_clock_retained"
    else:
        game["operational_schedule_state"] = schedule.get("state")


def _eligible_occurrence(game, day):
    if game.get("occurrence_id"):
        return bool(game.get("paper_eligible"))
    return ((game.get("provider_membership") or {}).get("state") == "eligible"
            and game.get("eastern_game_date", day) == day)


def _known_before(game):
    capture = game["capture"]
    observation = game.get("observation")
    if observation is None:
        first, target = capture.get("first_provider_observed_at"), capture.get("target_at")
        return bool(first and target and stamp(first) < stamp(target))
    if not capture.get("target_at"):
        return observation.get("known_before_tminus10") is True
    target = stamp(capture["target_at"])
    start = target + timedelta(minutes=10)
    schedule = game.get("occurrence_schedule") or {}
    for item in schedule.get("evidence", []):
        if item.get("starts_at") and stamp(item["starts_at"]) == start:
            origin = item["origin"]
            known_key = "source_identity_known_at" if origin == "source" else origin + "_clock_known_at"
            known = observation.get(known_key)
            if known and stamp(known) < target:
                return True
    return False


def _sporting_state(game):
    state = game.get("result_state")
    if state in ("final", "provider_final"):
        return "final"
    if state in ("pending", "provider_pending"):
        return "pending"
    if state in ("conflicting", "disputed"):
        return "disputed"
    return "missing"


def _paper_usability(game, as_of, saved_at=None):
    capture, saved = game["capture"], game.get("saved") or {}
    if saved:
        status = saved["status"]
        if status == "no_task" and saved.get("starts_at") and saved_at and stamp(saved["starts_at"]) > stamp(saved_at):
            return "pending"
        return {"reconstructed":"reconstructed", "captured":"frozen", "pending":"pending", "upcoming":"pending",
                "due":"pending", "claimed":"pending"}.get(status, "missing")
    if capture["state"] == "captured" and capture.get("frozen_id"):
        return "frozen"
    if capture["state"] in ("upcoming", "due", "claimed") or (
            game.get("starts_at") and stamp(game["starts_at"]) > stamp(as_of)):
        return "pending"
    return "missing"


def _reconciliation(value, games, run, issues):
    if "occurrences" not in value or not games and not run:
        return None
    current = [game for game in games if game["research_scope"] == "eligible"]
    reviewed = [game for game in games if game.get("saved")] if run else current
    cohort_ids = {game["id"] for game in reviewed}
    usable = [game for game in reviewed if game["paper_usability"] in ("frozen", "reconstructed")]
    evaluated = [(game.get("saved") or {}).get("qualifying") for game in usable]
    qualifiers = [row["all_venues"] for row in evaluated if row and row.get("all_venues") is not None]
    original_states = Counter(game["capture"]["state"] for game in reviewed)
    return dict(cohort_name=f'{value["date"]} Eastern · reconciled observed men’s D1 vs D1 cohort',
        reviewed_games=len(reviewed), usable_games=len(usable),
        frozen_games=sum(game["paper_usability"] == "frozen" for game in usable),
        reconstructed_games=sum(game["paper_usability"] == "reconstructed" for game in usable),
        games_with_trades=sum(count > 0 for count in qualifiers) if run else None,
        games_without_qualifiers=qualifiers.count(0) if run else None,
        historical_gaps=sum(game["paper_usability"] == "missing" for game in reviewed),
        accepted_historical_gaps=sum(issue["kind"] == "capture" and issue["game_id"] in cohort_ids
            and issue["active"] and issue["status"] == issue_dispositions.GAP for issue in issues),
        finals=sum(_sporting_state(game) == "final" for game in reviewed),
        excluded_games=sum(game["research_scope"] == "excluded" for game in games),
        other_date_games=sum(game["research_scope"] == "other_date" for game in games),
        corroborated_schedule_disagreements=sum("schedule_corroborated" in game["facets"] for game in current),
        original_capture_states=dict(original_states), exhaustive_slate=value.get("expected_games") is not None)


def _gap(evidence, consequence, cause, classification, remedy, **location):
    return dict(evidence=evidence, consequence=consequence, cause=cause,
                classification=classification, remedy=remedy, **location)


def _coverage_gaps(value, games):
    gaps = []
    if value.get("expected_games") is None:
        gaps.append(_gap("Independently complete dated D1 slate", "An absolute coverage rate cannot be established.",
                         "The retained CBBD and odds exports do not attest exhaustive membership.", "external_source_limitation",
                         "Compare an exhaustive season-scoped schedule and resolve remaining schedule revisions by occurrence."))
    now = stamp(value["as_of"])
    for game in games:
        location = dict(game_id=game["id"], game_title=game.get("title"))
        match = game.get("match_state")
        applicability = game.get("day_applicability")
        if game.get("scope_state") == "unresolved" or applicability == "disputed":
            gaps.append(_gap("Confirmed participant identities or Eastern game date", "Dated eligibility remains unresolved.",
                             game.get("match_reason") or "Conflicting or incomplete upstream identity or schedule evidence.",
                             "external_source_limitation", "Obtain a corrected source record or dated official confirmation.", **location))
        if (game.get("occurrence_schedule") or {}).get("state") == "start_disputed":
            gaps.append(_gap("Agreed scheduled start", "The game’s Eastern date is known and its exact start remains disputed.",
                             "Retained source, provider or official scheduled clocks disagree.", "external_source_limitation",
                             "Check the organizer’s latest schedule and retain the original capture target.", **location))
        if not _eligible_occurrence(game, value.get("date")):
            continue
        if match in ("provider_only", "source_only", "no_market"):
            gaps.append(_gap("Matching independent schedule or provider market evidence", "An observed game lacks independent cross-source coverage.",
                             game.get("match_reason") or "Counterpart not retained.", "external_source_limitation",
                             "Reconcile the next guarded source revision or confirm the missing member directly with the source.", **location))
        capture, saved = game["capture"], game.get("saved") or {}
        state = capture["state"]
        if state != "captured":
            target = capture.get("target_at") or (game.get("schedule") or {}).get("target_at")
            start = game.get("starts_at") or (game.get("schedule") or {}).get("starts_at")
            future = state in ("upcoming", "due", "claimed") or (state == "no_task" and start and stamp(start) > now)
            original = saved.get("status") == "reconstructed"
            if future:
                consequence, remedy = "There is no frozen evidence yet.", "Observe the existing guarded deadline and its task disposition."
                classification = "future_event"
            elif original:
                consequence, remedy = ("The saved analysis has a reconstruction and the original failed capture remains in the ledger.",
                                       "Use the retained reconstruction for paper analysis and the original disposition for reliability.")
                classification = "irrecoverable_historical_loss"
            else:
                consequence, remedy = ("The game has no qualifying retained T−10 checkpoint in this view.",
                                       "Check for an original in-window receipt; leave the historical gap if none exists.")
                classification = "irrecoverable_historical_loss"
            cause = capture.get("reason") or state
            if target:
                cause = f"{cause} ({stamp(target).isoformat()})"
            gaps.append(_gap("Original T−10 capture", consequence, cause, classification, remedy, **location))
        if state == "captured" or saved.get("status") in ("captured", "reconstructed"):
            gaps.append(_gap("Exhaustive venue inventory", "Requested and returned markets only give bounded offer evidence.",
                             "The odds feed describes returned event objects and exposes no exhaustive venue inventory.",
                             "external_source_limitation", "Compare request and returned cells in the game’s census and seek venue inventory if available.", **location))
        result = _sporting_state(game)
        if result != "final":
            gaps.append(_gap("Confirmed sporting final", "A sporting result cannot be verified yet.",
                             game.get("result_reason") or result,
                             "future_event" if result == "pending" else "external_source_limitation",
                             "Inspect the existing prior-day source job or an official result once available.", **location))
    return gaps


def _market_gaps(census, game):
    location = dict(game_id=game["id"], game_title=game.get("title"))
    gaps = []
    if census["original_response"]["state"] != "retained":
        gaps.append(_gap("Original response bytes", "Only the normalized checkpoint can be inspected.",
                         census["original_response"].get("reason") or "Original receipt unavailable.",
                         "irrecoverable_historical_loss", "Check the durable receipt archive for these original bytes.", **location))
    for cell in census.get("request_cells", []):
        if cell["state"] not in ("requested_but_unreturned", "return_unverified", "unsupported", "not_requested"):
            continue
        gaps.append(_gap("Requested venue and outcome observation" if cell["requested"] else "Venue and outcome request",
                         "No returned line can be established for this cell.", cell["state"], "external_source_limitation",
                         "Use the saved request and original response; check provider or venue capability for future captures.",
                         venue=cell["venue"], market=cell["family"], outcome=cell["outcome"], **location))
    for offer in census.get("offers", []):
        missing = offer.get("reference_gap")
        if missing:
            causes = ", ".join(missing["causes"]) or missing["reason"]
            recoverable = "normalization_or_projection_gap" in missing["causes"] or not missing["frozen_disposition_matches"]
            gaps.append(_gap("Trusted exact-line reference evidence", "The offer is excluded from reference-backed paper EV.",
                             causes, "recoverable_engineering" if recoverable else missing["assessment"],
                             "Inspect exact book and side evidence in this market census.", venue=offer["venue"],
                             market=offer["family"], outcome=offer["outcome"], line=offer["line"], **location))
        elif offer.get("price_state") == "explicitly_unavailable" or offer.get("disposition") == "price_withdrawn":
            gaps.append(_gap("Available original price", "This unavailable observation cannot qualify as an offer.",
                             offer.get("price_reason") or "Provider explicitly marked unavailable.",
                             "external_source_limitation", "Preserve the withdrawal and observe future captures.",
                             venue=offer["venue"], market=offer["family"], outcome=offer["outcome"], line=offer["line"], **location))
        elif offer.get("disposition") == "screen_passed":
            evidence = "Actual venue fees and executable quoted size"
            if not offer.get("venue_contract_id"):
                evidence += " and venue contract ID"
            gaps.append(_gap(evidence, "The quoted price supports a modeled paper ticket only.",
                             "The frozen odds observation supplies no verified account fee or order-book depth.",
                             "external_source_limitation", "Compare an authorized venue contract, fee schedule and same-time order book.",
                             venue=offer["venue"], market=offer["family"], outcome=offer["outcome"], line=offer["line"], **location))
    return gaps


def _coverage_summary(value, games, run, report, censuses=None, *, issues=()):
    from app.storage.mens_d1_coverage import EASTERN

    provider = [game for game in games if (game.get("provider_membership") or {}).get("state") == "eligible"
                and (not game.get("provider_evidence") or str(stamp(game["provider_evidence"]["starts_at"])
                     .astimezone(EASTERN).date()) == value.get("date"))]
    counts = value.get("counts", {})
    expected = counts.get("expected")
    source_eligible = [game for game in games if "expected" in game["facets"]]
    if "occurrences" in value:
        current = [game for game in games if _eligible_occurrence(game, value["date"])]
        basis = "reconciled_occurrences"
    else:
        current = source_eligible if expected is not None else provider
        basis = "source" if expected is not None else "provider_known"
    saved = report.get("games", [])
    captured = [game for game in saved if game["status"] in ("captured", "reconstructed")]
    observed_counts = [game.get("observed_offer_count") for game in captured]
    evaluated_counts = [game.get("evaluated_offers") for game in captured]
    exclusions = Counter()
    for game in captured:
        exclusions.update(game.get("exclusions") or {})
    reference = {reason: amount for reason, amount in exclusions.items() if reason.startswith("reference_")}
    states = Counter(game["capture"]["state"] for game in current)
    market_summaries = [market_census.summarize_coverage(game.get("coverage"),
        derived=(censuses or {}).get(game.get("checkpoint_id"))) or {} for game in captured]
    retrieval = Counter(summary.get("retrieval_state", "unknown_completeness") for summary in market_summaries)
    result_states = Counter(_sporting_state(game) for game in current)
    matches = counts.get("matches", {})
    countable_markets = [summary for summary in market_summaries if summary.get("returned_cells") is not None
                         and summary.get("requested_cells") is not None]
    original_markets = [summary for summary in market_summaries if summary.get("version") == market_census.VERSION]
    offer_accounting, reference_accounting = Counter(), Counter()
    for summary in original_markets:
        offer_accounting.update(summary["offer_accounting"])
        reference_accounting.update(summary["reference_accounting"])
    return dict(
        population=dict(as_of=value["as_of"], observed_at=value.get("source_observed_at"),
                        revision=value.get("population_revision"), expected_games=expected,
                        source_identity=value.get("source"), source_mode=value.get("source_mode"),
                        source_corroborated_additional_eligible=counts.get("source_corroborated_additional_eligible"),
                        source_official_eastern_date_conflicts=counts.get("source_official_eastern_date_conflicts"),
                        source_url=value.get("source_url"), source_eligible_games=counts.get("source_eligible"),
                        source_returned_mens_games=counts.get("source_returned_mens_games"),
                        source_eligible_known_before_tminus10=sum(game.get("known_before_tminus10") is True
                                                                  for game in source_eligible) if value.get("population_revision") else None,
                        matched_games=sum("matched" in game["facets"] for game in current) if "occurrences" in value
                            else counts.get("provider_matches"),
                        raw_source_provider_matches=counts.get("provider_matches"),
                        raw_source_unresolved_membership=counts.get("unresolved_membership"),
                        reconciled_eligible_games=len(current) if "occurrences" in value else None,
                        provider_known_games=len(provider), occurrence_games=len(games),
                        source_only_games=sum(game.get("match_state") == "source_only" and game.get("scope_state") == "eligible"
                                              and game.get("day_applicability") != "other_date" for game in games),
                        provider_only_games=sum(game.get("match_state") == "provider_only" for game in current),
                        unresolved_membership_games=sum(game.get("scope_state") == "unresolved" for game in games),
                        schedule_disputes=sum(game.get("match_state") in ("schedule_conflict", "site_conflict") and
                            game.get("day_applicability") != "other_date" for game in games),
                        date_disputes=sum(game.get("day_applicability") == "disputed" for game in games),
                        unresolved_date_games=sum(game.get("day_applicability") == "disputed" for game in games),
                        source_match_states=matches),
        capture=dict(as_of=value["as_of"], current_denominator=len(current),
                     population_basis=basis, current_states=dict(states),
                     known_before_target=sum(_known_before(game) for game in current),
                     current_frozen=states["captured"],
                     current_upcoming=sum(states[state] for state in ("upcoming", "due", "claimed")),
                     current_misses=states["missed"], current_refusals=states["refused"],
                     saved_at=report.get("as_of"), saved_denominator=len(saved) if run else None,
                     saved_frozen=sum(game["status"] == "captured" for game in captured),
                     saved_reconstructed=sum(game["status"] == "reconstructed" for game in captured),
                     saved_states=dict(Counter(game["status"] for game in saved)),
                     zero_offer_games=sum(count == 0 for count in observed_counts),
                     zero_qualifier_games=sum(game.get("tickets") == 0 for game in captured)),
        markets=dict(as_of=report.get("as_of"), evidence_games=len(captured) if run else None,
                     saved_retrieval_states=dict(retrieval), current_evidence_games=states["captured"],
                     current_as_of=value["as_of"],
                     observed_offer_games=sum(n is not None for n in observed_counts),
                     observed_offers=sum(observed_counts) if captured and None not in observed_counts else None,
                     cell_counts_games=len(countable_markets), original_census_games=len(original_markets),
                     requested_cells=sum(summary["requested_cells"] for summary in countable_markets) if countable_markets else None,
                     returned_cells=sum(summary["returned_cells"] for summary in countable_markets) if countable_markets else None,
                     unreturned_cells=sum(summary["unreturned_cells"] for summary in countable_markets
                                          if summary.get("unreturned_cells") is not None) if countable_markets else None,
                     no_provider_odds_cells=sum(summary["no_provider_odds_cells"] for summary in original_markets)
                                            if original_markets else None,
                     offer_accounting=dict(offer_accounting) if original_markets else None,
                     offer_accounting_minimum_ev=market_census.BASELINE_MINIMUM if original_markets else None,
                     request_states=dict(Counter(summary.get("request_state", "unknown_completeness")
                                                 for summary in market_summaries)),
                     venue_inventory="unknown", traversal_states=dict(Counter(
                         summary.get("traversal", "unknown") for summary in market_summaries))),
        reference=dict(as_of=report.get("as_of"), observed_offers=sum(observed_counts) if captured and None not in observed_counts else None,
                       evaluated_offers=sum(evaluated_counts) if captured and None not in evaluated_counts else None,
                       reference_gaps=sum(reference.values()) if captured else None,
                       exclusions=dict(exclusions), reference_exclusions=reference,
                       verified_method_accounting=dict(reference_accounting) if original_markets else None),
        trade=dict(as_of=report.get("as_of"), variants={name: paper_evidence.clock_counts(portfolio["tickets"])
                   for name, portfolio in report.get("portfolios", {}).items()}, fees="unknown", size="unknown",
                   contract_identity="provider_market_keys_retained_venue_contract_may_be_unknown"),
        results=dict(as_of=value["as_of"], denominator=len(current),
                     states={state: result_states[state] for state in ("final", "pending", "disputed", "missing")}),
        reconciliation=_reconciliation(value, games, run, issues),
    )


def coverage_view(db, day, run_id, selection):
    from app.storage.mens_d1_coverage import read_coverage

    value = read_coverage(db, day)
    value.setdefault("date", day)
    runs, run, report = _saved(db, day, run_id)
    population = report.get("population") or {}
    retained_sources = {row["source_game_id"]:row for row in population.get("games", []) if row.get("source_game_id")}
    retained_providers = {row["provider_event_id"]:row for row in population.get("games", []) if row.get("provider_event_id")}
    saved_games = {game["game_id"]:game for game in report.get("games", [])}
    tickets = {variant:{} for variant in report.get("portfolios", {})}
    for variant, portfolio in report.get("portfolios", {}).items():
        for ticket in portfolio["tickets"]:
            tickets[variant].setdefault(ticket["game_id"], []).append(ticket)
    if "occurrences" in value:
        games = [dict(row) for row in value["occurrences"]]
    else:
        games = [dict(row) for row in (*value["games"], *value["provider_only"])]
        games.extend(dict(source_game_id=result["source_game_id"], teams=result["teams"],
            starts_at=result.get("starts_at"), result_only=True, match_state="result_only",
            match_reason="A sporting result was retained without a matching schedule occurrence.",
            result=result, result_state="unresolved", result_reason="Schedule occurrence unverified.")
            for result in value["result_only"])
    attached = {row["provider_event_id"] for row in games if row.get("provider_event_id")}
    source_ids = {row["source_game_id"] for row in games if row.get("source_game_id")}
    checkpoints = _checkpoint_rows(db, day, attached | set(retained_providers))
    stored = {row["source_event_id"]:row for row in checkpoints}
    censuses = market_census.read_summaries(db, [*(row["late_id"] for row in checkpoints),
        *(game.get("checkpoint_id") for game in saved_games.values())])
    named = attached | {identity for game in games for identity in game.get("provider_event_ids", [])}
    games.extend(_provider_row(row) for event_id,row in stored.items() if event_id not in named)
    retained_occurrences = {row["occurrence_id"]:row for row in population.get("games", []) if row.get("occurrence_id")}
    for game in games:
        if "retained_scope" in game:
            game["provider_membership"] = game.pop("retained_scope")
        game["id"] = _row_id(game)
        source_aliases = [f'source:{record["source_game_id"]}' for record in game.get("source_records", [])
                          if record.get("source_game_id")]
        if game.get("source_game_id"):
            source_aliases.append(f'source:{game["source_game_id"]}')
        if game.get("provider_event_id"):
            source_aliases.append(f'provider:{game["provider_event_id"]}')
        game["legacy_ids"] = sorted(set(source_aliases) - {game["id"]})
        selected = _matches_id(game, selection)
        row = stored.get(game.get("provider_event_id"))
        _provider_result_disposition(game, row, value["as_of"])
        _operational_schedule(game)
        retained = retained_occurrences.get(game.get("occurrence_id")) or retained_sources.get(game.get("source_game_id"))
        provider_scope = retained_providers.get(game.get("provider_event_id"))
        if retained is None and provider_scope and provider_scope.get("source_game_id") not in source_ids:
            retained = provider_scope
        if retained:
            game["retained_scope"] = dict(state=retained["scope_state"], reason=retained["scope_reason"], teams=retained.get("teams"))
        game["capture"] = _capture(row, value["as_of"], censuses.get(row["late_id"]) if row else None)
        game["saved"] = None
        saved_game_id = retained.get("game_id") if retained else row["id"] if row and not population else None
        saved = saved_games.get(saved_game_id)
        if saved:
            matches = {name:items.get(saved_game_id, []) for name,items in tickets.items()}
            game["saved"] = _saved_game(saved, run, matches, censuses.get(saved.get("checkpoint_id")))
            if selected:
                game["ticket_clocks"] = {name:[{key:ticket.get(key) for key in ("id","label","venue","times")}
                    for ticket in items] for name,items in matches.items()}
        if row:
            game["title"] = game.get("title") or row["event"].get("title")
            game_id = row["id"]
            if selected:
                revision = experiment._revision(db, row)
                query = urlencode(dict(id=game_id, revision=revision))
                game["checkpoint_inspect"] = '/data?evidence=checkpoints&' + query
                game["checkpoint_export"] = '/api/research/experiment?export=1&' + query
        in_scope = (_eligible_occurrence(game, day) if "occurrences" in value else (game.get("scope_state") == "eligible"
                    or (game.get("provider_membership") or {}).get("state") == "eligible"
                    or bool(retained and retained["scope_state"] == "eligible")))
        game["research_scope"] = ("other_date" if game.get("day_applicability") == "other_date" else
            "eligible" if in_scope else "unresolved" if game.get("day_applicability") == "disputed" else
            game["scope_state"] if game.get("scope_state") in ("excluded", "unresolved") else "not_eligible")
        game["paper_usability"] = _paper_usability(game, value["as_of"], report.get("as_of")) if in_scope or saved else None
        game["facets"] = _facets(game, in_scope)
    facets = Counter(facet for game in games for facet in game["facets"])
    evaluated = [game["saved"]["evaluated_offers"] for game in games if "evaluated" in game["facets"]]
    offers = {"evaluated":sum(evaluated) if evaluated else None}
    for variant in tickets:
        facet = "qualifying_" + variant
        offers[facet] = sum(game["saved"]["qualifying"][variant] for game in games if facet in game["facets"])
    games.sort(key=lambda row:((row.get("schedule") or {}).get("starts_at") or row.get("starts_at") or "~", row["id"]))
    issues, issue_counts = issue_dispositions.list_issues(db, value, games, run)
    by_game = {}
    for issue in issues:
        by_game.setdefault(issue["game_id"], []).append(issue["id"])
    for game in games:
        game["issues"] = by_game.get(game["id"], [])
    return {**{key:val for key,val in value.items() if key not in ("games","provider_only","occurrences")},
        "games":games,"facets":dict(facets),"offer_counts":offers,
        "run":run if run_id else None,"runs":runs,"analysis_run":run,"run_population":report.get("population"),
        "missing_items":_coverage_gaps(value, games),
        "issues":issues,"issue_counts":issue_counts,
        "coverage_summary":_coverage_summary(value, games, run, report, censuses, issues=issues),
        "provider_requests":0,"orders_submitted":0}


def decide_issue(db, day, body):
    issue_dispositions.lock(db, body["id"])
    view = coverage_view(db, day, body.get("run"), None)
    issue = next((item for item in view["issues"] if item["id"] == body["id"]), None)
    if issue is None:
        raise web.HTTPNotFound(reason="The selected issue is unavailable for this date.")
    issue_dispositions.require_current(issue, body)
    # The private app has one owner identity at the authenticated proxy.
    return issue_dispositions.record(db, day, issue, body["status"], body["reason"], "owner",
                                     evidence_url=body["evidence_url"])


def _matches_id(row, identity):
    return identity == row["id"] or identity in row.get("legacy_ids", [])


def market_view(db, day, run_id, game_id, version, raw=False):
    value = coverage_view(db, day, run_id, None)
    game = next((row for row in value["games"] if _matches_id(row, game_id)), None)
    if game is None:
        raise web.HTTPNotFound(reason="The selected game is unavailable on this date.")
    if version == "saved":
        checkpoint = (game.get("saved") or {}).get("checkpoint_id")
    else:
        checkpoint = game["capture"].get("frozen_id") if game["capture"]["state"] == "captured" else None
    if not checkpoint:
        raise web.HTTPNotFound(reason="There is no retained T−10 market evidence for this selection.")
    minimum = (value.get("run") or {}).get("minimum_ev") if version == "saved" else None
    derived = market_census.read_summaries(db, [checkpoint]).get(checkpoint)
    census = (derived if raw and derived else
              market_census.for_checkpoint(db, checkpoint, include_rows=not raw,
                  minimum=minimum or market_census.BASELINE_MINIMUM))
    if raw:
        from app.collection.original_receipts import read

        original = census["original_response"]
        if original["state"] != "retained":
            raise web.HTTPNotFound(reason="The original odds response is unavailable for this capture.")
        try:
            return read(original["id"])
        except (KeyError, OSError, ValueError):
            raise web.HTTPNotFound(reason="The original odds response is unavailable for this capture.") from None
    census = market_census.apply_summary(census, derived)
    saved = game.get("saved") or {}
    return dict(census, date=day, game=game_id, title=game.get("title"), basis=version,
                missing_items=_market_gaps(census, game),
                saved_disposition={key: saved.get(key) for key in ("status", "qualifying", "exclusions")}
                if version == "saved" else None)


def _response(value, filename=None):
    headers = dict(HEADERS)
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return web.Response(body=encoded(serial(value)), content_type="application/json", headers=headers)


def _provider_result_receipt(db, identity):
    from app.collection.original_receipts import lookup, read

    row = db.execute("""SELECT 1 FROM public.ev_experiment_record r
        JOIN public.ev_experiment_game g ON r.game_id=g.id
        WHERE r.id=%s AND r.kind='outcome' AND g.provider='sportsgameodds' AND g.event->>'league'='NCAAB'""",
        (identity,)).fetchone()
    if row is not None:
        index = experiment._closure(db, [identity])
        digest = experiment._value(index[identity], index)["data"].get("receipt_sha256")
        evidence = lookup(digest)
        found = next((item for item in reversed(evidence.get("captures", [])) if item["state"] == "retained"), None)
        if found:
            return read(found["id"])
    raise web.HTTPNotFound(reason="Original provider result response was not retained.")


def mount(app, *, read_only=False):
    gate = asyncio.Semaphore(2)

    async def work(operation, *args, read_only=True):
        def query():
            with connect() as db, db.transaction():
                if read_only:
                    db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                db.execute("SET LOCAL statement_timeout='10s'")
                return operation(db, *args)
        try:
            async with asyncio.timeout(20), gate:
                return await joined_thread(__name__, "mens_d1_coverage_after_cancellation", query)
        except TimeoutError:
            raise web.HTTPServiceUnavailable(reason="Stored coverage is busy. Retry shortly.") from None

    async def coverage(request):
        query = request.query
        if (set(query) - {"date", "run", "game", "export", "summary"}
                or query.get("export") not in (None, "1") or query.get("summary") not in (None, "1")
                or query.get("summary") and (query.get("game") or query.get("export"))):
            raise PublicRequestError("Invalid men’s D1 coverage request.")
        try:
            day = workspace.game_day(query.get("date"))
        except workspace.SelectionError as exc:
            raise PublicRequestError(str(exc)) from None
        run_id, game = query.get("run"), query.get("game")
        if run_id is not None and not workspace.HASH.fullmatch(run_id):
            raise PublicRequestError("Select a saved run identity.")
        if game is not None and (len(game) > 512 or not game.startswith(("source:", "provider:"))):
            raise PublicRequestError("Select a coverage game identity.")
        value = await work(coverage_view, day, run_id, game)
        if query.get("summary"):
            fields = ("date", "as_of", "coverage_summary", "issue_counts", "provider_requests", "orders_submitted", "run", "runs", "analysis_run")
            value = {key: value[key] for key in fields if key in value}
        return _response(value, f"predict-mens-d1-{day}.json" if query.get("export") else None)

    async def issue(request):
        if request.query:
            raise PublicRequestError("Issue decision options belong in the JSON body.")
        try:
            body = issue_dispositions.validate(await read_json(request))
            day = workspace.game_day(body["date"])
            return _response(await work(decide_issue, day, body, read_only=False))
        except (workspace.SelectionError, issue_dispositions.InvalidDecision) as exc:
            raise PublicRequestError(str(exc)) from None
        except issue_dispositions.StaleDecision as exc:
            raise web.HTTPConflict(reason=str(exc)) from None

    async def market(request):
        query = request.query
        game, run_id, version = query.get("game"), query.get("run"), query.get("version")
        raw = query.get("raw")
        if (set(query) - {"date", "run", "game", "version", "export", "raw"} or query.get("export") not in (None, "1")
                or raw not in (None, "1") or (raw and query.get("export"))
                or version not in ("current", "saved") or not game or len(game) > 512
                or not game.startswith(("source:", "provider:")) or (version == "saved" and run_id is None)
                or (run_id is not None and not workspace.HASH.fullmatch(run_id))):
            raise PublicRequestError("Select a game and a current or saved T−10 market census.")
        try:
            day = workspace.game_day(query.get("date"))
        except workspace.SelectionError as exc:
            raise PublicRequestError(str(exc)) from None
        value = await work(market_view, day, run_id, game, version, raw is not None)
        if raw:
            metadata, body = value
            return web.Response(body=body, content_type="application/json", headers={**HEADERS,
                "Content-Disposition":f'attachment; filename="predict-original-{metadata["receipt_sha256"]}.json"'})
        name = f'predict-mens-d1-markets-{day}-{value["checkpoint_id"][:12]}.json' if query.get("export") else None
        return _response(value, name)

    async def status(request):
        from app.storage.mens_d1_coverage import read_status

        if request.query:
            raise PublicRequestError("Daily collection status takes no filters.")
        value = await work(read_status)
        return _response(dict(value, provider_requests=0, orders_submitted=0))

    async def receipt(request):
        from app.storage.mens_d1_coverage import read_receipt

        identity = request.match_info["receipt_id"]
        if request.query or not workspace.HASH.fullmatch(identity):
            raise PublicRequestError("Select an original source receipt.")
        try:
            value = await work(read_receipt, identity)
        except ValueError as exc:
            if str(exc) == "mens_d1_receipt_unknown":
                raise web.HTTPNotFound(reason="Original source receipt was not retained.") from None
            raise
        # Attach JSON so provider markup never executes in the owner origin.
        return _response(value, f"predict-source-{identity[:12]}.json")

    async def provider_receipt(request):
        identity = request.match_info["result_id"]
        if request.query or not workspace.HASH.fullmatch(identity):
            raise PublicRequestError("Select a retained provider result.")
        metadata, body = await work(_provider_result_receipt, identity)
        return web.Response(body=body, content_type="application/json", headers={**HEADERS,
            "Content-Disposition":f'attachment; filename="predict-original-{metadata["receipt_sha256"]}.json"'})

    app.router.add_get(BASE, coverage)
    if not read_only:
        app.router.add_post(BASE + "/issues", issue)
    app.router.add_get(BASE + "/market-census", market)
    app.router.add_get(BASE + "/status", status)
    app.router.add_get(BASE + "/receipts/{receipt_id}", receipt)
    app.router.add_get(BASE + "/provider-results/{result_id}", provider_receipt)
