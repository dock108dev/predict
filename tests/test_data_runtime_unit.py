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

    def test_missing_runtime_is_unavailable(self):
        value = self.read(None)
        self.assertFalse(value['active'])
        self.assertEqual(value['revision'], 0)

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
                runtime.persist_control.assert_awaited_with('stopping')
            finally:
                await store.close()
                service.ownership.release()

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
    async def test_busy_heartbeat_write_yields_to_source_and_does_not_stop_owner(self):
        import asyncio
        from threading import Event
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.collection.data_runtime import DataRuntime
        entered=Event();release=Event();source_progress=[]
        runtime=DataRuntime(service=SimpleNamespace(close=AsyncMock(),background_calculations={}))
        runtime.lock_connection=Mock();runtime.resource_guard=Mock();runtime.state=Mock()
        def busy(*args,**kwargs):
            entered.set();release.wait(2)
            return False
        runtime.state.write_snapshot.side_effect=busy
        task=asyncio.create_task(runtime.heartbeat())
        try:
            while not entered.is_set():await asyncio.sleep(.001)
            # A normal source turn can run while SQL publication holds authority.
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
        service=SimpleNamespace(close=AsyncMock(),background_calculations={})
        runtime=DataRuntime(service=service)
        runtime.lock_connection=Mock();runtime.resource_guard=Mock();runtime.state=Mock()
        runtime.board=SimpleNamespace(task=task,error=None)
        def written(*args,**kwargs):runtime.stopping.set()
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

    async def test_estimate_and_coverage_task_deaths_are_detected(self):
        import asyncio
        from types import SimpleNamespace
        from app.collection.data_runtime import DataRuntime
        async def fail():raise OSError('SECRET background')
        tasks=[asyncio.create_task(fail()) for _ in range(2)]
        await asyncio.sleep(0)
        runtime=DataRuntime(service=SimpleNamespace(background_calculations={}))
        runtime.board=SimpleNamespace(task=None,estimate_task=tasks[0],coverage_task=tasks[1],error=None)
        runtime.lock_connection=Mock();runtime.resource_guard=Mock();runtime.state=Mock()
        runtime.state.write_snapshot.side_effect=lambda *a,**kw:runtime.stopping.set()
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
