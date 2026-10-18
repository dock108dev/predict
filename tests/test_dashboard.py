import asyncio
from datetime import datetime,timezone,timedelta
import time,unittest
from app.dashboard.controller import Controller,limits_for
from app.dashboard.views import age_view,candidate_view

class FakeStore:
 def event(self,*args):pass
class FakePipeline:
 def __init__(self,*args):self.finished=False;self.store=FakeStore();self.journal=False
 def start(self):return 'test-session'
 def bootstrap(self,data):return {'markets':[],'candidates':[]}
 def synthetic_bootstrap(self):return self.bootstrap([])
 def book(self,b):return self.bootstrap([])
 def disconnect(self,*a):return self.bootstrap([])
 def synthetic_tick(self,n):return self.bootstrap([])
 def finish(self,*a):self.finished=True
 def failure_journal(self,*a):self.journal=True
 def depth(self,cid):return {'id':cid}
class QuietSource:
 instances=[]
 def __init__(self,run):self.closed=False;self.cancelled=False;QuietSource.instances.append(self)
 async def prepare(self):return [{}]
 async def venue(self,d):
  try:await asyncio.Event().wait()
  finally:self.cancelled=True
 async def close(self):self.closed=True

class ControllerTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):self.c=Controller(FakePipeline,QuietSource)
 async def asyncTearDown(self):await self.c.close()
 async def ready(self):
  for _ in range(100):
   if self.c.state=='scanning':return
   await asyncio.sleep(.01)
  self.fail('not scanning')
 async def test_start_double_start_stop_cleanup(self):
  await self.c.start('live',{});await self.ready()
  with self.assertRaises(RuntimeError):await self.c.start('live',{})
  self.c.request_stop('owner stop');await asyncio.wait_for(self.c.task,2)
  self.assertTrue(self.c.worker.finished);self.assertTrue(QuietSource.instances[-1].closed);self.assertTrue(QuietSource.instances[-1].cancelled)
  self.assertEqual(self.c.state,'stopped')
 async def test_quiet_deadline(self):
  begin=time.monotonic();await self.c.start('live',{'seconds':5})
  await asyncio.wait_for(self.c.task,6)
  self.assertLess(time.monotonic()-begin,5.8);self.assertEqual(self.c.reason,'Scan deadline reached')
  self.assertTrue(QuietSource.instances[-1].cancelled)
 async def test_bounded_queue_marks_backpressure(self):
  self.c.accepting=True
  for i in range(48):self.assertTrue(self.c.offer(('book',i)))
  self.assertFalse(self.c.offer(('book','overflow')))
  self.assertEqual(self.c.queue.qsize(),48);self.assertIn('Backpressure',self.c.reason);self.assertTrue(self.c.stop_event.is_set())
 async def test_worker_failure_stops(self):
  class Broken(FakePipeline):
   def book(self,b):raise RuntimeError('database failed')
  self.c.pipeline_factory=Broken
  await self.c.start('live',{});await self.ready();self.c.offer(('book','x'))
  await asyncio.wait_for(self.c.task,2)
  self.assertEqual(self.c.state,'failed');self.assertTrue(self.c.worker.finished)
 async def test_database_finish_failure_journal(self):
  class Broken(FakePipeline):
   def finish(self,*a):raise RuntimeError('database down')
  self.c.pipeline_factory=Broken;await self.c.start('live',{});await self.ready();self.c.request_stop('stop')
  await self.c.task;self.assertTrue(self.c.worker.journal);self.assertIn('incomplete',self.c.error)
 async def test_slow_worker_does_not_block_loop(self):
  class Slow(FakePipeline):
   def book(self,b):time.sleep(.2);return {'markets':[],'candidates':[]}
  self.c.pipeline_factory=Slow;await self.c.start('live',{});await self.ready();self.c.offer(('book','x'))
  t=time.monotonic();await asyncio.sleep(.03);self.assertLess(time.monotonic()-t,.1)
 async def test_no_launch_resume(self):self.assertEqual(self.c.state,'idle');self.assertIsNone(self.c.task)
 async def test_depth_requires_active(self):
  with self.assertRaises(ValueError):await self.c.depth('c')
 async def test_quiet_discovery_cancelled(self):
  class SlowDiscovery(QuietSource):
   async def prepare(self):await asyncio.Event().wait()
  self.c.source_factory=SlowDiscovery;await self.c.start('live',{})
  await asyncio.sleep(.02);self.c.request_stop('stop discovery');await asyncio.wait_for(self.c.task,1)
  self.assertTrue(QuietSource.instances[-1].closed)

class DisplayTests(unittest.TestCase):
 def test_limits_validate(self):
  for v in [{'seconds':61},{'markets':0},{'receipts':True},{'host':'example.com'}]:
   with self.assertRaises(ValueError):limits_for(v)
 def test_clock_disconnect_and_historical_isolation(self):
  now=datetime.now(timezone.utc)
  v={'markets':[{'key':'k','venue_key':'kalshi','quotes':[dict(received_at=now.isoformat(),sync='synchronized',state='active')]}],'candidates':[dict(legs=[dict(market_key='k',received_at=now.isoformat())],current_opportunity=True)]}
  self.assertTrue(age_view(v,active=True,health={'kalshi':{'state':'connected'}})['candidates'][0]['current_opportunity'])
  self.assertFalse(age_view(v,active=True,health={'kalshi':{'state':'disconnected'}})['candidates'][0]['current_opportunity'])
  self.assertFalse(age_view(v,active=False)['candidates'][0]['current_opportunity'])
  v['markets'][0]['quotes'][0]['received_at']=(now-timedelta(seconds=31)).isoformat()
  self.assertFalse(age_view(v,active=True,health={'kalshi':{'state':'connected'}})['candidates'][0]['current_opportunity'])
 def test_candidate_leg_age_cannot_borrow_other_side_freshness(self):
  now=datetime.now(timezone.utc)
  v={'freshness_seconds':10,'markets':[{'key':'k','venue_key':'kalshi','quotes':[dict(received_at=now.isoformat(),sync='synchronized',state='active')]}],'candidates':[dict(legs=[dict(market_key='k',received_at=(now-timedelta(seconds=11)).isoformat())],current_opportunity=True)]}
  self.assertFalse(age_view(v,active=True,health={'kalshi':{'state':'connected'}})['candidates'][0]['current_opportunity'])
 def test_live_current_qualification_propagates(self):
  from app.arbitrage_example import synthetic_inputs,evaluate_fixture,selected
  c=selected(evaluate_fixture(synthetic_inputs()));v=candidate_view(c)
  self.assertFalse(v['current_opportunity']);self.assertFalse(v['qualified'])
  self.assertTrue(v['reasons']);self.assertEqual(v['profit'],c['conditional_calculation']['worst_case_profit'])
