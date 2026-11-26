"""Transactional grading dispatch, leased work and immutable report publication."""

from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.collection.mens_d1_jobs import _late_capture_due
from app.collection.odds_http import BudgetStop
from app.research import records
from app.storage.mens_d1_coverage import OFFICIAL_CORROBORATION_VERSION
from app.storage.store import encoded, hashed

LOG = logging.getLogger(__name__)
LEASE = timedelta(seconds=90)
INPUT_BATCH = 64
VERSION_FIELDS = "r.id,r.supersedes,r.processed_at,r.observed_at,r.evidence_revision,r.grading_rule,r.status"

# CBBD occurrence reconciliation considers adjacent Eastern dates. Provider
# signals also resolve by exact frozen game or source ID for every sport.
MATCH = """((input.game_date BETWEEN job.game_date - 1 AND job.game_date + 1
        AND job.league IN ('NCAAB','all-sports'))
    OR EXISTS (SELECT 1 FROM public.paper_result_dependency dependency
        WHERE dependency.run_id=job.run_id
          AND dependency.dependency IN (input.game_key,input.provider_key)))"""

# Match paper_results.build_report's grading version on the immutable selections.
# The job league check keeps existing single-league reports off the JSON path.
EXPECTED_RULE = """CASE WHEN job.league IN ('NHL','all-sports') AND EXISTS (
    SELECT 1 FROM jsonb_array_elements(run.payload#>'{report,portfolios,all_venues,tickets}') ticket
    WHERE COALESCE(ticket->>'family',ticket#>>'{identity,family}') IN ('spread','total')
      AND (job.league='NHL' OR ticket->>'game_id' IN (
          SELECT game->>'game_id' FROM jsonb_array_elements(run.payload#>'{report,games}') game
          WHERE game->>'league'='NHL'))
) THEN %s ELSE %s END"""


class PublicationDeferred(ValueError):
    """An explicit capacity or capture constraint prevented publication."""


def utc():
    return datetime.now(timezone.utc)


def repair(db, rule=None):
    """Restore missing job/dependency rows and seed the outbox from retained evidence."""
    from app.research import paper_results

    with db.transaction():
        db.execute("""SELECT public.paper_result_register(run.id,run.game_date,run.payload)
            FROM public.research_workspace_run run WHERE public.paper_result_is_run(run.payload)
              AND NOT EXISTS (SELECT 1 FROM public.paper_result_job job WHERE job.run_id=run.id)""")
        db.execute("""INSERT INTO public.paper_result_input(id,game_date)
            SELECT 'daily:' || daily.id,daily.game_date FROM public.mens_d1_revision daily
            WHERE NOT EXISTS (SELECT 1 FROM public.paper_result_input input WHERE input.id='daily:' || daily.id)
            ON CONFLICT DO NOTHING""")
        db.execute("""INSERT INTO public.paper_result_input(id,game_date)
            SELECT 'official:' || binding.id,daily.game_date FROM public.mens_d1_binding binding
            JOIN public.mens_d1_revision daily ON daily.id=binding.schedule_revision_id
            WHERE binding.facts->>'kind'=%s AND NOT EXISTS (
                SELECT 1 FROM public.paper_result_input input WHERE input.id='official:' || binding.id)
            ON CONFLICT DO NOTHING""", (OFFICIAL_CORROBORATION_VERSION,))
        db.execute("""INSERT INTO public.paper_result_input(id,game_date,game_key,provider_key)
            SELECT 'game:' || game.id || ':' || game.schedule_id || ':' || game.outcome_id,
                CASE WHEN game.event->>'league'='NCAAB'
                     THEN ((game.event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date END,
                'game:' || game.id,'provider:' || game.provider || ':' || game.source_event_id
            FROM public.ev_experiment_game game WHERE game.outcome_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM public.paper_result_input input
                  WHERE input.id='game:' || game.id || ':' || game.schedule_id || ':' || game.outcome_id)
            ON CONFLICT DO NOTHING""")
        db.execute("""INSERT INTO public.paper_result_input(id,provider_key)
            SELECT 'legacy:' || record.id,'provider:sportsgameodds:' || public.paper_result_sgo_event(record.payload)
            FROM public.research_record record
            WHERE record.kind='sporting' AND public.paper_result_sgo_event(record.payload) IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM public.paper_result_input input WHERE input.id='legacy:' || record.id)
            ON CONFLICT DO NOTHING""")
        db.execute(f"""UPDATE public.paper_result_job job SET generation=generation+1,
            due_at=clock_timestamp(),attempts=0
            FROM public.research_workspace_run run
            WHERE run.id=job.run_id AND job.generation=job.processed_generation
              AND (job.applied_rule IS DISTINCT FROM ({EXPECTED_RULE}) OR job.current_result_id IS NULL)""",
            (paper_results.NHL_VERSION, rule or paper_results.VERSION))


