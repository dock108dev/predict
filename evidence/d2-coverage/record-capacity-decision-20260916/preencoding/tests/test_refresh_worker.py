"""Immutable receipt-bound refresh, worker ownership, and publication races."""
import asyncio
from dataclasses import replace
import pickle
import threading
import unittest
from unittest.mock import patch

from app.capture_benchmark import fixture, synthetic_observations
from app.dashboard.controller import Controller, DEFAULTS
from app.dashboard.pipeline import Pipeline
from app.dashboard.refresh import compute, thaw_result
from app.storage.replay import replay
from tests.test_dashboard import FakePipeline, QuietSource


def pipeline():
    p=Pipeline('synthetic',dict(DEFAULTS));p.sid='snapshot-session'
    p.parents,p.matcher,p.contexts,p.rows,books=fixture(4)
    p.titles={r['key']:r['native']['title'] for r in p.rows}
    for book in books:
        for o in synthetic_observations(book,source_time_semantics='unknown'):
            key=(o.quote.raw.ref.venue.value,o.quote.raw.ref.market_id,o.quote.outcome_id)
            p.observations[key]=o;p.current_receipts[key]='receipt:'+str(len(p.current_receipts))
    p.dirty=4
    return p


class SnapshotTests(unittest.TestCase):
    def test_initial_empty_discovery_has_a_view_without_invented_inputs(self):
        p=Pipeline('live',dict(DEFAULTS));p.sid='initial'
        result=thaw_result(compute(p.snapshot(True)))
        self.assertEqual(result['view']['markets'],[])
        self.assertEqual(result['sample']['inputs'],0)
        self.assertEqual(result['receipt_ids'],[])

    def test_artifact_hashes_match_original_wire_format(self):
        from app.storage.store import Store
        cases=[None,{'a':['x'*5000,{'b':'é'*4100}],'z':3},[{'repeated':'test','nested':list(range(100))}]*40]
        expected=['4c9ddd90e346ca332128b39ad498a1cbf7a3b58d8a6060f6dba65bd6fbd04a67',
            '35d4e7a0e3525ffc993bc0fcecb5d29b8d6cf92680a58d8fc031e2f9eed18f31',
            'dd0ec80a94c290b17e9e289ca0c5dd7f0562d4d0dbb82bfd614664d75e0905ea']
        self.assertEqual([x[0] for x in Store(None).compile_many(cases)],expected)

    def test_capture_mutation_cannot_change_inflight_snapshot(self):
        p=pipeline();snap=p.snapshot();frozen=pickle.loads(snap)
        def capture():
            p.observations={k:replace(o,sync='unsynchronized') for k,o in p.observations.items()}
            p.current_receipts={k:'new:'+v for k,v in p.current_receipts.items()}
            p.contexts.clear();p.rows.clear();p.parents.snapshot.clear();p.registry.data.clear()
        thread=threading.Thread(target=capture);thread.start();thread.join()
        result=thaw_result(compute(snap));replay(result['audit'])
        self.assertEqual(result['receipt_ids'],list(frozen['current_receipts'].values()))
        self.assertEqual(result['audit']['input']['options']['registry'],frozen['registry'].data)
        self.assertEqual(result['view']['at'],frozen['evaluation_time'].isoformat())
        self.assertEqual([o['quote']['raw']['received_at'] for o in result['audit']['input']['observations']],
            [o.quote.raw.received_at.isoformat() for o in frozen['observations'].values()])
        self.assertEqual(result['sample']['coalesced'],3)
        self.assertIsNone(p.snapshot())

    def test_snapshot_limit_does_not_consume_dirty_inputs(self):
        p=pipeline();p.titles['oversized']='x'*(9*1024*1024)
        with self.assertRaises(OverflowError):p.snapshot()
        self.assertEqual(p.dirty,4);self.assertEqual(p.snapshot_sequence,0)

    def test_persistence_rejects_old_session_or_out_of_order_before_sql(self):
        p=pipeline();result=compute(p.snapshot());p.seq=99
        self.assertIsNone(p.persist_refresh(result))
        p.seq=0;p.sid='another-session'
        self.assertIsNone(p.persist_refresh(result))


