"""Shared background admission with real synchronous lifetime ownership."""
import asyncio
from threading import Event, Thread
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase,TestCase
from unittest.mock import patch

from app.collection.background_work import BackgroundWork,resident_bytes


class SharedOptionalThread(IsolatedAsyncioTestCase):
    async def test_reuses_one_heap_and_keeps_cancelled_work_charged(self):
        from app.collection.background_work import optional_thread
        from threading import get_ident
        work=budget();entered=Event();release=Event();threads=[]
        def first():
            with work.claim('estimates',100):
                threads.append(get_ident());entered.set();release.wait(3)
        task=asyncio.create_task(optional_thread(first))
        while not entered.is_set():await asyncio.sleep(.005)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        second=asyncio.create_task(optional_thread(lambda:threads.append(get_ident())))
        await asyncio.sleep(.01)
        self.assertEqual(work.snapshot()['active'],{'estimates':100})
        self.assertEqual(len(threads),1)
        with work.claim('observations',100,source=True) as source:self.assertTrue(source)
        release.set();await second
        self.assertEqual(threads[0],threads[1])
        self.assertEqual(work.snapshot()['active'],{})


def budget():
    return BackgroundWork(sampler=lambda:100,limit_bytes=1000,source_runway_bytes=200,ingress_headroom_bytes=100)


class BackgroundAdmission(TestCase):
    def test_resize_planning_replaces_only_its_own_reservation(self):
        work=budget()
        with work.claim('estimates',100):
            self.assertEqual(work.capacity('estimates'),499)
            self.assertEqual(work.capacity('estimates',replacing=True),599)
            self.assertEqual(work.capacity('coverage',replacing=True),499)
            work.resize('estimates',599)
            self.assertEqual(work.snapshot()['reserved_bytes'],599)
            with work.claim('coverage',1) as denied:self.assertFalse(denied)
        self.assertEqual(work.snapshot()['reserved_bytes'],0)
        with work.claim('estimates',100) as denied:self.assertFalse(denied)
        with work.claim('coverage',100) as admitted:self.assertTrue(admitted)
        self.assertFalse(work.snapshot()['active'])

    def test_live_growth_remains_charged_and_cannot_overcommit(self):
        work=budget()
        with work.claim('scanner',100):
            work.resize('scanner',300)
            self.assertEqual(work.snapshot()['active']['scanner'],300)
            work.resize('scanner',50)
            self.assertEqual(work.snapshot()['active']['scanner'],300)
            with self.assertRaisesRegex(ValueError,'background_memory_capacity'):
                work.resize('scanner',600)
            self.assertEqual(work.snapshot()['active']['scanner'],300)
        self.assertEqual(work.snapshot()['reserved_bytes'],0)

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
            def transaction(self):return self
            def execute(self,*args):return self
            def fetchone(self):return dict(owned=True)
        with patch('app.storage.latest_board.connect',return_value=DB()),\
                patch('app.storage.latest_board.capture_reservation',return_value=700) as preflight,\
                patch('app.storage.latest_board._reconcile',side_effect=AssertionError('denied capture decoded')),\
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


def test_optional_work_yields_to_acquisition_pressure_and_resumes():
    work=budget();work.acquisition_pressure=lambda:True
    with work.claim('scanner',100) as lease:
        assert not lease and lease.reason=='native_acquisition_catching_up'
    with work.claim('observations',100,source=True) as lease:
        assert not lease and lease.reason=='native_acquisition_catching_up'
    work.acquisition_pressure=lambda:False
    with work.claim('observations',100,source=True) as lease:assert lease
    with work.claim('scanner',100) as lease:assert lease


def test_precapture_yield_preserves_estimate_turn_without_allocating_or_bypassing_memory():
    from app.collection.background_work import AcquisitionDeferred
    from app.storage.latest_board import LatestBoardOwner
    import pytest
    work=budget();work.acquisition_pressure=lambda:True
    owner=LatestBoardOwner(SimpleNamespace())
    work.critical_acquisition_pressure=lambda:True
    with patch('app.collection.background_work.BACKGROUND',work):
        with pytest.raises(AcquisitionDeferred):owner.tick()
        with pytest.raises(AcquisitionDeferred):owner.tick()
        assert work.snapshot()['waiting']==['estimates']
        assert work.snapshot()['reserved_bytes']==0
        work.request('scanner');work.acquisition_pressure=lambda:False
        work.critical_acquisition_pressure=lambda:False
        with work.claim('scanner',100) as lease:
            assert not lease and lease.reason=='background_work_turn'
        # A waiting turn is not memory admission. An oversized measured capture
        # stays deferred and cannot prevent a smaller healthy owner progressing.
        with work.claim('estimates',700) as lease:
            assert not lease and lease.reason=='background_memory_capacity'
        with work.claim('scanner',100) as lease:assert lease
        with work.claim('estimates',100) as lease:assert lease
        assert not work.snapshot()['waiting']
        owner.closed=True
        from app.comparison.calculation_control import CalculationStopped
        with pytest.raises(CalculationStopped):owner.tick()
        assert not work.snapshot()['waiting']


