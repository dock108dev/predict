"""DA01 fixture-only read/lifecycle guards. No credentials or provider requests."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.collection.current_policy import DEFAULT
from app.collection.current_service import CurrentService
from app.collection.local_ownership import LocalOwnership
from app.collection.runtime_client import RuntimeClient
from app.collection.runtime_status import HEARTBEAT_SECONDS, read_runtime
from app.dashboard.current_state import CurrentStore
from tests.test_current_service import FakeWorker


AT = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def runtime_row(**updates):
    row = dict(runtime_id='fixture-runtime', owner_pid=123, state='running', dispatch=True,
               heartbeat_at=AT, config=deepcopy(DEFAULT), source_status={
                   'kalshi': dict(state='available', source_at='2026-10-16T11:59:00+00:00',
                                  received_at='2026-10-16T11:59:02+00:00')},
               revision=4, status=dict(sources=[]), paused_sources=[], global_stopped=False)
    row.update(updates)
    return row


class RuntimeReadGuards(unittest.TestCase):
    def test_runtime_still_refuses_the_operating_disk_floor_and_sql_cap(self):
        from types import SimpleNamespace
        from app.collection.data_runtime import DataRuntime
        from app.collection.odds_http import BudgetStop
        from app.collection.current_storage_policy import FREE_DISK_BYTE_FLOOR, SQL_BYTE_CAP
        runtime=DataRuntime(service=SimpleNamespace(config=deepcopy(DEFAULT)))
        runtime.lock_connection=Mock()
        with patch('app.collection.current_storage_policy.shutil.disk_usage',return_value=SimpleNamespace(free=FREE_DISK_BYTE_FLOOR-1)):
            with self.assertRaisesRegex(BudgetStop,'current_observation_disk_free_floor'):
                runtime.resource_guard()
        runtime.lock_connection.execute.assert_not_called()
        runtime.lock_connection.execute.return_value.fetchone.return_value={'n':SQL_BYTE_CAP}
        with patch('app.collection.current_storage_policy.shutil.disk_usage',return_value=SimpleNamespace(free=FREE_DISK_BYTE_FLOOR*2)):
            with self.assertRaisesRegex(ValueError,'data_runtime_sql_storage_guard'):
                runtime.resource_guard()

    def read(self, row, at=AT):
        db = Mock()
        db.execute.return_value.fetchone.return_value = row
        return read_runtime(db, at)

    def test_heartbeat_does_not_refresh_source_clock(self):
        value = self.read(runtime_row())
        self.assertTrue(value['active'])
        self.assertEqual(value['states']['kalshi']['source_at'], '2026-10-16T11:59:00+00:00')

    def test_dead_future_and_stopped_runtime_fail_closed(self):
        for row in (runtime_row(heartbeat_at=AT-timedelta(seconds=HEARTBEAT_SECONDS+1)),
                    runtime_row(heartbeat_at=AT+timedelta(seconds=1)),
                    runtime_row(state='stopped'), runtime_row(state='failed')):
            value = self.read(row)
            self.assertFalse(value['healthy'])
            self.assertFalse(value['dispatch'])
            self.assertFalse(value['active'])
            self.assertEqual(value['states']['kalshi']['reason_code'], 'data_runtime_unhealthy')
            self.assertEqual(value['states']['kalshi']['source_at'], '2026-10-16T11:59:00+00:00')

    def test_expired_runtime_revokes_sync_without_rewriting_retained_clocks(self):
        status=dict(sources=[dict(provider='kalshi',metrics=dict(synchronization=dict(
            state='synchronized',continuity_intact=True,generation=2)))])
        value=self.read(runtime_row(status=status,heartbeat_at=AT-timedelta(seconds=9)))
        self.assertEqual(value['status']['sources'][0]['metrics']['synchronization']['state'],'disconnected')
        self.assertEqual(status['sources'][0]['metrics']['synchronization']['state'],'synchronized')

    def test_missing_runtime_is_unavailable(self):
        value = self.read(None)
        self.assertFalse(value['active'])
        self.assertEqual(value['revision'], 0)

    def test_live_heartbeat_does_not_pass_health_when_enabled_dispatch_is_blocked(self):
        from runpy import run_path
        from app.collection.runtime_status import source_states

        health = run_path('deploy/check-health.py')['collector_health']
        blocked = self.read(runtime_row(dispatch=False, paused_sources=['polymarket_us']))
        stopped = self.read(runtime_row(dispatch=False, global_stopped=True))
        disabled = self.read(runtime_row(dispatch=False, config=dict(DEFAULT, enabled=False)))
        self.assertTrue(blocked['healthy'])
        self.assertEqual(blocked['reason_code'], 'data_runtime_not_dispatching')
        self.assertEqual(source_states({}, blocked)['kalshi']['state'], 'unavailable')
        self.assertEqual(source_states({}, stopped)['kalshi']['state'], 'stopped')
        self.assertIsNone(disabled['reason_code'])
        running=self.read(runtime_row(dispatch=True))
        with patch('app.storage.store.connect') as connection:
            sql=connection.return_value.__enter__.return_value.execute
            for runtime, pending_failure, expected in (
                (blocked,None,False), (stopped,None,True), (disabled,None,True),
                (running,None,True), (running,{'error':'game_calculation_failed'},False),
                (dict(running,healthy=False),None,False),
            ):
                with self.subTest(expected=expected,failure=pending_failure):
                    summary=dict(state=runtime['service_state'],dispatch=runtime['active'],
                        global_stopped=runtime['global_stopped'],enabled=runtime['config']['enabled'],
                        healthy=runtime['healthy'])
                    early=not summary['healthy'] or summary['global_stopped'] or not summary['enabled']
                    sql.return_value.fetchone.side_effect=[summary] if early else [summary,pending_failure]
                    self.assertEqual(health(),expected)
                    self.assertFalse(any('pregame_unit' in str(call) for call in sql.call_args_list))

    def test_postgres_local_offset_heartbeat_is_returned_as_utc(self):
        value = self.read(runtime_row(heartbeat_at=AT.astimezone(timezone(timedelta(hours=-4)))))
        self.assertEqual(value['heartbeat_at'], '2026-10-16T12:00:00+00:00')
        self.assertTrue(value['active'])


class IsolatedRuntimeClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Unit fixtures must never fall through to the ordinary owner configuration.
        config = patch('app.collection.runtime_client.load', return_value=deepcopy(DEFAULT))
        config.start()
        self.addCleanup(config.stop)


class AppLifecycle(IsolatedRuntimeClient):
    async def test_app_start_and_close_never_send_collection_control(self):
        client = RuntimeClient()
        client.state = Mock()
        store = object()
        await client.start(store)
        await client.close()
        self.assertIs(client.store, store)
        self.assertTrue(client.closed)
        client.state.submit.assert_not_called()
        client.state.write.assert_not_called()

    async def test_explicit_stop_waits_for_owner_acknowledgment(self):
        client = RuntimeClient()
        client.state = Mock()
        client.state.read.return_value = dict(runtime_id='runtime', healthy=True)
        client.state.submit.return_value = 'control'
        client.state.result.return_value = dict(state='acknowledged', acknowledgment=dict(acknowledged=True))
        self.assertTrue((await client.stop())['acknowledged'])
        client.state.submit.assert_called_once_with('runtime', 'stop', {})
        client.state.result.assert_called_with('control')

    async def test_explicit_stop_reports_owner_failure(self):
        from app.dashboard.current_state import SelectionError
        client = RuntimeClient()
        client.state = Mock()
        client.state.read.return_value = dict(runtime_id='runtime', healthy=True)
        client.state.submit.return_value = 'control'
        client.state.result.return_value = dict(state='failed', acknowledgment=dict(error='cleanup_safety_unresolved', reason='Cleanup unresolved.'))
        with self.assertRaises(SelectionError) as result:
            await client.stop()
        self.assertEqual(result.exception.body['error'], 'cleanup_safety_unresolved')


class PersistedStopGates(unittest.IsolatedAsyncioTestCase):
    async def test_watchdog_publication_failure_requires_confirmed_stop_retry(self):
        import asyncio
        from app.collection.data_runtime import DataRuntime
        from app.dashboard.current_state import SelectionError

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = CurrentService(config=dict(DEFAULT, aggregate_enabled=False),
                directory=root/'state', ownership=LocalOwnership(root/'owner'), worker_factory=FakeWorker)
            store = CurrentStore(service)
            runtime = DataRuntime(service=service)
            runtime.persist_control = unittest.mock.AsyncMock()
            release_client = asyncio.Event()
            await service.start(store)
            service.config['cleanup_seconds'] = .02
            worker = service.workers['kalshi']
            close_client = worker.close

            async def pending_client():
                await release_client.wait()
                await close_client()

            worker.close = pending_client
            admission_close = store.admission.close
            try:
                with patch.object(store.admission, 'close', side_effect=OSError('CONTROLLED publication secret')):
                    service.config['rss_bytes'] = 1
                    await asyncio.wait_for(asyncio.shield(service.watchdog), timeout=2)
                    self.assertFalse(service.dispatch)
                    self.assertTrue(store._source_stopping)
                    self.assertTrue(store.comparison_jobs.closed)
                    self.assertTrue(all(task.done() for task in service.tasks.values()))
                    self.assertEqual(service.workers['polymarket_us'].close_count, 1)
                    self.assertIn('source_publication_cleanup_failed', service.cleanup_errors)
                    self.assertFalse(service.client_cleanup_tasks['kalshi'].done())
                    with self.assertRaises(SelectionError) as result:
                        await runtime.control('stop', {})
                    self.assertEqual(result.exception.body['error'], 'cleanup_safety_unresolved')
                    self.assertNotIn('secret', str(service.cleanup_errors))
                    self.assertTrue(runtime.global_stopped)
                    self.assertFalse(service.cleanup_complete)
                    with self.assertRaisesRegex(ValueError, 'owns native acquisition'):
                        LocalOwnership(root/'owner').acquire('competitor')

                # A healed publication path alone still cannot release a live client.
                self.assertIs(store.admission.close.__func__, admission_close.__func__)
                with self.assertRaises(SelectionError):
                    await runtime.control('stop', {})
                self.assertEqual(service.cleanup_errors, ['client_cleanup_timeout'])
                self.assertIsNotNone(service.ownership.file)
                release_client.set()
                await runtime.control('stop', {})
                self.assertTrue(service.cleanup_complete)
                self.assertFalse(service.dispatch)
                self.assertIsNone(service.ownership.file)
                self.assertEqual([w.close_count for w in service.workers.values()], [1, 1])
                self.assertTrue(all(t.done() for t in service.client_cleanup_tasks.values()))
                rival = LocalOwnership(root/'owner')
                rival.acquire('after-confirmed-close')
                rival.release()
            finally:
                release_client.set()
                await store.close()
                service.ownership.release()

    async def test_stop_revokes_running_workers_despite_existing_cleanup_issue(self):
        from app.collection.data_runtime import DataRuntime
        from app.dashboard.current_state import SelectionError
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = CurrentService(config=dict(DEFAULT, aggregate_enabled=False),
                directory=root/'state', ownership=LocalOwnership(root/'owner'), worker_factory=FakeWorker)
            store = CurrentStore(service)
            runtime = DataRuntime(service=service)
            runtime.persist_control = unittest.mock.AsyncMock()
            try:
                await service.start(store)
                await __import__('asyncio').sleep(0)
                service.cleanup_errors = ['earlier_source_cleanup_unresolved']
                with self.assertRaises(SelectionError) as result:
                    await runtime.control('stop', {})
                self.assertEqual(result.exception.body['error'], 'cleanup_safety_unresolved')
                self.assertFalse(service.dispatch)
                self.assertTrue(all(worker.closed for worker in service.workers.values()))
                self.assertTrue(all(task.done() for task in service.tasks.values()))
                self.assertEqual(service.cleanup_errors, ['earlier_source_cleanup_unresolved'])
                runtime.persist_control.assert_awaited_with('stopping')
            finally:
                await store.close()
                service.ownership.release()

    async def test_stop_retries_timed_out_pause_cleanup_and_keeps_pause_choice(self):
        import asyncio
        from app.collection.data_runtime import DataRuntime
        from app.dashboard.current_state import SelectionError

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = CurrentService(config=dict(DEFAULT, aggregate_enabled=False),
                directory=root/'state', ownership=LocalOwnership(root/'owner'), worker_factory=FakeWorker)
            store = CurrentStore(service)
            runtime = DataRuntime(service=service)
            runtime.persist_control = unittest.mock.AsyncMock()
            release_client = asyncio.Event()
            await service.start(store)
            service.config['cleanup_seconds'] = .02
            worker = service.workers['kalshi']
            close_client = worker.close

            async def pending_client():
                await release_client.wait()
                await close_client()

            worker.close = pending_client
            try:
                with self.assertRaises(SelectionError) as pause:
                    await runtime.control('pause', {'source': 'kalshi'})
                self.assertEqual(pause.exception.body['error'], 'cleanup_safety_unresolved')
                self.assertEqual(set(service.cleanup_errors), {'client_cleanup_timeout', 'kalshi:cleanup_failure'})
                self.assertEqual(runtime.paused_sources, {'kalshi'})
                self.assertTrue(service.dispatch)

                with self.assertRaises(SelectionError) as stop:
                    await runtime.control('stop', {})
                self.assertEqual(stop.exception.body['error'], 'cleanup_safety_unresolved')
                self.assertFalse(service.dispatch)
                self.assertIsNotNone(service.ownership.file)
                self.assertEqual(service.workers['polymarket_us'].close_count, 1)

                release_client.set()
                await runtime.control('stop', {})
                self.assertTrue(service.cleanup_complete)
                self.assertEqual(service.cleanup_errors, [])
                self.assertEqual(worker.close_count, 1)
                self.assertIsNone(service.ownership.file)
                self.assertTrue(runtime.global_stopped)
                self.assertEqual(runtime.paused_sources, {'kalshi'})
                self.assertEqual(service.paused_sources, {'kalshi'})
            finally:
                release_client.set()
                await store.close()
                service.ownership.release()

    async def test_terminal_close_keeps_runtime_authorities_until_source_resources_close(self):
        import asyncio
        from app.collection.data_runtime import DataRuntime

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = CurrentService(config=dict(DEFAULT, aggregate_enabled=False),
                directory=root/'state', ownership=LocalOwnership(root/'source'), worker_factory=FakeWorker)
            runtime = DataRuntime(service=service, owner=LocalOwnership(root/'runtime'))
            runtime.owner.acquire('terminal-close-fixture')
            runtime.lock_connection = connection = Mock()
            runtime.persist_control = unittest.mock.AsyncMock()
            runtime.store = CurrentStore(service)
            await service.start(runtime.store)
            service.config['cleanup_seconds'] = .001
            release = asyncio.Event()
            service.workers['kalshi'].close = release.wait
            try:
                with self.assertRaisesRegex(RuntimeError, 'data_runtime_source_cleanup_unresolved'):
                    await runtime.close()
                self.assertFalse(service.dispatch)
                self.assertIsNotNone(service.ownership.file)
                self.assertIsNotNone(runtime.owner.file)
                connection.close.assert_not_called()
                release.set()
                await runtime.close()
                self.assertTrue(service.cleanup_complete)
                self.assertIsNone(service.ownership.file)
                self.assertIsNone(runtime.owner.file)
                connection.close.assert_called_once()
            finally:
                release.set()
                service.ownership.release()
                runtime.owner.release()

    async def test_source_pause_survives_new_service(self):
        FakeWorker.starts = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = CurrentService(config=dict(DEFAULT, aggregate_enabled=False),
                directory=root/'state', ownership=LocalOwnership(root/'owner'),
                worker_factory=FakeWorker, paused_sources={'kalshi'})
            store = CurrentStore(service)
            try:
                await service.start(store)
                await __import__('asyncio').sleep(0)
                self.assertEqual(FakeWorker.starts, ['polymarket_us'])
                self.assertEqual(service.states['kalshi']['state'], 'stopped')
            finally:
                await store.close()

    async def test_global_stop_does_not_consume_or_dispatch_on_restart(self):
        service = CurrentService(config=dict(DEFAULT, aggregate_enabled=False), globally_stopped=True,
                                 worker_factory=FakeWorker)
        store = CurrentStore(service)
        try:
            with patch('app.collection.current_service.consume') as consume:
                await service.start(store)
            consume.assert_not_called()
            self.assertFalse(service.dispatch)
            self.assertEqual(service.workers, {})
            self.assertEqual(service.states['kalshi']['state'], 'stopped')
        finally:
            await store.close()


class CalculationIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_worker_backs_off_after_failure_despite_ingress_wakes(self):
        import asyncio
        from types import SimpleNamespace
        from app.storage import ordinary_owner

        owner = ordinary_owner.OrdinaryOwner(SimpleNamespace(config={'cleanup_seconds': 2}))
        loop = asyncio.get_running_loop()
        attempts = []
        delay = .05

        async def run(stopped, **options):
            attempts.append(loop.time())
            if len(attempts) == 1:
                owner.wake.set()
                loop.call_soon(owner.wake.set)
                loop.call_later(delay / 4, owner.wake.set)
                raise RuntimeError('fixture publication failure')
            owner.closed = True
            return {'published': True}

        with patch.object(ordinary_owner, 'TURN_INTERVAL_SECONDS', delay), \
             patch.object(ordinary_owner, 'run', side_effect=run):
            await asyncio.wait_for(owner.run_ordinary(), timeout=2)
        self.assertEqual(len(attempts), 2)
        self.assertGreaterEqual(attempts[1] - attempts[0], delay)
        self.assertIsNone(owner.error)
        self.assertEqual(owner.progress['ordinary']['published'], True)

    async def test_ordinary_worker_can_close_during_retry_delay(self):
        import asyncio
        from types import SimpleNamespace
        from app.storage import ordinary_owner

        owner = ordinary_owner.OrdinaryOwner(SimpleNamespace(config={'cleanup_seconds': 2}))
        failed = asyncio.Event()

        async def run(stopped, **options):
            failed.set()
            raise RuntimeError('fixture publication failure')

        with patch.object(ordinary_owner, 'TURN_INTERVAL_SECONDS', 60), \
             patch.object(ordinary_owner, 'run', side_effect=run) as worker:
            owner.task = asyncio.create_task(owner.run_ordinary())
            try:
                await asyncio.wait_for(failed.wait(), timeout=2)
            finally:
                await owner.close()
            worker.assert_awaited_once()

    async def test_ordinary_publisher_runs_on_admission_with_no_web_process(self):
        import asyncio
        from types import SimpleNamespace
        from app.storage.ordinary_owner import OrdinaryOwner

        turns = asyncio.Queue()

        async def run(stopped, *, root, module=None, **options):
            if module == 'app.collection.ordinary_worker':
                turns.put_nowait('published')
            return {'published': True}

        service = SimpleNamespace(ingress=SimpleNamespace(), config={'cleanup_seconds': 2})
        publisher = OrdinaryOwner(service)
        with patch('app.storage.ordinary_owner.run', side_effect=run):
            await publisher.start()
            try:
                self.assertEqual(await asyncio.wait_for(turns.get(), .5), 'published')
                service.ingress.on_native_admitted()
                self.assertEqual(await asyncio.wait_for(turns.get(), .5), 'published')
            finally:
                await publisher.close()

    async def test_slow_accounting_projection_does_not_block_source_loop(self):
        import asyncio
        from threading import Event
        from types import SimpleNamespace
        from app.collection.data_runtime import DataRuntime
        entered=Event();release=Event()
        def accounting():
            entered.set();release.wait(2)
            return {'quota':None,'recovery_reason':None}
        runtime=DataRuntime(service=SimpleNamespace(status_accounting=accounting,background_calculations={}))
        runtime.state=Mock()
        task=asyncio.create_task(runtime.persist_heartbeat())
        try:
            while not entered.is_set():await asyncio.sleep(.001)
            self.assertFalse(task.done())
            runtime.state.snapshot.assert_not_called()
        finally:
            release.set();await task
        self.assertEqual(runtime.state.snapshot.call_args.kwargs['accounting'],{'quota':None,'recovery_reason':None})

    async def test_busy_heartbeat_write_yields_to_source_and_does_not_stop_owner(self):
        import asyncio
        from threading import Event
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.collection.data_runtime import DataRuntime
        entered=Event();release=Event();source_progress=[]
        runtime=DataRuntime(service=SimpleNamespace(runtime_id='runtime',close=AsyncMock(),background_calculations={},status_accounting=lambda:{}))
        runtime.lock_connection=Mock();runtime.resource_guard=Mock();runtime.state=Mock()
        def busy(*args,**kwargs):
            entered.set();release.wait(2)
            return False
        runtime.state.write_snapshot.side_effect=busy
        task=asyncio.create_task(runtime.heartbeat())
        try:
            while not entered.is_set():await asyncio.sleep(.001)
            # Status can be busy while the liveness write and sources proceed.
            while runtime.state.renew_heartbeat.call_count < 2:await asyncio.sleep(.001)
            source_progress.append('complete image committed')
            self.assertFalse(task.done())
            runtime.stopping.set();release.set();await task
            self.assertEqual(source_progress,['complete image committed'])
            self.assertFalse(runtime.failed)
            runtime.service.close.assert_not_awaited()
            runtime.state.write_snapshot.assert_called_once()
        finally:
            release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_failed_calculation_task_does_not_stop_healthy_collection(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.collection.data_runtime import DataRuntime
        async def fail():raise RuntimeError('authored calculation failure')
        task=asyncio.create_task(fail())
        await asyncio.sleep(0)
        service=SimpleNamespace(runtime_id='runtime',close=AsyncMock(),background_calculations={},status_accounting=lambda:{})
        runtime=DataRuntime(service=service)
        runtime.lock_connection=Mock();runtime.resource_guard=Mock();runtime.state=Mock()
        runtime.board=SimpleNamespace(task=task,error=None)
        loop=asyncio.get_running_loop()
        def written(*args,**kwargs):loop.call_soon_threadsafe(runtime.stopping.set)
        runtime.state.write_snapshot.side_effect=written
        await runtime.heartbeat()
        service.close.assert_not_awaited()
        self.assertFalse(runtime.failed)
        self.assertEqual(service.background_calculations['board'],'unavailable')
        self.assertEqual(runtime.board.error,'background_calculation_worker_stopped')


class RuntimeFailureHandling(IsolatedRuntimeClient):
    def runtime(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.collection.data_runtime import DataRuntime
        service=SimpleNamespace(close=AsyncMock(),cleanup_errors=[])
        runtime=DataRuntime(service=service,owner=Mock())
        runtime.store=SimpleNamespace(close=AsyncMock())
        runtime.lock_connection=Mock()
        runtime.persist_control=AsyncMock()
        return runtime

    async def test_shutdown_attempts_remaining_resources_after_worker_and_database_failure(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        runtime=self.runtime();db=runtime.lock_connection
        original=OSError('SECRET worker')
        runtime.board=SimpleNamespace(close=AsyncMock(side_effect=original))
        runtime.scanner=SimpleNamespace(close=AsyncMock())
        db.close.side_effect=RuntimeError('SECRET database')
        with self.assertLogs('app.collection.data_runtime',level='ERROR') as logs:
            with self.assertRaises(OSError) as caught:await runtime.close()
        self.assertIs(caught.exception,original)
        runtime.service.close.assert_awaited_once()
        runtime.scanner.close.assert_awaited_once()
        runtime.store.close.assert_awaited_once()
        runtime.owner.release.assert_called_once()
        self.assertTrue(runtime.failed)
        self.assertIn(unittest.mock.call('failed'),runtime.persist_control.call_args_list)
        self.assertNotIn('SECRET',' '.join(logs.output))

    async def test_startup_primary_survives_secondary_cleanup_failure(self):
        from unittest.mock import AsyncMock
        from app.collection.data_runtime import DataRuntime
        original=OSError('SECRET startup')
        runtime=DataRuntime(connector=Mock(side_effect=original),owner=Mock())
        runtime.close=AsyncMock(side_effect=RuntimeError('SECRET cleanup'))
        with self.assertLogs('app.collection.data_runtime',level='ERROR') as logs:
            with self.assertRaises(OSError) as caught:await runtime.start()
        self.assertIs(caught.exception,original)
        self.assertNotIn('SECRET',' '.join(logs.output))

    async def test_cancelled_resource_close_does_not_skip_later_cleanup(self):
        import asyncio
        runtime=self.runtime()
        runtime.service.close.side_effect=asyncio.CancelledError()
        with self.assertLogs('app.collection.data_runtime',level='ERROR'):
            with self.assertRaises(asyncio.CancelledError):await runtime.close()
        runtime.store.close.assert_awaited_once()
        runtime.owner.release.assert_called_once()
        self.assertTrue(runtime.failed)

    async def test_failed_heartbeat_logs_and_stops_even_when_status_write_fails(self):
        runtime=self.runtime()
        runtime.lock_connection.execute.side_effect=OSError('SECRET heartbeat')
        runtime.persist_control.side_effect=OSError('SECRET persistence')
        with self.assertLogs('app.collection.data_runtime',level='ERROR') as logs:
            await runtime.heartbeat()
        self.assertTrue(runtime.failed)
        self.assertTrue(runtime.stopping.is_set())
        runtime.service.close.assert_awaited_once()
        self.assertNotIn('SECRET',' '.join(logs.output))

    async def test_source_resource_shutdown_exits_for_process_supervisor(self):
        runtime = self.runtime()
        runtime.service.closed = True
        runtime.service.stop_reason = 'resource guard stopped acquisition'
        with self.assertLogs('app.collection.data_runtime', level='ERROR'):
            await runtime.heartbeat()
        self.assertTrue(runtime.failed)
        self.assertTrue(runtime.stopping.is_set())
        runtime.persist_control.assert_awaited_once_with('stopping')
        runtime.service.close.assert_awaited_once()

    async def test_estimate_and_coverage_task_deaths_are_detected(self):
        import asyncio
        from types import SimpleNamespace
        from app.collection.data_runtime import DataRuntime
        async def fail():raise OSError('SECRET background')
        tasks=[asyncio.create_task(fail()) for _ in range(2)]
        await asyncio.sleep(0)
        runtime=DataRuntime(service=SimpleNamespace(runtime_id='runtime',background_calculations={},status_accounting=lambda:{}))
        runtime.board=SimpleNamespace(task=None,estimate_task=tasks[0],coverage_task=tasks[1],error=None)
        runtime.lock_connection=Mock();runtime.resource_guard=Mock();runtime.state=Mock()
        loop=asyncio.get_running_loop()
        runtime.state.write_snapshot.side_effect=lambda *a,**kw:loop.call_soon_threadsafe(runtime.stopping.set)
        with self.assertLogs('app.collection.data_runtime',level='ERROR') as logs:
            await runtime.heartbeat()
        self.assertEqual(runtime.service.background_calculations['coverage'],'unavailable')
        self.assertEqual(runtime.service.background_calculations['board'],'unavailable')
        self.assertFalse(runtime.failed)
        self.assertNotIn('SECRET',' '.join(logs.output))

    def test_process_boundary_does_not_print_raw_error(self):
        from app.collection.data_runtime import main
        def failed_run(coroutine):
            coroutine.close()
            raise OSError('SECRET startup')
        with patch('sys.argv',['data_runtime']),patch('asyncio.run',side_effect=failed_run):
            with self.assertLogs('app.collection.data_runtime',level='ERROR') as logs:
                with self.assertRaises(SystemExit) as caught:main()
        self.assertEqual(caught.exception.code,1)
        self.assertNotIn('SECRET',' '.join(logs.output))

    async def test_control_ack_read_failure_has_unknown_outcome_and_no_resubmit(self):
        client=RuntimeClient();client.state=Mock()
        client.state.read.return_value=dict(runtime_id='runtime')
        client.state.submit.return_value='command'
        client.state.result.side_effect=OSError('SECRET ack')
        from app.dashboard.current_state import SelectionError
        with self.assertLogs('app.collection.runtime_client',level='ERROR') as logs:
            with self.assertRaises(SelectionError) as caught:await client.stop()
        self.assertEqual(caught.exception.body['error'],'data_runtime_control_unknown')
        client.state.submit.assert_called_once()
        self.assertNotIn('SECRET',' '.join(logs.output)+str(caught.exception.body))


if __name__ == '__main__':
    unittest.main()


def test_loop_profile_snapshot_survives_concurrent_new_stack_keys():
    import threading
    from app.collection.loop_progress import LoopProgress
    progress=LoopProgress();done=threading.Event()
    def record():
        for n in range(10000):
            progress.profile[(str(n),)]+=1
            progress.thread_profile[('worker',str(n))]+=1
        done.set()
    thread=threading.Thread(target=record);thread.start()
    try:
        while not done.is_set():
            snapshot=progress.snapshot()
            assert len(snapshot['sampled_stacks'])<=24
            assert len(snapshot['sampled_threads'])<=32
    finally:thread.join()
    assert progress.snapshot()['sampled_stacks']


def test_missing_images_and_replaceable_tails_do_not_veto_current_work():
    from types import SimpleNamespace
    from app.collection.data_runtime import DataRuntime
    metrics=dict(selected_markets=10,initial_images=10,stream_connected=True,derived_oldest_pending_seconds=6)
    worker=SimpleNamespace(closed=False,failed=False,metrics=metrics)
    runtime=DataRuntime.__new__(DataRuntime)
    runtime.service=SimpleNamespace(dispatch=True,workers={'kalshi':worker},paused_sources=set())
    assert not runtime.acquisition_pressure()
    assert not runtime.acquisition_pressure(critical=True)
    metrics['derived_oldest_pending_seconds']=3
    assert not runtime.acquisition_pressure()
    metrics['initial_images']=0
    metrics['raw_oldest_pending_seconds']=300
    assert not runtime.acquisition_pressure(critical=True)
    metrics['raw_oldest_pending_seconds']=0
    metrics['receive_oldest_seconds']=3
    assert not runtime.acquisition_pressure(critical=True)
    metrics['receive_buffer_bytes']=20*1024*1024
    assert runtime.acquisition_pressure()
    assert not runtime.acquisition_pressure(critical=True)
    metrics['receive_buffer_bytes']=25*1024*1024
    assert runtime.acquisition_pressure(critical=True)
    runtime.service.paused_sources={'kalshi'}
    assert not runtime.acquisition_pressure()


def test_active_sgo_admission_defers_research_until_current_rows_finish():
    from types import SimpleNamespace
    from app.collection.data_runtime import DataRuntime
    runtime=DataRuntime.__new__(DataRuntime)
    ingress=SimpleNamespace(tasks={'accepted-sgo-page':object()})
    runtime.service=SimpleNamespace(dispatch=True,workers={},paused_sources=set(),ingress=ingress)
    assert runtime.acquisition_pressure()
    assert runtime.acquisition_pressure(critical=True)
    ingress.tasks.clear()
    assert not runtime.acquisition_pressure()
    assert not runtime.acquisition_pressure(critical=True)


def test_native_restore_defers_optional_work_until_the_source_can_stream():
    from types import SimpleNamespace
    from app.collection.data_runtime import DataRuntime
    worker = SimpleNamespace(closed=False, failed=False, metrics={'restoration': {'stage': 'admitting_saved_catalog'}})
    task = Mock()
    task.done.return_value = False
    runtime = DataRuntime.__new__(DataRuntime)
    runtime.service = SimpleNamespace(dispatch=True, workers={'polymarket_us': worker},
                                      tasks={'polymarket_us': task}, paused_sources=set())
    assert runtime.acquisition_pressure()
    assert not runtime.acquisition_pressure(critical=True)
    task.done.return_value = True
    assert not runtime.acquisition_pressure()
    task.done.return_value = False
    worker.metrics['restoration']['stage'] = 'complete'
    assert not runtime.acquisition_pressure()


def test_storage_interval_requires_measured_deferred_work_near_guard():
    from app.collection.data_runtime import needs_storage_interval
    from app.collection.current_storage_policy import SQL_BYTE_CAP, MIB
    report=dict(after_bytes=SQL_BYTE_CAP-192*MIB,deferred=[dict(reason='rewrite_headroom',reusable_bytes=32*MIB)])
    assert needs_storage_interval(report)
    assert not needs_storage_interval(dict(report,after_bytes=report['after_bytes']-1))
    assert not needs_storage_interval(dict(report,deferred=[dict(reason='lock_timeout')]))
    assert not needs_storage_interval(dict(state='busy'))
    assert needs_storage_interval(dict(state='busy'),sql_bytes=SQL_BYTE_CAP-128*MIB)
    assert not needs_storage_interval(dict(state='busy'),sql_bytes=SQL_BYTE_CAP-128*MIB-1)


def test_hosted_ceiling_keeps_early_maintenance_without_restarting_at_old_ceiling():
    import os
    import subprocess
    import sys

    subprocess.run([sys.executable, '-c', '''
from app.collection.current_storage_policy import GIB, MIB, SQL_BYTE_CAP
from app.collection.data_runtime import needs_storage_interval
from app.storage.storage_maintenance import PRESSURE_BYTES

assert SQL_BYTE_CAP == 4 * GIB
assert PRESSURE_BYTES == (2 * GIB) * 3 // 5
assert not needs_storage_interval({'state': 'busy'}, sql_bytes=2 * GIB)
assert needs_storage_interval({'state': 'busy'}, sql_bytes=SQL_BYTE_CAP - 128 * MIB)
'''], env=dict(os.environ, PREDICT_DATABASE_CAP_GIB='4'), check=True)