class RefreshFake(FakePipeline):
    def __init__(self,*a):
        super().__init__(*a);self.dirty=0;self.books=[];self.serial=0;self.persisted=[];self.finished=False
    def book(self,b):self.books.append(b);self.dirty+=1
    def disconnect(self,*a):self.dirty+=1
    def snapshot(self,force=False):
        if not self.dirty:return None
        self.serial+=1;self.dirty=0
        return pickle.dumps(dict(sid='test-session',view=dict(sequence=self.serial,books=list(self.books),candidates=[])))
    def persist_refresh(self,result):
        value=pickle.loads(result);self.persisted.append(value);return value
    def record_publication(self,*a):pass
    def finish(self,*a):self.finished=True;super().finish(*a)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.c=Controller(RefreshFake,QuietSource);self.entered=threading.Event();self.release=threading.Event()
    async def asyncTearDown(self):self.release.set();await self.c.close()
    async def ready(self):
        await self.c.start('live',{})
        for _ in range(500):
            if self.c.state=='scanning':return
            await asyncio.sleep(.001)
        self.fail('start did not settle')
    async def until(self,condition):
        for _ in range(1000):
            if condition():return
            await asyncio.sleep(.001)
        self.fail('condition did not settle')
    def blocked_compute(self,snapshot):
        self.entered.set();self.release.wait(2);return snapshot

    async def test_capture_continues_with_one_compute_and_one_pending_signal(self):
        with patch('app.dashboard.refresh.compute',self.blocked_compute):
            await self.ready();self.c.offer(('book',0));await self.until(self.entered.is_set)
            for n in range(1,41):self.assertTrue(self.c.offer(('book',n)))
            await self.until(lambda:len(self.c.worker.books)==41)
            self.assertEqual(self.c.refresh_accounting['submitted'],1)
            self.assertTrue(self.c.refresh_accounting['pending_signal'])
            self.assertFalse(self.c.worker.persisted)
            self.release.set();await self.until(lambda:len(self.c.worker.persisted)==2)
            self.assertEqual(self.c.worker.persisted[-1]['view']['books'],list(range(41)))
            await self.until(lambda:self.c.published_sequence==2)
            self.assertEqual(self.c.view['books'],list(range(41)))
            self.c.request_stop('owner');await self.c.task
            self.assertTrue(self.c.worker.shutdown['refresh_work']['settled'])
            self.assertEqual(self.c.worker.shutdown['unprocessed'],0)

    async def test_disconnect_during_compute_discards_old_completion(self):
        with patch('app.dashboard.refresh.compute',self.blocked_compute):
            await self.ready();self.c.offer(('book',1));await self.until(self.entered.is_set)
            self.c.view=dict(markets=[],candidates=[dict(legs=[],current_opportunity=True)])
            epoch=self.c.eligibility_epoch;self.c.offer(('disconnect',('kalshi','lost')))
            self.assertGreater(self.c.eligibility_epoch,epoch)
            self.assertFalse(self.c.view['candidates'][0]['current_opportunity'])
            self.release.set();await self.until(lambda:self.c.refresh_accounting['discarded']>=1)
            self.assertNotEqual(self.c.published_sequence,1)
            self.c.request_stop('owner');await self.c.task

    async def test_stop_during_compute_and_depth_settles_before_finish(self):
        depth_entered=threading.Event();depth_release=threading.Event()
        with patch('app.dashboard.refresh.compute',self.blocked_compute):
            await self.ready();self.c.offer(('book',1));await self.until(self.entered.is_set)
            await self.until(lambda:not self.c.inflight)
            def depth(cid):depth_entered.set();depth_release.wait(2);return dict(id=cid)
            self.c.worker.depth=depth
            request=asyncio.create_task(self.c.depth('x'));await self.until(depth_entered.is_set)
            self.c.request_stop('owner');await asyncio.sleep(.02)
            self.assertFalse(self.c.worker.finished);self.assertFalse(self.c.task.done())
            self.release.set();depth_release.set();await request;await self.c.task
            self.assertIsNone(self.c.depth_result);self.assertEqual(self.c.published_sequence,0)
            self.assertTrue(self.c.worker.finished)

    async def test_compute_and_publication_failure_stop_and_account(self):
        for failure in ('compute','publication'):
            with patch('app.dashboard.refresh.compute',side_effect=RuntimeError('compute')) if failure=='compute' else patch('app.dashboard.refresh.compute',lambda x:x):
                await self.ready()
                if failure=='publication':self.c.worker.persist_refresh=lambda x:(_ for _ in ()).throw(RuntimeError('publication'))
                self.c.offer(('book',1));await asyncio.wait_for(self.c.task,2)
                self.assertEqual(self.c.state,'failed')
                self.assertEqual(self.c.refresh_accounting['failed'],1)
                self.assertEqual(self.c.worker.shutdown['processed'],1)
                self.assertTrue(self.c.worker.shutdown['refresh_work']['settled'])

    async def test_out_of_order_and_prior_session_completion_cannot_publish(self):
        await self.ready();generation=self.c.generation;epoch=self.c.eligibility_epoch
        def result(n):return dict(sid=self.c.sid,view=dict(sequence=n,candidates=[]))
        self.assertTrue(self.c.publish_refresh(result(2),generation,epoch))
        self.assertFalse(self.c.publish_refresh(result(1),generation,epoch))
        self.c.request_stop('owner');await self.c.task;await self.ready()
        self.assertFalse(self.c.publish_refresh(result(3),generation,epoch))
        self.assertEqual(self.c.published_sequence,0)

    async def test_dedicated_writer_failure_closes_before_finalization(self):
        for stage in ('compute','publication'):
            await self.ready();closed=[];entered=[]
            class Dedicated:
                def run(inner,snapshot):
                    entered.append(threading.get_ident())
                    raise RuntimeError(stage+' failed')
                def close(inner):closed.append(threading.get_ident())
            self.c.refresh_writer=Dedicated()
            self.c.offer(('book',1));await asyncio.wait_for(self.c.task,2)
            self.assertEqual(self.c.state,'failed')
            self.assertEqual(self.c.refresh_accounting['failed'],1)
            self.assertEqual(self.c.worker.shutdown['processed'],1)
            self.assertTrue(self.c.worker.shutdown['refresh_work']['settled'])
            self.assertTrue(closed);self.assertEqual(set(entered),set(closed))
