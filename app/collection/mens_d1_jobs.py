"""Server-owned, restart-safe men's D1 schedule and result jobs."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.diagnostics import failure
from app.research import records
from app.storage import mens_d1_coverage as coverage
from app.storage.store import ROOT, connect, encoded, stamp
from . import mens_d1_cbbd as cbbd
from . import mens_d1_source as source
from .bulk_checkpoint import owned_thread
from .current_storage_policy import SQL_BYTE_CAP, require_disk_space, sql_usage
from .odds_http import BudgetStop
from .service_secrets import read_file

SOURCE = coverage.SOURCE
CBBD = coverage.PUBLIC_SOURCE
TICK_SECONDS = 60
ATTEMPT_LEASE = timedelta(minutes=3)
ATTEMPT_LIMIT = 3
DETAIL_LIMIT = 4
RETRY_DELAY = timedelta(minutes=15)
PRESSURE_FLOOR = timedelta(seconds=90)
MAX_STORAGE_RESERVATION = 3 * (source.MAX_FIRECRAWL_RESPONSE_BYTES + coverage.MAX_PARSED_BYTES)
BLOCKED_REASON = 'sports_reference_private_hosted_use_and_firecrawl_account_unverified'


@dataclass(frozen=True)
class Authority:
    window_id: str
    starts_at: datetime
    ends_at: datetime
    available_credits: int
    daily_credits: int
    key: str

    def budget(self):
        return dict(window_starts_at=coverage.clock(self.starts_at), window_ends_at=coverage.clock(self.ends_at),
            window_credit_ceiling=self.available_credits, daily_credit_ceiling=self.daily_credits,
            per_request_credit_reservation=source.DOCUMENTED_BASIC_SCRAPE_CREDITS)


def authority(at):
    """Require reviewed source terms and a known provider account allowance."""
    try:
        raw = read_file('firecrawl-sports-reference-policy')
    except FileNotFoundError:
        raw = None
    except (OSError, ValueError, UnicodeError):
        return None, 'firecrawl_account_policy_unavailable'
    if raw is None:
        return None, BLOCKED_REASON
    try:
        policy = json.loads(raw)
        start, end = stamp(policy['window_starts_at']), stamp(policy['window_ends_at'])
        window, available, daily = policy['window_id'], policy['available_credits_at_start'], policy['daily_credits']
        if (policy['source'] != SOURCE or not isinstance(policy['private_hosted_use_reference'], str)
                or not policy['private_hosted_use_reference'].strip()
                or not isinstance(window, str) or not 0 < len(window) <= 128
                or type(available) is not int or type(daily) is not int or not 0 < daily <= available
                or not start <= at < end):
            raise ValueError('firecrawl_account_policy_invalid')
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return None, 'firecrawl_account_window_or_permission_unverified'
    try:
        key = read_file('firecrawl')
    except FileNotFoundError:
        key = None
    except (OSError, ValueError, UnicodeError):
        return None, 'firecrawl_credential_unavailable'
    key = (key or os.environ.get('FIRECRAWL_API_KEY') or '').strip()
    if not key or len(key) > 1024 or any(character.isspace() for character in key):
        return None, 'firecrawl_credential_unavailable'
    return Authority(window, start, end, available, daily, key), None


def _job(db, day, purpose, kind, due, expires, *, data=None, source_id=SOURCE):
    if expires <= due:
        return
    db.execute("""INSERT INTO public.mens_d1_job
        (source,game_date,purpose,kind,due_at,expires_at,next_attempt_at,input)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source,game_date,purpose) DO UPDATE SET
          due_at=EXCLUDED.due_at,expires_at=EXCLUDED.expires_at,next_attempt_at=EXCLUDED.next_attempt_at
        WHERE mens_d1_job.state='pending' AND mens_d1_job.attempts=0
          AND (mens_d1_job.due_at,mens_d1_job.expires_at) IS DISTINCT FROM (EXCLUDED.due_at,EXCLUDED.expires_at)""",
        (source_id, day, purpose, kind, due, expires, due, Jsonb(data or {})))


def _schedule_jobs(db, day, at, source_id):
    local = coverage.eastern_time
    tomorrow = day + timedelta(days=1)
    evening = local(day - timedelta(days=1), 22, 45)
    morning = local(day, 4)
    _job(db, day, 'schedule_preview', 'schedule', evening, morning, source_id=source_id)
    _job(db, day, 'schedule_morning', 'schedule', morning, local(day, 11), source_id=source_id)
    revisions = coverage.schedule_revisions(db, day, at=at, source=source_id)
    first = min((stamp(game['scheduled_start']) for game in revisions[0]['facts']
                 if game.get('scheduled_start') and game.get('membership_status') != 'excluded'
                 and game['status'] not in ('postponed', 'cancelled')), default=None) if revisions else None
    if first is None:
        pre_due, pre_expiry = local(day, 10), local(day, 12)
    else:
        pre_due, pre_expiry = max(first - timedelta(minutes=45), evening), first
    _job(db, day, 'schedule_before_first_tip', 'schedule', pre_due, pre_expiry, source_id=source_id)
    _job(db, day, 'schedule_afternoon', 'schedule', local(day, 13, 30), local(day, 17, 30), source_id=source_id)
    _job(db, day, 'schedule_evening', 'schedule', local(day, 18, 30), local(tomorrow), source_id=source_id)


def _result_jobs(db, day, source_id):
    local = coverage.eastern_time
    next_day, following = day + timedelta(days=1), day + timedelta(days=2)
    _job(db, day, 'results_morning', 'results', local(next_day, 5, 30), local(next_day, 12, 30), source_id=source_id)
    _job(db, day, 'results_corrections', 'results', local(next_day, 12, 30), local(next_day, 21), source_id=source_id)
    _job(db, day, 'results_unresolved_followup', 'results', local(following, 5, 30), local(following, 12, 30),
         source_id=source_id)


def _unresolved_result(db, day, at, source_id):
    slates = coverage.schedule_revisions(db, day, at=at, source=source_id)
    rows = coverage._result_rows(db, day, at, source=source_id)
    if not slates:
        return not rows or any(row['status'] not in ('final', 'cancelled', 'postponed') for _, row in rows)
    decided = {coverage._pair(row['teams'], 'source_team_id') for _, row in rows
               if row['status'] in ('final', 'cancelled', 'postponed') and not row.get('detail_reason')}
    return any(coverage._pair(row['teams'], 'source_team_id') not in decided
               for row in slates[0]['facts'] if row['membership_status'] == 'eligible')


def _source_state(db, source_id, at, state, blocked_reason, budget=None, *, initialize=False):
    args = (source_id, state, blocked_reason, at, Jsonb(budget or {}))
    db.execute("""INSERT INTO public.mens_d1_source_state(source,state,reason,checked_at,budget)
        VALUES (%s,%s,%s,%s,%s) ON CONFLICT (source) DO UPDATE SET state=EXCLUDED.state,
        reason=EXCLUDED.reason,checked_at=EXCLUDED.checked_at,budget=EXCLUDED.budget
        WHERE NOT %s OR mens_d1_source_state.reason IN (%s,%s)""",
        (*args, initialize, cbbd.KEY_UNAVAILABLE, 'collection_stopped_or_paused'))


def plan(db, at, approved, blocked_reason, *, source_id=SOURCE, configured=False):
    local_day = at.astimezone(coverage.EASTERN).date()
    state = ('paused' if (configured or approved) and blocked_reason else 'active' if approved else
             'configured' if configured else 'disabled')
    _source_state(db, source_id, at, state, blocked_reason, approved.budget() if approved else None,
                  initialize=state == 'configured')
    for day in (local_day, local_day + timedelta(days=1)):
        _schedule_jobs(db, day, at, source_id)
    for offset in (-2, -1, 0, 1):
        _result_jobs(db, local_day + timedelta(days=offset), source_id)
    db.execute("""UPDATE public.mens_d1_attempt SET settled_at=%s,reserved_storage_bytes=0,disposition='unknown',
        error='attempt_interrupted_credit_charge_unknown' WHERE source=%s
        AND settled_at IS NULL AND admitted_at<%s""", (at, source_id, at - ATTEMPT_LEASE))
    db.execute("""UPDATE public.mens_d1_job SET state=CASE
            WHEN attempts<%s AND expires_at>%s THEN 'pending' ELSE 'failed' END,
        next_attempt_at=%s,last_reason='attempt_interrupted_credit_charge_unknown'
        WHERE source=%s AND state='running' AND last_attempt_at<%s""",
        (ATTEMPT_LIMIT, at + RETRY_DELAY, at + RETRY_DELAY, source_id, at - ATTEMPT_LEASE))
    db.execute("""UPDATE public.mens_d1_job SET state='expired',
        last_reason=COALESCE(last_reason,'job_window_elapsed')
        WHERE source=%s AND state='pending' AND expires_at<=%s""", (source_id, at))


def _late_capture_due(db, at):
    return db.execute("""SELECT EXISTS (SELECT 1 FROM public.ev_experiment_task
        WHERE checkpoint='late' AND state IN ('pending','claimed') AND target_at<=%s
        AND deadline_at>=%s) AS busy""", (at + PRESSURE_FLOOR, at)).fetchone()['busy']


def _credit_spend(db, at, approved):
    start = coverage.eastern_time(at.astimezone(coverage.EASTERN).date())
    return db.execute("""SELECT
        COALESCE(sum(COALESCE(charged_credits,reserved_credits)) FILTER(
          WHERE admitted_at>=%s),0) AS day,
        COALESCE(sum(COALESCE(charged_credits,reserved_credits)) FILTER(
          WHERE account_window=%s OR admitted_at>=%s OR charged_credits IS NULL),0) AS window
        FROM public.mens_d1_attempt WHERE source=%s""",
        (start, approved.window_id, approved.starts_at, SOURCE)).fetchone()


def _admit(db, at, approved, source_id):
    if _late_capture_due(db, at):
        return 'protected_tminus10_capture_due'
    if source_id == CBBD:
        held = db.execute("""SELECT COALESCE(sum(reserved_credits),0) AS calls FROM public.mens_d1_attempt
            WHERE source=%s AND account_window=%s AND charged_credits IS NULL""",
            (CBBD, approved.window_id)).fetchone()['calls']
        if approved.remaining <= held:
            return cbbd.ALLOWANCE_EXHAUSTED
    else:
        cost = source.DOCUMENTED_BASIC_SCRAPE_CREDITS
        spending = _credit_spend(db, at, approved)
        if (spending['day'] + cost > approved.daily_credits
                or spending['window'] + cost > approved.available_credits):
            return 'firecrawl_credit_allowance_exhausted_or_held'
    usage = records.retention_usage(db)
    if usage['total'] + usage['reserved'] + MAX_STORAGE_RESERVATION > records.TOTAL_BYTE_CAP:
        return 'research_retention_capacity'
    if sql_usage(db) + MAX_STORAGE_RESERVATION + 8 * 1024 * 1024 > SQL_BYTE_CAP:
        return 'research_sql_runway'
    try:
        require_disk_space(ROOT / '.local/postgres', append_bytes=MAX_STORAGE_RESERVATION)
    except BudgetStop:
        return 'current_observation_disk_free_floor'
    return None


def _due_job(db, at, source_id):
    return db.execute("""SELECT * FROM public.mens_d1_job WHERE source=%s AND state='pending'
        AND next_attempt_at<=%s AND expires_at>%s AND NOT EXISTS
          (SELECT 1 FROM public.mens_d1_job WHERE source=%s AND state='running')
        ORDER BY due_at DESC,purpose LIMIT 1 FOR UPDATE""", (source_id, at, at, source_id)).fetchone()


def _defer(db, job, at, reason, *, delay=RETRY_DELAY):
    db.execute("""UPDATE public.mens_d1_job SET last_reason=%s,next_attempt_at=%s
        WHERE (source,game_date,purpose)=(%s,%s,%s)""",
        (reason, at + delay, job['source'], job['game_date'], job['purpose']))


def claim(db, at, approved, *, source_id=SOURCE):
    with db.transaction():
        records._writer_lock(db)
        job = _due_job(db, at, source_id)
        if not job:
            return None
        key = (source_id, job['game_date'], job['purpose'])
        if job['purpose'] == 'results_unresolved_followup' and not _unresolved_result(db, job['game_date'], at, source_id):
            db.execute("""UPDATE public.mens_d1_job SET state='coalesced',last_reason='recent_results_resolved'
                WHERE (source,game_date,purpose)=(%s,%s,%s)""", key)
            return None
        reason = _admit(db, at, approved, source_id)
        if reason:
            delay = RETRY_DELAY if reason == cbbd.ALLOWANCE_EXHAUSTED else timedelta(minutes=1)
            _defer(db, job, at, reason, delay=delay)
            return None
        if job['kind'] == 'detail':
            url, reason = job['input']['url'], job['input']['reason']
        else:
            url = (cbbd.source_url(job['game_date']) if source_id == CBBD else
                   source.source_url(job['game_date'], job['kind']))
            reason = job['purpose']
            db.execute("""UPDATE public.mens_d1_job SET state='coalesced',last_reason='superseded_overdue_job'
                WHERE source=%s AND game_date=%s AND kind=%s AND purpose<>%s
                AND state='pending' AND due_at<%s""",
                (source_id, job['game_date'], job['kind'], job['purpose'], job['due_at']))
        attempt = dict(id=uuid4().hex, admitted_at=at, request_url=url, request_reason=reason)
        db.execute("""INSERT INTO public.mens_d1_attempt
            (id,source,game_date,purpose,request_url,request_reason,account_window,admitted_at,
             reserved_credits,reserved_storage_bytes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (attempt['id'], *key, url, reason, approved.window_id, at,
             1 if source_id == CBBD else source.DOCUMENTED_BASIC_SCRAPE_CREDITS, MAX_STORAGE_RESERVATION))
        db.execute("""UPDATE public.mens_d1_job SET state='running',attempts=attempts+1,last_attempt_at=%s,
            last_reason=NULL WHERE (source,game_date,purpose)=(%s,%s,%s)""", (at, *key))
        return dict(job, attempts=job['attempts'] + 1), attempt


