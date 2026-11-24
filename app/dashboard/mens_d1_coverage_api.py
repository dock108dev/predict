"""Read-only daily coverage assembled from retained source and checkpoint evidence."""

import asyncio
from collections import Counter
from urllib.parse import urlencode

from aiohttp import web

from app.owned_work import joined_thread
from app.research import experiment, market_census, paper_evidence, workspace
from app.storage.store import connect, encoded, stamp
from .local_security import HEADERS, PublicRequestError
from .pipeline import serial


BASE = "/api/workspace/mens-d1"


def _saved(db, day, run_id):
    runs = list(db.execute("""SELECT r.id,r.game_date,r.definition_version,r.observed_at,r.summary,
               d.payload->>'designation' designation,d.payload#>>'{policy,scope}' scope,
               d.payload#>>'{policy,minimum_ev}' minimum_ev
        FROM public.research_workspace_run r JOIN public.research_workspace_definition d
        ON d.version=r.definition_version WHERE r.game_date=%s::date
        ORDER BY r.observed_at DESC,r.id""", (day,)))
    selected = next((row for row in runs if row["id"] == run_id), None) if run_id else next(
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


def _capture(row, as_of):
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
                market_summary=market_census.summarize_coverage(row["checkpoint_coverage"]))


def _provider_row(row):
    event = row["event"]
    return dict(provider_event_id=row["source_event_id"], title=event.get("title"),
                starts_at=event["starts_at"], match_state="provider_only",
                match_reason="No reviewed daily-slate link exists for this retained odds-provider game.")


def _provider_result_disposition(game, checkpoint, as_of):
    if game.get("source_game_id") or game.get("result_state") == "provider_final":
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
    return f'source:{row["source_game_id"]}' if row.get("source_game_id") else f'provider:{row["provider_event_id"]}'


def _saved_game(game, run, tickets):
    if game is None:
        return None
    base = f'/api/research/workspace/runs/{run["id"]}/evidence/{game["game_id"]}'
    qualifying = {variant:len(rows) for variant, rows in tickets.items()} if game["status"] in ("captured", "reconstructed") else None
    return dict(**game, qualifying=qualifying,
                market_summary=market_census.summarize_coverage(game.get("coverage")),
                evidence_export=base + "?export=1", original_response_export=base + "?raw=1")


def _facets(row, in_scope):
    scope, match = row.get("scope_state"), row.get("match_state")
    source = row.get("source_game_id") is not None
    facets = []
    if source and not row.get("removed") and not row.get("result_only") and row.get("gender") in ("men", "male", "mens", "m"):
        facets.append("source_mens")
    if scope in ("eligible", "excluded", "unresolved") and source:
        facets.append({"eligible":"expected","excluded":"excluded","unresolved":"membership_unresolved"}[scope])
    retained = row.get("retained_scope") or {}
    if retained.get("state") in ("eligible", "excluded", "unresolved"):
        facets.append("retained_" + retained["state"])
    provider_scope = (row.get("provider_membership") or {}).get("state")
    if provider_scope in ("eligible", "excluded", "unresolved"):
        facets.append("provider_scope_" + provider_scope)
    if match in ("source_only", "provider_only", "provider_conflict", "identity_conflict", "schedule_conflict", "site_conflict", "no_market", "result_only"):
        facets.append(match)
    if scope == "eligible" and match in ("matched", "no_market"):
        facets.append("matched")
    capture, saved = row["capture"], row.get("saved") or {}
    # Include the original task disposition even if a later calculation recovered the response.
    if in_scope:
        if capture.get("frozen_id") or saved.get("status") == "captured":
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
        if (saved.get("qualifying") or {}).get("all_venues") == 0:
            facets.append("zero_qualifiers")
        if any(reason.startswith("reference_") and count for reason, count in (saved.get("exclusions") or {}).items()):
            facets.append("reference_gaps")
    for variant in ("best_venue", "all_venues"):
        if (saved.get("qualifying") or {}).get(variant, 0):
            facets.append("qualifying_" + variant)
    if scope == "eligible":
        result = row.get("result_state")
        facets.append({"final":"final", "conflicting":"conflicting", "pending":"result_pending"}.get(result, "result_unresolved"))
    if (row.get("provider_results") or [{}])[0].get("status") == "final":
        facets.append("provider_final")
    if row.get("result_state") in ("provider_pending", "provider_result_unresolved"):
        facets.append(row["result_state"])
    return facets


