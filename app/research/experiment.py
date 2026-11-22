"""Durable first-observation / T−10 experiment, with checkpoint-only retention.

The collector owns acquisition. These functions only schedule, freeze and read
evidence. Browser reads cannot activate scheduling or dispatch provider calls.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.storage.store import encoded, hashed, stamp
from . import records
from .experiment_evidence import (
    ACCOUNTING_METADATA_BYTES, GAME_METADATA_BYTES, pack, references, unpack,
)

VERSION = "first-observed-24h-vs-tminus10-screen-ev-1"
LOCK = 901114
MAX_GAMES = 512
RECORD_BYTE_CAP = 1024 * 1024
LATE_SECONDS = 600
LATE_TOLERANCE_SECONDS = 60
OUTCOME_OFFSETS = (3 * 3600, 4 * 3600, 6 * 3600, 12 * 3600, 24 * 3600)
OUTCOME_WINDOW_SECONDS = 900
CLAIM_TIMEOUT_SECONDS = 120
MAX_EVENT_BYTES = 8192
MIN_CHECKPOINT_RUNWAY = 64 * 1024


def utc():
    return datetime.now(timezone.utc)


def clock(value):
    return stamp(value).astimezone(timezone.utc).isoformat()


def _lock(db):
    records._writer_lock(db)
    db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))


def _dbclock(db):
    return db.execute("SELECT clock_timestamp() now").fetchone()["now"]


def _get(db, identity):
    row = db.execute("SELECT * FROM public.ev_experiment_record WHERE id=%s", (identity,)).fetchone()
    if not row or hashed(row["payload"]) != identity:
        raise ValueError("experiment_record_integrity")
    if references(row["payload"]) != set(row["refs"]):
        raise ValueError("experiment_record_dependencies")
    return row


def _closure(db, roots):
    if not roots:
        return {}
    rows = db.execute("""WITH RECURSIVE closure AS (
        SELECT * FROM public.ev_experiment_record WHERE id=ANY(%s)
        UNION
        SELECT r.* FROM public.ev_experiment_record r
        JOIN closure parent ON r.id=ANY(parent.refs)
    ) SELECT * FROM closure ORDER BY recorded_at,id""", (list(set(roots)),))
    result = {}
    for row in rows:
        if hashed(row["payload"]) != row["id"] or len(encoded(row["payload"])) != row["payload_bytes"]:
            raise ValueError("experiment_record_integrity")
        if references(row["payload"]) != set(row["refs"]):
            raise ValueError("experiment_record_dependencies")
        result[row["id"]] = row
    if any(identity not in result for identity in roots):
        raise ValueError("experiment_record_missing")
    return result


def _value(row, index):
    return unpack(row["payload"]["value"], index)


def _admit(db, size, *, reserve=0):
    used = records.retention_usage(db)
    if used["total"] + used["reserved"] + size + reserve > records.TOTAL_BYTE_CAP:
        raise ValueError("research_retention_capacity")
    from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage, require_disk_space
    from app.storage.store import ROOT
    if sql_usage(db) + (size + reserve) * 3 + 8 * 1024 * 1024 > SQL_BYTE_CAP:
        raise ValueError("research_sql_runway")
    require_disk_space(ROOT / ".local/postgres", append_bytes=(size + reserve) * 3)


def _write(db, kind, value, *, game_id=None, checkpoint=None, reserve=0, summary=None):
    root, blobs = pack(value)
    body = dict(version=VERSION, kind=kind, game_id=game_id, checkpoint=checkpoint, value=root)
    if summary is not None:
        body["summary"] = summary
    identity = hashed(body)
    bodies = dict(blobs)
    bodies[identity] = body
    existing = {row["id"] for row in db.execute(
        "SELECT id FROM public.ev_experiment_record WHERE id=ANY(%s)", (list(bodies),))}
    new = [(key, payload) for key, payload in bodies.items() if key not in existing]
    sizes = {key: len(encoded(payload)) for key, payload in new}
    if any(size > RECORD_BYTE_CAP for size in sizes.values()):
        raise ValueError("research_record_capacity")
    total = sum(sizes.values())
    if new or reserve:
        _admit(db, total, reserve=reserve)
    if new:
        with db.cursor() as cursor:
            cursor.executemany("""INSERT INTO public.ev_experiment_record
                (id,kind,game_id,checkpoint,payload_bytes,refs,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""", [
                (key, payload["kind"], game_id if payload["kind"] != "blob" else None,
                 checkpoint if payload["kind"] != "blob" else None,
                 sizes[key], sorted(references(payload)), Jsonb(payload)) for key, payload in new])
    return identity, total


def _account_refusal(db, reason, source_event_id=None, at=None):
    db.execute("""UPDATE public.ev_experiment_accounting SET discovery_refusals=discovery_refusals+1,
        last_refused_at=%s,last_reason=%s,last_source_event_id=%s WHERE singleton""",
        (at or utc(), str(reason)[:160], str(source_event_id)[:256] if source_event_id else None))


def activate(db, *, at=None):
    at = at or utc()
    with db.transaction():
        _lock(db)
        row = db.execute("SELECT policy_id FROM public.ev_experiment_accounting WHERE singleton").fetchone()
        if row["policy_id"]:
            index = _closure(db, [row["policy_id"]])
            return dict(_value(index[row["policy_id"]], index), id=row["policy_id"])
        from app.comparison.current_pregame import REFERENCE_POLICY, COHERENT_POLICY
        policy = dict(version=VERSION, activated_at=clock(at), early=dict(
            rule="first_new_received_event_observation_after_activation_with_start_within_24h",
            window_seconds=86400, baseline="frozen_once; actual_first_observation_not_assumed_Tminus24h",
            existing_games="first_new_received_page_after_activation; older_source_receipts_not_backfilled"),
            late=dict(target_seconds_before_start=LATE_SECONDS, window_start_offset_seconds=0,
                window_end_offset_seconds=LATE_TOLERANCE_SECONDS,
                late_discovery="freeze_one_actual_early_snapshot; late_missed_without_pre_target_baseline; no_second_request",
                cutoffs="dispatch,receipt,knowledge,and_actual_database_persistence_inside_window"),
            outcomes=dict(offsets_seconds=list(OUTCOME_OFFSETS), window_seconds=OUTCOME_WINDOW_SECONDS,
                max_requests=len(OUTCOME_OFFSETS), missed_windows="skip; no_catchup_burst"),
            selection=dict(rule="early_screen_EV>0 OR late_screen_EV>0", unknown="null; never_zero_or_negative",
                exact_bet="canonical_event+provider+original_book+venue+market+period+outcome+exact_line+settlement"),
            screen_policy=REFERENCE_POLICY, coherent_policy=COHERENT_POLICY,
            requested_scope=dict(bookmakers=["kalshi","polymarket","novig","prophetexchange",
                "fanduel","draftkings","betmgm","caesars","betonline"], includeAltLines=True,
                odd_ids=["points-all-game-ou-over","points-all-game-ou-under","points-away-game-ml-away",
                    "points-away-game-sp-away","points-home-game-ml-home","points-home-game-sp-home"]),
            reschedules="preserve_early; append_schedule; retarget_late; mark_settlement_continuity_unverified",
            retention=dict(checkpoints_only=True, shared_inputs="content_addressed_nested_JSON",
                no_automatic_eviction=True, total_byte_cap=records.TOTAL_BYTE_CAP, max_games=MAX_GAMES,
                metadata_bytes_per_game=GAME_METADATA_BYTES,
                late_reservation="early_new_unique_bytes + max(64KiB,25percent); charged_inside_total; larger_late_surface_can_still_refuse"),
            scheduling_transition=dict(from_policy=records.VERSION, from_default_horizon_seconds=3600,
                retired_at=clock(at), to_policy=VERSION, historical_records="unchanged_and_readable"))
        identity, _ = _write(db, "policy", policy)
        db.execute("UPDATE public.ev_experiment_accounting SET policy_id=%s,activated_at=%s WHERE singleton", (identity, at))
        return dict(policy, id=identity)


def _event(event):
    value = deepcopy(event)
    value["provider"] = value.get("provider") or "sportsgameodds"
    value["source_event_id"] = value.get("source_event_id") or value.get("native_event_id")
    for key in ("source_event_id", "event_id", "league", "starts_at", "home", "away"):
        if not value.get(key):
            raise ValueError("experiment_exact_event_required")
    value["starts_at"] = clock(value["starts_at"])
    value["source_metadata_received_at"] = value.get("source_metadata_received_at") or value.get("source_received_at")
    value["status"] = dict(value.get("status") or {})
    if len(encoded(value)) > MAX_EVENT_BYTES:
        raise ValueError("experiment_event_metadata_capacity")
    return value


def _schedule_value(event, *, at, previous=None):
    starts = stamp(event["starts_at"])
    return dict(event=event, observed_at=clock(at), previous_schedule_id=previous,
                starts_at=clock(starts), target_at=clock(starts-timedelta(seconds=LATE_SECONDS)),
                deadline_at=clock(starts-timedelta(seconds=LATE_SECONDS-LATE_TOLERANCE_SECONDS)),
                cancelled=event["status"].get("cancelled") is True)


def discover(db, events, *, at=None):
    at = at or utc()
    policy = activate(db, at=at)
    result = dict(discovered=0, rescheduled=0, cancelled=0, outside_window=0, refused=0)
    for incoming in events:
        event = _event(incoming)
        try:
            with db.transaction():
                _lock(db)
                row = db.execute("SELECT * FROM public.ev_experiment_game WHERE provider=%s AND source_event_id=%s FOR UPDATE",
                                 (event["provider"], event["source_event_id"])).fetchone()
                if not row:
                    if not 0 < (stamp(event["starts_at"])-at).total_seconds() <= 86400:
                        result["outside_window"] += 1
                        continue
                    count = db.execute("SELECT count(*) n FROM public.ev_experiment_game").fetchone()["n"]
                    if count >= MAX_GAMES:
                        raise ValueError("experiment_game_capacity")
                    event["discovery_kind"] = event.get("discovery_kind") or (
                        "new_received_event" if event.get("source_metadata_received_at") and
                        stamp(event["source_metadata_received_at"]) >= stamp(policy["activated_at"]) else "policy_activation_existing_game")
                    game_id = hashed([VERSION, event["provider"], event["source_event_id"],
                                      event["league"], event["home"], event["away"]])
                    schedule = _schedule_value(event, at=at)
                    schedule_id, size = _write(db, "schedule", schedule, game_id=game_id, reserve=GAME_METADATA_BYTES)
                    db.execute("""INSERT INTO public.ev_experiment_game
                        (id,policy_id,provider,source_event_id,event,discovered_at,first_observed_at,schedule_id,unique_payload_bytes,state)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (game_id, policy["id"], event["provider"], event["source_event_id"], Jsonb(event), at, at, schedule_id, size,
                         "cancelled" if schedule["cancelled"] else "tracking"))
                    starts = stamp(event["starts_at"])
                    for checkpoint, target, deadline in (
                        ("early", at, starts),
                        ("late", stamp(schedule["target_at"]), stamp(schedule["deadline_at"])),
                        ("outcome", starts+timedelta(seconds=OUTCOME_OFFSETS[0]), starts+timedelta(seconds=OUTCOME_OFFSETS[0]+OUTCOME_WINDOW_SECONDS)),
                    ):
                        state = "cancelled" if schedule["cancelled"] else "missed" if checkpoint == "late" and at >= target else "pending"
                        db.execute("""INSERT INTO public.ev_experiment_task
                            (game_id,checkpoint,schedule_id,state,target_at,deadline_at,last_reason)
                            VALUES(%s,%s,%s,%s,%s,%s,%s)""", (game_id, checkpoint, schedule_id,
                            state, target, deadline, "late_discovery_no_pre_target_baseline" if state == "missed" else "cancelled" if state == "cancelled" else None))
                    result["discovered"] += 1
                else:
                    if any(event[key] != row["event"][key] for key in ("home", "away", "league")):
                        raise ValueError("experiment_event_identity_changed")
                    old_cancel = row["event"].get("status", {}).get("cancelled") is True
                    cancelled = event["status"].get("cancelled") is True
                    changed = stamp(event["starts_at"]) != stamp(row["event"]["starts_at"])
                    if not changed and cancelled == old_cancel:
                        continue
                    schedule = _schedule_value(event, at=at, previous=row["schedule_id"])
                    schedule_id, size = _write(db, "schedule", schedule, game_id=row["id"])
                    db.execute("""UPDATE public.ev_experiment_game SET event=%s,schedule_id=%s,
                        state=%s,unique_payload_bytes=unique_payload_bytes+%s,updated_at=clock_timestamp() WHERE id=%s""",
                        (Jsonb(event), schedule_id, "cancelled" if cancelled else "rescheduled", size, row["id"]))
                    starts = stamp(event["starts_at"])
                    if not row["early_id"]:
                        early_target = max(row["discovered_at"], starts-timedelta(hours=24))
                        early_deferred = early_target > at
                        early_state = "cancelled" if cancelled else "pending" if early_deferred else None
                        db.execute("""UPDATE public.ev_experiment_task SET schedule_id=%s,target_at=%s,deadline_at=%s,
                            state=COALESCE(%s,state),token=CASE WHEN %s THEN NULL ELSE token END,
                            last_reason=CASE WHEN %s THEN 'rescheduled_outside_24h; early_not_yet_frozen' ELSE last_reason END
                            WHERE game_id=%s AND checkpoint='early'""",
                            (schedule_id,early_target,starts,early_state,early_deferred or cancelled,early_deferred,row["id"]))
                    for checkpoint, target, deadline in (
                        ("late", stamp(schedule["target_at"]), stamp(schedule["deadline_at"])),
                        ("outcome", starts+timedelta(seconds=OUTCOME_OFFSETS[0]), starts+timedelta(seconds=OUTCOME_OFFSETS[0]+OUTCOME_WINDOW_SECONDS)),
                    ):
                        state = "cancelled" if cancelled else "missed" if at > deadline else "pending"
                        db.execute("""UPDATE public.ev_experiment_task SET schedule_id=%s,state=%s,target_at=%s,
                            deadline_at=%s,token=NULL,claimed_at=NULL,slot_index=0,result_id=NULL,
                            last_reason=%s,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint=%s""",
                            (schedule_id, state, target, deadline, "cancelled" if cancelled else
                             "rescheduled_after_checkpoint" if checkpoint == "late" and row["late_id"] else None,
                             row["id"], checkpoint))
                    if cancelled:
                        db.execute("UPDATE public.ev_experiment_game SET late_reserved_bytes=0 WHERE id=%s", (row["id"],))
                        db.execute("UPDATE public.ev_experiment_task SET state='cancelled',last_reason='cancelled' WHERE game_id=%s AND checkpoint='early' AND state<>'captured'", (row["id"],))
                        result["cancelled"] += 1
                    if changed:
                        result["rescheduled"] += 1
                    current_game = db.execute("SELECT * FROM public.ev_experiment_game WHERE id=%s", (row["id"],)).fetchone()
                    _comparison(db, current_game)
        except Exception as exc:
            if not records._retention_failure(exc) and str(exc) not in ("experiment_game_capacity", "experiment_event_identity_changed"):
                raise
            with db.transaction():
                _lock(db)
                _account_refusal(db, exc, event["source_event_id"], at)
            result["refused"] += 1
    return result


