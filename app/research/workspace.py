"""Append-only research definitions, runs and findings over retained evidence."""

from collections import Counter
from datetime import date, datetime, timezone
from fractions import Fraction
import json
import re

from psycopg.types.json import Jsonb

from app.storage import payload_codec
from app.storage.store import ROOT, encoded, hashed, stamp
from . import experiment, mens_d1, paper, paper_evidence, records
from .ev_movement import _role

SCHEMA = "predict-research-workspace-1"
PILOT_VERSION = "ncaab-t10-paper-v1"
PILOT_DAY = paper.POLICY["default_date"]
ASSUMPTIONS = ("minimum_ev", "reference_bankroll_usd", "kelly_multiplier")
HASH = re.compile(r"[0-9a-f]{64}")


class SelectionError(ValueError):
    """An authored workspace validation error safe to display to the owner."""


class UnknownSelection(SelectionError):
    pass


def game_day(value):
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except (TypeError, ValueError):
        pass
    raise SelectionError("Use an Eastern game date in YYYY-MM-DD format.")


def assumptions(values):
    if not isinstance(values, dict) or set(values) - set(ASSUMPTIONS):
        raise SelectionError("Choose a screening EV, sizing reference, or Kelly fraction.")
    normalized = {}
    for key, raw in values.items():
        if not isinstance(raw, str) or not re.fullmatch(r"(?:\d{1,12}(?:\.\d{1,12})?|\.\d{1,12}|\d{1,12}/\d{1,12})", raw):
            raise SelectionError("Use decimal or fraction strings for replay assumptions.")
        try:
            value = Fraction(raw)
        except (ValueError, ZeroDivisionError):
            raise SelectionError("Use a valid decimal or fraction for each replay assumption.") from None
        if value <= 0 or key == "kelly_multiplier" and value > 1:
            raise SelectionError("Use positive replay assumptions and a Kelly fraction no greater than one.")
        normalized[key] = str(value)
    return normalized


def experiment_registration(value):
    if not isinstance(value, dict) or set(value) != {"title", "question", "claim_ids"}:
        raise SelectionError("Provide a title, question and claims for the new experiment.")
    title, question, claim_ids = value["title"], value["question"], value["claim_ids"]
    if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 120
            or not isinstance(question, str) or not 1 <= len(question.strip()) <= 600):
        raise SelectionError("Enter a short title and question for the new experiment.")
    if (not isinstance(claim_ids, list) or not claim_ids
            or any(not isinstance(claim, str) or not re.fullmatch(r"[0-9a-z-]{1,64}", claim) for claim in claim_ids)):
        raise SelectionError("Select at least one recorded claim for the new experiment.")
    return dict(title=title.strip(), question=question.strip(), claim_ids=sorted(set(claim_ids)))


def _record(row):
    result = dict(row["payload"], id=row["id"], version=row["version"],
                  recorded_at=row["recorded_at"].isoformat())
    if "supersedes" in row:
        result["supersedes"] = row["supersedes"]
    if "run_id" in row:
        result["run_id"] = row["run_id"]
    return result


def _definition(db, version):
    row = db.execute("SELECT * FROM public.research_workspace_definition WHERE version=%s", (version,)).fetchone()
    if row is None:
        raise UnknownSelection("Unknown experiment definition version.")
    return _record(row)


def _run_summary(row):
    return dict(row["summary"], id=row["id"], date=row["game_date"].isoformat(),
                created_at=row["recorded_at"].isoformat(), as_of=row["observed_at"].isoformat(),
                supersedes=row["supersedes"], definition_version=row["definition_version"],
                report_revision=row["report_revision"])


def index(db):
    from . import paper_campaigns
    catalog = list(db.execute("""SELECT * FROM public.research_workspace_catalog
        ORDER BY recorded_at,version"""))
    definitions = [_record(row) for row in db.execute("""SELECT * FROM public.research_workspace_definition
        ORDER BY recorded_at DESC,version""")]
    pilot = next(definition for definition in definitions if definition["version"] == PILOT_VERSION)
    runs = [_run_summary(row) for row in db.execute("""SELECT id,game_date,recorded_at,observed_at,supersedes,
        definition_version,report_revision,summary FROM public.research_workspace_run
        ORDER BY observed_at DESC,id""")]
    findings = [_record(row) for row in db.execute("""SELECT * FROM public.research_workspace_finding
        ORDER BY recorded_at DESC,version""")]
    # Date keys come from the retained checkpoint owner, independently of saved analyses.
    available = list(db.execute("""SELECT
        ((g.event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date::text AS date,
        count(*) AS tracked_games,
        count(*) FILTER (WHERE g.late_id IS NOT NULL AND t.state='captured'
            AND t.schedule_id=g.schedule_id) AS captured_games
        FROM public.ev_experiment_game g
        LEFT JOIN public.ev_experiment_task t ON t.game_id=g.id AND t.checkpoint='late'
        WHERE g.event->>'league'=%s GROUP BY 1 ORDER BY 1 DESC""", (pilot["policy"]["league"],)))
    return dict(schema=SCHEMA, pilot=dict(date=PILOT_DAY, title=pilot["title"], definition_version=PILOT_VERSION),
        theories=[_record(row) for row in catalog if row["kind"] == "theory"],
        claims=[_record(row) for row in catalog if row["kind"] == "claim"],
        definitions=definitions, mens_d1_template=mens_d1.template(pilot),
        runs=runs, findings=findings, available_dates=available, campaigns=paper_campaigns.index(db),
        provider_requests=0, orders_submitted=0)


