"""Sporting-result reports over frozen paper selections and retained evidence."""

from collections import Counter, defaultdict
from datetime import date
from fractions import Fraction
from functools import lru_cache
import json

from app.collection import original_receipts
from app.collection.sgo_nhl_scoring import BASIS as NHL_SCORE_BASIS, nhl_scoring
from app.storage import mens_d1_coverage as d1
from app.storage.mens_d1_occurrences import occurrence_ledger
from app.storage.store import hashed, stamp
from . import experiment, paper, paper_depth, records, workspace

VERSION = "paper-sporting-grades-1"
NHL_VERSION = "paper-sporting-grades-nhl-2"
SCHEMA = "predict-paper-results-1"
VARIANTS = ("best_venue", "all_venues")
RESOLVED = frozenset(("win", "loss", "push", "void"))
# SportsGameOdds documents the physical game-score basis at
# https://sportsgameodds.com/docs/data-types/periods. Venue terms may differ.
SPORT_SCORING = {
    "NCAAB": "full-game points including overtime",
    "NBA": "full-game points including overtime",
    "NCAAF": "full-game points including overtime",
    "NFL": "full-game points including overtime",
    "MLB": "full-game runs including extra innings",
    "NHL": "the full-game winner including a shootout",
}
CAPTURED = frozenset(("captured", "reconstructed"))
EXCEPTION = frozenset(("cancelled", "postponed", "removed"))
SGO = "sportsgameodds"
BASE = "/api/workspace/mens-d1"
SGO_ORIGINAL = "/api/research/workspace/result-evidence"
ODD_NAMES = dict(moneyline="ml", spread="sp", total="ou")
SIDES = dict(moneyline=("home", "away"), spread=("home", "away"), total=("over", "under"))
NHL_LINE_FAMILIES = frozenset(("spread", "total"))
# The published full-game rules for these venues count one goal for a shootout win.
# The paper quotes remain SGO observations, without venue settlement confirmation.
NHL_LINE_VENUES = frozenset(("novig", "polymarket_us"))


def _nhl_line_games(report):
    nhl_only = report["policy"].get("league") == "NHL"
    game_ids = {game["game_id"] for game in report.get("games", ()) if game.get("league") == "NHL"}
    return {ticket["game_id"] for ticket in report["portfolios"]["all_venues"]["tickets"]
            if (nhl_only or ticket["game_id"] in game_ids) and
            (ticket.get("family") or ticket["identity"]["family"]) in NHL_LINE_FAMILIES}


def _scores(teams):
    result = {}
    for team in teams:
        identity, score = team.get("canonical_id"), team.get("score")
        if not identity or score is None or isinstance(score, bool) or identity in result:
            return {}
        try:
            value = Fraction(score)
        except (TypeError, ValueError, ZeroDivisionError):
            return {}
        if value.denominator != 1 or value < 0:
            return {}
        result[identity] = int(value)
    return result if len(result) == 2 else {}


def _latest(items, publisher):
    def recency(item):
        return (stamp(item.get("observed_at") or item["recorded_at"]),
                stamp(item["recorded_at"]), item["id"])

    unique = {}
    for item in sorted(items, key=recency, reverse=True):
        unique.setdefault(item[publisher], item)
    return list(unique.values())


def _clock_match(left, right):
    return bool(left and right and stamp(left) == stamp(right))


