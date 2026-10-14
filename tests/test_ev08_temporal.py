"""Production temporal ownership, revocation and financial agreement regressions."""
import asyncio
from datetime import timedelta
import unittest
from unittest.mock import patch
from app.dashboard.current_state import CurrentStore, SelectionError, CURRENT_KEY
from app.dashboard.current_contract import packed, serialize, snapshot_inputs, stamp
from tests.current_fixture import InjectedTestProvider, fixture
from tests.test_ev06_pairs import cross_group_workload
from app.comparison.estimated_policy import EstimatePolicy


class TemporalOwnership(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tick=[0];self.store=CurrentStore(InjectedTestProvider(cross_group_workload()),monotonic=lambda:self.tick[0])
    async def asyncTearDown(self):await self.store.close()

    async def settle(self):
        while self.store.temporal.driver and not self.store.temporal.driver.done():
            await asyncio.wait_for(asyncio.shield(self.store.temporal.driver),20)
        self.assertIsNone(self.store.temporal.failure)

    async def test_revocation_precedes_work_and_all_complete_reads_withhold(self):
        old=self.store._state;clock=old['clock_at'];epoch=self.store._calculation_epoch
        # Exact production boundary, no fake generator or refresh replacement.
        self.tick[0]=901
        self.store.refresh_age()
        self.assertIs(self.store._state,old)
        self.assertTrue(self.store._economic_invalidated)
        for call in (self.store.snapshot,self.store.encoded_snapshot,
                     lambda:self.store.encoded_changes(old['runtime_id'],1),
                     lambda:self.store.encoded_transport_snapshot(),
                     lambda:self.store.details(dict(runtime_id=old['runtime_id'],state_revision=1,quote_id='missing'))):
            with self.assertRaises(SelectionError) as ctx:call()
            self.assertEqual(ctx.exception.status,503)
            self.assertEqual(ctx.exception.body['error'],'temporal_pending')
        self.assertFalse(self.store.economic_valid(epoch));self.assertEqual(self.store._state['clock_at'],clock)
        await self.settle()
        result=self.store._state
        self.assertFalse(self.store._economic_invalidated)
        original=snapshot_inputs(old);original.update(clock_at=(stamp(clock)+timedelta(seconds=901)).isoformat(),state_revision=result['state_revision'])
        self.assertEqual(packed(result),packed(serialize(original,allow_synthetic=True)))
        self.assertIs(result['comparison_profiles'],old['comparison_profiles'])
        self.assertGreater(self.store.temporal.metrics['units'],20)
        self.assertIsNone(self.store.temporal.iterator)

    async def test_harmless_tick_reuses_exact_future_index_and_full_bytes(self):
        old=self.store._state;deadline=self.store._economic_deadline
        self.tick[0]=1
        with patch('app.dashboard.current_deadlines.next_deadline',side_effect=AssertionError('Unchanged index scanned')):
            self.store.refresh_age();await self.settle()
        result=self.store._state
        self.assertEqual(self.store._economic_deadline,deadline)
        raw=snapshot_inputs(old);raw.update(clock_at=result['clock_at'],state_revision=result['state_revision'])
        self.assertEqual(packed(result),packed(serialize(raw,allow_synthetic=True)))

    async def test_age_ticks_do_not_supersede_work_and_frozen_lease_stays_original(self):
        old=self.store._state;quote=next(iter(self.store.index(old).values()))['quote']
        held=self.store.create(dict(schema=old['schema'],runtime_id=old['runtime_id'],state_revision=1,
            quote_id=quote['id'],quote_revision=quote['revision'],client_id='owned-temporal'))
        token=held['selection_id'];before=packed(held['review'])
        self.tick[0]=100;self.store.refresh_age()
        await asyncio.sleep(.003)
        job=self.store.temporal.active
        self.tick[0]=101;self.store.refresh_age()
        self.assertIs(self.store.temporal.active,job)
        await self.settle()
        self.assertEqual(self.store.temporal.metrics['started'],1)
        self.assertEqual(packed(self.store.get(token)['review']),before)

    async def test_policy_change_supersedes_and_only_latest_policy_publishes(self):
        a=EstimatePolicy(capital_ceiling_usd='500');b=EstimatePolicy(capital_ceiling_usd='750')
        with patch('app.comparison.estimated_policy.load',new=lambda:a),patch('app.dashboard.current_incremental.load',new=lambda:a):
            self.store.refresh_age();await asyncio.sleep(.005)
            active=self.store.temporal.active;iterator=self.store.temporal.iterator
            with patch('app.comparison.estimated_policy.load',new=lambda:b),patch('app.dashboard.current_incremental.load',new=lambda:b):
                self.store.refresh_age();self.assertTrue(active['cancelled'])
                await self.settle()
                self.assertEqual(self.store._state['estimate_policy'],b.to_dict())
                self.assertIsNone(iterator.gi_frame)
                self.assertGreaterEqual(self.store.temporal.metrics['cancelled'],1)

    async def test_invalid_source_admission_does_not_ack_or_cancel_active_work(self):
        self.tick[0]=901;self.store.refresh_age();await asyncio.sleep(.003)
        old=self.store._state;active=self.store.temporal.active;epoch=self.store._input_epoch
        bad=snapshot_inputs(old);bad['state_revision']=2;bad['events'][0]['groups'][0]['outcome_cardinality']=1
        with self.assertRaises(ValueError):self.store.commit(bad)
        self.assertIs(self.store._state,old);self.assertFalse(active['cancelled']);self.assertEqual(self.store._input_epoch,epoch)
        await self.settle()

    async def test_admitted_packet_cancels_actual_old_iterator_before_publication(self):
        self.tick[0]=901;self.store.refresh_age();await asyncio.sleep(.003)
        iterator=self.store.temporal.iterator;raw=snapshot_inputs(self.store._state);raw['state_revision']=7
        self.assertTrue(self.store.commit(raw))
        self.assertIsNone(iterator.gi_frame,'superseded staging releases before another source admission')
        self.assertIsNone(self.store.temporal.active['previous'])
        self.assertIsNone(self.store.temporal.active['known'])
        await self.settle()
        self.assertEqual(self.store._state['state_revision'],7);self.assertIsNone(iterator.gi_frame)
        self.assertFalse(self.store._economic_invalidated)

    async def test_stop_closes_actual_iterator_writer_readers_and_publication(self):
        old=self.store._state;self.tick[0]=901;self.store.refresh_age()
        # Wait until the real financial projection, not only its aging prelude.
        while self.store.temporal.metrics['units']<20:await asyncio.sleep(.001)
        iterator=self.store.temporal.iterator;driver=self.store.temporal.driver
        owner=self.store.encoded_bodies.encode({'retained':'x'*100000})
        reader=self.store.encoded_bodies.payload(owner,adopt=True);blocked=asyncio.Event()
        class Writer:
            async def write(self,data):blocked.set();await asyncio.Event().wait()
        writing=asyncio.create_task(reader.write(Writer()));await blocked.wait()
        await self.store.close();await asyncio.gather(writing,return_exceptions=True)
        self.assertIsNone(iterator.gi_frame);self.assertTrue(driver.done());self.assertIs(self.store._state,old)
        self.assertIsNone(self.store.temporal.active);self.assertIsNone(self.store.temporal.pending)
        self.assertFalse(self.store.encoded_bodies.readers);self.assertFalse(self.store.encoded_bodies.owners)
        with self.assertRaises(ValueError):self.store.commit(fixture(10))
        self.store.refresh_age();await asyncio.sleep(.01);self.assertIs(self.store._state,old)

    async def test_index_failure_never_publishes_staged_financial_state(self):
        self.tick[0]=901;old=self.store._state
        with patch('app.dashboard.current_deadlines.next_deadline',side_effect=ValueError('authored failure')):
            self.store.refresh_age();await self.store.temporal.driver
        self.assertIs(self.store._state,old);self.assertTrue(self.store._economic_invalidated)
        self.assertIsNotNone(self.store.temporal.failure)
        self.assertIsNone(self.store.temporal.iterator)
        with self.assertRaises(SelectionError) as ctx:self.store.snapshot()
        self.assertEqual(ctx.exception.body['error'],'temporal_failed')

    async def test_real_lifecycle_stop_health_acknowledges_without_reconstruction(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from app.collection.current_service import CurrentService
        from app.collection.current_policy import DEFAULT
        from app.collection.local_ownership import LocalOwnership
        class RefusedAcquisitionWorker:
            def __init__(self,service,venue):self.service=service;self.venue=venue;self.closed=False;self.metrics={'requests':0}
            async def run(self):
                self.service.source_state(self.venue,'unavailable','Authored acquisition refusal')
                await asyncio.Event().wait()
            async def close(self):self.closed=True
        with TemporaryDirectory() as directory:
            root=Path(directory)
            service=CurrentService(config=dict(DEFAULT,aggregate_enabled=False),directory=root/'state',
                ownership=LocalOwnership(root/'owner'),worker_factory=RefusedAcquisitionWorker)
            service.allow_synthetic=True
            store=CurrentStore(service)
            await service.start(store);await asyncio.sleep(0)
            raw=cross_group_workload();raw['state_revision']=10;store.commit(raw)
            store.monotonic=lambda:store._age_origin+901
            store.refresh_age()
            while store.temporal.metrics['units']<20:await asyncio.sleep(.001)
            iterator=store.temporal.iterator;old=store._state;sequence=service.sink.sequence
            with patch('app.dashboard.current_incremental.project',side_effect=AssertionError('Stop cannot rebuild prices')):
                await store.close()
            self.assertIsNone(iterator.gi_frame);self.assertIs(store._state,old)
            self.assertTrue(service.cleanup_complete);self.assertIsNone(service.ownership.file)
            self.assertFalse(service.dispatch);self.assertEqual(service.sink.sequence,sequence+4)
            self.assertTrue(all(value['state']=='stopped' for value in store._shutdown_health.values()))
            self.assertTrue(all(value['state']=='stopped' for value in service.states.values()))
            self.assertFalse(store.temporal.active);self.assertFalse(store.temporal.pending)

    async def test_captured_stream_completes_on_boundary_without_renewing_eligibility(self):
        pool=self.store.encoded_bodies;epoch=self.store._calculation_epoch
        owner=pool.encode({'rows':['é'*40000]*4})
        reader=pool.payload(owner,adopt=True,**self.store.delivery_guards(epoch))
        parts=[]
        class Writer:
            async def write(inner,data):
                parts.append(data);self.tick[0]=901
        await reader.write(Writer())
        self.assertGreater(len(parts),1);self.assertTrue(reader.closed)
        self.assertFalse(self.store.economic_valid(epoch))
        self.assertFalse(pool.owners);self.assertFalse(pool.readers)
        self.assertTrue(self.store._economic_invalidated)

    async def test_utf8_byte_bound_matches_canonical_wire(self):
        from app.dashboard.current_contract import drain,byte_count_steps
        from unittest.mock import patch
        value={'rows':['é🙂']*100}
        self.assertEqual(drain(byte_count_steps(value)),len(packed(value)))
        with patch('app.dashboard.current_contract.MAX_BYTES',len(packed(value))-1):
            with self.assertRaises(ValueError):drain(byte_count_steps(value))


class PendingRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_default_routes_refuse_before_expensive_rebuild(self):
        from aiohttp.test_utils import TestClient, TestServer
        from app.dashboard.multi_game_server import create_app
        from tests.test_current_state import owner
        async with TestClient(TestServer(create_app(owner=owner(),sessions={},current_provider=InjectedTestProvider(cross_group_workload())))) as client:
            store=client.server.app[CURRENT_KEY];old=store._state
            store.monotonic=lambda:store._age_origin+901
            paths=['/api/current','/api/current/changes?runtime_id='+old['runtime_id']+'&state_revision=1',
                '/api/comparison','/api/arbs','/api/current/details?runtime_id='+old['runtime_id']+'&state_revision=1&quote_id=missing']
            for path in paths:
                response=await client.get(path);value=await response.json()
                self.assertEqual(response.status,503,path);self.assertEqual(value['error'],'temporal_pending')
                self.assertNotIn('events',value);self.assertNotIn('rows',value)
            await store.temporal.driver
            response=await client.get('/api/current');self.assertEqual(response.status,200)