def _changed_definition(parent, values):
    prior = parent["policy"]
    changes = {name: value for name, value in values.items() if value != prior[name]}
    if not changes:
        return parent
    version = hashed([parent["version"], changes])
    policy = dict(prior, **changes)
    policy.update(version=f"paper-tminus10-exploratory-{version}", baseline=None,
                  selection="unrounded captured screening EV at the versioned threshold; recheck at sized cash commitment",
                  sizing_scale_usd=str(Fraction(policy["reference_bankroll_usd"]) * Fraction(policy["kelly_multiplier"])))
    changed = dict(parent, version=version, supersedes=parent["version"], policy=policy,
                   designation="exploratory_replay", registration="Exploratory assumptions recorded when this version is saved.")
    changed.pop("recorded_at")
    return changed


def _register_definition(db, template, proposed, registration):
    claim_ids = registration["claim_ids"]
    claims = list(db.execute("""SELECT DISTINCT ON (id) id,version FROM public.research_workspace_catalog
        WHERE kind='claim' AND id=ANY(%s) ORDER BY id,recorded_at DESC,version""", (claim_ids,)))
    if len(claims) != len(claim_ids):
        raise SelectionError("Select existing research claims for the new experiment.")
    identity = hashed([template["id"], registration])
    claim_versions = [row["version"] for row in claims]
    version = hashed([identity, template["version"], proposed["policy"], claim_versions])
    definition = dict(proposed, **registration, id=identity, version=version, supersedes=None,
                      template_version=template["version"], designation="exploratory_replay",
                      claim_versions=claim_versions,
                      registration="Separate experiment registered at the time of replay, using a recorded template policy.")
    definition.pop("recorded_at", None)
    return definition


def _compact_report(report):
    from .paper_campaigns import _age_bucket

    compact_evidence = ((report.get("population") or {}).get("kind") == "reconciled_occurrences"
                        or "leagues" in report["policy"])
    versioned_sizing = "sizing_mode" in report["policy"]
    witnesses = {}
    for portfolio in report["portfolios"].values():
        compact = []
        for ticket in portfolio["tickets"]:
            ticket = dict(ticket)
            witness = ticket.pop("witness")
            identity = ticket["id"]
            offer_index = ticket.pop("offer_index")
            if identity not in witnesses:
                calculation = witness["sized_calculation"]
                if compact_evidence:
                    witnesses[identity] = dict(offer_index=offer_index,
                        encoded_calculation=payload_codec.encode(encoded(calculation).decode()))
                else:
                    witnesses[identity] = dict(offer_index=offer_index, sized_calculation=calculation)
                if versioned_sizing:
                    witnesses[identity]["reference_age_bucket"] = _age_bucket(paper_evidence.reference_age(calculation))
            if versioned_sizing:
                ticket["reference_age_bucket"] = witnesses[identity]["reference_age_bucket"]
            compact.append(ticket)
        portfolio["tickets"] = compact
    # The exact sporting result stays under its immutable source ID.
    report.pop("outcome_evidence")
    if compact_evidence:
        # Detailed rejected quotes and exact lines remain on the frozen checkpoint.
        for game in report["games"]:
            if game.get("coverage"):
                game["coverage"] = {key:value for key,value in game["coverage"].items()
                                    if key not in ("rejected_projection", "line_ranges")}
    return dict(report=report, witnesses=witnesses)


def _sized_calculation(witness):
    if "sized_calculation" in witness:
        return witness["sized_calculation"]
    return json.loads(payload_codec.decode(witness["encoded_calculation"]))