def _source_evidence(occurrence, frozen_start, receipt_hashes):
    if not occurrence:
        return []
    schedule = occurrence["occurrence_schedule"]
    starts_at = frozen_start or schedule.get("starts_at")
    verified = _clock_match(schedule.get("starts_at"), starts_at)
    # Exact retained source occurrence, or canonical pair plus a provider/official
    # clock binding. A disputed same-date candidate alone cannot grade a ticket.
    if not verified:
        return []
    current = {}
    for item in occurrence.get("source_records", ()):
        current.setdefault((item["source"], item["kind"]), item)
    heads = [item for (source, kind), item in current.items()
             if kind != "schedule" or (source, "results") not in current]
    evidence = []
    for item in heads:
        if item["status"] != "final" and item["status"] not in EXCEPTION:
            continue
        receipt = item["receipt_id"]
        evidence.append(dict(id=item["id"], revision=item["revision"], source=item["source"],
            source_game_id=item["source_game_id"], state=item["status"], scores=_scores(item["teams"]),
            overtime_periods=item.get("overtime_periods"), observed_at=item["observed_at"],
            recorded_at=item["recorded_at"], published_at=item.get("published_at"),
            receipt_id=receipt, receipt_sha256=receipt_hashes.get(receipt),
            url=f"{BASE}/receipts/{receipt}"))
    for item in _latest(occurrence.get("official_source_evidence", ()), "publisher"):
        if item["status"] != "final":
            continue
        evidence.append(dict(id=item["id"], source=item["publisher"], source_game_id=item["source_game_id"],
            state="final", scores=_scores(item["teams"]), overtime_periods=item.get("overtime_periods"),
            observed_at=item["observed_at"], recorded_at=item["recorded_at"],
            receipt_sha256=item.get("artifact_sha256"), url=item.get("source_url")))
    return evidence


def _sgo_evidence(game, known, roles, identity, data, recorded_at, url=None):
    source = data.get("source_result") or {}
    if (source.get("source"), source.get("event_id"), source.get("league")) != (
            SGO, known["source_event_id"], known["league"]):
        return None
    if not source.get("receipt_sha256") or not _clock_match(source.get("starts_at"), known["starts_at"]):
        return None
    if game.get("schedule_id") and data.get("schedule_id") and game["schedule_id"] != data["schedule_id"]:
        return None
    reason = source.get("reason")
    observed_at = data.get("observed_at") or source.get("received_at")
    if not observed_at or (reason != "sporting_result_cancelled"
                           and stamp(observed_at) < stamp(known["starts_at"])):
        return None
    same_orientation = all(source.get(role) == known.get(role) for role in ("home", "away"))
    if not same_orientation and reason != "sporting_result_canonical_role_mapping_changed":
        return None
    state = ("conflicting" if reason and ("conflict" in reason or "role_mapping" in reason)
             else "cancelled" if reason == "sporting_result_cancelled"
             else "final" if data.get("final") and data.get("result") == "completed"
             else "unresolved")
    scores = _scores([dict(canonical_id=roles.get(role), score=data.get(role + "_score"))
                      for role in ("home", "away")]) if state == "final" else {}
    return dict(id=identity, source=SGO, source_game_id=source["event_id"], state=state, scores=scores,
                observed_at=observed_at,
                recorded_at=recorded_at, published_at=data.get("published_at"),
                receipt_sha256=source["receipt_sha256"], url=url)


def _original_events(digest):
    body = original_receipts.read_by_digest(digest)
    if body is None:
        return ()
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        return ()
    events = payload.get("data") if isinstance(payload, dict) else None
    return tuple(event for event in events if isinstance(event, dict)) if isinstance(events, list) else ()


def _nhl_result_scoring(known, result, source, originals):
    roles = ("home", "away")
    final_scores = {role: result["scores"].get(known[role]) for role in roles}
    source = source.get("source_result") or {}
    stored = source.get("nhl_scoring")
    if (isinstance(stored, dict) and stored.get("basis") == NHL_SCORE_BASIS and
            stored.get("scores") == final_scores and stored.get("decision") in ("regulation", "overtime", "shootout")):
        return stored
    event_id = result["source_game_id"]
    events = [event for event in originals(result["receipt_sha256"]) if event.get("eventID") == event_id]
    if len(events) != 1:
        return None
    return nhl_scoring(events[0], event_id=event_id, starts_at=known["starts_at"],
        team_ids={role: source.get(f"{role}_provider_id") for role in roles},
        final_scores=final_scores)


