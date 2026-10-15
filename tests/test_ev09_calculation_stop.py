"""A stopped local calculation abandons probes and frees its worker promptly."""
import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.comparison.calculation_control import cancellation, checkpoint, CalculationStopped
from app.comparison.estimated_consumer import consume
from app.collection.current_database import DatabasePipeline

class CalculationStop(unittest.IsolatedAsyncioTestCase):
    async def test_close_interrupts_active_financial_probe_within_existing_limit(self):
        started = threading.Event()
        pipe = DatabasePipeline(SimpleNamespace(config={'cleanup_seconds':1}))
        published = []
        def calculation():
            with cancellation(lambda:pipe.closed):
                started.set()
                while True:
                    checkpoint()
                    time.sleep(.005)
            published.append('forbidden')
        async def worker():
            try:await asyncio.to_thread(calculation)
            except CalculationStopped:pass
        pipe.task = asyncio.create_task(worker())
        self.assertTrue(await asyncio.to_thread(started.wait, 1))
        self.assertTrue(await pipe.close())
        self.assertTrue(pipe.task.done())
        self.assertEqual(published, [])
        checkpoint()  # Worker cancellation cannot leak into independent calculations.

    async def test_financial_consumer_honors_stop_before_touching_inputs(self):
        with cancellation(lambda:False):
            with self.assertRaises(CalculationStopped):
                with cancellation(lambda:True):pass
            checkpoint()
        active = False
        with cancellation(lambda:active):
            active = True
            with self.assertRaises(CalculationStopped):
                consume(None, None, at=None, native_quantity='1')