def test_precapture_coverage_yield_registers_once_and_stop_cancels_waiter():
    from app.collection.background_work import AcquisitionDeferred
    from app.storage.latest_board import LatestBoardOwner
    import pytest
    work=budget();work.acquisition_pressure=lambda:True
    owner=LatestBoardOwner(SimpleNamespace())
    work.critical_acquisition_pressure=lambda:True
    with patch('app.collection.background_work.BACKGROUND',work):
        with pytest.raises(AcquisitionDeferred):owner.coverage_tick()
        with pytest.raises(AcquisitionDeferred):owner.coverage_tick()
        assert work.snapshot()['waiting']==['coverage']
        asyncio.run(owner.close())
        assert not work.snapshot()['waiting']


def test_waiter_is_released_on_unchanged_result_and_planning_failure():
    import pytest
    work=budget()
    assert work.requested('coverage',lambda:dict(unchanged=True))==dict(unchanged=True)
    assert not work.snapshot()['waiting']
    def fail():raise OSError('fixture planning error')
    with pytest.raises(OSError):work.requested('estimates',fail)
    assert not work.snapshot()['waiting']
    with work.claim('scanner',100) as lease:assert lease


def test_admitted_component_can_finish_under_soft_pressure_but_raw_pressure_and_stop_interrupt():
    import pytest
    from app.collection.background_work import optional_cancelled,AcquisitionDeferred
    work=budget()
    with patch('app.collection.background_work.BACKGROUND',work):
        with work.claim('estimates',100) as lease:
            assert lease
            work.acquisition_pressure=lambda:True
            assert not optional_cancelled(False)
            assert work.snapshot()['active']=={'estimates':100}
            work.critical_acquisition_pressure=lambda:True
            with pytest.raises(AcquisitionDeferred):optional_cancelled(False)
            assert optional_cancelled(True)
        assert not work.snapshot()['active']


class CatchupResume(IsolatedAsyncioTestCase):
    async def test_optional_owner_retries_after_acquisition_deferral(self):
        from app.storage.latest_board import LatestBoardOwner
        from app.collection.background_work import AcquisitionDeferred
        owner=LatestBoardOwner(SimpleNamespace());calls=[]
        def tick(**kwargs):
            calls.append(1);owner.wake.set()
            if len(calls)==1:raise AcquisitionDeferred('native_acquisition_catching_up')
            owner.closed=True
            return dict(published=True,errors=[],batches=[])
        owner.tick=tick
        await asyncio.wait_for(owner.run(),3)
        self.assertEqual(len(calls),2)
        self.assertIsNone(owner.error)
        self.assertTrue(owner.last['published'])


def test_scanner_defers_before_expensive_reservation_queries():
    from types import SimpleNamespace
    from unittest.mock import patch
    from app.dashboard.scanner_api import Scanner
    from app.collection.background_work import AcquisitionDeferred
    owner=SimpleNamespace(durable=True,stopped=lambda:False,
        connector=lambda:(_ for _ in ()).throw(AssertionError('SQL planning must wait')))
    owner._once_background=lambda:Scanner._once_background(owner)
    work=budget();work.acquisition_pressure=lambda:True
    with patch('app.collection.background_work.BACKGROUND',work):
        with __import__('pytest').raises(AcquisitionDeferred):Scanner.once(owner)
    assert work.snapshot()['waiting']==['scanner']


def test_scanner_turn_yields_worker_and_reservation_without_clearing_preparation():
    import pytest
    from app.dashboard.scanner_api import Scanner
    from app.collection.background_work import AcquisitionDeferred
    work=budget();prepared={'completed_group':'retained'}
    class DB:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    owner=SimpleNamespace(durable=True,restored=True,stopped=lambda:False,
        connector=DB,continuation=None,preparation=prepared,
        _withdraw_if_stopped=lambda:False)
    def worker():
        work.request('estimates')
        return Scanner._once(owner)
    owner._once_worker=worker
    owner._once_background=lambda:Scanner._once_background(owner)
    with patch('app.collection.background_work.BACKGROUND',work),\
            patch('app.storage.scanner_readiness.capture_reservation',return_value=100),\
            patch('app.dashboard.scanner_api.perf_counter',side_effect=[0,6]):
        with pytest.raises(AcquisitionDeferred,match='background_turn_yielded'):Scanner.once(owner)
    assert work.snapshot()['active']=={}
    assert owner.preparation is prepared and prepared=={'completed_group':'retained'}
    assert owner.capture_guard is None and owner.capture_turn_deadline is None
    with work.claim('estimates',100) as lease:assert lease


def test_transient_raw_pressure_yields_without_discarding_captured_work():
    from app.collection.background_work import BACKGROUND,optional_cancelled
    with patch.object(BACKGROUND,'critical_acquisition_pressure',side_effect=[True,True,False,False]), \
            patch('app.collection.background_work.time.sleep') as sleep:
        assert optional_cancelled(False) is False
    sleep.assert_called_once_with(.01)


def test_persistent_pressure_still_cancels_within_bounded_grace_and_stop_is_immediate():
    import pytest
    from app.collection.background_work import BACKGROUND,optional_cancelled,AcquisitionDeferred
    with patch.object(BACKGROUND,'critical_acquisition_pressure',return_value=True) as pressure, \
            patch('app.collection.background_work.time.sleep') as sleep, \
            patch('app.collection.background_work.time.monotonic',side_effect=[0,0,2.1]):
        assert optional_cancelled(True) is True
        pressure.assert_not_called();sleep.assert_not_called()
        with pytest.raises(AcquisitionDeferred):optional_cancelled(False)
    sleep.assert_called_once_with(.01)