def tracked_source_ids(db):
    return [row["source_event_id"] for row in db.execute("SELECT source_event_id FROM public.ev_experiment_game ORDER BY id")]


def reserved_late_objects(db, *, at=None, through=None):
    at = at or utc()
    through = through or at + timedelta(seconds=900)
    return db.execute("""SELECT count(*) n FROM public.ev_experiment_task
        WHERE checkpoint='late' AND state IN ('pending','claimed') AND target_at<=%s AND deadline_at>=%s""",
        (through, at)).fetchone()["n"]


def task_authorized(db, token, *, at=None):
    at = at or utc()
    row = db.execute("""SELECT t.*,g.event,g.schedule_id current_schedule FROM public.ev_experiment_task t
        JOIN public.ev_experiment_game g ON g.id=t.game_id WHERE t.token=%s AND t.state='claimed'""", (token,)).fetchone()
    return bool(row and row["schedule_id"] == row["current_schedule"]
                and not row["event"].get("status", {}).get("cancelled")
                and row["target_at"] <= at <= row["deadline_at"])


def _advance_outcome(db, task, event, at, *, reason=None):
    index = task["slot_index"] + 1
    skipped = task["skipped_windows"]
    starts = stamp(event["starts_at"])
    while index < len(OUTCOME_OFFSETS) and starts + timedelta(seconds=OUTCOME_OFFSETS[index]+OUTCOME_WINDOW_SECONDS) < at:
        index += 1
        skipped += 1
    if index >= len(OUTCOME_OFFSETS):
        db.execute("UPDATE public.ev_experiment_task SET state='exhausted',token=NULL,claimed_at=NULL,slot_index=%s,skipped_windows=%s,last_reason=%s,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='outcome'",
                   (index, skipped, reason or "postgame_followup_exhausted", task["game_id"]))
    else:
        target = starts + timedelta(seconds=OUTCOME_OFFSETS[index])
        db.execute("UPDATE public.ev_experiment_task SET state='pending',token=NULL,claimed_at=NULL,slot_index=%s,skipped_windows=%s,target_at=%s,deadline_at=%s,last_reason=%s,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='outcome'",
                   (index, skipped, target, target+timedelta(seconds=OUTCOME_WINDOW_SECONDS), reason, task["game_id"]))


