"""Literal portfolio oracles, bounded search and existing shared-engine seams."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import unittest

from app.comparison.adapters import adapt
from app.comparison.buffers import DepthLeg, DepthLevel, depth_allocation
from app.comparison.cashflows import cashflow_inputs
from app.comparison.costs import (
    CostRegistry, CostRequest, CostRule, DepthInputs, FeeTerms, FillInputs,
    FundingComponent, QuantityGridInputs, UnitSpec,
)
from app.comparison.domain import EvidenceReference, ExactNumber
from app.comparison.event_links import EventLinks, instant
from app.comparison.net_arbs import ArbLeg, ArbLimits, evaluate_arb_allocation, search_arbs
from app.comparison.net_costs import calculate_net_costs, wire
from app.comparison.payouts import CompletionContext, PayoutCell, PayoutProfile, bind_profile, selection_digest
from app.fees.engine import Registry


ROOT = Path(__file__).resolve().parents[1]
TIME = "2026-10-08T12:00:00Z"
EVIDENCE = EvidenceReference("authored:comparison-net-arb-vectors-1", "b" * 64, "authored")


class NetArbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / "app/fixtures/comparison-net-arbs-v1.json").read_text())
        adapters = json.loads((ROOT / "app/fixtures/comparison-outcome-adapters-v1.json").read_text())
        payouts = json.loads((ROOT / "app/fixtures/comparison-payouts-v1.json").read_text())
        cls.at = instant(TIME)
        links = EventLinks.from_dict(adapters["links"])
        cls.selections = {row["id"]: adapt(row["fact"], links=links, at=cls.at) for row in adapters["rows"]}
        cls.profiles = {row["selection_id"]: PayoutProfile.from_dict(row["profile"]) for row in payouts["profile_rows"]}
        cls.context = CompletionContext.from_dict(payouts["ordinary_context"])

    def bound(self, name, *, price=None, venue=None, complete=True, tie=None, win=None):
        selected = self.selections[name]
        if price is not None:
            selected = replace(selected, price=replace(selected.price, amount=ExactNumber(price)))
        if venue:
            selected = replace(selected, native=replace(selected.native, venue=venue, evidence=(EVIDENCE,),
                original_wording="Authored exact cashflow example"))
        profile = self.profiles[name]
        changes = dict(native_key=selected.native.key, version="authored-arb-payout-1", rule_revision="authored-arb-payout-1",
                       source_evidence=(EVIDENCE,))
        if complete:
            changes["noncompleted"] = PayoutCell(ExactNumber(tie or "0.5"), "estimated", "Authored terminal payout sensitivity")
        if tie is not None:
            selected = replace(selected, equality=replace(selected.equality, treatment="fraction", payout=ExactNumber(tie)))
            changes["equal"] = PayoutCell(ExactNumber(tie), "estimated", "Authored tie payout sensitivity")
        if win is not None:
            changes["above" if name == "Dallas YES" else "below"] = PayoutCell(ExactNumber(win), "estimated", "Authored unequal face payout")
        profile = replace(profile, **changes)
        return bind_profile(selected, profile, at=self.at, rule_revision=profile.rule_revision, context=self.context)

    def leg(self, bound, *, right_fee="0", available="100", minimum="1", increment="1", liquidity=None):
        venue, event, market, _, _ = bound.selection.native.key
        unit = UnitSpec("dollar_face_contracts", "1")
        grid = QuantityGridInputs(minimum, increment, "0.01", EVIDENCE)
        price = bound.selection.price.amount.original
        if bound.selection.price.unit == "cents_per_contract":
            price = wire(Fraction(price) / 100)
        depth = DepthLeg(venue + market, unit, grid, DepthInputs(available, EVIDENCE),
            (DepthLevel(price, available, liquidity or venue + market, EVIDENCE),), True,
            native_key=bound.selection.native.key)
        if venue == "kalshi":
            terms = FeeTerms("quadratic", "0", "0.000001", "ceiling", "order_accumulator", "taker")
        else:
            terms = FeeTerms("quantity", right_fee, "0.01", "half_even", "order", "taker")
        rule = CostRule("authored-arb-fee-" + venue, venue, "single", "authored", "controlled_scenario",
                        "2026-10-08T00:00:00Z", None, None, unit, terms, "declared_zero", True, (EVIDENCE,))
        registry = CostRegistry(dict(schema=1, version="comparison-cost-inputs-1", rules=[rule.to_dict()]))
        request = CostRequest(venue, "single", "authored", TIME, TIME, event_id=event, market_id=market,
                              series_id="s", pinned_version=rule.version, allow_controlled_scenario=True)
        kwargs = dict(registry=registry)
        if venue == "kalshi":
            kwargs["engine_registry"] = Registry(dict(schema=1, schedules=[dict(venue=venue, product="single",
                version="authored-arb-shared", coefficient="0", effective_from=TIME, effective_to=None)]))
            kwargs["engine_context"] = dict(venue=venue, product="single", channel="authored", environment="authored",
                market_id=market, event_id=event, series_id="s", trade_time=TIME, calculation_time=TIME,
                schedule_version="authored-arb-shared", balance_precision="0.0001",
                kalshi_metadata=dict(source="authored", series_id="s", event_id=event, event_history_complete=True,
                    series_changes=[dict(scheduled_ts=TIME, fee_type="quadratic", fee_multiplier="1")], event_changes=[]))
        return ArbLeg(bound, depth, request, kwargs, TIME, "pregame", "authored_complete_depth_fills")

    def pair(self, row=None, *, available="100", minimum="1", increment="1", liquidity=None):
        row = row or {}
        prices = row.get("prices", ["0.4", "0.55"])
        first = self.bound("Dallas YES", price=prices[0], complete=row.get("complete", True),
                           tie=row.get("left_tie_payout"), win=row.get("left_win_payout"))
        second = self.bound("Tampa Bay LONG", price=prices[1], venue="prophetx", complete=row.get("complete", True))
        return (self.leg(first, available=available, minimum=minimum, increment=increment, liquidity=liquidity),
                self.leg(second, right_fee=row.get("right_fee_per_face", "0"), available=available,
                         minimum=minimum, increment=increment, liquidity=liquidity))

    def evaluate(self, pair, quantities):
        from app.comparison.net_arbs import _allocation
        return _allocation(pair, quantities, at=self.at, policy=__import__("app.comparison.costs", fromlist=["DEFAULT_POLICY"]).DEFAULT_POLICY)

    def test_independent_positive_negative_zero_conditional_and_unequal_vectors(self):
        for row in self.fixture["vectors"]:
            with self.subTest(id=row["id"]):
                result = self.evaluate(self.pair(row), tuple(row["quantities"]))
                self.assertTrue(result["available"], result["reasons"])
                self.assertEqual(Fraction(result["minimum_return_usd"]), Fraction(row["buffered_minimum"]))
                self.assertEqual(Fraction(result["denominator_usd"]), Fraction(row["buffered_capital"]))
                if "buffered_minimum_percent" in row:
                    self.assertEqual(Fraction(result["minimum_return_percent"]), Fraction(row["buffered_minimum_percent"]))
                self.assertEqual(result["category"], "all_modeled_outcomes" if row["complete"] else "conditional_known_states")
                self.assertEqual(result["all_modeled_outcome_profitable"], row["complete"] and Fraction(row["buffered_minimum"]) > 0)
                self.assertEqual(result["conditional_profitable"], not row["complete"] and Fraction(row["buffered_minimum"]) > 0)

    def test_tie_loss_and_one_leg_exposure_separate_from_pair(self):
        row = next(r for r in self.fixture["vectors"] if r["id"] == "tie-loss")
        result = self.evaluate(self.pair(row), ("100", "100"))
        self.assertEqual(len(result["limiting_states"]), 2)
        self.assertFalse(result["modeled_profitable"])
        self.assertEqual(result["state_descriptors"], [
            dict(state_id="completed:None:-1", terminal="completed", score_domain="home_margin",
                 score_range=dict(lower=None, upper=-1)),
            dict(state_id="completed:0:0", terminal="completed", score_domain="home_margin",
                 score_range=dict(lower=0, upper=0)),
            dict(state_id="completed:1:None", terminal="completed", score_domain="home_margin",
                 score_range=dict(lower=1, upper=None)),
            dict(state_id="noncompleted", terminal="noncompleted", score_domain="home_margin",
                 score_range=None),
        ])
        profitable = self.evaluate(self.pair(), ("100", "100"))
        self.assertTrue(profitable["all_modeled_outcome_profitable"])
        exposures = profitable["one_leg_exposures"]
        self.assertEqual(min(Fraction(v) for v in exposures[0]["state_profits_usd"].values()), -41)
        self.assertEqual(min(Fraction(v) for v in exposures[1]["state_profits_usd"].values()), -56)
        self.assertFalse(exposures[0]["fully_acquired_pair"])
        summaries = profitable["cost_summaries"]
        self.assertEqual([Fraction(row["acquisition_usd"]) for row in summaries["base"]], [40, 55])
        self.assertEqual([Fraction(row["acquisition_usd"]) for row in summaries["conservative"]], [41, 56])
        self.assertEqual([Fraction(row["net_entry_fee_usd"]) for row in summaries["conservative"]], [0, 0])
        self.assertEqual([Fraction(row["capital"]["deployed_capital_usd"]) for row in summaries["conservative"]], [41, 56])
        self.assertTrue(all(row["settlement_fee_usd"] == "0" for leg in summaries["base"] for row in leg["states"].values()))

    def test_bounds_declared_before_search_and_orientation_deduplicated(self):
        pair = self.pair(available="2", minimum="1", increment="1")
        limits = ArbLimits(max_candidate_pairs=1, max_allocation_evaluations=4, max_results=1, max_points_per_leg=2)
        result = search_arbs(pair + pair[::-1], at=self.at, limits=limits)
        self.assertEqual(result["candidate_pairs"], 1)
        self.assertEqual(result["allocation_evaluations"], 4)
        self.assertEqual(result["returned_results"], 1)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["results"][0]["search_label"], "best evaluated allocation")
        self.assertFalse(result["results"][0]["global_optimum_established"])
        reversed_result = search_arbs(pair[::-1], at=self.at, limits=limits)
        self.assertEqual(result["results"], reversed_result["results"])

    def test_point_and_evaluation_truncation_are_explicit(self):
        result = search_arbs(self.pair(available="100"), at=self.at,
            limits=ArbLimits(max_candidate_pairs=256, max_allocation_evaluations=3, max_results=128, max_points_per_leg=4))
        self.assertTrue(result["truncated"])
        self.assertTrue(result["truncation"]["allocation_evaluations"])
        self.assertEqual(result["allocation_evaluations"], 3)
        self.assertEqual(result["limits"], dict(candidate_pairs=256, allocation_evaluations=3, returned_results=128, points_per_leg=4))

    def test_pair_and_return_bounds_and_exact_sort(self):
        pair = self.pair(available="2")
        extra = replace(pair[1].bound_leg.selection, native=replace(pair[1].bound_leg.selection.native,
            market_id="authored-other-market", instrument_id="authored-other-instrument"),
            payout=replace(pair[1].bound_leg.selection.payout, instrument_id="authored-other-instrument"))
        profile = replace(pair[1].bound_leg.profile, native_key=extra.native.key)
        third = self.leg(bind_profile(extra, profile, at=self.at, rule_revision=profile.rule_revision, context=self.context), available="2")
        limited = search_arbs(pair + (third,), at=self.at,
            limits=ArbLimits(max_candidate_pairs=1, max_allocation_evaluations=8, max_results=1))
        self.assertEqual(limited["candidate_pairs"], 1)
        self.assertEqual(limited["theoretical_candidate_pairs"], 2)
        self.assertTrue(limited["truncation"]["candidate_pairs"])
        returned = search_arbs(pair + (third,), at=self.at,
            limits=ArbLimits(max_candidate_pairs=2, max_allocation_evaluations=8, max_results=1))
        self.assertTrue(returned["truncation"]["returned_results"])
        self.assertEqual(returned["returned_results"], 1)

    def test_shared_liquidity_and_missing_depth_withhold_local_pair(self):
        pair = self.pair(available="100", liquidity="same-economic-liquidity")
        with self.assertRaisesRegex(ValueError, "Shared liquidity"):
            self.evaluate(pair, ("60", "60"))
        pair = self.pair(available="2")
        missing = replace(pair[0], depth_leg=replace(pair[0].depth_leg,
                          depth=DepthInputs(None, None), levels=None))
        result = search_arbs((missing, pair[1]), at=self.at)
        self.assertEqual(result["returned_results"], 0)
        self.assertIn("arb_native_size_depth_grid_unavailable", result["diagnostics"][0]["reasons"][0])

    def test_multilevel_costs_use_actual_consumed_depth_and_legal_stress(self):
        pair = self.pair(available="2")
        depth = replace(pair[0].depth_leg, levels=(DepthLevel("0.4", "1", "a1", EVIDENCE),
                                                  DepthLevel("0.5", "1", "a2", EVIDENCE)))
        first = replace(pair[0], depth_leg=depth)
        result = self.evaluate((first, pair[1]), ("2", "2"))
        self.assertTrue(result["available"], result["reasons"])
        # .41 + .51 + 2*.56 = 2.04; every ordinary paired receipt is $2.
        self.assertEqual(Fraction(result["denominator_usd"]), Fraction("2.04"))
        self.assertEqual(Fraction(result["minimum_return_usd"]), Fraction("-0.04"))

    def test_stale_or_unknown_source_clock_and_private_terms_never_acquire(self):
        pair = self.pair(available="2")
        result = search_arbs((replace(pair[0], original_source_clock=None), pair[1]), at=self.at)
        self.assertEqual(result["returned_results"], 0)
        self.assertEqual(result["diagnostics"][0]["reasons"], ["source_quote_age_unknown"])
        public = json.dumps(search_arbs(pair, at=self.at, limits=ArbLimits(max_allocation_evaluations=4)))
        self.assertNotIn("cost_kwargs", public)
        self.assertNotIn("engine_context", public)
        self.assertNotIn("net_before", public)
        from app.comparison.net_arbs import _cost_summary
        summary = _cost_summary(dict(acquisition_usd="40", entry_fee_usd="0", net_entry_fee_usd="0",
            rounding_refund_usd="0", engine_context={"account": "private-account"},
            capital=dict(deployed_capital_usd="40", account="private-account"),
            states={"unknown": dict(net_profit_usd=None, settlement_fee_usd=None, net_before="private-baseline")}))
        self.assertIsNone(summary["states"]["unknown"]["settlement_fee_usd"])
        self.assertNotIn("private-account", json.dumps(summary))
        self.assertNotIn("private-baseline", json.dumps(summary))
        unbounded = search_arbs((replace(pair[0], fill_partition_basis=None), pair[1]), at=self.at)
        self.assertEqual(unbounded["returned_results"], 0)
        self.assertIn("bounded_fragmentation_required", unbounded["diagnostics"][0]["reasons"][0])

    def test_duplicate_conflicting_fee_assumptions_remove_only_that_instrument(self):
        pair = self.pair(available="2")
        conflict = replace(pair[1], cost_kwargs=dict(pair[1].cost_kwargs,
            extra_funding=(FundingComponent("independent-allowance", "1", "consumed_allowance", "entry"),)))
        result = search_arbs(pair + (conflict,), at=self.at)
        self.assertEqual(result["candidate_pairs"], 0)
        self.assertIn("conflicting_duplicate_arb_instrument", result["diagnostics"][0]["reasons"])

    def test_integer_push_and_void_refund_are_not_positive_all_outcome(self):
        original = self.selections["Dallas -8"]
        original = replace(original, native=replace(original.native, venue="kalshi"),
                           price=replace(original.price, amount=ExactNumber("2"), unit="decimal_odds"))
        first_profile = replace(self.profiles["Dallas -8"], version="authored-integer", rule_revision="authored-integer",
            native_key=original.native.key, above=PayoutCell(ExactNumber("2"), "estimated", "Authored even-money payout"),
            noncompleted=PayoutCell(ExactNumber("1"), "estimated", "Authored void refund"))
        first = bind_profile(original, first_profile, at=self.at, rule_revision=first_profile.rule_revision, context=self.context)
        second_selection = replace(original, participant_id=original.event.away_id, signed_line=ExactNumber("8"),
            predicate=replace(original.predicate, operator="lt"),
            native=replace(original.native, venue="prophetx", market_id="authored-integer-opposite", instrument_id="authored-integer-side"))
        second_profile = replace(first_profile, native_key=second_selection.native.key,
            selection_sha256=selection_digest(second_selection), below=first_profile.above, above=first_profile.below)
        second = bind_profile(second_selection, second_profile, at=self.at, rule_revision=second_profile.rule_revision, context=self.context)
        inputs = cashflow_inputs((first, second), ("10", "10"), at=self.at)
        costs = []
        for index, bound in enumerate((first, second)):
            venue, event, market, _, _ = bound.selection.native.key
            terms = FeeTerms("net_gain", "0", "0.01", "half_even", "order", "taker")
            rule = CostRule("authored-stake-" + venue, venue, "straight", "authored", "controlled_scenario",
                TIME, None, None, UnitSpec("stake_usd"), terms, "declared_zero", True, (EVIDENCE,))
            registry = CostRegistry(dict(schema=1, version="comparison-cost-inputs-1", rules=[rule.to_dict()]))
            request = CostRequest(venue, "straight", "authored", TIME, TIME, event_id=event, market_id=market,
                pinned_version=rule.version, allow_controlled_scenario=True)
            costs.append(calculate_net_costs(request, inputs, native_quantity="10", native_price="-110",
                grid=QuantityGridInputs("0.01", "0.01", "0.01", EVIDENCE),
                fill_inputs=FillInputs("authored_fills", True, 1, 1, ("o",)), fills=[], registry=registry, leg_index=index))
        depth = dict(depth_qualified=True, native_quantities=["10", "10"], reasons=[],
                     qualification="authored evidenced USD risk allocation")
        result = evaluate_arb_allocation(inputs, tuple(costs), tuple(costs), depth, ("10", "10"))
        self.assertTrue(result["available"], result["reasons"])
        self.assertEqual(Fraction(result["minimum_return_usd"]), 0)
        self.assertIn("noncompleted", result["limiting_states"])
        self.assertFalse(result["all_modeled_outcome_profitable"])

    def test_exact_missing_zero_cannot_be_invented_or_mixed_revision(self):
        pair = self.pair()
        result = self.evaluate(pair, ("100", "100"))
        self.assertNotIn("probabilities", result)
        self.assertFalse(result["one_leg_exposures"][0]["fully_acquired_pair"])
        with self.assertRaises(ValueError):
            ArbLimits(max_candidate_pairs=True)


if __name__ == "__main__":
    unittest.main()
