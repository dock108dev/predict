from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
import json
from pathlib import Path
import unittest

from app.comparison.adapters import adapt, adapt_many, definition_digest, MAX_FACTS, selection_record
from app.comparison.event_links import EventLinks

FIXTURE = Path(__file__).resolve().parents[1] / "app/fixtures/comparison-outcome-adapters-v1.json"


class ComparisonAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.raw = {row["id"]: row["fact"] for row in cls.fixture["rows"]}
        cls.links = EventLinks.from_dict(cls.fixture["links"])
        cls.at = datetime.fromisoformat(cls.fixture["evaluation_at"].replace("Z", "+00:00"))
        cls.samples = {name: adapt(fact, links=cls.links, at=cls.at) for name, fact in cls.raw.items()}

    def adapt(self, fact):
        return adapt(fact, links=self.links, at=self.at)

    def test_exact_retained_us_short_orientation_and_direct_win_match(self):
        short = self.samples["Dallas SHORT"]
        self.assertEqual(short.native.side_id, "2059747")
        self.assertEqual(short.native.market_id, "1030131")
        self.assertEqual(short.participant_id, "NFL:DAL")
        self.assertEqual(short.predicate.operator, "gt")
        self.assertEqual(short.semantic_key(), self.samples["Dallas YES"].semantic_key())
        self.assertEqual(short.semantic_key(), self.samples["Dallas moneyline"].semantic_key())
        self.assertNotEqual(self.samples["Dallas NO"].semantic_key(), self.samples["Tampa Bay LONG"].semantic_key())
        self.assertEqual(self.samples["Dallas NO"].equality.payout.value, Fraction(1, 2))
        self.assertEqual(self.samples["Tampa Bay LONG"].native.side_id, "2059746")

    def test_independent_score_matrix_preserves_equality_total_and_team_total(self):
        for row in self.fixture["score_vectors"]:
            sample = self.samples[row["selection_id"]]
            with self.subTest(row=row):
                self.assertIs(sample.predicate.evaluate(sample.event, row["home"], row["away"]), row["expected"])
        no = self.samples["Dallas NO"]
        opponent = self.samples["Tampa Bay LONG"]
        self.assertTrue(no.predicate.evaluate(no.event, 8, 8))
        self.assertFalse(opponent.predicate.evaluate(opponent.event, 8, 8))

    def test_away_anchor_reversal_and_half_point_equivalence(self):
        fact = deepcopy(self.raw["Tampa Bay +8.5"])
        d = fact["definition"]
        # Away +8.5 cover is away_margin > -8.5, hence home_margin < 8.5.
        self.assertEqual(d["threshold"], "-17/2")
        mapped = self.adapt(fact)
        self.assertEqual(mapped.predicate.threshold.value, Fraction(17, 2))
        self.assertEqual(mapped.predicate.operator, "lt")
        native_no = deepcopy(self.raw["Dallas -8.50"])
        native_no["native"]["side_id"] = "no"
        native_no["definition"].update(side_id="no", position="NO", assertion="complement", complement_evidence="Authored strict complementary side")
        native_no["definition_sha256"] = definition_digest(native_no["definition"])
        other = self.adapt(native_no)
        self.assertEqual(mapped.semantic_key(), other.semantic_key())
        # At an infeasible 8.5 equality, <=8.5 and <8.5 have the same integer truth.
        for home, away, expected in [(8, 0, True), (9, 0, False), (0, 9, True)]:
            self.assertIs(mapped.predicate.evaluate(mapped.event, home, away), expected)
            self.assertIs(other.predicate.evaluate(other.event, home, away), expected)

    def test_original_operator_handicap_15_vector_matrix(self):
        # Independent original authored scores/lines and expected values, not a
        # production formula used to manufacture the oracle.
        expectations = [(-9, "-8.5", False), (-9, "-8", False), (-9, "8.5", False),
                        (-8, "-8.5", False), (-8, "-8", False), (-8, "8.5", True),
                        (0, "-8.5", False), (0, "-8", False), (0, "8.5", True),
                        (8, "-8.5", False), (8, "-8", False), (8, "8.5", True),
                        (9, "-8.5", True), (9, "-8", True), (9, "8.5", True)]
        for margin, line, expected in expectations:
            fact = deepcopy(self.raw["Dallas -8.50"])
            d = fact["definition"]
            d.update(signed_line=line, threshold={"-8.5": "8.5", "-8": "8", "8.5": "-8.5"}[line])
            if line == "-8":
                fact["equality"] = dict(treatment="predicate", payout=None, refund_fees="not_applicable", unknown_reason=None)
            fact["definition_sha256"] = definition_digest(d)
            sample = self.adapt(fact)
            with self.subTest(margin=margin, line=line):
                self.assertIs(sample.predicate.evaluate(sample.event, max(margin, 0), max(-margin, 0)), expected)

    def test_period_line_scope_and_unresolved_participant_rejected_locally(self):
        self.assertNotEqual(self.samples["Dallas first-half win"].semantic_key(), self.samples["Dallas YES"].semantic_key())
        self.assertNotEqual(self.samples["Dallas -8"].semantic_key(), self.samples["Dallas -8.50"].semantic_key())
        for field, value in [("participant_id", None), ("native_participant_id", None), ("domain", "unknown")]:
            fact = deepcopy(self.raw["Dallas YES"])
            fact["definition"][field] = value
            fact["definition_sha256"] = definition_digest(fact["definition"])
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.adapt(fact)
        fact = deepcopy(self.raw["Dallas YES"])
        fact["scope"]["overtime"] = "unknown"
        with self.assertRaises(ValueError):
            self.adapt(fact)

    def test_definition_side_and_event_are_exact_and_expired_is_not_renewed(self):
        for change in ["digest", "side", "event", "position", "complement"]:
            fact = deepcopy(self.raw["Dallas YES"])
            if change == "digest":
                fact["definition"]["operator"] = "le"
            elif change == "side":
                fact["native"]["side_id"] = "no"
            elif change == "event":
                fact["event"]["occurrence_id"] = "authored:rematch"
            elif change == "position":
                fact["definition"]["position"] = "LONG"
                fact["definition_sha256"] = definition_digest(fact["definition"])
            else:
                fact = deepcopy(self.raw["Dallas NO"])
                fact["definition"]["complement_evidence"] = None
                fact["definition_sha256"] = definition_digest(fact["definition"])
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.adapt(fact)
        with self.assertRaises(ValueError):
            adapt(self.raw["Dallas SHORT"], links=self.links, at=datetime(2026, 10, 9, 0, 15, tzinfo=timezone.utc))

    def test_duplicate_instruments_do_not_create_quotes_or_fake_pairs(self):
        good = deepcopy(self.raw["Dallas YES"])
        batch = adapt_many([good, deepcopy(good), self.raw["Dallas SHORT"]], links=self.links, at=self.at)
        self.assertEqual(len(batch.selections), 2)
        self.assertEqual(batch.duplicates, 1)
        changed = deepcopy(good)
        changed["definition"]["operator"] = "ge"
        changed["definition_sha256"] = definition_digest(changed["definition"])
        batch = adapt_many([good, changed, self.raw["Dallas SHORT"]], links=self.links, at=self.at)
        self.assertEqual([x.native.side_id for x in batch.selections], ["2059747"])
        self.assertEqual(len(batch.rejected), 1)
        with self.assertRaises(ValueError):
            adapt_many([good] * (MAX_FACTS + 1), links=self.links, at=self.at)

    def test_record_exposes_input_and_unknown_without_metric_or_acquisition(self):
        result = selection_record(self.samples["Dallas SHORT"])
        self.assertEqual(result["settlement_status"], "unbound")
        self.assertIsNone(result["comparison_input"]["payout"])
        self.assertIsNone(result["comparison_input"]["payout_unknown"]["value"])
        self.assertEqual(result["comparison_input"]["native"]["original_wording"], self.raw["Dallas SHORT"]["native"]["original_wording"])


if __name__ == "__main__":
    unittest.main()