def _summary(report, title):
    games = report["games"]
    states = Counter(game["status"] for game in games)
    pending = states["pending"] + states["claimed"]
    captured = states["captured"]
    reconstructed = states["reconstructed"]
    missing = len(games) - captured - reconstructed - pending
    partial = sum(game["status"] in ("captured", "reconstructed") and (game.get("coverage") or {}).get("incomplete") is not False
                  for game in games)
    coverage = dict(expected_games=None, tracked_games=len(games), captured_games=captured,
                    missing_tracked_games=missing, pending_games=pending, untracked_games=None,
                    source_coverage_unconfirmed_games=partial, dispositions=dict(states))
    if reconstructed:
        coverage["reconstructed_games"] = reconstructed
    population = report.get("population")
    uncovered = 0
    if population:
        scopes = Counter(entry["scope_state"] for entry in population["games"])
        coverage.update(population_kind=population["kind"], population_revision=population["revision"],
                        eligible_games=scopes["eligible"], excluded_games=scopes["excluded"],
                        unverified_membership_games=scopes["unresolved"])
        if population["kind"] == "verified_daily_schedule":
            coverage.update(expected_games=scopes["eligible"], untracked_games=scopes["eligible"] - len(games))
        elif population["kind"] == "reconciled_occurrences":
            coverage.update(tracked_games=len(games) - states["no_task"],
                            missing_tracked_games=missing - states["no_task"], untracked_games=states["no_task"],
                            expected_games=population.get("expected_games"), dated_eligible_games=len(games),
                            disputed_date_games=sum(row.get("day_applicability") == "disputed" for row in population["games"]))
        uncovered = scopes["unresolved"] + (coverage["untracked_games"] or 0)
    if not captured and not reconstructed:
        validity = "no_valid_capture"
    elif missing or pending or partial or uncovered:
        validity = "incomplete_tracked_capture"
    else:
        validity = "tracked_captures_only"
    status = {"no_valid_capture": "awaiting_captures" if pending else "incomplete",
              "incomplete_tracked_capture": "incomplete", "tracked_captures_only": "screened"}[validity]
    return dict(title=title, status=status, validity=validity, coverage=coverage,
                variants={name: {k: v for k, v in portfolio.items() if k != "tickets"}
                          for name, portfolio in report["portfolios"].items()
                          if not portfolio.get("candidate_pool_only")})


def _finding_payloads(run_id, definition, report, summary):
    all_venues = report["portfolios"]["all_venues"]
    ranked = all_venues.get("candidate_pool_only") is True
    selected = report["portfolios"]["best_venue"] if ranked else all_venues
    capture_evidence = [dict(label="Run population and coverage", run_id=run_id)]
    ticket_evidence = [dict(label="Selected paper trades" if ranked else "Both venue variants", run_id=run_id)]
    for game in report["games"]:
        capture_evidence.append(dict(label=game["title"], run_id=run_id, game_id=game["game_id"],
                                     checkpoint_id=game["checkpoint_id"]))
    if selected["tickets"]:
        ticket = next((row for row in selected["tickets"] if row["grading"]["pnl_usd"] is not None),
                      selected["tickets"][0])
        ticket_evidence.append(dict(label="Frozen quote, sized calculation and result evidence", run_id=run_id,
                                    ticket_id=ticket["id"], game_id=ticket["game_id"],
                                    checkpoint_id=ticket["checkpoint_id"]))
    coverage = summary["coverage"]
    rows = (
        ("law", "Expected value identity", ["net-ev-law"],
         "The saved calculations show the recorded state probabilities, receipts and committed capital used by the EV rule.",
         "unexamined", ["A paper replay applies the arithmetic under its assumptions. The identity follows from the definition of expectation."],
         ticket_evidence),
        ("coverage", "Capture coverage", ["evidence-quality", "t10-selection"],
         (f'{coverage["captured_games"]} of {coverage["tracked_games"]} tracked games had an eligible frozen T−10 capture.'
          + (f' Another {coverage["reconstructed_games"]} were calculated retrospectively from original responses received in the T−10 window; these are not original EV captures.'
             if coverage.get("reconstructed_games") else "")),
         "support" if summary["validity"] == "tracked_captures_only" else "inconclusive",
         ["The expected league-wide population and untracked games are unknown.",
          "Missing captures and incomplete source returns limit what this run can examine."], capture_evidence),
        ("sizing", "Paper selection and sizing", ["t10-selection", "fee-sizing"],
         (f'{selected["count"]} paper trades selected with at most one trade per game.' if ranked else
          f'{selected["count"]} tickets qualified across {selected["unique_games"]} games in All qualifying venues.'),
         "support" if selected["count"] else "unexamined",
         ["The replay documents which branch ran. Independent checks are needed to verify the calculation.",
          "Every ticket uses a modeled amount and captured price. Execution and venue settlement remain unverified."],
         ticket_evidence),
        ("returns", "Repeated profitability", ["positive-net-returns"],
         "This pipeline replay leaves repeated net returns and the 12-month risk objective unexamined.",
         "unexamined", ["A retrospective day does not establish representative return behavior.",
                        "Finite capital, fill and dependence assumptions are still open."],
         [dict(label="Pipeline run and limitations", run_id=run_id)]),
    )
    linked = set()
    for key, title, claim_ids, statement, disposition, limitations, evidence in rows:
        claim_ids = [claim for claim in claim_ids if claim in definition["claim_ids"]]
        if not claim_ids:
            continue
        linked.update(claim_ids)
        identity = hashed([run_id, key])
        payload = dict(definition_version=definition["version"], title=title, statement=statement,
                       disposition=disposition, claim_ids=claim_ids, limitations=limitations, evidence=evidence)
        yield identity, hashed([identity, payload]), payload
    unsupported = sorted(set(definition["claim_ids"]) - linked)
    if unsupported:
        identity = hashed([run_id, "unexamined"])
        payload = dict(definition_version=definition["version"], title="Claims left unexamined",
            statement="This replay produced no specific finding for these selected claims.",
            disposition="unexamined", claim_ids=unsupported, limitations=["The replay evaluates the recorded template policy."],
            evidence=[dict(label="Run population and evaluation", run_id=run_id)])
        yield identity, hashed([identity, payload]), payload


