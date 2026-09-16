"""Saved real page plus explicitly mutated fixture variants; no network calls."""
import copy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from app.reference.public_page import parse, american_decimal, DelayedPolicy

ROOT = Path(__file__).resolve().parents[1] / 'evidence/public-nfl-reference'
RAW = (ROOT / 'vegasinsider.html').read_bytes()
META = json.loads((ROOT / 'capture.json').read_text())
BODY = re.findall(rb'<tbody\b[^>]*\bid="odds-table-moneyline--0"[^>]*>.*?</tbody>', RAW, re.S)[0]


def fixture(raw=BODY, **kwargs):
    metadata = dict(META, sha256=sha256(raw).hexdigest())
    return parse(raw, metadata, event_id='32144330', **kwargs)


class PublicPageTests(unittest.TestCase):
    def test_saved_real_capture(self):
        result = parse(RAW, META, event_id='32144330')
        self.assertEqual([s['american_price'] for s in result['sides']], ['+180', '-218'])
        self.assertEqual([s['team'] for s in result['sides']], ['Detroit Lions', 'Buffalo Bills'])
        self.assertEqual(result['scheduled_start'], '2026-09-18T00:15:00Z')
        self.assertEqual(result['bookmaker'], 'draftkings')
        self.assertEqual(result['displayed_notice_text'], ['Last Updated Sep 15 2026, 2:41 PM'])
        for field in ('bookmaker_updated_at', 'disclosed_delay_seconds', 'copied_from', 'probabilities', 'conditional_ev', 'unconditional_ev'):
            self.assertIsNone(result[field])
        self.assertFalse(result['current_executable'])

    def test_hash_and_http_failure(self):
        for meta in (dict(META, sha256='bad'), dict(META, status=403), dict(META, url='https://example.com')):
            with self.assertRaises(ValueError):
                parse(RAW, meta, event_id='32144330')

    def test_no_best_consensus_or_other_book_selection(self):
        for book in ('best', 'Consensus', 'bet365', 'polymarket'):
            with self.assertRaises(ValueError): fixture(bookmaker=book)

    def test_no_spread_or_duplicate_table_fallback(self):
        for raw in (BODY.replace(b'odds-table-moneyline--0', b'odds-table-spread--0'), BODY + BODY):
            with self.assertRaises(ValueError): fixture(raw)

    def test_missing_duplicate_book(self):
        for raw in (BODY.replace(b'alt="draftkings"', b'alt="unknown"'), BODY.replace(b'alt="bet365"', b'alt="draftkings"')):
            with self.assertRaises(ValueError): fixture(raw)

    def test_missing_price_never_borrows_other_book_or_event(self):
        raw = BODY.replace(b'<span class="data-moneyline"> +180 </span>', b'<span></span>', 1)
        with self.assertRaisesRegex(ValueError, 'missing_or_duplicate_price'): fixture(raw)

    def test_column_removed_or_span_rejected(self):
        for raw in (BODY.replace(b'<td class="game-odds">', b'<td class="game-odds" colspan="2">', 1),
                    BODY.replace(b'<td class="game-odds"> <span> <span class="data-moneyline"> +136 </span> </span> </td>', b'', 1)):
            with self.assertRaisesRegex(ValueError, 'column_alignment'): fixture(raw)

    def test_duplicate_team_and_bad_start(self):
        for raw in (BODY.replace(b'alt="Buffalo Bills"', b'alt="Detroit Lions"'),
                    BODY.replace(b'2026-09-18T00:15:00Z', b'2026-09-18T00:15:00', 1)):
            with self.assertRaises(ValueError): fixture(raw)

    def test_delay_notice_preserved_without_inventing_clock(self):
        result = fixture(BODY + b'<p>Odds are delayed by approximately 15 minutes.</p>')
        self.assertEqual(result['delay_notice'], ['Odds are delayed by approximately 15 minutes.'])
        self.assertIsNone(result['bookmaker_updated_at'])

    def test_decimal_conversion(self):
        self.assertEqual(american_decimal('+180'), '2.8')
        self.assertEqual(american_decimal('-200'), '1.5')
        for raw in ('0', '+99', 'NaN', '-0', '+180.0', 'EVEN'):
            with self.assertRaises(ValueError): american_decimal(raw)


class ResearchTimeTests(unittest.TestCase):
    def check(self, **kwargs):
        inputs = dict(retrieved_at='2026-09-16T03:15:00Z', cutoff='2026-09-16T03:30:00Z',
                      scheduled_start='2026-09-18T00:15:00Z', disclosed_delay_seconds=900)
        inputs.update(kwargs)
        return DelayedPolicy().assess(**inputs)

    def test_fifteen_minute_delay_allowed_and_clock_unknown(self):
        result = self.check()
        self.assertTrue(result['research_time_eligible'])
        self.assertFalse(result['current_executable'])
        self.assertIsNone(result['bookmaker_updated_at'])
        self.assertFalse(result['upstream_age_verified'])

    def test_unknown_delay_not_claimed_fresh(self):
        self.assertIn('update_and_delay_unknown', self.check(disclosed_delay_seconds=None)['reasons'])

    def test_limits_and_future_clocks(self):
        for changes in (dict(retrieved_at='2026-09-16T03:09:59Z'),
                        dict(retrieved_at='2026-09-16T03:30:01Z'),
                        dict(bookmaker_updated_at='2026-09-16T03:16:00Z'),
                        dict(bookmaker_updated_at='2026-09-16T03:09:59Z'),
                        dict(disclosed_delay_seconds=901),
                        dict(scheduled_start='2026-09-16T03:31:00Z'),
                        dict(target_received_at='2026-09-16T03:29:29Z')):
            with self.subTest(changes=changes):
                self.assertFalse(self.check(**changes)['research_time_eligible'])
        self.assertTrue(self.check(target_received_at='2026-09-16T03:29:30Z')['research_time_eligible'])


if __name__ == '__main__':
    unittest.main()
