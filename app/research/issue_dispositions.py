"""Review decisions over retained evidence, independent of saved paper results."""

from collections import Counter, defaultdict
from datetime import timezone
import re
from urllib.parse import urlencode, urlsplit

from psycopg.types.json import Jsonb

from app.storage.store import hashed, stamp


OPEN = "open"
RESOLVED = "resolved_by_evidence"
GAP = "accepted_historical_gap"
LIMIT = "accepted_source_limitation"
EXCLUDED = "excluded_by_scope"
OTHER_DATE = "assigned_another_date"
HASH = re.compile(r"[0-9a-f]{64}")


class InvalidDecision(ValueError):
    pass


class StaleDecision(ValueError):
    pass


def _clock(value):
    return stamp(value).astimezone(timezone.utc).isoformat() if value else None


def _link(label, url):
    return dict(label=label, url=url)


def _data(day, game_id=None, *, run=None):
    query = dict(evidence="mens-d1", scope="mens-d1", date=day)
    if game_id:
        query["coverage_game"] = game_id
    if run:
        query["run"] = run
    return "/data?" + urlencode(query)


def _evidence_links(day, game):
    links = [_link("Retained occurrence and capture history", _data(day, game["id"]))]
    if receipt := game.get("receipt_id"):
        links.append(_link("Original schedule receipt", f"/api/workspace/mens-d1/receipts/{receipt}"))
    for official in game.get("official_source_evidence", []):
        if official.get("source_url"):
            links.append(_link(official["publisher"], official["source_url"]))
    return list({link["url"]:link for link in links}.values())


def issue_id(day, kind, game_id=None):
    return hashed(["mens-d1", day, kind, game_id])


def _candidate(day, kind, title, reason, evidence, facts, allowed, *, game=None, at=None, verified=False):
    game_id = game["id"] if game else None
    return dict(id=issue_id(day, kind, game_id), kind=kind, game_id=game_id,
        game_title=game.get("title") if game else None, title=title, reason=reason,
        evidence_revision=hashed(["research-issue-evidence-1", kind, facts]), evidence=evidence,
        allowed_statuses=list(allowed), reported_at=_clock(at), active=True, verified_evidence=verified)


def _scope_issues(day, game, at, links, known):
    scope, applicability = game.get("scope_state"), game.get("day_applicability")
    schedule = game.get("occurrence_schedule") or {}
    official = game.get("official_source_evidence", [])
    membership_reason = game.get("scope_reason")
    corroborated = membership_reason == "both_participants_verified_by_official_occurrence_evidence"
    keep_scope = issue_id(day, "membership", game["id"]) in known
    if scope in ("unresolved", "excluded") or corroborated or keep_scope:
        membership = [(team.get("canonical_id"), evidence.get("division"), evidence.get("membership_record_id"))
                      for team in game.get("teams", []) for evidence in (team.get("membership") or {},)]
        if scope == "excluded":
            reason = "Retained membership evidence places at least one participant outside men’s Division I."
            allowed = (RESOLVED, EXCLUDED)
        elif corroborated:
            reason = "Retained official occurrence evidence identifies both Division I participants. The original placeholder stays in source history."
            allowed = (RESOLVED,)
        else:
            reason = "Review participant identities and the applicable season membership evidence."
            allowed = (RESOLVED, LIMIT)
        yield _candidate(day, "membership", "Men’s Division I membership", reason, links,
            [scope, membership_reason, game.get("membership_version"), sorted(membership, key=str),
             sorted(citation["id"] for citation in official) if corroborated else []], allowed, game=game, at=at,
             verified=corroborated or scope == "excluded")
    clock_state = schedule.get("state")
    keep_schedule = issue_id(day, "schedule", game["id"]) in known
    if applicability == "other_date" or keep_schedule or (scope != "excluded" and (
            applicability == "disputed" or clock_state in ("start_disputed", "official_provider_clock_corroborated"))):
        target_day = game.get("eastern_game_date")
        if applicability == "other_date" and target_day:
            links = [*links, _link(f"Open {target_day} Eastern coverage", _data(target_day, game["id"]))]
            reason = f"The retained occurrence belongs to {target_day} Eastern. The original source clocks stay in the audit."
            allowed = (RESOLVED, OTHER_DATE)
        elif clock_state == "official_provider_clock_corroborated":
            reason = "Official and odds-provider clocks agree. The differing source clock and original T−10 target remain in the audit."
            allowed = (RESOLVED,)
        else:
            reason = "Review the retained clocks for this occurrence and its Eastern game date."
            allowed = (RESOLVED, LIMIT)
        clocks = [(clock["origin"], _clock(clock.get("starts_at")), clock.get("source_url"))
                  for clock in schedule.get("evidence", [])]
        yield _candidate(day, "schedule", "Schedule and Eastern date", reason, links,
            [clock_state, applicability, target_day, sorted(set(clocks), key=str),
             _clock(game["capture"].get("target_at"))], allowed, game=game, at=at,
             verified=clock_state == "official_provider_clock_corroborated" or applicability == "other_date")


