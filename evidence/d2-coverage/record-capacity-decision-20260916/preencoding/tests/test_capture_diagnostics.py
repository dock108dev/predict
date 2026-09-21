"""13A diagnostics prove an existing failure; they do not assert a repair."""
import asyncio
from collections import Counter
from dataclasses import asdict
import json
import unittest

from app.capture_benchmark import fixture, schedule, synthetic_observations
from app.dashboard.diagnostics import Measurements, MeasuredController, MeasuredQueue, reconcile
from app.dashboard.pipeline import serial


class FixtureTests(unittest.TestCase):
    def test_deterministic_two_and_four_market_fixtures(self):
        for n in (2,4):
            p,m,c,rows,books=fixture(n)
            self.assertEqual(Counter(r['venue'] for r in rows),{'kalshi':n,'polymarket_us':n})
            self.assertEqual(len({r['key'] for r in rows}),2*n)
            self.assertEqual(serial([asdict(b) for b in books]),serial([asdict(b) for b in fixture(n)[-1]]))
            self.assertTrue(m.report(p)['pairs'])
            for b in books:
                observations=synthetic_observations(b,source_time_semantics='unknown',locks_clear=None,units_verified=False)
                self.assertEqual(len(observations),2)
                self.assertTrue(all(o.evidence_class=='synthetic' and o.environment=='synthetic' for o in observations))
                self.assertTrue(all(not o.units_verified for o in observations))
    def test_finite_schedules_include_quiet_disconnect_depth_and_bursts(self):
        for s in ('ordinary','burst24','overflow40','slow','depth'):
            steps=schedule(s)
            self.assertLessEqual(sum(x['count'] for x in steps),41)
            self.assertTrue(any(x['quiet_seconds'] for x in steps))
        self.assertTrue(any(x['kind']=='depth' for x in schedule('depth')))
        self.assertTrue(any(x['kind']=='disconnect' for x in schedule('ordinary')))


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_overflow_and_accounting(self):
        m=Measurements();c=MeasuredController(m);c.queue=MeasuredQueue(m);c.accepting=True
        try:
            for n in range(56):c.offer_identified(str(n),('book',n),100)
            self.assertEqual(c.queue.qsize(),48)
            self.assertIn('Backpressure',c.reason)
            self.assertEqual(max(x['estimated_bytes'] for x in m.queue_samples),4800)
            result=reconcile(m,[],[],[],0)
            self.assertEqual(result['counts']['accepted'],48)
            self.assertEqual(result['counts']['rejected'],8)
            self.assertEqual(m.items[48]['rejection'],'queue_full')
            self.assertTrue(all(x['rejection']=='acceptance_closed' for x in m.items[49:]))
            self.assertEqual(result['counts']['unprocessed'],48)
            self.assertIsNone(result['counts']['wire_messages'])
            self.assertTrue(all(result['gates'].values()))
            with self.assertRaises(ValueError):c.offer_identified('0',('book',0),1)
        finally:await c.close()
    async def test_queue_wait_and_oldest_age(self):
        m=Measurements();c=MeasuredController(m);c.queue=MeasuredQueue(m);c.accepting=True
        try:
            c.offer_identified('a',('book',0),20)
            await asyncio.sleep(.01);m.sample()
            self.assertGreater(m.queue_samples[-1]['oldest_seconds'],0)
            self.assertEqual(c.queue.get_nowait(),('book',0))
            self.assertGreater(m.items[0]['queue_wait_seconds'],0)
            self.assertEqual(m.queue_samples[-1]['entries'],0)
        finally:await c.close()
    async def test_attempted_write_is_not_commit_and_partial_item_stays_unprocessed(self):
        m=Measurements();m.items=[dict(id='x',accepted=True,processed=False)]
        m.bindings=[dict(kind='receipt',id='r0',item_id='x',returned=True),
                    dict(kind='receipt',id='r1',item_id='x',returned=False)]
        result=reconcile(m,['r0'],[],[],1)
        self.assertEqual(result['counts']['committed_receipts'],1)
        self.assertEqual(result['counts']['attempted_receipt_writes'],2)
        self.assertEqual(result['items'][0]['disposition'],'explicitly_unprocessed')
        self.assertFalse(result['bindings'][1]['committed'])
        self.assertFalse(reconcile(m,['unbound'],[],[],1)['gates']['all_receipts_bound'])
