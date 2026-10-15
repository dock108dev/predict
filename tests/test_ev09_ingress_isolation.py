"""Ordinary maintenance only expires current rows and joins on Stop."""
import asyncio
from contextlib import nullcontext
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app.collection.current_database import DatabasePipeline


class IngressIsolation(unittest.IsolatedAsyncioTestCase):
    def pipeline(self):
        return DatabasePipeline(SimpleNamespace(config={'cleanup_seconds': 1}))

    async def test_maintenance_routes_only_to_current_row_expiry(self):
        pipe = self.pipeline()
        database = object()
        rows = Mock()
        with patch('app.collection.current_database.connect', return_value=nullcontext(database)), \
                patch('app.storage.current_rows.CurrentRowStore', return_value=rows) as store:
            self.assertEqual(pipe.tick(), 0)
            store.assert_called_once_with(database)
            rows.expire.assert_called_once_with()
            self.assertEqual(rows.method_calls, [('expire', (), {})])
            pipe.closed = True
            pipe.tick()
            store.assert_called_once_with(database)

    async def test_close_joins_active_expiry_without_starting_more_work(self):
        pipe = self.pipeline()
        entered = threading.Event()
        release = threading.Event()
        def expire():
            entered.set()
            if not release.wait(1):
                raise AssertionError('authored expiry release timed out')
        with patch.object(pipe, 'tick', side_effect=expire) as tick:
            pipe.wake.set()
            pipe.task = asyncio.create_task(pipe.run_maintenance())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                closing = asyncio.create_task(pipe.close())
                await asyncio.sleep(0)
                self.assertTrue(pipe.closed)
                self.assertFalse(closing.done())
                release.set()
                self.assertTrue(await closing)
            finally:
                release.set()
                await pipe.close()
        self.assertTrue(pipe.task.done())
        self.assertIsNone(pipe.error)
        tick.assert_called_once_with()

    async def test_expiry_failure_stops_after_three_attempts(self):
        pipe = self.pipeline()
        def fail():
            pipe.wake.set()
            raise OSError('authored-expiry-unavailable')
        with patch.object(pipe, 'tick', side_effect=fail) as tick:
            pipe.wake.set()
            pipe.task = asyncio.create_task(pipe.run_maintenance())
            await asyncio.wait_for(asyncio.shield(pipe.task), 1)
            self.assertEqual(tick.call_count, 3)
            self.assertIn('authored-expiry-unavailable', pipe.error)
            self.assertTrue(await pipe.close())

    async def test_retired_import_and_finance_switches_fail_explicitly(self):
        pipe = self.pipeline()
        for options in ({'ingress': False}, {'import_only': True}):
            with self.subTest(options=options), self.assertRaises(TypeError):
                pipe.tick(**options)