def _coverage_summary(value, games, run, report):
    provider = [game for game in games if (game.get("provider_membership") or {}).get("state") == "eligible"]
    counts = value.get("counts", {})
    expected = counts.get("expected")
    source_eligible = [game for game in games if "expected" in game["facets"]]
    current = source_eligible if expected is not None else provider
    saved = report.get("games", [])
    captured = [game for game in saved if game["status"] in ("captured", "reconstructed")]
    observed_counts = [game.get("observed_offer_count") for game in captured]
    evaluated_counts = [game.get("evaluated_offers") for game in captured]
    exclusions = Counter()
    for game in captured:
        exclusions.update(game.get("exclusions") or {})
    reference = {reason: amount for reason, amount in exclusions.items() if reason.startswith("reference_")}
    states = Counter(game["capture"]["state"] for game in current)
    retrieval = Counter(summary["retrieval_state"] for game in captured
                        if (summary := market_census.summarize_coverage(game.get("coverage"))))
    retrieval["unknown_completeness"] += len(captured) - sum(retrieval.values())
    return dict(
        population=dict(as_of=value["as_of"], observed_at=value.get("source_observed_at"),
                        revision=value.get("population_revision"), expected_games=expected,
                        source_identity=value.get("source"), source_mode=value.get("source_mode"),
                        source_corroborated_additional_eligible=counts.get("source_corroborated_additional_eligible"),
                        source_url=value.get("source_url"), source_eligible_games=counts.get("source_eligible"),
                        source_returned_mens_games=counts.get("source_returned_mens_games"),
                        source_eligible_known_before_tminus10=sum(game.get("known_before_tminus10") is True
                                                                  for game in source_eligible) if value.get("population_revision") else None,
                        matched_games=sum("matched" in game["facets"] for game in current) if expected is not None else None,
                        provider_known_games=len(provider)),
        capture=dict(as_of=value["as_of"], current_denominator=len(current),
                     population_basis="source" if expected is not None else "provider_known",
                     current_frozen=states["captured"],
                     current_upcoming=sum(states[state] for state in ("upcoming", "due", "claimed")),
                     current_misses=states["missed"], current_refusals=states["refused"],
                     saved_at=report.get("as_of"), saved_denominator=len(saved) if run else None,
                     saved_frozen=sum(game["status"] == "captured" for game in captured),
                     saved_reconstructed=sum(game["status"] == "reconstructed" for game in captured)),
        markets=dict(as_of=report.get("as_of"), evidence_games=len(captured) if run else None,
                     saved_retrieval_states=dict(retrieval), current_evidence_games=states["captured"],
                     current_as_of=value["as_of"],
                     observed_offer_games=sum(n is not None for n in observed_counts),
                     observed_offers=sum(observed_counts) if captured and None not in observed_counts else None),
        reference=dict(as_of=report.get("as_of"), observed_offers=sum(observed_counts) if captured and None not in observed_counts else None,
                       evaluated_offers=sum(evaluated_counts) if captured and None not in evaluated_counts else None,
                       reference_gaps=sum(reference.values()) if captured else None,
                       exclusions=dict(exclusions), reference_exclusions=reference),
        trade=dict(as_of=report.get("as_of"), variants={name: paper_evidence.clock_counts(portfolio["tickets"])
                   for name, portfolio in report.get("portfolios", {}).items()}),
    )


