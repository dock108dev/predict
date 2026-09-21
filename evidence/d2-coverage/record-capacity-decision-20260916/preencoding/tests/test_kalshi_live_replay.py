"""Sanitized production evidence replay; every test remains offline."""
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import unittest

from app.adapters.kalshi import Response, parse_market
from app.adapters.kalshi_stream import BookReconstructor, RecoveryRequired
from app.models.core import BookSync, SourceTimeProgress

ROOT = Path(__file__).resolve().parents[1] / 'evidence/slice-4/recovery-20260912'


def fixture():
    report=json.loads((ROOT/'report.json').read_text())
    record=report['responses'][2]
    response=Response((ROOT/record['file']).read_text(),record['source'],datetime.fromisoformat(record['received_at']))
    markets=[parse_market(response,m,m['event_ticker'],'KXNFLGAME') for m in json.loads(response.body)['markets']]
    return BookReconstructor(markets),json.loads((ROOT/'stream.json').read_text())


class LiveReplayTests(unittest.TestCase):
    def test_two_generations_all_levels_and_source_time(self):
        e,frames=fixture()
        generation=0
        expected={}
        snapshots=deltas=removals=repeated=0
        for record in frames:
            if record['generation'] != generation:
                generation=record['generation']; e.begin(generation); expected={}
            native=json.loads(record['body']); msg=native['msg']; kind=native['type']
            if kind=='orderbook_snapshot':
                expected[msg['market_ticker']]={side:{Decimal(p):Decimal(q) for p,q in msg.get(side+'_dollars_fp',[])} for side in ('yes','no')}
                snapshots+=1
            elif kind=='orderbook_delta':
                values=expected[msg['market_ticker']][msg['side']]
                p=Decimal(msg['price_dollars']); q=values.get(p,Decimal(0))+Decimal(msg['delta_fp'])
                if q:
                    values[p]=q
                else:
                    values.pop(p,None); removals+=1
                deltas+=1
            book=e.feed(record['body'],generation,datetime.fromisoformat(record['received_at']))
            if book is None: continue
            self.assertEqual(book.sync,BookSync.SYNCHRONIZED)
            for outcome in book.outcomes:
                actual={level.price.value:level.quantity.value for level in outcome.bids.levels}
                self.assertEqual(actual,expected[msg['market_ticker']][outcome.outcome_id])
            if book.source_time_progress==SourceTimeProgress.REPEATED: repeated+=1
        self.assertEqual((snapshots,deltas),(4,13))
        self.assertEqual(generation,2)
        self.assertGreaterEqual(repeated,2)
        self.assertEqual(removals,0)  # No natural zero-level removal in this capture.
        self.assertEqual(e.seq,7)

    def test_omitted_real_delta_detects_gap_and_invalidates_both_markets(self):
        e,frames=fixture(); e.begin(1)
        for record in frames[:3]:
            e.feed(record['body'],1,datetime.fromisoformat(record['received_at']))
        with self.assertRaises(RecoveryRequired):
            e.feed(frames[4]['body'],1,datetime.fromisoformat(frames[4]['received_at']))
        self.assertEqual(len(e.last),2)
        self.assertTrue(all(b.sync==BookSync.UNSYNCHRONIZED for b in e.last.values()))

    def test_reused_sid_from_closed_connection_is_ignored(self):
        e,frames=fixture(); e.begin(1)
        for r in frames[:3]: e.feed(r['body'],1,datetime.fromisoformat(r['received_at']))
        e.begin(2)
        for r in frames[11:14]: e.feed(r['body'],2,datetime.fromisoformat(r['received_at']))
        before=dict(e.last)
        self.assertIsNone(e.feed(frames[3]['body'],1,datetime.fromisoformat(frames[3]['received_at'])))
        self.assertEqual(e.last,before)
