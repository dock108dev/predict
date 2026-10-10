"""Literal/Fraction stress oracles, independent of calculation implementations."""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Inexact, ROUND_DOWN, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import unittest

from app.comparison.adapters import adapt
from app.comparison.buffers import (
    DepthLeg, DepthLevel, adverse_price, age_gate, calculate_buffered_costs,
    depth_allocation, fixed_sensitivity, paired_net_costs, supported_size,
)
from app.comparison.costs import (
    ComparisonCostPolicy, CostRegistry, CostRequest, CostRule, DepthInputs,
    FeeTerms, FillInputs, QuantityGridInputs, UnitSpec,
)
from app.comparison.domain import EvidenceReference
from app.comparison.event_links import EventLinks, instant
from app.comparison.payouts import CompletionContext, PayoutProfile, bind_profile


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "app/fixtures/comparison-buffers-v1.json"
EVIDENCE = EvidenceReference("authored:comparison-buffer-vectors-1", "b" * 64, "authored")


class ComparisonBufferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors = json.loads(FIXTURE.read_text())
        cls.now = "2026-10-08T12:00:00Z"

    def unit(self, name="dollar_face_contracts"):
        return UnitSpec(name, "0.01" if name == "novig_v3_cent_contracts" else "1")

    def grid(self, *, minimum="1", increment="1", tick="0.01"):
        return QuantityGridInputs(minimum, increment, tick, EVIDENCE)

    def leg(self, leg_id="a", *, unit=None, minimum="1", increment="1", available="100", levels=None, price="0.4", liquidity="shared", partial=True):
        return DepthLeg(leg_id, unit or self.unit(), self.grid(minimum=minimum, increment=increment),
                        DepthInputs(available, EVIDENCE),
                        levels or (DepthLevel(price, available, liquidity, EVIDENCE),), partial)

    def test_authored_policy_vectors_and_defaults(self):
        expected = {"tests/fixtures/comparison-policy-vectors.json":
                    "e64c288506f2f7a9c4b3b5a49d33d8cb4bdab86fdd0892db1a4990ebdea5fb9f"}
        for path, sha in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), sha)
        self.assertEqual(asdict(ComparisonCostPolicy()), dict(
            version='comparison-cost-policy-1', ceiling_usd='100', role='taker',
            portfolio_basis='standalone', funding_basis='already_prefunded',
            denominator='actual_deployed_capital', optional_override_surface='Details',
            pregame_age_seconds=900, live_age_seconds=15, gross_pinnacle_baseline_age_seconds=1800,
            adverse_price_per_dollar_face='0.01', extra_arbitrary_reserve_usd='0',
            contingent_funding_credit_usd='0'))

    def test_legal_movement_independent_native_grid_vectors(self):
        for row in self.vectors["movement_vectors"]:
            unit = (UnitSpec(row["unit"], "1", row["quantity_scale"], row["price_scale"])
                    if row["unit"] == "fixed_point_contracts" else self.unit(row["unit"]))
            with self.subTest(row=row["id"]):
                result = adverse_price(unit, self.grid(tick=row["tick"]), row["price"])
                self.assertTrue(result["available"], result)
                self.assertEqual(Fraction(result["adverse_native_price"]), Fraction(row["adverse"]))
        self.assertEqual(Fraction(adverse_price(self.unit(), self.grid(tick="0.004"), "0.4")["movement_per_dollar_face"]), Fraction(3, 250))

    def test_missing_off_grid_impossible_and_stake_price_locally_decline(self):
        for grid, price, reason in ((self.grid(tick=None), "0.4", "legal_price_grid_unknown"),
                                    (self.grid(tick="0.03"), "0.4", "observed_price_off_legal_grid"),
                                    (self.grid(), "0.99", "adverse_legal_price_impossible")):
            value = adverse_price(self.unit(), grid, price)
            self.assertFalse(value["available"])
            self.assertEqual(value["reasons"], [reason])
            self.assertIsNone(value["adverse_native_price"])
        value = adverse_price(UnitSpec("stake_usd"), self.grid(), "0.5")
        self.assertEqual(value["reasons"], ["stake_price_payout_legal_grid_conversion_unavailable"])

    def test_age_boundaries_original_clock_and_fractional_expiry(self):
        vectors = [("pregame", "2026-10-08T11:45:01Z", True),
                   ("pregame", "2026-10-08T11:45:00Z", True),
                   ("pregame", "2026-10-08T11:44:59Z", False),
                   ("pregame", "2026-10-08T11:44:59.999999Z", False),
                   ("live", "2026-10-08T11:59:45Z", True),
                   ("live", "2026-10-08T11:59:44Z", False),
                   ("pregame", None, False), ("pregame", "2026-10-08T12:00:01Z", False)]
        for phase, clock, expected in vectors:
            with self.subTest(phase=phase, clock=clock):
                result = age_gate(clock, phase=phase, at=self.now)
                self.assertEqual(result["eligible"], expected)
                self.assertEqual(result["gross_pinnacle_age_seconds"], 1800)
        self.assertFalse(age_gate("2026-10-08T11:00:00Z", phase="pregame", at=self.now)["eligible"])
        self.assertEqual(age_gate("2026-10-08T11:59:00", phase="pregame", at=self.now)["reasons"], ["source_quote_age_unknown"])
        self.assertEqual(age_gate(None, phase="delayed", at=self.now)["reasons"], ["comparison_phase_unknown"])

    def test_independent_monotonic_cost_vectors_and_negative_edge(self):
        for row in self.vectors["fixed_profit_vectors"]:
            paired = fixed_sensitivity({"win": "5"}, {"win": row["profit"]},
                                       base_capital_usd="50", conservative_capital_usd="50",
                                       base_quantities=("100",), conservative_quantities=("100",))
            self.assertTrue(paired["available"])
            self.assertEqual(Fraction(paired["states"]["win"]["conservative_return_percent"]), Fraction(row["percent"]))
        self.assertLess(Fraction(paired["states"]["win"]["conservative_return_percent"]), 0)

    def test_negative_expanded_denominator_rebases_both_and_ceiling_holds(self):
        row = self.vectors["negative_expanded_capital"]
        args = dict(base_capital_usd=row["base_capital"], conservative_capital_usd=row["stress_capital"],
                    base_quantities=("100",), conservative_quantities=("100",))
        paired = fixed_sensitivity({"loss": row["base_profit"]}, {"loss": row["stress_profit"]},
                                   policy=ComparisonCostPolicy().with_details_ceiling("120"), **args)
        self.assertEqual(Fraction(paired["denominator_usd"]), 120)
        self.assertEqual(Fraction(paired["states"]["loss"]["base_return_percent"]), Fraction(-25, 3))
        self.assertEqual(Fraction(paired["states"]["loss"]["conservative_return_percent"]), Fraction(-55, 6))
        self.assertEqual(Fraction(paired["base_refundable_sensitivity_allowance_usd"]), 20)
        blocked = fixed_sensitivity({"loss": "-10"}, {"loss": "-11"}, **args)
        self.assertFalse(blocked["available"])
        self.assertIn("comparison_capital_ceiling_exceeded", blocked["reasons"])
        self.assertIsNone(blocked["states"]["loss"]["conservative_return_percent"])

    def test_coarse_deployment_excludes_idle_ceiling_and_refundable_hold_count_once(self):
        q = self.vectors["coarse_capital"]
        paired = fixed_sensitivity({"win": q["profit"]}, {"win": q["profit"]},
                                   base_capital_usd=q["deployed"], conservative_capital_usd=q["deployed"],
                                   base_quantities=("80",), conservative_quantities=("80",))
        self.assertEqual(Fraction(paired["denominator_usd"]), 44)
        self.assertEqual(Fraction(paired["states"]["win"]["base_return_percent"]), 10)
        hold = fixed_sensitivity({"win": "5"}, {"win": "3"}, base_capital_usd="60", conservative_capital_usd="60",
                                 base_quantities=("100",), conservative_quantities=("100",))
        self.assertEqual(Fraction(hold["states"]["win"]["base_return_percent"]), Fraction(25, 3))
        self.assertEqual(Fraction(hold["states"]["win"]["conservative_return_percent"]), 5)

    def test_unknown_improved_state_and_resizing_cannot_claim_monotonicity(self):
        for profit, reason in ((None, "fixed_allocation_state_profit_unknown:loss"), ("-9", "conservative_cost_improves_fixed_allocation_state:loss")):
            paired = fixed_sensitivity({"loss": "-10"}, {"loss": profit}, base_capital_usd="100", conservative_capital_usd="100",
                                       base_quantities=("100",), conservative_quantities=("100",))
            self.assertFalse(paired["available"])
            self.assertIn(reason, paired["reasons"])
            self.assertIsNone(paired["states"]["loss"]["conservative_return_percent"])
        with self.assertRaisesRegex(ValueError, "frozen"):
            fixed_sensitivity({"win": "5"}, {"win": "6"}, base_capital_usd="50", conservative_capital_usd="60",
                              base_quantities=("100",), conservative_quantities=("120",))

    def test_existing_depth_engine_consumes_shared_liquidity_once(self):
        legs = (self.leg("a"), self.leg("b", price="0.5"))
        valid = depth_allocation(legs, ("60", "40"))
        self.assertTrue(valid["depth_qualified"], valid)
        self.assertEqual([Fraction(x["quantity"]) for x in valid["consumed_legs"]], [60, 40])
        self.assertIsNone(valid["net_result"])
        self.assertFalse(valid["fee_capital_qualified"])
        invalid = depth_allocation(legs, ("60", "60"))
        self.assertFalse(invalid["depth_qualified"])
        self.assertIn("Shared liquidity exhausted", invalid["reasons"][0])

    def test_native_grids_cent_units_offset_grids_and_partial_rules(self):
        offset = depth_allocation((self.leg(minimum="1.5", increment="1", available="10"),), ("2.5",))
        self.assertTrue(offset["depth_qualified"], offset)
        bad = depth_allocation((self.leg(minimum="1.5", increment="1", available="10"),), ("3",))
        self.assertIn("a:quantity_off_native_grid", bad["reasons"])
        cent = self.leg(unit=self.unit("novig_v3_cent_contracts"), minimum="100", increment="100", available="8000")
        self.assertEqual(Fraction(depth_allocation((cent,), ("8000",))["normalized_quantities"][0]), 80)
        partial = depth_allocation((self.leg(partial=False),), ("80",))
        self.assertFalse(partial["depth_qualified"])
        self.assertIn("partial final level", partial["reasons"][0])

    def test_missing_depth_stays_unknown_and_supported_size_separate(self):
        absent = replace(self.leg(), depth=DepthInputs(None, None), levels=None)
        missing = depth_allocation((absent,), ("100",))
        self.assertFalse(missing["depth_qualified"])
        self.assertIn("a:depth_inputs_unavailable", missing["reasons"])
        self.assertIsNone(supported_size(absent)["native_quantity"])
        leg = self.leg(available="80")
        target = depth_allocation((leg,), ("100",))
        self.assertIn("a:target_size_depth_insufficient", target["reasons"])
        smaller = supported_size(leg)
        self.assertEqual(smaller["native_quantity"], "80")
        self.assertEqual(smaller["size_basis"], "details_supported_size_sensitivity")
        self.assertFalse(smaller["ranking_replacement"])
        self.assertTrue(smaller["depth_qualified"])

    def controlled_net_inputs(self):
        adapter = json.loads((ROOT / "app/fixtures/comparison-outcome-adapters-v1.json").read_text())
        payout = json.loads((ROOT / "app/fixtures/comparison-payouts-v1.json").read_text())
        row = next(x for x in adapter["rows"] if x["id"] == "Dallas YES")
        selection = adapt(row["fact"], links=EventLinks.from_dict(adapter["links"]), at=instant(self.now))
        selection = replace(selection, native=replace(selection.native, venue="prophetx", evidence=(EVIDENCE,), original_wording="Authored conditional YES example"))
        raw = next(x["profile"] for x in payout["profile_rows"] if x["selection_id"] == "Dallas YES")
        profile = replace(PayoutProfile.from_dict(raw), native_key=selection.native.key,
                          source_evidence=(EVIDENCE,), version="authored-buffer-payout-1", rule_revision="authored-buffer-payout-1")
        bound = bind_profile(selection, profile, at=instant(self.now), rule_revision=profile.rule_revision,
                             context=CompletionContext.from_dict(payout["ordinary_context"]))
        rule = CostRule("authored-buffer-fee-1", "prophetx", "single", "authored", "controlled_scenario",
                        "2026-10-08T00:00:00Z", None, None, self.unit(),
                        FeeTerms("quantity", "0.001", "0.01", "half_even", "per_fill", "taker"),
                        "declared_zero", True, (EVIDENCE,))
        registry = CostRegistry(dict(schema=1, version="comparison-cost-inputs-1", rules=[rule.to_dict()]))
        request = CostRequest("prophetx", "single", "authored", self.now, self.now,
                              market_id=selection.native.market_id, event_id=selection.native.event_id,
                              pinned_version=rule.version, allow_controlled_scenario=True)
        depth = replace(self.leg(), native_key=selection.native.key)
        return bound, request, dict(unit=self.unit(), native_quantity="100", native_price="0.4", grid=self.grid(),
                                   fill_inputs=FillInputs("authored_fills", True, 1, 1, ("order",)),
                                   fills=[dict(fill_id="fill", order_id="order", role="taker", price="0.4", quantity="100", unit="contracts")],
                                   original_source_clock=self.now, phase="pregame", registry=registry,
                                   depth_leg=depth, include_exceptions=False)

    def test_reviewed_s01_s02_reprice_contract_keeps_quantity_and_fee_recalculation(self):
        bound, request, kwargs = self.controlled_net_inputs()
        original = deepcopy(kwargs["fills"])
        result = calculate_buffered_costs(bound, request, **kwargs)
        self.assertTrue(result["depth_qualified_ranking_available"], result["reasons"])
        self.assertEqual(Fraction(result["base"]["capital"]["deployed_capital_usd"]), Fraction(401, 10))
        self.assertEqual(Fraction(result["conservative"]["capital"]["deployed_capital_usd"]), Fraction(411, 10))
        self.assertEqual([Fraction(x["net_profit_usd"]) for x in result["base"]["states"].values()],
                         [Fraction(-401, 10), Fraction(99, 10), Fraction(599, 10)])
        self.assertEqual([Fraction(x["net_profit_usd"]) for x in result["conservative"]["states"].values()],
                         [Fraction(-411, 10), Fraction(89, 10), Fraction(589, 10)])
        self.assertEqual(Fraction(result["sensitivity"]["denominator_usd"]), Fraction(411, 10))
        self.assertEqual(kwargs["fills"], original)
        altered = deepcopy(result["conservative"])
        altered["size_basis"]["native_quantity"] = "99"
        with self.assertRaisesRegex(ValueError, "frozen"):
            paired_net_costs(result["base"], altered)

    def test_integrated_age_depth_unknown_fees_and_fragmentation_are_local(self):
        bound, request, kwargs = self.controlled_net_inputs()
        missing = calculate_buffered_costs(bound, request, **dict(kwargs, depth_leg=None))
        self.assertTrue(missing["hypothetical_estimate_available"])
        self.assertFalse(missing["depth_qualified_ranking_available"])
        stale = calculate_buffered_costs(bound, request, **dict(kwargs, original_source_clock="2026-10-08T11:44:59Z"))
        self.assertFalse(stale["hypothetical_estimate_available"])
        self.assertIn("source_quote_too_old_for_future_net", stale["reasons"])
        unknown = calculate_buffered_costs(bound, request, **dict(kwargs, fill_inputs=FillInputs("unknown_split", False, None, None)))
        self.assertFalse(unknown["hypothetical_estimate_available"])
        self.assertIn("bounded_fragmentation_required", unknown["base"]["reasons"])
        raw = kwargs["registry"].data
        raw["rules"][0]["mandatory_charges_known"] = False
        blocked = calculate_buffered_costs(bound, request, **dict(kwargs, registry=CostRegistry(raw)))
        self.assertFalse(blocked["depth_qualified_ranking_available"])
        self.assertTrue(any("mandatory" in x for x in blocked["base"]["reasons"]))

    def test_unknown_exception_retains_conditional_monotonic_sensitivity(self):
        bound, request, kwargs = self.controlled_net_inputs()
        result = calculate_buffered_costs(bound, request, **dict(kwargs, include_exceptions=True))
        self.assertTrue(result["depth_qualified_ranking_available"], result["reasons"])
        pair = result["sensitivity"]
        self.assertEqual(pair["comparison_scope"], "conditional_known_states")
        self.assertFalse(pair["all_modeled_outcome_qualified"])
        self.assertEqual(pair["unknown_state_ids"], ["noncompleted"])
        self.assertIsNone(pair["states"]["noncompleted"]["base_profit_usd"])
        self.assertIsNone(pair["states"]["noncompleted"]["conservative_profit_usd"])
        self.assertIsNone(pair["states"]["noncompleted"]["conservative_return_percent"])
        values = [pair["states"][state] for state in pair["evaluated_state_ids"]]
        self.assertEqual([Fraction(row["conservative_profit_usd"]) for row in values],
                         [Fraction(-411, 10), Fraction(89, 10), Fraction(589, 10)])
        self.assertTrue(all(Fraction(row["conservative_return_percent"]) <= Fraction(row["base_return_percent"]) for row in values))

    def test_decimal_context_cannot_change_exact_sensitivity_or_price(self):
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            paired = fixed_sensitivity({"win": "5"}, {"win": "3"}, base_capital_usd="60", conservative_capital_usd="60",
                                       base_quantities=("100",), conservative_quantities=("100",))
            self.assertEqual(Fraction(paired["states"]["win"]["base_return_percent"]), Fraction(25, 3))
            self.assertEqual(Fraction(adverse_price(self.unit(), self.grid(tick="0.004"), "0.4")["adverse_native_price"]), Fraction(103, 250))


if __name__ == "__main__":
    unittest.main()