def due(db, *, at=None, limit=1):
    at = at or utc()
    limit = max(1, min(8, int(limit)))
    claimed = []
    with db.transaction():
        _lock(db)
        overdue = list(db.execute("""SELECT t.*,g.event FROM public.ev_experiment_task t
            JOIN public.ev_experiment_game g ON g.id=t.game_id WHERE
            (t.state='pending' AND t.deadline_at<%s) OR
            (t.state='claimed' AND (t.deadline_at<%s OR t.claimed_at<%s)) FOR UPDATE OF t""",
            (at, at, at-timedelta(seconds=CLAIM_TIMEOUT_SECONDS))))
        for task in overdue:
            if task["checkpoint"] == "outcome":
                _advance_outcome(db, task, task["event"], at, reason="missed_postgame_window" if task["state"] == "pending" else "interrupted_postgame_attempt")
            else:
                why = "interrupted_after_claim; no_automatic_refetch" if task["state"] == "claimed" else "checkpoint_window_missed"
                db.execute("UPDATE public.ev_experiment_task SET state='missed',last_reason=%s,token=NULL,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint=%s",
                           (why, task["game_id"], task["checkpoint"]))
                if task["checkpoint"] == "late":
                    db.execute("UPDATE public.ev_experiment_game SET late_reserved_bytes=0 WHERE id=%s", (task["game_id"],))
        rows = db.execute("""SELECT t.*,g.event,g.late_reserved_bytes FROM public.ev_experiment_task t JOIN public.ev_experiment_game g ON g.id=t.game_id
            WHERE t.state='pending' AND t.target_at<=%s AND t.deadline_at>=%s
            ORDER BY CASE t.checkpoint WHEN 'late' THEN 0 WHEN 'early' THEN 1 ELSE 2 END,t.deadline_at,t.game_id
            LIMIT %s FOR UPDATE OF t SKIP LOCKED""", (at, at, limit))
        for row in rows:
            if row["checkpoint"] == "outcome" and row["attempts"] >= len(OUTCOME_OFFSETS):
                db.execute("UPDATE public.ev_experiment_task SET state='exhausted',last_reason='outcome_request_budget_exhausted',updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='outcome'", (row["game_id"],))
                continue
            usage = records.retention_usage(db)
            own_reservation = row["late_reserved_bytes"] if row["checkpoint"] == "late" else 0
            if usage["total"] + usage["reserved"] + MIN_CHECKPOINT_RUNWAY > records.TOTAL_BYTE_CAP + own_reservation:
                db.execute("UPDATE public.ev_experiment_task SET state='refused',refusals=refusals+1,first_refused_at=COALESCE(first_refused_at,%s),last_refused_at=%s,last_reason='research_retention_capacity_before_dispatch' WHERE game_id=%s AND checkpoint=%s", (at,at,row["game_id"],row["checkpoint"]))
                if row["checkpoint"] == "late":
                    db.execute("UPDATE public.ev_experiment_game SET late_reserved_bytes=0 WHERE id=%s", (row["game_id"],))
                continue
            token = uuid4().hex
            db.execute("UPDATE public.ev_experiment_task SET state='claimed',token=%s,claimed_at=%s,attempts=attempts+1,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint=%s",
                       (token, at, row["game_id"], row["checkpoint"]))
            claimed.append(dict(game_id=row["game_id"], checkpoint=row["checkpoint"], token=token,
                schedule_id=row["schedule_id"], event=row["event"], target_at=clock(row["target_at"]),
                deadline_at=clock(row["deadline_at"]), requested_at=clock(at), attempt=row["attempts"]+1,
                outcome_slot_index=row["slot_index"]))
    return claimed


