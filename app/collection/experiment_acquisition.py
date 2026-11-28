"""Collector-owned early/T-10 experiment acquisition and bounded result follow-up.

The browser never calls this owner. Checkpoints share the running SGO worker's
transport, account window, source controls and serialized request slot. Nothing
here creates an account partition, retries an uncertain request or releases a
financial hold.
"""
import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect

from app.storage.store import ROOT, connect, hashed, stamp
from app.comparison.reference_scope import REQUEST_BOOKS
from app.diagnostics import failure as report_failure
from app.research.experiment import LATE_BATCH_SIZE
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
REQUEST_RESERVATION_SECONDS = 60


def late_protection_until(worker, *, at=None):
    """When the serial provider lane can next admit an ordinary page."""
    at = at or worker.now()
    return max((deadline for target, deadline in getattr(worker, 'experiment_late_windows', ())
                if target - timedelta(seconds=REQUEST_RESERVATION_SECONDS) <= at <= deadline), default=None)


def late_protection_active(worker):
    return late_protection_until(worker) is not None


class CheckpointUnavailable(RuntimeError):
    def __init__(self, reason, *, details=None, dispatched=False):
        super().__init__(reason)
        self.details = details or {}
        self.dispatched = dispatched


class BatchAuthorityChanged(CheckpointUnavailable):
    def __init__(self, excluded):
        super().__init__('experiment_authority_or_window_closed')
        self.excluded = excluded


class CheckpointStorageUnavailable(CheckpointUnavailable):
    """The pre-dispatch storage check could not fit this request scope."""


def _start_pull(task, params, at):
    from app.storage.acquisition_snapshot import start
    with connect() as db:
        return start(db, params, at=at, event=task['event'],
                     late_task=task if task['checkpoint'] == 'late' else None)


def _end_pull(pull_id, state, details):
    from app.storage.acquisition_snapshot import finish
    with connect() as db:
        finish(db, pull_id, state, details=details)


async def _close_failed_pull(pull_id, state, details):
    try:
        await owned_thread(_end_pull, pull_id, state, details)
    except Exception as cleanup:
        report_failure(__name__, 'checkpoint_pull_cleanup', cleanup)


def _cancelled_evidence(exc):
    return dict(reason='capture_cancelled') | getattr(exc, 'checkpoint_details', {})


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


def batch_scope(tasks):
    params = request_scope(tasks[0])
    return dict(params, eventIDs=','.join(request_scope(task)['eventIDs'] for task in tasks),
                limit=len(tasks))


def request_shape(task):
    scope = request_scope(task)
    return tuple((key, value) for key, value in scope.items() if key not in ('eventIDs', 'limit'))


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


def declaration_changed(old, incoming):
    return (not old or any(incoming[key] != old.get(key) for key in ('home', 'away', 'league'))
            or stamp(incoming['starts_at']) != stamp(old['starts_at'])
            or (incoming['status'].get('cancelled') is True) != (old['status'].get('cancelled') is True))


