"""Offline failure injection; temporary state and no provider operations."""
import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiohttp.test_utils import AioHTTPTestCase
from app.collection.continuous import ContinuousSession
from app.dashboard.multi_game_server import create_app
from app.reference.refresh import Refresh
from app.adapters.novig_stream import MarketStream
from tests.segmented_collector_fixture import Fixture


class ResourceMonitor(unittest.IsolatedAsyncioTestCase):
    async def test_failure_stops_collection_and_rejects_both_manifest_modes(self):
        for segmented in (False, True):
            with self.subTest(segmented=segmented), tempfile.TemporaryDirectory() as tmp:
                trigger = asyncio.Event()
                async def broken_monitor(session):
                    await trigger.wait()
                    raise OSError('SECRET disk check')
                fixture = Fixture()
                with patch.object(ContinuousSession, 'monitor', broken_monitor):
                    try:
                        owner = await fixture.start(tmp, product_mode=True, segmented=segmented)
                        with self.assertLogs(level='ERROR') as logs:
                            trigger.set()
                            await asyncio.wait_for(owner.finalizer, 10)
                        self.assertEqual(owner.session.monitor_error, 'OSError')
                        self.assertTrue(owner.session.intake_closed)
                        self.assertEqual(owner.status()['state'], 'failed')
                        self.assertIn('resource_monitor_failure', owner.session.reason)
                        self.assertFalse((owner.session.output/'manifest.json').exists())
                        self.assertIsNone(owner.owner_lock)
                        self.assertIn('resource_monitor', ' '.join(logs.output))
                        self.assertNotIn('SECRET', ' '.join(logs.output) + str(owner.status()))
                    finally:
                        await fixture.close()

    async def test_premature_monitor_exit_is_failure_but_stop_cancellation_is_normal(self):
        from app.collection.transport_session import TransportSession
        import time
        for outcome in ('return', 'cancel', 'stop'):
            early_exit = outcome != 'stop'
            with self.subTest(outcome=outcome):
                stop = asyncio.Event()
                session = object.__new__(ContinuousSession)
                session.stop_event = stop
                session.intake_closed = False
                session.started_monotonic = time.monotonic()
                session.state = 'running'
                session.request_stop = lambda reason: (setattr(session, 'reason', reason), stop.set())
                async def monitor():
                    if outcome == 'cancel':raise asyncio.CancelledError()
                    if not early_exit:await asyncio.Future()
                session.monitor = monitor
                async def run(self):
                    if early_exit:await stop.wait()
                    else:
                        await asyncio.sleep(0)
                        stop.set()
                    self.state = 'stopped'
                with patch.object(TransportSession, 'run', run):
                    if early_exit:
                        with self.assertLogs('app.collection.continuous', level='ERROR'):
                            await ContinuousSession.run(session)
                    else:await ContinuousSession.run(session)
                self.assertEqual(session.state, 'failed' if early_exit else 'stopped')
                expected = {'return':'RuntimeError', 'cancel':'CancelledError', 'stop':None}
                self.assertEqual(session.monitor_error, expected[outcome])


class ReferenceFailure(unittest.IsolatedAsyncioTestCase):
    async def test_primary_failure_and_cancellation_survive_report_failure(self):
        plan = dict(provider='the_odds_api', sport='americanfootball_nfl',
                    bookmakers='pinnacle', markets=['h2h'], oddsFormat='decimal', max_credits=1)
        for original in (OSError('SECRET transport'), asyncio.CancelledError()):
            with self.subTest(error=type(original).__name__):
                refresh = Refresh()
                retain = Mock(side_effect=[None, OSError('SECRET report')])
                with self.assertLogs('app.reference.refresh', level='ERROR') as logs:
                    with self.assertRaises(type(original)) as caught:
                        await refresh.acquire(plan, at='2026-10-01T12:00:00Z', approved=True,
                            transport=AsyncMock(side_effect=original), retain=retain)
                self.assertIs(caught.exception, original)
                self.assertTrue(refresh.stopped)
                self.assertEqual(refresh.credits, 1)
                self.assertEqual(refresh.ledger[0]['state'], 'failed')
                self.assertEqual(refresh.cache, {})
                self.assertNotIn('SECRET', ' '.join(logs.output))


