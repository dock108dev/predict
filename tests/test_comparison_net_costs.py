"""Independent exact-input S02 oracles; no provider/account/owner state."""
from copy import deepcopy
from dataclasses import replace
from decimal import Inexact, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import unittest

from app.comparison.costs import (
    VERSION as COST_VERSION, CostRegistry, CostRequest, CostRule, CreditInputs,
    FeeTerms, FillInputs, FundingComponent, PositionInputs, QuantityGridInputs,
    UnitSpec, load_cost_registry,
)
from app.comparison.domain import EvidenceReference
from app.comparison.net_costs import calculate_net_costs, entry_fee_bounds
from app.fees.engine import Registry


ROOT = Path(__file__).resolve().parents[1]
TIME = "2026-10-08T10:00:00Z"
EVIDENCE = EvidenceReference("app/fixtures/comparison-net-costs-v1.json", "0" * 64, "authored")


def decimal_string(value):
    """Only construct finite test inputs; expected numbers come from vectors."""
    value = Fraction(value)
    for places in range(60):
        scaled = value * 10 ** places
        if scaled.denominator == 1:
            integer = scaled.numerator
            if not places:
                return str(integer)
            sign = "-" if integer < 0 else ""
            digits = str(abs(integer)).zfill(places + 1)
            return sign + digits[:-places] + "." + digits[-places:]
    return str(value)


def setup_case(venue, quantity="1", price="0.5", *, precision="0.0001", rate=None,
               gross_win=None, fragments=1, different_orders=False):
    """Clearly named authored rules; no modification of accepted DATA registry."""
    product = {"novig": "v3_market", "prophetx": "straight"}.get(venue, "event_contract")
    spec = UnitSpec("novig_v3_cent_contracts", "0.01") if venue == "novig" else (
        UnitSpec("stake_usd") if venue == "prophetx" else UnitSpec("dollar_face_contracts", "1"))
    rate = rate or {"kalshi": "0.07", "polymarket_us": "0.0695", "novig": "0.03",
                    "prophetx": "0.02", "controlled": "0"}[venue]
    terms = {
        "kalshi": FeeTerms("quadratic", rate, "0.000001", "ceiling", "order_accumulator", "taker"),
        "polymarket_us": FeeTerms("quadratic", rate, "0.01", "half_even", "cumulative_order_cap", "taker"),
        "novig": FeeTerms("quadratic", rate, "0.00001", "half_up", "per_fill", "taker"),
        "prophetx": FeeTerms("net_gain", rate, "0.01", "half_even", "order", "taker", True),
        "controlled": FeeTerms("quantity", rate, "0.01", "half_even", "order", "taker"),
    }[venue]
    rule = CostRule("authored-s02-" + venue, venue, product, "controlled", "controlled_scenario",
                    TIME, None, None, spec, terms, "declared_zero", True, (EVIDENCE,))
    registry = CostRegistry(dict(schema=1, version=COST_VERSION, rules=[rule.to_dict()]))
    request = CostRequest(venue, product, "controlled", TIME, TIME, market_id="m", event_id="e",
                          series_id="s", pinned_version=rule.version, allow_controlled_scenario=True)
    q = Fraction(quantity)
    face = q / 100 if venue == "novig" else q
    cash = q if venue == "prophetx" else face * Fraction(price)
    receipts = dict(win=gross_win or decimal_string(face * (2 if venue == "prophetx" else 1)),
                    loss="0", refund=decimal_string(cash))
    scenario = dict(version="comparison-cashflows-1", state_ids=["win", "loss", "refund"],
                    partition_complete=True, conditioning="authored exhaustive scenario",
                    table_revision="authored-table-v1", legs=[dict(native_key=[venue, "e", "m", "i", "side"],
                        bound_revision="authored-leg-v1", quantity=decimal_string(face),
                        quantity_unit="usd_risk" if venue == "prophetx" else "contracts",
                        acquisition_cash=decimal_string(cash), receipts=receipts)])
    fills = [dict(fill_id="f" + str(i), order_id="o" + str(i) if different_orders else "o",
                  price=price, quantity=decimal_string(q / fragments), role="taker",
                  unit="novig_v3_contracts" if venue == "novig" else "contracts") for i in range(fragments)]
    fill_inputs = FillInputs("authored_fills", True, fragments, fragments,
                            tuple(f["order_id"] for f in fills) if different_orders else ("o",))
    engine_registry = Registry(dict(schema=1, schedules=[dict(venue=venue, product=product,
        version="authored-shared-s02-" + venue, coefficient=rate, maker_coefficient="0.0125",
        effective_from=TIME, effective_to=None, api_regime="v3" if venue == "novig" else None)]))
    context = dict(venue=venue, product=product, environment="authored", market_id="m", event_id="e", series_id="s",
                   channel="controlled", trade_time=TIME, calculation_time=TIME,
                   schedule_version="authored-shared-s02-" + venue, balance_precision=precision,
                   kalshi_metadata=dict(source="authored", series_id="s", event_id="e", event_history_complete=True,
                       series_changes=[dict(scheduled_ts=TIME, fee_type="quadratic", fee_multiplier="1")], event_changes=[]),
                   api_regime="v3", market_fee=dict(coefficient=rate, makerCredit="0", charged="ALWAYS"))
    return request, scenario, dict(native_quantity=quantity, native_price=price,
        grid=QuantityGridInputs("0.01" if venue == "prophetx" else "1",
                                "0.01" if venue == "prophetx" else "1", "0.01", EVIDENCE),
        fill_inputs=fill_inputs, fills=fills, registry=registry,
        engine_context=context, engine_registry=engine_registry)


class NetCostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / "app/fixtures/comparison-net-costs-v1.json").read_text())

    def test_accepted_oracles_are_unchanged(self):
        for ref in self.fixture["upstream_inputs"]:
            self.assertEqual(hashlib.sha256((ROOT / ref["path"]).read_bytes()).hexdigest(), ref["sha256"])

    def test_two_sizes_tiny_prices_and_rounding_boundaries(self):
        for vector in self.fixture["vectors"]:
            with self.subTest(id=vector["id"]):
                request, scenario, kwargs = setup_case(vector["venue"], vector["quantity"], vector.get("price", "0.5"),
                    precision=vector.get("precision", "0.0001"), gross_win=vector.get("gross_win"))
                result = calculate_net_costs(request, scenario, **kwargs)
                self.assertTrue(result["available"], result["reasons"])
                self.assertTrue(result["complete_state_available"])
                self.assertEqual(Fraction(result["capital"]["deployed_capital_usd"]), Fraction(vector["deployed"]))
                if "entry_fee" in vector:
                    self.assertEqual(Fraction(result["net_entry_fee_usd"]), Fraction(vector["entry_fee"]))
                if "settlement" in vector:
                    self.assertEqual(Fraction(result["states"]["win"]["settlement_fee_usd"]), Fraction(vector["settlement"]))
                self.assertEqual(Fraction(result["states"]["win"]["net_profit_usd"]), Fraction(vector["win"]))
                self.assertEqual(Fraction(result["states"]["loss"]["net_profit_usd"]), Fraction(vector["loss"]))
                self.assertNotIn("engine_context", json.dumps(result))

    def test_us_order_cap_and_novig_fragmentation(self):
        for vector in self.fixture["fragment_vectors"]:
            request, scenario, kwargs = setup_case(vector["venue"], vector["quantity"], vector["price"], fragments=2)
            split = calculate_net_costs(request, scenario, **kwargs)
            combined = calculate_net_costs(*setup_case(vector["venue"], vector["quantity"], vector["price"])[:2],
                **setup_case(vector["venue"], vector["quantity"], vector["price"])[2])
            self.assertTrue(split["available"], split["reasons"])
            if vector["venue"] == "polymarket_us":
                request, scenario, kwargs = setup_case(vector["venue"], vector["quantity"], vector["price"],
                                                     fragments=2, different_orders=True)
                other = calculate_net_costs(request, scenario, **kwargs)
                self.assertEqual(Fraction(split["entry_fee_usd"]), Fraction(vector["same_order_fee"]))
                self.assertEqual(Fraction(other["entry_fee_usd"]), Fraction(vector["different_orders_fee"]))
            else:
                self.assertEqual(Fraction(split["entry_fee_usd"]), Fraction(vector["split_fee"]))
                self.assertEqual(Fraction(combined["entry_fee_usd"]), Fraction(vector["combined_fee"]))

    def test_kalshi_accumulator_refund_once_and_two_grid_envelope(self):
        request, scenario, kwargs = setup_case("kalshi", "2", fragments=2, precision="0.01")
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertEqual(Fraction(result["entry_fee_usd"]), Fraction("0.04"))
        # Two .0025 rounding remainders do not yet reach one cent.
        self.assertEqual(Fraction(result["rounding_refund_usd"]), 0)
        request, scenario, kwargs = setup_case("kalshi", "4", fragments=4, precision="0.01")
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertEqual(Fraction(result["entry_fee_usd"]), Fraction("0.08"))
        self.assertEqual(Fraction(result["rounding_refund_usd"]), Fraction("0.01"))
        self.assertEqual(Fraction(result["capital"]["deployed_capital_usd"]), Fraction("2.07"))
        request, scenario, kwargs = setup_case("kalshi")
        bound = entry_fee_bounds(request, registry=kwargs["registry"], fills=kwargs["fills"],
            fill_inputs=kwargs["fill_inputs"], engine_context=kwargs["engine_context"],
            engine_registry=kwargs["engine_registry"], quantity_dollar_face="1")
        self.assertTrue(bound["available"], bound["reasons"])
        self.assertEqual(Fraction(bound["lower_usd"]), Fraction("0.0175"))
        self.assertEqual(Fraction(bound["upper_usd"]), Fraction("0.02"))

    def test_us_unknown_split_bound_is_not_exact_net(self):
        request, scenario, kwargs = setup_case("polymarket_us", "2")
        kwargs["fill_inputs"] = FillInputs("unknown_split", False, None, None)
        exact = calculate_net_costs(request, scenario, **kwargs)
        self.assertFalse(exact["available"])
        self.assertIn("exact_fill_allocation_required", exact["reasons"])
        bound = entry_fee_bounds(request, registry=kwargs["registry"], fills=kwargs["fills"],
                                 fill_inputs=kwargs["fill_inputs"], quantity_dollar_face="2")
        self.assertTrue(bound["available"])
        self.assertEqual(Fraction(bound["lower_usd"]), 0)
        self.assertEqual(Fraction(bound["upper_usd"]), Fraction("0.03"))
        self.assertIsNone(bound["exact_fee_usd"])
        mismatch = entry_fee_bounds(request, registry=kwargs["registry"], fills=kwargs["fills"],
                                 fill_inputs=kwargs["fill_inputs"], quantity_dollar_face="3")
        self.assertFalse(mismatch["available"])
        self.assertIn("cost_bound_quantity_mismatch", mismatch["reasons"])

    def test_public_research_is_local_refusal_even_when_pinned(self):
        registry = load_cost_registry()
        for rule in registry.rules:
            if rule.source_kind != "research_proposal":
                continue
            request, scenario, kwargs = setup_case(rule.venue)
            request = replace(request, product=rule.product, channel=rule.channel,
                              pinned_version=rule.version, allow_controlled_scenario=False)
            kwargs["registry"] = registry
            result = calculate_net_costs(request, scenario, **kwargs)
            self.assertFalse(result["available"])
            self.assertIn("public_proposal_not_runtime_binding", result["reasons"])
            self.assertIsNone(result["entry_fee_usd"])
            self.assertEqual(result["states"]["win"]["gross_return_usd"], scenario["legs"][0]["receipts"]["win"])

    def test_grids_units_minima_and_fee_binding_are_independent(self):
        request, scenario, kwargs = setup_case("novig", "1")
        kwargs["grid"] = QuantityGridInputs("100", "100", "0.01", EVIDENCE)
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertIn("quantity_below_native_minimum", result["reasons"])
        kwargs["grid"] = QuantityGridInputs("1", "1", None, EVIDENCE)
        self.assertIn("legal_price_grid_unknown", calculate_net_costs(request, scenario, **kwargs)["reasons"])
        request, scenario, kwargs = setup_case("polymarket_us")
        kwargs["engine_context"]["market_id"] = "sibling"
        self.assertIn("shared_engine_context_scope_conflict", calculate_net_costs(request, scenario, **kwargs)["reasons"])
        request, scenario, kwargs = setup_case("polymarket_us")
        row = kwargs["registry"].rules[0]
        kwargs["registry"] = CostRegistry(dict(schema=1, version=COST_VERSION,
            rules=[replace(row, terms=replace(row.terms, rate="0.06")).to_dict()]))
        self.assertIn("shared_engine_coefficient_conflict", calculate_net_costs(request, scenario, **kwargs)["reasons"])

    def test_fixed_point_grid_uses_original_wire_tick(self):
        request, scenario, kwargs = setup_case("polymarket_us")
        row = kwargs["registry"].rules[0]
        kwargs["registry"] = CostRegistry(dict(schema=1, version=COST_VERSION, rules=[replace(row,
            unit=UnitSpec("fixed_point_contracts", "1", "100", "100")).to_dict()]))
        kwargs.update(native_quantity="100", native_price="50",
                      grid=QuantityGridInputs("100", "100", "1", EVIDENCE))
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertTrue(result["available"], result["reasons"])

    def test_fee_reverses_marginal_profit_and_capital_ceiling(self):
        request, scenario, kwargs = setup_case("controlled", "100", "0.5", rate="0.06", gross_win="55")
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertEqual(Fraction(result["states"]["win"]["gross_return_usd"]) - 50, 5)
        self.assertEqual(Fraction(result["states"]["win"]["net_profit_usd"]), -1)
        self.assertEqual(Fraction(result["capital"]["deployed_capital_usd"]), 56)
        kwargs["ceiling_usd"] = "55"
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertFalse(result["available"])
        self.assertIn("comparison_capital_ceiling_exceeded", result["reasons"])

    def test_refundable_hold_and_consumed_hold_use_funded_capital(self):
        for vector in self.fixture["capital_vectors"]:
            request, scenario, kwargs = setup_case("controlled", "100", "0.5", gross_win=vector["returned_payout"])
            kwargs["extra_funding"] = (FundingComponent("independent-hold", vector["hold"], "refundable_hold", "entry"),)
            kwargs["hold_returns_usd"] = {s: vector["hold_return"] for s in scenario["state_ids"]}
            result = calculate_net_costs(request, scenario, **kwargs)
            self.assertEqual(Fraction(result["capital"]["deployed_capital_usd"]), Fraction(vector["deployed"]))
            self.assertEqual(Fraction(result["states"]["win"]["net_profit_usd"]), Fraction(vector["net_profit"]))
            kwargs["hold_returns_usd"] = {}
            unknown = calculate_net_costs(request, scenario, **kwargs)
            self.assertFalse(unknown["available"])
            self.assertIn("refundable_hold_return_unknown", unknown["states"]["win"]["reasons"])

    def test_later_credits_and_duplicate_acquisition_cannot_fund_entry(self):
        request, scenario, kwargs = setup_case("controlled", "88", "0.5")
        kwargs["credits"] = (CreditInputs("volume_rebate", "100", "weekly", False, "hypothetical", EVIDENCE),)
        kwargs["extra_funding"] = (FundingComponent("later-credit", "100", "later_credit", "later"),)
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertEqual(Fraction(result["capital"]["deployed_capital_usd"]), 44)
        self.assertEqual(Fraction(result["capital"]["residual_ceiling_usd"]), 56)
        kwargs["extra_funding"] = (FundingComponent("second-name-for-buy", "44", "acquisition", "entry"),)
        self.assertIn("acquisition_and_entry_fee_are_already_counted", calculate_net_costs(request, scenario, **kwargs)["reasons"])

    def test_standalone_and_incremental_commission_with_private_positions(self):
        request, scenario, kwargs = setup_case("prophetx", "100", gross_win="200")
        standalone = calculate_net_costs(request, scenario, **kwargs)
        self.assertEqual(Fraction(standalone["states"]["win"]["settlement_fee_usd"]), 2)
        request = replace(request, portfolio_basis="incremental_existing_positions", account_ref="account:authored_private")
        missing = calculate_net_costs(request, scenario, **kwargs)
        self.assertIn("scoped_existing_positions_required", missing["reasons"])
        kwargs["positions"] = PositionInputs("account:authored_private", "m", True,
            dict(win="-80", loss="80", refund="0"), EVIDENCE)
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertTrue(result["available"], result["reasons"])
        self.assertEqual(Fraction(result["states"]["win"]["settlement_fee_usd"]), Fraction("0.40"))
        self.assertEqual(Fraction(result["states"]["win"]["net_profit_usd"]), Fraction("99.60"))
        self.assertEqual(Fraction(result["states"]["loss"]["settlement_fee_usd"]), Fraction("-1.60"))
        self.assertEqual(Fraction(result["capital"]["deployed_capital_usd"]), 100)
        public = json.dumps(result)
        self.assertNotIn("authored_private", public)
        self.assertNotIn("net_before", public)
        self.assertNotIn('"-80"', public)

    def test_unknown_settlement_or_payout_preserves_local_prices(self):
        request, scenario, kwargs = setup_case("polymarket_us")
        row = kwargs["registry"].rules[0]
        kwargs["registry"] = CostRegistry(dict(schema=1, version=COST_VERSION,
                                               rules=[replace(row, settlement_status="unknown").to_dict()]))
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertTrue(result["entry_available"])
        self.assertFalse(result["available"])
        self.assertIn("settlement_charge_inputs_required", result["reasons"])
        request, scenario, kwargs = setup_case("polymarket_us")
        scenario["legs"][0]["receipts"]["refund"] = None
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertTrue(result["available"])
        self.assertFalse(result["complete_state_available"])
        self.assertIsNone(result["states"]["refund"]["net_profit_usd"])

    def test_actual_s01_receipts_preserve_tie_and_unknown_exception(self):
        from app.comparison.adapters import adapt
        from app.comparison.cashflows import cashflow_inputs
        from app.comparison.event_links import EventLinks, instant
        from app.comparison.payouts import CompletionContext, PayoutProfile, bind_profile
        payout = json.loads((ROOT / "app/fixtures/comparison-payouts-v1.json").read_text())
        adapters = json.loads((ROOT / "app/fixtures/comparison-outcome-adapters-v1.json").read_text())
        at = instant(payout["evaluation_at"])
        fact = next(row["fact"] for row in adapters["rows"] if row["id"] == "Dallas YES")
        selected = adapt(fact, links=EventLinks.from_dict(adapters["links"]), at=at)
        profile = PayoutProfile.from_dict(next(row["profile"] for row in payout["profile_rows"]
                                              if row["selection_id"] == "Dallas YES"))
        leg = bind_profile(selected, profile, at=at, rule_revision=profile.rule_revision,
                           context=CompletionContext.from_dict(payout["ordinary_context"]))
        scenario = cashflow_inputs((leg,), ("1",), at=at)
        request, _, kwargs = setup_case("kalshi", "1", "0.4")
        key = leg.selection.native.key
        request = replace(request, event_id=key[1], market_id=key[2])
        kwargs["engine_context"].update(event_id=key[1], market_id=key[2])
        kwargs["engine_context"]["kalshi_metadata"]["event_id"] = key[1]
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertTrue(result["available"], result["reasons"])
        self.assertFalse(result["complete_state_available"])
        self.assertEqual([Fraction(s["net_profit_usd"]) if s["net_profit_usd"] is not None else None
                          for s in result["states"].values()],
                         [Fraction("-0.4168"), Fraction("0.0832"), Fraction("0.5832"), None])

    def test_changed_dependency_revision_and_ambient_context_independence(self):
        request, scenario, kwargs = setup_case("kalshi")
        baseline = calculate_net_costs(request, scenario, **kwargs)
        with localcontext() as context:
            context.prec = 3
            context.traps[Inexact] = True
            self.assertEqual(calculate_net_costs(request, scenario, **kwargs), baseline)
        changed = deepcopy(scenario)
        changed["table_revision"] = "new-payout"
        self.assertNotEqual(calculate_net_costs(request, changed, **kwargs)["revision"], baseline["revision"])

    def test_us_half_even_midpoints_and_maker_credit_excluded(self):
        for quantity, fee in (("1", "0"), ("3", "0.02")):
            request, scenario, kwargs = setup_case("polymarket_us", quantity, rate="0.02")
            result = calculate_net_costs(request, scenario, **kwargs)
            self.assertEqual(Fraction(result["entry_fee_usd"]), Fraction(fee))
        request, scenario, kwargs = setup_case("polymarket_us", "100")
        request = replace(request, role="maker")
        row = kwargs["registry"].rules[0]
        terms = replace(row.terms, role="maker", rate="0.0125", aggregation="per_fill")
        kwargs["registry"] = CostRegistry(dict(schema=1, version=COST_VERSION, rules=[replace(row, terms=terms).to_dict()]))
        kwargs["fills"][0]["role"] = "maker"
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertTrue(result["available"], result["reasons"])
        self.assertEqual(Fraction(result["capital"]["deployed_capital_usd"]), 50)
        self.assertEqual(Fraction(result["entry_fee_usd"]), 0)
        self.assertIn("maker_rebate", result["credits_excluded_from_funding"])

    def test_settlement_withheld_attachment_prevents_second_charge(self):
        request, scenario, kwargs = setup_case("controlled", "10")
        row = kwargs["registry"].rules[0]
        settlement = FeeTerms("net_gain", "0.02", "0.01", "half_even", "order", "taker")
        rule = replace(row, settlement_status="known_terms", settlement_terms=settlement)
        kwargs["registry"] = CostRegistry(dict(schema=1, version=COST_VERSION, rules=[rule.to_dict()]))
        separately = calculate_net_costs(request, scenario, **kwargs)
        self.assertEqual(Fraction(separately["states"]["win"]["settlement_fee_usd"]), Fraction("0.1"))
        self.assertEqual(Fraction(separately["states"]["win"]["net_profit_usd"]), Fraction("4.9"))
        kwargs["registry"] = CostRegistry(dict(schema=1, version=COST_VERSION,
            rules=[replace(rule, settlement_treatment="already_withheld_from_payout").to_dict()]))
        blocked = calculate_net_costs(request, scenario, **kwargs)
        self.assertIn("withheld_settlement_charge_attachment_required", blocked["reasons"])
        scenario["legs"][0].update(settlement_charge_already_withheld=True)
        scenario["legs"][0]["receipts"]["win"] = "9.9"
        withheld = calculate_net_costs(request, scenario, **kwargs)
        self.assertEqual(Fraction(withheld["states"]["win"]["settlement_fee_usd"]), 0)
        self.assertEqual(Fraction(withheld["states"]["win"]["net_profit_usd"]), Fraction("4.9"))

    def test_only_consumed_hold_cash_reduces_commission_base(self):
        request, scenario, kwargs = setup_case("prophetx", "50", gross_win="55")
        kwargs["extra_funding"] = (FundingComponent("hold", "10", "refundable_hold", "entry"),)
        kwargs["hold_returns_usd"] = {s: "8" for s in scenario["state_ids"]}
        result = calculate_net_costs(request, scenario, **kwargs)
        self.assertEqual(Fraction(result["capital"]["deployed_capital_usd"]), 60)
        self.assertEqual(Fraction(result["states"]["win"]["settlement_fee_usd"]), Fraction("0.06"))
        self.assertEqual(Fraction(result["states"]["win"]["net_profit_usd"]), Fraction("2.94"))


if __name__ == "__main__":
    unittest.main()
