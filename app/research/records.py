"""Prospective populations, causal capture and append-only outcome evaluation.

The journal remains the owner of personal decisions and fills. This owner never
filters membership by EV and never treats record count as independent games.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction as F

from app.comparison.current_pregame import COHERENT_POLICY, COHERENT_POLICIES, reference_key
from app.comparison.cashflows import exact_wire as wire
from app.storage.store import Store, encoded, hashed, stamp
from app.storage.current_rows import LOCK as CURRENT_LOCK
from .calculation import freeze, reproduce

VERSION = "prospective-market-research-1"
LOCK = 901112
MAX_CASES = 2048
RECORD_BYTE_CAP = 1024 * 1024
EVALUATION_RECORD_BYTE_CAP = 4 * 1024 * 1024
# Keep the retired cohort's observation sublimit. Current checkpoint and market
# witnesses share the wider allocation under the existing SQL and disk guards.
OBSERVATION_BYTE_CAP = 96 * 1024 * 1024
TOTAL_BYTE_CAP = 2 * 1024 * 1024 * 1024
# Keep the original single-response memory ceiling independent of disk retention.
COHORT_EXPORT_PAYLOAD_BYTE_CAP = 128 * 1024 * 1024
EVIDENCE_RESPONSE_BYTE_CAP = 257 * 1024 * 1024
DISPOSITION_SLOT_BYTES = 2048
ACCOUNTING_BYTES = 2048
DEFAULT_HORIZONS = [3600]


def utc():
    return datetime.now(timezone.utc)


def _clock(value):
    return stamp(value).astimezone(timezone.utc).isoformat()


def _writer_lock(db):
    # Research takes the current-owner lock before its capacity gate. Optional
    # native writes try only the research gate and never wait for current rows.
    db.execute("SELECT pg_advisory_xact_lock(%s)", (CURRENT_LOCK,))
    db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))


def _fingerprint(payload, reason):
    def inputs(value):
        if isinstance(value, list):
            return [inputs(v) for v in value]
        if not isinstance(value, dict):
            return value
        # Re-running identical inputs is not a new source observation. Source
        # and receipt clocks, IDs, revisions, policies and cashflows remain.
        return {k: inputs(v) for k, v in value.items()
                if k not in ("calculated_at", "cutoff", "baseline_id")}
    return hashed([inputs(payload), reason])


def record_byte_cap(kind):
    return EVALUATION_RECORD_BYTE_CAP if kind == "evaluation" else RECORD_BYTE_CAP


def retention_usage(db):
    """One allocation owner for historical research and checkpoint evidence."""
    row = dict(db.execute("""SELECT count(*) records,COALESCE(sum(payload_bytes),0) total,
        COALESCE(sum(payload_bytes) FILTER(WHERE kind='observation'),0) observations,
        max(recorded_at) latest_recorded_at FROM public.research_record""").fetchone())
    slots = db.execute("SELECT count(*) n FROM public.research_retention_disposition").fetchone()["n"]
    row["reserved"] = slots * DISPOSITION_SLOT_BYTES + ACCOUNTING_BYTES
    row.update(experiment_records=0, experiment_bytes=0, experiment_reserved_bytes=0, workspace_bytes=0)
    if db.execute("SELECT to_regclass('public.ev_experiment_record') r").fetchone()["r"]:
        from .experiment_evidence import GAME_METADATA_BYTES, ACCOUNTING_METADATA_BYTES
        extra = db.execute("SELECT count(*) n,COALESCE(sum(payload_bytes),0) bytes,max(recorded_at) latest FROM public.ev_experiment_record").fetchone()
        games = db.execute("SELECT count(*) n,COALESCE(sum(late_reserved_bytes),0) late FROM public.ev_experiment_game").fetchone()
        reserve = games["n"] * GAME_METADATA_BYTES + ACCOUNTING_METADATA_BYTES + int(games["late"])
        row.update(experiment_records=extra["n"], experiment_bytes=extra["bytes"], experiment_reserved_bytes=reserve)
        row["total"] += extra["bytes"]
        row["records"] += extra["n"]
        row["reserved"] += reserve
        if extra["latest"] and (not row["latest_recorded_at"] or extra["latest"] > row["latest_recorded_at"]):
            row["latest_recorded_at"] = extra["latest"]
    if db.execute("SELECT to_regclass('public.market_pull') r").fetchone()["r"]:
        from app.storage.acquisition_snapshot import ORDINARY_PAGE_BYTES

        # The compressed witness is retained once. Charge its derived JSON
        # projection by the allocated relation, including TOAST and indexes.
        market = db.execute('''SELECT COALESCE(sum(bytes),0)
            + pg_total_relation_size('public.market_pull_scope') bytes,
            count(*) FILTER (WHERE page_lease_until > statement_timestamp()) active_pages FROM (
            SELECT allocation_bytes AS bytes, CASE WHEN state='in_progress'
                THEN (details->>'ordinary_page_lease_until')::timestamptz END page_lease_until FROM public.market_pull
            UNION ALL SELECT allocation_bytes,NULL FROM public.market_pull_receipt
            UNION ALL SELECT allocation_bytes,NULL FROM public.market_pull_evidence) allocation''').fetchone()
        row['market_snapshot_bytes'] = int(market['bytes'])
        row['total'] += row['market_snapshot_bytes']
        row['market_page_reserved_bytes'] = market['active_pages'] * ORDINARY_PAGE_BYTES
        row['reserved'] += row['market_page_reserved_bytes']
    if db.execute("SELECT to_regclass('public.research_workspace_run') r").fetchone()['r']:
        workspace = db.execute('''SELECT count(*) n, COALESCE(sum(payload_bytes),0) bytes FROM (
            SELECT payload_bytes FROM public.research_workspace_catalog
            UNION ALL SELECT payload_bytes FROM public.research_workspace_definition
            UNION ALL SELECT payload_bytes FROM public.research_workspace_run
            UNION ALL SELECT payload_bytes FROM public.research_workspace_finding) allocation''').fetchone()
        row['workspace_bytes'] = workspace['bytes']
        row['total'] += workspace['bytes']
        row['records'] += workspace['n']
    if db.execute("SELECT to_regclass('public.mens_d1_receipt') r").fetchone()['r']:
        daily = db.execute("""SELECT
            (SELECT sum(pg_total_relation_size(relation)) FROM unnest(ARRAY[
                 'public.mens_d1_source_state','public.mens_d1_job','public.mens_d1_attempt',
                 'public.mens_d1_receipt','public.mens_d1_revision','public.mens_d1_binding'
            ]::regclass[]) AS relation) bytes,
            (SELECT COALESCE(sum(reserved_storage_bytes),0) FROM public.mens_d1_attempt
             WHERE reserved_storage_bytes>0) reserved""").fetchone()
        row['daily_coverage_bytes'] = int(daily['bytes'])
        row['daily_coverage_reserved_bytes'] = int(daily['reserved'])
        row['total'] += row['daily_coverage_bytes']
        row['reserved'] += row['daily_coverage_reserved_bytes']
    if db.execute("SELECT to_regclass('public.paper_result_report') r").fetchone()['r']:
        # PostgreSQL compresses immutable reports. Keep their canonical payload
        # length for export and new-write admission, and charge allocated storage
        # here using the same rule as the associated job and dependency tables.
        results = db.execute("""SELECT count(*) n,
            (SELECT sum(pg_total_relation_size(relation)) FROM unnest(ARRAY[
                'public.paper_result_report','public.paper_result_job',
                'public.paper_result_dependency','public.paper_result_input'
            ]::regclass[]) AS relation) bytes FROM public.paper_result_report""").fetchone()
        row['paper_result_bytes'] = int(results['bytes'])
        row['total'] += row['paper_result_bytes']
        row['records'] += results['n']
    if db.execute("SELECT to_regclass('public.paper_campaign') r").fetchone()['r']:
        campaign_bytes = db.execute("""SELECT pg_total_relation_size('public.paper_campaign') +
            pg_total_relation_size('public.paper_campaign_day') +
            COALESCE(pg_total_relation_size(to_regclass('public.paper_campaign_retirement')),0) +
            COALESCE(pg_total_relation_size(to_regclass('public.research_run_official_shadow')),0) +
            COALESCE(pg_total_relation_size(to_regclass('public.ev_experiment_checkpoint_commit')),0) bytes""").fetchone()['bytes']
        row['total'] += campaign_bytes
    if db.execute("SELECT to_regclass('public.research_market_census') r").fetchone()['r']:
        census_bytes = db.execute("""SELECT pg_total_relation_size('public.research_market_census')
            + pg_total_relation_size('public.research_market_census_retry') bytes""").fetchone()['bytes']
        row['market_census_bytes'] = census_bytes
        row['total'] += census_bytes
    if db.execute("SELECT to_regclass('public.ev_experiment_depth') r").fetchone()['r']:
        depth = db.execute("""SELECT count(*) n,COALESCE(sum(payload_bytes),0) bytes
            FROM public.ev_experiment_depth""").fetchone()
        row['experiment_depth_bytes'] = depth['bytes']
        row['total'] += depth['bytes']
        row['records'] += depth['n']
    return row


def _record(db, kind, payload, *, cohort_id=None, case_key=None, slot=None):
    body = dict(version=VERSION, kind=kind, **payload)
    identity = hashed(body)
    size = len(encoded(body))
    if size > record_byte_cap(kind):
        raise ValueError("research_record_capacity")
    if db.execute("SELECT 1 FROM public.research_record WHERE id=%s", (identity,)).fetchone():
        return dict(body, id=identity)
    used = retention_usage(db)
    if used["total"] + used["reserved"] + size > TOTAL_BYTE_CAP or (
        kind == "observation" and used["observations"] + size > OBSERVATION_BYTE_CAP
    ):
        raise ValueError("research_retention_capacity")
    from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage, require_disk_space
    from app.storage.store import ROOT
    if sql_usage(db) + size * 3 + 8 * 1024 * 1024 > SQL_BYTE_CAP:
        raise ValueError("research_sql_runway")
    require_disk_space(ROOT / ".local/postgres", append_bytes=size * 3)
    Store(db).immutable("research_record", dict(
        id=identity, kind=kind, cohort_id=cohort_id, case_key=case_key, slot=slot,
        payload_bytes=size, payload=body,
    ), ["id"])
    return dict(body, id=identity)


def _get(db, identity, *, kind=None):
    row = db.execute("SELECT * FROM public.research_record WHERE id=%s", (identity,)).fetchone()
    if not row or kind and row["kind"] != kind:
        raise ValueError("research_record_unknown")
    if hashed(row["payload"]) != row["id"]:
        raise ValueError("research_record_integrity")
    return dict(row["payload"], id=row["id"], recorded_at=row["recorded_at"].isoformat())


def declare(db, *, name, cases, horizons=DEFAULT_HORIZONS, designation="prospective",
            at=None, population_description=None):
    """Freeze exact population and horizons before any EV/outcome inspection."""
    at = at or utc()
    if designation not in ("prospective", "retrospective_replay", "synthetic_demonstration"):
        raise ValueError("research_designation")
    if not isinstance(name, str) or not 1 <= len(name) <= 120:
        raise ValueError("research_cohort_name")
    if (not isinstance(cases, list) or not cases or len(cases) > MAX_CASES
            or not isinstance(horizons, list) or not horizons
            or len(horizons) != len(set(horizons))
            or any(type(h) is not int or not 0 < h <= 7 * 86400 for h in horizons)):
        raise ValueError("research_population_or_horizon_capacity")
    normalized = []
    for item in cases:
        required = ("case_key", "event_id", "starts_at", "family", "period", "line")
        if not isinstance(item, dict) or any(key not in item for key in required):
            raise ValueError("research_exact_case_required")
        if (not isinstance(item["case_key"], str) or not 1 <= len(item["case_key"].encode()) <= 256
                or not isinstance(item["event_id"], str) or not item["event_id"]):
            raise ValueError("research_exact_case_required")
        if designation == "prospective" and any(
            stamp(item["starts_at"]) - timedelta(seconds=h) <= at for h in horizons
        ):
            raise ValueError("research_declaration_after_capture_cutoff")
        case = dict(item, starts_at=_clock(item["starts_at"]))
        if case["line"] is not None:
            case["line"] = wire(F(case["line"]))
        normalized.append(case)
    normalized.sort(key=lambda item: item["case_key"])
    if len({item["case_key"] for item in normalized}) != len(normalized):
        raise ValueError("research_duplicate_case")
    with db.transaction():
        _writer_lock(db)
        required = len(normalized) * len(horizons) * DISPOSITION_SLOT_BYTES
        used = retention_usage(db)
        if used["total"] + used["reserved"] + required + RECORD_BYTE_CAP > TOTAL_BYTE_CAP:
            raise ValueError("research_disposition_capacity")
        cohort = _record(db, "cohort", dict(
            name=name, declared_at=at.isoformat(), designation=designation,
            population=normalized, horizons=sorted(horizons, reverse=True),
            probability_policy=COHERENT_POLICY,
            probability_policies=list(COHERENT_POLICIES),
            population_description=population_description or "Explicit exact market identities; all EV signs and unavailable cases",
            selection_rule="one whole reference pair per exact market and horizon; latest known inputs at cutoff",
            scoring_rule="binary anchor Brier/log-loss; fixed ten-bin calibration; exceptional outcomes excluded with reason",
            trading_results="separate_optional_evidence_stream",
        ))
        for case in normalized:
            for horizon in horizons:
                db.execute("""INSERT INTO public.research_retention_disposition(cohort_id,case_key,slot)
                    VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""", (cohort["id"], case["case_key"], str(horizon)))
        return cohort


def _retention_failure(exc):
    return str(exc) in ("research_record_capacity", "research_retention_capacity", "research_disposition_capacity", "research_sql_runway",
                        "current_observation_disk_free_floor") or isinstance(exc, OSError)


def _activate_accounting(db):
    db.execute("""UPDATE public.research_retention_accounting
        SET coverage_started_at=clock_timestamp() WHERE singleton AND coverage_started_at IS NULL""")


def note_prior_retention_gap(db, *, first_observed_at, evidence_reference):
    """Record sourced historical uncertainty without inventing missed counts."""
    first = stamp(first_observed_at)
    if not isinstance(evidence_reference, str) or not 1 <= len(evidence_reference.encode()) <= 1024:
        raise ValueError("research_retention_evidence_reference")
    with db.transaction():
        _writer_lock(db)
        db.execute("""UPDATE public.research_retention_accounting
            SET prior_first_observed_refusal_at=LEAST(prior_first_observed_refusal_at,%s),
                prior_evidence_reference=%s
            WHERE singleton AND (coverage_started_at IS NULL OR %s<=coverage_started_at)""",
            (first, evidence_reference, first))
    return retention_accounting(db)


def retention_accounting(db):
    row = db.execute("SELECT * FROM public.research_retention_accounting WHERE singleton").fetchone()
    return dict({k: _clock(v) if hasattr(v, "isoformat") else v for k, v in row.items()},
        prior_window_status="uncounted; affected cases and attempts unknown",
        counter_scope="refusals recorded by disposition-aware code from coverage_started_at",
        prior_uncounted_window_end=_clock(row["coverage_started_at"]) if row["coverage_started_at"] else None)


def _disposition(db, cohort_id, case_key, horizon, stage, *, reason=None, fingerprint=None,
                 attempted_bytes=0, at=None):
    if stage not in ("observation", "capture"):
        raise ValueError("research_disposition_stage")
    at = at or utc()
    with db.transaction():
        _writer_lock(db)
        _activate_accounting(db)
        if reason is None:
            db.execute("UPDATE public.research_retention_disposition SET " + stage +
                "_recovered_at=%s,updated_at=clock_timestamp() WHERE cohort_id=%s AND case_key=%s AND slot=%s AND " +
                stage + "_refusals>0 AND " + stage + "_recovered_at IS NULL", (at, cohort_id, case_key, str(horizon)))
        else:
            reason = str(reason).encode()[:160].decode(errors="ignore")
            row = db.execute("UPDATE public.research_retention_disposition SET " + stage + "_refusals=" + stage +
                "_refusals+1," + stage + "_first_refused_at=COALESCE(" + stage + "_first_refused_at,%s)," + stage +
                "_last_refused_at=%s," + stage + "_recovered_at=NULL,last_reason=%s,last_input_fingerprint=%s,"
                "last_attempted_bytes=%s,updated_at=clock_timestamp() WHERE cohort_id=%s AND case_key=%s AND slot=%s RETURNING slot",
                (at, at, reason, fingerprint, attempted_bytes, cohort_id, case_key, str(horizon))).fetchone()
            if not row:
                raise ValueError("research_disposition_slot_unreserved")


def retention_dispositions(db, cohort_id):
    rows = []
    for row in db.execute("SELECT * FROM public.research_retention_disposition WHERE cohort_id=%s ORDER BY case_key,slot", (cohort_id,)):
        rows.append({k: _clock(v) if hasattr(v, "isoformat") else v for k, v in row.items()})
    return rows


def capture_snapshot(capture, records=None, *, db=None):
    """Read old inline captures and new immutable observation references offline."""
    if capture.get("snapshot") is not None:
        return capture["snapshot"]
    if not capture.get("snapshot_id"):
        return None
    identity = capture.get("observation_id")
    observation = _load_observation(identity, records=records, db=db)
    snapshot = observation_snapshot(observation, records=records, db=db)
    if (observation.get("cohort_id") != capture.get("cohort_id")
            or observation.get("case_key") != capture.get("case_key")
            or not snapshot or snapshot.get("id") != capture["snapshot_id"]):
        raise ValueError("research_capture_snapshot_identity")
    return snapshot


def _load_observation(identity, *, records=None, db=None):
    if records is not None:
        observation = records.get(identity)
        if observation is None:
            raise ValueError("research_capture_observation_missing")
        observation = observation.get("payload", observation)
        if hashed(observation) != identity:
            raise ValueError("research_capture_observation_integrity")
    elif db is not None:
        observation = _get(db, identity, kind="observation")
    else:
        raise ValueError("research_capture_observation_missing")
    return observation


def observation_snapshot(observation, records=None, *, db=None, _seen=None):
    observation = observation.get("payload", observation)
    if observation.get("snapshot") is not None:
        return observation["snapshot"]
    if not observation.get("snapshot_id"):
        return None
    identity = observation.get("snapshot_observation_id")
    seen = set(_seen or ())
    if identity in seen or len(seen) >= 64:
        raise ValueError("research_observation_reference_cycle")
    seen.add(identity)
    original = _load_observation(identity, records=records, db=db)
    if (original.get("cohort_id"), original.get("case_key")) != (observation.get("cohort_id"), observation.get("case_key")):
        raise ValueError("research_observation_reference_identity")
    snapshot = observation_snapshot(original, records=records, db=db, _seen=seen)
    if not snapshot or snapshot["id"] != observation["snapshot_id"]:
        raise ValueError("research_observation_snapshot_identity")
    return snapshot


def list_cohorts(db, *, limit=30):
    limit = max(1, min(100, int(limit)))
    return [dict(r["payload"], id=r["id"], recorded_at=r["recorded_at"].isoformat())
            for r in db.execute("SELECT * FROM public.research_record WHERE kind='cohort' ORDER BY recorded_at DESC,id LIMIT %s", (limit,))]


def _observe(db, cohort_id, case_key, payload, *, known_at=None, record=None, fee_input=None,
            unavailable_reason=None, reuse_observation_id=None):
    """Retain a candidate when known, rather than backfilling an earlier cutoff."""
    known_at = known_at or utc()
    with db.transaction():
        _writer_lock(db)
        cohort = _get(db, cohort_id, kind="cohort")
        case = next((c for c in cohort["population"] if c["case_key"] == case_key), None)
        if not case:
            raise ValueError("research_case_outside_population")
        if known_at < stamp(cohort["declared_at"]) and cohort["designation"] == "prospective":
            raise ValueError("research_observation_before_declaration")
        snapshot = None
        if payload is not None:
            clocks = [payload.get("calculated_at"), *(
                (payload.get("times") or {}).get(k) for k in ("source_at", "received_at", "projected_at")
            )]
            clocks += [q.get(k) for q in (payload.get("coherent_probability") or {}).get("prices", [])
                       for k in ("source_at", "received_at")]
            if any(stamp(t) > known_at for t in clocks if t and isinstance(t, str)):
                raise ValueError("research_future_input")
            if payload.get("game_key") != case["event_id"]:
                raise ValueError("research_event_identity_conflict")
            if reuse_observation_id:
                prior = _get(db, reuse_observation_id, kind="observation")
                if (prior.get("cohort_id"), prior.get("case_key"), prior.get("input_fingerprint")) != (
                    cohort_id, case_key, _fingerprint(payload, unavailable_reason)):
                    raise ValueError("research_reaffirmation_input_conflict")
                if stamp(prior["known_at"]) > known_at:
                    raise ValueError("research_future_input")
                snapshot = observation_snapshot(prior, db=db)
                reuse_observation_id = prior.get("snapshot_observation_id") or reuse_observation_id
            else:
                snapshot = freeze(payload, record=record, fee_input=fee_input)
        body = dict(
            cohort_id=cohort_id, case_key=case_key, known_at=known_at.isoformat(),
            reason=unavailable_reason,
            input_fingerprint=_fingerprint(payload, unavailable_reason),
        )
        if reuse_observation_id:
            body.update(snapshot_observation_id=reuse_observation_id,
                        snapshot_id=snapshot["id"] if snapshot else None,
                        observation_kind="reaffirmed_current_inputs")
        else:
            body["snapshot"] = snapshot
        return _record(db, "observation", body, cohort_id=cohort_id, case_key=case_key)


def observe(db, cohort_id, case_key, payload, *, known_at=None, record=None, fee_input=None,
            unavailable_reason=None, reuse_observation_id=None):
    known_at = known_at or utc()
    cohort = _get(db, cohort_id, kind="cohort")
    case = next((c for c in cohort["population"] if c["case_key"] == case_key), None)
    horizons = [h for h in cohort["horizons"] if case and
                known_at <= stamp(case["starts_at"]) - timedelta(seconds=h)]
    try:
        result = _observe(db, cohort_id, case_key, payload, known_at=known_at,
            record=record, fee_input=fee_input, unavailable_reason=unavailable_reason,
            reuse_observation_id=reuse_observation_id)
    except Exception as exc:
        if _retention_failure(exc):
            for horizon in horizons:
                _disposition(db, cohort_id, case_key, horizon, "observation", reason=exc,
                    fingerprint=_fingerprint(payload, unavailable_reason),
                    attempted_bytes=len(encoded([payload, record, fee_input])), at=known_at)
        raise
    for horizon in horizons:
        _disposition(db, cohort_id, case_key, horizon, "observation", at=known_at)
    return result


def capture_due(db, *, at=None, cohort_id=None, limit=128):
    """Freeze due slots, retaining missing/excluded cases without future inputs."""
    at = at or utc()
    if type(limit) is not int or not 1 <= limit <= 2048:
        raise ValueError("research_capture_capacity")
    captured = []
    with db.transaction():
        _writer_lock(db)
        cohorts = [_get(db, cohort_id, kind="cohort")] if cohort_id else list_cohorts(db)
        for cohort in cohorts:
            existing = {(r["case_key"], r["slot"]) for r in db.execute(
                "SELECT case_key,slot FROM public.research_record WHERE kind='capture' AND cohort_id=%s", (cohort["id"],))}
            for case in cohort["population"]:
                for horizon in cohort["horizons"]:
                    slot = str(horizon)
                    cutoff = stamp(case["starts_at"]) - timedelta(seconds=horizon)
                    if cutoff > at or (case["case_key"], slot) in existing:
                        continue
                    row = db.execute("""SELECT * FROM public.research_record
                        WHERE kind='observation' AND cohort_id=%s AND case_key=%s
                          AND (payload->>'known_at')::timestamptz<=%s
                          AND (%s<>'prospective' OR recorded_at<=%s)
                        ORDER BY (payload->>'known_at')::timestamptz DESC,recorded_at DESC,id DESC LIMIT 1""",
                        (cohort["id"], case["case_key"], cutoff, cohort["designation"], cutoff)).fetchone()
                    observation = row["payload"] if row else None
                    snapshot = observation_snapshot(observation, db=db) if observation else None
                    reason = (observation or {}).get("reason")
                    status = "missing"
                    if snapshot:
                        result = reproduce(snapshot)
                        status = "captured" if result["status"] in ("calculated", "probability_only") else "unavailable"
                        reason = result.get("reason")
                    elif observation:
                        status = "unavailable"
                    else:
                        reason = "no_inputs_known_by_capture_cutoff"
                    body = dict(
                        cohort_id=cohort["id"], case_key=case["case_key"], horizon_seconds=horizon,
                        cutoff=cutoff.isoformat(), status=status, reason=reason,
                        observation_id=row["id"] if row else None,
                        snapshot_id=snapshot["id"] if snapshot else None,
                        snapshot_storage="immutable_observation_reference",
                        historical_freshness="not_established",
                    )
                    gap = db.execute("""SELECT observation_refusals,observation_first_refused_at,
                        observation_last_refused_at FROM public.research_retention_disposition
                        WHERE cohort_id=%s AND case_key=%s AND slot=%s""",
                        (cohort["id"], case["case_key"], slot)).fetchone()
                    if gap and gap["observation_refusals"]:
                        body["retention_gaps"] = {k: _clock(v) if hasattr(v, "isoformat") else v for k, v in gap.items()}
                    try:
                        item = _record(db, "capture", body, cohort_id=cohort["id"], case_key=case["case_key"], slot=slot)
                    except Exception as exc:
                        if not _retention_failure(exc):
                            raise
                        _disposition(db, cohort["id"], case["case_key"], horizon, "capture", reason=exc,
                                     attempted_bytes=len(encoded(body)), at=at)
                        continue
                    _disposition(db, cohort["id"], case["case_key"], horizon, "capture", at=at)
                    captured.append(item)
                    if len(captured) >= limit:
                        return captured
    return captured


def annotate(db, cohort_id, case_key, kind, data, *, supersedes_id=None, reason=None, at=None):
    """Append sporting results or separate venue settlement, including corrections."""
    at = at or utc()
    if kind not in ("sporting", "settlement"):
        raise ValueError("research_outcome_kind")
    if (not isinstance(data, dict) or any(k not in data for k in
            ("source", "published_at", "observed_at", "final"))
            or not data["source"] or type(data["final"]) is not bool):
        raise ValueError("research_outcome_source_clocks_required")
    if (stamp(data["observed_at"]) > at or data["published_at"] is not None
            and stamp(data["published_at"]) > stamp(data["observed_at"])):
        raise ValueError("research_outcome_clock_order")
    with db.transaction():
        _writer_lock(db)
        cohort = _get(db, cohort_id, kind="cohort")
        case = next((c for c in cohort["population"] if c["case_key"] == case_key), None)
        if not case:
            raise ValueError("research_case_outside_population")
        if kind == "sporting":
            if data["final"] and stamp(data["published_at"] or data["observed_at"]) < stamp(case["starts_at"]):
                raise ValueError("research_final_result_before_start")
            if data.get("result") not in ("completed", "cancelled", "unresolved"):
                raise ValueError("research_sporting_result_required")
            if data["result"] == "completed" and any(
                type(data.get(k)) is not int or data[k] < 0 for k in ("home_score", "away_score")
            ):
                raise ValueError("research_exact_sporting_scores_required")
        else:
            if any(not data.get(k) for k in ("contract_id", "basis")) or "payout_per_contract" not in data:
                raise ValueError("research_separate_settlement_identity_required")
            if data["payout_per_contract"] is not None and not 0 <= F(data["payout_per_contract"]) <= 1:
                raise ValueError("research_settlement_payout_invalid")
        prior = db.execute("""SELECT id FROM public.research_record WHERE cohort_id=%s AND case_key=%s AND kind=%s
            ORDER BY recorded_at DESC,id DESC LIMIT 1""", (cohort_id, case_key, kind)).fetchone()
        if prior and (supersedes_id != prior["id"] or not reason) or not prior and supersedes_id:
            raise ValueError("research_outcome_correction_requires_latest_and_reason")
        return _record(db, kind, dict(
            cohort_id=cohort_id, case_key=case_key, data=data,
            known_at=at.isoformat(), supersedes_id=supersedes_id, correction_reason=reason,
        ), cohort_id=cohort_id, case_key=case_key)


def resolved_side(case, data):
    if not data["final"]:
        return None, "sporting_outcome_not_final"
    if data["result"] != "completed":
        return None, "sporting_" + data["result"]
    home, away = F(data["home_score"]), F(data["away_score"])
    if case["period"] != "full_game":
        return None, "outcome_period_unsupported"
    if case["line"] is not None and F(case["line"]).denominator not in (1, 2):
        return None, "outcome_line_settlement_unsupported"
    if case["family"] == "moneyline":
        delta, sides = home - away, ("home", "away")
    elif case["family"] == "spread" and case["line"] is not None:
        delta, sides = home + F(case["line"]) - away, ("home", "away")
    elif case["family"] == "total" and case["line"] is not None:
        delta, sides = home + away - F(case["line"]), ("over", "under")
    else:
        return None, "outcome_market_unsupported"
    if delta == 0:
        return None, "tie_or_push_outside_decisive_conditioning"
    return sides[0 if delta > 0 else 1], None


def scores(probability, actual):
    p = F(probability)
    if not 0 < p < 1 or actual not in (0, 1):
        raise ValueError("research_binary_probability_invalid")
    brier = (p - actual) ** 2
    with localcontext() as ctx:
        ctx.prec = 40
        likelihood = p if actual else 1 - p
        value = Decimal(likelihood.numerator) / Decimal(likelihood.denominator)
        loss = -value.ln()
    return dict(brier=wire(brier), log_loss=str(loss))


def _prior_gap_exclusion(db, cohort_id, case_key, cutoff, accounting):
    start = accounting.get("prior_first_observed_refusal_at")
    if not start or stamp(cutoff) < stamp(start):
        return None
    end = accounting.get("coverage_started_at")
    if end and stamp(cutoff) >= stamp(end):
        row = db.execute("""SELECT payload FROM public.research_record
            WHERE kind='observation' AND cohort_id=%s AND case_key=%s
              AND recorded_at>=%s AND recorded_at<=%s
              AND (payload->>'known_at')::timestamptz>=%s
              AND (payload->>'known_at')::timestamptz<=%s
            ORDER BY (payload->>'known_at')::timestamptz DESC,recorded_at DESC,id DESC LIMIT 1""",
            (cohort_id, case_key, end, cutoff, end, cutoff)).fetchone()
        if row:
            snapshot = observation_snapshot(row["payload"], db=db)
            if snapshot and reproduce(snapshot).get("probability") is not None:
                return None
    return "prior_uncounted_retention_gap"


def evaluate(db, cohort_id, *, as_of=None, persist=False):
    """Keep future slots pending; resolve due slots at the knowledge cutoff."""
    as_of = as_of or utc()
    cohort = _get(db, cohort_id, kind="cohort")
    cases = {c["case_key"]: c for c in cohort["population"]}
    captures = list(db.execute("""SELECT * FROM public.research_record
        WHERE cohort_id=%s AND kind='capture' AND recorded_at<=%s ORDER BY case_key,slot""", (cohort_id, as_of)))
    # Synthetic fixture clocks are explicit; their actual persistence timestamps
    # remain available, and their scores never masquerade as prospective results.
    if cohort["designation"] == "synthetic_demonstration":
        captures = list(db.execute("SELECT * FROM public.research_record WHERE cohort_id=%s AND kind='capture' ORDER BY case_key,slot", (cohort_id,)))
    by_slot = {(r["case_key"], r["slot"]): r for r in captures}
    dispositions = retention_dispositions(db, cohort_id)
    for disposition in dispositions:
        key = (disposition["case_key"], disposition["slot"])
        first = disposition["capture_first_refused_at"]
        if key not in by_slot and first and stamp(first) <= as_of:
            by_slot[key] = dict(id=None, payload=dict(status="missing",
                reason="capture_retention_refused:" + (disposition["last_reason"] or "unknown")))
    snapshots = {key: capture_snapshot(row["payload"], db=db) for key, row in by_slot.items()}
    accounting = retention_accounting(db)
    gap_exclusions = {key: _prior_gap_exclusion(db, cohort_id, key[0], row["payload"]["cutoff"], accounting)
        for key, row in by_slot.items() if row["payload"].get("status") == "captured"}
    results = []
    calibration = [dict(lower=wire(F(i, 10)), upper=wire(F(i + 1, 10)), count=0,
                        probability_sum=F(0), actual_sum=0) for i in range(10)]
    for case_key, case in cases.items():
        for horizon in cohort["horizons"]:
            row = by_slot.get((case_key, str(horizon)))
            cutoff = stamp(case["starts_at"]) - timedelta(seconds=horizon)
            item = dict(case_key=case_key, event_id=case["event_id"], horizon_seconds=horizon,
                        capture_cutoff=cutoff.isoformat(), due=cutoff<=as_of,
                        status="missing", reason="capture_missing_at_due_cutoff", capture_id=None,
                        outcome_id=None, brier=None, log_loss=None)
            if cutoff > as_of:
                item.update(status="pending", reason="capture_horizon_not_due")
                results.append(item); continue
            if not row:
                results.append(item); continue
            capture = row["payload"]
            item["capture_id"] = row["id"]
            if gap_exclusions.get((case_key, str(horizon))):
                item.update(status="excluded", reason=gap_exclusions[(case_key, str(horizon))])
                results.append(item); continue
            if capture["status"] != "captured":
                item.update(status="missing" if capture["status"] == "missing" else "excluded", reason=capture["reason"])
                results.append(item); continue
            outcome = db.execute("""SELECT * FROM public.research_record
                WHERE cohort_id=%s AND case_key=%s AND kind='sporting'
                  AND (payload->>'known_at')::timestamptz<=%s
                  AND (%s='synthetic_demonstration' OR recorded_at<=%s)
                ORDER BY recorded_at DESC,id DESC LIMIT 1""", (cohort_id, case_key, as_of, cohort["designation"], as_of)).fetchone()
            if not outcome:
                item["reason"] = "sporting_outcome_missing"
                results.append(item); continue
            item["outcome_id"] = outcome["id"]
            side, reason = resolved_side(case, outcome["payload"]["data"])
            if side is None:
                item.update(status="excluded", reason=reason)
                results.append(item); continue
            snapshot = snapshots[(case_key, str(horizon))]
            reproduce(snapshot)
            ref = snapshot["inputs"]["calculation"]["coherent_probability"]
            anchor = "over" if case["family"] == "total" else "home"
            p = F(ref["probabilities"][anchor])
            actual = int(side == anchor)
            item.update(status="scored", reason=None, probability=wire(p), actual=actual,
                        probability_policy=ref["policy_version"], **scores(p, actual))
            bucket = calibration[min(9, int(p * 10))]
            bucket["count"] += 1; bucket["probability_sum"] += p; bucket["actual_sum"] += actual
            results.append(item)
    scored = [r for r in results if r["status"] == "scored"]
    counts = Counter(r["status"] for r in results)
    for bucket in calibration:
        n = bucket["count"]
        total_probability, total_actual = bucket.pop("probability_sum"), bucket.pop("actual_sum")
        bucket["mean_probability"] = wire(total_probability / n) if n else None
        bucket["observed_frequency"] = wire(F(total_actual, n)) if n else None
    summary = dict(
        cohort_id=cohort_id, as_of=as_of.isoformat(), designation=cohort["designation"],
        probability_policy=cohort["probability_policy"],
        population_records=len(results), distinct_events=len({r["event_id"] for r in results}),
        due_records=sum(r["due"] for r in results), future_records=sum(not r["due"] for r in results),
        due_distinct_events=len({r["event_id"] for r in results if r["due"]}),
        future_distinct_events=len({r["event_id"] for r in results if not r["due"]}),
        scored_records=len(scored), scored_distinct_events=len({r["event_id"] for r in scored}),
        status_counts=dict(counts), records=results,
        mean_brier=wire(sum((F(r["brier"]) for r in scored), F(0)) / len(scored)) if scored else None,
        mean_log_loss=str(sum((Decimal(r["log_loss"]) for r in scored), Decimal(0)) / len(scored)) if scored else None,
        calibration=calibration,
        policy_comparison=_policy_comparison(db, cohort, by_slot, as_of, snapshots=snapshots, gap_exclusions=gap_exclusions),
        retention_accounting=accounting,
        retention_dispositions=[d for d in dispositions if d["observation_refusals"] or d["capture_refusals"]],
        limitations=["Repeated horizons/markets from one event are dependent samples",
                     "Probability quality requires outcome evidence; arithmetic tests do not establish calibration",
                     "Sporting outcomes are separate from venue settlement and actual fills",
                     "Archive replay is top-only where depth was not retained; freshness is not established"],
    )
    if persist:
        with db.transaction():
            _writer_lock(db)
            return _record(db, "evaluation", summary, cohort_id=cohort_id)
    return summary


def _policy_comparison(db, cohort, captures, as_of, *, snapshots=None, gap_exclusions=None):
    """Every policy sees the same declared slots, including its missing cases."""
    policies = cohort.get("probability_policies", [cohort["probability_policy"]])
    results = {policy: [] for policy in policies}
    for case in cohort["population"]:
        outcome = db.execute("""SELECT * FROM public.research_record
            WHERE cohort_id=%s AND case_key=%s AND kind='sporting'
              AND (payload->>'known_at')::timestamptz<=%s
              AND (%s='synthetic_demonstration' OR recorded_at<=%s)
            ORDER BY recorded_at DESC,id DESC LIMIT 1""", (cohort["id"], case["case_key"], as_of, cohort["designation"], as_of)).fetchone()
        for horizon in cohort["horizons"]:
            row = captures.get((case["case_key"], str(horizon)))
            snapshot = (snapshots or {}).get((case["case_key"], str(horizon)))
            cutoff = stamp(case["starts_at"]) - timedelta(seconds=horizon)
            for policy in policies:
                item = dict(case_key=case["case_key"], event_id=case["event_id"],
                    horizon_seconds=horizon, capture_id=row["id"] if row else None,
                    capture_cutoff=cutoff.isoformat(), due=cutoff<=as_of,
                    outcome_id=outcome["id"] if outcome else None,
                    status="missing", reason="capture_missing_at_due_cutoff", brier=None, log_loss=None)
                if cutoff > as_of:
                    item.update(status="pending", reason="capture_horizon_not_due", capture_id=None, outcome_id=None)
                    results[policy].append(item); continue
                if (gap_exclusions or {}).get((case["case_key"], str(horizon))):
                    item.update(status="excluded", reason=gap_exclusions[(case["case_key"], str(horizon))])
                elif not snapshot:
                    item["reason"] = row["payload"]["reason"] if row else item["reason"]
                else:
                    reproduce(snapshot)
                    calculation = snapshot["inputs"]["calculation"]
                    reference = (calculation.get("coherent_probability")
                        if policy == cohort["probability_policy"] else
                        calculation.get("alternative_probabilities", {}).get(policy))
                    if not reference or not reference.get("probabilities"):
                        item.update(status="excluded", reason=(reference or {}).get("reason") or "policy_probability_unavailable")
                    elif not outcome:
                        item["reason"] = "sporting_outcome_missing"
                    else:
                        side, reason = resolved_side(case, outcome["payload"]["data"])
                        if side is None:
                            item.update(status="excluded", reason=reason)
                        else:
                            anchor = "over" if case["family"] == "total" else "home"
                            p = F(reference["probabilities"][anchor])
                            item.update(status="scored", reason=None, probability=wire(p),
                                actual=int(side == anchor), **scores(p, int(side == anchor)))
                results[policy].append(item)
    summaries = []
    for policy, rows in results.items():
        scored = [r for r in rows if r["status"] == "scored"]
        summaries.append(dict(policy_version=policy, population_records=len(rows),
            due_records=sum(r["due"] for r in rows), future_records=sum(not r["due"] for r in rows),
            due_distinct_events=len({r["event_id"] for r in rows if r["due"]}),
            future_distinct_events=len({r["event_id"] for r in rows if not r["due"]}),
            distinct_events=len({r["event_id"] for r in rows}), scored_records=len(scored),
            scored_distinct_events=len({r["event_id"] for r in scored}),
            status_counts=dict(Counter(r["status"] for r in rows)),
            mean_brier=wire(sum((F(r["brier"]) for r in scored), F(0)) / len(scored)) if scored else None,
            mean_log_loss=str(sum((Decimal(r["log_loss"]) for r in scored), Decimal(0)) / len(scored)) if scored else None,
            records=rows))
    return summaries


def detail(db, cohort_id):
    cohort = _get(db, cohort_id, kind="cohort")
    return dict(cohort=cohort, evaluation=evaluate(db, cohort_id), provider_requests=0)


def export_cohort(db, cohort_id):
    """Export every retained cohort revision as one bounded, verifiable bundle.

    One SQL statement supplies the immutable set and its actual persistence
    clocks. Summary reads stay small; export never acquires data or appends a
    freshly computed evaluation that could differ from the exported evidence.
    """
    payload_byte_cap = min(TOTAL_BYTE_CAP, COHORT_EXPORT_PAYLOAD_BYTE_CAP)
    rows = db.execute("""SELECT id,kind,cohort_id,case_key,slot,recorded_at,payload_bytes,
        CASE WHEN sum(payload_bytes) OVER ()<=%s THEN payload END payload,
        statement_timestamp() AS export_statement_at
        FROM public.research_record
        WHERE (id=%s AND kind='cohort') OR cohort_id=%s
        ORDER BY recorded_at,id""", (payload_byte_cap, cohort_id, cohort_id))
    exported = []
    payload_bytes = 0
    declaration = None
    saved_evaluations = []
    for row in rows:
        payload = row["payload"]
        if payload is None:
            raise ValueError("research_export_capacity")
        size = len(encoded(payload))
        if (hashed(payload) != row["id"] or size != row["payload_bytes"]
                or payload.get("kind") != row["kind"]):
            raise ValueError("research_export_record_integrity")
        payload_bytes += size
        if size > record_byte_cap(row["kind"]):
            raise ValueError("research_export_capacity")
        item = {key: row[key] for key in
                ("id", "kind", "cohort_id", "case_key", "slot", "payload_bytes", "payload")}
        item["recorded_at"] = _clock(row["recorded_at"])
        exported.append(item)
        if row["kind"] == "cohort" and row["id"] == cohort_id:
            declaration = item
        elif row["cohort_id"] != cohort_id or payload.get("cohort_id") != cohort_id:
            raise ValueError("research_export_cohort_integrity")
        if row["kind"] == "evaluation":
            saved_evaluations.append(dict(
                id=item["id"], recorded_at=item["recorded_at"],
                **{key: payload.get(key) for key in (
                    "as_of", "designation", "population_records", "distinct_events",
                    "due_records", "future_records", "due_distinct_events", "future_distinct_events",
                    "scored_records", "scored_distinct_events", "status_counts",
                    "probability_policy", "mean_brier", "mean_log_loss",
                )},
            ))
    if declaration is None:
        raise ValueError("research_record_unknown")
    cohort = declaration["payload"]
    body = dict(
        schema="predict-research-cohort-export-1", cohort_id=cohort_id,
        exported_at=_clock(row["export_statement_at"]),
        cohort=dict(id=cohort_id, recorded_at=declaration["recorded_at"],
            **{key: cohort.get(key) for key in
               ("name", "declared_at", "designation", "horizons", "probability_policy", "probability_policies")},
            population_records=len(cohort["population"])),
        evaluation=dict(
            saved_count=len(saved_evaluations), saved=saved_evaluations,
            latest_saved_id=saved_evaluations[-1]["id"] if saved_evaluations else None,
            current_recomputed=False,
            reason=None if saved_evaluations else "no_saved_evaluation",
        ),
        records=exported,
        research_retention=status(db),
        retention_dispositions=retention_dispositions(db, cohort_id),
        retention_observed_at=_clock(utc()),
        completeness="all_retained_cohort_records_in_one_sql_snapshot; no_truncation",
        provider_requests=0,
    )
    # Immutable envelopes add IDs, persistence clocks and audit metadata to the
    # already bounded retained payloads. Reserve a bounded API allocation rather
    # than rejecting valid near-cap state or changing the storage allowance.
    export_byte_cap = EVIDENCE_RESPONSE_BYTE_CAP
    bundle = dict(body, manifest=dict(
        record_count=len(exported), records_by_kind=dict(Counter(r["kind"] for r in exported)),
        total_payload_bytes=payload_bytes, retained_payload_byte_cap=payload_byte_cap,
        canonical_byte_cap=export_byte_cap,
        payload_hash="each record id is SHA256 of its canonical JSON payload",
        bundle_sha256=hashed(body),
        bundle_hash_scope="all top-level fields except manifest; canonical JSON uses app.storage.store.encoded",
    ))
    index = {item["id"]: item for item in exported}
    for item in exported:
        if item["kind"] == "capture":
            capture_snapshot(item["payload"], index)
    # A capacity refusal is explicit; silently omitting older revisions is unsafe.
    if len(encoded(bundle)) + 1 > export_byte_cap:
        raise ValueError("research_export_capacity")
    return bundle


def retention_disposition_summary(db):
    return db.execute("""SELECT count(*) slots,COALESCE(sum(observation_refusals),0)::bigint observation_refusals,
        COALESCE(sum(capture_refusals),0)::bigint capture_refusals,
        count(*) FILTER(WHERE observation_refusals>0 AND observation_recovered_at IS NULL) observation_open_gaps,
        count(*) FILTER(WHERE capture_refusals>0 AND capture_recovered_at IS NULL) capture_open_gaps,
        count(*) FILTER(WHERE observation_refusals>0) observation_affected_slots,
        count(*) FILTER(WHERE capture_refusals>0) capture_affected_slots
        FROM public.research_retention_disposition""").fetchone()


def status(db):
    used = retention_usage(db)
    row = dict(records=used["records"], retained_bytes=used["total"], observation_bytes=used["observations"],
               latest_recorded_at=used["latest_recorded_at"], experiment_records=used["experiment_records"],
               experiment_payload_bytes=used["experiment_bytes"], experiment_allocation_bytes=used["experiment_reserved_bytes"],
               workspace_bytes=used['workspace_bytes'])
    if row["latest_recorded_at"] is not None:
        row["latest_recorded_at"] = row["latest_recorded_at"].isoformat()
    allocation = used["reserved"]
    return dict(row, byte_cap=TOTAL_BYTE_CAP, observation_byte_cap=OBSERVATION_BYTE_CAP,
                record_byte_caps=dict(ordinary=RECORD_BYTE_CAP, evaluation=EVALUATION_RECORD_BYTE_CAP),
                disposition_allocation_bytes=allocation, total_allocation_bytes=row["retained_bytes"]+allocation,
                retention_dispositions=retention_disposition_summary(db), retention_accounting=retention_accounting(db),
                provider_requests=0)


def preserve_conditional(db, payload, *, record=None, fee_input=None,
                         reason="provider_venue_fee_applicability_unestablished"):
    """Keep a former numeric witness before withdrawing current applicability.

    This is outside a prospective population and does not mint a new forecast.
    The original payload and asserted input shape remain exactly as retained.
    """
    with db.transaction():
        _writer_lock(db)
        return _record(db, "observation", dict(
            designation="historical_conditional_calculation",
            reason=reason,
            original_calculation=payload, source_record=record, fee_input=fee_input,
        ), case_key=payload["id"])


def conditional_history(db, contract_id, *, limit=20):
    limit = max(1, min(100, int(limit)))
    return [dict(r["payload"], id=r["id"], recorded_at=r["recorded_at"].isoformat())
        for r in db.execute("""SELECT * FROM public.research_record
            WHERE kind='observation' AND cohort_id IS NULL AND case_key=%s
              AND payload->>'designation'='historical_conditional_calculation'
            ORDER BY recorded_at DESC,id DESC LIMIT %s""", (contract_id, limit))]


def _case(row):
    record = row.get("record") or dict(row["contract"], event=row["event"])
    event = record["event"]
    market = record["market_identity"]
    try:
        family, _, line = reference_key(record)
        identity_reason = None
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        family, line, identity_reason = market["family"], None, str(exc)
    key = hashed([row["game_key"], market["period"], family, wire(line) if line is not None else None,
                  row["contract_id"] if identity_reason else None])
    payload = row.get("payload") or {}
    source_ids = list(payload.get("sportsbook_event_ids") or [])
    if row["provider"] == "sportsgameodds" and row["native_event_id"] not in source_ids:
        source_ids.append(row["native_event_id"])
    return dict(
        case_key=key, event_id=row["game_key"], starts_at=event["scheduled_start"],
        family=family, period=market["period"], line=wire(line) if line is not None else None,
        home=event["home"], away=event["away"], league=event["competition"],
        source_event_ids=sorted(source_ids), identity_reason=identity_reason,
    )


def _current_population(db, at):
    # Membership uses every current calculation disposition, with no predicate
    # on EV, fees, probability or reason. The declared population is the bounded
    # primary normalized path, not every raw unsupported provider field.
    return list(db.execute("""SELECT c.contract_id,c.game_key,c.reason,e.provider,e.native_event_id,
        e.facts AS event,t.facts AS contract,p.record,p.fee_input,p.payload,c.payload AS calculation
        FROM public.current_pregame_calculation c
        JOIN public.current_contract t ON t.id=c.contract_id
        JOIN public.current_event e ON e.id=t.event_id
        LEFT JOIN public.current_pregame_price p ON p.contract_id=c.contract_id
        WHERE c.start_at>%s AND c.start_at<=%s
        ORDER BY c.game_key,c.family,c.venue,c.contract_id""", (at, at + timedelta(days=7))))


def automatic_turn(db, *, at=None):
    """Normal collector-side research scheduling; passive reads never call it.

    Once daily, freeze the exact known population before inspecting values.
    Later-discovered identities wait for a later declaration; the name and
    population description make that boundary visible rather than backfilling.
    """
    supplied_clock = at is not None
    at = at or utc()
    with db.transaction():
        _writer_lock(db)
        _activate_accounting(db)
    accounting = retention_accounting(db)
    if not supplied_clock:
        at = utc()
    captured = capture_due(db, at=at)
    name = "daily-primary-pregame:" + at.astimezone(timezone.utc).date().isoformat()
    rows = _current_population(db, at)
    existing = db.execute("SELECT id FROM public.research_record WHERE kind='cohort' AND payload->>'name'=%s", (name,)).fetchone()
    declared = None
    declaration_refused = None
    if not existing:
        cases = {}
        for row in rows:
            case = _case(row)
            if stamp(case["starts_at"]) - timedelta(seconds=max(DEFAULT_HORIZONS)) <= at:
                continue
            cases.setdefault(case["case_key"], case)
        if cases:
            try:
                declared = declare(
                    db, name=name, cases=list(cases.values()), at=at,
                    population_description="All primary normalized exact market identities known at this daily declaration; all calculation statuses and EV signs; starts within seven days, more than one hour ahead. Later discoveries are outside this frozen population.",
                )
            except Exception as exc:
                if not _retention_failure(exc):
                    raise
                declaration_refused = str(exc)
                with db.transaction():
                    _writer_lock(db)
                    db.execute("""UPDATE public.research_retention_accounting SET declaration_refusals=declaration_refusals+1,
                        last_declaration_refused_at=%s,last_declaration_reason=%s,last_declaration_population=%s WHERE singleton""",
                        (at, declaration_refused[:160], len(cases)))
    by_key = {}
    for row in rows:
        case = _case(row)
        by_key.setdefault(case["case_key"], row)
    observed = skipped = refused = 0
    for cohort in list_cohorts(db):
        if cohort["designation"] != "prospective":
            continue
        gap_cases = {d["case_key"] for d in retention_dispositions(db, cohort["id"])
                     if d["observation_refusals"] and d["observation_recovered_at"] is None}
        for case in cohort["population"]:
            if stamp(case["starts_at"]) - timedelta(seconds=min(cohort["horizons"])) < at:
                continue
            row = by_key.get(case["case_key"])
            payload = (row.get("calculation") or row.get("payload")) if row else None
            why = (row.get("reason") if row else "current_identity_missing")
            if payload is None and row and case["identity_reason"] is None:
                # Probability evaluation does not require a known execution fee.
                # Use retained pairs while leaving net EV and cashflows unknown.
                from app.comparison import current_pregame as math
                refs = {}
                for eid in case["source_event_ids"]:
                    refs[eid] = list(db.execute("SELECT id,revision,facts FROM public.current_sgo_reference WHERE event_id=%s", (eid,)))
                record = dict(row["contract"], event=row["event"])
                try:
                    ref = math.qualified_coherent_reference(record, refs, at=at)
                except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
                    ref = dict(policy_version=COHERENT_POLICY, probability=None,
                               probabilities=None, reason=str(exc))
                payload = dict(
                    id=row["contract_id"], game_key=case["event_id"], kickoff=case["starts_at"],
                    family=case["family"], period=case["period"],
                    selection=row["contract"]["selection"], calculated_at=at.isoformat(),
                    times=dict(source_at=None, received_at=None), fee=None,
                    coherent_probability=ref, reference=None, raw=dict(net_ev=None),
                )
            prior = db.execute("""SELECT id,payload,recorded_at FROM public.research_record WHERE kind='observation'
                AND cohort_id=%s AND case_key=%s ORDER BY recorded_at DESC,id DESC LIMIT 1""", (cohort["id"], case["case_key"])).fetchone()
            same = prior and prior["payload"].get("input_fingerprint") == _fingerprint(payload, why)
            prior_window = accounting.get("prior_first_observed_refusal_at")
            cutover = accounting.get("coverage_started_at")
            reaffirm = same and (case["case_key"] in gap_cases or prior_window and cutover
                and (prior["recorded_at"] < stamp(cutover) or stamp(prior["payload"]["known_at"]) < stamp(cutover))
                and stamp(case["starts_at"]) - timedelta(seconds=min(cohort["horizons"])) >= stamp(prior_window))
            if same and not reaffirm:
                skipped += 1
                continue
            try:
                observe(db, cohort["id"], case["case_key"], payload, known_at=at,
                        record=row.get("record") if row and row.get("payload") else None,
                        fee_input=row.get("fee_input") if row and row.get("payload") else None,
                        unavailable_reason=why, reuse_observation_id=prior["id"] if reaffirm else None)
            except Exception as exc:
                if not _retention_failure(exc):
                    raise
                refused += 1
                continue
            observed += 1
    return dict(declared_cohort=declared["id"] if declared else None,
                state="degraded" if refused or declaration_refused else "ready", refused_observations=refused,
                declaration_refused=declaration_refused,
                new_observations=observed, unchanged=skipped, captured=len(captured), **status(db))


def import_sporting(db, observations):
    """Attach bounded original sporting results through exact source/event roles."""
    if not isinstance(observations, list) or len(observations) > MAX_CASES:
        raise ValueError("research_sporting_import_capacity")
    cohorts = list_cohorts(db, limit=100)
    result = dict(matched=0, unmatched=0, unchanged=0)
    for observation in observations:
        matches = []
        for cohort in cohorts:
            for case in cohort["population"]:
                if (observation["event_id"] in case.get("source_event_ids", ())
                        and stamp(observation["starts_at"]) == stamp(case["starts_at"])
                        and observation.get("home") == case.get("home")
                        and observation.get("away") == case.get("away")
                        and observation.get("league") == case.get("league")):
                    matches.append((cohort, case))
        def exact_score(value):
            if value is None or isinstance(value, bool):
                return None
            number = F(value)
            if number < 0 or number.denominator != 1:
                return None
            return int(number)

        data = dict(
            source=observation["source"], published_at=observation.get("published_at"),
            observed_at=observation["received_at"], final=observation["final"],
            result=observation.get("result") or ("completed" if observation["final"] else "unresolved"),
            home_score=exact_score(observation.get("home_score")), away_score=exact_score(observation.get("away_score")),
            receipt_sha256=observation.get("receipt_sha256"),
            source_result=observation,
        )
        if not matches:
            with db.transaction():
                _writer_lock(db)
                _record(db, "sporting", dict(mapping_status="unmatched",
                    reason="declared_exact_event_or_roles_unavailable", source_result=observation))
            result["unmatched"] += 1
            continue
        for cohort, case in matches:
            prior = db.execute("""SELECT id,payload FROM public.research_record
                WHERE cohort_id=%s AND case_key=%s AND kind='sporting'
                ORDER BY recorded_at DESC,id DESC LIMIT 1""", (cohort["id"], case["case_key"])).fetchone()
            if prior and prior["payload"]["data"] == data:
                result["unchanged"] += 1
                continue
            annotate(db, cohort["id"], case["case_key"], "sporting", data,
                supersedes_id=prior["id"] if prior else None,
                reason="provider sporting result revision" if prior else None,
                at=stamp(observation["knowledge_at"]))
            result["matched"] += 1
    return result
