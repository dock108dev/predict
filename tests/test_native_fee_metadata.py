from copy import deepcopy
import unittest
from app.collection.native_fee_metadata import context
from app.collection.native_payload import envelope,validate_envelope
from app.fees.engine import kalshi_terms

class ScopedFeeFacts(unittest.TestCase):
    def test_scoped_current_baseline_nullable_overrides_and_future_changes(self):
        series=dict(ticker='KXNFLGAME',fee_type='quadratic',fee_multiplier=1)
        changes=dict(series_fee_change_arr=[dict(series_ticker='KXNFLGAME',fee_type='quadratic_with_maker_fees',fee_multiplier='2',scheduled_ts='2026-10-02T00:00:00Z')])
        events=dict(cursor='',event_fee_changes=[dict(series_ticker='KXNFLGAME',event_ticker='E',fee_type_override=None,fee_multiplier_override='3',scheduled_ts='2026-09-30T00:00:00Z'),dict(series_ticker='KXNFLGAME',event_ticker='E',fee_type_override=None,fee_multiplier_override=None,scheduled_ts='2026-10-02T12:00:00Z')])
        c=context(series,changes,events,'KXNFLGAME','E','2026-10-01T00:00:00+00:00')
        scope=dict(series_id='KXNFLGAME',event_id='E',kalshi_metadata=c)
        self.assertEqual(kalshi_terms(scope,'2026-10-01T01:00:00Z'),dict(fee_type='quadratic',fee_multiplier='3'))
        self.assertEqual(kalshi_terms(scope,'2026-10-03T01:00:00Z'),dict(fee_type='quadratic_with_maker_fees',fee_multiplier='2'))
        with self.assertRaises(ValueError):kalshi_terms(scope,'2026-09-30T01:00:00Z')
        bad=deepcopy(events);bad['cursor']='next'
        with self.assertRaises(ValueError):context(series,changes,bad,'KXNFLGAME','E','2026-10-01T00:00:00+00:00')
        bad=deepcopy(events);bad['event_fee_changes'][0]['event_ticker']='OTHER'
        with self.assertRaises(ValueError):context(series,changes,bad,'KXNFLGAME','E','2026-10-01T00:00:00+00:00')

    def test_exact_documented_envelopes(self):
        self.assertEqual(envelope('/trade-api/v2/series/fee_changes'),'series_fee_change_arr')
        self.assertEqual(envelope('/trade-api/v2/events/fee_changes'),'event_fee_changes')
        validate_envelope({'series':{'ticker':'KXNFLGAME'}},'/trade-api/v2/series/KXNFLGAME')
        validate_envelope({'event_fee_changes':[],'cursor':''},'/trade-api/v2/events/fee_changes')
        with self.assertRaises(ValueError):validate_envelope({'event_fee_changes':{}},'/trade-api/v2/events/fee_changes')
        with self.assertRaises(ValueError):validate_envelope({'series':{}},'/trade-api/v2/unknown')