def _details(db, day, rows, at):
    expires = coverage.eastern_time(day + timedelta(days=2), 12, 30)
    if expires <= at + timedelta(minutes=1):
        return
    count = db.execute("""SELECT count(*) n FROM public.mens_d1_job
        WHERE source=%s AND game_date=%s AND kind='detail'""", (SOURCE, day)).fetchone()['n']
    for game in rows:
        if count >= DETAIL_LIMIT:
            break
        if game['membership_status'] != 'eligible' or not game.get('detail_reason') or not game.get('detail_url'):
            continue
        purpose = 'result_detail_' + coverage.hashed(game['source_game_id'])[:24]
        if db.execute("""SELECT 1 FROM public.mens_d1_job
            WHERE (source,game_date,purpose)=(%s,%s,%s)""", (SOURCE, day, purpose)).fetchone():
            continue
        _job(db, day, purpose, 'detail', at + timedelta(minutes=1), expires,
             data=dict(url=game['detail_url'], reason=game['detail_reason'], game=game))
        count += 1


def finish(db, job, attempt, at, *, receipt=None, rows=None, membership_version=None, error=None,
           no_dispatch=False):
    source_id = job['source']
    with db.transaction():
        records._writer_lock(db)
        current = db.execute("""SELECT settled_at FROM public.mens_d1_attempt WHERE id=%s FOR UPDATE""",
                             (attempt['id'],)).fetchone()
        if not current or current['settled_at']:
            return
        charge = 0 if no_dispatch else receipt.credits_used if receipt else None
        if receipt:
            error = error or receipt.error
            if not error and (rows is None or len(rows) > coverage.MAX_ROWS
                              or len(encoded(rows)) > coverage.MAX_PARSED_BYTES):
                error = 'parsed_source_page_exceeds_retention_reservation'
            parser = cbbd.PARSER_VERSION if source_id == CBBD else source.PARSER_VERSION
            coverage.retain(db, job, attempt, receipt, rows=rows, parser_version=parser,
                            membership_version=membership_version, error=error)
        succeeded = not error and receipt is not None and not receipt.error
        delay = timedelta(minutes=1) if no_dispatch else RETRY_DELAY
        result = 'succeeded' if succeeded else (
            'pending' if (no_dispatch or job['attempts'] < ATTEMPT_LIMIT) and at + delay < job['expires_at'] else 'failed')
        db.execute("""UPDATE public.mens_d1_attempt SET settled_at=%s,reserved_storage_bytes=0,
            disposition=%s,charged_credits=%s,error=%s WHERE id=%s""",
            (at, 'not_dispatched' if no_dispatch else 'dispatched', charge, error, attempt['id']))
        db.execute("""UPDATE public.mens_d1_job SET state=%s,next_attempt_at=%s,attempts=attempts-%s,
            last_success_at=CASE WHEN %s THEN %s ELSE last_success_at END,last_reason=%s
            WHERE (source,game_date,purpose)=(%s,%s,%s)""",
            (result, at + delay if result == 'pending' else at, int(no_dispatch), succeeded, at, error,
             source_id, job['game_date'], job['purpose']))
        if succeeded and job['kind'] == 'results' and source_id == SOURCE:
            _details(db, job['game_date'], rows, at)


