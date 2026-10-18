"""Deadline, live-capacity ownership and shutdown with uncooperative workers."""
import asyncio
from threading import Event
from time import monotonic, sleep
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from app.dashboard.read_work import ReadWork, ReadDeadline, Trace, TRACE


class SelectedReadWork(IsolatedAsyncioTestCase):
    async def run_work(self, work, selected, fn):
        trace=Trace('selected' if selected else 'ordinary'); token=TRACE.set(trace)
        try:return await work.run(selected,fn,trace)
        finally:TRACE.reset(token)

    async def test_cancelled_worker_stays_counted_and_ordinary_progresses(self):
        work=ReadWork(queue_seconds=.05,work_seconds=.5)
        entered=Event(); release=Event()
        def blocked():entered.set();release.wait(3);return 'late'
        task=asyncio.create_task(self.run_work(work,True,blocked))
        while not entered.is_set():await asyncio.sleep(.005)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(work.pending['selected'],1)
        self.assertEqual(len(work.running),1)
        self.assertGreater(work.diagnostics()['reserved_bytes'],0)
        self.assertEqual(await self.run_work(work,False,lambda:'ordinary'),'ordinary')
        queued=asyncio.create_task(self.run_work(work,True,lambda:'never'))
        await asyncio.sleep(.01)
        with self.assertRaisesRegex(ReadDeadline,'current_read_busy'):
            await self.run_work(work,True,lambda:'excess')
        with self.assertRaisesRegex(ReadDeadline,'queue_timeout'):await queued
        self.assertEqual(work.pending['selected'],1)
        release.set()
        while work.running:await asyncio.sleep(.005)
        self.assertEqual(work.pending['selected'],0)
        self.assertEqual(work.diagnostics()['reserved_bytes'],0)
        self.assertEqual(await self.run_work(work,True,lambda:'new'),'new')
        await work.close()

    async def test_worker_response_deadline_and_bounded_shutdown_do_not_reclaim_live_worker(self):
        work=ReadWork(queue_seconds=.02,work_seconds=.03)
        release=Event()
        task=asyncio.create_task(self.run_work(work,True,lambda:release.wait(3)))
        with self.assertRaisesRegex(ReadDeadline,'current_read_timeout'):await task
        self.assertEqual(len(work.running),1)
        start=monotonic();await work.close()
        self.assertLess(monotonic()-start,1.2)
        self.assertEqual(len(work.running),1)
        self.assertGreater(work.diagnostics()['reserved_bytes'],0)
        with self.assertRaisesRegex(ReadDeadline,'busy'):
            await self.run_work(work,False,lambda:None)
        release.set()
        while work.running:await asyncio.sleep(.005)
        self.assertEqual(work.diagnostics()['reserved_bytes'],0)

    async def test_bounded_diagnostics_and_memory_refusal(self):
        work=ReadWork()
        for _ in range(80):self.assertEqual(await self.run_work(work,False,lambda:1),1)
        self.assertEqual(len(work.diagnostics()['records']),64)
        with self.assertRaisesRegex(ValueError,'memory_capacity'):work.guard(768*1024**2)
        self.assertEqual(sum(work.pending.values()),0)
        await work.close()

    async def test_background_publisher_cooperates_with_existing_shutdown_deadline(self):
        from app.storage.latest_board import LatestBoardOwner
        from app.comparison.calculation_control import checkpoint
        owner=LatestBoardOwner(SimpleNamespace(config=dict(cleanup_seconds=5)))
        entered=Event();finished=Event();db=MagicMock()
        db.execute.return_value.fetchone.return_value=dict(owned=True)
        def reconciling(*args,**kwargs):
            entered.set()
            try:
                while True:checkpoint();sleep(.005)
            finally:finished.set()
        with patch('app.storage.latest_board.connect',return_value=db),patch('app.storage.latest_board.reconcile',side_effect=reconciling):
            owner.task=asyncio.create_task(owner.run(observations_only=True))
            while not entered.is_set():await asyncio.sleep(.005)
            start=monotonic();await owner.close()
            self.assertTrue(finished.is_set())
            self.assertLess(monotonic()-start,.5)

    async def test_thread_start_failure_returns_all_capacity(self):
        work=ReadWork()
        with patch('app.dashboard.read_work.Thread.start',side_effect=RuntimeError('cannot start')):
            with self.assertRaises(RuntimeError):await self.run_work(work,True,lambda:None)
        self.assertEqual(work.running,{})
        self.assertEqual(work.reservations,{})
        self.assertEqual(work.pending['selected'],0)
        self.assertEqual(await self.run_work(work,True,lambda:'recovered'),'recovered')

    async def test_detached_worker_failure_is_safe_and_observable(self):
        work=ReadWork();entered=Event();release=Event()
        loop=asyncio.get_running_loop();previous=loop.get_exception_handler();unhandled=[]
        loop.set_exception_handler(lambda loop,context:unhandled.append(context))
        def broken():
            entered.set();release.wait(3)
            raise OSError('SECRET retained payload')
        task=asyncio.create_task(self.run_work(work,True,broken))
        try:
            while not entered.is_set():await asyncio.sleep(.005)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            with self.assertLogs('app.dashboard.read_work',level='ERROR') as logs:
                release.set()
                while work.running:await asyncio.sleep(.005)
            self.assertIn('retained_read_worker',' '.join(logs.output))
            self.assertNotIn('SECRET',' '.join(logs.output))
            self.assertEqual(unhandled,[])
            self.assertEqual(work.pending['selected'],0)
        finally:
            release.set()
            loop.set_exception_handler(previous)
            await work.close()
