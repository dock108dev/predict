"""Failure injection with temporary synthetic state and loopback-only fixtures."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiohttp.test_utils import TestClient, TestServer
from app.dashboard import coverage_owner
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game import MultiOwner
from app.dashboard.multi_game_server import create_app
from tests.segmented_collector_fixture import Fixture


class CoverageFailures(unittest.IsolatedAsyncioTestCase):
    async def test_direct_start_rejects_unconfirmed_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner = CoverageOwner(tmp, pilot_output=Path(tmp)/'pilot', product_mode=True)
            owner.session = SimpleNamespace(task=None, cleanup_errors=['kalshi:OSError'])
            with self.assertRaisesRegex(ValueError, 'cleanup failed'):
                await owner.start()
            self.assertFalse((Path(tmp)/'pilot/collector.lock').exists())

    async def test_start_failure_and_cancellation_preserve_original_and_release_lock(self):
        for original in (OSError('SECRET primary'), asyncio.CancelledError()):
            with self.subTest(error=type(original).__name__), tempfile.TemporaryDirectory() as tmp:
                session = SimpleNamespace(
                    sid='synthetic', task=asyncio.get_running_loop().create_future(),
                    start=AsyncMock(side_effect=original),
                    stop=AsyncMock(side_effect=OSError('SECRET cleanup')), cleanup_errors=[])
                session.task.set_result(None)
                owner = CoverageOwner(tmp, pilot_output=Path(tmp)/'pilot',
                                      session_factory=Mock(return_value=session))
                with self.assertLogs('app.dashboard.coverage_owner', level='ERROR') as logs:
                    with self.assertRaises(type(original)) as caught:
                        await owner.start()
                self.assertIs(caught.exception, original)
                session.stop.assert_awaited_once()
                self.assertIsNone(owner.owner_lock)
                self.assertFalse(owner.starting)
                self.assertEqual(session.cleanup_errors, ['startup:OSError'])
                self.assertNotIn('SECRET', ' '.join(logs.output))

    async def test_flat_publication_failures_leave_no_completion_manifest(self):
        for fault in ('replay', 'fsync', 'capacity'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                fixture = Fixture()
                owner = await fixture.start(tmp, product_mode=True, segmented=False)
                original_save = coverage_owner.save_json

                def save(path, value):
                    if fault == 'fsync' and path.name == 'manifest.pending.json':
                        with patch('os.fsync', side_effect=OSError('SECRET disk')):
                            return original_save(path, value)
                    return original_save(path, value)

                try:
                    with patch.object(coverage_owner, 'save_json', side_effect=save):
                        with patch.object(coverage_owner, 'replay_groups',
                                          side_effect=ValueError('SECRET replay') if fault == 'replay' else None,
                                          return_value={}):
                            with patch.dict(coverage_owner.LIMITS,
                                            output_bytes=1 if fault == 'capacity' else coverage_owner.LIMITS['output_bytes']):
                                with self.assertLogs('app.dashboard.coverage_owner', level='ERROR'):
                                    await owner.stop()
                                    await owner.finalizer
                    folder = owner.session.output
                    self.assertFalse((folder/'manifest.json').exists())
                    self.assertEqual(owner.status()['state'], 'failed')
                    self.assertIsNotNone(owner.error)
                    self.assertNotIn('SECRET', owner.error)
                    self.assertTrue((folder/'report.json').exists())
                    if fault != 'replay':
                        self.assertTrue((folder/'manifest.pending.json').exists())
                finally:
                    await fixture.close()

    async def test_saved_package_error_is_safe_and_logged_for_both_readers(self):
        for history in (False, True):
            with self.subTest(history=history), tempfile.TemporaryDirectory() as tmp:
                owner = MultiOwner(tmp, personal_beta=True)
                if history:
                    owner.history_paths = lambda: {'synthetic': Path(tmp)/'synthetic'}
                    target = 'app.dashboard.session_history.load'
                else:
                    owner.saved = lambda: ['synthetic']
                    target = 'app.dashboard.multi_game_server.saved_rows'
                client = TestClient(TestServer(create_app(owner=owner, sessions={})))
                await client.start_server()
                try:
                    with patch(target, side_effect=OSError('SECRET private path')):
                        with self.assertLogs('app.dashboard.multi_game_server', level='ERROR') as logs:
                            response = await client.get('/api/dashboard?capture=synthetic')
                            data = await response.json()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(data['state'], 'incomplete')
                    self.assertEqual(data['rows'], [])
                    self.assertIn('local log', data['error'])
                    self.assertNotIn('SECRET', str(data) + ' '.join(logs.output))
                finally:
                    await client.close()

    async def test_segmented_secondary_report_failure_is_observable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture()
            owner = await fixture.start(tmp, product_mode=True, segmented=True)
            original_save = coverage_owner.save_json

            def fail(path, value):
                if path.name in ('manifest.pending.json', 'finalization-failure.json'):
                    raise OSError('SECRET disk failure')
                return original_save(path, value)

            try:
                with patch.object(coverage_owner, 'save_json', side_effect=fail):
                    with self.assertLogs('app.dashboard.coverage_owner', level='ERROR') as logs:
                        await owner.stop()
                        await owner.finalizer
                output = ' '.join(logs.output)
                self.assertIn('segmented_publication', output)
                self.assertIn('segmented_failure_report', output)
                self.assertNotIn('SECRET', output)
                self.assertEqual(owner.status()['state'], 'failed')
                self.assertEqual(owner.mock_result['status'], 'failed')
                self.assertFalse((owner.session.output/'manifest.json').exists())
                self.assertIsNone(owner.owner_lock)
            finally:
                await fixture.close()

    async def test_segmented_output_cap_precedes_publication(self):
        from app.collection.segmented import POLICY
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture()
            owner = await fixture.start(tmp, product_mode=True, segmented=True)
            folder = owner.session.output
            history = owner.session.journal.history
            original_size = history.disk_bytes

            def size():
                return POLICY['output'] + 1 if (folder/'manifest.pending.json').exists() else original_size()

            try:
                with patch.object(history, 'disk_bytes', side_effect=size):
                    with self.assertLogs('app.dashboard.coverage_owner', level='ERROR'):
                        await owner.stop()
                        await owner.finalizer
                self.assertEqual(owner.status()['state'], 'failed')
                self.assertTrue((folder/'manifest.pending.json').exists())
                self.assertFalse((folder/'manifest.json').exists())
            finally:
                await fixture.close()