def discover_events(db, *, at, leagues, tracked_source_ids=()):
    """Observe retained event metadata now; never backdate an early checkpoint."""
    # Existing games must receive cancellations and reschedules even outside
    # the new-game 24-hour window. The store applies that window on creation.
    rows = list(db.execute('''SELECT f.event_id,f.facts-'members' AS facts,g.event AS tracked_event
        FROM public.current_sgo_event_frame f
        LEFT JOIN public.ev_experiment_game g
          ON g.provider='sportsgameodds' AND g.source_event_id=f.event_id
        WHERE f.facts#>>'{event_context,league}'=ANY(%s)
          AND (((f.facts->>'starts_at')::timestamptz>%s
              AND (f.facts->>'starts_at')::timestamptz<=%s) OR f.event_id=ANY(%s))
        ORDER BY (f.facts->>'starts_at')::timestamptz,f.event_id LIMIT 2049''',
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
        value = event_metadata(event, facts['receipt_sha256'])
        if declaration_changed(row['tracked_event'], value):
            result.append(value)
    return result


@asynccontextmanager
async def _request_slot(worker, already_locked):
    if already_locked:
        yield
    else:
        async with worker.request_lock:
            yield


async def acquire(worker, task, *, eligible=None, request_locked=False, batch=None):
    """Fetch exactly once after admission; preserve real dispatch/receipt clocks.

    Eligibility is checked by GuardedPageCollector again after account usage and
    immediately before network dispatch. A late response remains a paid receipt,
    but cannot become a valid checkpoint.
    """
    from .activity_collector import budget_admit
    from app.research.experiment import sql_runway_bytes
    from .current_storage_policy import SQL_BYTE_CAP, sql_usage, require_disk_space
    from .odds_http import BudgetStop
    from .original_receipts import capture
    from .sportsgameodds_collector import GuardedPageCollector
    from .sportsgameodds_schedule import response_object_charge

    if worker.collector is None or worker.ledger is None or worker.window_id is None:
        raise CheckpointUnavailable('experiment_source_not_initialized')
    params = batch_scope(batch) if batch else request_scope(task)
    reserved_bytes = sum(item.get('storage_reservation_bytes', 0) for item in (batch or [task]))
    append_bytes = 3 * reserved_bytes
    pull_id = None
    receipt = {}
    timings = dict(claimed_at=task.get('requested_at'), lane_entered_at=worker.now().isoformat())
    if batch:
        timings['manifest_ready_at'] = max(item['_manifest_ready_at'] for item in batch)
        timings['lane_entered_at'] = task['_lane_entered_at']
        timings['batch_work_started_at'] = task['_batch_work_started_at']
    dispatched_at = None
    transport = worker.transport

    class TimedTransport:
        async def fetch(self, request, key):
            nonlocal dispatched_at
            dispatched_at = worker.now()
            return await transport.fetch(request, key)

    async def usage():
        timings['usage_requested_at'] = worker.now().isoformat()
        value = await worker.collector.account_usage()
        timings['usage_ready_at'] = worker.now().isoformat()
        return value

    def storage():
        with connect() as db:
            runway = sql_runway_bytes(reserved_bytes) if reserved_bytes else 0
            if sql_usage(db) + runway >= SQL_BYTE_CAP:
                raise CheckpointStorageUnavailable('research_sql_runway')
        try:
            require_disk_space(ROOT / '.local/postgres', append_bytes=append_bytes)
        except BudgetStop as exc:
            raise CheckpointStorageUnavailable(str(exc)) from exc

    async def check(_params, *, own_reserved=False):
        moment = worker.now()
        if task['checkpoint'] != 'late' and late_protection_until(worker, at=moment):
            raise CheckpointUnavailable('protected_tminus10_capture_due')
        if batch:
            excluded = {item['token'] for item in batch if not authorized(worker, item, at=moment)}
            if eligible is not None:
                excluded.update(await eligible(batch, moment))
            if excluded:
                raise BatchAuthorityChanged(excluded)
        elif not authorized(worker, task, at=moment):
            return False
        elif eligible is not None:
            value = eligible(task, moment)
            if not (await value if inspect.isawaitable(value) else value):
                return False
        await owned_thread(storage)
        reserved = (max(0, getattr(worker, 'experiment_reserved_objects', 0))
                    if task['checkpoint'] != 'late' else 0)
        # Rolling exposure already includes this request after the collector
        # reserves it. Rechecking must not count that same object twice.
        budget_admit(worker.ledger, worker.window_id,
                     (0 if own_reserved else params['limit']) + reserved, worker.now())
        reserved_requests = (max(0, getattr(worker, 'experiment_reserved_requests', 0))
                             if task['checkpoint'] != 'late' else 0)
        if reserved_requests:
            rate = worker.ledger.request_capacity(worker.window_id, now=worker.now())
            if rate['available'] < reserved_requests or (not own_reserved and rate['available'] == reserved_requests):
                raise CheckpointUnavailable('experiment_checkpoint_rate_headroom')
        if batch:
            excluded = {item['token'] for item in batch if not authorized(worker, item, at=worker.now())}
            if excluded:
                raise BatchAuthorityChanged(excluded)
            return True
        return authorized(worker, task, at=worker.now())

    async def retain(request, response):
        timings['response_received_at'] = response.received_at
        receipt.update(await owned_thread(capture, request, response,
                                          root=worker.original_response_root))
        timings['original_retention_finished_at'] = worker.now().isoformat()
        worker.metrics['experiment_original_receipt'] = receipt

    async def reserved_check(params):
        return await check(params, own_reserved=True)

    collector = GuardedPageCollector(worker.ledger, worker.window_id, TimedTransport(),
        controls=worker.controls, account_usage=usage,
        eligible=check, eligible_after_reservation=reserved_check, receipt_retainer=retain)
    late = task['checkpoint'] == 'late'
    if late and not request_locked:
        worker.experiment_late_waiting = True
    try:
        async with _request_slot(worker, request_locked):
            if not await check(params):
                raise CheckpointUnavailable('experiment_authority_or_window_closed')
            if not batch and task['checkpoint'] != 'outcome':
                pull_id = await owned_thread(_start_pull, task, params, worker.now())
                task['_pull_id'] = pull_id
                timings['manifest_ready_at'] = worker.now().isoformat()
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
                    at = worker.now()
                    retry = worker.ledger.request_capacity(worker.window_id, now=at)['next_at']
                    if at >= stamp(task['deadline_at']) or retry >= stamp(task['deadline_at']):
                        raise CheckpointUnavailable('experiment_rate_window_missed') from exc
                    timings['last_rate_wait_until'] = retry.isoformat()
                    await asyncio.sleep(max(0, (retry - at).total_seconds()))
    except BaseException as exc:
        dispatched = dispatched_at is not None
        details = dict(request_scope=params, original_response=receipt,
            dispatch_at=dispatched_at.isoformat() if dispatched else None,
            failed_at=worker.now().isoformat(), timings=timings)
        details.update(getattr(exc, 'details', {}) or {})
        cancelled = isinstance(exc, asyncio.CancelledError)
        if cancelled:
            exc.checkpoint_details = details
        reason = str(exc)[:160] or type(exc).__name__
        if pull_id:
            await _close_failed_pull(pull_id, 'cancelled' if cancelled else 'failed' if dispatched else 'refused',
                                     details | dict(reason=reason))
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, CheckpointUnavailable):
            exc.dispatched = dispatched
            exc.details = details
            raise
        raise CheckpointUnavailable(reason, dispatched=dispatched, details=details) from exc
    finally:
        if late and not request_locked:
            worker.experiment_late_waiting = False
    details = dict(version=VERSION, request_scope=params, pull_id=page.pull_id, attempt_id=page.attempt_id,
                   dispatch_at=dispatched_at.isoformat() if dispatched_at else None,
                   receipt_sha256=page.receipt_sha256, original_response=receipt, timings=timings)
    try:
        known_at = worker.now()
        worker.metrics['last_valid_received_at'] = page.received_at
        details.update(known_at=known_at.isoformat(), paid_event_requests=1,
                       charged_objects=response_object_charge(len(page.events)), response_event_count=len(page.events),
                       next_cursor_present=page.next_cursor is not None, timings=dict(timings, parse_finished_at=known_at.isoformat()))
        if batch:
            details['batch'] = dict(request_scope=params, size=len(batch),
                response_event_ids=[event['event_id'] for event in page.events],
                paid_event_requests=details.pop('paid_event_requests'), charged_objects=details.pop('charged_objects'))
            if receipt.get('state') != 'retained' or receipt.get('receipt_sha256') != page.receipt_sha256:
                raise CheckpointUnavailable('experiment_original_receipt_unavailable', details=details, dispatched=True)
            page = replace(page, physical_event_ids=tuple(details['batch']['response_event_ids']))
            worker.metrics['experiment_acquisition'] = details
            return dict(page=page, dispatch_at=dispatched_at, known_at=known_at, acquisition=details)
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
            await _close_failed_pull(pull_id,
                'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed',
                dict(getattr(exc, 'details', None) or details, reason=str(exc)[:160] or type(exc).__name__))
        raise


def event_from_batch(task, acquired, events, quotes):
    """Project one declared event from an authentic shared response."""
    from .sportsgameodds_adapter import project_event

    source_page = acquired['page']
    params = request_scope(task)
    identity = params['eventIDs']
    event = events.get(identity)
    details = dict(acquired['acquisition'], request_scope=params, pull_id=task['_pull_id'])
    details['timings'] = dict(details['timings'], claimed_at=task.get('requested_at'))
    if not event or event['league'] != task['event']['league']:
        reason = 'experiment_event_not_returned' if not event else 'experiment_response_event_scope'
        raise CheckpointUnavailable(reason, details=details, dispatched=True)
    received_at = stamp(event['received_at'])
    details['received_at'] = event['received_at']
    if received_at > acquired['known_at']:
        raise CheckpointUnavailable('experiment_future_receipt', details=details, dispatched=True)
    if acquired['known_at'] > stamp(task['deadline_at']):
        raise CheckpointUnavailable('experiment_response_after_deadline', details=details, dispatched=True)
    page = project_event(source_page, event, quotes.get(identity, ()),
                         pull_id=task['_pull_id'], request_scope=params)
    return dict(acquired, page=page, acquisition=details, received_at=received_at, request_scope=params)


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
        self.last_comparison = None
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
            discovered = experiment.discover(db, events, at=at) if events else {}
            return dict(discovered=discovered, status=experiment.status(db))

    def _pressure(self, at):
        from app.research import experiment
        with self.connector() as db:
            result = experiment.late_schedule_pressure(db, at=at, through=at + timedelta(minutes=15))
            # Keep quota reservations for all scheduled tasks, including games
            # whose prerequisite early turn still needs to run.
            result['objects'] = experiment.reserved_late_objects(db, at=at, through=at + timedelta(minutes=15))
            result['requests'] = experiment.reserved_late_objects(
                db, at=at, through=at + timedelta(seconds=REQUEST_RESERVATION_SECONDS))
            return result

    def _claim(self, at, *, protected=False):
        from app.research import experiment
        with self.connector() as db:
            tasks = experiment.due(db, at=at, limit=1, late_only=protected, recheck_clock=True)
            return tasks[0] if tasks else None

    def _claim_late(self, at):
        from app.research import experiment
        with self.connector() as db:
            return experiment.due(db, at=at, limit=LATE_BATCH_SIZE, late_only=True, recheck_clock=True)

    def _compare_pending(self, worker):
        from app.research import experiment
        from .background_work import BACKGROUND, SOURCE_RUNWAY

        def can_start():
            return (not late_protection_active(worker) and not worker.page_in_progress
                    and not any(worker.controls().values()))

        with BACKGROUND.claim('observations', SOURCE_RUNWAY, source=True) as lease:
            if lease:
                with self.connector() as db:
                    return experiment.finish_pending_comparison(db, can_start=can_start)

    async def _authorized(self, task, at):
        from app.research import experiment
        def read():
            with self.connector() as db:
                return experiment.task_authorized(db, task['token'], at=at)
        return await owned_thread(read)

    async def _excluded_members(self, tasks, at):
        from app.research import experiment
        tokens = {task['token'] for task in tasks}
        def read():
            with self.connector() as db:
                return tokens - experiment.authorized_late_tokens(db, tokens, at=at)
        return await owned_thread(read)

    def _fail(self, task, reason, *, at, dispatched=False, details=None):
        from app.research import experiment
        with self.connector() as db:
            if not dispatched and reason == 'protected_tminus10_capture_due':
                return experiment.defer_checkpoint(db, task, at=at)
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
            with self.connector() as db:
                acquired['acquisition'].setdefault('timings', {})['calculation_started_at'] = worker.now().isoformat()
                actual_event = event_metadata(page.events[0], page.receipt_sha256)
                # Schedule mutations commit before the CPU-only calculation.
                # The due task still has to pass the same schedule/token check.
                if declaration_changed(task['event'], actual_event):
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
                from app.storage.acquisition_snapshot import (
                    finish, observe_checkpoint_commit, prepare_publication, publish, record_timing,
                )
                acquired['acquisition'].setdefault('timings', {})['calculation_finished_at'] = finished.isoformat()
                snapshot['acquisition'] = deepcopy(acquired['acquisition'])
                prepared = prepare_publication(page, snapshot, details=acquired['acquisition'])
                acquired['acquisition']['timings']['projection_ready_at'] = worker.now().isoformat()
                with db.transaction():
                    saved = experiment.capture(db, task['game_id'], task['checkpoint'], snapshot,
                        token=task['token'], requested_at=acquired['dispatch_at'],
                        received_at=acquired['received_at'], known_at=finished, scope=acquired['request_scope'],
                        market_publication_bytes=prepared.allocation_bytes, snapshot_bytes=prepared.raw_bytes,
                        defer_comparison='batch' in acquired['acquisition'])
                    if saved['state'] == 'captured':
                        acquired['acquisition']['timings']['checkpoint_recorded_at'] = saved['recorded_at']
                        if task['checkpoint'] == 'late':
                            acquired['acquisition']['checkpoint_identity'] = dict(
                                id=saved['id'], schedule_id=task['schedule_id'])
                        publish(db, page, snapshot, details=acquired['acquisition'], prepared=prepared)
                        record_timing(db, page.pull_id, 'persistence_checked_at')
                        persisted = experiment._dbclock(db)
                        if persisted > stamp(task['deadline_at']):
                            acquired['acquisition']['timings']['persistence_checked_at'] = persisted.isoformat()
                            raise CheckpointUnavailable('experiment_checkpoint_persistence_after_deadline',
                                dispatched=True, details=acquired['acquisition'])
                    else:
                        finish(db, page.pull_id, 'failed', details=dict(acquired['acquisition'], **saved))
                if task['checkpoint'] == 'late' and saved['state'] == 'captured':
                    try:
                        observe_checkpoint_commit(db, page.pull_id, checkpoint_id=saved['id'],
                            **{key: task[key] for key in ('game_id', 'schedule_id', 'target_at', 'deadline_at')})
                    except Exception as exc:
                        report_failure(__name__, 'checkpoint_commit_observation', exc)
                return saved

    async def _failed_turn(self, worker, task, exc, acquired=None):
        reason = str(exc)[:160] or type(exc).__name__
        details = getattr(exc, 'details', None) or (acquired or {}).get('acquisition')
        dispatched = getattr(exc, 'dispatched', acquired is not None)
        try:
            failure = await owned_thread(self._fail, task, reason, at=worker.now(),
                                         dispatched=dispatched, details=details)
        except Exception as cleanup:
            report_failure(__name__, 'checkpoint_failure_record', cleanup)
            failure = dict(state='unrecorded', reason=reason, dispatched=dispatched, details=details)
        if task.get('_pull_id'):
            await _close_failed_pull(task['_pull_id'], 'failed' if dispatched else 'refused',
                                     dict(details or {}, reason=reason))
        self.progress = dict(self.progress, state='degraded', last_failure=failure,
                             last_completed_at=worker.now().isoformat())

    async def _complete_turn(self, worker, task, acquired):
        try:
            if worker.now() > stamp(task['deadline_at']):
                raise CheckpointUnavailable('experiment_checkpoint_window_missed', dispatched=True)
            saved = await owned_thread(self._finish, worker, task, acquired)
        except Exception as exc:
            await self._failed_turn(worker, task, exc, acquired)
        else:
            self.progress = dict(self.progress, state='ready', last_saved=saved,
                                 last_completed_at=worker.now().isoformat())

    async def _capture_batch(self, worker, tasks):
        from .sportsgameodds_collector import DailyObjectPacing

        members = []
        started_at = worker.now().isoformat()
        for task in tasks:
            try:
                if not authorized(worker, task, at=worker.now()):
                    raise CheckpointUnavailable('experiment_authority_or_window_closed')
                task.setdefault('_batch_work_started_at', started_at)
                if '_pull_id' not in task:
                    task['_pull_id'] = await owned_thread(_start_pull, task, request_scope(task), worker.now())
                    task['_manifest_ready_at'] = worker.now().isoformat()
            except Exception as exc:
                await self._failed_turn(worker, task, exc)
            else:
                members.append(task)

        while members:
            try:
                acquired = await acquire(worker, members[0], eligible=self._excluded_members,
                                         request_locked=True, batch=members)
            except BatchAuthorityChanged as exc:
                # No dispatch occurred. Remove revoked claims and independently
                # recheck the remaining exact members under a fresh reservation.
                for task in members:
                    if task['token'] in exc.excluded:
                        await self._failed_turn(worker, task, exc)
                members = [task for task in members if task['token'] not in exc.excluded]
            except Exception as exc:
                # Smaller groups can fit the same storage or object allowance.
                # Reuse the original claims and manifests and recheck their deadlines.
                cause = exc.__cause__
                if (len(members) > 1 and isinstance(exc, CheckpointUnavailable) and not exc.dispatched and
                        (isinstance(exc, CheckpointStorageUnavailable) or isinstance(cause, DailyObjectPacing) or
                         str(cause) in ('insufficient object allowance', 'operational_object_budget'))):
                    half = len(members) // 2
                    await self._capture_batch(worker, members[:half])
                    await self._capture_batch(worker, members[half:])
                    return
                for task in members:
                    await self._failed_turn(worker, task, exc)
                return
            else:
                break
        if not members:
            return
        events = {event['event_id']: event for event in acquired['page'].events}
        quotes = defaultdict(list)
        for quote in acquired['page'].quotes:
            quotes[quote['event_id']].append(quote)
        for task in members:
            try:
                individual = event_from_batch(task, acquired, events, quotes)
            except CheckpointUnavailable as exc:
                await self._failed_turn(worker, task, exc)
            else:
                await self._complete_turn(worker, task, individual)

    async def _capture_group(self, worker, tasks):
        worker.experiment_late_waiting = True
        groups = {}
        for task in tasks:
            groups.setdefault(request_shape(task), []).append(task)
        try:
            async with worker.request_lock:
                entered_at = worker.now().isoformat()
                for members in groups.values():
                    if worker.controls()['stopped'] or worker.controls()['source_paused']:
                        for task in members:
                            await self._failed_turn(worker, task,
                                CheckpointUnavailable('experiment_authority_or_window_closed'))
                        continue
                    for task in members:
                        task['_lane_entered_at'] = entered_at
                    worker.page_in_progress = True
                    try:
                        await self._capture_batch(worker, members)
                    finally:
                        worker.page_in_progress = False
        except asyncio.CancelledError as exc:
            for task in tasks:
                if task.get('_pull_id'):
                    await _close_failed_pull(task['_pull_id'], 'cancelled', _cancelled_evidence(exc))
            raise
        finally:
            worker.experiment_late_waiting = False

    async def tick(self):
        worker = self.service.workers.get('sportsgameodds')
        if worker is None or worker.collector is None or worker.ledger is None or worker.window_id is None:
            self.progress = dict(state='waiting_for_source', version=VERSION)
            return
        controls = worker.controls()
        if controls['stopped'] or controls['source_paused']:
            worker.experiment_late_windows = ()
            worker.experiment_reserved_objects = worker.experiment_reserved_requests = 0
            self.last_discovery = None
            self.progress = dict(state='source_stopped_or_paused', version=VERSION)
            return
        at = worker.now()
        if self.last_discovery is None or (at-self.last_discovery).total_seconds() >= DISCOVERY_SECONDS:
            self.last_discovery = at
            try:
                pressure = await owned_thread(self._pressure, at)
                worker.experiment_late_windows = pressure['windows']
                worker.experiment_reserved_requests = pressure['requests']
                worker.experiment_reserved_objects = pressure['objects']
                rate = await owned_thread(worker.ledger.request_capacity, worker.window_id, now=at)
                worker.metrics['experiment_rate_capacity'] = dict(
                    limit=rate['limit'], used=rate['used'], available=rate['available'],
                    as_of=at.isoformat(), next_at=rate['next_at'].isoformat())
                reserved = dict(reserved_objects=worker.experiment_reserved_objects,
                                reserved_requests=worker.experiment_reserved_requests)
                self.progress = dict(self.progress, **reserved)
                if not late_protection_active(worker):
                    prepared = await owned_thread(self._prepare, at)
                    self.progress = dict(state='ready', version=VERSION, **reserved, **prepared)
            except Exception as exc:
                # Discovery errors must not starve already declared T-10 work.
                # Its own fresh authority, timing and capacity checks still run.
                self.progress = dict(state='degraded', version=VERSION,
                    discovery_reason=str(exc)[:160] or type(exc).__name__)
        protected = late_protection_active(worker)
        if protected:
            tasks = await owned_thread(self._claim_late, worker.now())
            if tasks:
                await self._capture_group(worker, tasks)
                return True
            task = None
        else:
            task = await owned_thread(self._claim, worker.now(), protected=False)
        if task is None:
            at = worker.now()
            if not protected and (self.last_comparison is None or
                                  (at - self.last_comparison).total_seconds() >= DISCOVERY_SECONDS):
                self.last_comparison = at
                await owned_thread(self._compare_pending, worker)
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
                    await self._complete_turn(worker, task, acquired)
                finally:
                    worker.page_in_progress = False
        except asyncio.CancelledError as exc:
            # The durable claim survives termination; an uncertain request is
            # never redispatched merely because this coroutine was cancelled.
            if task.get('_pull_id'):
                await _close_failed_pull(task['_pull_id'], 'cancelled', _cancelled_evidence(exc))
            raise
        except Exception as exc:
            await self._failed_turn(worker, task, exc, acquired)
        finally:
            if late:
                worker.experiment_late_waiting = False
        return True

    async def run(self):
        while not self.closed:
            try:
                if await self.tick():
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                report_failure(__name__, 'early_tminus10_experiment', exc)
                self.progress = dict(state='unavailable', version=VERSION, reason=str(exc)[:160])
            await asyncio.sleep(1)

    async def close(self):
        self.closed = True
        if self.task:
            await self.task
