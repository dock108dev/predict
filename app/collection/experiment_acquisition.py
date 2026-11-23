"""Collector-owned early/T-10 experiment acquisition and bounded result follow-up.

The browser never calls this owner. Checkpoints share the running SGO worker's
transport, account window, source controls and serialized request slot. Nothing
here creates an account partition, retries an uncertain request or releases a
financial hold.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import inspect

from app.storage.store import ROOT, connect, hashed, stamp
from app.comparison.reference_scope import REQUEST_BOOKS
from .bulk_checkpoint import owned_thread
from .current_policy import aggregate_provider, aggregate_scope
from .sportsgameodds_transport import ODD_IDS

VERSION = 'first-observed-24h-tminus10-acquisition-1'
# Exact declared response scope, including the existing optional reference book.
BOOKS = REQUEST_BOOKS
LEGACY_BOOKS = ('kalshi', 'polymarket', 'novig', 'prophetexchange',
         'fanduel', 'draftkings', 'betmgm', 'caesars', 'betonline')
OUTCOME_OFFSETS = (3 * 3600, 4 * 3600, 6 * 3600, 12 * 3600, 24 * 3600)
DISCOVERY_SECONDS = 5


class CheckpointUnavailable(RuntimeError):
    def __init__(self, reason, *, details=None, dispatched=False):
        super().__init__(reason)
        self.details = details or {}
        self.dispatched = dispatched


def _start_pull(task, params, at):
    from app.storage.acquisition_snapshot import start
    with connect() as db:
        return start(db, params, at=at, event=task['event'])


def _end_pull(pull_id, state, details):
    from app.storage.acquisition_snapshot import finish
    with connect() as db:
        finish(db, pull_id, state, details=details)


def request_scope(task):
    """One event object; all six supported outcomes and every declared book."""
    event = task['event']
    identity = event.get('source_event_id') or event.get('native_event_id')
    if not isinstance(identity, str) or not identity:
        raise ValueError('experiment_source_event_required')
    declared = task.get('requested_scope')
    books = declared['bookmakers'] if declared is not None else LEGACY_BOOKS
    odds = declared['odd_ids'] if declared is not None else ODD_IDS
    params = dict(eventIDs=identity, oddID=','.join(sorted(odds)), limit=1,
                  includeOpposingOdds=True, bookmakerID=','.join(books))
    if task['checkpoint'] in ('early', 'late'):
        params['includeAltLines'] = True
    elif task['checkpoint'] != 'outcome':
        raise ValueError('experiment_checkpoint_kind')
    return params


def authorized(worker, task, *, at):
    """Recheck controls, declared scope and actual timing before dispatch."""
    controls = worker.controls()
    config = worker.service.config
    if (controls['stopped'] or controls['source_paused'] or not config.get('enabled')
            or not config.get('aggregate_enabled') or aggregate_provider(config) != 'sportsgameodds'
            or task['event']['league'] not in aggregate_scope(config)):
        return False
    start = stamp(task['event']['starts_at'])
    target, deadline = stamp(task['target_at']), stamp(task['deadline_at'])
    if not target <= at <= deadline:
        return False
    if task['checkpoint'] == 'outcome':
        return at >= start
    status = task['event'].get('status') or {}
    if isinstance(status, dict) and any(status.get(key) is True for key in
                                       ('started', 'live', 'ended', 'completed', 'cancelled')):
        return False
    return timedelta(0) < start - at <= timedelta(hours=24)


def event_metadata(event, receipt_sha256):
    """Use the existing canonical roles/schedule owner; keep source clocks."""
    from app.comparison.event_links import provider_key
    from app.normalization.college_registry import sgo_registry
    from .sportsgameodds_current_rows import event_record

    canonical = event_record(event, receipt_sha256, event['received_at'], sgo_registry())
    return dict(provider='sportsgameodds', source_event_id=event['event_id'],
                event_id=hashed(provider_key('sportsgameodds', canonical)),
                title=canonical['title'], league=event['league'],
                starts_at=canonical['scheduled_start'], home=canonical['home'], away=canonical['away'],
                status=dict(event['status']), phase=event['phase'],
                source_received_at=event['received_at'],
                source_metadata_received_at=event['received_at'],
                previous_starts_at=event.get('previous_starts_at', []))


def discover_events(db, *, at, leagues, tracked_source_ids=()):
    """Observe retained event metadata now; never backdate an early checkpoint."""
    # Existing games must receive cancellations and reschedules even outside
    # the new-game 24-hour window. The store applies that window on creation.
    rows = list(db.execute('''SELECT event_id,facts-'members' AS facts
        FROM public.current_sgo_event_frame
        WHERE facts#>>'{event_context,league}'=ANY(%s)
          AND (((facts->>'starts_at')::timestamptz>%s
              AND (facts->>'starts_at')::timestamptz<=%s) OR event_id=ANY(%s))
        ORDER BY (facts->>'starts_at')::timestamptz,event_id LIMIT 2049''',
        (list(leagues), at, at+timedelta(hours=24), list(tracked_source_ids))))
    if len(rows) > 2048:
        raise ValueError('experiment_discovery_capacity; no_complete_scope_claimed')
    result = []
    for row in rows:
        facts = row['facts']
        context = facts.get('event_context') or {}
        if not all(context.get(key) is not None for key in ('league', 'phase', 'teams', 'status')):
            continue
        event = dict(event_id=row['event_id'], starts_at=facts['starts_at'],
                     received_at=facts['received_at'], aliases=[], **context)
        result.append(event_metadata(event, facts['receipt_sha256']))
    return result


@asynccontextmanager
async def _request_slot(worker, already_locked):
    if already_locked:
        yield
    else:
        async with worker.request_lock:
            yield


async def acquire(worker, task, *, eligible=None, request_locked=False):
    """Fetch exactly once after admission; preserve real dispatch/receipt clocks.

    Eligibility is checked by GuardedPageCollector again after account usage and
    immediately before network dispatch. A late response remains a paid receipt,
    but cannot become a valid checkpoint.
    """
    from .activity_collector import budget_admit
    from .current_storage_policy import SQL_BYTE_CAP, sql_usage, require_disk_space
    from .original_receipts import capture
    from .sportsgameodds_collector import GuardedPageCollector
    from .sportsgameodds_schedule import response_object_charge

    if worker.collector is None or worker.ledger is None or worker.window_id is None:
        raise CheckpointUnavailable('experiment_source_not_initialized')
    params = request_scope(task)
    pull_id = None
    receipt = {}
    dispatched_at = None
    transport = worker.transport

    class TimedTransport:
        async def fetch(self, request, key):
            nonlocal dispatched_at
            dispatched_at = worker.now()
            return await transport.fetch(request, key)

    def storage():
        with connect() as db:
            if sql_usage(db) >= SQL_BYTE_CAP:
                raise CheckpointUnavailable('experiment_sql_storage_guard')
        require_disk_space(ROOT / '.local/postgres')

    async def check(_params, *, own_reserved=False):
        moment = worker.now()
        if not authorized(worker, task, at=moment):
            return False
        if eligible is not None:
            value = eligible(task, moment)
            if not (await value if inspect.isawaitable(value) else value):
                return False
        await owned_thread(storage)
        reserved = (max(0, getattr(worker, 'experiment_reserved_objects', 0))
                    if task['checkpoint'] != 'late' else 0)
        # Rolling exposure already includes this request after the collector
        # reserves it. Rechecking must not count that same object twice.
        budget_admit(worker.ledger, worker.window_id,
                     (0 if own_reserved else 1) + reserved, worker.now())
        reserved_requests = (max(0, getattr(worker, 'experiment_reserved_requests', 0))
                             if task['checkpoint'] != 'late' else 0)
        if reserved_requests:
            rate = worker.ledger.request_capacity(worker.window_id, now=worker.now())
            if rate['available'] < reserved_requests or (not own_reserved and rate['available'] == reserved_requests):
                raise CheckpointUnavailable('experiment_checkpoint_rate_headroom')
        return authorized(worker, task, at=worker.now())

    async def retain(request, response):
        receipt.update(await owned_thread(capture, request, response,
                                          root=worker.original_response_root))
        worker.metrics['experiment_original_receipt'] = receipt

    async def reserved_check(params):
        return await check(params, own_reserved=True)

    collector = GuardedPageCollector(worker.ledger, worker.window_id, TimedTransport(),
        controls=worker.controls, account_usage=worker.collector.account_usage,
        eligible=check, eligible_after_reservation=reserved_check, receipt_retainer=retain)
    late = task['checkpoint'] == 'late'
    if late and not request_locked:
        worker.experiment_late_waiting = True
    try:
        async with _request_slot(worker, request_locked):
            if not await check(params):
                raise CheckpointUnavailable('experiment_authority_or_window_closed')
            if task['checkpoint'] != 'outcome':
                pull_id = await owned_thread(_start_pull, task, params, worker.now())
                task['_pull_id'] = pull_id
            while True:
                try:
                    page = await collector.fetch(params, worker.key, pull_id=pull_id)
                    break
                except RuntimeError as exc:
                    # A rejected rate reservation is provably pre-dispatch.
                    # Wait for the existing minute window; never retry a paid
                    # request or extend a checkpoint's declared deadline.
                    if str(exc) != 'request rate limit' or dispatched_at is not None:
                        raise
                    remaining = (stamp(task['deadline_at'])-worker.now()).total_seconds()
                    if remaining <= 0:
                        raise CheckpointUnavailable('experiment_rate_window_missed') from exc
                    await asyncio.sleep(min(1, remaining))
    except BaseException as exc:
        if pull_id:
            await owned_thread(_end_pull, pull_id,
                'cancelled' if isinstance(exc, asyncio.CancelledError) else
                'failed' if dispatched_at is not None else 'refused',
                dict(reason=str(exc)[:160] or type(exc).__name__, original_response=receipt))
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, CheckpointUnavailable):
            exc.dispatched = dispatched_at is not None
            if not exc.details:
                exc.details = dict(request_scope=params, original_response=receipt,
                    dispatch_at=dispatched_at.isoformat() if dispatched_at else None,
                    failed_at=worker.now().isoformat())
            raise
        raise CheckpointUnavailable(str(exc)[:160] or type(exc).__name__,
            dispatched=dispatched_at is not None, details=dict(request_scope=params,
                dispatch_at=dispatched_at.isoformat() if dispatched_at else None,
                original_response=receipt, failed_at=worker.now().isoformat())) from exc
    finally:
        if late and not request_locked:
            worker.experiment_late_waiting = False
    try:
        known_at = worker.now()
        worker.metrics['last_valid_received_at'] = page.received_at
        details = dict(version=VERSION, request_scope=params, pull_id=page.pull_id, attempt_id=page.attempt_id,
                       dispatch_at=dispatched_at.isoformat() if dispatched_at else None,
                       known_at=known_at.isoformat(), receipt_sha256=page.receipt_sha256,
                       original_response=receipt, paid_event_requests=1,
                       charged_objects=response_object_charge(len(page.events)),
                       response_event_count=len(page.events), next_cursor_present=page.next_cursor is not None)
        if len(page.events) != 1:
            raise CheckpointUnavailable('experiment_event_not_returned' if not page.events else
                                        'experiment_response_event_scope', details=details, dispatched=True)
        event = page.events[0]
        details['received_at'] = event['received_at']
        if event['event_id'] != params['eventIDs'] or event['league'] != task['event']['league']:
            raise CheckpointUnavailable('experiment_response_event_scope', details=details, dispatched=True)
        received_at = stamp(event['received_at'])
        if received_at > known_at:
            raise CheckpointUnavailable('experiment_future_receipt', details=details, dispatched=True)
        if known_at > stamp(task['deadline_at']):
            raise CheckpointUnavailable('experiment_response_after_deadline', details=details, dispatched=True)
        worker.metrics['experiment_acquisition'] = details
        return dict(page=page, request_scope=params, dispatch_at=dispatched_at,
                    received_at=received_at, known_at=known_at, acquisition=details)
    except BaseException as exc:
        if pull_id:
            await owned_thread(_end_pull, pull_id,
                'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed',
                dict(reason=str(exc)[:160] or type(exc).__name__, original_response=receipt))
        raise


def utc():
    return datetime.now(timezone.utc)


class ExperimentAcquisition:
    """One browser-independent task, with durable claims owned by the store."""
    def __init__(self, service, *, connector=connect):
        self.service = service
        self.connector = connector
        self.closed = False
        self.task = None
        self.last_discovery = None
        self.progress = dict(state='starting', version=VERSION)

    async def start(self):
        self.task = asyncio.create_task(self.run(), name='predict-early-tminus10-experiment')

    def _prepare(self, at):
        from app.research import experiment
        with self.connector() as db:
            policy = experiment.activate(db, at=at)
            events = discover_events(db, at=at, leagues=aggregate_scope(self.service.config),
                                     tracked_source_ids=experiment.tracked_source_ids(db))
            for event in events:
                event['discovery_kind'] = ('policy_activation_existing_game'
                    if stamp(event['source_metadata_received_at']) < stamp(policy['activated_at'])
                    else 'new_received_event')
            discovered = experiment.discover(db, events, at=at)
            objects = experiment.reserved_late_objects(db, at=at, through=at+timedelta(minutes=15))
            requests = experiment.reserved_late_objects(db, at=at, through=at+timedelta(minutes=1))
            return dict(discovered=discovered, reserved_objects=objects, reserved_requests=requests,
                        status=experiment.status(db))

    def _claim(self, at):
        from app.research import experiment
        with self.connector() as db:
            tasks = experiment.due(db, at=at, limit=1)
            return tasks[0] if tasks else None

    async def _authorized(self, task, at):
        from app.research import experiment
        def read():
            with self.connector() as db:
                return experiment.task_authorized(db, task['token'], at=at)
        return await owned_thread(read)

    def _fail(self, task, reason, *, at, dispatched=False, details=None):
        from app.research import experiment
        with self.connector() as db:
            return experiment.fail_checkpoint(db, task['game_id'], task['checkpoint'], reason,
                token=task['token'], at=at, dispatched=dispatched, details=details)

    def _finish(self, worker, task, acquired):
        from app.research import experiment
        from app.research.ev_movement import build_snapshot
        from .background_work import BACKGROUND, SOURCE_RUNWAY
        from .sgo_game_results import observations

        page = acquired['page']
        with BACKGROUND.claim('observations', SOURCE_RUNWAY, source=True) as lease:
            if not lease:
                raise CheckpointUnavailable(lease.reason, details=acquired['acquisition'], dispatched=True)
            with self.connector() as db, db.transaction():
                actual_event = event_metadata(page.events[0], page.receipt_sha256)
                experiment.discover(db, [actual_event], at=acquired['known_at'])
                source = page.events[0]
                if task['checkpoint'] != 'outcome' and (
                        source['phase'] != 'pregame' or any(source['status'].get(key) is True for key in
                            ('started', 'live', 'ended', 'completed', 'finalized', 'cancelled'))):
                    raise CheckpointUnavailable('experiment_response_not_pregame', dispatched=True,
                        details=dict(acquired['acquisition'], received_phase=source['phase'],
                                     received_status=source['status']))
                if task['checkpoint'] == 'outcome':
                    outcomes = observations(page, known_at=acquired['known_at'].isoformat())
                    observation = outcomes[0] if outcomes else dict(
                        version='sgo-final-team-points-1', source='sportsgameodds', kind='sporting_result',
                        event_id=actual_event['source_event_id'], league=actual_event['league'],
                        starts_at=actual_event['starts_at'], home=actual_event['home'], away=actual_event['away'],
                        received_at=acquired['received_at'].isoformat(), knowledge_at=acquired['known_at'].isoformat(),
                        known_at=acquired['known_at'].isoformat(), observed_at=acquired['received_at'].isoformat(),
                        published_at=None, source_at=None, home_score=None, away_score=None,
                        final=False, result='unresolved', state='unavailable',
                        reason='sporting_result_fields_unavailable', receipt_sha256=page.receipt_sha256,
                        venue_settlement=None, actual_trade_result=None)
                    return experiment.capture_outcome(db, task['game_id'], observation,
                        token=task['token'], requested_at=acquired['dispatch_at'],
                        received_at=acquired['received_at'], known_at=worker.now(),
                        scope=acquired['request_scope'])
                snapshot = build_snapshot(db, page, request_scope=acquired['request_scope'],
                    dispatch_at=acquired['dispatch_at'].isoformat(), known_at=acquired['known_at'].isoformat())
                finished = worker.now()
                snapshot['times'].update(inputs_cutoff=acquired['known_at'].isoformat(),
                    calculation_finished_at=finished.isoformat(), known_at=finished.isoformat(), captured_at=finished.isoformat())
                snapshot['acquisition'] = acquired['acquisition']
                saved = experiment.capture(db, task['game_id'], task['checkpoint'], snapshot,
                    token=task['token'], requested_at=acquired['dispatch_at'],
                    received_at=acquired['received_at'], known_at=finished, scope=acquired['request_scope'])
                from app.storage.acquisition_snapshot import publish, finish
                if saved['state'] == 'captured':
                    publish(db, page, snapshot, details=acquired['acquisition'])
                else:
                    finish(db, page.pull_id, 'failed', details=saved)
                return saved

    async def tick(self):
        worker = self.service.workers.get('sportsgameodds')
        if worker is None or worker.collector is None or worker.ledger is None or worker.window_id is None:
            self.progress = dict(state='waiting_for_source', version=VERSION)
            return
        controls = worker.controls()
        if controls['stopped'] or controls['source_paused']:
            self.progress = dict(state='source_stopped_or_paused', version=VERSION)
            return
        at = worker.now()
        if self.last_discovery is None or (at-self.last_discovery).total_seconds() >= DISCOVERY_SECONDS:
            self.last_discovery = at
            try:
                prepared = await owned_thread(self._prepare, at)
                worker.experiment_reserved_objects = prepared['reserved_objects']
                worker.experiment_reserved_requests = prepared['reserved_requests']
                self.progress = dict(state='ready', version=VERSION, **prepared)
            except Exception as exc:
                # Discovery errors must not starve already declared T-10 work.
                # Its own fresh authority, timing and capacity checks still run.
                self.progress = dict(state='degraded', version=VERSION,
                    discovery_reason=str(exc)[:160] or type(exc).__name__)
        task = await owned_thread(self._claim, worker.now())
        if task is None:
            return
        self.progress = dict(self.progress, state='capturing', task={key:task.get(key) for key in
            ('game_id', 'checkpoint', 'target_at', 'deadline_at', 'attempt')})
        acquired = None
        late = task['checkpoint'] == 'late'
        if late:
            worker.experiment_late_waiting = True
        try:
            async with worker.request_lock:
                # A storage interval may have been requested while waiting.
                # Once owned, the complete paid receipt and checkpoint drain
                # together before maintenance or another SGO request proceeds.
                if not authorized(worker, task, at=worker.now()):
                    raise CheckpointUnavailable('experiment_authority_or_window_closed')
                worker.page_in_progress = True
                try:
                    acquired = await acquire(worker, task, eligible=self._authorized, request_locked=True)
                    saved = await owned_thread(self._finish, worker, task, acquired)
                finally:
                    worker.page_in_progress = False
            self.progress = dict(self.progress, state='ready', last_saved=saved,
                                 last_completed_at=worker.now().isoformat())
        except asyncio.CancelledError:
            # The durable claim survives termination; an uncertain request is
            # never redispatched merely because this coroutine was cancelled.
            if task.get('_pull_id'):
                await owned_thread(_end_pull, task['_pull_id'], 'cancelled', dict(reason='capture_cancelled'))
            raise
        except Exception as exc:
            reason = str(exc)[:160] or type(exc).__name__
            details = getattr(exc, 'details', None) or (acquired or {}).get('acquisition')
            dispatched = getattr(exc, 'dispatched', acquired is not None)
            failure = await owned_thread(self._fail, task, reason, at=worker.now(),
                                         dispatched=dispatched, details=details)
            if task.get('_pull_id'):
                await owned_thread(_end_pull, task['_pull_id'], 'failed', dict(reason=reason))
            self.progress = dict(self.progress, state='degraded', last_failure=failure,
                                 last_completed_at=worker.now().isoformat())
        finally:
            if late:
                worker.experiment_late_waiting = False

    async def run(self):
        from app.diagnostics import failure
        while not self.closed:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure(__name__, 'early_tminus10_experiment', exc)
                self.progress = dict(state='unavailable', version=VERSION, reason=str(exc)[:160])
            await asyncio.sleep(1)

    async def close(self):
        self.closed = True
        if self.task:
            await self.task