def _admit(db, size):
    from app.collection.current_storage_policy import SQL_BYTE_CAP, require_disk_space, sql_usage

    if size > records.EVALUATION_RECORD_BYTE_CAP:
        raise SelectionError("The replay exceeds the saved research evaluation size limit.")
    used = records.retention_usage(db)
    if used["total"] + used["reserved"] + size > records.TOTAL_BYTE_CAP:
        raise SelectionError("Research retention is full. Existing captures and saved runs were preserved.")
    if sql_usage(db) + size * 3 + 8 * 1024 * 1024 > SQL_BYTE_CAP:
        raise SelectionError("Database storage has insufficient runway for this replay.")
    require_disk_space(ROOT / ".local/postgres", append_bytes=size * 3)


def _unchanged_recovery_run(db, day, definition, *, population=None):
    """Reopen an unchanged, terminal opportunity record without decoding quotes.

    Applies to the versioned recovery and verified D1 opportunity projections.
    Any scope, schedule, task, checkpoint or attempt change requires a new
    calculation. Deadline passage changes a pending report even without writes.
    """
    policy = definition["policy"]
    legacy = (definition.get("designation") == "retrospective_raw_recovery"
              and policy.get("recovery_version") == "raw-t10-opportunity-recovery-1")
    if (not legacy and population is None) or policy.get("defer_results") is not True:
        return None
    previous = db.execute("""SELECT id,payload FROM public.research_workspace_run
        WHERE definition_version=%s AND game_date=%s ORDER BY observed_at DESC,id LIMIT 1""",
        (definition["version"], day)).fetchone()
    if not previous:
        return None
    saved = {g["game_id"]:g for g in previous["payload"]["report"]["games"] if g["status"] != "no_task"}
    current = list(db.execute("""SELECT g.*,t.state AS task_state,t.schedule_id AS task_schedule_id,
        t.target_at,t.deadline_at,t.last_reason FROM public.ev_experiment_game g
        JOIN public.ev_experiment_task t ON t.game_id=g.id AND t.checkpoint='late'
        WHERE g.event->>'league'=%s AND
        ((g.event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date=%s::date""",
        (policy["league"], day)))
    if population is not None:
        allowed = {row.get("provider_event_id") for row in population["games"] if mens_d1.in_paper_cohort(row)}
        current = [game for game in current if game["event"]["source_event_id"] in allowed]
    if set(saved) != {g["id"] for g in current}:
        return None
    attempts = {row["game_id"]:row["ids"] for row in db.execute("""SELECT game_id,
        array_agg(id ORDER BY recorded_at,id) AS ids FROM public.ev_experiment_record
        WHERE game_id=ANY(%s) AND kind='attempt' AND checkpoint='late' GROUP BY game_id""", (list(saved),))}
    now = datetime.now(timezone.utc)
    for game in current:
        prior = saved[game["id"]]
        if (legacy and (game["task_state"] not in ("captured", "refused", "missed") or game["deadline_at"] >= now)
                or game["baseline_correction_id"]
                or game["schedule_id"] != prior["schedule_id"]
                or game["task_schedule_id"] != game["schedule_id"]
                or game["event"]["title"] != prior["title"]
                or game["event"]["starts_at"] != prior["starts_at"]
                or game["target_at"] != stamp(prior["target_at"])
                or game["deadline_at"] != stamp(prior["deadline_at"])
                or attempts.get(game["id"], []) != prior["attempt_ids"]):
            return None
        if prior["status"] == "reconstructed":
            if (game["late_id"] is not None or game["task_state"] != prior["original_capture_status"]
                    or policy.get("recovered_checkpoints", {}).get(game["id"]) != prior["checkpoint_id"]):
                return None
        else:
            state, reason = game["task_state"], game["last_reason"]
            if state in ("pending", "claimed") and game["deadline_at"] < now:
                state, reason = "missed", "capture_window_closed"
            if (state != prior["status"] or game["late_id"] != prior["checkpoint_id"]
                    or not legacy and state != "captured" and reason != prior["reason"]):
                return None
    return previous["id"]


