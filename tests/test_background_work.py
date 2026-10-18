"""Shared background admission with real synchronous lifetime ownership."""
import asyncio
from threading import Event, Thread
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import patch

from app.collection.background_work import BackgroundWork,resident_bytes


def budget():
    return BackgroundWork(sampler=lambda:100,limit_bytes=1000,source_runway_bytes=200,ingress_headroom_bytes=100)


class BackgroundAdmission(TestCase):
    def test_coverage_can_start_during_source_work_with_reserved_source_runway(self):
        work=budget()
        with work.claim('observations',200,source=True) as source:
            self.assertTrue(source)
            with work.claim('coverage',100) as coverage:
                self.assertTrue(coverage)
                self.assertEqual(work.snapshot()['reserved_bytes'],300)
                with work.claim('scanner',100) as other:self.assertFalse(other)
            self.assertIn('observations',work.snapshot()['active'])
        self.assertFalse(work.snapshot()['active'])
    def test_source_runs_independently_while_slow_optional_remains_charged(self):
        work=budget();started=Event();finish=Event()
        def optional():
            with work.claim('estimates',300) as lease:
                self.assertTrue(lease);started.set();finish.wait(2)
        thread=Thread(target=optional);thread.start();self.assertTrue(started.wait(1))
        try:
            with work.claim('observations',200,source=True) as source:
                self.assertTrue(source)
                self.assertEqual(work.snapshot()['reserved_bytes'],500)
                with work.claim('coverage',50) as denied:self.assertFalse(denied)
            self.assertEqual(work.snapshot()['optional_owner'],'estimates')
        finally:finish.set();thread.join(2)
        self.assertEqual(work.snapshot()['reserved_bytes'],0)

    def test_fair_optional_turns_and_memory_infeasible_head_cannot_starve_small_work(self):
        work=budget()
        with work.claim('estimates',300):
            with work.claim('scanner',200) as waiting:self.assertFalse(waiting)
            with work.claim('coverage',100) as waiting:self.assertFalse(waiting)
        with work.claim('estimates',300) as denied:self.assertFalse(denied)
        with work.claim('scanner',200) as admitted:self.assertTrue(admitted)
        with work.claim('coverage',100) as admitted:self.assertTrue(admitted)
        with work.claim('estimates',300) as admitted:self.assertTrue(admitted)
        with work.claim('estimates',700) as denied:
            self.assertFalse(denied);self.assertEqual(denied.reason,'background_memory_capacity')
        with work.claim('coverage',100) as admitted:self.assertTrue(admitted)

    def test_deferred_stop_cancels_only_waiting_turn_and_diagnostics_are_bounded(self):
        work=budget()
        with work.claim('coverage',100):
            with work.claim('scanner',50) as denied:self.assertFalse(denied)
            work.cancel('scanner');work.cancel('coverage')
            self.assertEqual(work.snapshot()['optional_owner'],'coverage')
            self.assertEqual(work.snapshot()['waiting'],[])
        snapshot=work.snapshot()
        self.assertEqual(snapshot['process_limit_bytes'],1000)
        self.assertEqual(snapshot['source_runway_bytes'],200)
        self.assertEqual(snapshot['counts']['coverage'],dict(admitted=1,deferred=0))

    def test_inflight_optional_growth_is_counted_without_queueing_source(self):
        resident=[100]
        work=BackgroundWork(sampler=lambda:resident[0],limit_bytes=1000,
            source_runway_bytes=200,ingress_headroom_bytes=100)
        with work.claim('estimates',300):
            resident[0]=550
            with work.claim('observations',200,source=True) as source:
                self.assertFalse(source);self.assertEqual(source.reason,'background_memory_capacity')
                self.assertNotIn('observations',work.snapshot()['waiting'])
            resident[0]=200
            with work.claim('observations',200,source=True) as source:self.assertTrue(source)

    def test_current_resident_sample_is_positive_without_reading_peak_guard(self):
        with patch('app.collection.continuous.rss',side_effect=AssertionError('current sample must succeed')):
            self.assertGreater(resident_bytes(),0)

    def test_board_worker_preflights_before_decoding_and_keeps_defer_explicit(self):
        from app.storage.latest_board import LatestBoardOwner
        work=budget();owner=LatestBoardOwner(SimpleNamespace(config=dict(cleanup_seconds=1)))
        class DB:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,*args):return self
            def fetchone(self):return dict(owned=True)
        with patch('app.storage.latest_board.connect',return_value=DB()),\
                patch('app.storage.latest_board.capture_reservation',return_value=700) as preflight,\
                patch('app.storage.latest_board.reconcile',side_effect=AssertionError('denied capture decoded')),\
                patch('app.collection.background_work.BACKGROUND',work):
            result=owner.tick(observations_only=False)
        preflight.assert_called_once();self.assertTrue(result['deferred'])
        self.assertEqual(owner.admission_status['estimates']['reason'],'background_memory_capacity')


class WorkerLifetime(IsolatedAsyncioTestCase):
    async def test_cancelled_await_does_not_release_live_synchronous_reservation(self):
        work=budget();started=Event();finish=Event()
        def sync_worker():
            with work.claim('coverage',200):started.set();finish.wait(2)
        task=asyncio.create_task(asyncio.to_thread(sync_worker))
        while not started.is_set():await asyncio.sleep(.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(work.snapshot()['optional_owner'],'coverage')
        with work.claim('scanner',100) as denied:self.assertFalse(denied)
        finish.set()
        for _ in range(100):
            if work.snapshot()['optional_owner'] is None:break
            await asyncio.sleep(.001)
        self.assertIsNone(work.snapshot()['optional_owner'])