def _native_game(known, occurrence):
    provider = (occurrence or {}).get("provider_evidence") or {}
    teams = {team["role"]: team for team in provider.get("teams", ())}
    roles, names = {}, {}
    away, separator, home = known.get("title", "").partition(" at ")
    labels = dict(away=away, home=home) if separator else {}
    for role in ("home", "away"):
        team = teams.get(role, {})
        if (team.get("original_canonical_id") or team.get("canonical_id")) == known.get(role):
            roles[role] = team.get("canonical_id") or known.get(role)
        else:
            roles[role] = known.get(role)
        names[role] = labels.get(role) or team.get("name") or roles[role]
    return roles, names


def _game_result(roles, names, evidence, unavailable=None):
    ids = {roles.get("home"), roles.get("away")}
    finals = [item for item in evidence if item["state"] == "final" and set(item["scores"]) == ids]
    scores = finals[0]["scores"] if finals else {}
    state, reason = "pending", "final_not_yet_retained"
    if any(item["state"] == "conflicting" for item in evidence) or any(
            item["scores"] != scores for item in finals[1:]) or (finals and any(
                item["state"] in EXCEPTION for item in evidence)):
        state, reason = "conflicting", "retained_result_evidence_disagrees"
    elif unavailable:
        state, reason = unavailable
    elif any(item["state"] == "final" and item["scores"] and set(item["scores"]) != ids for item in evidence):
        state, reason = "unresolved", "retained_result_participants_disagree"
    elif finals:
        state, reason = "final", "retained_final_score"
    elif evidence:
        state = evidence[0]["state"] if evidence[0]["state"] in EXCEPTION else "unresolved"
        reason = "retained_" + state if state in EXCEPTION else "retained_final_score_or_participant_binding_unavailable"
    result = dict(state=state, reason=reason, home=names.get("home"), away=names.get("away"),
                home_id=roles.get("home"), away_id=roles.get("away"),
                home_score=scores.get(roles.get("home")) if state == "final" else None,
                away_score=scores.get(roles.get("away")) if state == "final" else None,
                overtime_periods=next((item["overtime_periods"] for item in finals
                                      if item.get("overtime_periods") is not None), None),
                observed_at=max((item["observed_at"] for item in evidence if item.get("observed_at")),
                                key=stamp, default=None),
                evidence=evidence)
    if state == "final" and (scoring := finals[0].get("nhl_scoring")):
        result["nhl_scoring"] = scoring
    return result


def _game_context(game, source, known, current, occurrence, evidence):
    roles, names = _native_game(known, occurrence)
    if not known:
        sources = {t.get("canonical_id"): t for t in (occurrence or {}).get("teams", ())}
        for team in sources.values():
            role = team.get("display_role") or team.get("role")
            if role in ("home", "away"):
                roles[role], names[role] = team.get("canonical_id"), team.get("name")
    unavailable = None
    current_event = current.get("event") or {}
    if (current_event.get("status") or {}).get("cancelled") is True:
        unavailable = ("cancelled", "retained_cancelled")
    elif known and current_event and not _clock_match(known["starts_at"], current_event["starts_at"]):
        unavailable = ("unresolved", "frozen_occurrence_schedule_changed")
    elif occurrence and occurrence.get("day_applicability") == "other_date":
        unavailable = ("unresolved", "frozen_occurrence_schedule_changed")
    # A report always preserves the original game identity. New bindings may
    # supply the first canonical occurrence ID for a previously unscoped run.
    occurrence_id = (game.get("occurrence_id") or source.get("occurrence_id")
                     or (occurrence or {}).get("occurrence_id"))
    if not occurrence_id and known.get("source_event_id"):
        occurrence_id = f"provider:{known['source_event_id']}"
    result = dict(game_id=game["game_id"], occurrence_id=occurrence_id, title=game.get("title"),
                starts_at=game.get("starts_at"), capture_status=game["status"], capture_reason=game.get("reason"),
                checkpoint_id=game.get("checkpoint_id"), schedule_id=game.get("schedule_id"),
                result=_game_result(roles, names, evidence, unavailable))
    if "selection_audit" in game:
        result["selection_audit"] = game["selection_audit"]
    if "league" in game:
        result["league"] = game["league"]
    return result


