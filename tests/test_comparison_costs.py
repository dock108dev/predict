"""Portable authored D09 results, independent of current venue/account bindings."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
import hashlib
import json
from pathlib import Path
import unittest
from tests.comparison_oracles import artifact_path

from app.comparison.costs import (
    CapitalInputs, ComparisonCostPolicy, CostRegistry, CostRequest, CostRule,
    CreditInputs, DEFAULT_POLICY, DepthInputs, EstimateBounds, FeeTerms, FillInputs,
    FundingComponent, NativeMarketFeeInputs, PositionInputs, QuantityGridInputs,
    UnitSpec, authored_fee, load_cost_registry,
)
from app.comparison.domain import EvidenceReference


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "app/fixtures/comparison-costs-v1.json"


class ComparisonCostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.vectors = cls.fixture["portable_vectors"]
        cls.registry = load_cost_registry()
        cls.evidence = EvidenceReference(**cls.fixture["upstream_inputs"][1])

    def test_upstream_and_legacy_artifacts_remain_bound(self):
        for ref in self.fixture["upstream_inputs"] + self.fixture["history_refs"]:
            with self.subTest(ref=ref["ref"]):
                self.assertEqual(hashlib.sha256(artifact_path(ref["ref"]).read_bytes()).hexdigest(), ref["sha256"])

    def test_portable_resolution_vectors(self):
        for vector in self.vectors["resolution_vectors"]:
            with self.subTest(vector=vector["id"]):
                result = self.registry.resolve(CostRequest(**vector["request"]))
                self.assertEqual(result.rule.version if result.rule else None, vector["version"])
                self.assertEqual(result.entry_rule_inputs_available, vector["entry"])
                self.assertEqual(result.net_rule_inputs_available, vector["net"])
                self.assertEqual(list(result.reasons), vector["reasons"])
                self.assertTrue(result.to_dict()["gross_inputs_preserved"])

    def test_portable_native_units_and_two_sizes(self):
        for vector in self.vectors["unit_vectors"]:
            with self.subTest(vector=vector["id"]):
                spec = UnitSpec(**vector["spec"])
                self.assertEqual(spec.dollar_face(vector["amount"]), vector["face"])
                if "wire_price" in vector:
                    self.assertEqual(spec.probability_price(vector["wire_price"]), vector["price"])
        with self.assertRaisesRegex(ValueError, "payout"):
            UnitSpec("stake_usd").dollar_face("100")
        with self.assertRaisesRegex(ValueError, "conversion"):
            UnitSpec("novig_v3_cent_contracts", "1")
        with self.assertRaisesRegex(ValueError, "wire integer"):
            UnitSpec("novig_v3_cent_contracts", "0.01").dollar_face("1.1")
        for scale in (True, "0", "1.5", "1000000001"):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                UnitSpec("fixed_point_contracts", "1", scale, "100")

    def test_portable_algebra_uses_shared_engine(self):
        for vector in self.vectors["algebra_vectors"]:
            with self.subTest(vector=vector["id"]):
                result = authored_fee(FeeTerms(**vector["terms"]), vector["fills"],
                                      positions=vector.get("positions"), outcomes=vector.get("outcomes"))
                if "entry_fee" in vector:
                    self.assertEqual(Decimal(result["entry_fee"]), Decimal(vector["entry_fee"]))
                if "state_fees" in vector:
                    self.assertEqual(result["state_fees"], vector["state_fees"])
                self.assertEqual(result["qualification"], "hypothetical mathematical policy")

    def test_provider_caps_and_accumulators_are_not_approximated(self):
        terms = next(rule.terms for rule in self.registry.rules if rule.venue == "polymarket_us")
        with self.assertRaisesRegex(ValueError, "existing shared venue engine"):
            terms.generic_policy()
        accumulator = replace(terms, aggregation="order_accumulator")
        with self.assertRaisesRegex(ValueError, "existing shared venue engine"):
            accumulator.generic_policy()

    def test_strict_exact_cost_numbers(self):
        for value in (0.5, True, "NaN", "Infinity", "1e100", "1/3", ".5", "-1",
                      "1" + "0" * 100 + "1", "0.0000000000001"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FundingComponent("cash1", value, "acquisition", "entry")
        for value in ("2026-10-08", "2026-10-08T10:00:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CostRequest("controlled", "single", "controlled", value, value)
        with self.assertRaisesRegex(ValueError, "precedes"):
            CostRequest("controlled", "single", "controlled", "2026-10-08T10:00:00Z", "2026-10-08T09:00:00Z")
        terms = FeeTerms("quantity", "1", "0.01", "half_even", "per_fill", "taker")
        with self.assertRaisesRegex(ValueError, "supported 24 digits"):
            authored_fee(terms, [{"price": "0.5", "quantity": "1" + "0" * 100 + "1"}])

    def test_pin_cannot_promote_date_only_or_public_research(self):
        public = next(rule for rule in self.registry.rules if rule.venue == "novig")
        with self.assertRaisesRegex(ValueError, "primary-source"):
            replace(public, source_kind="public_document", effective_from="2026-10-08T12:00:00Z")
        primary = replace(self.evidence, evidence_class="primary_source")
        with self.assertRaisesRegex(ValueError, "effective instant"):
            replace(public, source_kind="public_document", evidence=(primary,))
        with self.assertRaisesRegex(ValueError, "account-term evidence"):
            replace(public, source_kind="account_terms", account_ref="account:authored",
                    effective_from="2026-10-08T12:00:00Z")

    def test_overlap_is_a_local_ambiguity_and_histories_are_immutable(self):
        data = self.registry.data
        current = next(row for row in data["rules"] if row["version"] == "authored-current")
        data["rules"].append(dict(current, version="authored-conflict"))
        registry = CostRegistry(data)
        request = CostRequest("controlled", "single", "controlled", "2026-10-08T10:00:00Z", "2026-10-08T10:00:00Z")
        result = registry.resolve(request)
        self.assertEqual(result.reasons, ("fee_override_ambiguous",))
        self.assertTrue(result.gross_inputs_preserved)
        data["rules"][0]["terms"]["rate"] = "0.99"
        self.assertNotEqual(registry.data["rules"][0]["terms"]["rate"], "0.99")
        self.assertEqual(len(self.registry.rules), len(self.fixture["rules"]))
        with self.assertRaisesRegex(ValueError, "empty fee interval"):
            CostRule.from_dict(dict(current, effective_to=current["effective_from"]))

    def test_fragmentation_is_explicit_and_bounded(self):
        unbounded = FillInputs("unknown_split", False, None, None)
        self.assertEqual(unbounded.reasons("per_fill"), ("bounded_fragmentation_required",))
        bounded = FillInputs("unknown_split", False, None, 10)
        self.assertEqual(bounded.reasons("per_fill"), ())
        self.assertEqual(bounded.reasons("order_accumulator"), ("complete_order_history_required",))
        self.assertEqual(bounded.reasons("cumulative_order_cap"), ("supported_order_cap_bound_required",))
        full = FillInputs("authored_fills", True, 2, 2, ("order1",))
        self.assertEqual(full.reasons("order_accumulator"), ())
        self.assertEqual(replace(full, complete_order_history=False).reasons("per_fill"), ("complete_order_history_required",))
        for count in (True, 0, -1, 10001):
            with self.subTest(count=count), self.assertRaises(ValueError):
                FillInputs("unknown_split", False, None, count)
        with self.assertRaises(ValueError):
            FillInputs("observed_fills", True, 3, 2, ("order1",))
        for identities in ((None,), ("",), ["order1"], ("order1", "order2")):
            with self.subTest(identities=identities), self.assertRaises(ValueError):
                FillInputs("observed_fills", True, 1, 1, identities)

    def test_estimate_bound_provenance_expiry_and_quantity(self):
        bound = EstimateBounds("0", "0.01", "1", "authored_scenario", self.evidence,
                               "2026-10-08T12:00:00Z", 2)
        self.assertEqual(bound.reasons(calculation_time="2026-10-08T11:59:59Z",
                                      quantity_dollar_face="1", aggregation="per_fill"), ())
        self.assertEqual(bound.reasons(calculation_time="2026-10-08T12:00:00Z",
                                      quantity_dollar_face="2", aggregation="per_fill"),
                         ("cost_bound_quantity_mismatch", "cost_bound_expired"))
        no_fragments = replace(bound, fragment_upper_bound=None)
        self.assertEqual(no_fragments.reasons(calculation_time="2026-10-08T10:00:00Z",
                                             quantity_dollar_face="1", aggregation="per_fill"),
                         ("bounded_fragmentation_required",))
        with self.assertRaises(ValueError):
            replace(bound, upper_usd="-1")

    def test_evidenced_unit_grids_depth_and_movement_inputs(self):
        for vector in self.vectors["grid_vectors"]:
            with self.subTest(vector=vector["id"]):
                evidence = self.evidence if any(vector[k] is not None for k in (
                    "minimum_native", "increment_native", "legal_price_tick")) else None
                grid = QuantityGridInputs(vector["minimum_native"], vector["increment_native"],
                                          vector["legal_price_tick"], evidence)
                self.assertEqual(list(grid.reasons(vector["amount"])), vector["reasons"])
                self.assertEqual(grid.adverse_movement_floor, vector["movement_floor"])
        for vector in self.vectors["depth_vectors"]:
            with self.subTest(vector=vector["id"]):
                depth = DepthInputs(vector["available_native"],
                                    self.evidence if vector["available_native"] is not None else None,
                                    vector["basis"])
                self.assertEqual(list(depth.reasons(vector["amount"])), vector["reasons"])
        with self.assertRaisesRegex(ValueError, "provenance"):
            QuantityGridInputs("1", "1", "0.01", None)
        with self.assertRaisesRegex(ValueError, "fabricated depth"):
            DepthInputs("100", None)

    def test_selected_native_fee_condition_is_not_a_league_guess(self):
        for vector in self.vectors["native_fee_vectors"]:
            with self.subTest(vector=vector["id"]):
                inputs = NativeMarketFeeInputs("m1", "novig_v3", vector["coefficient"],
                                              vector["maker_credit"], vector["charged"],
                                              vector["phase"], self.evidence)
                self.assertEqual(inputs.charge_active, vector["charge_active"])
                if vector["charge_active"] is None:
                    with self.assertRaisesRegex(ValueError, "fee_match_phase_unknown"):
                        inputs.engine_metadata("m1")
                else:
                    self.assertEqual(inputs.engine_metadata("m1")["coefficient"], vector["coefficient"])
                with self.assertRaisesRegex(ValueError, "scope"):
                    inputs.engine_metadata("other-market")
        with self.assertRaisesRegex(ValueError, "RFQ remains separate"):
            NativeMarketFeeInputs("m1", "rfq", "0.03", "0", "ALWAYS", None, self.evidence)

    def test_scoped_positions_and_shared_public_privacy(self):
        baseline = {"win": "-80", "loss": "20"}
        positions = PositionInputs("account:authored", "m1", True, baseline, self.evidence)
        baseline["win"] = "0"
        self.assertEqual(positions.net_before_usd["win"], "-80")
        request = CostRequest("controlled", "market_commission", "controlled",
                              "2026-10-08T10:00:00Z", "2026-10-08T10:00:00Z",
                              market_id="m1", account_ref="account:authored",
                              portfolio_basis="incremental_existing_positions",
                              pinned_version="authored-commission", allow_controlled_scenario=True)
        result = self.registry.resolve(request, positions=positions, outcome_names=("win", "loss"))
        self.assertTrue(result.net_rule_inputs_available)
        public = json.dumps(result.to_dict())
        # Rule is account-neutral; the private portfolio enters as a digest only.
        self.assertNotIn("-80", public)
        self.assertNotIn("account:authored", public)
        self.assertNotIn("net_before", public)
        with self.assertRaisesRegex(ValueError, "scope"):
            positions.generic_context(replace(request, account_ref="account:other"), ("win", "loss"))
        with self.assertRaisesRegex(ValueError, "state basis"):
            positions.generic_context(request, ("win",))
        for raw in ("person@example.com", "123456", "account:a/b", None):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                PositionInputs(raw, "m1", True, baseline, self.evidence)

    def test_count_once_capital_and_deployed_denominator(self):
        for vector in self.vectors["funding_vectors"]:
            with self.subTest(vector=vector["id"]):
                inputs = CapitalInputs(tuple(FundingComponent(**c) for c in vector["components"]), vector["ceiling_usd"])
                self.assertEqual(Decimal(inputs.deployed_usd), Decimal(vector["deployed_usd"]))
                basis = inputs.basis()
                self.assertEqual(Decimal(basis["residual_ceiling_usd"]), Decimal(vector["residual_usd"]))
                self.assertEqual(list(inputs.reasons), vector["reasons"])
                self.assertEqual(basis["denominator"], "actual_deployed_capital")
        cash = FundingComponent("buy1", "44", "acquisition", "entry")
        with self.assertRaisesRegex(ValueError, "more than once"):
            CapitalInputs((cash, cash))
        with self.assertRaises(ValueError):
            CapitalInputs([cash])
        with self.assertRaisesRegex(ValueError, "refunds exceed"):
            CapitalInputs((cash, FundingComponent("refund1", "40", "deterministic_rounding_refund", "entry")))
        with self.assertRaises(ValueError):
            FundingComponent("credit1", "10", "later_credit", "entry")
        with self.assertRaises(ValueError):
            FundingComponent("hold1", "10", "refundable_hold", "entry", True)

    def test_contingent_rebates_never_fund_entry(self):
        for kind in ("maker_rebate", "volume_rebate", "maker_credit_program", "position_fee_adjustment"):
            with self.subTest(kind=kind):
                credit = CreditInputs(kind, None, "later", True, "unknown", self.evidence)
                self.assertEqual(credit.immediate_funding_credit_usd, "0")
                self.assertEqual(replace(credit, amount_usd="100", eligibility="hypothetical").immediate_funding_credit_usd, "0")

    def test_reviewed_policy_and_details_override_revision(self):
        self.assertEqual(DEFAULT_POLICY.ceiling_usd, "100")
        self.assertEqual(DEFAULT_POLICY.gross_pinnacle_baseline_age_seconds, 1800)
        override = DEFAULT_POLICY.with_details_ceiling("50")
        self.assertNotEqual(override.revision, DEFAULT_POLICY.revision)
        self.assertEqual(override.denominator, "actual_deployed_capital")
        self.assertEqual(override.optional_override_surface, "Details")
        for vector in self.vectors["age_vectors"]:
            with self.subTest(vector=vector):
                self.assertEqual(not DEFAULT_POLICY.future_age_reasons(vector["phase"], vector["source_age_seconds"]), vector["admit"])
        self.assertTrue(DEFAULT_POLICY.future_age_reasons("pregame", True))
        for change in ({"ceiling_usd": "0"}, {"gross_pinnacle_baseline_age_seconds": 900}, {"contingent_funding_credit_usd": "1"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ComparisonCostPolicy(**change)

    def test_retained_cashflows_preserve_fixed_sensitivity_basis(self):
        costs = [v for v in self.vectors["cashflow_vectors"] if "extra_consumed_cost_usd" in v]
        self.assertEqual([Decimal(v["profit_usd"]) for v in costs], sorted(
            [Decimal(v["profit_usd"]) for v in costs], reverse=True))
        for vector in self.vectors["cashflow_vectors"]:
            with self.subTest(vector=vector["id"]):
                if "fixed_comparison_deployment_usd" in vector:
                    profit = Decimal(vector["gross_return_usd"]) - Decimal(vector["entry_usd"]) - Decimal(vector["extra_consumed_cost_usd"])
                    self.assertEqual(profit, Decimal(vector["profit_usd"]))
                    self.assertEqual(profit / Decimal(vector["fixed_comparison_deployment_usd"]), Decimal(vector["roi_fixed_sensitivity_basis"]))
                else:
                    capital = Decimal(vector["entry_acquisition_usd"]) + Decimal(vector["prefunded_refundable_hold_usd"])
                    profit = Decimal(vector["outcome_returned_payout_plus_hold_usd"]) - capital
                    self.assertEqual(capital, Decimal(vector["capital_usd"]))
                    self.assertEqual(profit, Decimal(vector["profit_usd"]))
        grid = self.vectors["quantity_grid_vector"]
        self.assertEqual(Decimal(grid["profit_usd"]) / Decimal(grid["actual_deployed_usd"]), Decimal(grid["roi"]))
        counter = self.vectors["negative_denominator_counterexample"]
        self.assertFalse(counter["accept_as_improvement"])
        self.assertLess(Decimal(counter["stress_profit_usd"]), Decimal(counter["base_profit_usd"]))
        self.assertGreater(Decimal(counter["stress_roi"]), Decimal(counter["base_roi"]))

    def test_arithmetic_is_independent_of_ambient_decimal_context(self):
        spec = UnitSpec("fixed_point_contracts", "1", "100", "10000")
        inputs = CapitalInputs((FundingComponent("buy1", "44.123", "acquisition", "entry"),))
        expected = (spec.dollar_face("150"), spec.probability_price("5000"), inputs.basis())
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            self.assertEqual((spec.dollar_face("150"), spec.probability_price("5000"), inputs.basis()), expected)


if __name__ == "__main__":
    unittest.main()
