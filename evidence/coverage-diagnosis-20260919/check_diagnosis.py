"""Focused offline diagnostic checks; no application edits or real transport."""
import asyncio,json,unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
from tests.test_kalshi import market,frame,ack,NOW
from app.adapters.kalshi_stream import MarketStream
from app.models.core import ReceiptFreshness,BookSync
D=Path(__file__).resolve().parent
class DiagnosisChecks(unittest.TestCase):
 def test_loss_evidence_and_threshold(self):
  ms=json.loads((D/'per-market.json').read_text())['markets']
  self.assertEqual(len(ms),96)
  for venue,native,lost,stale in [('kalshi',555,41,112),('polymarket_us',1330,3,37)]:
   xs=[m for m in ms if m['venue']==venue]
   self.assertEqual(sum(m['native_updates'] for m in xs),native)
   self.assertEqual(sum(not m['pre_stop_usable'] for m in xs),lost)
   self.assertEqual(sum(m['stale_observations'] for m in xs),stale)
   for m in xs:
    self.assertTrue(m['initially_usable'])
    for o in m['observations']:
     if not o['usable']:
      self.assertEqual(o['cause'],'freshness_expiry');self.assertGreaterEqual(o['age_seconds'],30)
      self.assertIsNotNone(o['prior_native_observation']['ingress_id'])
 def test_all_checkpoints_and_terminal(self):
  d=json.loads((D/'coverage-timeline.json').read_text())
  self.assertEqual(len(d['matched_checkpoints']),65)
  self.assertEqual(d['events'][-2]['counts'],{'kalshi':23,'polymarket_us':29})
  self.assertEqual(d['events'][-1]['counts'],{'kalshi':0,'polymarket_us':0})
  self.assertTrue(d['events'][-1]['terminal'])
 def test_native_replay_and_historical_behavior_identity(self):
  d=json.loads((D/'identity-and-replay.json').read_text())
  self.assertEqual(d['derived_health_books'],149)
  self.assertEqual(d['subsequent_changed_files'],['app/collection/supervised_live.py','tests/segmented_collector_fixture.py'])
  self.assertIn('app/adapters/kalshi_stream.py',d['unchanged_behavior_files'])
  self.assertTrue(all(not r['gaps'] for r in d['replay'].values()))
class TimerCharacterization(unittest.IsolatedAsyncioTestCase):
 async def test_busy_other_market_defers_quiet_market_expiry_until_timeout(self):
  # Synthetic clock jumps model elapsed receipt age, with immediate finite recv.
  # This is a characterization of the historical defect, not a repaired expectation.
  clock=[NOW];sent=[]
  messages=[(0,ack()),(0,frame(1,mid='quiet')),(0,frame(2,mid='busy')),
            (31,frame(3,'orderbook_delta',mid='busy')),(32,frame(4,'orderbook_delta',mid='busy')),
            (32.5,None)]
  class Clock:
   @staticmethod
   def now(tz):return clock[0]
  class Conn:
   async def send(self,body):sent.append(body)
   async def close(self):pass
   async def recv(self):
    seconds,body=messages.pop(0);clock[0]=NOW+timedelta(seconds=seconds)
    if body is None:raise TimeoutError
    return body
  async def factory():return Conn()
  stream=MarketStream([market('quiet'),market('busy')],factory,stale_seconds=30,duration=60,max_connections=1)
  observed=[]
  with patch('app.adapters.kalshi_stream.datetime',Clock):
   iterator=stream.run()
   try:
    for _ in range(5):
     b=await anext(iterator);observed.append((b.raw.ref.market_id,b.receipt_freshness.value,(clock[0]-NOW).total_seconds()))
     if len(observed) in (3,4):
      self.assertEqual(stream.engine.last['quiet'].receipt_freshness,ReceiptFreshness.RECENT)
      self.assertEqual(stream.engine.last['quiet'].sync,BookSync.SYNCHRONIZED)
    self.assertEqual(observed[-1],('quiet','stale',32.5))
   finally:await iterator.aclose()
  (D/'timer-characterization.json').write_text(json.dumps(dict(kind='synthetic offline characterization; no live measurement',threshold_seconds=30,observed=observed,quiet_remains_recent_at_31_and_32_seconds=True,first_timeout_marks_stale_at=32.5),indent=2)+'\n')
if __name__=='__main__':unittest.main(verbosity=2)