def _lookup_games(db, run):
    report = run["payload"]["report"]
    games = report["games"]
    nhl_line_games = _nhl_line_games(report)
    originals = lru_cache(maxsize=2)(_original_events)
    day = date.fromisoformat(report["date"])
    source_games = {row["game_id"]: row for row in (report.get("population") or {}).get("games", ())
                    if row.get("game_id")}
    touched = db.execute("""SELECT id,event,schedule_id,outcome_id FROM public.ev_experiment_game
        WHERE id=ANY(%s)""", ([g["game_id"] for g in games],))
    tracked = {row["id"]: row for row in touched}
    roots = [g["schedule_id"] for g in games if g.get("schedule_id")]
    roots += [g["outcome_id"] for g in tracked.values() if g.get("outcome_id")]
    retained = experiment._closure(db, roots)
    at = db.execute("SELECT transaction_timestamp() AS at").fetchone()["at"]
    occurrences = []
    if games and (report["policy"].get("league") == "NCAAB" or
                  any(game.get("league") == "NCAAB" for game in games)):
        providers = d1._providers(db, day, at, neighbors=True)
        occurrences = occurrence_ledger(db, day, at, providers, include_history=False)
    by_occurrence = {occurrence["occurrence_id"]: occurrence for occurrence in occurrences}
    by_provider = {occurrence["provider_event_id"]: occurrence for occurrence in occurrences
                   if occurrence.get("provider_event_id")}
    receipt_ids = sorted({row["receipt_id"] for occurrence in occurrences
                          for row in occurrence.get("source_records", ())})
    receipt_hashes = {row["id"]: row["body_sha256"] for row in db.execute(
        "SELECT id,body_sha256 FROM public.mens_d1_receipt WHERE id=ANY(%s)", (receipt_ids,))}
    native_ids = [row["event"]["source_event_id"] for row in tracked.values()]
    legacy = defaultdict(list)
    for item in db.execute("""SELECT id,payload,recorded_at FROM public.research_record
        WHERE kind='sporting' AND public.paper_result_sgo_event(payload)=ANY(%s)
        ORDER BY recorded_at DESC,id""", (native_ids,)):
        source = (item["payload"].get("data") or {}).get("source_result") or item["payload"].get("source_result") or {}
        if source.get("source") == SGO:
            legacy[source["event_id"]].append(item)
    for game in games:
        current = tracked.get(game["game_id"], {})
        frozen = retained.get(game.get("schedule_id"))
        known = experiment._value(frozen, retained)["event"] if frozen else {}
        saved = source_games.get(game["game_id"], {})
        occurrence_id = game.get("occurrence_id") or saved.get("occurrence_id")
        native_id = known.get("source_event_id") or saved.get("provider_event_id")
        occurrence = by_provider.get(native_id) if native_id else by_occurrence.get(occurrence_id)
        if occurrence and not native_id and _scores([dict(t, score=0) for t in saved.get("teams", ())]) != _scores(
                [dict(t, score=0) for t in occurrence["teams"]]):
            occurrence = None
        roles, _ = _native_game(known, occurrence)
        evidence = _source_evidence(occurrence, game.get("starts_at"), receipt_hashes)
        candidates = []
        outcome = retained.get(current.get("outcome_id"))
        if known and outcome:
            value = experiment._value(outcome, retained)
            data = dict(value["data"], schedule_id=value.get("schedule_id"))
            candidates.append((_sgo_evidence(game, known, roles, outcome["id"], data,
                outcome["recorded_at"].isoformat(), f"{SGO_ORIGINAL}/{outcome['id']}"), data))
        for item in legacy[native_id] if known else ():
            data = item["payload"].get("data")
            if not data:
                source = item["payload"]["source_result"]
                data = dict(source_result=source, final=source.get("final"),
                    result=source.get("result") or ("completed" if source.get("final") else "unresolved"),
                    home_score=source.get("home_score"), away_score=source.get("away_score"))
            if not data.get("final") and (data.get("source_result") or {}).get("reason") == "sporting_result_not_final":
                continue
            candidates.append((_sgo_evidence(game, known, roles, item["id"], data, item["recorded_at"].isoformat(),
                f"{SGO_ORIGINAL}/{item['id']}"), data))
        # When two acquisition lanes saved the same provider receipt, prefer the
        # outcome record because it supplies the original-download route.
        unique = {}
        for item, data in candidates:
            if item is not None:
                unique.setdefault(item["receipt_sha256"], (item, data))
        for item in _latest((item for item, _ in unique.values()), "source"):
            if game["game_id"] in nhl_line_games and known["league"] == "NHL" and item["state"] == "final":
                scoring = _nhl_result_scoring(known, item, unique[item["receipt_sha256"]][1], originals)
                if scoring:
                    item["nhl_scoring"] = scoring
            evidence.append(item)
        context = _game_context(game, saved, known, current, occurrence, evidence)
        yield context, known


