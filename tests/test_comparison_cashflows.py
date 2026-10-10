"""Independent original cashflow oracles; no production formula supplies answers."""
from copy import deepcopy
from dataclasses import replace
from decimal import localcontext
from fractions import Fraction
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.comparison.adapters import adapt
from app.comparison.cashflows import cashflow_inputs, evaluate_portfolio, exact_wire
from app.comparison.domain import ExactNumber, Quantity
from app.comparison.event_links import EventLinks, instant
from app.comparison.payouts import CompletionContext, PayoutCell, PayoutProfile, ScoreRange, bind_profile, joint_states

FIXTURES = Path(__file__).resolve().parents[1] / "app/fixtures"


class ComparisonCashflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = json.loads((FIXTURES / "comparison-payouts-v1.json").read_text())
        adapters = json.loads((FIXTURES / "comparison-outcome-adapters-v1.json").read_text())
        cls.at = instant(fixture["evaluation_at"])
        cls.context = CompletionContext.from_dict(fixture["ordinary_context"])
        cls.delayed = CompletionContext.from_dict(fixture["72_hour_context"])
        links = EventLinks.from_dict(adapters["links"])
        cls.selections = {row["id"]: adapt(row["fact"], links=links, at=cls.at) for row in adapters["rows"]}
        cls.profiles = {row["selection_id"]: PayoutProfile.from_dict(row["profile"]) for row in fixture["profile_rows"]}

    def bound(self, name, *, profile=None, selection=None, context=None):
        profile = profile or self.profiles[name]
        return bind_profile(selection or self.selections[name], profile, at=self.at,
                            rule_revision=profile.rule_revision, context=context or self.context)

    def pair(self, *, quantities=("1", "1"), exception=False):
        # Research's independent 2/5 + 11/20 example, not the fixture's default.
        selected = replace(self.selections["Tampa Bay LONG"], price=replace(self.selections["Tampa Bay LONG"].price, amount=ExactNumber("11/20")))
        return cashflow_inputs((self.bound("Dallas YES"), self.bound("Tampa Bay LONG", selection=selected)),
                               quantities, at=self.at, include_exceptions=exception)

    def test_known_leg_and_portfolio_win_loss_tie_original_rational_oracles(self):
        inputs = self.pair(exception=True)
        wire = inputs.to_dict()
        self.assertEqual([Fraction(row["acquisition_cash"]) for row in wire["legs"]], [Fraction(2, 5), Fraction(11, 20)])
        self.assertEqual([Fraction(value) if value is not None else None for value in wire["legs"][0]["profits"].values()],
                         [Fraction(-2, 5), Fraction(1, 10), Fraction(3, 5), None])
        self.assertEqual([Fraction(value) if value is not None else None for value in wire["legs"][1]["profits"].values()],
                         [Fraction(9, 20), Fraction(-1, 20), Fraction(-11, 20), None])
        result = evaluate_portfolio(inputs)
        self.assertEqual([Fraction(v) if v is not None else None for v in result["full"]["states"].values()],
                         [Fraction(1, 20), Fraction(1, 20), Fraction(1, 20), None])
        self.assertIsNone(result["full"]["worst_case_return"])
        self.assertFalse(result["all_modeled_outcome_profitable"])
        self.assertTrue(result["conditional_profitable"])
        self.assertEqual(Fraction(result["conditional"]["return_denominator"]), Fraction(19, 20))
        self.assertEqual(Fraction(result["conditional"]["return_pct"]), Fraction(100, 19))
        self.assertEqual(result["conditional"]["state_ids"], list(inputs.state_ids[:-1]))

    def test_two_sizes_and_differing_native_stake_tie_cashflows(self):
        for size in ("1", "3.5"):
            q = Fraction(size)
            with self.subTest(size=size):
                inputs = cashflow_inputs((self.bound("Dallas YES"), self.bound("Dallas moneyline")), (size, size), at=self.at, include_exceptions=False)
                result = evaluate_portfolio(inputs)
                # Per-contract 1/2 and per-stake refund 1 are different receipts.
                self.assertEqual([Fraction(v) for v in result["full"]["states"].values()],
                                 [Fraction(-7, 5) * q, Fraction(1, 10) * q, Fraction(8, 5) * q])
                self.assertEqual(Fraction(result["conditional"]["return_denominator"]), Fraction(7, 5) * q)
                self.assertEqual(inputs.to_dict()["legs"][1]["quantity_unit"], "usd_risk")
                self.assertEqual(result["estimate_class"], "contains_estimated_payouts")

    def test_tie_losing_pair_never_all_outcome_profitable(self):
        profile = replace(self.profiles["Dallas YES"], version="authored-strict-win-2", rule_revision="authored-strict-win-2",
                          equal=PayoutCell(ExactNumber("0"), "estimated", "Authored strict-win tie-zero sensitivity"),
                          noncompleted=PayoutCell(ExactNumber("1"), "estimated", "Authored terminal face repayment sensitivity"))
        equality = replace(self.selections["Dallas YES"].equality, treatment="predicate", payout=None)
        selected = replace(self.selections["Dallas YES"], equality=equality)
        first = self.bound("Dallas YES", profile=profile, selection=selected)
        second_profile = replace(self.profiles["Tampa Bay LONG"], version="authored-terminal-2", rule_revision="authored-terminal-2",
                                 noncompleted=PayoutCell(ExactNumber("1"), "estimated", "Authored terminal face repayment sensitivity"))
        inputs = cashflow_inputs((first, self.bound("Tampa Bay LONG", profile=second_profile)), ("1", "1"), at=self.at)
        result = evaluate_portfolio(inputs)
        expected = [Fraction(1, 5), Fraction(-3, 10), Fraction(1, 5), Fraction(6, 5)]
        self.assertEqual([Fraction(v) for v in result["full"]["states"].values()], expected)
        self.assertEqual(Fraction(result["full"]["worst_case_return"]), Fraction(-3, 10))
        self.assertFalse(result["all_modeled_outcome_profitable"])
        self.assertFalse(result["conditional_profitable"])

    def test_integer_push_void_and_fee_retention_remain_explicit(self):
        leg = self.bound("Dallas -8")
        profile = replace(leg.profile, version="authored-refund-2", rule_revision="authored-refund-2",
                          noncompleted=PayoutCell(ExactNumber("1"), "estimated", "Authored void returns USD stake; entry fee retained"))
        inputs = cashflow_inputs((self.bound("Dallas -8", profile=profile),), ("10",), at=self.at)
        engine = evaluate_portfolio(inputs)
        equality = next(s.state_id for s in inputs.table.states if s.score_range == ScoreRange(8, 8))
        self.assertEqual(Fraction(engine["full"]["states"][equality]), 0)
        self.assertEqual(Fraction(engine["full"]["states"]["noncompleted"]), 0)
        # Explicit fee-inclusive cash 10.25; refund receipts stay 10, no fee erase.
        fee_result = evaluate_portfolio(inputs, cash=("10.25",), fee_basis="authored_retained_entry_fee")
        self.assertEqual(Fraction(fee_result["full"]["states"][equality]), Fraction(-1, 4))
        self.assertEqual(Fraction(fee_result["full"]["states"]["noncompleted"]), Fraction(-1, 4))
        self.assertNotEqual(engine["revision"], fee_result["revision"])

    def test_negative_net_receipt_separately_funds_liability_once(self):
        inputs = self.pair()
        states = inputs.state_ids
        result = evaluate_portfolio(inputs, cash=("2/5", "11/20"),
                                    receipts=({state: "-1/4" for state in states}, {state: "1" for state in states}),
                                    fee_basis="authored_settlement_debit")
        self.assertEqual(Fraction(result["full"]["acquisition_cash"]), Fraction(19, 20))
        self.assertEqual(Fraction(result["full"]["settlement_liability_funding"]), Fraction(1, 4))
        self.assertEqual(Fraction(result["full"]["return_denominator"]), Fraction(6, 5))
        self.assertEqual([Fraction(v) for v in result["full"]["states"].values()], [Fraction(-1, 5)] * 3)

    def test_unknown_cost_or_receipt_never_zero_and_other_states_survive(self):
        inputs = self.pair()
        unknown_cash = evaluate_portfolio(inputs, cash=(None, "0.55"), fee_basis="cost_unavailable")
        self.assertTrue(all(v is None for v in unknown_cash["full"]["states"].values()))
        self.assertFalse(unknown_cash["conditional_profitable"])
        rows = tuple(deepcopy(leg.to_dict()["receipts"]) for leg in inputs.legs)
        rows[0][inputs.state_ids[1]] = None
        missing_tie = evaluate_portfolio(inputs, receipts=rows, fee_basis="tie_cost_unknown")
        self.assertIsNone(missing_tie["full"]["states"][inputs.state_ids[1]])
        self.assertEqual(Fraction(missing_tie["full"]["states"][inputs.state_ids[0]]), Fraction(1, 20))
        self.assertEqual(missing_tie["conditional"]["state_ids"], [inputs.state_ids[0], inputs.state_ids[2]])

    def test_completed_only_cannot_inherit_all_terminal_label(self):
        result = evaluate_portfolio(self.pair())
        self.assertFalse(result["partition_complete"])
        self.assertFalse(result["all_modeled_outcome_profitable"])
        self.assertTrue(result["conditional_profitable"])
        self.assertIsNone(result["full"]["worst_case_return"])
        self.assertIn("Applicable state coverage incomplete", result["full"]["reasons"])

    def test_exact_rational_shared_engine_not_rounded_and_context_independent(self):
        inputs = self.pair(quantities=("1/3", "1/3"))
        with localcontext() as context:
            context.prec = 3
            actual = evaluate_portfolio(inputs)
        self.assertEqual([Fraction(v) for v in actual["full"]["states"].values()], [Fraction(1, 60)] * 3)
        self.assertEqual(Fraction(actual["conditional"]["return_denominator"]), Fraction(19, 60))
        self.assertEqual(Fraction(actual["conditional"]["return_pct"]), Fraction(100, 19))
        from app.settlement import portfolio as shared
        with patch("app.comparison.cashflows.portfolio", wraps=shared) as reused:
            self.assertEqual(evaluate_portfolio(inputs), actual)
            self.assertEqual(reused.call_count, 2)
        self.assertEqual(exact_wire(Fraction(1, 3)), "1/3")
        self.assertEqual(exact_wire(Fraction(-9, 40)), "-0.225")

    def test_price_quantity_profile_and_completion_revisions_change(self):
        inputs = self.pair()
        resized = self.pair(quantities=("2", "2"))
        self.assertNotEqual(inputs.revision, resized.revision)
        selected = replace(self.selections["Dallas YES"], price=replace(self.selections["Dallas YES"].price, amount=ExactNumber("0.41")))
        repriced = cashflow_inputs((self.bound("Dallas YES", selection=selected),), ("1",), at=self.at)
        original = cashflow_inputs((self.bound("Dallas YES"),), ("1",), at=self.at)
        self.assertNotEqual(original.revision, repriced.revision)
        delayed = cashflow_inputs((self.bound("Dallas YES", context=self.delayed), self.bound("Dallas SHORT", context=self.delayed)),
                                  ("1", "1"), at=self.at)
        self.assertIsNone(delayed.to_dict()["legs"][0]["receipts"][delayed.state_ids[2]])
        self.assertEqual(delayed.to_dict()["legs"][1]["receipts"][delayed.state_ids[2]], "1")
        self.assertIn("fair-price", delayed.to_dict()["legs"][0]["reasons"][delayed.state_ids[2]])
        self.assertEqual(delayed.to_dict()["completion_conditions"][0]["context"], self.delayed.to_dict())

    def test_public_snapshot_cannot_mutate_shared_inputs_and_stale_revision_refuses(self):
        inputs = self.pair()
        before = inputs.to_dict()
        returned = inputs.to_dict()
        returned["completion_conditions"][0]["context"]["started_at"] = "2026-10-11T00:15:00Z"
        returned["legs"][0]["price"]["amount"] = "0"
        returned["legs"][0]["receipts"][inputs.state_ids[0]] = "100"
        self.assertEqual(inputs.to_dict(), before)
        with self.assertRaisesRegex(ValueError, "revision"):
            replace(inputs, revision="forged")
        # A direct mutation of a shared field is detected before any calculation.
        inputs.legs[0].price["amount"] = "0"
        with self.assertRaisesRegex(ValueError, "revision"):
            evaluate_portfolio(inputs)

    def test_expired_sibling_period_domain_and_bad_quantities_refused(self):
        with self.assertRaisesRegex(ValueError, "expired"):
            cashflow_inputs((self.bound("Dallas YES"),), ("1",), at=instant("2026-10-09T00:15:00Z"))
        with self.assertRaises(ValueError):
            self.bound("Dallas NO", profile=self.profiles["Dallas YES"])
        for second in ("Dallas first-half win", "Combined over 20.5", "Dallas YES"):
            with self.subTest(second=second), self.assertRaises(ValueError):
                cashflow_inputs((self.bound("Dallas YES"), self.bound(second)), ("1", "1"), at=self.at)
        for quantity in ("0", "-1", 1.0, True, Quantity(ExactNumber("1"), "usd_risk", "USD")):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                cashflow_inputs((self.bound("Dallas YES"),), (quantity,), at=self.at)

    def test_incomplete_overlap_duplicate_lifecycle_forged_table_refused(self):
        legs = (self.bound("Dallas YES"),)
        table = joint_states(legs, at=self.at)
        alternatives = [replace(table, states=table.states[1:]),
                        replace(table, states=table.states + (replace(table.states[-1], state_id="duplicate-void"),)),
                        replace(table, states=(replace(table.states[0], score_range=ScoreRange(None, 0)),) + table.states[1:]),
                        replace(table, states=(replace(table.states[0], payouts=(PayoutCell(ExactNumber("1"), "evidenced", None),)),) + table.states[1:]),
                        replace(table, coverage="conditional_completed")]
        for forged in alternatives:
            with self.subTest(forged=forged.coverage), self.assertRaisesRegex(ValueError, "partition"):
                cashflow_inputs(legs, ("1",), at=self.at, table=forged)
        inputs = cashflow_inputs(legs, ("1",), at=self.at, table=table)
        with self.assertRaisesRegex(ValueError, "Receipt set"):
            evaluate_portfolio(inputs, receipts=({inputs.state_ids[0]: "1"},))
        with self.assertRaises(ValueError):
            evaluate_portfolio(inputs, cash=("-1",))
        with self.assertRaisesRegex(ValueError, "precision"):
            evaluate_portfolio(inputs, cash=(Fraction(10**95),))


if __name__ == "__main__":
    unittest.main()
