"""Real retained validation/projection, explicit outcomes and atomic ownership."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.dashboard.current_contract import packed, serialize, quotes_of
from app.dashboard.current_state import CurrentStore
from tests.current_fixture import InjectedTestProvider, fixture
from tests.test_ev06_pairs import cross_group_workload


class RetainedAdmission(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.raw=fixture(2)
        self.store=CurrentStore(InjectedTestProvider(dict(self.raw,events=[],comparison_profiles={})),monotonic=lambda:0)
        self.store._state['state_revision']=1

    async def asyncTearDown(self):await self.store.close()

    async def test_success_owns_input_exact_full_state_and_reconciles_identity(self):
        raw=cross_group_workload();raw['state_revision']=2
        expected=serialize(deepcopy(raw),allow_synthetic=True)
        future=self.store.admission.submit(raw)
        generation=self.store.admission.page()['generation_id']
        pending=self.store.admission.page(settings_generation=7)
        self.assertIsNone(pending['input_epoch']);self.assertIsNone(pending['state_revision'])
        self.assertIsNone(pending['progress']['total_pairs'])
        raw['events'].clear()
        outcome=await asyncio.wait_for(asyncio.shield(future),20)
        self.assertEqual(outcome.status,'success')
        with self.assertRaises(TypeError):bool(outcome)
        self.assertEqual(packed(expected),packed(self.store._state))
        ready=self.store.admission.page(settings_generation=7,generation_id=generation)
        self.assertEqual(ready['status'],'ready');self.assertEqual(ready['input_epoch'],1)
        p=ready['progress'];self.assertEqual(p['pending_singles'],0);self.assertEqual(p['pending_pairs'],0)
        self.assertEqual(p['total_singles'],p['ready_singles']+p['refused_singles'])
        self.assertEqual(p['total_pairs'],p['ready_pairs']+p['refused_pairs'])
        self.assertTrue(ready['rows']);self.assertEqual(ready['settings_generation'],7)

    async def test_long_native_identifiers_keep_existing_current_capacity(self):
        raw=deepcopy(self.raw)
        q=quotes_of(raw['events'][0]['groups'][0]['outcomes'][0])[0]
        q['source']['native_market_id']='𐀀'*2048
        outcome=await self.store.admission.submit(raw)
        self.assertEqual(outcome.status,'success')
        from app.dashboard.current_admission import rows_of
        self.assertIn('𐀀'*2048,[r['native']['market_id'] for r in rows_of(self.store._state)])

    async def test_reader_capacity_disconnect_and_stop_close_blocked_write(self):
        from app.dashboard.current_admission import PriceReader
        from types import SimpleNamespace
        future=self.store.admission.submit(self.raw)
        owner=self.store.admission;request=SimpleNamespace(task=None)
        readers=[PriceReader(owner,b'{}',request) for _ in range(owner.MAX_READERS)]
        with self.assertRaises(ValueError):PriceReader(owner,b'{}',request)
        readers[0].release();self.assertEqual(owner.readers,15)
        blocked=asyncio.Event()
        class Writer:
            async def write(self,body):blocked.set();await asyncio.Event().wait()
        writing=asyncio.create_task(readers[1].write(Writer()));await blocked.wait()
        await self.store.close();await asyncio.gather(writing,return_exceptions=True)
        self.assertEqual(owner.readers,0);self.assertFalse(owner.payloads)
        self.assertEqual((await future).status,'stopped')
        self.assertTrue(all(r.closed for r in readers))

    async def test_reads_reuse_one_owned_generation(self):
        future=self.store.admission.submit(self.raw)
        self.assertIs(self.store.admission.submit(deepcopy(self.raw)),future)
        ids={self.store.admission.page(settings_generation=i)['generation_id'] for i in range(12)}
        self.assertEqual(len(ids),1)
        self.assertEqual((await future).status,'success')
        self.assertEqual(self.store.admission.metrics['started'],1)

    async def test_malformed_native_units_clocks_reject_preserving_previous(self):
        before=packed(self.store._state)
        for field in ('native','units','clock','binding'):
            bad=deepcopy(self.raw);q=quotes_of(bad['events'][0]['groups'][0]['outcomes'][0])[0]
            if field=='native':q['source']['native_market_id']=''
            elif field=='units':q['original']['units']='unknown_currency'
            elif field=='clock':q['times']['source_at']='yesterday'
            else:q['binding']['selection']['event_id']='conflict'
            outcome=await self.store.admission.submit(bad)
            self.assertEqual(outcome.status,'rejection',field)
            self.assertIsNone(outcome.input_epoch);self.assertEqual(packed(self.store._state),before)
            page=self.store.admission.page();self.assertEqual(page['rows'],[]);self.assertIsNone(page['state_revision'])
        self.assertEqual(self.store._input_epoch,0)

    async def test_supersession_closes_original_iterator_without_acknowledgement(self):
        first=self.store.admission.submit(self.raw)
        await asyncio.sleep(0)
        iterator=self.store.admission.iterator
        raw=deepcopy(self.raw);raw['runtime_id']='synthetic:replacement'
        second=self.store.admission.submit(raw)
        self.assertEqual((await first).status,'supersession')
        self.assertEqual((await second).status,'success')
        self.assertIsNone(iterator.gi_frame)
        self.assertEqual(self.store._input_epoch,1)

    async def test_stop_during_bootstrap_closes_iterator_and_never_installs(self):
        future=self.store.admission.submit(self.raw)
        await asyncio.sleep(0);iterator=self.store.admission.iterator
        await self.store.close()
        self.assertEqual((await future).status,'stopped');self.assertIsNone(iterator.gi_frame)
        self.assertEqual(self.store._input_epoch,0);self.assertIsNone(self.store.admission.active)
        self.assertEqual(self.store.admission.page()['status'],'stopped')
        self.assertEqual(self.store.admission.page()['rows'],[])

    async def test_stop_during_financial_admission_releases_actual_owned_generator(self):
        raw=cross_group_workload();raw['state_revision']=2
        future=self.store.admission.submit(raw)
        while self.store.admission.page()['progress']['discovery_status']!='evaluating':await asyncio.sleep(0)
        iterator=self.store.admission.iterator
        self.assertTrue(self.store.admission.page()['rows'])
        await self.store.close()
        self.assertEqual((await future).status,'stopped');self.assertIsNone(iterator.gi_frame)
        self.assertEqual(self.store._input_epoch,0);self.assertEqual(len(self.store.encoded_bodies.owners),0)

    async def test_cancelled_future_revokes_publication(self):
        future=self.store.admission.submit(self.raw);await asyncio.sleep(0)
        future.cancel();await self.store.admission.driver
        self.assertEqual(self.store._input_epoch,0);self.assertEqual(self.store.admission.page()['status'],'stopped')
        self.assertEqual(self.store.admission.page()['rows'],[])

    async def test_policy_change_supersedes_pending_progress(self):
        from app.comparison.estimated_policy import EstimatePolicy
        future=self.store.admission.submit(self.raw)
        with patch('app.comparison.estimated_policy.load',new=lambda:EstimatePolicy(capital_ceiling_usd='500')):
            page=self.store.admission.page()
            self.assertEqual(page['status'],'superseded');self.assertIsNone(page['input_epoch'])
            self.assertEqual((await future).status,'supersession')
        await self.store.admission.driver
        self.assertEqual(self.store._input_epoch,0)

    async def test_timeout_rejects_complete_admission(self):
        future=self.store.admission.submit(self.raw);self.store.admission.latest['deadline']=0
        self.assertEqual((await future).status,'rejection');self.assertEqual(self.store._input_epoch,0)

    async def test_harmless_clock_shell_does_not_supersede_owned_input(self):
        future=self.store.admission.submit(self.raw);await asyncio.sleep(0)
        # Same complete revision/epoch, as used by harmless temporal updates.
        self.store._state=dict(self.store._state)
        self.assertEqual((await future).status,'success');self.assertEqual(self.store._input_epoch,1)

    async def test_eligibility_boundary_rejects_without_relabeling_or_ack(self):
        raw=cross_group_workload();raw['state_revision']=2
        before=packed(self.store._state)
        future=self.store.admission.submit(raw)
        from datetime import timedelta
        from app.dashboard.current_contract import stamp
        self.store._clock_origin=stamp(raw['clock_at'])+timedelta(days=2)
        self.assertEqual((await future).status,'supersession')
        self.assertEqual(future.result().error,'eligibility_changed')
        self.assertEqual(packed(self.store._state),before);self.assertEqual(self.store._input_epoch,0)
        latest=self.store.admission.latest
        self.assertEqual(latest['input_clock_at'],raw['clock_at'])
        self.assertEqual((await latest['future']).status,'success')
        self.assertEqual(self.store._input_epoch,1)

    async def test_native_number_stays_useful_with_unknown_payout(self):
        raw=deepcopy(self.raw)
        q=quotes_of(raw['events'][0]['groups'][0]['outcomes'][0])[0];q['original']['payout']=None
        future=self.store.admission.submit(raw)
        while self.store.admission.page()['progress']['discovery_status']=='validating_prices':await asyncio.sleep(0)
        page=self.store.admission.page()
        self.assertTrue(any(r['original']['payout'] is None for r in page['rows']))
        self.assertIsNone(page['input_epoch'])
        await future

    async def test_owned_install_never_resets_validation_clock_to_old_calculation(self):
        from datetime import timedelta
        from app.dashboard.current_contract import stamp
        tick=[0];self.store.monotonic=lambda:tick[0];self.store._age_origin=0
        self.store._clock_origin=stamp(self.raw['clock_at'])
        future=self.store.admission.submit(self.raw);await asyncio.sleep(0);tick[0]=100
        self.assertEqual((await future).status,'success')
        self.assertEqual(self.store.validation_clock(),stamp(self.raw['clock_at'])+timedelta(seconds=100))

    async def test_pagination_identity_and_query_fail_closed(self):
        await self.store.admission.submit(self.raw)
        for query in (dict(page=1),dict(generation_id='late-body'),dict(page=-1),dict(settings_generation=True)):
            with self.assertRaises(ValueError):self.store.admission.page(**query)

    async def test_new_complete_source_commit_supersedes_queued_candidate_only_after_success(self):
        future=self.store.admission.submit(self.raw)
        bad=deepcopy(self.raw);bad['events'][0]['groups'][0]['outcome_cardinality']=1
        with self.assertRaises(ValueError):self.store.commit(bad)
        self.assertFalse(future.done());self.assertEqual(self.store._input_epoch,0)
        self.assertTrue(self.store.commit(self.raw));self.assertEqual((await future).status,'supersession')
        await self.store.admission.driver;self.assertEqual(self.store._input_epoch,1)

    async def test_opt_in_retained_initialization_is_pending_without_financial_ack(self):
        provider=InjectedTestProvider(self.raw);provider.retained_bootstrap=True
        store=CurrentStore(provider,monotonic=lambda:0)
        try:
            self.assertEqual(store._state['events'],[]);self.assertEqual(store._input_epoch,0)
            self.assertEqual(store.admission.page()['status'],'pending')
            self.assertEqual((await store.admission.latest['future']).status,'success')
            self.assertEqual(store._state['runtime_id'],self.raw['runtime_id'])
        finally:await store.close()


class Compatibility(unittest.TestCase):
    def test_five_outcomes_keep_unknown_totals_explicit(self):
        fixtures=json.loads(Path('app/fixtures/retained-prices-v1.json').read_text())
        self.assertEqual({v['status'] for v in fixtures},{'pending','ready','rejected','superseded','stopped'})
        for value in fixtures:
            if value['status']!='ready':
                self.assertIsNone(value['state_revision']);self.assertIsNone(value['input_epoch'])
                self.assertIsNone(value['progress']['total_pairs'])


if __name__=='__main__':unittest.main()