def _grading_rule(ticket, calculation, known):
    identity = ticket["identity"]
    family, period, side = (identity[k] for k in ("family", "period", "outcome"))
    settlement = identity.get("settlement") or {}
    scope = settlement.get("scoring_scope") or {}
    if period != "full_game":
        return "unsupported_period", "Only a retained full-game score can be used for this ticket."
    if family not in SIDES or side not in SIDES[family]:
        return "unsupported_market", "The retained binary scoring adapter does not recognize this selection."
    if not known:
        return "frozen_contract_binding_unverified", "The original occurrence and participant binding are unavailable."
    league = known["league"]
    if league not in SPORT_SCORING:
        return "unsupported_sport_scoring", "No verified full-game scoring basis is available for this sport."
    if league == "NHL" and family in NHL_LINE_FAMILIES:
        venue = ticket["venue"]
        depth = ticket.get("depth") or {}
        depth_settlement = depth.get("settlement") or {}
        verified_depth = (depth.get("version") == (calculation.get("sizing") or {}).get("execution_rule")
                          == paper_depth.FIXED_PROFIT_VERSION and depth.get("eligible") is True
                          and depth_settlement.get("available") is True
                          and depth_settlement.get("overtime") == "included"
                          and depth_settlement.get("shootout") == "official_final_score"
                          and depth_settlement.get("shootout_count") == "one_goal_to_winning_team")
        if ((venue not in NHL_LINE_VENUES and not verified_depth) or venue != identity.get("venue", venue) or
                venue != calculation.get("venue", venue)):
            return "unsupported_scoring_terms", "A full-game scoring rule for this NHL venue and market is unavailable."
    if scope.get("conflicts") or settlement.get("explicit") or (
            "excluded" in (*settlement.get("overtime_evidence", []), scope.get("overtime"))):
        return "unsupported_scoring_terms", "The retained market terms conflict with a normal full-game score."
    source = calculation.get("source") or {}
    odd_participant = "all" if family == "total" else side
    expected_odd = f"points-{odd_participant}-game-{ODD_NAMES[family]}-{side}"
    if (identity.get("provider"), settlement.get("rules"), settlement.get("result_policy"),
            settlement.get("outcome_cardinality"), source.get("provider"), source.get("native_outcome_id")) != (
            SGO, "sportsgameodds-unverified-1", f"sportsgameodds-unverified-1:{family}", 2, SGO, expected_odd):
        return "unsupported_scoring_terms", "The frozen source does not establish a modeled full-game scoring adapter."
    selection = calculation.get("selection") or {}
    try:
        line, selected_line = identity["line"], selection.get("signed_line")
        quote_line = source.get("native_line")
        same_line = selected_line is quote_line is None if line is None else (
            Fraction(line) == Fraction(selected_line) == Fraction(quote_line))
    except (ValueError, ZeroDivisionError, TypeError):
        same_line = False
    if (identity.get("event") != ticket["game_id"] or source.get("native_event_id") != known["source_event_id"]
            or calculation.get("game_key") != ticket["game_id"] or calculation.get("league") != league
            or (calculation.get("family"), calculation.get("period"), calculation.get("side")) != (family, period, side)
            or not _clock_match(calculation.get("kickoff"), known["starts_at"])
            or (side in ("home", "away") and selection.get("participant") != known[side]) or not same_line):
        return "frozen_contract_binding_unverified", "Frozen occurrence, participant, side or exact line could not be verified."
    return None, None


