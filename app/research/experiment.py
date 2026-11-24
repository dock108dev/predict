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
from app.comparison.fee_mode import read as read_fee_mode
from app.comparison.reference_scope import REQUEST_BOOKS, VERSION as REFERENCE_SCOPE_VERSION
from . import records
from .experiment_evidence import (
    ACCOUNTING_METADATA_BYTES, GAME_METADATA_BYTES, pack, pack_checkpoint, references, unpack,
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
LATE_BATCH_SIZE = 25
RETENTION_VERSION = 'checkpoint-and-market-witness-2'


def _retention_policy():
    return dict(version=RETENTION_VERSION, checkpoints_only=True,
        shared_inputs='content_addressed_nested_JSON', no_automatic_eviction=True,
        total_byte_cap=records.TOTAL_BYTE_CAP, max_games=MAX_GAMES,
        metadata_bytes_per_game=GAME_METADATA_BYTES,
        late_reservation='early_unique_bytes_plus_market_publication_estimate_plus_max_64KiB_or_25_percent')


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
    root, blobs = pack_checkpoint(value) if kind == "checkpoint" else pack(value)
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
        mode = read_fee_mode(db)
        row = db.execute("SELECT policy_id FROM public.ev_experiment_accounting WHERE singleton").fetchone()
        if row["policy_id"]:
            index = _closure(db, [row["policy_id"]])
            previous = _value(index[row["policy_id"]], index)
            retention_current = previous.get('retention', {}).get('version') == RETENTION_VERSION
            if (previous.get('requested_scope_version') == REFERENCE_SCOPE_VERSION
                    and previous['requested_scope']['bookmakers'] == list(REQUEST_BOOKS)
                    and previous.get('fee_mode') == mode and retention_current):
                return dict(previous, id=row['policy_id'])
            # Scope changes append a new policy for future games. A declared
            # game's policy_id, original activation, clocks and frozen evidence
            # stay unchanged, including its still-pending checkpoint requests.
            policy = deepcopy(previous)
            if (previous.get('requested_scope_version') != REFERENCE_SCOPE_VERSION
                    or previous['requested_scope']['bookmakers'] != list(REQUEST_BOOKS)):
                policy['requested_scope'] = dict(previous['requested_scope'], bookmakers=list(REQUEST_BOOKS))
                policy['requested_scope_version'] = REFERENCE_SCOPE_VERSION
                policy['scope_activated_at'] = clock(at)
                policy['scope_transition'] = dict(previous_policy_id=row['policy_id'], changed_at=clock(at),
                    existing_games='retain_original_policy_and_request_scope',
                    probability_policy='unchanged; additional_books_are_reference_prices_and_market_book_comparisons')
            if previous.get('fee_mode') != mode:
                policy['fee_mode'] = deepcopy(mode)
                policy['fee_mode_transition'] = dict(previous_policy_id=row['policy_id'], changed_at=clock(at),
                    existing_evidence='immutable; each_new_checkpoint_freezes_its_actual_fee_mode')
            if not retention_current:
                policy['retention'] = _retention_policy()
                policy['retention_transition'] = dict(previous_policy_id=row['policy_id'], changed_at=clock(at),
                    existing_evidence='immutable; existing_late_reservations_preserved')
            policy['fee_mode_rule'] = 'declared_mode_is_context; each_checkpoint_freezes_actual_mode; no_retroactive_recalculation'
            identity, _ = _write(db, 'policy', policy)
            db.execute('UPDATE public.ev_experiment_accounting SET policy_id=%s WHERE singleton', (identity,))
            return dict(policy, id=identity)
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
            fee_mode=deepcopy(mode),
            fee_mode_rule='declared_mode_is_context; each_checkpoint_freezes_actual_mode; no_retroactive_recalculation',
            requested_scope_version=REFERENCE_SCOPE_VERSION, scope_activated_at=clock(at),
            requested_scope=dict(bookmakers=list(REQUEST_BOOKS), includeAltLines=True,
                odd_ids=["points-all-game-ou-over","points-all-game-ou-under","points-away-game-ml-away",
                    "points-away-game-sp-away","points-home-game-ml-home","points-home-game-sp-home"]),
            reschedules="preserve_early; append_schedule; retarget_late; mark_settlement_continuity_unverified",
            retention=_retention_policy(),
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


def late_schedule_pressure(db, *, at, through):
    """The existing protected demand, grouped by its actual capture windows."""
    windows = {(row["target_at"], row["deadline_at"]): row["tasks"] for row in db.execute(
        """SELECT target_at,deadline_at,count(*) tasks FROM public.ev_experiment_task late
        WHERE checkpoint='late' AND state IN ('pending','claimed') AND target_at<=%s AND deadline_at>=%s
          AND NOT EXISTS (SELECT 1 FROM public.ev_experiment_task early WHERE early.game_id=late.game_id
                          AND early.checkpoint='early' AND early.state IN ('pending','claimed'))
        GROUP BY target_at,deadline_at ORDER BY target_at,deadline_at""", (through, at))}
    return dict(windows=windows, objects=sum(windows.values()))


def task_authorized(db, token, *, at=None):
    at = at or utc()
    row = db.execute("""SELECT t.*,g.event,g.schedule_id current_schedule FROM public.ev_experiment_task t
        JOIN public.ev_experiment_game g ON g.id=t.game_id WHERE t.token=%s AND t.state='claimed'""", (token,)).fetchone()
    return bool(row and row["schedule_id"] == row["current_schedule"]
                and not row["event"].get("status", {}).get("cancelled")
                and (row["checkpoint"] != "late" or not db.execute(
                    "SELECT 1 FROM public.ev_experiment_task WHERE game_id=%s AND checkpoint='early' AND state IN ('pending','claimed')",
                    (row["game_id"],)).fetchone())
                and row["target_at"] <= at <= row["deadline_at"])


def authorized_late_tokens(db, tokens, *, at):
    return {row["token"] for row in db.execute("""
        SELECT t.token FROM public.ev_experiment_task t
        JOIN public.ev_experiment_game g ON g.id=t.game_id
        WHERE t.token=ANY(%s) AND t.state='claimed' AND t.checkpoint='late'
          AND t.schedule_id=g.schedule_id AND t.target_at<=%s AND t.deadline_at >=%s
          AND g.event#>'{status,cancelled}' IS DISTINCT FROM 'true'::jsonb
          AND NOT EXISTS (SELECT 1 FROM public.ev_experiment_task early WHERE early.game_id=t.game_id
                          AND early.checkpoint='early' AND early.state IN ('pending','claimed'))
        """, (list(tokens), at, at))}


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


def due(db, *, at=None, limit=1, late_only=False, recheck_clock=False):
    at = at or utc()
    limit = max(1, min(LATE_BATCH_SIZE if late_only else 8, int(limit)))
    claimed = []
    # Idle polling must not queue behind, or acquire, the whole-database
    # research writer lock. If work becomes due later it is read next turn.
    work = db.execute("""SELECT 1 FROM public.ev_experiment_task t
        WHERE (state='pending' AND deadline_at<%s)
          OR (state='claimed' AND (deadline_at<%s OR claimed_at<%s))
          OR (state='pending' AND target_at<=%s AND (%s=false OR checkpoint='late')
              AND (checkpoint<>'late' OR NOT EXISTS (
                SELECT 1 FROM public.ev_experiment_task early
                WHERE early.game_id=t.game_id AND early.checkpoint='early' AND early.state IN ('pending','claimed'))))
        LIMIT 1""", (at, at, at-timedelta(seconds=CLAIM_TIMEOUT_SECONDS), at, late_only)).fetchone()
    if not work:
        return claimed
    with db.transaction():
        _lock(db)
        if recheck_clock:
            at = max(at, _dbclock(db))
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
        rows = db.execute("""SELECT t.*,g.event,g.late_reserved_bytes,g.policy_id FROM public.ev_experiment_task t JOIN public.ev_experiment_game g ON g.id=t.game_id
            WHERE t.state='pending' AND t.target_at<=%s AND t.deadline_at>=%s
              AND (%s=false OR t.checkpoint='late')
              AND (t.checkpoint<>'late' OR NOT EXISTS (
                SELECT 1 FROM public.ev_experiment_task early
                WHERE early.game_id=t.game_id AND early.checkpoint='early' AND early.state IN ('pending','claimed')))
            ORDER BY CASE t.checkpoint WHEN 'late' THEN 0 WHEN 'early' THEN 1 ELSE 2 END,t.deadline_at,t.game_id
            LIMIT %s FOR UPDATE OF t SKIP LOCKED""", (at, at, late_only, limit))
        policies = {}
        usage = records.retention_usage(db)
        window = None
        for row in rows:
            if late_only:
                row_window = (row["target_at"], row["deadline_at"])
                if window is not None and row_window != window:
                    break
                window = row_window
            if row["checkpoint"] == "outcome" and row["attempts"] >= len(OUTCOME_OFFSETS):
                db.execute("UPDATE public.ev_experiment_task SET state='exhausted',last_reason='outcome_request_budget_exhausted',updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='outcome'", (row["game_id"],))
                continue
            own_reservation = row["late_reserved_bytes"] if row["checkpoint"] == "late" else 0
            if usage["total"] + usage["reserved"] + MIN_CHECKPOINT_RUNWAY > records.TOTAL_BYTE_CAP + own_reservation:
                db.execute("UPDATE public.ev_experiment_task SET state='refused',refusals=refusals+1,first_refused_at=COALESCE(first_refused_at,%s),last_refused_at=%s,last_reason='research_retention_capacity_before_dispatch' WHERE game_id=%s AND checkpoint=%s", (at,at,row["game_id"],row["checkpoint"]))
                if row["checkpoint"] == "late":
                    db.execute("UPDATE public.ev_experiment_game SET late_reserved_bytes=0 WHERE id=%s", (row["game_id"],))
                    usage["reserved"] -= own_reservation
                continue
            token = uuid4().hex
            db.execute("UPDATE public.ev_experiment_task SET state='claimed',token=%s,claimed_at=%s,attempts=attempts+1,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint=%s",
                       (token, at, row["game_id"], row["checkpoint"]))
            if row['policy_id'] not in policies:
                index = _closure(db, [row['policy_id']])
                policies[row['policy_id']] = _value(index[row['policy_id']], index)
            claimed.append(dict(game_id=row["game_id"], checkpoint=row["checkpoint"], token=token,
                policy_id=row['policy_id'], requested_scope=deepcopy(policies[row['policy_id']]['requested_scope']),
                schedule_id=row["schedule_id"], event=row["event"], target_at=clock(row["target_at"]),
                deadline_at=clock(row["deadline_at"]), requested_at=clock(at), attempt=row["attempts"]+1,
                outcome_slot_index=row["slot_index"]))
    return claimed


def defer_checkpoint(db, claim, *, at):
    """Release only an undispatched lower-priority claim on its exact token."""
    checkpoint = claim["checkpoint"]
    if checkpoint not in ("early", "outcome"):
        raise ValueError("experiment_defer_requires_non_late_claim")
    row = db.execute("""UPDATE public.ev_experiment_task SET state='pending',token=NULL,
        claimed_at=NULL,attempts=greatest(0,attempts-1),last_reason='protected_tminus10_capture_due',
        updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint=%s
        AND state='claimed' AND token=%s AND schedule_id=%s AND deadline_at>=%s RETURNING game_id""",
        (claim["game_id"], checkpoint, claim["token"], claim["schedule_id"], at)).fetchone()
    if row:
        return dict(state="deferred", reason="protected_tminus10_capture_due", game_id=row["game_id"],
                    checkpoint=checkpoint)
    return fail_checkpoint(db, claim["game_id"], checkpoint, "experiment_authority_or_window_closed",
                           token=claim["token"], at=at)


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
    index = index or _closure(db, [identity, *([game["baseline_correction_id"]] if game.get("baseline_correction_id") else [])])
    row = index[identity]
    value = _value(row, index)
    view = dict(value, id=identity, persisted_at=clock(row["recorded_at"]),
                actual_at=clock(row["recorded_at"]), captured_at=clock(row["recorded_at"]),
                target_at=value["target_at"], window_start=value["target_at"], deadline_at=value["deadline_at"])
    if checkpoint == "late" and value["schedule_id"] != game["schedule_id"]:
        view.update(status="superseded_by_reschedule", reason="rescheduled_late_target_changed",
                    current_target_at=clock(task["target_at"]), current_deadline_at=clock(task["deadline_at"]))
    return _corrected_view(view, checkpoint, game, index)


def _corrected_view(view, checkpoint, game, index):
    correction_id = game.get("baseline_correction_id")
    if not correction_id:
        return view
    correction_row = index.get(correction_id)
    if correction_row is None:
        raise ValueError("experiment_baseline_correction_missing")
    correction = _value(correction_row, index)
    if correction.get("correction_kind") != "first_actual_observation_role_alias":
        raise ValueError("experiment_baseline_correction_invalid")
    if view["id"] != correction["first_observation_id"]:
        return view
    result = dict(view, baseline_correction_id=correction_id,
        corrected_at=clock(correction_row["recorded_at"]), original_checkpoint=view["checkpoint"],
        correction_reason=correction["reason"])
    if checkpoint == "early":
        result.update(checkpoint="early", role="first_actual_observation_recovered_from_existing_checkpoint",
                      original_early_id=correction["original_early_id"])
    else:
        result.update(status="not_comparable_baseline_correction",
                      reason="same_actual_observation_is_early_baseline; no_distinct_valid_late_checkpoint")
    return result


def _comparison_value(db, game):
    from .ev_movement import compare_checkpoints
    roots = [game[key] for key in ("early_id", "late_id", "baseline_correction_id") if game.get(key)]
    index = _closure(db, roots)
    early = _checkpoint_view(db, game, "early", index)
    late = _checkpoint_view(db, game, "late", index)
    return compare_checkpoints(early, late)


def _write_comparison(db, game_id, value):
    compact = dict(value)
    compact.pop("context", None)
    compact.pop("reference_context", None)
    compact.pop("main_line_links", None)
    identity, size = _write(db, "comparison", compact, game_id=game_id)
    db.execute("UPDATE public.ev_experiment_game SET comparison_id=%s,retained_cases=%s,unique_payload_bytes=unique_payload_bytes+%s,updated_at=clock_timestamp() WHERE id=%s",
               (identity, len(value["cases"]), size, game_id))


def _comparison(db, game):
    value = _comparison_value(db, game)
    _write_comparison(db, game["id"], value)
    return value


def finish_pending_comparison(db, *, can_start):
    game = db.execute("""SELECT * FROM public.ev_experiment_game
        WHERE late_id IS NOT NULL AND comparison_id IS NULL
        ORDER BY updated_at,id LIMIT 1""").fetchone()
    if not game or not can_start():
        return None
    value = _comparison_value(db, game)
    with db.transaction():
        _lock(db)
        unchanged = db.execute("""SELECT 1 FROM public.ev_experiment_game
            WHERE id=%s AND schedule_id=%s AND late_id=%s
              AND early_id IS NOT DISTINCT FROM %s AND baseline_correction_id IS NOT DISTINCT FROM %s
              AND comparison_id IS NULL FOR UPDATE""", (game["id"], game["schedule_id"],
                game["late_id"], game["early_id"], game["baseline_correction_id"])).fetchone()
        if unchanged:
            _write_comparison(db, game["id"], value)
    return game["id"]


def correct_first_observation(db, game_id, *, reason, evidence_reference):
    """Append an explicit role correction using already persisted source facts.

    The referenced checkpoint retains its original receipt, knowledge and SQL
    persistence clocks. This correction is recorded now and never manufactures
    a pre-target baseline or a second observation from the same physical page.
    """
    if not isinstance(reason,str) or not 1 <= len(reason.encode()) <= 1024:
        raise ValueError("experiment_baseline_correction_reason")
    if not isinstance(evidence_reference,str) or not 1 <= len(evidence_reference.encode()) <= 2048:
        raise ValueError("experiment_baseline_correction_evidence")
    with db.transaction():
        _lock(db)
        game = db.execute("SELECT * FROM public.ev_experiment_game WHERE id=%s FOR UPDATE",(game_id,)).fetchone()
        if not game:
            raise ValueError("experiment_game_unknown")
        rows = list(db.execute("SELECT id FROM public.ev_experiment_record WHERE game_id=%s AND kind='checkpoint' ORDER BY recorded_at,id",(game_id,)))
        if not rows:
            raise ValueError("experiment_baseline_correction_no_observation")
        index = _closure(db,[row["id"] for row in rows])
        candidates = [(index[row["id"]],_value(index[row["id"]],index)) for row in rows]
        first, value = min(candidates,key=lambda pair:(stamp(pair[1]["received_at"]),
            stamp(pair[1]["known_at"]),pair[0]["recorded_at"],pair[0]["id"]))
        if first["game_id"] != game_id or value.get("status") != "captured" or stamp(value["known_at"]) > first["recorded_at"]:
            raise ValueError("experiment_baseline_correction_source_invalid")
        if game["early_id"] == first["id"]:
            return dict(state="unchanged",game_id=game_id,first_observation_id=first["id"],
                        baseline_correction_id=game.get("baseline_correction_id"))
        now = _dbclock(db)
        original_early_id = game["early_id"]
        correction = dict(correction_version="first-actual-observation-role-correction-1",
            correction_kind="first_actual_observation_role_alias", reason=reason,
            evidence_reference=evidence_reference, correction_requested_at=clock(now),
            original_early_id=original_early_id, first_observation_id=first["id"],
            original_late_id=game["late_id"], original_checkpoint=first["checkpoint"],
            first_received_at=value["received_at"], first_known_at=value["known_at"],
            first_persisted_at=clock(first["recorded_at"]),
            late_comparability="same_point_not_comparable" if game["late_id"] == first["id"] else "distinct_point_requires_original_timing_validation",
            historical_records="all_original_checkpoint_rows_and_clocks_preserved",
            provider_requests=0, new_measurement=False)
        identity, size = _write(db,"comparison",correction,game_id=game_id,checkpoint="baseline_correction")
        db.execute("""UPDATE public.ev_experiment_game SET early_id=%s,baseline_correction_id=%s,
            state='baseline_corrected',late_reserved_bytes=0,unique_payload_bytes=unique_payload_bytes+%s,
            updated_at=clock_timestamp() WHERE id=%s""",(first["id"],identity,size,game_id))
        db.execute("""UPDATE public.ev_experiment_task SET state='captured',result_id=%s,token=NULL,
            last_reason='first_actual_observation_role_corrected; see_baseline_correction',
            updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='early'""",(first["id"],game_id))
        if game["late_id"] == first["id"]:
            db.execute("""UPDATE public.ev_experiment_task SET state='missed',token=NULL,
                last_reason='first_actual_page_is_early_baseline; no_distinct_valid_late_checkpoint',
                updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='late'""",(game_id,))
        game = db.execute("SELECT * FROM public.ev_experiment_game WHERE id=%s",(game_id,)).fetchone()
        _comparison(db,game)
        return dict(state="corrected",game_id=game_id,id=identity,original_early_id=original_early_id,
            first_observation_id=first["id"], corrected_at=clock(_get(db,identity)["recorded_at"]),provider_requests=0)


def capture(db, game_id, checkpoint, snapshot, *, token=None, requested_at=None,
            received_at=None, known_at=None, scope=None, market_publication_bytes=0,
            snapshot_bytes=None, defer_comparison=False):
    if checkpoint not in ("early", "late"):
        raise ValueError("experiment_checkpoint_kind")
    checked_at = None
    try:
        with db.transaction():
            _lock(db)
            task, game = _task(db, game_id, checkpoint, token)
            checked_at = now = _dbclock(db)
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
            frozen = dict(snapshot)
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
            if snapshot.get("fee_mode") is not None:
                value["fee_mode"] = deepcopy(snapshot["fee_mode"])
            if checkpoint == "late":
                # The late capture may consume its own reservation, while other
                # games' reserved reproduction space remains protected.
                db.execute("UPDATE public.ev_experiment_game SET late_reserved_bytes=0 WHERE id=%s", (game_id,))
            identity, size = _write(db, "checkpoint", value, game_id=game_id, checkpoint=checkpoint,
                summary=dict(requested_at=clock(requested),received_at=clock(received),known_at=clock(known),
                    target_at=clock(task["target_at"]),deadline_at=clock(task["deadline_at"]),
                    coverage=deepcopy(snapshot.get("coverage") or {}),
                    **({"fee_mode":deepcopy(snapshot["fee_mode"])} if snapshot.get("fee_mode") is not None else {})))
            if checkpoint == "early":
                late_target = stamp(game["event"]["starts_at"])-timedelta(seconds=LATE_SECONDS)
                reserve = 0
                if known < late_target:
                    # The late transaction must retain both immutable research
                    # inputs and the inspectable Data publication.
                    paired_bytes = size + market_publication_bytes
                    reserve = paired_bytes + max(MIN_CHECKPOINT_RUNWAY, paired_bytes // 4)
                    _admit(db, 0, reserve=reserve)
                else:
                    db.execute("UPDATE public.ev_experiment_task SET state='missed',token=NULL,last_reason=CASE WHEN last_reason='late_discovery_no_pre_target_baseline' THEN last_reason ELSE 'early_baseline_after_target' END,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint='late' AND state<>'captured'", (game_id,))
                db.execute("UPDATE public.ev_experiment_game SET late_reserved_bytes=%s WHERE id=%s", (reserve,game_id))
            row = db.execute("SELECT recorded_at FROM public.ev_experiment_record WHERE id=%s",
                             (identity,)).fetchone()
            checked_at = _dbclock(db)
            if row["recorded_at"] > task["deadline_at"] or checked_at > task["deadline_at"]:
                raise ValueError("experiment_checkpoint_persistence_after_deadline")
            db.execute("UPDATE public.ev_experiment_game SET " + checkpoint + "_id=%s,unique_payload_bytes=unique_payload_bytes+%s,raw_checkpoint_bytes=raw_checkpoint_bytes+%s,updated_at=clock_timestamp() WHERE id=%s",
                       (identity, size, snapshot_bytes if snapshot_bytes is not None else len(encoded(snapshot)), game_id))
            db.execute("UPDATE public.ev_experiment_task SET state='captured',result_id=%s,token=NULL,last_reason=NULL,updated_at=clock_timestamp() WHERE game_id=%s AND checkpoint=%s",
                       (identity, game_id, checkpoint))
            if defer_comparison and checkpoint == "late":
                # Checkpoint and market evidence are complete now. A null
                # comparison pointer with a late capture lets the idle owner
                # rebuild the derived comparison after a crash or restart.
                db.execute("UPDATE public.ev_experiment_game SET comparison_id=NULL,retained_cases=0 WHERE id=%s",
                           (game_id,))
            else:
                game = db.execute("SELECT * FROM public.ev_experiment_game WHERE id=%s", (game_id,)).fetchone()
                _comparison(db, game)
            checked_at = _dbclock(db)
            if checked_at > task["deadline_at"]:
                raise ValueError("experiment_checkpoint_persistence_after_deadline")
            return dict(state="captured", id=identity, game_id=game_id, checkpoint=checkpoint,
                        recorded_at=clock(row["recorded_at"]), new_unique_payload_bytes=size)
    except Exception as exc:
        if not records._retention_failure(exc) and str(exc) not in (
                "experiment_checkpoint_window_missed", "experiment_checkpoint_persistence_after_deadline",
                "experiment_causal_clock_order"):
            raise
        return fail_checkpoint(db, game_id, checkpoint, str(exc), token=token, dispatched=True,
            details=dict(snapshot.get("acquisition") or {},
                         requested_at=clock(requested_at) if requested_at else None,
                         received_at=clock(received_at) if received_at else None,
                         known_at=clock(known_at) if known_at else None,
                         failure_checked_at=clock(checked_at) if checked_at else None))


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
        baseline_correction_id=row.get("baseline_correction_id"),
        retained_cases=row["retained_cases"], unique_payload_bytes=row["unique_payload_bytes"],
        raw_checkpoint_bytes=row["raw_checkpoint_bytes"], late_reserved_bytes=row["late_reserved_bytes"])


def _revision(db, row):
    tasks = list(db.execute("SELECT checkpoint,state,target_at,deadline_at,last_reason,result_id,attempts,refusals FROM public.ev_experiment_task WHERE game_id=%s ORDER BY checkpoint", (row["id"],)))
    return hashed(dict(policy=row["policy_id"], schedule=row["schedule_id"], early=row["early_id"],
        late=row["late_id"], outcome=row["outcome_id"], comparison=row["comparison_id"],
        baseline_correction=row.get("baseline_correction_id"),
        tasks=[{k:clock(v) if hasattr(v,"isoformat") else v for k,v in task.items()} for task in tasks]))


def status(db):
    accounting = db.execute("SELECT * FROM public.ev_experiment_accounting WHERE singleton").fetchone()
    usage = records.retention_usage(db)
    task_counts = db.execute("SELECT checkpoint,state,count(*) records,sum(refusals)::bigint refusals FROM public.ev_experiment_task GROUP BY checkpoint,state ORDER BY checkpoint,state").fetchall()
    # A non-null pair can still be the same recovered page, a superseded
    # schedule or an invalid order. Check only immutable checkpoint headers and
    # their small summaries; never unpack market snapshots for a status read.
    games = db.execute("""WITH checkpoint_pairs AS (
        SELECT g.unique_payload_bytes,g.late_reserved_bytes,
            (g.early_id<>g.late_id
             AND e.kind='checkpoint' AND l.kind='checkpoint'
             AND e.checkpoint='early' AND l.checkpoint='late'
             AND e.game_id=g.id AND l.game_id=g.id
             AND et.state='captured' AND lt.state='captured'
             AND et.result_id=g.early_id AND lt.result_id=g.late_id
             AND et.schedule_id=g.schedule_id AND lt.schedule_id=g.schedule_id
             AND NULLIF(e.payload#>>'{summary,target_at}','')::timestamptz=et.target_at
             AND NULLIF(e.payload#>>'{summary,deadline_at}','')::timestamptz=et.deadline_at
             AND NULLIF(l.payload#>>'{summary,target_at}','')::timestamptz=lt.target_at
             AND NULLIF(l.payload#>>'{summary,deadline_at}','')::timestamptz=lt.deadline_at
             AND NULLIF(e.payload#>>'{summary,received_at}','')::timestamptz<=NULLIF(e.payload#>>'{summary,known_at}','')::timestamptz
             AND NULLIF(l.payload#>>'{summary,received_at}','')::timestamptz<=NULLIF(l.payload#>>'{summary,known_at}','')::timestamptz
             AND NULLIF(e.payload#>>'{summary,known_at}','')::timestamptz<NULLIF(l.payload#>>'{summary,known_at}','')::timestamptz
             AND NULLIF(e.payload#>>'{summary,known_at}','')::timestamptz<lt.target_at
             AND NULLIF(e.payload#>>'{summary,known_at}','')::timestamptz<=e.recorded_at
             AND NULLIF(l.payload#>>'{summary,known_at}','')::timestamptz<=l.recorded_at
             AND NULLIF(l.payload#>>'{summary,received_at}','')::timestamptz>=lt.target_at
             AND e.recorded_at<l.recorded_at
             AND e.recorded_at<=et.deadline_at AND l.recorded_at<=lt.deadline_at) valid_pair
        FROM public.ev_experiment_game g
        LEFT JOIN public.ev_experiment_task et ON et.game_id=g.id AND et.checkpoint='early'
        LEFT JOIN public.ev_experiment_task lt ON lt.game_id=g.id AND lt.checkpoint='late'
        LEFT JOIN public.ev_experiment_record e ON e.id=g.early_id
        LEFT JOIN public.ev_experiment_record l ON l.id=g.late_id
    ) SELECT count(*) n,count(*) FILTER(WHERE valid_pair) complete,
        COALESCE(sum(unique_payload_bytes),0) bytes,
        COALESCE(sum(late_reserved_bytes),0) late_reserved,
        COALESCE(avg(unique_payload_bytes) FILTER(WHERE valid_pair),0) mean_complete_bytes
        FROM checkpoint_pairs""").fetchone()
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


def catalog(db, *, include_context=False, outcomes_only=False, limit=50, offset=0):
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    predicate = "outcome_id IS NOT NULL" if outcomes_only else "true" if include_context else "retained_cases>0"
    total = db.execute("SELECT count(*) n FROM public.ev_experiment_game WHERE " + predicate).fetchone()["n"]
    rows = list(db.execute("SELECT * FROM public.ev_experiment_game WHERE " + predicate +
        " ORDER BY first_observed_at DESC,id LIMIT %s OFFSET %s", (limit, offset)))
    if outcomes_only:
        return dict(games=[_game_summary(row, _revision(db, row)) for row in rows],
            total_games=total, offset=offset, limit=limit, next_offset=offset+limit if offset+limit<total else None,
            provider_requests=0)
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
        roots = [game[k] for k in ("policy_id", "schedule_id", "early_id", "late_id", "outcome_id", "baseline_correction_id") if game.get(k)]
        index = _closure(db, roots)
        early = _checkpoint_view(db, game, "early", index)
        late = _checkpoint_view(db, game, "late", index)
        comparison = compare_checkpoints(early, late)
        outcome = _value(index[game["outcome_id"]], index) if game["outcome_id"] else None
        correction = None
        rejected_early = None
        if game.get("baseline_correction_id"):
            correction_row = index[game["baseline_correction_id"]]
            correction = dict(_value(correction_row,index),id=correction_row["id"],corrected_at=clock(correction_row["recorded_at"]))
            if correction["original_early_id"]:
                rejected_index = _closure(db,[correction["original_early_id"]])
                rejected_row = rejected_index[correction["original_early_id"]]
                rejected_early = dict(_value(rejected_row,rejected_index),id=rejected_row["id"],
                    persisted_at=clock(rejected_row["recorded_at"]),status="invalid_early_role",
                    reason="later_actual_page_was_previously_assigned_early_role; original_preserved")
        history = list(db.execute("SELECT id FROM public.ev_experiment_record WHERE game_id=%s AND kind IN ('schedule','outcome') ORDER BY recorded_at,id", (game_id,)))
        history_index = _closure(db, [row["id"] for row in history])
        tasks = list(db.execute("SELECT * FROM public.ev_experiment_task WHERE game_id=%s ORDER BY checkpoint", (game_id,)))
        return dict(game=_game_summary(game, current), revision=current, policy=_value(index[game["policy_id"]], index),
            early=early, late=late, **comparison, outcomes=[dict(_value(history_index[r["id"]], history_index), id=r["id"],
                persisted_at=clock(history_index[r["id"]]["recorded_at"])) for r in history if history_index[r["id"]]["kind"] == "outcome"],
            schedule_history=[dict(_value(history_index[r["id"]], history_index), id=r["id"]) for r in history if history_index[r["id"]]["kind"] == "schedule"],
            quality=score_comparison(comparison, outcome), retention=status(db),
            baseline_correction=correction, later_observation_context=rejected_early,
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
            byte_cap=records.EVIDENCE_RESPONSE_BYTE_CAP))
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
    correction_id = game.get("baseline_correction_id")
    if correction_id:
        if correction_id not in index:
            raise ValueError("experiment_baseline_correction_missing")
        correction = _value(index[correction_id],index)
        for key in ("first_observation_id","original_early_id","original_late_id"):
            source_id = correction.get(key)
            if source_id and (source_id not in index or index[source_id]["kind"] != "checkpoint"
                              or index[source_id]["game_id"] != game["id"]):
                raise ValueError("experiment_baseline_correction_source_invalid")
        if game["early_id"] != correction["first_observation_id"]:
            raise ValueError("experiment_baseline_correction_invalid")
    history_checks = {}
    for row in index.values():
        if row["kind"] == "checkpoint":
            value = _value(row,index)
            if stamp(row["recorded_at"]) > stamp(value["deadline_at"]) or stamp(value["known_at"]) > stamp(row["recorded_at"]):
                raise ValueError("experiment_checkpoint_persistence_after_deadline")
            history_checks[row["id"]] = reproduce_checkpoint(value["snapshot"])
    for name in ("early", "late"):
        identity = game[name+"_id"]
        if identity:
            row = index[identity]
            value = _value(row, index)
            if stamp(row["recorded_at"]) > stamp(value["deadline_at"]) or stamp(value["known_at"]) > stamp(row["recorded_at"]):
                raise ValueError("experiment_checkpoint_persistence_after_deadline")
            view = _corrected_view(dict(value,id=identity,persisted_at=row["recorded_at"]),name,game,index)
            if view["status"] == "captured":
                checks[name] = history_checks[identity]
            checkpoints[name] = view
        else:
            checkpoints[name] = None
    comparison = compare_checkpoints(checkpoints["early"], checkpoints["late"])
    outcome = _value(index[game["outcome_id"]], index) if game["outcome_id"] else None
    result = dict(version=VERSION, records=len(index), checkpoints=checks, counts=comparison["counts"],
                checkpoint_history_reproduced=len(history_checks),
                baseline_correction_id=correction_id,
                quality=score_comparison(comparison, outcome), provider_requests=0)
    if "fee_modes" in comparison:
        result.update(fee_modes=comparison["fee_modes"], fee_modes_differ=comparison["fee_modes_differ"])
    return result
