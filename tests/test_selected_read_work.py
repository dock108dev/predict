"""Deadline, live-capacity ownership and shutdown with uncooperative workers."""
import asyncio
from threading import Event
from time import monotonic, sleep
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from app.dashboard.read_work import ReadWork, ReadDeadline, Trace, TRACE


class SelectedReadWork(IsolatedAsyncioTestCase):
    async def test_completed_allocation_is_resident_not_reserved_twice(self):
        work=ReadWork();ordinary=Trace('ordinary');selected=Trace('selected')
        token=TRACE.set(ordinary)
        try:
            with patch('app.dashboard.read_work.process_bytes',return_value=400*1024**2):
                work.guard(200*1024**2)
            with patch('app.dashboard.read_work.process_bytes',return_value=550*1024**2):
                work.guard()
                self.assertEqual(work.reservations[ordinary],16*1024**2)
                TRACE.set(selected)
                work.guard(128*1024**2)
                with self.assertRaisesRegex(ValueError,'memory_capacity'):
                    work.guard(129*1024**2)
                TRACE.set(ordinary)
                with self.assertRaisesRegex(ValueError,'memory_capacity'):
                    work.guard(100*1024**2)
        finally:TRACE.reset(token)

    async def test_refusal_releases_captured_graph_without_waiting_for_cyclic_gc(self):
        import gc,weakref
        class Captured:pass
        references=[];work=ReadWork()
        def refused():
            captured=Captured();references.append(weakref.ref(captured))
            raise ValueError('current_slate_read_authority_changed')
        enabled=gc.isenabled();gc.disable()
        try:
            try:await self.run_work(work,False,refused)
            except ValueError as error:
                self.assertEqual(str(error),'current_slate_read_authority_changed')
                self.assertIsNone(references[0]())
            else:self.fail('Expected a refusal')
        finally:
            if enabled:gc.enable()
            await work.close()

    async def test_completed_page_does_not_wait_for_cyclic_gc(self):
        import gc,weakref
        class Page:pass
        work=ReadWork();enabled=gc.isenabled();gc.disable()
        try:
            value=await self.run_work(work,False,Page)
            reference=weakref.ref(value)
            del value
            await asyncio.sleep(0)
            self.assertIsNone(reference())
        finally:
            if enabled:gc.enable()
            await work.close()

    async def test_read_lanes_reuse_distinct_threads_and_close_idle_workers(self):
        from threading import get_ident
        work=ReadWork()
        ordinary=[await self.run_work(work,False,get_ident) for _ in range(3)]
        selected=[await self.run_work(work,True,get_ident) for _ in range(3)]
        self.assertEqual(len(set(ordinary)),1)
        self.assertEqual(len(set(selected)),1)
        self.assertNotEqual(ordinary[0],selected[0])
        self.assertEqual(work.diagnostics()['running'],0)
        await work.close()
        for _ in range(20):
            if not any(t.is_alive() for t in work.worker_threads.values()):break
            await asyncio.sleep(.005)
        self.assertFalse(any(t.is_alive() for t in work.worker_threads.values()))

    async def test_cancelled_read_discards_only_its_frame_after_worker_exit(self):
        from app.storage.slate_reads import CapturedReads
        cache=CapturedReads(resource_bytes=lambda:0)
        other=cache.capture({},[b'{}'],context='other',authority='same')
        trace=Trace('ordinary');release=Event();entered=Event()
        def blocked():
            frame=cache.capture({},[b'{}'],context='owned',authority='same')
            trace.frames.add(frame.token);entered.set();release.wait(3)
        trace.cleanup=lambda:[cache.discard(token) for token in trace.frames]
        work=ReadWork(work_seconds=1)
        token=TRACE.set(trace)
        try:task=asyncio.create_task(work.run(False,blocked,trace))
        finally:TRACE.reset(token)
        while not entered.is_set():await asyncio.sleep(.005)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(len(cache.frames),2)
        self.assertGreater(work.diagnostics()['reserved_bytes'],0)
        release.set()
        while work.running:await asyncio.sleep(.005)
        self.assertEqual(list(cache.frames),[other.token])
        self.assertEqual(work.diagnostics()['reserved_bytes'],0)
        await work.close()

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

    async def test_background_shutdown_timeout_keeps_live_connection_owned(self):
        from app.storage.latest_board import LatestBoardOwner
        owner=LatestBoardOwner(SimpleNamespace(config=dict(cleanup_seconds=.05)))
        entered=Event();release=Event();db=MagicMock()
        db.__enter__.return_value=db
        db.execute.return_value.fetchone.return_value=dict(owned=True)
        def blocked(*args,**kwargs):entered.set();release.wait(3)
        with patch('app.storage.latest_board.connect',return_value=db),patch('app.storage.coverage_latest.reconcile',side_effect=blocked):
            owner.coverage_task=asyncio.create_task(owner.run_coverage())
            try:
                while not entered.is_set():await asyncio.sleep(.005)
                with self.assertRaises(TimeoutError):await owner.close()
                db.cancel_safe.assert_called_once_with(timeout=1)
                self.assertIn(db,owner.connections)
                self.assertFalse(owner.coverage_task.done())
                self.assertFalse(owner.drain_task.done())
            finally:
                release.set()
                await asyncio.wait_for(asyncio.shield(owner.drain_task),1)
            self.assertEqual(owner.connections,set())
            self.assertTrue(owner.coverage_task.done())

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