def _grade(ticket, calculation, known, result, commitment):
    if result["state"] == "conflicting":
        return "conflicting", result["reason"], "Retained result evidence contains conflicting scores or participant roles.", None
    if result["state"] in EXCEPTION:
        return "unsupported", "void_refund_unverified", "The occurrence did not complete as scheduled. A recorded void or refund cashflow is unavailable.", None
    reason, explanation = _grading_rule(ticket, calculation, known)
    if reason:
        return "unsupported", reason, explanation, None
    if result["state"] == "pending":
        return "pending", result["reason"], "Waiting for a retained final score.", None
    if result["state"] != "final":
        return "unresolved", result["reason"], "The final score could not be bound to the frozen occurrence and participants.", None
    identity = ticket["identity"]
    family, line, side = identity["family"], identity["line"], identity["outcome"]
    basis = SPORT_SCORING[known["league"]]
    scores = {role: result[role + "_score"] for role in ("home", "away")}
    if known["league"] == "NHL" and family in NHL_LINE_FAMILIES:
        scoring = result.get("nhl_scoring") or {}
        if scoring.get("basis") != NHL_SCORE_BASIS or scoring.get("scores") != scores:
            return "unsupported", "shootout_score_basis_unverified", "Retained NHL periods do not verify the official full-game score.", None
        basis = "the official NHL full-game score"
        if scoring["decision"] == "shootout":
            basis += " including one goal for the shootout winner"
    if family == "spread" and side == "away":
        line = str(-Fraction(line))
    winner, reason = records.resolved_side(dict(family=family, period=identity["period"], line=line),
        dict(final=True, result="completed", home_score=scores["home"], away_score=scores["away"]))
    if reason == "tie_or_push_outside_decisive_conditioning":
        return "unsupported", "push_refund_unverified", "The full-game score ties the modeled selection. A recorded push or refund cashflow is unavailable.", None
    if reason:
        return "unsupported", reason, "The final score cannot grade the saved market and line.", None
    state = "win" if side == winner else "loss"
    fee = calculation.get("fee") or {}
    try:
        if (Fraction(fee["committed_usd"]) != commitment
                or Fraction(calculation["raw"]["net_ev"]) != Fraction(ticket["ev"])
                or Fraction(calculation["reference"]["probability"]) != Fraction(ticket["probability"])):
            raise ValueError("frozen_calculation_mismatch")
        returned = Fraction(fee["cashflows"][state]["net_receipt_usd"])
        if returned < 0:
            raise ValueError("negative_modeled_receipt")
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return "unresolved", "recorded_cashflow_unverified", "The original price model or grade cashflow could not be verified.", None
    score = f"{result['away']} {result['away_score']}, {result['home']} {result['home_score']}"
    selection = f"{ticket['label']} ({side} {identity['line']})" if line is not None else ticket["label"]
    winner_name = (result.get(winner) or winner)
    explanation = f"{score}. Using {basis}, the {family} outcome was {winner_name}. {selection} grades as a {state}."
    return state, "decisive_full_game_score", explanation, returned


def _money(row, **fields):
    for key, value in fields.items():
        key = key.removesuffix("_")
        row[key + "_usd"] = paper.money(value) if value is not None else None
        row[key + "_exact_usd"] = str(value) if value is not None else None
    return row


