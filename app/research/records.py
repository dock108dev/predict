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
OBSERVATION_BYTE_CAP = 16 * 1024 * 1024
TOTAL_BYTE_CAP = 32 * 1024 * 1024
DEFAULT_HORIZONS = [3600]


def utc():
    return datetime.now(timezone.utc)


def _clock(value):
    return stamp(value).astimezone(timezone.utc).isoformat()


def _writer_lock(db):
    # Serialize the whole-database capacity check with existing ingress writers.
    # All research mutations take the current-owner lock first, then their own.
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


def _record(db, kind, payload, *, cohort_id=None, case_key=None, slot=None):
    body = dict(version=VERSION, kind=kind, **payload)
    identity = hashed(body)
    size = len(encoded(body))
    if size > RECORD_BYTE_CAP:
        raise ValueError("research_record_capacity")
    if db.execute("SELECT 1 FROM public.research_record WHERE id=%s", (identity,)).fetchone():
        return dict(body, id=identity)
    used = db.execute("""SELECT COALESCE(sum(payload_bytes),0) total,
        COALESCE(sum(payload_bytes) FILTER(WHERE kind='observation'),0) observations
        FROM public.research_record""").fetchone()
    if used["total"] + size > TOTAL_BYTE_CAP or (
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
        if not item["case_key"] or not item["event_id"]:
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
        return _record(db, "cohort", dict(
            name=name, declared_at=at.isoformat(), designation=designation,
            population=normalized, horizons=sorted(horizons, reverse=True),
            probability_policy=COHERENT_POLICY,
            probability_policies=list(COHERENT_POLICIES),
            population_description=population_description or "Explicit exact market identities; all EV signs and unavailable cases",
            selection_rule="one whole reference pair per exact market and horizon; latest known inputs at cutoff",
            scoring_rule="binary anchor Brier/log-loss; fixed ten-bin calibration; exceptional outcomes excluded with reason",
            trading_results="separate_optional_evidence_stream",
        ))


def list_cohorts(db, *, limit=30):
    limit = max(1, min(100, int(limit)))
    return [dict(r["payload"], id=r["id"], recorded_at=r["recorded_at"].isoformat())
            for r in db.execute("SELECT * FROM public.research_record WHERE kind='cohort' ORDER BY recorded_at DESC,id LIMIT %s", (limit,))]


def observe(db, cohort_id, case_key, payload, *, known_at=None, record=None, fee_input=None,
            unavailable_reason=None):
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
            snapshot = freeze(payload, record=record, fee_input=fee_input)
        return _record(db, "observation", dict(
            cohort_id=cohort_id, case_key=case_key, known_at=known_at.isoformat(),
            snapshot=snapshot, reason=unavailable_reason,
            input_fingerprint=_fingerprint(payload, unavailable_reason),
        ), cohort_id=cohort_id, case_key=case_key)


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
                    snapshot = observation.get("snapshot") if observation else None
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
                    captured.append(_record(db, "capture", dict(
                        cohort_id=cohort["id"], case_key=case["case_key"], horizon_seconds=horizon,
                        cutoff=cutoff.isoformat(), status=status, reason=reason,
                        observation_id=row["id"] if row else None, snapshot=snapshot,
                        historical_freshness="not_established",
                    ), cohort_id=cohort["id"], case_key=case["case_key"], slot=slot))
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


def evaluate(db, cohort_id, *, as_of=None, persist=False):
    """Resolve every declared slot to scored, missing or excluded at a knowledge cutoff."""
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
    results = []
    calibration = [dict(lower=wire(F(i, 10)), upper=wire(F(i + 1, 10)), count=0,
                        probability_sum=F(0), actual_sum=0) for i in range(10)]
    for case_key, case in cases.items():
        for horizon in cohort["horizons"]:
            row = by_slot.get((case_key, str(horizon)))
            item = dict(case_key=case_key, event_id=case["event_id"], horizon_seconds=horizon,
                        status="missing", reason="capture_pending_or_missing", capture_id=None,
                        outcome_id=None, brier=None, log_loss=None)
            if not row:
                results.append(item); continue
            capture = row["payload"]
            item["capture_id"] = row["id"]
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
            snapshot = capture["snapshot"]
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
        scored_records=len(scored), scored_distinct_events=len({r["event_id"] for r in scored}),
        status_counts=dict(counts), records=results,
        mean_brier=wire(sum((F(r["brier"]) for r in scored), F(0)) / len(scored)) if scored else None,
        mean_log_loss=str(sum((Decimal(r["log_loss"]) for r in scored), Decimal(0)) / len(scored)) if scored else None,
        calibration=calibration,
        policy_comparison=_policy_comparison(db, cohort, by_slot, as_of),
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


def _policy_comparison(db, cohort, captures, as_of):
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
            snapshot = row["payload"].get("snapshot") if row else None
            for policy in policies:
                item = dict(case_key=case["case_key"], event_id=case["event_id"],
                    horizon_seconds=horizon, capture_id=row["id"] if row else None,
                    outcome_id=outcome["id"] if outcome else None,
                    status="missing", reason="capture_pending_or_missing", brier=None, log_loss=None)
                if not snapshot:
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


def status(db):
    row = db.execute("""SELECT count(*) records,COALESCE(sum(payload_bytes),0) retained_bytes,
        max(recorded_at) latest_recorded_at FROM public.research_record""").fetchone()
    row = dict(row)
    if row["latest_recorded_at"] is not None:
        row["latest_recorded_at"] = row["latest_recorded_at"].isoformat()
    return dict(row, byte_cap=TOTAL_BYTE_CAP, observation_byte_cap=OBSERVATION_BYTE_CAP,
                provider_requests=0)


def preserve_conditional(db, payload, *, record=None, fee_input=None):
    """Keep a former numeric witness before withdrawing current applicability.

    This is outside a prospective population and does not mint a new forecast.
    The original payload and asserted input shape remain exactly as retained.
    """
    with db.transaction():
        _writer_lock(db)
        return _record(db, "observation", dict(
            designation="historical_conditional_calculation",
            reason="provider_venue_fee_applicability_unestablished",
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
    at = at or utc()
    captured = capture_due(db, at=at)
    name = "daily-primary-pregame:" + at.astimezone(timezone.utc).date().isoformat()
    rows = _current_population(db, at)
    existing = db.execute("SELECT id FROM public.research_record WHERE kind='cohort' AND payload->>'name'=%s", (name,)).fetchone()
    declared = None
    if not existing:
        cases = {}
        for row in rows:
            case = _case(row)
            if stamp(case["starts_at"]) - timedelta(seconds=max(DEFAULT_HORIZONS)) <= at:
                continue
            cases.setdefault(case["case_key"], case)
        if cases:
            declared = declare(
                db, name=name, cases=list(cases.values()), at=at,
                population_description="All primary normalized exact market identities known at this daily declaration; all calculation statuses and EV signs; starts within seven days, more than one hour ahead. Later discoveries are outside this frozen population.",
            )
    by_key = {}
    for row in rows:
        case = _case(row)
        by_key.setdefault(case["case_key"], row)
    observed = skipped = 0
    for cohort in list_cohorts(db):
        if cohort["designation"] != "prospective":
            continue
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
                    ref = math.coherent_reference(record, refs, at=at)
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
            prior = db.execute("""SELECT payload FROM public.research_record WHERE kind='observation'
                AND cohort_id=%s AND case_key=%s ORDER BY recorded_at DESC,id DESC LIMIT 1""", (cohort["id"], case["case_key"])).fetchone()
            if prior and prior["payload"].get("input_fingerprint") == _fingerprint(payload, why):
                skipped += 1
                continue
            observe(db, cohort["id"], case["case_key"], payload, known_at=at,
                    record=row.get("record") if row and row.get("payload") else None,
                    fee_input=row.get("fee_input") if row and row.get("payload") else None,
                    unavailable_reason=why)
            observed += 1
    return dict(declared_cohort=declared["id"] if declared else None,
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
