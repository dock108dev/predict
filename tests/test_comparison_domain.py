"""Portable authored truths; neither provider acquisitions nor archive oracles."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import unittest

from app.comparison.domain import (
    CanonicalSelection, ExactNumber, Quantity, UnknownValue, VERSION,
)

FIXTURE = Path(__file__).resolve().parents[1] / "app/fixtures/comparison-domain-v1.json"
SCHEMA = FIXTURE.with_name("comparison-domain-schema-v1.json")


class ComparisonDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.raw = {row["id"]: row["selection"] for row in cls.fixture["samples"]}
        cls.samples = {name: CanonicalSelection.from_dict(raw) for name, raw in cls.raw.items()}

    def test_wire_roundtrip_retains_decimal_and_rational_originals(self):
        for name, raw in self.raw.items():
            with self.subTest(name=name):
                self.assertEqual(json.loads(json.dumps(self.samples[name].to_dict())), raw)
        spread = self.samples["Dallas -8.50"]
        self.assertEqual(spread.signed_line.original, "-8.50")
        self.assertEqual(spread.predicate.threshold.original, "17/2")
        self.assertEqual(spread.price.amount.original, "0.4000")
        self.assertEqual(spread.predicate.threshold.value, Fraction(17, 2))

    def test_independent_original_score_truths(self):
        for row in self.fixture["score_vectors"]:
            selection = self.samples[row["selection_id"]]
            with self.subTest(row=row):
                self.assertIs(selection.predicate.evaluate(selection.event, row["home"], row["away"]), row["expected"])

    def test_same_predicate_separate_cashflow_and_wording(self):
        yes = self.samples["Dallas YES"]
        sportsbook = self.samples["Dallas moneyline"]
        self.assertEqual(yes.semantic_key(), sportsbook.semantic_key())
        self.assertNotEqual(yes.cashflow_key(), sportsbook.cashflow_key())
        self.assertNotEqual(self.samples["Dallas NO"].semantic_key(), self.samples["Tampa Bay LONG"].semantic_key())
        renamed = replace(yes, native=replace(yes.native, original_wording="A different language label"))
        self.assertEqual(yes.semantic_key(), renamed.semantic_key())
        self.assertEqual(yes.cashflow_key(), renamed.cashflow_key())

    def test_scope_role_line_and_occurrence_do_not_merge(self):
        yes = self.samples["Dallas YES"]
        candidates = [self.samples["Dallas first-half win"], self.samples["Dallas -8.50"],
                      replace(yes, scope=replace(yes.scope, overtime="excluded")),
                      replace(yes, event=replace(yes.event, occurrence_id="authored:rematch")),
                      replace(yes, event=replace(yes.event, home_id="NFL:TB", away_id="NFL:DAL"))]
        for other in candidates:
            self.assertNotEqual(yes.semantic_key(), other.semantic_key())
        same_number = replace(self.samples["Dallas -8.50"], predicate=replace(self.samples["Dallas -8.50"].predicate, threshold=ExactNumber("8.5000")))
        self.assertEqual(same_number.semantic_key(), self.samples["Dallas -8.50"].semantic_key())

    def test_exact_inputs_reject_float_boolean_nonfinite_and_quarter_line(self):
        for value in [1.0, True, 1, None, "NaN", "Infinity", "1e-2", " 0.5", "1/0", "1/2/3"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ExactNumber.parse(value)
        changed = deepcopy(self.raw["Dallas -8.50"])
        changed["signed_line"] = "-8.25"
        changed["predicate"]["threshold"] = "8.25"
        with self.assertRaises(ValueError):
            CanonicalSelection.from_dict(changed)

    def test_strict_version_unknown_fields_roles_and_signed_handicap(self):
        cases = []
        for key, value in [("schema_version", "comparison-domain-2"), ("invented", 1), ("participant_id", "NFL:UNKNOWN")]:
            raw = deepcopy(self.raw["Dallas YES"])
            raw[key] = value
            cases.append(raw)
        raw = deepcopy(self.raw["Dallas -8.50"])
        raw["signed_line"] = "8.50"
        cases.append(raw)
        raw = deepcopy(self.raw["Dallas YES"])
        raw["event"]["scheduled_start"] = "2026-10-09T00:18:00Z"
        cases.append(raw)
        raw = deepcopy(self.raw["Dallas YES"])
        raw["event"]["away_id"] = raw["event"]["home_id"]
        cases.append(raw)
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                CanonicalSelection.from_dict(raw)

    def test_unknown_is_null_with_named_evidence_not_zero(self):
        raw = deepcopy(self.raw["Dallas YES"])
        raw["payout"] = None
        raw["payout_unknown"] = {"value": None, "reason": "Exact effective rule unavailable", "missing_evidence": ["Current instrument clause snapshot"]}
        value = CanonicalSelection.from_dict(raw)
        self.assertIsNone(value.payout)
        self.assertIsInstance(value.payout_unknown, UnknownValue)
        self.assertEqual(value.to_dict(), raw)
        self.assertEqual(value.semantic_key(), self.samples["Dallas YES"].semantic_key())
        raw["payout_unknown"]["value"] = "0"
        with self.assertRaises(ValueError):
            CanonicalSelection.from_dict(raw)
        unresolved = replace(value, scope=replace(value.scope, overtime="unknown"))
        with self.assertRaises(ValueError):
            unresolved.semantic_key()

    def test_profile_sibling_units_and_equality_are_strict(self):
        changed = deepcopy(self.raw["Dallas YES"])
        changed["payout"]["side_id"] = "no"
        with self.assertRaises(ValueError):
            CanonicalSelection.from_dict(changed)
        for price in [{"amount": "0.5", "unit": "decimal_odds", "payout_unit": "usd_per_usd_stake", "currency": "USD"},
                      {"amount": "40", "unit": "cents_per_contract", "payout_unit": "usd_per_usd_stake", "currency": "USD"}]:
            changed = deepcopy(self.raw["Dallas YES"])
            changed["price"] = price
            with self.assertRaises(ValueError):
                CanonicalSelection.from_dict(changed)
        changed = deepcopy(self.raw["Dallas YES"])
        changed["equality"]["payout"] = "3/2"
        with self.assertRaises(ValueError):
            CanonicalSelection.from_dict(changed)
        self.assertEqual(Quantity(ExactNumber("100.00"), "usd_risk", "USD").to_dict()["amount"], "100.00")
        with self.assertRaises(ValueError):
            Quantity(ExactNumber("100"), "contracts", "USD")

    def test_schema_declares_version_and_exact_shape(self):
        schema = json.loads(SCHEMA.read_text())
        self.assertEqual(schema["properties"]["schema_version"]["const"], VERSION)
        self.assertEqual(set(schema["required"]), set(self.raw["Dallas YES"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["$defs"]["price"]["properties"]["amount"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