def _checkpoint_links(day, game, run, saved):
    links = _evidence_links(day, game)
    if saved.get("checkpoint_id") and run:
        query = urlencode(dict(date=day, game=game["id"], run=run["id"], version="saved"))
        links.append(_link("Retained T−10 market census", f"/api/workspace/mens-d1/market-census?{query}"))
    elif game["capture"].get("frozen_id") and game["capture"]["state"] == "captured":
        query = urlencode(dict(date=day, game=game["id"], version="current"))
        links.append(_link("Original T−10 market census", f"/api/workspace/mens-d1/market-census?{query}"))
    return links


def _game_issues(day, game, run, at, known):
    links = _evidence_links(day, game)
    yield from _scope_issues(day, game, at, links, known)
    if "result_ledger" not in game["facets"]:
        return
    match = game.get("match_state")
    if match in ("provider_only", "source_only", "no_market") or issue_id(day, "cross_source", game["id"]) in known:
        yield _candidate(day, "cross_source", "Independent schedule and provider evidence",
            "The schedule population remains visible while the retained provider or independent source coverage is reviewed.",
            links, [match, game.get("match_reason"), game.get("provider_event_id")], (RESOLVED, LIMIT), game=game, at=at,
            verified=match == "matched")
    capture, saved = game["capture"], game.get("saved") or {}
    capture_state, saved_state = capture["state"], saved.get("status")
    frozen = ((capture_state == "captured" and capture.get("frozen_id"))
              or (saved_state == "captured" and saved.get("checkpoint_id")))
    recovered = saved_state == "reconstructed" and saved.get("checkpoint_id")
    upcoming = capture_state in ("upcoming", "due", "claimed") or (
        capture_state == "no_task" and game.get("starts_at") and stamp(game["starts_at"]) > stamp(at))
    keep_capture = issue_id(day, "capture", game["id"]) in known
    if keep_capture or (capture_state != "captured" and not upcoming):
        if frozen:
            reason = "Retained original T−10 evidence is available for review."
            allowed = (RESOLVED,)
        elif recovered:
            reason = "A retained reconstruction is usable for paper analysis. The original capture state remains unchanged."
            allowed = (RESOLVED,)
        else:
            reason = "No qualifying retained T−10 prices were identified for this occurrence."
            allowed = (GAP,)
        facts = [capture_state, capture.get("reason"), capture.get("task_schedule_id"),
                 *(_clock(capture.get(field)) for field in ("target_at", "deadline_at")),
                 capture.get("frozen_id"), saved.get("checkpoint_id")]
        yield _candidate(day, "capture", "Original T−10 capture", reason, _checkpoint_links(day, game, run, saved),
                         facts, allowed, game=game, at=capture.get("task_updated_at") or at,
                         verified=bool(recovered or frozen))

    if saved.get("checkpoint_id") or capture_state == "captured" and capture.get("frozen_id"):
        market = saved.get("market_summary") or capture.get("market_summary") or {}
        checkpoint = saved.get("checkpoint_id") or capture.get("frozen_id")
        links = _checkpoint_links(day, game, run, saved)
        witness = market.get("evidence_revision")
        retrieval = market.get("retrieval_state")
        inventory_reason = ("A retained target-event response measures returned markets. An unreturned cell leaves the historical offering unknown."
                            if retrieval == "complete_requested_event_response" else
                            "Review target-event retrieval and venue cells in the retained census. Unknown offering stays distinct from observed unavailability.")
        candidate = _candidate(day, "venue_inventory", "Provider inventory coverage",
            inventory_reason,
            links, [checkpoint, witness], (RESOLVED, LIMIT), game=game, at=at)
        candidate["checkpoint_id"] = checkpoint
        yield candidate
        exclusions = {key:value for key, value in (saved.get("exclusions") or {}).items() if key.startswith("reference_")}
        if exclusions:
            yield _candidate(day, "reference", "Exact-line reference eligibility",
                "The frozen method requires the exact book, side and line and enough trusted books. Inspect the census for the missing inputs.",
                links, [checkpoint, exclusions], (RESOLVED, LIMIT), game=game, at=at)

    result = game.get("result_state")
    if result not in ("pending", "provider_pending", "final", "provider_final") or issue_id(day, "result", game["id"]) in known:
        results = game.get("result_revisions", []) + game.get("provider_results", [])
        yield _candidate(day, "result", "Sporting final", game.get("result_reason") or "Review the retained sporting result.", links,
            [result, game.get("result_reason"), [revision.get("id") for revision in results]],
            (RESOLVED, LIMIT), game=game, at=at, verified=result in ("final", "provider_final"))


def candidates(value, games, run, known=()):
    day, at = value["date"], value["as_of"]
    known = set(known)
    if (value.get("expected_games") is None and games) or issue_id(day, "slate") in known:
        yield _candidate(day, "slate", "Independent slate coverage",
            "The observed cohort can be reconciled. The retained sources do not establish an independently exhaustive men’s Division I slate.",
            [_link("Observed schedule population", _data(day))],
            [value.get("expected_games"), sorted(game["id"] for game in games if "result_ledger" in game["facets"])],
            (RESOLVED, LIMIT), at=at)
    for game in games:
        yield from _game_issues(day, game, run, at, known)