def dispatch(db):
    """Fan out retained inputs and mark them dispatched in one transaction."""
    return db.execute(f"""WITH batch AS (
        SELECT * FROM public.paper_result_input WHERE dispatched_at IS NULL
        ORDER BY retained_at,id FOR UPDATE SKIP LOCKED LIMIT %s
    ), dirty AS (
        UPDATE public.paper_result_job job SET generation=generation+1,attempts=0,
            due_at=clock_timestamp()
        WHERE EXISTS (SELECT 1 FROM batch input WHERE {MATCH})
    )
    UPDATE public.paper_result_input input SET dispatched_at=clock_timestamp()
    FROM batch WHERE input.id=batch.id""", (INPUT_BATCH,)).rowcount


def claim(db, *, at=None):
    at = at or utc()
    return db.execute("""WITH next AS (
        SELECT run_id FROM public.paper_result_job WHERE generation>processed_generation
          AND due_at<=%s AND (lease_until IS NULL OR lease_until<=%s)
        ORDER BY due_at,run_id FOR UPDATE SKIP LOCKED LIMIT 1
    )
    UPDATE public.paper_result_job job SET lease_token=%s,lease_until=%s,attempts=attempts+1
    FROM next WHERE job.run_id=next.run_id
    RETURNING job.run_id,job.generation,job.lease_token,job.attempts""",
        (at, at, uuid4().hex, at + LEASE)).fetchone()


def _admit(db, size):
    from app.collection.current_storage_policy import SQL_BYTE_CAP, require_disk_space, sql_usage
    from app.storage.store import ROOT

    # Never wait on a collection writer or publish over a protected capture.
    for lock in (records.CURRENT_LOCK, records.LOCK):
        if not db.execute("SELECT pg_try_advisory_xact_lock(%s) held", (lock,)).fetchone()["held"]:
            raise PublicationDeferred("writer_busy")
    if _late_capture_due(db, utc()):
        raise PublicationDeferred("protected_tminus10_capture_due")
    used = records.retention_usage(db)
    if size > records.EVALUATION_RECORD_BYTE_CAP or used["total"] + used["reserved"] + size > records.TOTAL_BYTE_CAP:
        raise PublicationDeferred("research_result_storage_capacity")
    if sql_usage(db) + size * 3 + 8 * 1024 * 1024 > SQL_BYTE_CAP:
        raise PublicationDeferred("research_result_storage_runway")
    try:
        require_disk_space(ROOT / ".local/postgres", append_bytes=size * 3)
    except BudgetStop as error:
        raise PublicationDeferred("research_result_disk_runway") from error


