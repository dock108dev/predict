"""Authoritative revocation without rebuilding, plus explicit owned Stop."""
import asyncio
from datetime import timedelta
import json
import unittest
from unittest.mock import patch
from app.comparison.estimated_policy import EstimatePolicy
from app.dashboard.current_contract import stamp
from app.dashboard.current_deadlines import next_deadline
from app.dashboard.current_encoded import EncodedBodies, EncodedDelivery
from app.dashboard.comparison_jobs import ComparisonJobs, CalculatedBody, Superseded
from app.dashboard.current_state import CurrentStore
from tests.current_fixture import InjectedTestProvider, fixture


class DeadlineIndex(unittest.TestCase):
    def test_applicable_boundaries_and_opaque_metadata(self):
        now='2026-10-12T12:00:00+00:00'
        for key in ('start_at','effective_from','effective_until','effective_to',
                    'expires_at','scheduled_ts','model_effective_from'):
            state=dict(clock_at=now,events=[],comparison_profiles={'p':{key:'2026-10-12T12:00:02+00:00'}})
            self.assertEqual(next_deadline(state),stamp(now)+timedelta(seconds=2),key)
        state=dict(clock_at=now,events=[],comparison_profiles={'p':{'source_at':[now,now],'observed_at':'opaque'}})
        self.assertEqual(next_deadline(state),stamp(now)+timedelta(seconds=900.000001))
        state['calculations']={'expires_at':'2026-10-12T12:00:01+00:00'}
        self.assertEqual(next_deadline(state),stamp(now)+timedelta(seconds=900.000001))


