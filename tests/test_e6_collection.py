import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from app.collection.session import Session,checked,compute
from app.collection.synthetic import WallClock,knowledge,ReferenceTransport,PredictionTransport,DiscoveryTransport
from app.collection.environment import Environment
from app.collection.storage import Repository
from app.collection.reopen import reopen
from app.pricing.baseline import calculate
from app.reference.records import as_of,Receipt
from app.pricing.fixtures import records,receipt
from app.reference.fixtures import before
from app.opportunities.fixtures import inputs


class BoundsTests(unittest.TestCase):
    def test_reject_nonfinite_and_expansion(self):
        for value in (0,-1,float('inf'),float('nan'),True,901):
            with self.assertRaises(ValueError):checked({'seconds':value})
        with self.assertRaises(ValueError):checked({'queue_items':1.5})

    def test_latest_invalid_and_stale(self):
        src,assessed,target=knowledge();clock=WallClock();at=clock.now()
        from app.reference.enrichment import enrich
        from app.reference.fixtures import payload
        r=receipt(payload().replace(before(65).encode(),at.encode()),at=at)
        history=(src,r,enrich(r,src,assessed))
        estimate=calculate(as_of(history,at),target=target,cutoff=at,estimated_at=at)
        self.assertEqual(estimate.data['status'],'degraded')
        later=clock.now();invalid=receipt(b'bad json',identity='latest-invalid',at=later)
        result=calculate(as_of((*history,invalid,enrich(invalid,src,assessed)),later),target=target,cutoff=later,estimated_at=later)
        self.assertEqual(result.data['status'],'unavailable')
        from datetime import datetime,timedelta
        stale=(datetime.fromisoformat(at)+timedelta(seconds=50)).isoformat()
        self.assertEqual(calculate(as_of(history,stale),target=target,cutoff=stale,estimated_at=stale).data['status'],'unavailable')


class DurableTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='e6-check-');self.out=Path(self.temp.name)
        self.env=await asyncio.to_thread(Environment.create);self.db=self.env.connect();self.session=None
    async def asyncTearDown(self):
        if self.session and self.session.task and not self.session.task.done():await self.session.stop()
        self.db.close();await asyncio.to_thread(self.env.remove,self.out/'cleanup');self.temp.cleanup()
    def build(self,**overrides):
        limits=checked({**dict(seconds=6,prediction_poll=.3,reference_poll=.6,discovery_poll=.3,calculation_poll=.6),**overrides})
        clock=WallClock();src,assessed,target=knowledge();cutoff=clock.now()
        template=inputs(estimate=calculate(as_of([src],cutoff),target=target,cutoff=cutoff,estimated_at=cutoff))
        transports={b['observation']['quote']['raw']['ref']['venue']:PredictionTransport(b['observation']['quote']['raw']['ref']['venue'],b,clock) for b in template['market']['books']}
        transports.update(reference=ReferenceTransport(clock,interruption=None),discovery=DiscoveryTransport())
        self.session=Session(Repository(self.db,self.out,limits),clock,self.out,limits,transports)
        return self.session
    async def test_manual_stop_and_exact_reopening(self):
        s=self.build();await s.start();await asyncio.sleep(2);await s.stop()
        self.assertEqual(s.state,'completed');self.assertTrue(s.producers_closed)
        self.assertEqual(s.delivered,s.persisted);self.assertEqual(s.queue.qsize(),0)
        saved=await asyncio.to_thread(reopen,self.out/s.sid)
        self.assertGreater(saved['calculations'],0)
        self.assertTrue(all(t.closed for t in s.transports.values()))
        # Tampered evidence fails closed, including observation ledger.
        p=self.out/s.sid/'session.json';p.write_text(p.read_text()+' ')
        with self.assertRaises(ValueError):reopen(self.out/s.sid)
    async def test_quota(self):
        s=self.build();s.transports['reference'].failure='quota';await s.start();await s.task
        self.assertEqual(s.state,'failed');self.assertEqual(s.reason,'quota_exhausted')
        self.assertEqual(s.repo.counts(s.sid)['reference'],1)
    async def test_entitlement(self):
        s=self.build();s.transports['reference'].failure='entitlement';await s.start();await s.task
        self.assertEqual(s.state,'failed');self.assertEqual(s.reason,'entitlement_stop')
    async def test_capacity_pressure_preserves_delivery(self):
        s=self.build(queue_items=1);await s.start();await s.task
        self.assertEqual(s.state,'failed');self.assertIn('capacity',s.reason)
        self.assertLessEqual(s.queue.high_items,1)
        journal=[json.loads(x) for x in (self.out/(s.sid+'.journal.jsonl')).read_text().splitlines()]
        self.assertEqual(sum(x['type']=='delivered' for x in journal),s.delivered)
    async def test_schedule(self):
        s=self.build();s.transports['discovery'].change='schedule';await s.start();await s.task
        self.assertEqual(s.state,'failed');self.assertIn('schedule',s.reason)
        self.assertIsNone(s.status()['view'])
    async def test_disappearance(self):
        s=self.build();s.transports['discovery'].change='disappearance';await s.start();await s.task
        self.assertEqual(s.state,'failed');self.assertIn('scope',s.reason)
    async def test_identity(self):
        s=self.build();s.transports['discovery'].change='identity';await s.start();await s.task
        self.assertEqual(s.state,'failed')
    async def test_kickoff(self):
        s=self.build();s.transports['discovery'].change='kickoff';await s.start();await s.task
        self.assertEqual(s.state,'failed')
    async def test_prediction_recovery(self):
        s=self.build();t=s.transports['kalshi'];t.interruption=.5;t.outage=.5
        await s.start();await asyncio.sleep(.8)
        self.assertEqual(s.health['kalshi']['state'],'disconnected');self.assertIsNone(s.status()['view'])
        await asyncio.sleep(1.5);await s.stop()
        rows=self.db.execute('SELECT detail FROM coverage_event WHERE session_id=%s',(s.sid,)).fetchall()
        self.assertTrue(any(r['detail'].get('e6_ingress',{}).get('value',{}).get('reason')=='observed_recovery' for r in rows))
    async def test_primary_failure_fallback(self):
        s=self.build();await s.start();await asyncio.sleep(.5);self.db.close();await s.task
        self.assertEqual(s.state,'failed');self.assertIn('closed',s.storage_error)
        journal=[json.loads(x) for x in (self.out/(s.sid+'.journal.jsonl')).read_text().splitlines()]
        self.assertTrue(any(x['type']=='fallback_failure' for x in journal))
    async def test_restart_marks_unfinished_without_crash_time(self):
        repo=Repository(self.db,self.out,checked({}));src,_,_=knowledge();repo.start('unfinished-e6',src,checked({}))
        recovered=repo.recover();self.assertEqual(recovered[0]['state'],'interrupted');self.assertIsNone(recovered[0]['crash_at'])
        self.assertEqual(repo.recover(),[])
    async def test_stopping_waits_for_export(self):
        import threading
        s=self.build();entered=threading.Event();release=threading.Event();original=s.repo.export
        def slow_export(sid):
            entered.set();release.wait(timeout=3);return original(sid)
        s.repo.export=slow_export
        await s.start();await asyncio.sleep(.5)
        task=asyncio.create_task(s.stop())
        await asyncio.to_thread(entered.wait,2)
        try:
            self.assertEqual(s.state,'stopping');self.assertFalse(task.done())
        finally:release.set()
        await task;self.assertEqual(s.state,'completed')
    async def test_slow_persistence_bounds_and_keeps_loop_responsive(self):
        import time
        s=self.build(queue_items=6);original=s.repo.persist
        def slow(item):time.sleep(.15);return original(item)
        s.repo.persist=slow
        await s.start();ticks=0
        while not s.task.done() and ticks<20:
            await asyncio.sleep(.05);ticks+=1
        await s.stop()
        self.assertGreaterEqual(ticks,5)
        self.assertLessEqual(s.queue.high_items,6)
        self.assertEqual(s.calculations,0) # never snapshots an in-flight receipt
    async def test_storage_capacity_stops_before_write(self):
        s=self.build(storage_bytes=1);await s.start();await s.task
        self.assertEqual(s.state,'failed');self.assertEqual(s.repo.used,0)
        self.assertEqual(s.repo.counts(s.sid)['prediction'],0)
    async def test_transient_retry_exhaustion(self):
        s=self.build(retries=1);s.transports['kalshi'].interruption=0;s.transports['kalshi'].outage=60
        await s.start();await s.task
        self.assertEqual(s.state,'failed');self.assertIn('retries exhausted',s.reason)
    async def test_exact_repeat_receipts_are_not_deduplicated(self):
        s=self.build();transport=s.transports['reference'];original=transport.request;prior=[]
        async def repeat(request):
            response=await original(request)
            if not prior:prior.append(response)
            return prior[0]
        transport.request=repeat
        await s.start();await asyncio.sleep(1.5);await s.stop()
        from app.reference.records import Receipt
        receipts=[r for r in s.repo.refs.records() if isinstance(r,Receipt)]
        self.assertGreaterEqual(len(receipts),2)
        self.assertEqual(len(set(r.body_sha256 for r in receipts)),1)
        self.assertEqual(len(set(r.id for r in receipts)),len(receipts))
    async def test_slow_calculation_does_not_block_capture(self):
        import time
        from unittest.mock import patch
        from app.collection.session import compute
        s=self.build();calls=[]
        def slow(*args):calls.append(1);time.sleep(1);return compute(*args)
        with patch('app.collection.session.compute',slow):
            await s.start();await asyncio.sleep(.9);first=s.persisted
            await asyncio.sleep(.7);self.assertGreater(s.persisted,first)
            await s.stop()
        self.assertGreater(len(calls),0);self.assertEqual(s.delivered,s.persisted)
    async def test_stale_prediction_snapshot_keeps_economics_unavailable(self):
        s=self.build();s.transports['kalshi'].stale=True
        await s.start();await asyncio.sleep(1.6);await s.stop()
        result=await asyncio.to_thread(reopen,self.out/s.sid)
        self.assertGreater(len(result['snapshots']),0)
        for snapshot in result['snapshots']:
            if snapshot['audit']:
                self.assertTrue(all(row['status']=='unavailable' for row in snapshot['audit']['signals']))
    async def test_saved_health_blocks_outage_economics(self):
        from app.collection.server import project
        s=self.build(prediction_poll=.5,reference_poll=2,calculation_poll=.3);s.transports['kalshi'].interruption=.3;s.transports['kalshi'].outage=4
        await s.start();await asyncio.sleep(2.3);await s.stop()
        result=await asyncio.to_thread(reopen,self.out/s.sid)
        unavailable=[r for r in result['snapshots'] if not r['session_context']['eligible']]
        self.assertTrue(unavailable)
        for snapshot in unavailable:
            projected=project(snapshot)
            self.assertEqual(projected['status'],'unavailable')
            self.assertTrue(all(x['net_total_usd'] is None for x in projected['signals']))
