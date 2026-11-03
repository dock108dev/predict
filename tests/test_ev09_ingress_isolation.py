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

    async def test_maintenance_expires_rows_and_runs_independent_retention(self):
        pipe = self.pipeline()
        database = object()
        rows = Mock()
        with patch('app.collection.current_database.connect', return_value=nullcontext(database)), \
                patch('app.storage.current_rows.CurrentRowStore', return_value=rows) as store, \
                patch('app.collection.current_database.sql_usage', return_value=123) as usage, \
                patch('app.storage.storage_maintenance.maintain', return_value={'after_bytes':123}) as maintenance:
            self.assertEqual(pipe.tick(), 0)
            usage.assert_called_once_with(database)
            maintenance.assert_called_once_with(database,collecting=True)
            self.assertEqual(pipe.maintenance,{'after_bytes':123})
            self.assertEqual(pipe.used, 123)
            store.assert_called_once_with(database)
            rows.expire.assert_called_once_with()
            self.assertEqual(rows.method_calls, [('expire', (), {})])
            pipe.closed = True
            pipe.tick()
            store.assert_called_once_with(database)
            usage.assert_called_once_with(database)

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

    async def test_expiry_failure_remains_unavailable_until_stop_without_killing_recovery(self):
        pipe = self.pipeline()
        loop=asyncio.get_running_loop()
        def fail():
            if tick.call_count<3:loop.call_soon_threadsafe(pipe.wake.set)
            raise OSError('authored-expiry-unavailable')
        with patch.object(pipe, 'tick', side_effect=fail) as tick:
            pipe.wake.set()
            pipe.task = asyncio.create_task(pipe.run_maintenance())
            async def failed_three_times():
                while pipe.maintenance_failures<3:await asyncio.sleep(.005)
            try:
                await asyncio.wait_for(failed_three_times(),1)
                self.assertFalse(pipe.task.done())
                self.assertEqual(tick.call_count, 3)
                self.assertEqual(pipe.error,'OSError')
                self.assertEqual(pipe.error_details['exception'],'OSError')
                self.assertNotIn('authored-expiry-unavailable',str(pipe.error_details))
            finally:self.assertTrue(await pipe.close())
            self.assertTrue(pipe.task.done())

    async def test_retired_import_and_finance_switches_fail_explicitly(self):
        pipe = self.pipeline()
        for options in ({'ingress': False}, {'import_only': True}):
            with self.subTest(options=options), self.assertRaises(TypeError):
                pipe.tick(**options)
