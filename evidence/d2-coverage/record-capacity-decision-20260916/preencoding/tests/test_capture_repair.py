"""13B lifecycle and resource boundaries; no venue access."""
import asyncio
import threading
import time
import unittest
from app.dashboard.bounds import CaptureQueue,retained_bytes
from app.dashboard.controller import Controller
from app.capture_benchmark import fixture
from tests.test_dashboard import FakePipeline,QuietSource


class CaptureBoundsTests(unittest.TestCase):
    def test_fixture_heap_is_not_serialized_size(self):
        for markets in (2,4):
            q=CaptureQueue()
            for n in range(40):q.put_nowait(('book',fixture(markets)[-1][n%(2*markets)]))
            self.assertLess(q.bytes,q.byte_limit)
            self.assertGreater(q.bytes,40000)
            while not q.empty():q.get_nowait()
            self.assertEqual(q.bytes,0)
    def test_byte_exhaustion_and_shared_references(self):
        item=('book','x'*2000)
        q=CaptureQueue(byte_limit=retained_bytes(item)-1)
        with self.assertRaises(asyncio.QueueFull):q.put_nowait(item)
        self.assertEqual(q.qsize(),0);self.assertEqual(q.last_rejection,'queue_bytes')
        q=CaptureQueue();q.put_nowait(item);q.put_nowait(item)
        q.get_nowait();self.assertEqual(q.bytes,retained_bytes(item))
        q.get_nowait();self.assertEqual(q.bytes,0)


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):self.c=Controller(FakePipeline,QuietSource)
    async def asyncTearDown(self):await self.c.close()
    async def ready(self):
        await self.c.start('live',{})
        for _ in range(100):
            if self.c.state=='scanning':return
            await asyncio.sleep(.005)
        self.fail('not ready')
    async def test_stop_drains_41_and_finalizes_once(self):
        class Slow(FakePipeline):
            def __init__(self,*a):super().__init__(*a);self.books=[];self.finishes=0
            def book(self,b):time.sleep(.003);self.books.append(b)
            def finish(self,*a):self.finishes+=1;super().finish(*a)
        self.c.pipeline_factory=Slow;await self.ready()
        for n in range(41):self.assertTrue(self.c.offer(('book',n)))
        self.c.request_stop('owner stop',initiator='owner');first=dict(self.c.stop_record)
        for _ in range(4):self.c.request_stop('owner stop',initiator='owner')
        self.c.request_stop('later deadline',initiator='deadline')
        with self.assertRaises(RuntimeError):await self.c.start('live',{})
        await asyncio.wait_for(self.c.task,2)
        self.assertEqual(self.c.worker.books,list(range(41)))
        self.assertEqual(self.c.worker.finishes,1);self.assertEqual(first,self.c.stop_record)
        self.assertEqual(len(self.c.later_causes),1)
        self.assertTrue(all(r['state']=='processed' for r in self.c.ledger))
    async def test_over_envelope_drains_accepted_and_records_rejections(self):
        await self.ready()
        for n in range(56):self.c.offer(('book',n))
        await asyncio.wait_for(self.c.task,2)
        self.assertEqual(len(self.c.ledger),48)
        self.assertEqual(sum(self.c.rejections.values()),8)
        self.assertEqual(self.c.rejections,{'queue_items':1,'acceptance_closed':7})
        self.assertEqual(self.c.worker.shutdown['unprocessed'],0)
    async def test_byte_limit_stops_and_preserves_first_trigger(self):
        await self.ready();self.c.queue.byte_limit=100
        self.assertFalse(self.c.offer(('book','x'*1000)))
        self.c.request_stop('owner stop')
        await self.c.task
        self.assertEqual(self.c.rejections,{'queue_bytes':1})
        self.assertEqual(self.c.stop_record['initiator'],'capacity')
    async def test_depth_rejected_when_capture_behind(self):
        await self.ready();self.c.offer(('book','pending'))
        with self.assertRaisesRegex(RuntimeError,'Capture is behind'):await self.c.depth('x')
    async def test_cancelled_depth_await_settles_before_finish(self):
        entered=threading.Event();release=threading.Event();order=[]
        class Depth(FakePipeline):
            def depth(self,cid):entered.set();release.wait(1);order.append('depth');return {'id':cid}
            def finish(self,*a):order.append('finish');super().finish(*a)
        self.c.pipeline_factory=Depth;await self.ready()
        request=asyncio.create_task(self.c.depth('x'))
        while not entered.is_set():await asyncio.sleep(.001)
        with self.assertRaises(RuntimeError):await self.c.depth('y')
        request.cancel();await asyncio.gather(request,return_exceptions=True)
        self.c.request_stop('owner stop');await asyncio.sleep(.02)
        self.assertFalse(self.c.task.done());self.assertTrue(self.c.depth_busy)
        release.set();await asyncio.wait_for(self.c.task,1)
        self.assertEqual(order,['depth','finish']);self.assertIsNone(self.c.depth_result)
        self.assertLess(self.c.producers_closed_at-self.c.stop_clock,2)
    async def test_failure_keeps_later_items_unprocessed(self):
        class Broken(FakePipeline):
            def book(self,b):raise RuntimeError('not retained')
        self.c.pipeline_factory=Broken;await self.ready()
        for n in range(3):self.c.offer(('book',n))
        self.c.request_stop('owner stop',initiator='owner');await self.c.task
        self.assertEqual(self.c.reason,'owner stop')
        self.assertEqual(self.c.worker.shutdown['unprocessed'],3)
        self.assertEqual(self.c.state,'failed')
    async def test_refresh_is_coalesced_between_committed_books(self):
        class Coalesced(FakePipeline):
            def __init__(self,*a):super().__init__(*a);self.books=0;self.views=[]
            def book(self,b):self.books+=1
            def refresh(self,force):
                if force:self.views.append(self.books)
        self.c.pipeline_factory=Coalesced;await self.ready()
        for n in range(24):self.c.offer(('book',n))
        self.c.request_stop('owner stop');await self.c.task
        self.assertEqual(self.c.worker.views,[24])