def _task(db, game_id, checkpoint, token):
    task = db.execute("SELECT * FROM public.ev_experiment_task WHERE game_id=%s AND checkpoint=%s FOR UPDATE", (game_id, checkpoint)).fetchone()
    game = db.execute("SELECT * FROM public.ev_experiment_game WHERE id=%s FOR UPDATE", (game_id,)).fetchone()
    if not task or not game:
        raise ValueError("experiment_game_unknown")
    if task["state"] != "claimed" or not token or token != task["token"]:
        raise ValueError("experiment_task_not_claimed_or_superseded")
    if task["schedule_id"] != game["schedule_id"]:
        raise ValueError("experiment_schedule_changed")
    return task, game


def fail_checkpoint(db, game_id, checkpoint, reason, *, token=None, at=None, dispatched=False, details=None):
    at = at or utc()
    with db.transaction():
        _lock(db)
        try:
            task, game = _task(db, game_id, checkpoint, token)
        except ValueError as exc:
            if str(exc) not in ("experiment_task_not_claimed_or_superseded", "experiment_schedule_changed"):
                raise
            return dict(state="superseded", game_id=game_id, checkpoint=checkpoint, reason=str(reason)[:160])
        refused = records._retention_failure(ValueError(str(reason)))
        state = "refused" if refused else "missed"
        db.execute("""UPDATE public.ev_experiment_task SET state=%s,token=NULL,last_reason=%s,
            refusals=refusals+%s,first_refused_at=CASE WHEN %s THEN COALESCE(first_refused_at,%s) ELSE first_refused_at END,
            last_refused_at=CASE WHEN %s THEN %s ELSE last_refused_at END,updated_at=clock_timestamp()
            WHERE game_id=%s AND checkpoint=%s""",
            (state, str(reason)[:160], int(refused), refused, at, refused, at, game_id, checkpoint))
        if checkpoint == "late":
            db.execute("UPDATE public.ev_experiment_game SET late_reserved_bytes=0 WHERE id=%s", (game_id,))
        # Reserved counters remain writable when payload allowance is full.
        if checkpoint == "outcome":
            _advance_outcome(db, task, game["event"], at, reason=str(reason)[:160])
        try:
            with db.transaction():
                identity, size = _write(db, "attempt", dict(reason=str(reason)[:160],
                    at=clock(at), dispatched=bool(dispatched), details=details,
                    schedule_id=game["schedule_id"], attempt=task["attempts"]), game_id=game_id, checkpoint=checkpoint)
                db.execute("UPDATE public.ev_experiment_game SET unique_payload_bytes=unique_payload_bytes+%s WHERE id=%s", (size, game_id))
        except Exception as exc:
            if not records._retention_failure(exc):
                raise
        return dict(state=state, reason=str(reason)[:160], game_id=game_id, checkpoint=checkpoint)


