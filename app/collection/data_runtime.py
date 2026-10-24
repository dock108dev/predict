"""Independent collection and shared calculation owner for the ordinary database."""
import argparse
import asyncio
import inspect
import signal
from app.diagnostics import failure
from app.storage.store import connect, Store
from app.dashboard.current_state import CurrentStore, SelectionError
from .current_policy import ROOT, load, candidate
from .current_service import CurrentService
from .local_ownership import LocalOwnership
from .runtime_status import RuntimeState, RUNTIME_LOCK


class DataRuntime:
    """One OS + database owner, with fixture-injectable source/calculation owners."""
    def __init__(self, service=None, *, connector=connect, owner=None, scanner_factory=None,
                 board_factory=None, config_path=None):
        self.connector = connector
        self.state = RuntimeState(connector)
        self.owner = owner or LocalOwnership(ROOT / '.local/predict-data-runtime-owner.lock')
        self.service = service
        self.config_path = config_path
        self.scanner_factory = scanner_factory
        self.board_factory = board_factory
        self.scanner = self.board = self.store = self.lock_connection = None
        self.paused_sources = set()
        self.global_stopped = False
        self.stopping = asyncio.Event()
        self.heartbeat_task = self.command_task = None
        self.failed = False
        self.selected_fees = None

    def prepare_status(self):
        from .background_work import BACKGROUND
        self.service.background_work = dict(BACKGROUND.snapshot(),progress=getattr(self.board,'progress',{}))
        self.service.background_calculations = dict(
            scanner='pending' if self.scanner is None else 'unavailable' if getattr(self.scanner, 'error', None) else 'stopped' if getattr(self.scanner, 'closed', False) else 'running',
            scanner_error=None if self.scanner is None or not getattr(self.scanner, 'error', None) else 'background_scanner_unavailable',
            board='pending' if self.board is None else 'unavailable' if getattr(self.board, 'error', None) else 'running',
            board_error=None if self.board is None or not getattr(self.board, 'error', None) else 'background_board_unavailable',
            coverage='pending' if self.board is None else 'unavailable'
                if getattr(self.board,'coverage_error',None) else 'pending'
                if not getattr(self.board,'last_coverage',None) or getattr(self.board,'last_coverage',{}).get('deferred') else 'running',
            coverage_error=None if self.board is None else getattr(self.board,'coverage_error',None),
            observations='pending' if self.board is None else 'unavailable'
                if getattr(self.board,'observation_error',None) or getattr(self.board,'task',None) and self.board.task.done()
                else 'stopped' if getattr(self.board,'closed',False) else 'running')

    def persist(self, phase='running'):
        self.prepare_status()
        self.state.write(self.service, state=phase, paused_sources=self.paused_sources,
                         global_stopped=self.global_stopped)

    async def persist_control(self, phase='running'):
        self.prepare_status()
        value=self.state.snapshot(self.service,state=phase,paused_sources=self.paused_sources,
                                  global_stopped=self.global_stopped)
        await asyncio.to_thread(self.state.write_snapshot,value)

    async def persist_heartbeat(self):
        self.prepare_status()
        value=self.state.snapshot(self.service, paused_sources=self.paused_sources,
                                  global_stopped=self.global_stopped)
        return await asyncio.to_thread(self.state.write_snapshot, value, heartbeat=True)

    async def start(self):
        # Acquire before migration, epoch access, source construction or dispatch.
        self.owner.acquire('data-runtime-starting')
        try:
            self.lock_connection = self.connector()
            locked = self.lock_connection.execute('SELECT pg_try_advisory_lock(%s) AS held', (RUNTIME_LOCK,)).fetchone()['held']
            if not locked:
                raise ValueError('Another data runtime owns this database')
            self.resource_guard()
            Store(self.lock_connection).migrate()
            self.paused_sources, self.global_stopped = self.state.retained_controls()
            if self.service is None:
                self.service = CurrentService(config=load(self.config_path), config_loader=lambda: load(self.config_path),
                    retained_directory=ROOT / '.local/predict-odds/diagnostics', database_mode=True,
                    paused_sources=self.paused_sources, globally_stopped=self.global_stopped)
            else:
                self.service.paused_sources = set(self.paused_sources)
                self.service.globally_stopped = self.global_stopped
            # Even an explicitly stopped owner needs its exact source identity
            # for guarded recovery; this does not consume acquisition authority.
            if self.global_stopped and self.service.digest is None:
                self.service.digest = candidate()[0]
            self.store = CurrentStore(self.service)
            await self.persist_control('starting')
            await self.service.start(self.store)
            await self.persist_control()
            if self.scanner_factory is None:
                from app.dashboard.scanner_api import Scanner
                self.scanner = Scanner(self.service, connector=self.connector, durable=True)
            else:
                self.scanner = self.scanner_factory(self.service)
            result = self.scanner.start()
            if inspect.isawaitable(result):
                await result
            if self.board_factory:
                self.board = self.board_factory(self.service)
                result = self.board.start()
                if inspect.isawaitable(result):
                    await result
            self.heartbeat_task = asyncio.create_task(self.heartbeat(), name='predict-data-heartbeat')
            self.command_task = asyncio.create_task(self.commands(), name='predict-data-controls')
        except BaseException:
            self.failed = True
            try:
                await self.close()
            except (Exception, asyncio.CancelledError) as exc:
                failure(__name__, 'data_runtime_start_cleanup', exc)
            raise

    def resource_guard(self):
        from .continuous import rss
        from .current_storage_policy import require_disk_space, SQL_BYTE_CAP
        require_disk_space(ROOT / '.local/postgres')
        if self.lock_connection.execute('SELECT pg_database_size(current_database()) n').fetchone()['n'] >= SQL_BYTE_CAP:
            raise ValueError('data_runtime_sql_storage_guard')
        sampled = rss()
        if self.service is not None:
            self.service.sampled_rss = sampled
            self.service.peak_rss = max(getattr(self.service, 'peak_rss', 0), sampled)
        if sampled >= 768 * 1024**2:
            raise ValueError('data_runtime_memory_guard')

    async def heartbeat(self):
        observed_tasks = set()
        try:
            while not self.stopping.is_set():
                # Also prove that our session-level database ownership survived.
                # A dropped lock connection must stop dispatch before reconnect.
                await asyncio.to_thread(self.lock_connection.execute, 'SELECT 1')
                if self.command_task and self.command_task.done():
                    self.command_task.result()
                    raise RuntimeError('data_runtime_controls_stopped')
                for worker, attribute, error_field in (
                    (self.scanner, 'task', 'error'),
                    (self.board, 'task', 'observation_error'),
                    (self.board, 'estimate_task', 'estimate_error'),
                    (self.board, 'coverage_task', 'coverage_error'),
                ):
                    task = getattr(worker, attribute, None)
                    if task and task.done():
                        if task not in observed_tasks:
                            observed_tasks.add(task)
                            error = None if task.cancelled() else task.exception()
                            failure(__name__, 'data_runtime_worker_stopped',
                                    error or RuntimeError('background_worker_stopped'))
                        setattr(worker, error_field, 'background_calculation_worker_stopped')
                        if error_field != 'coverage_error':
                            worker.error = 'background_calculation_worker_stopped'
                await asyncio.to_thread(self.resource_guard)
                await self.persist_heartbeat()
                try:
                    await asyncio.wait_for(self.stopping.wait(), 1)
                except TimeoutError:
                    pass
        except Exception as exc:
            failure(__name__, 'data_runtime_heartbeat', exc)
            self.failed = True
            self.stopping.set()
            try:await self.persist_control('stopping')
            except Exception as secondary:
                failure(__name__, 'data_runtime_failure_status', secondary)
            await self.service.close()

    async def commands(self):
        while not self.stopping.is_set():
            for command in await asyncio.to_thread(self.state.pending):
                try:
                    if command['runtime_id'] != self.service.runtime_id:
                        raise SelectionError(409, 'runtime_conflict', 'The owning runtime changed before this control was applied.')
                    details = await self.control(command['action'], command['body'])
                    await self.persist_control()
                    result = dict(acknowledged=True, runtime_id=self.service.runtime_id,
                                  action=command['action'])
                    if isinstance(details,dict):result.update(details)
                    await asyncio.to_thread(self.state.acknowledge, command['id'], result)
                except SelectionError as exc:
                    await self.persist_control()
                    await asyncio.to_thread(self.state.acknowledge, command['id'], exc.body, failed=True)
                except Exception as exc:
                    failure(__name__, 'data_runtime_control', exc)
                    await self.persist_control()
                    await asyncio.to_thread(self.state.acknowledge, command['id'],
                        dict(error='data_runtime_control_failed', reason='The owning data runtime could not safely finish this control.'), failed=True)
            await asyncio.sleep(.1)

    async def control(self, action, body):
        if action == 'stop' and body == {}:
            self.global_stopped = self.service.globally_stopped = True
            self.service.dispatch=False
            self.service.ingress.revoke()
            await self.persist_control('stopping')
            finite_clean = await self.withdraw(self.service.close())
            if not finite_clean:
                raise SelectionError(409,'cleanup_safety_unresolved','The finite operation has not confirmed transport cleanup.')
        elif action == 'pause' and set(body) == {'source'} and body['source'] in ('kalshi', 'polymarket_us', 'the_odds_api'):
            venue = body['source']
            if venue not in self.service.workers:
                raise SelectionError(409, 'source_not_running', 'This source is not running.')
            self.service.workers[venue].closed=True
            if hasattr(self.service.workers[venue],'lifecycle'):self.service.workers[venue].lifecycle.revoke()
            self.service.ingress.revoke(venue)
            self.paused_sources.add(venue)
            self.service.paused_sources = set(self.paused_sources)
            await self.persist_control()
            finite_clean = await self.withdraw(self.service.pause(venue), finite=venue=='kalshi')
            if not finite_clean:
                raise SelectionError(409,'cleanup_safety_unresolved','The finite operation has not confirmed transport cleanup.')
        elif action == 'collect_selected_fees':
            from .selected_fee_operation import SelectedFeeOperation
            if self.selected_fees is None:self.selected_fees=SelectedFeeOperation(self)
            try:return await self.selected_fees.start(body)
            except (ValueError,OSError) as exc:
                failure(__name__, 'selected_fee_control_refused', exc)
                raise SelectionError(409,'selected_fee_control_refused',
                    'The selected fee operation was refused; inspect the data runtime log and Admin status.') from None
        elif action == 'refresh' and set(body) == {'sports', 'request_id', 'reference'}:
            await self.service.refresh_aggregate(body['sports'], body['request_id'], reference=body['reference'])
        elif action == 'recover' and set(body) == {'runtime_id', 'candidate_digest'}:
            # Do not clear a persisted Stop unless recovery actually succeeds.
            old_stop = self.global_stopped
            self.service.globally_stopped = False
            try:
                await self.service.recover(body['runtime_id'], body['candidate_digest'])
            except BaseException:
                self.service.globally_stopped = old_stop
                raise
            self.global_stopped = False
        elif action == 'recover_accounting' and set(body) == {'runtime_id', 'candidate_digest', 'recovery_id', 'covered_attempts'}:
            await self.service.recover_accounting(body['runtime_id'], body['candidate_digest'], body['recovery_id'], body['covered_attempts'])
        else:
            raise SelectionError(400, 'data_runtime_control_invalid', 'Exact supported data runtime control required.')
        if action in ('stop', 'pause') and self.service.cleanup_errors:
            raise SelectionError(409, 'cleanup_safety_unresolved', 'The owning runtime withdrew acquisition, but safe cleanup remains unresolved.')

    async def withdraw(self, ordinary, *, finite=True):
        # Schedule ordinary revocation first; neither cleanup may delay or skip
        # the other. A supplemental failure cannot leave source dispatch alive.
        operations=[ordinary]
        if finite and self.selected_fees:operations.append(self.selected_fees.stop())
        results=await asyncio.gather(*operations,return_exceptions=True)
        if isinstance(results[0],BaseException):
            self.service.cleanup_errors.append('source_cleanup_unresolved')
        clean=not any(isinstance(value,BaseException) for value in results) and (len(results)==1 or results[1] is True)
        if not clean:self.service.cleanup_errors.append('selected_fee_cleanup_unresolved')
        return clean

    async def close(self):
        self.stopping.set()
        errors = []

        async def attempt(operation, action):
            try:
                result = action()
                if inspect.isawaitable(result):await result
            except (Exception, asyncio.CancelledError) as exc:
                self.failed = True
                errors.append(exc)
                failure(__name__, operation, exc)

        async def stop_fees():
            if not await self.selected_fees.stop('selected_fee_runtime_closing'):
                raise OSError('selected_fee_cleanup_unresolved')

        if self.selected_fees:
            await attempt('data_runtime_finite_close', stop_fees)
            if errors:self.service.cleanup_errors.append('selected_fee_cleanup_unresolved')
        for task in (self.heartbeat_task, self.command_task):
            if task and task is not asyncio.current_task():
                # Cancellation we request is normal; an already failed task is
                # still observed and cannot skip source/resource shutdown.
                task.cancel()
                async def join(task=task):
                    try:await task
                    except asyncio.CancelledError:pass
                await attempt('data_runtime_task_close', join)
        if self.service is not None:
            if self.store:
                await attempt('data_runtime_stopping_status', lambda: self.persist_control('stopping'))
            # Revoke dispatch even when startup failed before store construction.
            await attempt('data_runtime_source_close', self.service.close)
            if getattr(self.service, 'cleanup_errors', None):self.failed = True
            for worker in (self.board, self.scanner):
                if worker:await attempt('data_runtime_worker_close', worker.close)
            if self.store:
                await attempt('data_runtime_store_close', self.store.close)
                await attempt('data_runtime_terminal_status', lambda: self.persist_control('failed' if self.failed else 'stopped'))
        if self.lock_connection is not None:
            await attempt('data_runtime_database_close', self.lock_connection.close)
            self.lock_connection = None
        await attempt('data_runtime_owner_release', self.owner.release)
        if errors:raise errors[0]


async def run(config_path=None):
    from app.storage.latest_board import LatestBoardOwner
    runtime = DataRuntime(config_path=config_path, board_factory=LatestBoardOwner)
    loop = asyncio.get_running_loop()
    for name in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(name, runtime.stopping.set)
    await runtime.start()
    try:
        await runtime.stopping.wait()
    finally:
        await runtime.close()
    return 1 if runtime.failed else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--current-config', help='Existing bounded source configuration')
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.current_config))
    except Exception as exc:
        # The process boundary must not print credential-bearing exception text.
        failure(__name__, 'data_runtime_process', exc)
        raise SystemExit(1) from None
    raise SystemExit(result)


if __name__ == '__main__':
    main()