def _stored(db, day):
    return db.execute("""SELECT id,issue_id,evidence_revision,supersedes,status,reason,actor,decided_at,evidence,issue
        FROM public.research_issue_disposition WHERE game_date=%s ORDER BY sequence""", (day,))


def list_issues(db, value, games, run):
    history, prior = defaultdict(list), {}
    for row in _stored(db, value["date"]):
        identity = row["issue_id"]
        prior[identity] = row["issue"]
        history[identity].append(dict({key:row[key] for key in ("id", "evidence_revision", "supersedes", "status", "reason", "actor", "evidence")},
                                      decided_at=_clock(row["decided_at"])))
    issues = []
    for item in candidates(value, games, run, prior):
        prior.pop(item["id"], None)
        issues.append(_with_history(item, history[item["id"]]))
    issues.extend(_with_history(dict(item, active=False, allowed_statuses=[]), history[identity])
                  for identity, item in prior.items())
    return issues, dict(Counter(issue["status"] for issue in issues if issue["active"]))


def _with_history(item, history):
    latest = history[-1] if history else None
    changed = bool(item["active"] and latest and latest["evidence_revision"] != item["evidence_revision"])
    status = latest["status"] if latest and not changed else OPEN
    choices = [] if status == GAP else [choice for choice in item["allowed_statuses"] if choice != status]
    if item["active"] and status not in (OPEN, GAP):
        choices.append(OPEN)
    return dict(item, status=status, evidence_changed=changed, history=history, allowed_statuses=choices,
                latest_decision_id=latest["id"] if latest else None)


def _validated_url(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 1400 or any(ord(char) <= 32 or char == "\\" for char in value):
        raise InvalidDecision("Provide a retained evidence link or an HTTPS citation.")
    try:
        parsed = urlsplit(value)
        if (not parsed.scheme and not parsed.netloc and value.startswith("/") and not value.startswith("//")) or (
                parsed.scheme == "https" and parsed.hostname and not (parsed.username or parsed.password)):
            return value
    except ValueError:
        pass
    raise InvalidDecision("Provide a retained evidence link or an HTTPS citation.")


def validate(body):
    required = {"date", "id", "evidence_revision", "latest_decision_id", "status", "reason"}
    if not isinstance(body, dict) or not required <= set(body) or set(body) - required - {"run", "evidence_url"}:
        raise InvalidDecision("Provide the selected issue, evidence revision, decision and reason.")
    for field in ("id", "evidence_revision", "latest_decision_id", "run"):
        value = body.get(field)
        if value is None and field in ("latest_decision_id", "run"):
            continue
        if not isinstance(value, str) or not HASH.fullmatch(value):
            raise InvalidDecision("Select a saved issue and evidence revision.")
    if body["status"] not in (OPEN, RESOLVED, GAP, LIMIT, EXCLUDED, OTHER_DATE):
        raise InvalidDecision("Select an available issue decision.")
    reason = body["reason"]
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise InvalidDecision("Enter a decision reason of at most 1,000 characters.")
    return dict(body, reason=reason.strip(), evidence_url=_validated_url(body.get("evidence_url")))


def lock(db, identity):
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("research-issue:" + identity,))


def record(db, day, issue, status, reason, actor, *, evidence_url=None):
    if not issue["active"] or status not in issue["allowed_statuses"]:
        raise InvalidDecision("That decision is unavailable for the current evidence.")
    links = list(issue["evidence"])
    if evidence_url and all(item["url"] != evidence_url for item in links):
        links.append(_link("Decision citation", evidence_url))
    if status == RESOLVED and not (issue["verified_evidence"] or evidence_url):
        raise InvalidDecision("Provide the evidence that resolves this issue.")
    if status in (EXCLUDED, OTHER_DATE) and len(links) < 2:
        raise InvalidDecision("A scope decision requires a retained membership or date citation.")
    prior = issue["latest_decision_id"]
    revision = issue["evidence_revision"]
    identity = hashed([issue["id"], revision, prior, status, reason, actor, links])
    snapshot = {key:value for key, value in issue.items() if key not in (
        "status", "history", "evidence_changed", "latest_decision_id")}
    row = db.execute("""INSERT INTO public.research_issue_disposition
        (id,game_date,issue_id,evidence_revision,supersedes,status,reason,actor,evidence,issue)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING decided_at""",
        (identity, day, issue["id"], revision, prior, status, reason, actor, Jsonb(links), Jsonb(snapshot))).fetchone()
    decision = dict(id=identity, evidence_revision=revision, supersedes=prior, status=status, reason=reason,
                    actor=actor, decided_at=_clock(row["decided_at"]), evidence=links)
    snapshot["allowed_statuses"] = list(dict.fromkeys([*issue["allowed_statuses"], status, issue["status"]]))
    return _with_history(snapshot, [*issue["history"], decision])


def require_current(issue, body):
    if issue["evidence_revision"] != body["evidence_revision"] or issue["latest_decision_id"] != body["latest_decision_id"]:
        raise StaleDecision("Issue evidence or history changed. Reload and review the current evidence.")