def coverage_view(db, day, run_id, selection):
    from app.storage.mens_d1_coverage import read_coverage

    value = read_coverage(db, day)
    runs, run, report = _saved(db, day, run_id)
    population = report.get("population") or {}
    retained_sources = {row["source_game_id"]:row for row in population.get("games", []) if row.get("source_game_id")}
    retained_providers = {row["provider_event_id"]:row for row in population.get("games", []) if row.get("provider_event_id")}
    saved_games = {game["game_id"]:game for game in report.get("games", [])}
    tickets = {variant:{} for variant in report.get("portfolios", {})}
    for variant, portfolio in report.get("portfolios", {}).items():
        for ticket in portfolio["tickets"]:
            tickets[variant].setdefault(ticket["game_id"], []).append(ticket)
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
    games.extend(_provider_row(row) for event_id,row in stored.items() if event_id not in attached)
    for game in games:
        if "retained_scope" in game:
            game["provider_membership"] = game.pop("retained_scope")
        game["id"] = _row_id(game)
        row = stored.get(game.get("provider_event_id"))
        _provider_result_disposition(game, row, value["as_of"])
        retained = retained_sources.get(game.get("source_game_id"))
        provider_scope = retained_providers.get(game.get("provider_event_id"))
        if retained is None and provider_scope and provider_scope.get("source_game_id") not in source_ids:
            retained = provider_scope
        if retained:
            game["retained_scope"] = dict(state=retained["scope_state"], reason=retained["scope_reason"], teams=retained.get("teams"))
        game["capture"] = _capture(row, value["as_of"])
        game["saved"] = None
        saved_game_id = retained.get("game_id") if retained else row["id"] if row and not population else None
        saved = saved_games.get(saved_game_id)
        if saved:
            matches = {name:items.get(saved_game_id, []) for name,items in tickets.items()}
            game["saved"] = _saved_game(saved, run, matches)
            if game["id"] == selection:
                game["ticket_clocks"] = {name:[{key:ticket.get(key) for key in ("id","label","venue","times")}
                    for ticket in items] for name,items in matches.items()}
        if row:
            game["title"] = game.get("title") or row["event"].get("title")
            game_id = row["id"]
            if game["id"] == selection:
                revision = experiment._revision(db, row)
                query = urlencode(dict(id=game_id, revision=revision))
                game["checkpoint_inspect"] = '/data?evidence=checkpoints&' + query
                game["checkpoint_export"] = '/api/research/experiment?export=1&' + query
        in_scope = (game.get("scope_state") == "eligible"
                    or (game.get("provider_membership") or {}).get("state") == "eligible"
                    or bool(retained and retained["scope_state"] == "eligible"))
        game["facets"] = _facets(game, in_scope)
    facets = Counter(facet for game in games for facet in game["facets"])
    evaluated = [game["saved"]["evaluated_offers"] for game in games if "evaluated" in game["facets"]]
    offers = {"evaluated":sum(evaluated) if evaluated else None}
    for variant in tickets:
        facet = "qualifying_" + variant
        offers[facet] = sum(game["saved"]["qualifying"][variant] for game in games if facet in game["facets"])
    games.sort(key=lambda row:((row.get("schedule") or {}).get("starts_at") or row.get("starts_at") or "~", row["id"]))
    return {**{key:val for key,val in value.items() if key not in ("games","provider_only")},
        "games":games,"facets":dict(facets),"offer_counts":offers,
        "run":run,"runs":runs,"run_population":report.get("population"),
        "coverage_summary":_coverage_summary(value, games, run, report),
        "provider_requests":0,"orders_submitted":0}


def market_view(db, day, run_id, game_id, version, raw=False):
    value = coverage_view(db, day, run_id, None)
    game = next((row for row in value["games"] if row["id"] == game_id), None)
    if game is None:
        raise web.HTTPNotFound(reason="The selected game is unavailable on this date.")
    if version == "saved":
        checkpoint = (game.get("saved") or {}).get("checkpoint_id")
    else:
        checkpoint = game["capture"].get("frozen_id")
    if not checkpoint:
        raise web.HTTPNotFound(reason="There is no retained T−10 market evidence for this selection.")
    minimum = (value.get("run") or {}).get("minimum_ev") if version == "saved" else None
    census = market_census.for_checkpoint(db, checkpoint, include_rows=not raw, minimum=minimum or "1/25")
    if raw:
        from app.collection.original_receipts import read

        original = census["original_response"]
        if original["state"] != "retained":
            raise web.HTTPNotFound(reason="The original odds response is unavailable for this capture.")
        return read(original["id"])
    saved = game.get("saved") or {}
    return dict(census, date=day, game=game_id, title=game.get("title"), basis=version,
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


def mount(app):
    gate = asyncio.Semaphore(2)

    async def read(operation, *args):
        def query():
            with connect() as db, db.transaction():
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
        value = await read(coverage_view, day, run_id, game)
        if query.get("summary"):
            value = {key: value[key] for key in ("date", "as_of", "coverage_summary", "provider_requests", "orders_submitted")}
        return _response(value, f"predict-mens-d1-{day}.json" if query.get("export") else None)

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
        value = await read(market_view, day, run_id, game, version, raw is not None)
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
        value = await read(read_status)
        return _response(dict(value, provider_requests=0, orders_submitted=0))

    async def receipt(request):
        from app.storage.mens_d1_coverage import read_receipt

        identity = request.match_info["receipt_id"]
        if request.query or not workspace.HASH.fullmatch(identity):
            raise PublicRequestError("Select an original source receipt.")
        try:
            value = await read(read_receipt, identity)
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
        metadata, body = await read(_provider_result_receipt, identity)
        return web.Response(body=body, content_type="application/json", headers={**HEADERS,
            "Content-Disposition":f'attachment; filename="predict-original-{metadata["receipt_sha256"]}.json"'})

    app.router.add_get(BASE, coverage)
    app.router.add_get(BASE + "/market-census", market)
    app.router.add_get(BASE + "/status", status)
    app.router.add_get(BASE + "/receipts/{receipt_id}", receipt)
    app.router.add_get(BASE + "/provider-results/{result_id}", provider_receipt)