class DailyCoverageJobs:
    """Run one bounded source operation off the odds event loop."""
    def __init__(self, runtime, *, connector=connect, authority_loader=authority,
                 fetch=None, now=coverage.utc, cbbd_credential=cbbd.credential,
                 cbbd_account=cbbd.verify_account, cbbd_fetch=None):
        self.runtime = runtime
        self.connector = connector
        self.authority_loader = authority_loader
        self.fetch = fetch or source.fetch_firecrawl
        self.cbbd_credential = cbbd_credential
        self.cbbd_account = cbbd_account
        self.cbbd_fetch = cbbd_fetch or cbbd.fetch_games
        self.now = now
        self.task = None
        self.closed = asyncio.Event()
        self.idle = asyncio.Event()
        self.idle.set()

    def start(self):
        self.task = asyncio.create_task(self.run(), name='predict-mens-d1-daily-source')

    def stopped(self, source_id=SOURCE):
        runtime = self.runtime
        return (self.closed.is_set() or runtime.stopping.is_set() or runtime.global_stopped
                or source_id in runtime.paused_sources or not runtime.service.config.get('enabled', False)
                or not runtime.service.dispatch
                or runtime.storage_interval_requested)

    def pressure(self):
        worker = self.runtime.service.workers.get('sportsgameodds')
        return bool(worker and (worker.experiment_late_waiting or worker.experiment_reserved_requests)
                    or self.runtime.acquisition_pressure(critical=True))

    def _prepare(self, at, approved, reason, allowed):
        with self.connector() as db:
            with db.transaction():
                records._writer_lock(db)
                plan(db, at, approved, reason)
            if allowed and not self.stopped():
                return claim(db, at, approved)
        return None

    def _prepare_cbbd(self, at, key):
        reason = (cbbd.KEY_UNAVAILABLE if not key else 'collection_stopped_or_paused' if self.stopped(CBBD) else None)
        with self.connector() as db:
            with db.transaction():
                records._writer_lock(db)
                plan(db, at, None, reason, source_id=CBBD, configured=bool(key))
                if reason or self.pressure() or _late_capture_due(db, at) or not _due_job(db, at, CBBD):
                    return None
                status = coverage._source_state(db, CBBD)
                if (status['reason'] in (cbbd.ACCESS_DENIED, cbbd.RATE_LIMITED, cbbd.ALLOWANCE_EXHAUSTED)
                        and at < status['checked_at'] + RETRY_DELAY):
                    return None
        if self.stopped(CBBD) or self.pressure():
            return None
        approved, reason = self.cbbd_account(key, now=self.now)
        checked_at = self.now()
        with self.connector() as db:
            with db.transaction():
                records._writer_lock(db)
                reason = 'collection_stopped_or_paused' if self.stopped(CBBD) else reason
                _source_state(db, CBBD, checked_at, 'paused' if not approved or reason else 'active',
                              reason, approved.budget() if approved else None)
                if reason and (job := _due_job(db, checked_at, CBBD)):
                    _defer(db, job, checked_at, reason)
            if approved and not reason and checked_at < approved.ends_at and not self.pressure():
                if work := claim(db, checked_at, approved, source_id=CBBD):
                    return *work, approved
        return None

    def _collect(self, job, attempt, approved):
        at = self.now()
        is_cbbd = job['source'] == CBBD
        reason = ('collection_stopped_before_dispatch' if self.stopped(job['source']) else
                  ('cbbd_api_account_window_elapsed' if is_cbbd else 'firecrawl_account_window_elapsed')
                  if at >= approved.ends_at else
                  'protected_tminus10_capture_due' if self.pressure() else None)
        if reason:
            with self.connector() as db:
                finish(db, job, attempt, at, error=reason, no_dispatch=True)
            return
        receipt, rows, version, error = None, None, None, None
        try:
            receipt = (self.cbbd_fetch(attempt['request_url'], api_key=approved.key, now=self.now) if is_cbbd else
                       self.fetch(attempt['request_url'], api_key=approved.key))
            error = receipt.error
            if not error:
                membership = source.load_membership(job['game_date'])
                version = membership.version
                if is_cbbd:
                    rows = cbbd.parse_games(receipt, day=job['game_date'], kind=job['kind'])
                elif job['kind'] == 'detail':
                    rows = [source.parse_detail(receipt, day=job['game_date'], game=job['input']['game'],
                                                membership=membership)]
                else:
                    rows = source.parse_page(receipt, day=job['game_date'], kind=job['kind'], membership=membership)
        except source.SourcePageError as exc:
            error = str(exc)[:160]
        except Exception as exc:
            error = 'cbbd_api_request_or_parser_failed' if is_cbbd else 'firecrawl_source_request_or_parser_failed'
            failure(__name__, error, exc)
        with self.connector() as db:
            at = self.now()
            with db.transaction():
                finish(db, job, attempt, at, receipt=receipt, rows=rows, membership_version=version, error=error)
                if is_cbbd and error in (cbbd.ACCESS_DENIED, cbbd.RATE_LIMITED):
                    _source_state(db, CBBD, at, 'paused', error, approved.budget())

    def _refresh_bindings(self, at, approved, *, source_id=SOURCE):
        today = at.astimezone(coverage.EASTERN).date()
        with self.connector() as db:
            if not approved and not db.execute("""SELECT EXISTS (
                SELECT 1 FROM public.mens_d1_revision WHERE source=%s AND kind='schedule'
                  AND game_date BETWEEN %s AND %s) present""",
                (coverage.PUBLIC_SOURCE, today - timedelta(days=1), today + timedelta(days=1))).fetchone()['present']:
                return
            for day in (today - timedelta(days=1), today, today + timedelta(days=1)):
                if self.stopped(source_id):
                    break
                with db.transaction():
                    records._writer_lock(db)
                    usage = records.retention_usage(db)
                    if (usage['total'] + usage['reserved'] + coverage.MAX_PARSED_BYTES > records.TOTAL_BYTE_CAP
                            or _late_capture_due(db, at)):
                        break
                    coverage.retain_bindings(db, day, at=at)

    async def tick(self):
        at = self.now()
        approved, reason = await owned_thread(self.authority_loader, at)
        key = await owned_thread(self.cbbd_credential)
        if approved and self.stopped():
            reason = 'collection_stopped_or_paused'
        self.idle.clear()
        try:
            permitted = bool(approved and not reason and not self.pressure())
            work = await owned_thread(self._prepare, at, approved, reason, permitted)
            if work:
                await owned_thread(self._collect, *work, approved)
            api_work = await owned_thread(self._prepare_cbbd, self.now(), key)
            if api_work:
                await owned_thread(self._collect, *api_work)
            binding_source = CBBD if key else SOURCE
            if not self.stopped(binding_source) and not self.pressure():
                await owned_thread(self._refresh_bindings, self.now(), approved, source_id=binding_source)
        finally:
            self.idle.set()

    async def run(self):
        while not self.closed.is_set():
            try:
                await self.tick()
            except Exception as exc:
                failure(__name__, 'mens_d1_daily_job_failed', exc)
            try:
                await asyncio.wait_for(self.closed.wait(), TICK_SECONDS)
            except TimeoutError:
                pass

    async def wait_idle(self):
        await self.idle.wait()
        return True

    async def close(self):
        self.closed.set()
        if self.task:
            await self.task
