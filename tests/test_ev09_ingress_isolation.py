"""Ordinary persistence keeps moving while selected finance is busy."""
import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.collection.current_database import DatabasePipeline
from app.comparison.calculation_control import cancellation,checkpoint

class IngressIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_saving_continues_during_active_finance_and_both_stop(self):
        pipe=DatabasePipeline(SimpleNamespace(config={'cleanup_seconds':1}),[])
        calculating=threading.Event();saved=threading.Event();count=[0]
        def tick(*,ingress=True,import_only=False):
            with cancellation(lambda:pipe.closed):
                if import_only:
                    if calculating.is_set():
                        count[0]+=1
                        if count[0]>=3:saved.set()
                    return 8
                calculating.set()
                while True:
                    checkpoint();time.sleep(.005)
        with patch.object(pipe,'tick',side_effect=tick):
            await pipe.start()
            self.assertTrue(await asyncio.to_thread(saved.wait,1),'intake was blocked behind finance')
            self.assertTrue(await pipe.close())
        self.assertTrue(pipe.task.done() and pipe.ingress_task.done())
        self.assertEqual(pipe.failures,0);self.assertEqual(pipe.ingress_failures,0)
        self.assertIsNone(pipe.error);self.assertIsNone(pipe.ingress_error)