class EligibilityAndStop(unittest.IsolatedAsyncioTestCase):
    async def test_age_validation_does_not_rebuild_or_renew_captured_clock(self):
        tick=[0];store=CurrentStore(InjectedTestProvider(),monotonic=lambda:tick[0])
        old_clock=store._state['clock_at'];epoch=store._calculation_epoch
        store._economic_deadline=stamp(old_clock)+timedelta(seconds=2)
        with patch.object(store,'refresh_age',side_effect=AssertionError('Heavy validation')):
            tick[0]=1;self.assertTrue(store.economic_valid(epoch))
            tick[0]=2;self.assertFalse(store.economic_valid(epoch))
            self.assertFalse(store.economic_valid(epoch));self.assertEqual(store._calculation_epoch,epoch+1)
        self.assertEqual(store._state['clock_at'],old_clock)
        await store.close()

    async def test_policy_change_without_packet_revokes_once(self):
        store=CurrentStore(InjectedTestProvider(),monotonic=lambda:0);epoch=store._calculation_epoch
        with patch('app.comparison.estimated_policy.load',return_value=EstimatePolicy(capital_ceiling_usd='500')):
            self.assertFalse(store.economic_valid(epoch));self.assertFalse(store.economic_valid(epoch))
        self.assertEqual(store._calculation_epoch,epoch+1)
        await store.close()

    async def test_deadline_index_failure_does_not_acknowledge_or_swap(self):
        store=CurrentStore(InjectedTestProvider(),monotonic=lambda:0);old=store._state
        with patch('app.dashboard.current_deadlines.next_deadline',side_effect=ValueError('index unavailable')):
            with self.assertRaises(ValueError):store.commit(fixture(2))
        self.assertIs(store._state,old);self.assertEqual(store._calculation_epoch,0)
        await store.close()

    async def test_temporal_registry_shares_only_exact_admitted_owner(self):
        from app.dashboard.current_contract import snapshot_inputs, packed, quotes_of
        from app.dashboard.current_incremental import project
        from tests.test_ev06_pairs import cross_group_workload
        store=CurrentStore(InjectedTestProvider(cross_group_workload()),monotonic=lambda:0)
        old=store._state;registry=old['comparison_profiles'];before=packed(old)
        raw=snapshot_inputs(old,copy_graph=False)
        raw.update(clock_at=(stamp(old['clock_at'])+timedelta(seconds=901)).isoformat(),state_revision=2)
        borrowed,*_=project(raw,old,store._fingerprints,store._group_bytes,allow_synthetic=True,borrow_profiles=True)
        copied,*_=project(raw,old,store._fingerprints,store._group_bytes,allow_synthetic=True)
        self.assertIs(borrowed['comparison_profiles'],registry)
        self.assertIsNot(copied['comparison_profiles'],registry)
        self.assertEqual(packed(borrowed),packed(copied));self.assertEqual(packed(old),before)
        public=snapshot_inputs(old)
        with self.assertRaises(ValueError):
            project(public,old,store._fingerprints,store._group_bytes,allow_synthetic=True,borrow_profiles=True)
        self.assertEqual(len(list(quotes_of(borrowed['events'][0]['groups'][0]['outcomes'][0]))),
                         len(list(quotes_of(copied['events'][0]['groups'][0]['outcomes'][0]))))
        await store.close()

    async def test_file_calculation_matches_synchronous_financial_body(self):
        from app.dashboard.current_contract import serialize,packed
        from app.dashboard.comparison_jobs import body_steps
        from app.comparison.effective_policy import recalculate
        from app.comparison.metrics import snapshot_metrics
        from tests.test_ev06_pairs import cross_group_workload
        state=serialize(cross_group_workload(),allow_synthetic=True);pool=EncodedBodies()
        policy=EstimatePolicy(capital_ceiling_usd='500');steps=body_steps(state,policy,{},pool)
        while True:
            try:next(steps)
            except StopIteration as done:result=done.value;break
        steps.close();self.assertEqual(result.body.block(0,len(result.body)),
            packed(snapshot_metrics(recalculate(state,policy),copy_graph=False)))
        result.body.release();self.assertFalse(pool.owners);pool.close()

    async def test_cache_expiry_keeps_reader_lease_and_coalescing(self):
        pool=EncodedBodies();pool.CACHE_SECONDS=.02;jobs=ComparisonJobs()
        def work():
            yield ('owned',0)
            return CalculatedBody(pool.encode({'rows':[{'id':'both legs'}]}),'captured')
        a,b=await asyncio.gather(jobs.read('same',work,lambda:True),jobs.read('same',work,lambda:True))
        self.assertIs(a.body,b.body);self.assertEqual(jobs.metrics['started'],1)
        reader=EncodedDelivery(a.body,{'request_generation':1})
        other=EncodedDelivery(b.body,{'request_generation':2})
        await asyncio.sleep(.04);self.assertIsNone(jobs.completed);self.assertFalse(a.body.closed)
        self.assertEqual(json.loads(await reader.as_bytes())['request_generation'],1)
        reader.release();other.release();self.assertTrue(a.body.closed)
        await jobs.close();pool.close()

    async def test_graceful_stop_cancels_actual_iterator_and_blocked_writer(self):
        provider=InjectedTestProvider();store=CurrentStore(provider,monotonic=lambda:0)
        started=asyncio.Event();released=asyncio.Event();blocked=asyncio.Event()
        def rebuilding():
            scratch=bytearray(1024*1024)
            try:
                started.set()
                while True:yield ('financial_unit',len(scratch))
            finally:released.set()
        pending=asyncio.create_task(store.comparison_jobs.read('rebuild',rebuilding,lambda:True))
        owner=store.encoded_bodies.encode({'rows':['x'*1000]*100})
        reader=store.encoded_bodies.payload(owner,adopt=True)
        class Writer:
            async def write(self,value):blocked.set();await asyncio.Event().wait()
        writing=asyncio.create_task(reader.write(Writer()))
        await started.wait();await blocked.wait();await store.close()
        results=await asyncio.gather(pending,writing,return_exceptions=True)
        self.assertTrue(released.is_set());self.assertEqual(provider.close_count,1)
        self.assertTrue(all(isinstance(r,(asyncio.CancelledError,Superseded)) for r in results))
        self.assertFalse(store.encoded_bodies.owners);self.assertFalse(store.encoded_bodies.readers)
        self.assertIsNone(store.comparison_jobs.active);self.assertIsNone(store.comparison_jobs.pending)
        self.assertFalse(store.comparison_jobs.driver and not store.comparison_jobs.driver.done())
        with self.assertRaises(ValueError):store.commit(fixture(2))