def replay(db, day, definition_version, values, *, registration=None):
    """Use a stable evidence snapshot, then publish the definition and run atomically."""
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        population = None
        if definition_version == mens_d1.DAILY:
            if values or registration:
                raise SelectionError("Daily coverage uses the published paper policy.")
            parent = _definition(db, PILOT_VERSION)
            population = mens_d1.daily_population(db, day)
            if population is None:
                raise SelectionError("This date has no retained occurrence evidence. Review the date in Data.")
            recovery = mens_d1.daily_recovery(db, day, population)
            definition = mens_d1.definition(mens_d1.template(parent), population, mens_d1.RECONCILED,
                                            recovery=recovery)
        else:
            parent = _definition(db, definition_version)
            if parent["policy"].get("scope") == mens_d1.SCOPE:
                if values or registration:
                    raise SelectionError("This saved scope and policy are fixed.")
                record = db.execute("""SELECT id FROM public.research_workspace_run
                    WHERE definition_version=%s AND game_date=%s ORDER BY observed_at DESC,id LIMIT 1""",
                    (parent["version"], day)).fetchone()
                if record:
                    return run_detail(db, record["id"])
                raise UnknownSelection("This scoped definition belongs to a different game date.")
            definition = _changed_definition(parent, values)
            if registration:
                definition = _register_definition(db, parent, definition, registration)
        existing = _unchanged_recovery_run(db, day, definition, population=population)
        if existing:
            return run_detail(db, existing)
        report = paper.report(db, day, evidence=True, policy=definition["policy"], population=population)
    return _publish(db, day, parent, definition, report)


def correct_mens_d1_recovery(db):
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        original = _run(db, mens_d1.ORIGINAL_RUN)
        parent = _definition(db, original["definition_version"])
        day = original["game_date"].isoformat()
        population = mens_d1.retained_population(db, original)
        definition = mens_d1.definition(parent, population, mens_d1.RECOVERY)
        record = db.execute("""SELECT id FROM public.research_workspace_run
            WHERE definition_version=%s AND game_date=%s LIMIT 1""", (definition["version"], day)).fetchone()
        if record:
            return run_detail(db, record["id"])
        report = mens_d1.replay_retained(db, day, definition["policy"], population, original)
    return _publish(db, day, parent, definition, report)


def save_mens_d1_provider_snapshot(db, day):
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        parent = _definition(db, PILOT_VERSION)
        population = mens_d1.retained_provider_population(db, day)
        if population is None:
            raise SelectionError("No odds-provider game observations were retained on this date.")
        recovery = mens_d1.daily_recovery(db, day, population)
        definition = mens_d1.definition(mens_d1.template(parent), population, mens_d1.RETAINED, recovery=recovery)
        existing = _unchanged_recovery_run(db, day, definition, population=population)
        if existing:
            return run_detail(db, existing)
        report = paper.report(db, day, evidence=True, policy=definition["policy"], population=population)
    return _publish(db, day, parent, definition, report)


