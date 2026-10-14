"""Complete-result compatibility, underlying cancellation and latest ownership."""
import asyncio
import gc
import json
import unittest
import weakref
from unittest.mock import patch

from app.comparison.effective_policy import effective_policy,recalculate
from app.comparison.estimated_policy import EstimatePolicy
from app.comparison.metrics import snapshot_metrics
from app.dashboard.comparison_jobs import ComparisonJobs,Superseded,body_steps
from app.dashboard.current_contract import packed,serialize
from app.dashboard.current_response import ComparisonDelivery,CurrentResponse
from app.dashboard.current_state import CurrentStore
from tests.current_fixture import InjectedTestProvider,fixture
from tests.test_ev06_pairs import cross_group_workload


class CompleteJobs(unittest.TestCase):
    def test_large_canonical_encoding_varied_lengths_matches_independent_json(self):
        values=[dict(text='é'*(520000+n),state_revision=n,exact=dict(numerator='-1',denominator='3')) for n in range(4)]
        for value in values:
            self.assertEqual(packed(value),json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode())

    def test_complete_fragment_wire_equals_existing_financial_consumer(self):
        policy=EstimatePolicy(capital_ceiling_usd='500')
        state=serialize(cross_group_workload(),allow_synthetic=True,estimate_policy=EstimatePolicy())
        before=packed(state)
        expected=recalculate(state,policy)
        for filters in ({},{'venue':'kalshi'},{'results':'negative'},{'search':'absent'},{'league':'NFL'},{'league':'NBA'}):
            steps=body_steps(state,policy,filters)
            while True:
                try:next(steps)
                except StopIteration as done:
                    result=done.value;break
            self.assertEqual(result.body,packed(snapshot_metrics(expected,copy_graph=False,**filters)))
            self.assertEqual(result.clock_at,state['clock_at'])
        self.assertEqual(packed(state),before)

    def test_legacy_metric_layout_remains_complete(self):
        state=serialize(fixture(),allow_synthetic=True,estimate_policy=EstimatePolicy())
        policy=effective_policy(state['estimate_policy'],ceiling='500')
        steps=body_steps(state,policy,{})
        while True:
            try:next(steps)
            except StopIteration as done:result=done.value;break
        self.assertEqual(result.body,packed(snapshot_metrics(recalculate(state,policy),copy_graph=False)))

    def test_internal_temporal_projection_borrows_inputs_without_mutating_publication(self):
        from datetime import timedelta
        from app.dashboard.current_contract import snapshot_inputs,stamp,validate_snapshot
        from app.dashboard.current_incremental import project,signatures
        from app.dashboard.current_contract import quotes_of
        policy=EstimatePolicy()
        state=serialize(cross_group_workload(),allow_synthetic=True,estimate_policy=policy)
        before=packed(state);raw=snapshot_inputs(state,copy_graph=False)
        raw.update(clock_at=(stamp(state['clock_at'])+timedelta(seconds=901)).isoformat(),state_revision=state['state_revision']+1)
        sizes={(e['id'],g['id']):len(packed(g))+256*sum(len(quotes_of(o)) for o in g['outcomes']) for e in state['events'] for g in e['groups']}
        with patch('app.dashboard.current_incremental.load',return_value=policy):
            result,*_=project(raw,state,signatures(snapshot_inputs(state),policy.revision),sizes,allow_synthetic=True)
        self.assertEqual(packed(state),before)
        validate_snapshot(result,allow_synthetic=True)
        public=snapshot_inputs(state)
        self.assertIsNot(public['comparison_profiles'],state['comparison_profiles'])



class JobOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_coalescing_and_fair_safe_units(self):
        jobs=ComparisonJobs();seen=[]
        def work():
            for i in range(50):seen.append(i);yield ('test',i)
            return b'complete'
        a=asyncio.create_task(jobs.read('same',work,lambda:True))
        b=asyncio.create_task(jobs.read('same',work,lambda:True))
        self.assertEqual(await asyncio.gather(a,b),[b'complete']*2)
        self.assertEqual(seen,list(range(50)))
        self.assertEqual(jobs.metrics['started'],1)
        self.assertEqual(jobs.metrics['coalesced'],1)
        self.assertEqual(await jobs.read('same',work,lambda:True),b'complete')
        await jobs.close();self.assertIsNone(jobs.completed)

    async def test_superseded_iterator_and_owned_allocation_are_released(self):
        jobs=ComparisonJobs();started=asyncio.Event();released=asyncio.Event();refs=[]
        class Allocation:pass
        def old():
            allocation=Allocation();refs.append(weakref.ref(allocation))
            try:
                started.set()
                while True:yield 'obsolete'
            finally:released.set()
        def latest():yield 'latest';return b'new'
        a=asyncio.create_task(jobs.read('old',old,lambda:True));await started.wait()
        b=asyncio.create_task(jobs.read('latest',latest,lambda:True))
        with self.assertRaises(Superseded):await a
        self.assertEqual(await b,b'new');await released.wait();gc.collect()
        self.assertIsNone(refs[0]())
        self.assertIsNone(jobs.active);self.assertIsNone(jobs.pending)
        self.assertEqual(jobs.metrics['maximum_active'],1);self.assertEqual(jobs.metrics['maximum_pending'],1)
        await jobs.close()

    async def test_disconnect_stops_underlying_job_and_failure_does_not_poison_latest(self):
        jobs=ComparisonJobs();entered=asyncio.Event();released=asyncio.Event();closed=[]
        def work():
            try:
                entered.set()
                while True:yield 'pending'
            finally:closed.append(True);released.set()
        task=asyncio.create_task(jobs.read('disconnect',work,lambda:True));await asyncio.wait_for(entered.wait(),5)
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        await asyncio.wait_for(released.wait(),1)
        self.assertEqual(closed,[True])
        def broken():yield 'first';raise ValueError('authored failure')
        with self.assertRaises(ValueError):await jobs.read('failure',broken,lambda:True)
        def restored():yield 'last';return b'restored'
        self.assertEqual(await jobs.read('restore',restored,lambda:True),b'restored')
        await jobs.close()

    async def test_transport_disconnect_cancels_only_its_own_coalesced_reader(self):
        jobs=ComparisonJobs();entered=asyncio.Event();alive=[True];units=[]
        def work():
            entered.set()
            for i in range(100):units.append(i);yield i
            return b'complete'
        gone=asyncio.create_task(jobs.read('same',work,lambda:True,alive=lambda:alive[0]))
        other=asyncio.create_task(jobs.read('same',work,lambda:True));await asyncio.wait_for(entered.wait(),5)
        alive[0]=False
        result=await asyncio.gather(gone,return_exceptions=True)
        self.assertIsInstance(result[0],asyncio.CancelledError)
        self.assertEqual(await other,b'complete')
        self.assertEqual(units,list(range(100)))
        await jobs.close()

    async def test_quote_reference_policy_content_reset_and_stop_revoke_jobs(self):
        # Each source/context transition uses the same authoritative store epoch.
        # No changed state can publish through the old financial job.
        for cause in ('quote','reference','policy','content','reset','stop'):
            jobs=ComparisonJobs();valid=[True];entered=asyncio.Event();closed=[]
            def work():
                try:
                    entered.set()
                    while True:yield cause
                finally:closed.append(True)
            task=asyncio.create_task(jobs.read(cause,work,lambda:valid[0]));await asyncio.wait_for(entered.wait(),5)
            valid[0]=False;jobs.invalidate()
            with self.assertRaises(Superseded):await task
            self.assertEqual(closed,[True]);self.assertIsNone(jobs.completed)
            await jobs.close()

    async def test_age_only_tick_preserves_epoch_but_expiry_and_commit_revoke(self):
        tick=[0];policy=EstimatePolicy()
        with patch('app.comparison.estimated_policy.load',return_value=policy),patch('app.dashboard.current_incremental.load',return_value=policy):
            store=CurrentStore(InjectedTestProvider(),monotonic=lambda:tick[0]);epoch=store._calculation_epoch
            tick[0]=1;store.refresh_age();self.assertEqual(store._calculation_epoch,epoch)
            tick[0]=10000;store.refresh_age();self.assertGreater(store._calculation_epoch,epoch)
            before=store._calculation_epoch
            raw=fixture();raw['runtime_id']='synthetic:ev08:new';store.commit(raw)
            self.assertGreater(store._calculation_epoch,before)
            await store.close();self.assertTrue(store.comparison_jobs.closed)

    async def test_actual_matching_content_kickoff_and_stop_shutdown_running_work(self):
        from pathlib import Path
        from tests.ev07_fixture_runtime import FixtureBoundary,fixture_app,fixture_transition
        from tests.ev08_fixture import transition
        from app.dashboard.current_state import CURRENT_KEY
        for cause in ('matching_conflict','prepare_content_expiry','prepare_kickoff','change_second_leg','remove_reference','reset_runtime','stop'):
            with FixtureBoundary() as boundary:
                store=fixture_app(boundary,Path('test-results/ev08-continuation/authored-jobs'))[CURRENT_KEY]
                if cause in ('prepare_content_expiry','prepare_kickoff'):
                    transition(store,boundary,cause)
                epoch=store._calculation_epoch;entered=asyncio.Event();released=asyncio.Event()
                def pending():
                    try:
                        entered.set()
                        while True:yield 'authored safe unit'
                    finally:released.set()
                def valid():
                    store.refresh_age()
                    return not store.closed and epoch==store._calculation_epoch
                reader=asyncio.create_task(store.comparison_jobs.read(cause,pending,valid))
                await asyncio.wait_for(entered.wait(),5)
                if cause=='stop':await store.close()
                elif cause in ('prepare_content_expiry','prepare_kickoff'):transition(store,boundary,'advance_boundary')
                elif cause=='matching_conflict':transition(store,boundary,cause)
                else:fixture_transition(store,cause)
                result=await asyncio.gather(reader,return_exceptions=True)
                self.assertIsInstance(result[0],(Superseded,asyncio.CancelledError),cause)
                await asyncio.wait_for(released.wait(),1)
                self.assertIsNone(store.comparison_jobs.active)
                self.assertIsNone(store.comparison_jobs.completed)
                self.assertFalse(boundary.calls)
                await store.close()

    async def test_delivery_never_reuses_another_request_generation(self):
        body=packed(dict(rows=[dict(id='both-legs')],clock_at='captured'))
        class Writer:
            def __init__(self):self.parts=[]
            async def write(self,part):self.parts.append(bytes(part))
        for generation in ('1','2'):
            delivery=ComparisonDelivery(body,dict(request_generation=generation,delivery=dict(validated_clock_at='fresh')))
            writer=Writer();await delivery.write(writer)
            joined=b''.join(writer.parts);value=json.loads(joined)
            self.assertEqual(len(joined),delivery.size)
            self.assertEqual(value['request_generation'],generation)
            self.assertEqual(value['clock_at'],'captured')
            self.assertEqual(value['rows'],[dict(id='both-legs')])
            writer=Writer();await delivery.write_with_length(writer,delivery.size)
            self.assertEqual(b''.join(writer.parts),joined)
        self.assertIsInstance(CurrentResponse(body=delivery),CurrentResponse)

    async def test_http_library_length_hook_honors_bound_and_truncation(self):
        from app.dashboard.current_response import BoundedBytes,WRITE_BYTES
        body=b'x'*(WRITE_BYTES*3+5)
        class Writer:
            def __init__(self):self.parts=[]
            async def write(self,part):self.parts.append(bytes(part))
        for limit in (None,0,12,len(body)):
            writer=Writer();await BoundedBytes(body).write_with_length(writer,limit)
            self.assertEqual(b''.join(writer.parts),body if limit is None else body[:limit])
            self.assertTrue(all(len(p)<=WRITE_BYTES for p in writer.parts))
