"""Worker memory ownership and temporary-pressure regression cases."""
from unittest import TestCase
from unittest.mock import Mock, patch
from types import SimpleNamespace

from app.comparison.current_dependencies import encoded, encoded_size, digest, streaming_digest
from app.storage.scanner_preparation import PreparationCache, is_immutable_fact
from app.dashboard.scanner_api import Scanner
from app.collection.background_work import BackgroundWork
from tests.test_sc02_projection import frame, fake
from tests.test_ev09_n01 import AT


class WorkerMemory(TestCase):
    def test_streaming_identity_and_size_are_exact_for_shared_wide_frames(self):
        f, x = frame(40)
        value = dict(frame=f, inputs=x, unicode='é😀', escaped='"\\\n')
        self.assertEqual(encoded_size(value), len(encoded(value)))
        self.assertEqual(streaming_digest(value), digest(value))
        for bad in (float('nan'), float('inf')):
            with self.assertRaises(ValueError): encoded_size(bad)

    def test_cache_churn_preserves_exact_immutable_facts_and_expiry(self):
        cache=PreparationCache(max_entries=2)
        for n in range(10):
            value=dict(n=n,nested=[dict(original='é',clock=AT)])
            cache.put(str(n),value,at=AT,until='2026-10-30T00:00:00+00:00')
            value['nested'][0]['original']='mutated'
            frozen=cache.get_shared(str(n),at=AT)
            self.assertTrue(is_immutable_fact(frozen))
            self.assertEqual(frozen['nested'][0]['original'],'é')
            self.assertIs(cache._entries[str(n)][2],frozen)
            self.assertLessEqual(cache.stats()['entries'],2)
        self.assertIsNone(cache.get_shared('9',at='2026-10-30T00:00:00+00:00'))
        cache.clear();self.assertEqual(cache.stats()['bytes'],0)

    def worker(self):
        provider=SimpleNamespace(closed=False,closing=False,dispatch=True)
        with patch('app.comparison.scanner_summaries.SummaryWorker'):
            worker=Scanner(provider,durable=True,clock=lambda:AT)
        worker.projection.evaluator=fake
        return worker

    def test_changed_durable_capture_yields_without_recapture_or_current_finance(self):
        worker=self.worker();f,x=frame(3)
        worker.projection.ingest(f,x);worker.marker='before'
        worker._probe=Mock(return_value=('after',worker.projection.policy))
        worker._capture=Mock(side_effect=AssertionError('must yield to other owners'))
        worker._evaluate_current('before')
        self.assertIsNone(worker.marker)
        self.assertEqual(worker.projection.frame['revision'],f['revision'])
        self.assertFalse(worker.projection.rows);self.assertFalse(worker.projection.receipts)
        worker._capture.assert_not_called()

    def test_resize_deferral_releases_lease_preserves_frame_and_next_turn_recovers(self):
        work=BackgroundWork(sampler=lambda:100,limit_bytes=1000,
                           source_runway_bytes=200,ingress_headroom_bytes=100)
        worker=self.worker();worker.restored=True
        f,x=frame();worker.projection.ingest(f,x)
        saved=worker.projection.frame
        db=Mock();db.__enter__=Mock(return_value=db);db.__exit__=Mock(return_value=False)
        worker.connector=lambda:db
        def attempt():
            worker.capture_guard(600)
        worker._once_worker=Mock(side_effect=attempt)
        with patch('app.collection.background_work.BACKGROUND',work),\
             patch('app.storage.scanner_readiness.capture_reservation',return_value=100):
            self.assertTrue(worker.once()['deferred'])
            self.assertEqual(work.snapshot()['active'],{})
            self.assertIs(worker.projection.frame,saved)
            worker._once_worker.side_effect=lambda:worker.capture_guard(200)
            worker.once()
        self.assertEqual(work.snapshot()['active'],{})
        self.assertEqual(worker.admission_status['state'],'admitted')

    def test_live_turn_yields_complete_components_and_resumes_past_changing_head(self):
        from app.storage import latest_board as latest
        from contextlib import nullcontext
        work=BackgroundWork(sampler=lambda:100,limit_bytes=1000,
                           source_runway_bytes=200,ingress_headroom_bytes=100)
        db=Mock();db.transaction=lambda:nullcontext();db.execute.return_value.fetchall.return_value=[]
        admission={};served=[];clock=[0]
        groups=[['a','a-peer'],['b','b-peer'],['c','c-peer']]
        def calculate(db,**kwargs):
            served.append(list(kwargs['event_ids']));clock[0]+=21
            return dict(published=True,computed=1,reused=0,errors=[])
        with patch('app.collection.background_work.BACKGROUND',work),\
             patch.object(latest,'capture_reservation',return_value=100),\
             patch.object(latest,'capture_batches',side_effect=lambda db:groups),\
             patch.object(latest,'monotonic',side_effect=lambda:clock[0]),\
             patch.object(latest,'_reconcile',side_effect=calculate):
            first=latest.reconcile(db,admission=admission)
            self.assertTrue(first['yielded']);self.assertEqual(first['remaining_batches'],2)
            self.assertFalse(work.snapshot()['active'])
            with work.claim('coverage',100) as lease:self.assertTrue(lease)
            groups[0].append('new-peer')
            latest.reconcile(db,admission=admission)
            latest.reconcile(db,admission=admission)
        self.assertEqual(served,[['a','a-peer'],['b','b-peer'],['c','c-peer']])
        self.assertFalse(work.snapshot()['active'])
