"""Controlled U3 lifecycle/admission faults. No provider or credential I/O."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from app.collection.current_policy import DEFAULT, validate
from app.collection.current_service import CurrentService
from app.collection.local_ownership import LocalOwnership
from app.collection.current_sink import LatestStateSink, utc
from app.collection.transport_session import JournalSink, ObservationJournal, reopen, TransportSession
from app.dashboard.current_state import CurrentStore, SelectionError
from app.dashboard.multi_game_server import create_app
from tests.test_current_state import owner, request


def native_fixture():
    from tests.test_nfl_lines import fixture
    e=deepcopy(fixture()[1]['inventory']['kalshi']['events'][0])
    e['id']='test-current-event'
    m=dict(id='test-current-market',event_id=e['id'],market_type='moneyline',period='full_game',status='active',
        exclusion=None,sides=[dict(id='yes',role='yes'),dict(id='no',role='no')])
    binding=dict(version='manual-comparison-2',sha256='test-current-binding',status='BOUND_RAW_PREDICATE',
        identity=dict(family='moneyline',period='full_game',line=None),predicate=[dict(native_id='yes',participant=e['home'],predicate='win'),dict(native_id='no',participant=e['home'],predicate='not_win')])
    m['v1_raw_binding']=binding
    cat=dict(events=[e],markets=[m],selection=dict(ids=[m['id']]))
    at=utc()
    book=dict(raw=dict(ref=dict(venue='kalshi',event_id=e['id'],market_id=m['id']),kind='observation',received_at=at,exchange_at=at,json_text='{}'),
        outcomes=[dict(outcome_id=n,asks=dict(depth='full',levels=[dict(price=dict(value=p),quantity=dict(value='5',unit='contracts'))]),bids=None) for n,p in [('yes','.48'),('no','.53')]],
        state='active',sync='synchronized',sequence='1',quantity_unit='contracts')
    return cat,book


class FakeWorker:
    starts=[]
    def __init__(self,service,venue):self.service=service;self.venue=venue;self.closed=False;self.metrics={'requests':0};self.close_count=0
    async def run(self):
        self.starts.append(self.venue)
        if self.venue=='polymarket_us':
            self.service.source_state(self.venue,'unavailable','CONTROLLED missing credentials')
        await asyncio.Event().wait()
    async def close(self):self.closed=True;self.close_count+=1


class ServiceLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        FakeWorker.starts=[]
        self.service=CurrentService(directory=self.root/'state',ownership=LocalOwnership(self.root/'owner.lock'),worker_factory=FakeWorker)
        self.store=CurrentStore(self.service)
    async def asyncTearDown(self):await self.store.close();self.temp.cleanup()
    async def test_start_attachment_single_workers_consumed_record_shutdown(self):
        await self.service.start(self.store);await self.service.start(self.store);await asyncio.sleep(0)
        self.assertEqual(sorted(FakeWorker.starts),['kalshi','polymarket_us'])
        records=list((self.root/'state').glob('attempt-*.json'));self.assertEqual(len(records),1)
        self.assertTrue(self.service.ownership.file)
        await self.store.close();await self.service.close()
        self.assertTrue(self.service.cleanup_complete);self.assertIsNone(self.service.ownership.file)
        self.assertEqual(len(records),1)
    async def test_multiple_tabs_admin_security_and_legacy_conflict(self):
        async with TestClient(TestServer(create_app(owner=owner(),sessions={},current_provider=self.service))) as c:
            a=await c.get('/api/current/updates');b=await c.get('/api/current/updates')
            for response in (a,b):await response.content.readline()
            for _ in range(3):self.assertEqual((await c.get('/')).status,200);await c.get('/api/current')
            self.assertEqual(sorted(FakeWorker.starts),['kalshi','polymarket_us'])
            origin=str(c.make_url('/')).rstrip('/')
            denied=await c.post('/api/start',json={},headers={'Origin':origin});self.assertEqual(denied.status,409)
            self.assertEqual((await c.post('/api/admin/current',json={'action':'stop'})).status,403)
            self.assertEqual((await c.post('/api/admin/current',json={'action':'pause','source':'kalshi'},headers={'Origin':origin})).status,200)
            self.assertFalse(self.service.workers['polymarket_us'].closed)
            a.close();b.close()
            self.assertEqual((await c.post('/api/admin/current',json={'action':'stop'},headers={'Origin':origin})).status,200)
    async def test_competing_process_and_retained_transport_ownership(self):
        await self.service.start(self.store)
        import subprocess,sys
        code='from app.collection.local_ownership import LocalOwnership; import sys; LocalOwnership(sys.argv[1]).acquire("competing")'
        result=await asyncio.to_thread(subprocess.run,[sys.executable,'-c',code,str(self.root/'owner.lock')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        other=CurrentService(directory=self.root/'other',ownership=LocalOwnership(self.root/'owner.lock'),worker_factory=FakeWorker)
        store=CurrentStore(other)
        await other.start(store)
        self.assertFalse(other.dispatch);self.assertFalse(list((self.root/'other').glob('attempt-*.json')))
        await store.close()
        self.assertTrue(self.service.ownership.file)
        from unittest.mock import AsyncMock
        retained=object.__new__(TransportSession)
        retained.spec={'mode':'real'};retained.sid='controlled-retained-competitor'
        retained._start_owned=AsyncMock()
        with patch('app.collection.local_ownership.LocalOwnership',side_effect=lambda:LocalOwnership(self.root/'owner.lock')):
            with self.assertRaises(ValueError):await retained.start()
        retained._start_owned.assert_not_awaited()
    async def test_cancellation_cleanup_failure_keeps_ownership(self):
        await self.service.start(self.store);await asyncio.sleep(0)
        async def fail():raise OSError('CONTROLLED sensitive content must not appear')
        self.service.workers['kalshi'].close=fail
        await self.service.close()
        self.assertFalse(self.service.cleanup_complete);self.assertTrue(self.service.ownership.file)
        self.assertNotIn('sensitive',str(self.service.status()))
        self.service.workers['kalshi'].close=FakeWorker.close.__get__(self.service.workers['kalshi'])
        # Repair cannot claim the failed cleanup was safe; task teardown explicitly releases its disposable lock.
        self.service.ownership.release()
    async def test_resource_pressure_stops_without_cap_increase(self):
        self.service.config['rss_bytes']=1
        await self.service.start(self.store)
        await asyncio.sleep(.05)
        self.assertFalse(self.service.dispatch);self.assertTrue(self.service.cleanup_complete)
        self.assertTrue(any(i['code']=='rss_cap' for i in self.service.issues))


class SinkAdmission(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service=CurrentService(config=dict(DEFAULT,enabled=False))
        self.store=CurrentStore(self.service)
        self.service.store=self.store;self.service.sink=LatestStateSink(self.store,self.service.initial_state());self.service.dispatch=True
        self.cat,self.book=native_fixture()
        self.service.catalog('kalshi',self.cat);self.service.book('kalshi',self.book)
    async def asyncTearDown(self):await self.store.close()
    async def test_ephemeral_no_journal_cursor_and_identical_image_clocks(self):
        sink=self.service.sink;self.assertEqual(sink.reducer.cursor,0);self.assertEqual(sink.reducer.chain,'0'*64)
        state=self.store.snapshot();old=next(iter(self.store.index(state).values()))['quote']
        self.assertEqual(old['original']['value'],'.48');self.assertTrue(old['comparison']['eligible'])
        repeated=deepcopy(self.book);repeated['raw']['received_at']=utc();repeated['raw']['exchange_at']=utc()
        self.service.book('kalshi',repeated)
        new=self.store.index(self.store.snapshot())[old['id']]['quote']
        self.assertEqual(new['revision'],old['revision']);self.assertEqual(new['times'],old['times'])
    async def test_bad_commit_atomic_reducer_failure_isolated_and_recovery(self):
        sink=self.service.sink;sequence=sink.sequence;previous=deepcopy(sink.reducer.books)
        with self.assertRaises(ValueError):sink.commit(self.service.row('coverage_inventory','kalshi',inventory={},generation=2,previous_generation=-1),self.service.states)
        self.assertEqual(sink.sequence,sequence);self.assertEqual(sink.reducer.books,previous)
        with patch.object(self.store,'commit',side_effect=ValueError('CONTROLLED serialization rejection')):
            with self.assertRaises(ValueError):sink.commit(self.service.row('source_health','kalshi',state='unavailable'),self.service.states)
        self.assertEqual(sink.sequence,sequence)
        self.service.source_state('kalshi','resyncing','CONTROLLED recovery')
        q=next(iter(self.store.index(self.store.snapshot()).values()))['quote'];self.assertFalse(q['comparison']['eligible'])
        self.service.book('kalshi',self.book)
        q=next(iter(self.store.index(self.store.snapshot()).values()))['quote'];self.assertTrue(q['comparison']['eligible'])
    async def test_native_empty_side_depth_clock_and_rejected_book_recovery(self):
        old=next(iter(self.store.index(self.store.snapshot()).values()))['quote']
        depth=deepcopy(self.book);depth['raw']['exchange_at']=utc();depth['raw']['received_at']=utc()
        depth['outcomes'][0]['asks']['levels'][0]['quantity']['value']='7'
        self.service.book('kalshi',depth)
        q=self.store.index(self.store.snapshot())[old['id']]['quote']
        self.assertGreater(q['revision'],old['revision']);self.assertEqual(q['times'],old['times'])
        empty=deepcopy(depth);empty['outcomes'][1]['asks']['levels']=[]
        self.service.book('kalshi',empty)
        group=self.store.snapshot()['events'][0]['groups'][0]
        self.assertEqual(len(group['outcomes']),2);self.assertEqual(len(self.store.index(self.store.snapshot())),1)
        malformed=deepcopy(depth);malformed['outcomes']=malformed['outcomes'][:1]
        with self.assertRaises(ValueError):self.service.book('kalshi',malformed)
        self.assertEqual(self.service.states['kalshi']['state'],'resyncing')
        self.service.book('kalshi',depth)
        self.assertEqual(len(self.store.index(self.store.snapshot())),2)
        self.assertTrue(all(x['quote']['state']=='available' for x in self.store.index(self.store.snapshot()).values()))
    async def test_separate_native_winner_predicate_domains_do_not_merge_four_outcomes(self):
        other=deepcopy(self.cat);m=deepcopy(other['markets'][0]);m['id']='other-winner'
        for p in m['v1_raw_binding']['predicate']:p['participant']=other['events'][0]['away']
        m['v1_raw_binding']['sha256']='other-winner-binding';other['markets'].append(m)
        self.service.catalog('kalshi',other)
        b=deepcopy(self.book);b['raw']['ref']['market_id']=m['id'];self.service.book('kalshi',b)
        groups=self.store.snapshot()['events'][0]['groups']
        self.assertEqual(len(groups),2);self.assertTrue(all(len(g['outcomes'])==2 for g in groups))
    async def test_held_prices_update_aging_catalog_retirement_shutdown(self):
        held=self.store.create(request(self.store));frozen=deepcopy(held['review'])
        changed=deepcopy(self.book);changed['outcomes'][0]['asks']['levels'][0]['price']['value']='.49'
        self.service.book('kalshi',changed)
        self.assertEqual(self.store.get(held['selection_id'])['review'],frozen)
        self.assertEqual(self.store.get(held['selection_id'])['status'],'newer_available')
        self.service.catalog('kalshi',dict(events=[],markets=[],selection=dict(ids=[])))
        self.assertEqual(self.store.snapshot()['events'],[])
        self.assertEqual(self.store.get(held['selection_id'])['review'],frozen)
        await self.service.close()
        with self.assertRaises(SelectionError):self.store.get(held['selection_id'])
    async def test_oversize_ingress_rejected_before_swap(self):
        sequence=self.service.sink.sequence
        with self.assertRaises(ValueError):self.service.sink.commit(self.service.row('source_health','kalshi',state='connected',padding='x'*(8*1024*1024)),self.service.states)
        self.assertEqual(self.service.sink.sequence,sequence)
    async def test_unverified_source_event_inspectable_without_cues(self):
        cat=deepcopy(self.cat);cat['events'][0].pop('game_id');self.service.catalog('kalshi',cat);self.service.book('kalshi',self.book)
        q=next(iter(self.store.index(self.store.snapshot()).values()))['quote']
        self.assertTrue(q['display']['supported']);self.assertFalse(q['comparison']['eligible'])


class DurableSink(unittest.TestCase):
    def test_original_journal_fsync_and_exact_chain_replay(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'observations.jsonl';journal=ObservationJournal(p);sink=JournalSink(journal)
            ack=sink.commit(dict(type='session_finished',observed_at=utc()))
            journal.close();r=reopen(p)
            self.assertEqual(ack['acknowledgment'],'durable-journal-acknowledgment');self.assertEqual(ack['cursor'],1)
            self.assertEqual(ack['chain'],r['sha256']);self.assertEqual(r['state'],'complete')
    def test_policy_ceiling_and_scope_fail_closed(self):
        for key,value in [('duration_seconds',3601),('rediscovery_seconds',1),('rss_bytes',512*1024*1024),('enabled',1)]:
            with self.assertRaises(ValueError):validate(dict(DEFAULT,**{key:value}))
