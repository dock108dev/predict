from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal, localcontext
import unittest

from app.models.core import (
    BookLevel, BookSync, Depth, Event, EvidenceKind, Ladder, Market, MarketState,
    Money, NativeRef, OrderBook, Outcome, OutcomeBook, Probability, Quantity,
    Quote, QuoteSide, RawPayload, SettlementComparison, SettlementCompatibility,
    SettlementProfile, Venue, parse_decimal,
)


def raw(market_id="m-001"):
    return RawPayload(ref=NativeRef(venue=Venue.SYNTHETIC, event_id="e-001", market_id=market_id),
                      source="synthetic://test", received_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
                      json_text=' {"native_id":"001", "price":0.12345678901234567890123456789, "nested":[null]} ',
                      kind=EvidenceKind.SYNTHETIC)


def level(price="0.4", size="1.25", unit="contracts"):
    return BookLevel(price=Probability(value=Decimal(price)), quantity=Quantity(value=Decimal(size), unit=unit))


class NumericTests(unittest.TestCase):
    def test_exact_precision_without_context_rounding(self):
        value = "0.123456789012345678901234567890123456789"
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(str(Probability(value=parse_decimal(value)).value), value)
            self.assertEqual(str(Money(amount=Decimal(value), currency="USD").amount), value)
            self.assertEqual(str(Quantity(value=Decimal(value), unit="native_lots").value), value)

    def test_invalid_numeric_inputs(self):
        for invalid in (True, False, 0.1, None, {}, [], "not-a-number", "NaN", "sNaN", "Infinity", "-Infinity"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_decimal(invalid)
        for cls, field, extra in ((Probability, "value", {}), (Quantity, "value", {"unit": "contracts"}),
                                  (Money, "amount", {"currency": "USD"})):
            for invalid in (True, 1, "0.1", 0.1, Decimal("NaN"), Decimal("Infinity")):
                with self.subTest(cls=cls, invalid=invalid), self.assertRaises(ValueError):
                    cls(**{field: invalid}, **extra)

    def test_ranges_and_units(self):
        for value in ("-0.001", "1.001"):
            with self.assertRaises(ValueError):
                Probability(value=Decimal(value))
        for value in ("0", "1"):
            Probability(value=Decimal(value))
        with self.assertRaises(ValueError):
            Quantity(value=Decimal("-1"), unit="contracts")
        with self.assertRaises(ValueError):
            Quantity(value=Decimal("1"), unit="")
        with self.assertRaises(ValueError):
            Money(amount=Decimal("1"), currency="usd")
        self.assertEqual(Money(amount=Decimal("-1.0001"), currency="USD").amount, Decimal("-1.0001"))


class ObservationTests(unittest.TestCase):
    def test_timestamps_and_unknown_exchange_clock(self):
        source = raw()
        self.assertIsNone(source.exchange_at)
        for field in ("exchange_at", "received_at"):
            for bad in (datetime(2026, 9, 11), "2026-09-11T12:00:00Z"):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    replace(source, **{field: bad})
        with self.assertRaises(ValueError):
            replace(source, received_at=None)
        eastern = datetime(2026, 9, 11, tzinfo=timezone(timedelta(hours=-4)))
        self.assertEqual(replace(source, exchange_at=eastern).exchange_at, eastern)
        # Future relative to receipt is retained; clock skew isn't silently repaired.
        self.assertEqual(replace(source, exchange_at=eastern).received_at, source.received_at)
        with self.assertRaises(ValueError):
            Event(raw=raw(None), title="Invented", scheduled_start=datetime(2026, 9, 11))

    def test_native_ids_and_unmapped_ingestion(self):
        event = Event(raw=raw(None), title="Invented")
        market = Market(raw=raw(), title="Invented", outcomes=(Outcome(native_id="01", label="First"),))
        self.assertIsNone(event.canonical_id)
        self.assertIsNone(market.canonical_id)
        self.assertEqual(market.raw.ref.event_id, "e-001")
        self.assertEqual(market.raw.ref.market_id, "m-001")
        self.assertEqual(market.outcomes[0].native_id, "01")
        self.assertEqual(market.state, MarketState.UNKNOWN)
        with self.assertRaises(ValueError):
            replace(market, raw=raw(None))
        with self.assertRaises(ValueError):
            replace(market, canonical_id="")
        with self.assertRaises(ValueError):
            replace(market, outcomes=market.outcomes * 2)
        with self.assertRaises(ValueError):
            replace(market, state="active")

    def test_raw_text_and_nested_payload_preservation(self):
        source = raw()
        original = source.json_text
        decoded = source.decode()
        self.assertEqual(decoded["price"], Decimal("0.12345678901234567890123456789"))
        decoded["nested"].append("mutation")
        self.assertEqual(source.decode()["nested"], [None])
        self.assertEqual(source.json_text, original)
        with self.assertRaises(FrozenInstanceError):
            source.json_text = "{}"
        for invalid in ('{"price":NaN}', '{', '[] garbage'):
            with self.assertRaises(ValueError):
                replace(source, json_text=invalid)

    def test_unknown_quotes_and_settlement(self):
        quote = Quote(raw=raw(), outcome_id="01")
        self.assertIsNone(quote.bid)
        self.assertIsNone(quote.ask)
        self.assertEqual(quote.state, MarketState.UNKNOWN)
        side = QuoteSide(price=Probability(value=Decimal("0.4")))
        self.assertIsNone(side.quantity)
        profile = SettlementProfile(raw=raw())
        self.assertIsNone(profile.includes_overtime)
        self.assertIsNone(profile.rules_text)
        self.assertIsNone(profile.cancellation_behavior)
        comparison = SettlementComparison(left=raw().ref, right=raw("m-002").ref)
        self.assertEqual(comparison.compatibility, SettlementCompatibility.UNKNOWN)
        with self.assertRaises(ValueError):
            replace(comparison, compatibility=SettlementCompatibility.COMPATIBLE)
        with self.assertRaises(ValueError):
            replace(profile, includes_overtime="unknown")
        bid = QuoteSide(price=side.price, quantity=Quantity(value=Decimal("1"), unit="contracts"))
        ask = replace(bid, quantity=Quantity(value=Decimal("1"), unit="USD_stake"))
        with self.assertRaises(ValueError):
            replace(quote, bid=bid, ask=ask)


class BookTests(unittest.TestCase):
    def test_unavailable_empty_and_partial_are_distinct(self):
        book = OrderBook(raw=raw(), quantity_unit="contracts", outcomes=(
            OutcomeBook(outcome_id="yes", bids=Ladder(levels=(level(),), depth=Depth.PARTIAL)),
            OutcomeBook(outcome_id="no", bids=Ladder(levels=(), depth=Depth.FULL)),
        ))
        self.assertIsNone(book.outcomes[0].asks)
        self.assertEqual(book.outcomes[1].bids.levels, ())
        self.assertEqual(book.outcomes[0].bids.depth, Depth.PARTIAL)
        self.assertEqual(book.sync, BookSync.UNKNOWN)
        self.assertEqual(book.state, MarketState.UNKNOWN)
        self.assertIsNone(book.sequence)
        self.assertEqual(Ladder(levels=()).depth, Depth.UNKNOWN)
        self.assertIsNone(OutcomeBook(outcome_id="missing").bids)

    def test_invalid_ladders(self):
        for size in ("0", "-1"):
            with self.assertRaises(ValueError):
                level(size=size)
        with self.assertRaises(ValueError):
            Ladder(levels=(level(), level()))
        with self.assertRaises(ValueError):
            Ladder(levels=[level()])
        with self.assertRaises(ValueError):
            OutcomeBook(outcome_id="yes", bids=Ladder(levels=(level("0.3"), level("0.4"))))
        with self.assertRaises(ValueError):
            OutcomeBook(outcome_id="yes", asks=Ladder(levels=(level("0.4"), level("0.3"))))

    def test_units_and_outcome_identity(self):
        outcome = OutcomeBook(outcome_id="yes", bids=Ladder(levels=(level(unit="payout_cents"),)))
        with self.assertRaises(ValueError):
            OrderBook(raw=raw(), quantity_unit="contracts", outcomes=(outcome,))
        with self.assertRaises(ValueError):
            OrderBook(raw=raw(), quantity_unit="payout_cents", outcomes=(outcome, outcome))
        book = OrderBook(raw=raw(), quantity_unit="payout_cents", outcomes=(outcome,))
        self.assertEqual(book.outcomes[0].bids.levels[0].quantity.value, Decimal("1.25"))