class NovigCleanup(unittest.IsolatedAsyncioTestCase):
    async def test_primary_stream_failure_survives_failed_close(self):
        original = ValueError('SECRET frame')
        adapter = Mock(expires=1000, clock=Mock(return_value=0), refresh_locks=AsyncMock())
        stream = MarketStream(adapter, [], reconnects=0)
        stream._connect = AsyncMock(return_value=Mock(send=AsyncMock(),
            recv=AsyncMock(side_effect=original), close=AsyncMock(side_effect=OSError('SECRET close'))))
        with self.assertLogs('app.adapters.novig_stream', level='ERROR') as logs:
            with self.assertRaises(ValueError) as caught:await anext(stream.run())
        self.assertIs(caught.exception, original)
        self.assertEqual(stream.cleanup_errors, ['OSError'])
        self.assertNotIn('SECRET', ' '.join(logs.output))

    async def test_unsubscribe_failure_allows_confirmed_close(self):
        stream = MarketStream(Mock(), [])
        socket = Mock(send=AsyncMock(side_effect=OSError('SECRET unsubscribe')), close=AsyncMock())
        stream.ws = socket
        with self.assertLogs('app.adapters.novig_stream', level='ERROR') as logs:
            await stream.aclose()
        socket.close.assert_awaited_once()
        self.assertEqual(stream.cleanup_errors, [])
        self.assertNotIn('SECRET', ' '.join(logs.output))

    async def test_close_failure_remains_sticky_after_socket_detached(self):
        for error in (OSError('SECRET close'), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                stream = MarketStream(Mock(), [])
                stream.ws = Mock(send=AsyncMock(), close=AsyncMock(side_effect=error))
                with self.assertLogs('app.adapters.novig_stream', level='ERROR') as logs:
                    with self.assertRaises(OSError):await stream.aclose()
                self.assertTrue(stream.closed)
                self.assertIsNone(stream.ws)
                with self.assertRaises(OSError):await stream.aclose()
                self.assertEqual(stream.cleanup_errors, [type(error).__name__])
                self.assertNotIn('SECRET', ' '.join(logs.output))


class ArithmeticResponse(AioHTTPTestCase):
    async def get_application(self):
        self.owner = Mock()
        self.owner.session = None
        self.owner.close = AsyncMock()
        return create_app(owner=self.owner, sessions={})

    async def test_arithmetic_error_is_safe_and_logged(self):
        self.owner.status.side_effect = ZeroDivisionError('SECRET calculation')
        with self.assertLogs('app.dashboard.multi_game_server', level='ERROR') as logs:
            response = await self.client.get('/api/status')
        self.assertEqual(response.status, 422)
        self.assertNotIn('SECRET', await response.text() + ' '.join(logs.output))

    async def test_detached_history_failure_is_logged_and_releases_slot(self):
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        runtime_errors = []
        loop.set_exception_handler(lambda loop, context: runtime_errors.append(context))
        entered, release = threading.Event(), threading.Event()
        self.owner.history_paths.return_value = {'synthetic': Path('/unused')}
        self.owner.active.return_value = False
        def build(*args):
            entered.set()
            release.wait(3)
            raise OSError('SECRET history')
        handler = next(r.handler for r in self.app.router.routes()
                       if r.method == 'GET' and r.resource.canonical == '/api/opportunity-history')
        request = SimpleNamespace(query={'capture':'synthetic'})
        with patch('app.dashboard.opportunity_history.WatchStore.read', return_value=[{'id':'watch'}]), \
             patch('app.dashboard.opportunity_history.retained_history_key', return_value=None), \
             patch('app.dashboard.opportunity_history.build_history', side_effect=build):
            task = asyncio.create_task(handler(request))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                with self.assertLogs('app.dashboard.multi_game_server', level='ERROR') as logs:
                    release.set()
                    async with asyncio.timeout(3):
                        while not logs.output:await asyncio.sleep(.01)
                self.assertIn('opportunity_history_build', ' '.join(logs.output))
                self.assertNotIn('SECRET', ' '.join(logs.output))
                self.assertEqual(runtime_errors, [])
                # A new request gets to the worker, rather than remaining busy.
                with patch('app.dashboard.opportunity_history.build_history', return_value={'ok':True}):
                    response = await handler(request)
                self.assertEqual(response.status, 200)
            finally:
                loop.set_exception_handler(previous_handler)
                release.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