def _checkpoint_view(db, game, checkpoint, index=None):
    identity = game[checkpoint+"_id"]
    task = db.execute("SELECT * FROM public.ev_experiment_task WHERE game_id=%s AND checkpoint=%s", (game["id"], checkpoint)).fetchone()
    if not identity:
        return dict(status=task["state"], reason=task["last_reason"], target_at=clock(task["target_at"]),
                    window_start=clock(task["target_at"]), deadline_at=clock(task["deadline_at"]),
                    actual_at=None, captured_at=None, persisted_at=None, snapshot=None)
    index = index or _closure(db, [identity])
    row = index[identity]
    value = _value(row, index)
    view = dict(value, id=identity, persisted_at=clock(row["recorded_at"]),
                actual_at=clock(row["recorded_at"]), captured_at=clock(row["recorded_at"]),
                target_at=value["target_at"], window_start=value["target_at"], deadline_at=value["deadline_at"])
    if checkpoint == "late" and value["schedule_id"] != game["schedule_id"]:
        view.update(status="superseded_by_reschedule", reason="rescheduled_late_target_changed",
                    current_target_at=clock(task["target_at"]), current_deadline_at=clock(task["deadline_at"]))
    return view


def _comparison(db, game):
    from .ev_movement import compare_checkpoints
    roots = [game[key] for key in ("early_id", "late_id") if game[key]]
    index = _closure(db, roots)
    early = _checkpoint_view(db, game, "early", index)
    late = _checkpoint_view(db, game, "late", index)
    value = compare_checkpoints(early, late)
    compact = dict(value)
    compact.pop("context", None)
    compact.pop("reference_context", None)
    compact.pop("main_line_links", None)
    identity, size = _write(db, "comparison", compact, game_id=game["id"])
    db.execute("UPDATE public.ev_experiment_game SET comparison_id=%s,retained_cases=%s,unique_payload_bytes=unique_payload_bytes+%s,updated_at=clock_timestamp() WHERE id=%s",
               (identity, len(value["cases"]), size, game["id"]))
    return value


