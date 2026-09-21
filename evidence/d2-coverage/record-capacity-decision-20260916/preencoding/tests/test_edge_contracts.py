"""E1 adversarial contract boundaries; entirely synthetic, no database/network."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import unittest

from app.edge_contracts import (Economics, Status, SourceDecision, reference_decisions,
                                dumps, loads)
from app.e1_example import fixture, NOW
from app.arbitrage import book_observations
from app.arbitrage_example import synthetic_inputs
from app.depth import book_ladders
from app.models.core import (Money, Venue, OrderBook, Quantity)
from app.storage.replay import replay
from app.fees.engine import digest


class EdgeContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quotes, cls.fair, cls.books, cls.signals = fixture()

    def decision(self, name):
        return next(d for d in self.fair.decisions if d.quote.receipt_id == name)

    def choose(self, quotes, **kw):
        return reference_decisions(quotes, target=kw.get('target', Venue.KALSHI),
            terms=self.fair.terms, cutoff=NOW, max_receipt_age=timedelta(seconds=30), mode='synthetic')

    def test_reference_rejected_by_executable_book_and_depth_entrypoints(self):
        for fn in (book_observations, book_ladders):
            with self.subTest(fn=fn.__name__), self.assertRaisesRegex(ValueError, 'OrderBook'):
                fn(self.quotes[0])
        o = synthetic_inputs()[2][0]
        with self.assertRaisesRegex(ValueError, 'Quote'):
            replace(o, quote=self.quotes[0])
        with self.assertRaisesRegex(ValueError, 'RawPayload'):
            OrderBook(raw=self.quotes[0], quantity_unit='contracts', outcomes=())

    def test_existing_native_books_still_enter_existing_paths(self):
        for book in self.books:
            obs = book_observations(book, environment='synthetic', evidence_class='synthetic',
                                    source_time_semantics='snapshot')
            self.assertTrue(obs)
            self.assertEqual(next(o.quote.ask.price.value for o in obs if o.quote.ask), Decimal('0.40'))

    def test_late_arrival_old_source_time_excluded(self):
        d = self.decision('late-arrival')
        self.assertLess(d.quote.source_at, NOW)
        self.assertIn('received_after_cutoff', d.reasons)
        self.assertFalse(d.included)
        self.assertEqual(self.fair.input_receipt_ids, ('ref-001',))

    def test_tampered_inclusion_cannot_construct_or_replay_estimate(self):
        bad = tuple(replace(d, included=True, reasons=('eligible_contract_input',))
                    if d.quote.receipt_id == 'late-arrival' else d for d in self.fair.decisions)
        with self.assertRaisesRegex(ValueError, 'source decisions'):
            replace(self.fair, decisions=bad)
        payload = json.loads(dumps(self.fair))
        ds = payload['payload']['fields']['decisions']['tuple']
        for d in ds:
            if d['fields']['quote']['fields']['receipt_id'] == 'late-arrival':
                d['fields']['included'] = True
        payload['sha256'] = digest(payload['payload'])
        with self.assertRaisesRegex(ValueError, 'source decisions'):
            loads(json.dumps(payload))

    def test_exact_cutoff_is_inclusive_and_one_microsecond_later_is_not(self):
        q = replace(self.quotes[0], received_at=NOW)
        self.assertTrue(self.choose((q,))[0].included)
        self.assertFalse(self.choose((replace(q, received_at=NOW+timedelta(microseconds=1)),))[0].included)

    def test_source_clock_cannot_outrun_cutoff(self):
        q = replace(self.quotes[0], source_at=NOW + timedelta(seconds=1))
        self.assertIn('source_after_cutoff_clock_uncertainty', self.choose((q,))[0].reasons)

    def test_target_and_known_copy_excluded(self):
        for name in ('target-price', 'known-copy'):
            self.assertIn('target_venue_or_known_copy', self.decision(name).reasons)
        for field in ('provider', 'source_family', 'underlying_source'):
            q = replace(self.quotes[0], **{field:'polymarket_us'})
            self.assertFalse(self.choose((q,), target=Venue.POLYMARKET_US)[0].included)

    def test_duplicate_families_choose_latest_eligible_deterministically(self):
        self.assertIn('duplicate_source_family', self.decision('duplicate-family').reasons)
        self.assertEqual(self.choose(reversed(self.quotes)), self.fair.decisions)
        # A newer future receipt of the same family does not displace eligible history.
        self.assertTrue(self.decision('ref-001').included)
        q = replace(self.quotes[0], receipt_id='z-tie')
        ds = self.choose((self.quotes[0], q))
        self.assertEqual([d.quote.receipt_id for d in ds if d.included], ['z-tie'])

    def test_duplicate_receipt_ids_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'duplicate receipt'):
            self.choose((self.quotes[0], self.quotes[0]))

    def test_terms_and_missing_sides_excluded(self):
        self.assertIn('incompatible_market_terms', self.decision('wrong-period').reasons)
        self.assertIn('missing_paired_outcome', self.decision('missing-side').reasons)
        for terms in (replace(self.fair.terms, rules_profile_json=None),
                      replace(self.fair.terms, outcomes=tuple(reversed(self.fair.terms.outcomes))),
                      replace(self.fair.terms, scheduled_start=NOW+timedelta(days=2))):
            self.assertFalse(self.choose((replace(self.quotes[0], terms=terms),))[0].included)

    def test_unknown_lineage_and_family_excluded(self):
        for change in ({'source_family':None}, {'copied_from':None}, {'identity_evidence':()}):
            d = self.choose((replace(self.quotes[0], **change),))[0]
            self.assertIn('unverified_source_identity_or_lineage', d.reasons)

    def test_stale_and_wrong_mode_are_not_current(self):
        self.assertIn('stale_receipt', self.decision('stale').reasons)
        d = self.choose((replace(self.quotes[0], mode='historical'),))[0]
        self.assertIn('mode_mismatch', d.reasons)

    def test_no_sources_no_price_and_invalid_cutoff(self):
        with self.assertRaisesRegex(ValueError, 'eligible inputs'):
            replace(self.fair, decisions=())
        with self.assertRaisesRegex(ValueError, 'follow cutoff'):
            replace(self.fair, estimated_at=NOW-timedelta(seconds=1))
        with self.assertRaises(ValueError):
            replace(self.fair, as_of=NOW.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            replace(self.fair, max_receipt_age_seconds=0)

    def test_unknown_economics_cannot_be_promoted(self):
        for signal in self.signals:
            self.assertIsNone(signal.economics.total_dollars)
            self.assertIsNone(signal.economics.roi)
            with self.assertRaisesRegex(ValueError, 'unknown'):
                replace(signal.economics, total_dollars=Money(amount=Decimal('12'), currency='USD'))
            with self.assertRaisesRegex(ValueError, 'unknown'):
                replace(signal, status=Status.AVAILABLE)
        self.assertEqual(self.signals[1].probability_gap, Decimal('0.1200'))

    def test_existing_fee_unknowns_survive_detector_replay(self):
        audit = json.loads(self.signals[0].engine_audit_json)
        self.assertEqual(replay(audit), audit)
        calculations = [c['conditional_calculation'] for c in audit['result']['candidates']
                        if c['conditional_calculation'] is not None]
        self.assertTrue(calculations)
        self.assertTrue(all(c['worst_case_profit'] is None and c['worst_case_roi'] is None for c in calculations))

    def test_unknown_settlement_cannot_carry_known_net(self):
        from app.settlement import profile, fact
        old = json.loads(self.fair.terms.rules_profile_json)
        dimensions = {**old['dimensions'], 'tie':fact(reason='unverified tie')}
        unknown_profile = profile(sources=old['sources'], dimensions=dimensions,
                                  payouts=old['payouts'], actor='synthetic-test')
        known = Economics(quantity=Quantity(value=Decimal('100'),unit='contracts'),
            dollars_per_contract=Money(amount=Decimal('0.01'),currency='USD'),
            total_dollars=Money(amount=Decimal('1'),currency='USD'), roi=None,
            capital_denominator=None, denominator_basis='fixture; ROI not calculated', unknowns=())
        with self.assertRaisesRegex(ValueError, 'unknown settlement'):
            replace(self.signals[1], status=Status.CONDITIONAL, economics=known,
                    settlement_profiles_json=(json.dumps(unknown_profile),))

    def test_units_and_roi_denominator(self):
        kwargs = dict(quantity=Quantity(value=Decimal('100'),unit='contracts'),
            dollars_per_contract=Money(amount=Decimal('0.12'),currency='USD'),
            total_dollars=Money(amount=Decimal('12'),currency='USD'), roi=Decimal('0.3'),
            capital_denominator=Money(amount=Decimal('40'),currency='USD'),
            denominator_basis='fixture USD cash committed',unknowns=())
        e = Economics(**kwargs)
        self.assertNotEqual(e.roi, Decimal('0.12'))
        with self.assertRaises(ValueError):
            replace(e, capital_denominator=None)
        with self.assertRaises(ValueError):
            replace(e, quantity=Quantity(value=Decimal('100'),unit='USD_stake'))
        with self.assertRaises(ValueError):
            replace(e, total_dollars=Money(amount=Decimal('12'),currency='EUR'))

    def test_exact_roundtrip_preserves_types_scale_raw_and_all_signals(self):
        bundle = (self.quotes, self.fair, self.books, self.signals)
        encoded = dumps(bundle)
        restored = loads(encoded)
        self.assertEqual(restored, bundle)
        self.assertEqual(dumps(restored), encoded)
        self.assertEqual(str(restored[0][0].decimal_odds[0]), '1.90000000000000000001')
        self.assertEqual(str(restored[0][0].decimal_odds[1]), '2.1000')
        self.assertEqual(restored[0][0].raw_json, self.quotes[0].raw_json)
        self.assertEqual(restored[0][0].raw_sha256, self.quotes[0].raw_sha256)
        self.assertIsInstance(restored[2][0], OrderBook)

    def test_corrupt_provenance_and_unsupported_versions_rejected(self):
        envelope = json.loads(dumps(self.quotes[0]))
        envelope['payload']['fields']['raw_json'] = '{}'
        with self.assertRaisesRegex(ValueError, 'identity/version'):
            loads(json.dumps(envelope))
        envelope['format'] = 'edge-contracts-99'
        with self.assertRaises(ValueError):
            loads(json.dumps(envelope))

    def test_floats_mutable_inputs_bad_odds_and_missing_unknown_reasons_rejected(self):
        for changes in ({'decimal_odds':(1.9,Decimal('2.1'))},
                        {'decimal_odds':(Decimal('NaN'),Decimal('2.1'))},
                        {'decimal_odds':(Decimal('1'),Decimal('2.1'))},
                        {'unknowns':()}, {'identity_evidence':['mutable']},
                        {'received_at':NOW.replace(tzinfo=None)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.quotes[0], **changes)


if __name__ == '__main__':
    unittest.main()