def publish(db, job, report, rule):
    identity = hashed([job["run_id"], rule, report["evidence_revision"]])
    size = len(encoded(report))
    with db.transaction():
        row = db.execute(f"""SELECT generation,current_result_id,
            EXISTS (SELECT 1 FROM public.paper_result_input input
                WHERE input.dispatched_at IS NULL AND {MATCH}) AS input_pending
            FROM public.paper_result_job job WHERE run_id=%s AND lease_token=%s AND lease_until>clock_timestamp()
            FOR UPDATE""", (job["run_id"], job["lease_token"])).fetchone()
        if row is None:
            return None
        if row["generation"] != job["generation"] or row["input_pending"]:
            _release(db, job)
            return None
        if not db.execute("SELECT 1 FROM public.paper_result_report WHERE id=%s", (identity,)).fetchone():
            body = Jsonb(report)
            _admit(db, size)
            db.execute("""INSERT INTO public.paper_result_report
                (id,run_id,grading_rule,evidence_revision,supersedes,status,observed_at,payload_bytes,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (identity, job["run_id"], rule, report["evidence_revision"], row["current_result_id"],
                 report["status"], report.get("result_observed_at"), size, body))
        db.execute("""UPDATE public.paper_result_job
            SET current_result_id=%s,applied_rule=%s,processed_generation=generation,
                lease_token=NULL,lease_until=NULL,attempts=0,last_error=NULL
            WHERE run_id=%s AND lease_token=%s""", (identity, rule, job["run_id"], job["lease_token"]))
    return identity


def _release(db, job, *, delay=0, error=None):
    db.execute("""UPDATE public.paper_result_job SET lease_token=NULL,lease_until=NULL,
        due_at=CASE WHEN generation=%s THEN %s ELSE due_at END,
        last_error=CASE WHEN generation=%s AND %s::text IS NOT NULL THEN %s ELSE last_error END
        WHERE run_id=%s AND lease_token=%s""",
        (job["generation"], utc() + timedelta(seconds=delay), job["generation"], error, error,
         job["run_id"], job["lease_token"]))


def process_one(db, *, grader=None):
    from app.research import paper_results

    if _late_capture_due(db, utc()):
        return None
    grader = grader or paper_results.build
    job = claim(db)
    if job is None:
        return None
    try:
        with db.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            run = db.execute("SELECT * FROM public.research_workspace_run WHERE id=%s", (job["run_id"],)).fetchone()
            report = grader(db, run)
        identity = publish(db, job, report, report.get("grading_rule", paper_results.VERSION))
    except PublicationDeferred as error:
        reason = str(error)
        if reason in ("writer_busy", "protected_tminus10_capture_due"):
            _release(db, job, delay=2)
        else:
            _release(db, job, delay=60, error=reason)
            LOG.warning("Paper result publication deferred for %s (%s)", job["run_id"], reason)
        return None
    except Exception as error:
        delay = min(60, 2 ** min(job["attempts"], 6))
        _release(db, job, delay=delay, error="paper_result_processing_failed")
        LOG.error("Paper result processing failed for %s (%s)", job["run_id"], type(error).__name__)
        return None
    if identity:
        LOG.info("Published paper result %s for %s (%s)", identity, job["run_id"], report["status"])
    return identity


def _version(row):
    return dict(id=row["id"], supersedes=row["supersedes"], processed_at=row["processed_at"].isoformat(),
        observed_at=row["observed_at"].isoformat() if row["observed_at"] else None,
        evidence_revision=row["evidence_revision"], grading_rule_version=row["grading_rule"], status=row["status"])


def read(db, run_id, result_id=None, *, status_only=False, include_history=True):
    """Read the publication and dirty state without doing any grading or acquisition."""
    from app.research import paper_results

    job = db.execute(f"""SELECT job.current_result_id,job.last_error,job.applied_rule,
        job.generation,job.processed_generation,{EXPECTED_RULE} AS expected_rule,
        EXISTS (SELECT 1 FROM public.paper_result_input input
            WHERE input.dispatched_at IS NULL AND {MATCH}) AS input_pending
        FROM public.research_workspace_run run LEFT JOIN public.paper_result_job job ON job.run_id=run.id
        WHERE run.id=%s AND (job.run_id IS NOT NULL OR public.paper_result_is_run(run.payload))""",
        (paper_results.NHL_VERSION, paper_results.VERSION, run_id)).fetchone()
    if job is None:
        return None
    identity = result_id or job["current_result_id"]
    current = None
    if identity:
        columns = VERSION_FIELDS if status_only else VERSION_FIELDS + ",r.payload"
        current = db.execute(f"""SELECT {columns} FROM public.paper_result_report r
            WHERE r.run_id=%s AND r.id=%s""", (run_id, identity)).fetchone()
        if current is None:
            raise KeyError(identity)
    pending = (job["applied_rule"] != job["expected_rule"] or job["input_pending"]
               or job["generation"] != job["processed_generation"])
    state = "failed" if job["last_error"] else "update_pending" if pending else current["status"]
    version = _version(current) if current else None
    versions = [] if status_only or not include_history else [_version(row) for row in db.execute(f"""
        SELECT {VERSION_FIELDS} FROM public.paper_result_report r
        WHERE r.run_id=%s ORDER BY r.processed_at DESC,r.id""", (run_id,))]
    return dict(state=state, pending=pending, error=job["last_error"],
        updated_at=version["processed_at"] if version else None, latest_result_id=job["current_result_id"],
        version=version, versions=versions, report=current.get("payload") if current else None)
