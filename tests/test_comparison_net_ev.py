"""R07 literal/Fraction oracles and reviewed typed scenario/cost integration."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import unittest

from app.comparison.adapters import adapt
from app.comparison.cashflows import cashflow_inputs
from app.comparison.domain import EvidenceReference, ExactNumber, NativeProvenance, Price, ScorePredicate, UnknownValue
from app.comparison.event_links import EventLinks, instant
from app.comparison.net_costs import calculate_net_costs, revision
from app.comparison.net_ev import ProbabilityInputs, estimated_net_ev
from app.comparison.payouts import CompletionContext, PayoutCell, PayoutProfile, bind_profile
from app.comparison.pinnacle import ReferenceOutcome, ReferenceSet

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "app/fixtures"
EVIDENCE = EvidenceReference("app/fixtures/comparison-net-ev-v1.json", "0" * 64, "authored")


def stamp_cost(result):
    result["revision"] = revision({key: value for key, value in result.items() if key != "revision"})
    return result


class NetEVTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = json.loads((FIXTURES / "comparison-payouts-v1.json").read_text())
        adapters = json.loads((FIXTURES / "comparison-outcome-adapters-v1.json").read_text())
        cls.at = instant(fixture["evaluation_at"])
        cls.clock = cls.at.isoformat()
        cls.context = CompletionContext.from_dict(fixture["ordinary_context"])
        cls.delayed = CompletionContext.from_dict(fixture["72_hour_context"])
        links = EventLinks.from_dict(adapters["links"])
        cls.selections = {row["id"]: adapt(row["fact"], links=links, at=cls.at) for row in adapters["rows"]}
        cls.profiles = {row["selection_id"]: PayoutProfile.from_dict(row["profile"]) for row in fixture["profile_rows"]}
        cls.vectors = json.loads((FIXTURES / "comparison-net-ev-v1.json").read_text())

    def scenario(self, cost="1/2", *, name="Dallas YES", refund=False, context=None):
        selected = self.selections[name]
        if selected.price.payout_unit == "usd_per_contract":
            selected = replace(selected, price=replace(selected.price, amount=ExactNumber(cost)))
        profile = self.profiles[name]
        if refund:
            profile = replace(profile, version="authored-terminal-refund-v2", rule_revision="authored-terminal-refund-v2",
                              noncompleted=PayoutCell(ExactNumber(cost), "estimated", "Authored terminal acquisition repayment"))
        bound = bind_profile(selected, profile, at=self.at, rule_revision=profile.rule_revision, context=context or self.context)
        return cashflow_inputs((bound,), ("1",), at=self.at)

    def reference(self, inputs, *, three=False):
        from app.comparison.domain import CanonicalSelection
        selected = CanonicalSelection.from_dict(inputs.legs[0].selection)
        outcomes = []
        for index, (participant, operator, odds) in enumerate([(selected.event.home_id, "gt", "2"),
                (selected.event.away_id, "lt", "4" if three else "3")] + ([("tie", "eq", "4")] if three else [])):
            native = NativeProvenance("pinnacle", "authored-reference-event", "authored-reference-market", "authored-reference-" + str(index),
                                      participant, "Authored original reference outcome", selected.native.evidence)
            target = replace(selected, family="moneyline", participant_id=participant, signed_line=None,
                             predicate=ScorePredicate("home_margin", operator, ExactNumber("0")), native=native,
                             payout=None, payout_unknown=UnknownValue("Reference grading is separate", ("reference grading",)),
                             price=Price(ExactNumber(odds), "decimal_odds", "usd_per_usd_stake", "USD"))
            outcomes.append(ReferenceOutcome(target, ExactNumber(odds), self.clock, None, self.clock, "authored-ref-" + str(index)))
        return ReferenceSet(tuple(outcomes), "a" * 64, "explicit_three_way" if three else "decisive_win_loss", "b" * 64 if three else None)

    def authored_costs(self, inputs, *, deployed=None, fee="0"):
        """Authored S02 wire inputs; assertions use accepted independent literals."""
        leg = inputs.legs[0]
        deployed = Fraction(deployed) if deployed is not None else leg.acquisition_cash + Fraction(fee)
        states = {state: dict(gross_return_usd=None if gross is None else str(gross),
                              net_return_usd=None if gross is None else str(gross),
                              net_profit_usd=None if gross is None else str(gross - deployed), reasons=[])
                  for state, gross in leg.receipts}
        rule = dict(source_kind="controlled_scenario", version="authored-s04-explicit-cost-input", effective_from=self.clock,
                    effective_to=None, expires_at=None, channel="authored", evidence=[EVIDENCE.to_dict()])
        return stamp_cost(dict(version="comparison-net-costs-1", available=True, reasons=[],
                   capital=dict(deployed_capital_usd=str(deployed), ceiling_usd="100", denominator="actual_deployed_capital"),
                   acquisition_usd=str(leg.acquisition_cash), states=states, rule=dict(rule=rule),
                   size_basis=dict(native_quantity="1", common_capital_ceiling_usd="100"),
                   assumption="Authored standalone hypothetical cost scenario; no observed fee claim",
                   dependencies=dict(cashflows=inputs.table.revision, leg=leg.bound_revision)))

    def calculate(self, inputs, costs=None, reference=None, **kwargs):
        return estimated_net_ev(inputs, costs or self.authored_costs(inputs), reference or self.reference(inputs),
                                at=kwargs.pop("at", self.at), execution_source_at=kwargs.pop("execution_source_at", self.clock), **kwargs)

    def test_original_r07_positive_zero_negative_and_fee_sign_change(self):
        for vector in self.vectors["vectors"]:
            with self.subTest(id=vector["id"]):
                inputs = self.scenario(vector["cost"])
                costs = self.authored_costs(inputs, deployed=vector["deployed"])
                result = self.calculate(inputs, costs)
                self.assertTrue(result["available"], result["reason"])
                self.assertTrue(result["ranking_eligible"])
                self.assertEqual(Fraction(result["expected_profit_usd"]), Fraction(vector["expected_profit"]))
                self.assertEqual(Fraction(result["value"]), Fraction(vector["percent"]))
                self.assertEqual(Fraction(int(result["exact"]["numerator"]), int(result["exact"]["denominator"])), Fraction(vector["percent"]))
                self.assertEqual(result["conditioning"], "completed_decisive_results_only")
                self.assertEqual(result["capital_denominator"], vector["deployed_decimal"])
                self.assertEqual(result["label"], "estimated net benchmark EV")
                self.assertIn("noncompleted", result["details"]["excluded_state_ids"])
        sign = self.calculate(self.scenario(), self.authored_costs(self.scenario(), deployed="5/8"))
        self.assertEqual(Fraction(sign["gross_decisive_benchmark"]["return_percent"]), 20)
        self.assertEqual(Fraction(sign["value"]), -4)

    def test_actual_s02_adapter_and_source_age_s03_integration(self):
        from tests.test_comparison_net_costs import setup_case
        request, _, kwargs = setup_case("kalshi", price="0.5")
        inputs = self.scenario()
        key = inputs.legs[0].native_key
        request = replace(request, trade_time=self.clock, calculation_time=self.clock, event_id=key[1], market_id=key[2])
        kwargs["engine_context"].update(trade_time=self.clock, calculation_time=self.clock, event_id=key[1], market_id=key[2])
        kwargs["engine_context"]["kalshi_metadata"]["event_id"] = key[1]
        costs = calculate_net_costs(request, inputs, **kwargs)
        self.assertTrue(costs["available"], costs["reasons"])
        result = self.calculate(inputs, costs)
        self.assertTrue(result["available"], result["reason"])
        # Original quadratic .07 * .5 * .5 = .0175 on the supplied .0001
        # balance grid: capital .5175; 3/5 payout -.5175 = .0825.
        self.assertEqual(Fraction(result["expected_profit_usd"]), Fraction(33, 400))
        self.assertEqual(Fraction(result["value"]), Fraction(1100, 69))
        self.assertEqual(result["fee_basis"]["rule"]["source_kind"], "controlled_scenario")

    def test_pregame_live_boundaries_gross1800_and_original_receipt_clocks(self):
        inputs = self.scenario()
        for live, limit in ((False, 900), (True, 15)):
            with self.subTest(live=live):
                self.assertTrue(self.calculate(inputs, live=live, at=self.at + timedelta(seconds=limit))["available"])
                expired = self.calculate(inputs, live=live, at=self.at + timedelta(seconds=limit + 1))
                self.assertFalse(expired["available"])
                self.assertIn("too_old", expired["reason"])
                self.assertTrue(expired["gross_decisive_benchmark"]["available"])
        for source in (None, (self.at + timedelta(seconds=1)).isoformat()):
            self.assertFalse(self.calculate(inputs, execution_source_at=source)["available"])
        ref = self.reference(inputs)
        ref = replace(ref, outcomes=(replace(ref.outcomes[0], book_at=(self.at - timedelta(seconds=901)).isoformat()), ref.outcomes[1]))
        stale = self.calculate(inputs, reference=ref)
        self.assertFalse(stale["available"])
        self.assertTrue(stale["gross_decisive_benchmark"]["available"])
        self.assertIn("reference_source_quote_too_old", stale["reason"])
        missing = replace(ref, outcomes=(replace(ref.outcomes[0], book_at=None, market_at=None), ref.outcomes[1]))
        self.assertEqual(self.calculate(inputs, reference=missing)["reason"], "reference_source_clock_unknown")

    def probability(self, inputs, values, *, kind="authored_sensitivity", coverage="complete", qualified=False):
        evidence = EVIDENCE if not qualified else EvidenceReference("controlled-manual-probability-review", "d" * 64, "manual_review")
        return ProbabilityInputs(kind, inputs.table.revision, coverage, "Authored full terminal partition" if coverage == "complete" else "explicit named conditional states",
                     tuple((key, ExactNumber(value)) for key, value in values.items()), (evidence,), self.clock, None, qualified)

    def test_independent_complete_partition_and_authored_tie_sensitivity(self):
        inputs = self.scenario(refund=True)
        below, tie, above, terminal = inputs.state_ids
        values = {below: "9/25", tie: "1/10", above: "27/50", terminal: "0"}
        sensitivity = self.calculate(inputs, probability=self.probability(inputs, values))
        self.assertTrue(sensitivity["available"], sensitivity["reason"])
        self.assertFalse(sensitivity["ranking_eligible"])
        self.assertEqual(sensitivity["label"], "authored sensitivity EV")
        self.assertEqual(Fraction(sensitivity["expected_profit_usd"]), Fraction(9, 100))
        self.assertEqual(Fraction(sensitivity["value"]), 18)
        self.assertEqual(sensitivity["details"]["partition_class"], "complete_terminal_state_EV")
        self.assertEqual(sensitivity["details"]["excluded_state_ids"], [])
        model = self.probability(inputs, values, kind="independent_model", qualified=True)
        result = self.calculate(inputs, probability=model)
        self.assertTrue(result["ranking_eligible"])
        self.assertEqual(result["label"], "model EV")
        self.assertEqual(ProbabilityInputs.from_dict(model.to_dict()), model)

    def test_complete_mass_and_probability0_still_need_known_cashflows(self):
        inputs = self.scenario()
        below, tie, above, terminal = inputs.state_ids
        zero_exception = self.probability(inputs, {below: "2/5", tie: "0", above: "3/5", terminal: "0"})
        self.assertEqual(self.calculate(inputs, probability=zero_exception)["reason"], "required_state_net_profit_unknown")
        missing = self.probability(inputs, {below: "2/5", above: "3/5"})
        self.assertEqual(self.calculate(inputs, probability=missing)["reason"], "complete_probability_partition_incomplete")
        aliases = self.probability(inputs, {"cancelled": "1/2", "abandoned": "1/2"})
        self.assertEqual(self.calculate(inputs, probability=aliases)["reason"], "probability_state_outside_feasible_partition")
        for values in ({below: "0.4", tie: "0.1", above: "0.6", terminal: "0"},
                       {below: "-0.1", tie: "0.1", above: "1", terminal: "0"}):
            self.assertEqual(self.calculate(inputs, probability=self.probability(inputs, values))["reason"], "probabilities_must_sum_exactly_one")
        stale = replace(missing, partition_revision="stale")
        self.assertEqual(self.calculate(inputs, probability=stale)["reason"], "independent_probability_partition_revision_conflict")
        with self.assertRaises(ValueError):
            replace(missing, ranking_qualified=True)

    def test_repeating_complete_probabilities_and_local_tie_unknown(self):
        inputs = self.scenario(refund=True)
        below, tie, above, terminal = inputs.state_ids
        thirds = self.probability(inputs, {below: "1/3", tie: "1/3", above: "1/3", terminal: "0"})
        result = self.calculate(inputs, probability=thirds)
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual(result["expected_profit_usd"], "0")
        self.assertEqual(result["value"], "0")
        costs = self.authored_costs(inputs)
        costs["states"][tie]["net_profit_usd"] = costs["states"][tie]["net_return_usd"] = None
        conditional = self.calculate(inputs, stamp_cost(costs))
        self.assertTrue(conditional["available"], conditional["reason"])
        self.assertIn(tie, conditional["details"]["excluded_state_ids"])
        self.assertEqual(Fraction(conditional["value"]), 20)

    def test_model_contract_is_separate_from_reference_and_expires_independently(self):
        inputs = self.scenario(refund=True)
        below, tie, above, terminal = inputs.state_ids
        model = self.probability(inputs, {below: "2/5", tie: "0", above: "3/5", terminal: "0"}, kind="independent_model", qualified=True)
        result = estimated_net_ev(inputs, self.authored_costs(inputs), None, probability=model,
                                  at=self.at, execution_source_at=self.clock)
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual(result["label"], "model EV")
        self.assertFalse(result["gross_decisive_benchmark"]["available"])
        expired = replace(model, effective_until=(self.at + timedelta(seconds=1)).isoformat())
        self.assertEqual(self.calculate(inputs, at=self.at + timedelta(seconds=1), probability=expired)["reason"], "independent_probability_expired_or_not_effective")

    def test_explicit_three_way_still_conditional_on_completion(self):
        inputs = self.scenario()
        result = self.calculate(inputs, reference=self.reference(inputs, three=True))
        self.assertTrue(result["available"], result["reason"])
        # Above .5, equality .25 at half-face, below .25 => expected .625-.5.
        self.assertEqual(Fraction(result["expected_profit_usd"]), Fraction(1, 8))
        self.assertEqual(Fraction(result["value"]), 25)
        self.assertEqual(result["conditioning"], "completed_three_way_results_only")
        self.assertEqual(result["details"]["excluded_state_ids"], ["noncompleted"])
        self.assertEqual(result["details"]["partition_class"], "conditional_EV")

    def test_no_has_opposing_decisive_odds_and_own_tie_meaning(self):
        inputs = self.scenario(name="Dallas NO")
        result = self.calculate(inputs)
        self.assertTrue(result["available"], result["reason"])
        self.assertEqual(result["details"]["reference"]["selected_odds"], "3")
        self.assertTrue(result["details"]["reference"]["decisive_projection"])
        self.assertEqual(Fraction(result["value"]), -20)
        tie = inputs.state_ids[1]
        self.assertEqual(inputs.to_dict()["legs"][0]["receipts"][tie], "0.5")
        self.assertIn(tie, result["details"]["excluded_state_ids"])

    def test_cost_reference_profile_expiry_and_dependency_integrity(self):
        inputs = self.scenario()
        costs = self.authored_costs(inputs)
        unknown = deepcopy(costs)
        unknown["available"] = False
        unknown["reasons"] = ["fee_rounding_unknown"]
        self.assertEqual(self.calculate(inputs, stamp_cost(unknown))["reason"], "required_net_costs_unavailable")
        forged = deepcopy(costs)
        forged["states"][inputs.state_ids[0]]["net_profit_usd"] = "99"
        self.assertIn("revision_conflict", self.calculate(inputs, forged)["reason"])
        self.assertEqual(self.calculate(inputs, stamp_cost(forged))["reason"], "cost_profit_capital_basis_conflict")
        expires = deepcopy(costs)
        expires["rule"]["rule"]["expires_at"] = self.clock
        self.assertEqual(self.calculate(inputs, stamp_cost(expires))["reason"], "fee_rule_expired_or_not_effective")
        self.assertEqual(self.calculate(inputs, at=instant(inputs.legs[0].profile_effective_until))["reason"], "payout_profile_expired_or_not_effective")
        ref = self.reference(inputs)
        wrong = replace(ref, outcomes=tuple(replace(item, selection=replace(item.selection, event=replace(item.selection.event, occurrence_id="rematch"))) for item in ref.outcomes))
        self.assertEqual(self.calculate(inputs, reference=wrong)["reason"], "exact_reference_selection_missing")
        self.assertNotEqual(self.calculate(inputs)["revision"], self.calculate(inputs, at=self.at + timedelta(seconds=1))["revision"])

    def test_base_hypothetical_and_depth_qualified_conservative_are_distinct(self):
        inputs = self.scenario()
        costs = self.authored_costs(inputs)
        plain = self.calculate(inputs, costs)
        self.assertTrue(plain["ranking_eligible"])
        self.assertFalse(plain["depth_qualified"])
        self.assertFalse(plain["conservative_ranking_eligible"])
        buffer = dict(version="comparison-buffers-1", base=costs, conservative=None,
                      depth=dict(depth_qualified=True, reasons=[]), reasons=[], depth_qualified_ranking_available=True)
        buffer["revision"] = revision(buffer)
        qualified = self.calculate(inputs, costs, buffer=buffer)
        self.assertTrue(qualified["conservative_ranking_eligible"])
        self.assertTrue(qualified["depth_qualified"])
        buffer["depth"]["depth_qualified"] = False
        self.assertFalse(self.calculate(inputs, costs, buffer=buffer)["conservative_ranking_eligible"])

    def test_paired_sensitivity_uses_one_funded_denominator(self):
        inputs = self.scenario()
        base, conservative = self.authored_costs(inputs, deployed="0.7"), self.authored_costs(inputs, deployed="0.8")
        buffer = dict(version="comparison-buffers-1", base=base, conservative=conservative,
                      sensitivity=dict(denominator_usd="0.8"), depth=dict(depth_qualified=False, reasons=["depth_inputs_unavailable"]),
                      reasons=[], depth_qualified_ranking_available=False)
        buffer["revision"] = revision(buffer)
        first = self.calculate(inputs, base, buffer=buffer, funded_denominator="0.8")
        second = self.calculate(inputs, conservative, buffer=buffer, funded_denominator="0.8")
        self.assertEqual(Fraction(first["value"]), Fraction(-25, 2))
        self.assertEqual(Fraction(second["value"]), -25)
        self.assertEqual(first["capital_denominator"], second["capital_denominator"])
        self.assertEqual(Fraction(first["details"]["refundable_sensitivity_allowance_usd"]), Fraction(1, 10))
        self.assertFalse(second["conservative_ranking_eligible"])
        invalid = self.calculate(inputs, base, buffer=buffer, funded_denominator="0.7")
        self.assertEqual(invalid["reason"], "shared_sensitivity_funded_basis_unavailable")

    def test_accepted_oracle_hashes_preserved_and_exact_result_schema_fields(self):
        for item in self.vectors["upstream_inputs"]:
            self.assertEqual(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest(), item["sha256"])
        schema = json.loads((FIXTURES / "comparison-net-ev-schema-v1.json").read_text())
        result = self.calculate(self.scenario())
        self.assertTrue(set(schema["required"]) <= set(result))
        self.assertTrue(set(schema["properties"]["exact"]["required"]) <= set(result["exact"]))


if __name__ == "__main__":
    unittest.main()