def _ticket(run_id, ticket, witness, game, known):
    calculation = workspace._sized_calculation(witness) if witness else {}
    stake = Fraction(ticket["cash_commitment_usd"])
    expected = stake * Fraction(ticket["ev"])
    result = game["result"]
    state, reason, explanation, returned = _grade(ticket, calculation, known, result, stake)
    evidence_ids = [item["id"] for item in result["evidence"]]
    acquisition = calculation.get("acquisition") or {}
    quote_hashes = sorted({item["receipt_sha256"] for item in acquisition.get("required_inputs", ())
                           if item.get("receipt_sha256")})
    version = (NHL_VERSION if known.get("league") == "NHL" and
               ticket["identity"]["family"] in NHL_LINE_FAMILIES else VERSION)
    grade = dict(id=hashed([version, run_id, ticket["id"], game["occurrence_id"], result]),
                 state=state, reason=reason, explanation=explanation, evidence_ids=evidence_ids)
    row = {key: ticket.get(key) for key in ("id", "game_id", "label", "venue", "posted_odds", "probability",
           "ev", "family", "period", "side", "line", "exact_bet_id", "equivalent_bet_id", "checkpoint_id",
           "decision_at", "times")}
    if "sizing" in ticket:
        row.update(frozen_quote_id=ticket["frozen_quote_id"], sizing=ticket["sizing"])
    if "portfolio_selection" in ticket:
        row["portfolio_selection"] = ticket["portfolio_selection"]
    if "depth" in ticket:
        row["depth"] = ticket["depth"]
    row.update(grade=grade, occurrence_id=game["occurrence_id"], quote_receipt_sha256=quote_hashes,
               capture_origin="reconstructed" if game["capture_status"] == "reconstructed" else "frozen")
    return _money(row, stake=stake, expected_profit=expected, return_=returned,
                  pnl=returned-stake if returned is not None else None)


def _summary(tickets):
    states = Counter(t["grade"]["state"] for t in tickets)
    resolved = [t for t in tickets if t["grade"]["state"] in RESOLVED]
    stake = sum((Fraction(t["stake_exact_usd"]) for t in tickets), Fraction())
    resolved_stake = sum((Fraction(t["stake_exact_usd"]) for t in resolved), Fraction())
    expected = sum((Fraction(t["expected_profit_exact_usd"]) for t in tickets), Fraction())
    expected_resolved = sum((Fraction(t["expected_profit_exact_usd"]) for t in resolved), Fraction())
    returned = sum((Fraction(t["return_exact_usd"]) for t in resolved), Fraction()) if resolved or not tickets else None
    pnl = returned - resolved_stake if returned is not None else None
    roi = str(pnl/resolved_stake) if resolved_stake else None
    bases = dict(tickets=len(tickets), games=len({t["game_id"] for t in tickets}), resolved=len(resolved),
                 unresolved=len(tickets)-len(resolved), wins=states["win"], losses=states["loss"],
                 pushes=states["push"], voids=states["void"], roi=roi,
                 roi_percent=paper.money(Fraction(roi) * 100) if roi is not None else None, grade_counts=dict(states),
                 roi_denominator="resolved_ticket_stake" if len(resolved) != len(tickets) else "total_stake")
    return _money(bases, stake=stake, expected_profit=expected, resolved_expected_profit=expected_resolved,
                  unresolved_stake=stake-resolved_stake, roi_stake=resolved_stake, return_=returned, pnl=pnl)


def _breakdown(tickets, key, categories=()):
    groups = {category: [] for category in categories}
    for ticket in tickets:
        groups.setdefault(ticket[key], []).append(ticket)
    return {category: _summary(values) for category, values in groups.items()}


def portfolio_status(report, variant):
    summary = report["portfolios"][variant]["summary"]
    if summary["tickets"]:
        if not summary["unresolved"]:
            return "graded"
        if summary["resolved"]:
            return "partially_graded"
        return "awaiting_results" if summary["grade_counts"].get("pending") else "unresolved"
    games = report["games"]
    if any(game["capture_status"] in ("pending", "claimed") for game in games):
        return "collecting"
    if any(game["capture_status"] in CAPTURED for game in games):
        return "no_selected_tickets"
    return "no_usable_capture"