def capture(db, game_id, checkpoint, snapshot, *, token=None, requested_at=None,
            received_at=None, known_at=None, scope=None):
    if checkpoint not in ("early", "late"):
        raise ValueError("experiment_checkpoint_kind")
    try:
        with db.transaction():
            _lock(db)
            task, game = _task(db, game_id, checkpoint, token)
            now = _dbclock(db)
            requested = stamp(requested_at or task["claimed_at"])
            received = stamp(received_at or snapshot["times"]["received_at"])
            known = stamp(known_at or snapshot["times"]["known_at"])
            if not requested <= received <= known <= now:
                raise ValueError("experiment_causal_clock_order")
            if checkpoint == "early" and game["early_id"]:
                raise ValueError("experiment_early_baseline_already_frozen")
            if checkpoint == "early" and not 0 < (stamp(game["event"]["starts_at"])-received).total_seconds() <= 86400:
                raise ValueError("experiment_early_outside_24h_window")
            if not task["target_at"] <= requested or now > task["deadline_at"]:
                raise ValueError("experiment_checkpoint_window_missed")
            event = snapshot.get("event") or {}
            if (event.get("home"), event.get("away"), event.get("competition")) != (
                    game["event"]["home"], game["event"]["away"], game["event"]["league"]):
                raise ValueError("experiment_checkpoint_event_identity")
            if stamp(event["scheduled_start"]) != stamp(game["event"]["starts_at"]):
                raise ValueError("experiment_schedule_changed")
            source = snapshot.get("source_event") or {}
            if source and source.get("event_id") != game["source_event_id"]:
                raise ValueError("experiment_checkpoint_event_identity")
            frozen = deepcopy(snapshot)
            frozen["schedule"] = dict(id=game["schedule_id"], starts_at=game["event"]["starts_at"],
                target_at=clock(task["target_at"]), deadline_at=clock(task["deadline_at"]))
            value = dict(status="captured", checkpoint=checkpoint, schedule_id=game["schedule_id"],
                target_at=clock(task["target_at"]), deadline_at=clock(task["deadline_at"]),
                requested_at=clock(requested), received_at=clock(received), known_at=clock(known),
                observed_at=clock(game["first_observed_at"]),
                experiment_first_observed_at=clock(game["first_observed_at"]),
                source_metadata_received_at=game["event"].get("source_metadata_received_at"),
                discovery_kind=game["event"].get("discovery_kind") or "policy_activation_existing_game",
                capture_lag_seconds=str((received-game["first_observed_at"]).total_seconds()),
                observation_to_capture_lag_seconds=str((known-game["first_observed_at"]).total_seconds()),
                seconds_to_start=str((stamp(game["event"]["starts_at"])-received).total_seconds()),
                scope=scope or snapshot.get("request_scope"), snapshot=frozen)
            if checkpoint == "late":
                # The late capture may consume its own reservation, while other
                # games' reserved reproduction space remains protected.
                db.execute("UPDATE public.ev_experiment_game SET late_reserved_bytes=0 WHERE id=%s", (game_id,))
            identity, size = _write(db, "checkpoint", value, game_id=game_id, checkpoint=checkpoint,
                summary=dict(received_at=clock(received),known_at=clock(known),
                    target_at=clock(task["target_at"]),deadline_at=clock(task["deadline_at"]),
                    coverage=deepcopy(snapshot.get("coverage") or {})))
            if checkpoint == "early":
                late_target = stamp(game["event"]["starts_at"])-timedelta(seconds=LATE_SECONDS)
                reserve = 0
                if known < late_target:
                    reserve = size + max(MIN_CHECKPOINT_RUNWAY, size // 4)
                    _admit(db, 0, reserve=reserve)
                else:
                    db.execute("UPDATE public.ev_experiment_task SET state='missed',token=NULL,last_reason=CASE WHEN last_reason='late_discovery_no_pre_target_baseline' THEN last_reason ELSE 'early_baseline_after_target' END,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='late' AND state<>'captured'", (game_id,))
                db.execute("UPDATE public.ev_experiment_game SET late_reserved_bytes=%s WHERE id=%s", (reserve,game_id))
            row = _get(db, identity)
            if row["recorded_at"] > task["deadline_at"] or _dbclock(db) > task["deadline_at"]:
                raise ValueError("experiment_checkpoint_persistence_after_deadline")
            db.execute("UPDATE public.ev_experiment_game SET " + checkpoint + "_id=%s,unique_payload_bytes=unique_payload_bytes+%s,raw_checkpoint_bytes=raw_checkpoint_bytes+%s,updated_at=clock_timestamp() WHERE id=%s",
                       (identity, size, len(encoded(snapshot)), game_id))
            db.execute("UPDATE public.ev_experiment_task SET state='captured',result_id=%s,token=NULL,last_reason=NULL,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint=%s",
                       (identity, game_id, checkpoint))
            game = db.execute("SELECT * FROM public.ev_experiment_game WHERE id=%s", (game_id,)).fetchone()
            _comparison(db, game)
            if _dbclock(db) > task["deadline_at"]:
                raise ValueError("experiment_checkpoint_persistence_after_deadline")
            return dict(state="captured", id=identity, game_id=game_id, checkpoint=checkpoint,
                        recorded_at=clock(row["recorded_at"]), new_unique_payload_bytes=size)
    except Exception as exc:
        if not records._retention_failure(exc) and str(exc) not in (
                "experiment_checkpoint_window_missed", "experiment_checkpoint_persistence_after_deadline",
                "experiment_causal_clock_order"):
            raise
        return fail_checkpoint(db, game_id, checkpoint, str(exc), token=token, dispatched=True,
            details=dict(requested_at=clock(requested_at) if requested_at else None,
                         received_at=clock(received_at) if received_at else None,
                         known_at=clock(known_at) if known_at else None))


def capture_outcome(db, game_id, observation, *, token=None, requested_at=None,
                    received_at=None, known_at=None, scope=None):
    try:
        with db.transaction():
            _lock(db)
            task, game = _task(db, game_id, "outcome", token)
            now = _dbclock(db)
            source = observation or {}
            if (source.get("event_id"), source.get("home"), source.get("away"), source.get("league")) != (
                    game["source_event_id"], game["event"]["home"], game["event"]["away"], game["event"]["league"]):
                raise ValueError("experiment_outcome_identity")
            if stamp(source["starts_at"]) != stamp(game["event"]["starts_at"]):
                raise ValueError("experiment_outcome_schedule_changed")
            received = stamp(received_at or source["received_at"])
            known = stamp(known_at or source["knowledge_at"])
            if not received <= known <= now or received < stamp(game["event"]["starts_at"]):
                raise ValueError("experiment_outcome_clock_order")
            data = dict(source=source["source"], published_at=source.get("published_at"),
                observed_at=clock(received), final=source["final"],
                result=source.get("result") or ("completed" if source["final"] else "unresolved"),
                home_score=source.get("home_score"), away_score=source.get("away_score"),
                receipt_sha256=source.get("receipt_sha256"), source_result=source)
            identity, size = _write(db, "outcome", dict(data=data, known_at=clock(known),
                requested_at=clock(requested_at) if requested_at else None, scope=scope,
                schedule_id=game["schedule_id"], supersedes_id=game["outcome_id"]), game_id=game_id, checkpoint="outcome")
            db.execute("UPDATE public.ev_experiment_game SET outcome_id=%s,unique_payload_bytes=unique_payload_bytes+%s,updated_at=clock_timestamp() WHERE id=%s", (identity, size, game_id))
            if source["final"]:
                db.execute("UPDATE public.ev_experiment_task SET state='final',result_id=%s,token=NULL,last_reason=NULL,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='outcome'", (identity, game_id))
            else:
                _advance_outcome(db, task, game["event"], now, reason=source.get("reason") or "sporting_result_not_final")
            return dict(state="final" if source["final"] else "not_final", id=identity, game_id=game_id)
    except Exception as exc:
        if not records._retention_failure(exc):
            raise
        return fail_checkpoint(db, game_id, "outcome", str(exc), token=token, dispatched=True)


def observe_outcomes(db, observations, *, at=None):
    """Use ordinary final receipts without saving every non-final poll revision."""
    at = at or utc()
    counts = dict(matched=0, unchanged=0, nonfinal=0, unmatched=0, invalid=0, refused=0)
    for source in observations:
        if not source.get("final"):
            counts["nonfinal"] += 1
            continue
        game = db.execute("SELECT * FROM public.ev_experiment_game WHERE provider='sportsgameodds' AND source_event_id=%s", (source["event_id"],)).fetchone()
        if not game or (source.get("home"),source.get("away"),source.get("league"),stamp(source["starts_at"])) != (
                game["event"]["home"],game["event"]["away"],game["event"]["league"],stamp(game["event"]["starts_at"])):
            counts["unmatched"] += 1
            continue
        if not stamp(game["event"]["starts_at"]) <= stamp(source["received_at"]) <= stamp(source["knowledge_at"]) <= at:
            counts["invalid"] += 1
            continue
        try:
            with db.transaction():
                _lock(db)
                game = db.execute("SELECT * FROM public.ev_experiment_game WHERE id=%s FOR UPDATE", (game["id"],)).fetchone()
                if game["outcome_id"]:
                    index = _closure(db, [game["outcome_id"]])
                    prior = _value(index[game["outcome_id"]], index)["data"]
                    if prior.get("final") and (prior.get("home_score"),prior.get("away_score")) == (source.get("home_score"),source.get("away_score")):
                        counts["unchanged"] += 1
                        continue
                value = dict(data=dict(source=source["source"], published_at=source.get("published_at"),
                    observed_at=source["received_at"], final=True, result="completed",
                    home_score=source.get("home_score"), away_score=source.get("away_score"),
                    receipt_sha256=source.get("receipt_sha256"), source_result=source),
                    known_at=source["knowledge_at"], trigger="ordinary_final_receipt",
                    schedule_id=game["schedule_id"], supersedes_id=game["outcome_id"])
                identity, size = _write(db, "outcome", value, game_id=game["id"], checkpoint="outcome")
                db.execute("UPDATE public.ev_experiment_game SET outcome_id=%s,unique_payload_bytes=unique_payload_bytes+%s,updated_at=clock_timestamp() WHERE id=%s", (identity,size,game["id"]))
                db.execute("UPDATE public.ev_experiment_task SET state='final',result_id=%s,token=NULL,last_reason=NULL,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='outcome'", (identity,game["id"]))
                counts["matched"] += 1
        except Exception as exc:
            if not records._retention_failure(exc):
                raise
            with db.transaction():
                _lock(db)
                db.execute("UPDATE public.ev_experiment_task SET refusals=refusals+1,first_refused_at=COALESCE(first_refused_at,%s),last_refused_at=%s,last_reason=%s WHERE game_id=%s AND checkpoint='outcome'", (at,at,str(exc)[:160],game["id"]))
            counts["refused"] += 1
    return counts


def _game_summary(row, revision=None):
    event = row["event"]
    return dict(id=row["id"], revision=revision, title=event.get("title"), league=event["league"],
        starts_at=event["starts_at"], source_event_id=row["source_event_id"], event=event,
        state=row["state"], first_observed_at=clock(row["first_observed_at"]),
        early_id=row["early_id"], late_id=row["late_id"], outcome_id=row["outcome_id"],
        retained_cases=row["retained_cases"], unique_payload_bytes=row["unique_payload_bytes"],
        raw_checkpoint_bytes=row["raw_checkpoint_bytes"], late_reserved_bytes=row["late_reserved_bytes"])


def _revision(db, row):
    tasks = list(db.execute("SELECT checkpoint,state,target_at,deadline_at,last_reason,result_id,attempts,refusals FROM public.ev_experiment_task WHERE game_id=%s ORDER BY checkpoint", (row["id"],)))
    return hashed(dict(policy=row["policy_id"], schedule=row["schedule_id"], early=row["early_id"],
        late=row["late_id"], outcome=row["outcome_id"], comparison=row["comparison_id"],
        tasks=[{k:clock(v) if hasattr(v,"isoformat") else v for k,v in task.items()} for task in tasks]))


def status(db):
    accounting = db.execute("SELECT * FROM public.ev_experiment_accounting WHERE singleton").fetchone()
    usage = records.retention_usage(db)
    task_counts = db.execute("SELECT checkpoint,state,count(*) records,sum(refusals)::bigint refusals FROM public.ev_experiment_task GROUP BY checkpoint,state ORDER BY checkpoint,state").fetchall()
    games = db.execute("SELECT count(*) n,count(*) FILTER(WHERE early_id IS NOT NULL AND late_id IS NOT NULL) complete,COALESCE(sum(unique_payload_bytes),0) bytes,COALESCE(sum(late_reserved_bytes),0) late_reserved,COALESCE(avg(unique_payload_bytes) FILTER(WHERE early_id IS NOT NULL AND late_id IS NOT NULL),0) mean_complete_bytes FROM public.ev_experiment_game").fetchone()
    remaining = max(0, records.TOTAL_BYTE_CAP-usage["total"]-usage["reserved"])
    mean = int(games["mean_complete_bytes"]) if games["complete"] else None
    return dict(version=VERSION, activated=bool(accounting["policy_id"]), activated_at=clock(accounting["activated_at"]) if accounting["activated_at"] else None,
        policy_id=accounting["policy_id"], games=games["n"], complete_checkpoint_games=games["complete"],
        tasks=[dict(row) for row in task_counts], discovery_refusals=accounting["discovery_refusals"],
        last_refusal=accounting["last_reason"], storage=dict(byte_cap=records.TOTAL_BYTE_CAP,
            retained_bytes=usage["total"], allocated_bytes=usage["total"]+usage["reserved"],
            experiment_payload_bytes=usage["experiment_bytes"], metadata_allocation_bytes=games["n"]*GAME_METADATA_BYTES+ACCOUNTING_METADATA_BYTES,
            experiment_reserved_bytes=usage["experiment_reserved_bytes"],
            late_reserved_bytes=int(games["late_reserved"]),
            remaining_bytes=remaining, mean_complete_game_payload_bytes=mean,
            estimated_remaining_games=remaining//(mean+GAME_METADATA_BYTES) if mean else None,
            runway_scope="measured completed-game incremental payloads; shared-input order and future scope can differ; not operating-day guarantee",
            max_games=MAX_GAMES, no_automatic_eviction=True), provider_requests=0)


def _policy(db):
    row = db.execute("SELECT policy_id FROM public.ev_experiment_accounting WHERE singleton").fetchone()
    if not row["policy_id"]:
        return None
    index = _closure(db, [row["policy_id"]])
    return dict(_value(index[row["policy_id"]], index), id=row["policy_id"])


def catalog(db, *, include_context=False, limit=50, offset=0):
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    predicate = "true" if include_context else "retained_cases>0"
    total = db.execute("SELECT count(*) n FROM public.ev_experiment_game WHERE " + predicate).fetchone()["n"]
    rows = list(db.execute("SELECT * FROM public.ev_experiment_game WHERE " + predicate +
        " ORDER BY first_observed_at DESC,id LIMIT %s OFFSET %s", (limit, offset)))
    index = _closure(db, [row["comparison_id"] for row in rows if row["comparison_id"]])
    checkpoints = {row["id"]:row for row in db.execute(
        "SELECT id,recorded_at,payload->'summary' summary FROM public.ev_experiment_record WHERE id=ANY(%s)",
        ([row[key] for row in rows for key in ("early_id","late_id") if row[key]],))}
    games, cases = [], []
    for row in rows:
        revision = _revision(db, row)
        game = _game_summary(row, revision)
        comparison = _value(index[row["comparison_id"]], index) if row["comparison_id"] else dict(cases=[], counts={})
        game["case_counts"] = comparison.get("counts", {})
        tasks = list(db.execute("SELECT checkpoint,state,target_at,deadline_at,last_reason FROM public.ev_experiment_task WHERE game_id=%s ORDER BY checkpoint", (row["id"],)))
        game["checkpoints"] = {r["checkpoint"]: {k:clock(v) if hasattr(v,"isoformat") else v for k,v in r.items()} for r in tasks}
        game["late_target"] = game["checkpoints"]["late"]["target_at"]
        for label in ("early","late"):
            checkpoint = checkpoints.get(row[label+"_id"])
            game[label+"_at"] = clock(checkpoint["recorded_at"]) if checkpoint else None
            game[label+"_coverage"] = (checkpoint["summary"] or {}).get("coverage") if checkpoint else None
        game["coverage"] = dict(early=game["early_coverage"],late=game["late_coverage"])
        games.append(game)
        cases += [dict(case, game_id=row["id"], game_revision=revision, title=game["title"], league=game["league"])
                  for case in comparison["cases"]]
    policy = _policy(db)
    state = status(db)
    return dict(policy=policy, scheduling_transition=policy.get("scheduling_transition") if policy else None,
        status=state, storage=state["storage"], games=games, cases=cases, total_games=total,
        offset=offset, limit=limit, next_offset=offset+limit if offset+limit<total else None,
        include_context=include_context, provider_requests=0)


def detail(db, game_id, *, revision=None):
    from .ev_movement import compare_checkpoints, score_comparison
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        game = db.execute("SELECT * FROM public.ev_experiment_game WHERE id=%s", (game_id,)).fetchone()
        if not game:
            raise ValueError("experiment_game_unknown")
        current = _revision(db, game)
        if revision and revision != current:
            raise ValueError("experiment_revision_changed")
        roots = [game[k] for k in ("policy_id", "schedule_id", "early_id", "late_id", "outcome_id") if game[k]]
        index = _closure(db, roots)
        early = _checkpoint_view(db, game, "early", index)
        late = _checkpoint_view(db, game, "late", index)
        comparison = compare_checkpoints(early, late)
        outcome = _value(index[game["outcome_id"]], index) if game["outcome_id"] else None
        history = list(db.execute("SELECT id FROM public.ev_experiment_record WHERE game_id=%s AND kind IN ('schedule','outcome') ORDER BY recorded_at,id", (game_id,)))
        history_index = _closure(db, [row["id"] for row in history])
        tasks = list(db.execute("SELECT * FROM public.ev_experiment_task WHERE game_id=%s ORDER BY checkpoint", (game_id,)))
        return dict(game=_game_summary(game, current), revision=current, policy=_value(index[game["policy_id"]], index),
            early=early, late=late, **comparison, outcomes=[dict(_value(history_index[r["id"]], history_index), id=r["id"],
                persisted_at=clock(history_index[r["id"]]["recorded_at"])) for r in history if history_index[r["id"]]["kind"] == "outcome"],
            schedule_history=[dict(_value(history_index[r["id"]], history_index), id=r["id"]) for r in history if history_index[r["id"]]["kind"] == "schedule"],
            quality=score_comparison(comparison, outcome), retention=status(db),
            checkpoint_status=[{k:clock(v) if hasattr(v,"isoformat") else v for k,v in task.items() if k != "token"} for task in tasks],
            provider_requests=0)


def export_game(db, game_id, *, revision=None):
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        game = db.execute("SELECT * FROM public.ev_experiment_game WHERE id=%s", (game_id,)).fetchone()
        if not game:
            raise ValueError("experiment_game_unknown")
        current = _revision(db, game)
        if revision and current != revision:
            raise ValueError("experiment_revision_changed")
        roots = [row["id"] for row in db.execute("SELECT id FROM public.ev_experiment_record WHERE game_id=%s OR id=%s ORDER BY recorded_at,id", (game_id, game["policy_id"]))]
        index = _closure(db, roots)
        exported = [{k:clock(v) if hasattr(v,"isoformat") else v for k,v in row.items()} for row in index.values()]
        task_rows = list(db.execute("SELECT * FROM public.ev_experiment_task WHERE game_id=%s ORDER BY checkpoint", (game_id,)))
        body = dict(schema="predict-ev-checkpoint-export-1", version=VERSION, game=_game_summary(game, current),
            revision=current, exported_at=clock(utc()), root_ids=roots, records=exported,
            tasks=[{k:clock(v) if hasattr(v,"isoformat") else v for k,v in row.items() if k != "token"} for row in task_rows],
            retention=status(db), completeness="all_retained_game_revisions_and_shared_reproduction_dependencies; no_truncation",
            provider_requests=0)
        result = dict(body, manifest=dict(bundle_sha256=hashed(body), record_count=len(exported),
            payload_bytes=sum(row["payload_bytes"] for row in exported),
            records_by_kind=dict(Counter(row["kind"] for row in exported)),
            hash_scope="canonical JSON; all top-level fields except manifest",
            byte_cap=2*records.TOTAL_BYTE_CAP+1024*1024))
        if len(encoded(result)) > result["manifest"]["byte_cap"]:
            raise ValueError("experiment_export_capacity")
        return result


def reproduce_export(bundle):
    """Verify every dependency and both checkpoints with no database or network."""
    from .ev_movement import compare_checkpoints, reproduce_checkpoint, score_comparison
    if bundle.get("schema") != "predict-ev-checkpoint-export-1" or hashed({k:v for k,v in bundle.items() if k != "manifest"}) != bundle["manifest"]["bundle_sha256"]:
        raise ValueError("experiment_export_integrity")
    index = {row["id"]: row for row in bundle["records"]}
    if len(index) != len(bundle["records"]) or len(index) != bundle["manifest"]["record_count"]:
        raise ValueError("experiment_export_integrity")
    for row in index.values():
        if hashed(row["payload"]) != row["id"] or len(encoded(row["payload"])) != row["payload_bytes"] or references(row["payload"]) != set(row["refs"]):
            raise ValueError("experiment_export_integrity")
        if any(key not in index for key in row["refs"]):
            raise ValueError("experiment_blob_missing")
    game = bundle["game"]
    checkpoints, checks = {}, {}
    for name in ("early", "late"):
        identity = game[name+"_id"]
        if identity:
            row = index[identity]
            value = _value(row, index)
            if stamp(row["recorded_at"]) > stamp(value["deadline_at"]) or stamp(value["known_at"]) > stamp(row["recorded_at"]):
                raise ValueError("experiment_checkpoint_persistence_after_deadline")
            checks[name] = reproduce_checkpoint(value["snapshot"])
            checkpoints[name] = value
        else:
            checkpoints[name] = None
    comparison = compare_checkpoints(checkpoints["early"], checkpoints["late"])
    outcome = _value(index[game["outcome_id"]], index) if game["outcome_id"] else None
    return dict(version=VERSION, records=len(index), checkpoints=checks, counts=comparison["counts"],
                quality=score_comparison(comparison, outcome), provider_requests=0)
