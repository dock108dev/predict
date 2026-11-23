"""Durable owner viewing intent, independent of in-play scope and source controls."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.storage.store import connect, stamp

SCHEMA = "predict-activity-mode-1"
DEFAULT_SETTINGS = dict(
    monitor_interval_seconds=1800,
    monitor_phase_seconds=1200,
    monitor_horizon_seconds=86400,
    live_interval_seconds=60,
    live_window_seconds=3600,
    inactivity_seconds=900,
)
MAX_SECONDS = 31536000
# Additional conservative SGO returned-event limits, not Odds API credit pricing.
OBJECTS_PER_15_MINUTES = 300
OBJECTS_PER_DAY = 16800


def operating_budget():
    return dict(
        units="returned_event_objects",
        objects_per_15_minutes=OBJECTS_PER_15_MINUTES,
        objects_per_day=OBJECTS_PER_DAY,
        stricter_account_guards_apply=True,
    )


def acquisition_policy(settings):
    """Effective collection behavior, separate from retained viewing settings."""
    return dict(
        id="first_observed_tminus10",
        data_type="monitor",
        discovery=dict(
            interval_seconds=settings["monitor_interval_seconds"],
            phase_seconds=settings["monitor_phase_seconds"],
            horizon_seconds=settings["monitor_horizon_seconds"],
            continuous=True,
            known_games_billed=True,
        ),
        initial_capture="first_observed",
        final_capture_seconds_before_start=600,
        separate_saved_game_refresh=False,
        live_polling=False,
    )


def clock():
    return datetime.now(timezone.utc)


def validate_settings(settings, *, partial=False):
    if not isinstance(settings, dict) or set(settings) - set(DEFAULT_SETTINGS):
        raise ValueError("Unsupported activity settings")
    settings = deepcopy(settings)
    if not partial and set(settings) == set(DEFAULT_SETTINGS) - {
        "monitor_phase_seconds"
    }:
        settings["monitor_phase_seconds"] = DEFAULT_SETTINGS["monitor_phase_seconds"]
    if not partial and set(settings) != set(DEFAULT_SETTINGS):
        raise ValueError("Complete activity settings required")
    for key, value in settings.items():
        if key == "monitor_phase_seconds":
            if type(value) is not int or not 0 <= value <= MAX_SECONDS:
                raise ValueError("Monitor phase must be nonnegative integer seconds")
            continue
        if key == "monitor_horizon_seconds" and value is None:
            continue
        if type(value) is not int or not 1 <= value <= MAX_SECONDS:
            raise ValueError("Activity intervals must be positive integer seconds")
    return deepcopy(settings)


def monitor_schedule(settings, *, at=None, last_slot=None, catch_up=False):
    """Skip old startup backlog; running owners coalesce the latest due slot."""
    at = stamp(at or clock()).astimezone(timezone.utc)
    interval = settings["monitor_interval_seconds"]
    phase = (
        settings.get("monitor_phase_seconds", DEFAULT_SETTINGS["monitor_phase_seconds"])
        % interval
    )
    step = timedelta(seconds=interval)
    anchor = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=phase)
    slot = anchor + ((at - anchor) // step) * step
    try:
        consumed = stamp(last_slot).astimezone(timezone.utc) if last_slot else None
    except (ValueError, TypeError, AttributeError):
        consumed = None
    grace = timedelta(seconds=min(60, interval / 2))
    due = (consumed is None or consumed < slot) and (catch_up or at - slot <= grace)
    next_slot = slot + step
    if consumed and consumed >= next_slot:
        next_slot = anchor + ((consumed - anchor) // step + 1) * step
    return dict(
        current_slot_at=slot.isoformat(),
        next_slot_at=next_slot.isoformat(),
        next_monitor_at=(slot if due else next_slot).isoformat(),
        due=due,
        interval_seconds=interval,
        phase_seconds=phase,
        catchup_grace_seconds=grace.total_seconds(),
    )


def project(row, *, at=None, runs=None):
    at = stamp(at or clock()).astimezone(timezone.utc)
    row = row or dict(
        mode="monitor",
        settings=DEFAULT_SETTINGS,
        revision=0,
        last_activity_at=None,
        live_until=None,
        reason="default",
    )
    settings = validate_settings(row["settings"])
    deadline = (
        stamp(row["live_until"]).astimezone(timezone.utc)
        if row.get("live_until")
        else None
    )
    expired = row["mode"] == "live" and (deadline is None or at >= deadline)
    last_monitor = (runs or {}).get("monitor", {})
    schedule = monitor_schedule(
        settings,
        at=at,
        last_slot=last_monitor.get("monitor_slot_at"),
        catch_up=bool(last_monitor.get("monitor_slot_at"))
        and last_monitor.get("state") in ("running", "budget_delayed"),
    )
    return dict(
        schema=SCHEMA,
        mode="monitor" if expired else row["mode"],
        requested_mode=row["mode"],
        effective_mode="monitor",
        acquisition_policy=acquisition_policy(settings),
        revision=row["revision"],
        settings=settings,
        last_activity_at=stamp(row["last_activity_at"])
        .astimezone(timezone.utc)
        .isoformat()
        if row.get("last_activity_at")
        else None,
        live_until=deadline.isoformat() if deadline and not expired else None,
        reason="inactivity" if expired else row.get("reason", "selected"),
        runs=runs or {},
        monitor_schedule=schedule,
        next_monitor_at=schedule["next_monitor_at"],
    )


def read_control(*, at=None, connector=None):
    """Fresh, minimal dispatch authority; no activity renewal or provider access."""
    connector = connector or connect
    with connector() as db, db.transaction():
        db.execute("SET TRANSACTION READ ONLY")
        db.execute("SET LOCAL statement_timeout='2s'")
        row = db.execute("""SELECT m.*,(SELECT staged_bytes FROM odds_archive_usage WHERE singleton) AS staged_bytes
            FROM activity_mode m WHERE singleton""").fetchone()
    if (
        row is None
        or type(row.get("staged_bytes")) is not int
        or row["staged_bytes"] < 0
    ):
        raise RuntimeError("archive status unavailable")
    result = project(row, at=at)
    result["staged_bytes"] = row["staged_bytes"]
    return result


def read_status(db=None, *, at=None, connector=None):
    connector = connector or connect
    if db is None:
        with connector() as connection:
            return read_status(connection, at=at)
    row = db.execute("SELECT * FROM activity_mode WHERE singleton").fetchone()
    runs = {}
    for (
        run
    ) in db.execute("""SELECT latest.* FROM (VALUES('monitor'),('live')) kinds(kind)
          CROSS JOIN LATERAL (SELECT id,kind,started_at,scope_start_at,scope_end_at,
            state,completed_at,event_count,reason,progress->>'monitor_slot_at' AS monitor_slot_at FROM activity_collection_run r
            WHERE r.kind=kinds.kind ORDER BY started_at DESC LIMIT 1) latest"""):
        runs[run["kind"]] = {
            k: v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime) else v
            for k, v in run.items()
        }
    result = project(row, at=at, runs=runs)
    result["retention"] = retention_status(db)
    result["operating_budget"] = operating_budget()
    return result


def retention_status(db):
    from app.storage.odds_archive_export import status, MAX_WAIT, CHECK_INTERVAL

    value = status(db)
    feeds = value.get("feeds", [])
    verified = sum(r["verified"] for r in feeds)
    skipped = sum(r["skipped"] for r in feeds)
    last = max(
        (r["last_verified_at"] for r in feeds if r.get("last_verified_at")),
        default=None,
    )
    age = value.get("oldest_age_seconds")
    state = (
        "gaps"
        if skipped
        else "delayed"
        if age is not None and age > MAX_WAIT.total_seconds() + CHECK_INTERVAL
        else "retaining"
        if verified or value["staged_bytes"]
        else "awaiting_first_capture"
    )
    return dict(
        state=state,
        staged_bytes=value["staged_bytes"],
        verified_observations=verified,
        skipped_observations=skipped,
        oldest_age_seconds=age,
        last_verified_at=last.astimezone(timezone.utc).isoformat() if last else None,
    )


def expire(db, *, at=None):
    at = stamp(at or clock()).astimezone(timezone.utc)
    db.execute(
        """UPDATE activity_mode SET mode='monitor',live_until=NULL,reason='inactivity',
        revision=revision+1,updated_at=%s WHERE singleton AND mode='live'
        AND (live_until IS NULL OR live_until<=%s)""",
        (at, at),
    )


def patch(*, mode=None, settings=None, at=None, connector=None):
    connector = connector or connect
    if mode is not None and mode not in ("monitor", "live"):
        raise ValueError("Choose Monitor or Live")
    if mode is None and settings is None:
        raise ValueError("Activity mode or settings required")
    update = validate_settings(settings, partial=True) if settings is not None else {}
    if settings is not None and not update:
        raise ValueError("At least one setting required")
    at = stamp(at or clock()).astimezone(timezone.utc)
    with connector() as db, db.transaction():
        expire(db, at=at)
        row = db.execute(
            "SELECT * FROM activity_mode WHERE singleton FOR UPDATE"
        ).fetchone()
        value = validate_settings(dict(row["settings"], **update))
        selected = mode or row["mode"]
        last = at if selected == "live" else row["last_activity_at"]
        deadline = (
            at + timedelta(seconds=value["inactivity_seconds"])
            if selected == "live"
            else None
        )
        db.execute(
            """UPDATE activity_mode SET mode=%s,settings=%s,last_activity_at=%s,
            live_until=%s,reason='selected',revision=revision+1,updated_at=%s WHERE singleton""",
            (selected, Jsonb(value), last, deadline, at),
        )
        return read_status(db, at=at)


def activity(*, at=None, connector=None):
    """Record explicit owner input only; an expired Live session never reactivates."""
    connector = connector or connect
    at = stamp(at or clock()).astimezone(timezone.utc)
    with connector() as db, db.transaction():
        expire(db, at=at)
        db.execute(
            """UPDATE activity_mode SET last_activity_at=%s,
            live_until=%s+((settings->>'inactivity_seconds')::int*interval '1 second'),
            updated_at=%s WHERE singleton AND mode='live' AND live_until>%s""",
            (at, at, at, at),
        )
        return read_status(db, at=at)


def begin_run(db, kind, status, *, at=None):
    if kind not in ("monitor", "live"):
        raise ValueError("Unsupported collection kind")
    at = stamp(at or clock()).astimezone(timezone.utc)
    settings = status["settings"]
    horizon = (
        settings["monitor_horizon_seconds"]
        if kind == "monitor"
        else settings["live_window_seconds"]
    )
    run = dict(
        id=str(uuid4()),
        kind=kind,
        started_at=at.isoformat(),
        scope_start_at=at.isoformat(),
        scope_end_at=(at + timedelta(seconds=horizon)).isoformat() if horizon else None,
        settings_revision=status["revision"],
        completed=False,
    )
    progress = {}
    if kind == "monitor":
        run["monitor_slot_at"] = monitor_schedule(settings, at=at)["current_slot_at"]
        progress["monitor_slot_at"] = run["monitor_slot_at"]
    db.execute(
        """INSERT INTO activity_collection_run
        (id,kind,started_at,scope_start_at,scope_end_at,settings_revision,progress)
        VALUES(%s,%s,%s,%s,%s,%s,%s)""",
        tuple(
            run[k]
            for k in (
                "id",
                "kind",
                "started_at",
                "scope_start_at",
                "scope_end_at",
                "settings_revision",
            )
        )
        + (Jsonb(progress),),
    )
    return run


def update_run(
    db, run, *, state="running", event_count=0, reason=None, progress=None, at=None
):
    if state not in ("running", "budget_delayed", "partial", "complete", "failed"):
        raise ValueError("Unsupported collection state")
    at = stamp(at or clock()).astimezone(timezone.utc)
    db.execute(
        """UPDATE activity_collection_run SET state=%s,event_count=%s,reason=%s,
        progress=COALESCE(%s,progress),completed_at=%s WHERE id=%s""",
        (
            state,
            event_count,
            reason,
            Jsonb(progress) if progress is not None else None,
            at if state in ("complete", "partial", "failed") else None,
            run["id"],
        ),
    )


def eligible(events, status, *, at=None, kind="live"):
    at = stamp(at or clock()).astimezone(timezone.utc)
    seconds = (
        status["settings"]["live_window_seconds"]
        if kind == "live"
        else status["settings"]["monitor_horizon_seconds"]
    )
    if kind == "live" and status["mode"] != "live":
        return []
    end = at + timedelta(seconds=seconds) if seconds else None
    return [
        e
        for e in events
        if e.get("phase") == "pregame"
        and at < stamp(e["starts_at"])
        and (end is None or stamp(e["starts_at"]) <= end)
        and not any(
            e.get("status", {}).get(k)
            for k in (
                "started",
                "live",
                "ended",
                "completed",
                "cancelled",
                "delayed",
                "suspended",
            )
        )
    ]
