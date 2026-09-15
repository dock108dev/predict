"""Focused offline status/source-clock tests; no new venue observations."""
from datetime import datetime, timedelta, timezone
from decimal import localcontext
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from app.adapters.polymarket_us import state, source_time_value
from app.adapters.polymarket_us_stream import MarketStream
from app.models.core import BookSync, Depth, MarketState, ReceiptFreshness, SourceTimeProgress
from app.polymarket_us_verify import load_market
from tests.test_polymarket_us import market
from tests.test_polymarket_us_stream import message

ROOT=Path(__file__).resolve().parents[1]
CAPTURE=ROOT/'evidence/slice-2/verification-20260911T231849Z'

class HardeningTests(unittest.TestCase):
    def test_source_progress_survives_caller_decimal_precision_changes(self):
        stream = MarketStream([market()], None)
        epoch = stream.begin_subscription('r')
        stream.parse(message('r', transactTime='2026-09-11T01:00:00.123456789Z'),
                     'r', generation=epoch)
        epoch = stream.begin_subscription('new')
        with localcontext() as ctx:
            ctx.prec = 3
            for source, expected in [
                ('2026-09-10T21:00:00.123456789-04:00', SourceTimeProgress.REPEATED),
                ('2026-09-11T01:00:00.123456788Z', SourceTimeProgress.REGRESSED),
                ('2026-09-11T01:00:00.123456790Z', SourceTimeProgress.ADVANCED),
                ('2026-09-11T01:00:01Z', SourceTimeProgress.ADVANCED),
            ]:
                book = stream.parse(message('new', transactTime=source), 'new', generation=epoch)
                self.assertEqual(book.source_time_progress, expected)
                self.assertEqual(book.sync, BookSync.SYNCHRONIZED)
                self.assertEqual(book.receipt_freshness, ReceiptFreshness.RECENT)

    def test_replayed_reconnect_source_is_repeated_despite_recent_receipt(self):
        stream=MarketStream([load_market(CAPTURE/'public-smoke')],None)
        books=[]
        for name in ['market-frame-004.json','market-frame-005.json']:
            body=(CAPTURE/'authenticated-01'/name).read_text()
            rid=json.loads(body)['requestId']
            epoch=stream.begin_subscription(rid)
            books.append(stream.parse(body,rid,generation=epoch))
        self.assertEqual(books[1].source_time_progress,SourceTimeProgress.REPEATED)
        self.assertEqual(books[1].raw.exchange_at,books[0].raw.exchange_at)
        self.assertGreaterEqual(books[1].raw.received_at,books[0].raw.received_at)
        self.assertEqual(books[1].receipt_freshness,ReceiptFreshness.RECENT)
        self.assertEqual(books[1].sync,BookSync.SYNCHRONIZED)

    def test_missing_regressing_and_submicrosecond_clock_across_reconnect(self):
        stream=MarketStream([market()],None);epoch=stream.begin_subscription('r')
        def apply(value):return stream.parse(message('r',transactTime=value),'r',generation=epoch)
        self.assertEqual(apply('2026-09-11T01:00:00.123456789Z').source_time_progress,SourceTimeProgress.FIRST)
        epoch=stream.begin_subscription('r')
        missing=apply(None)
        self.assertEqual(missing.source_time_progress,SourceTimeProgress.MISSING)
        self.assertIsNone(missing.raw.source_age_at_receipt)
        regressed=apply('2026-09-11T01:00:00.123456788Z')
        self.assertEqual(regressed.source_time_progress,SourceTimeProgress.REGRESSED)
        self.assertEqual(regressed.sync,BookSync.SYNCHRONIZED)
        self.assertEqual(apply('2026-09-11T01:00:00.123456789Z').source_time_progress,SourceTimeProgress.REPEATED)
        self.assertEqual(apply('2026-09-11T01:00:00.123456790Z').source_time_progress,SourceTimeProgress.ADVANCED)
        self.assertEqual(source_time_value('2026-09-10T21:00:00.123456790-04:00'),source_time_value('2026-09-11T01:00:00.123456790Z'))

    def test_old_and_future_source_ages_are_signed_and_not_eligibility(self):
        receipt=datetime(2026,9,11,2,tzinfo=timezone.utc)
        stream=MarketStream([market()],None);epoch=stream.begin_subscription('r')
        with patch('app.adapters.polymarket_us_stream.datetime') as clock:
            clock.now.return_value=receipt
            old=stream.parse(message('r',transactTime='2026-09-11T01:00:00Z'),'r',generation=epoch)
            future=stream.parse(message('r',transactTime='2026-09-11T03:00:00Z'),'r',generation=epoch)
        self.assertEqual(old.raw.source_age_at_receipt,timedelta(hours=1))
        self.assertEqual(future.raw.source_age_at_receipt,timedelta(hours=-1))
        self.assertEqual(old.raw.receipt_age(receipt+timedelta(seconds=5)),timedelta(seconds=5))
        self.assertEqual(old.sync,BookSync.SYNCHRONIZED)
        self.assertEqual(old.outcomes[0].bids.depth,Depth.PARTIAL)
        with self.assertRaises(ValueError):old.raw.receipt_age(datetime(2026,9,11))

    def test_status_transitions_and_status_only_reopen_cannot_refresh_book(self):
        stream=MarketStream([market()],None);epoch=stream.begin_subscription('r')
        books=[]
        for status in ['MARKET_STATE_OPEN','MARKET_STATE_SUSPENDED','MARKET_STATE_OPEN', 'MARKET_STATE_HALTED','MARKET_STATE_EXPIRED','MARKET_STATE_TERMINATED','FUTURE_STATE',None]:
            book=stream.parse(message('r',state=status,transactTime='2026-09-11T01:00:00Z'),'r',generation=epoch)
            books.append(book)
            self.assertEqual(book.sync,BookSync.SYNCHRONIZED)
        self.assertEqual([b.state for b in books],[MarketState.ACTIVE,MarketState.SUSPENDED,MarketState.ACTIVE,MarketState.SUSPENDED,MarketState.CLOSED,MarketState.CLOSED,MarketState.UNKNOWN,MarketState.UNKNOWN])
        self.assertEqual(books[2].source_time_progress,SourceTimeProgress.REPEATED)
        reopen=json.loads(message('r',state='MARKET_STATE_OPEN'))
        del reopen['marketData']['bids'];del reopen['marketData']['offers']
        book=stream.parse(json.dumps(reopen),'r',generation=epoch)
        self.assertEqual(book.state,MarketState.ACTIVE)
        self.assertEqual(book.sync,BookSync.UNKNOWN)
        self.assertIsNone(book.outcomes[0].bids)
        self.assertEqual(book.source_time_progress,SourceTimeProgress.MISSING)
        # Retail schema has EXPIRED/TERMINATED, not an institutional CLOSED enum.
        self.assertEqual(state('INSTRUMENT_STATE_CLOSED'),MarketState.UNKNOWN)
        self.assertEqual(state('MARKET_STATE_MATCH_AND_CLOSE_AUCTION'),MarketState.UNKNOWN)