def _publish(db, day, parent, definition, report, *, details=True):
    document = _compact_report(report)
    revision = hashed(dict(document, report={k: v for k, v in report.items() if k != "as_of"}))
    run_id = hashed([definition["version"], day, revision])
    summary = _summary(report, definition["title"])
    findings = list(_finding_payloads(run_id, definition, report, summary))

    with db.transaction():
        records._writer_lock(db)
        if db.execute("SELECT 1 FROM public.research_workspace_run WHERE id=%s", (run_id,)).fetchone():
            return run_detail(db, run_id) if details else run_id
        create_definition = definition["version"] != parent["version"] and db.execute(
            "SELECT 1 FROM public.research_workspace_definition WHERE version=%s",
            (definition["version"],)).fetchone() is None
        definition_body = {k: v for k, v in definition.items() if k not in ("version", "id", "supersedes", "recorded_at")}
        document_bytes = len(encoded(document)) + len(encoded(summary))
        _admit(db, document_bytes + sum(len(encoded(item[2])) for item in findings)
               + (len(encoded(definition_body)) if create_definition else 0))
        if create_definition:
            db.execute("""INSERT INTO public.research_workspace_definition
                (version,id,supersedes,payload_bytes,payload) VALUES (%s,%s,%s,%s,%s)""",
                (definition["version"], definition["id"], definition["supersedes"],
                 len(encoded(definition_body)), Jsonb(definition_body)))
        if definition.get("campaign_id"):
            prior = db.execute("""SELECT r.id FROM public.research_workspace_run r
                JOIN public.research_workspace_definition d ON r.definition_version=d.version
                WHERE r.game_date=%s AND d.payload->>'campaign_id'=%s
                AND COALESCE(d.payload->>'sizing_mode','kelly')=%s
                ORDER BY r.recorded_at DESC,r.id LIMIT 1""",
                (day, definition["campaign_id"], definition.get("sizing_mode", "kelly"))).fetchone()
        elif definition.get("designation") == mens_d1.RECONCILED:
            prior = db.execute("""SELECT r.id FROM public.research_workspace_run r
                JOIN public.research_workspace_definition d ON r.definition_version=d.version
                WHERE r.game_date=%s AND r.observed_at<=%s AND d.payload->>'designation'=ANY(%s)
                ORDER BY r.observed_at DESC,r.id LIMIT 1""", (day, report["as_of"],
                [mens_d1.RECONCILED, mens_d1.DAILY_DESIGNATION, mens_d1.RETAINED, mens_d1.RECOVERY])).fetchone()
        else:
            prior = db.execute("""SELECT id FROM public.research_workspace_run
                WHERE definition_version=%s AND game_date=%s AND observed_at<=%s
                ORDER BY observed_at DESC,id LIMIT 1""", (definition["version"], day, report["as_of"])).fetchone()
        db.execute("""INSERT INTO public.research_workspace_run
            (id,definition_version,game_date,report_revision,observed_at,supersedes,summary,payload_bytes,payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, definition["version"], day, revision, report["as_of"], prior["id"] if prior else None,
             Jsonb(summary), document_bytes, Jsonb(document)))
        with db.cursor() as cursor:
            cursor.executemany("""INSERT INTO public.research_workspace_finding
                (version,id,run_id,payload_bytes,payload) VALUES (%s,%s,%s,%s,%s)""",
                [(version, identity, run_id, len(encoded(payload)), Jsonb(payload))
                 for identity, version, payload in findings])
    return run_detail(db, run_id) if details else run_id


def _run(db, run_id):
    row = db.execute("SELECT * FROM public.research_workspace_run WHERE id=%s", (run_id,)).fetchone()
    if row is None:
        raise UnknownSelection("Unknown saved research run.")
    return row


def _run_comparison(before, after, prior_id):
    def change(old, new):
        return dict(before=old, after=new, delta=new - old if old is not None and new is not None else None)

    def counts(old, new):
        return {key:change(old.get(key, 0), new.get(key, 0)) for key in sorted(set(old) | set(new))}

    def offers(report):
        observed = [game.get("observed_offer_count") for game in report["games"]
                    if game["status"] in ("captured", "reconstructed")]
        return None if None in observed else sum(observed)

    def game_identities(report):
        population = report.get("population") or {}
        by_game = {game["game_id"]: game.get("provider_event_id") or game.get("occurrence_id")
                   for game in population.get("games", []) if game.get("game_id")}
        return {by_game.get(game["game_id"]) or game["game_id"]:game for game in report["games"]}

    old_games, new_games = game_identities(before), game_identities(after)
    variants = {}
    for name, new in after["portfolios"].items():
        old = before["portfolios"][name]
        turnover = dict(before=old["turnover_usd"], after=new["turnover_usd"],
                        delta=paper.money(Fraction(new["turnover_usd"]) - Fraction(old["turnover_usd"])))
        variants[name] = dict(tickets=change(old["count"], new["count"]), turnover_usd=turnover)
    return dict(prior_run_id=prior_id, games=change(len(old_games), len(new_games)),
        added_games=[new_games[key]["title"] for key in sorted(new_games.keys() - old_games.keys())],
        removed_games=[old_games[key]["title"] for key in sorted(old_games.keys() - new_games.keys())],
        captures=counts(Counter(game["status"] for game in before["games"]),
                        Counter(game["status"] for game in after["games"])),
        offers=change(offers(before), offers(after)), exclusions=counts(before["exclusions"], after["exclusions"]),
        variants=variants)


def run_detail(db, run_id, *, export=False):
    row = _run(db, run_id)
    definition = _definition(db, row["definition_version"])
    findings = [_record(value) for value in db.execute("""SELECT * FROM public.research_workspace_finding
        WHERE run_id=%s ORDER BY recorded_at,version""", (run_id,))]
    report = row["payload"]["report"]
    result = dict(schema=SCHEMA, run=_run_summary(row), definition=definition, findings=findings, report=report,
                  provider_requests=0, orders_submitted=0)
    if definition.get("campaign_snapshot"):
        from .paper_campaigns import sizing_run_detail

        result.update(sizing_run_detail(db, row, definition, report))
    if definition.get("designation") == mens_d1.RECONCILED and row["supersedes"]:
        prior = db.execute("SELECT payload->'report' report FROM public.research_workspace_run WHERE id=%s",
                           (row["supersedes"],)).fetchone()["report"]
        result["comparison"] = _run_comparison(prior, report, row["supersedes"])
    if export:
        result["witnesses"] = {identity:dict(offer_index=witness["offer_index"], sized_calculation=_sized_calculation(witness))
                               for identity, witness in row["payload"]["witnesses"].items()}
        claims = list(db.execute("""SELECT * FROM public.research_workspace_catalog
            WHERE version=ANY(%s) ORDER BY version""", (definition["claim_versions"],)))
        result["claims"] = [_record(claim) for claim in claims]
        result["manifest"] = dict(bundle_sha256=hashed(result),
            exact_sources="/api/research/workspace/runs/" + run_id + "/evidence/{game_id}?export=1")
    return result


def offer_export_plan(db, run_id):
    """Find the immutable games, policy and selected offer indices for this run."""
    row = _run(db, run_id)
    report = row["payload"]["report"]
    policy = report["policy"]
    if not (report.get("population") or policy.get("leagues")):
        raise UnknownSelection("Select a dated campaign or men’s D1 analysis to export its observed offers.")
    witnesses = row["payload"]["witnesses"]
    selected = {name: {(ticket["game_id"], witnesses[ticket["id"]]["offer_index"]):ticket["id"]
                       for ticket in portfolio["tickets"]} for name, portfolio in report["portfolios"].items()}
    fields = dict(date=report["date"], as_of=report["as_of"], run_id=run_id,
                  report_revision=row["report_revision"], minimum_ev=policy["minimum_ev"],
                  provider_requests=0, orders_submitted=0)
    if policy.get("leagues"):
        fields.update(scope=policy["scope"], leagues=policy["leagues"])
    if policy.get("sizing_mode"):
        fields["sizing"] = {key: policy[key] for key in (
            "sizing_mode", "sizing_rule", "target_profit_usd", "kelly_multiplier", "reference_bankroll_usd",
            "minimum_stake_usd", "portfolio_rule", "portfolios", "market_scope", "alternate_odds_below"
        ) if key in policy}
    if policy.get("portfolio_rule") == paper.MAIN_FIRST_ONE_PER_GAME:
        selected["portfolio_selection"] = {
            (ticket["game_id"], witnesses[ticket["id"]]["offer_index"]): ticket["portfolio_selection"]
            for name in ("all_venues", "best_venue") for ticket in report["portfolios"][name]["tickets"]}
    return fields, report["games"], selected


def offer_export_game(db, game, minimum, selected, *, sizing=None):
    from .market_census import offer_rows, read_summaries, summarize_coverage

    entry = {key:game.get(key) for key in ("game_id", "title", "status", "checkpoint_id", "exclusions")}
    if "league" in game:
        entry["league"] = game["league"]
    if game["status"] not in ("captured", "reconstructed"):
        return dict(entry, offers=None)
    identity = game["checkpoint_id"]
    index = experiment._closure(db, [identity])
    checkpoint = experiment._value(index[identity], index)
    at = checkpoint["received_at"] if game["status"] == "reconstructed" else experiment.clock(index[identity]["recorded_at"])
    offers = offer_rows(checkpoint, game_id=game["game_id"], minimum=minimum, at=at)
    sizing_exclusions = {item["offer_index"]: item for item in game.get("sizing_exclusions", ())}
    portfolios = sizing.get("portfolios", selected) if sizing else selected
    selection_evidence = selected.get("portfolio_selection")
    show_line_role = selection_evidence is not None or (sizing and sizing.get("market_scope"))
    for offer in offers:
        position = offer["offer_index"]
        key = game["game_id"], position
        offer["selected_tickets"] = {name: selected[name][key] for name in portfolios if key in selected[name]}
        if show_line_role:
            offer["source_line_role"] = _role(checkpoint["snapshot"]["offers"][position]["record"])
        if selection_evidence is not None and key in selection_evidence:
            offer["portfolio_selection"] = selection_evidence[key]
        if sizing and position in sizing_exclusions:
            failure = sizing_exclusions[position]
            offer["sizing"] = dict(state="excluded", **{name: failure[name] for name in (
                "frozen_quote_id", "reason", "cash_commitment_usd", "minimum_stake_usd", "sized_ev"
            ) if name in failure})
        elif sizing and key in selected["all_venues"]:
            offer["sizing"] = dict(state="qualified",
                                   frozen_quote_id=hashed([identity, position, offer["exact_bet_id"]]))
    summary = summarize_coverage(game.get("coverage"), derived=read_summaries(db, [identity]).get(identity))
    return dict(entry, receipt_sha256=checkpoint["snapshot"].get("receipt_sha256"), decision_at=at,
                market_summary=summary, offers=offers)


def offer_export(db, run_id):
    fields, games, selected = offer_export_plan(db, run_id)
    value = dict(fields, games=[offer_export_game(db, game, fields["minimum_ev"], selected,
                                                sizing=fields.get("sizing")) for game in games])
    return dict(value, evidence_sha256=hashed(value))


def _game(report, game_id):
    for game in report["games"]:
        if game["game_id"] == game_id:
            return game
    raise UnknownSelection("Unknown game in this saved run.")


def _source_links(run_id, game_id):
    url = f"/api/research/workspace/runs/{run_id}/evidence/{game_id}"
    return dict(inspect=url, export=url + "?export=1", raw=url + "?raw=1")


def ticket_detail(db, run_id, ticket_id):
    row = _run(db, run_id)
    document = row["payload"]
    witness = document["witnesses"].get(ticket_id)
    if witness is None:
        raise UnknownSelection("Unknown ticket in this saved run.")
    report = document["report"]
    portfolio = report["portfolios"]["all_venues"]
    ticket = next(t for t in portfolio["tickets"] if t["id"] == ticket_id)
    if portfolio.get("candidate_pool_only"):
        ticket = next((t for t in report["portfolios"]["best_venue"]["tickets"] if t["id"] == ticket_id), ticket)
    game = _game(report, ticket["game_id"])
    checkpoint_id, outcome_id = game["checkpoint_id"], game["outcome_id"]
    index = experiment._closure(db, [key for key in (checkpoint_id, outcome_id) if key])
    checkpoint = experiment._value(index[checkpoint_id], index)
    outcome = dict(experiment._value(index[outcome_id], index), id=outcome_id) if outcome_id else None
    original_offer = checkpoint["snapshot"]["offers"][witness["offer_index"]]
    calculated = _sized_calculation(witness)
    links = _source_links(run_id, game["game_id"])
    persisted_at = index[checkpoint_id]["recorded_at"].isoformat()
    trade = paper_evidence.inspect(ticket, checkpoint, original_offer, calculated, report["policy"])
    trade["clocks"]["persisted_at"] = persisted_at
    evidence = dict(checkpoint=dict(id=checkpoint_id, game_id=game["game_id"], revision=checkpoint_id,
        persisted_at=persisted_at,
        **{key: checkpoint.get(key) for key in ("target_at", "deadline_at", "requested_at", "received_at", "known_at", "source_kind", "recovery")}),
        trade=trade,
        sporting_result=outcome, original_offer=original_offer, sized_calculation=calculated, links=links)
    return dict(run=_run_summary(row), ticket=dict(ticket, witness=dict(original_offer=original_offer,
        sized_calculation=calculated)), evidence=evidence, provider_requests=0, orders_submitted=0)


def game_evidence(db, run_id, game_id, *, export=False):
    from app.collection.original_receipts import lookup

    row = _run(db, run_id)
    game = _game(row["payload"]["report"], game_id)
    checkpoint_id = game["checkpoint_id"]
    roots = [key for key in (game["schedule_id"], checkpoint_id, game["outcome_id"], *game["attempt_ids"]) if key]
    index = experiment._closure(db, roots)
    checkpoint = experiment._value(index[checkpoint_id], index) if checkpoint_id else None
    snapshot = checkpoint["snapshot"] if checkpoint else {}
    metadata = None
    if checkpoint:
        metadata = dict({k: v for k, v in checkpoint.items() if k != "snapshot"}, id=checkpoint_id,
                        persisted_at=index[checkpoint_id]["recorded_at"].isoformat())
    receipt = lookup(snapshot.get("receipt_sha256"))
    outcome = experiment._value(index[game["outcome_id"]], index) if game["outcome_id"] else None
    links = _source_links(run_id, game_id)
    result = dict(run=_run_summary(row), game=game, links=links,
        checkpoint=metadata,
        receipt_sha256=snapshot.get("receipt_sha256"), original_response=receipt,
        attempts=[dict(experiment._value(index[key], index), id=key) for key in game["attempt_ids"]],
        sporting_result=outcome, provider_requests=0, orders_submitted=0)
    if export:
        result.update(root_ids=roots, records=[dict(value, recorded_at=value["recorded_at"].isoformat())
                                               for value in index.values()])
        result["manifest"] = dict(bundle_sha256=hashed(result))
    return result


def raw_response(db, run_id, game_id):
    from app.collection.original_receipts import read

    value = game_evidence(db, run_id, game_id)
    receipt = value["original_response"]
    if receipt["state"] == "retained":
        candidates = [row for row in receipt["captures"] if row["state"] == "retained"]
        if candidates:
            metadata, body = read(candidates[-1]["id"])
            return metadata["receipt_sha256"], body
    raise UnknownSelection("Original provider response bytes are unavailable for this frozen capture.")