def build_report(run, contexts):
    """Compute the exact same report for the same frozen run and evidence."""
    document = run["payload"]
    original = document["report"]
    policy = original["policy"]
    one_per_game = policy.get("portfolio_rule") == paper.MAIN_FIRST_ONE_PER_GAME
    game_entries = {game["game_id"]: (game, known) for game, known in contexts}
    witnesses = document.get("witnesses") or {}
    graded = {}
    for ticket in original["portfolios"]["all_venues"]["tickets"]:
        game, known = game_entries[ticket["game_id"]]
        graded[ticket["id"]] = _ticket(run["id"], ticket, witnesses.get(ticket["id"]), game, known)
    portfolios = {}
    for name in VARIANTS:
        entries = original["portfolios"][name]["tickets"]
        if one_per_game and name == "best_venue":
            # The ranked line may be witnessed at a different venue from the
            # best sized quote. Preserve that reason on the selected grade.
            tickets = [dict(graded[ticket["id"]], portfolio_selection=ticket["portfolio_selection"]) for ticket in entries]
        else:
            tickets = [graded[ticket["id"]] for ticket in entries]
        portfolios[name] = dict(tickets=tickets, summary=_summary(tickets),
            by_game=_breakdown(tickets, "game_id", game_entries), by_venue=_breakdown(tickets, "venue"),
            by_capture=_breakdown(tickets, "capture_origin", ("frozen", "reconstructed")))
    if one_per_game:
        portfolios["all_venues"]["candidate_pool_only"] = True
    primary = "best_venue" if one_per_game else "all_venues"
    games = [game for game, _ in game_entries.values()]
    coverage = dict((run.get("summary") or {}).get("coverage") or {})
    coverage.update(known_games=len(games),
        missing_capture_games=sum(g["capture_status"] not in CAPTURED | {"pending", "claimed"} for g in games),
        zero_trade_games=sum(g["capture_status"] in CAPTURED and not portfolios[primary]["by_game"][g["game_id"]]["tickets"]
                             for g in games),
        final_games=sum(g["result"]["state"] == "final" for g in games))
    summary = portfolios[primary]["summary"]
    pending_games = any(g["result"]["state"] == "pending" for g in games)
    if one_per_game:
        status = portfolio_status(dict(portfolios=portfolios, games=games), primary)
    elif summary["tickets"] and not summary["unresolved"]:
        status = "graded"
    elif summary["resolved"]:
        status = "partially_graded"
    elif summary["grade_counts"].get("pending") or pending_games:
        status = "collecting" if not summary["tickets"] and coverage.get("pending_games") else "awaiting_results"
    else:
        status = "unresolved" if summary["tickets"] else "no_selected_tickets"
    rule = NHL_VERSION if _nhl_line_games(original) else VERSION
    report = dict(schema=SCHEMA, grading_rule=rule, run_id=run["id"], date=original["date"],
                original_report_revision=run["report_revision"], status=status,
                evidence_revision=hashed([(g["game_id"], g["occurrence_id"], g["result"]) for g in games]),
                result_observed_at=max((g["result"]["observed_at"] for g in games if g["result"]["observed_at"]),
                                       key=stamp, default=None),
                coverage=coverage, games=games, portfolios=portfolios, provider_requests=0, orders_submitted=0)
    if "sizing_mode" in policy:
        report["sizing_policy"] = {key: policy[key] for key in ("sizing_mode", "sizing_rule", "target_profit_usd",
            "reference_bankroll_usd", "kelly_multiplier", "sizing_scale_usd", "minimum_ev", "minimum_stake_usd",
            "portfolio_rule", "portfolios", "market_scope", "alternate_odds_below", "depth_policy",
            "depth_execution_version", "prospective_start_at", "decision_before")
            if key in policy}
    return report


def build(db, run):
    return build_report(run, _lookup_games(db, run))
