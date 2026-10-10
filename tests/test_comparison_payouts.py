from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from fractions import Fraction
import json
from pathlib import Path
import unittest

from app.comparison.adapters import adapt
from app.comparison.event_links import EventLinks, instant
from app.comparison.payouts import (
    BoundLeg, CompletionContext, EXCEPTION_ALIASES, JointState, MAX_PROFILES, PayoutCell,
    PayoutProfile, ProfileRegistry, ScoreRange, bind_profile, joint_states,
    validate_states,
)

ROOT = Path(__file__).resolve().parents[1] / "app/fixtures"


class ComparisonPayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / "comparison-payouts-v1.json").read_text())
        inputs = json.loads((ROOT / "comparison-outcome-adapters-v1.json").read_text())
        cls.links = EventLinks.from_dict(inputs["links"])
        cls.at = instant(cls.fixture["evaluation_at"])
        cls.context = CompletionContext.from_dict(cls.fixture["ordinary_context"])
        cls.selections = {r["id"]: adapt(r["fact"], links=cls.links, at=cls.at) for r in inputs["rows"]}
        cls.raw = {r["selection_id"]: r["profile"] for r in cls.fixture["profile_rows"]}
        cls.profiles = {name: PayoutProfile.from_dict(raw) for name, raw in cls.raw.items()}
        cls.bound = {name: bind_profile(cls.selections[name], profile, at=cls.at, rule_revision=profile.rule_revision, context=cls.context)
                     for name, profile in cls.profiles.items()}

    def test_original_native_and_sportsbook_cashflows_share_one_scenario_table(self):
        legs = tuple(self.bound[name] for name in self.fixture["normal_winner_legs"])
        table = joint_states(legs, at=self.at)
        self.assertEqual(table.coverage, "complete_partition_local_unknowns")
        self.assertEqual(table.payout_units, ("usd_per_contract", "usd_per_contract", "usd_per_usd_stake"))
        for state, part in zip(table.states[:3], ["below", "equal", "above"]):
            self.assertEqual([p.value.original for p in state.payouts], self.fixture["normal_winner_expected"][part])
        tie = table.states[1]
        self.assertEqual(tie.score_range, ScoreRange(0, 0))
        self.assertEqual([p.value.value for p in tie.payouts], [Fraction(1, 2), Fraction(1, 2), Fraction(1)])
        exception = table.states[-1]
        self.assertEqual(exception.aliases, EXCEPTION_ALIASES)
        self.assertTrue(all(p.value is None and p.status == "unknown" for p in exception.payouts))
        self.assertNotIn("delayed_still_pending", exception.aliases)
        self.assertEqual(table.to_dict()["universe"], "integer_completed_scores_or_noncompleted_terminal")

    def test_complete_integer_regions_are_feasible_disjoint_and_exhaustive(self):
        legs = (self.bound["Dallas YES"], self.bound["Dallas -8.50"], self.bound["Dallas -8"])
        table = joint_states(legs, at=self.at)
        self.assertEqual([(s.score_range.lower, s.score_range.upper) for s in table.states[:-1]],
                         [(None, -1), (0, 0), (1, 7), (8, 8), (9, None)])
        # Every independently selected integer belongs to exactly one region.
        for margin in [-100000, -9, -1, 0, 1, 7, 8, 9, 100000]:
            matches = [s for s in table.states[:-1] if s.score_range.contains(margin)]
            self.assertEqual(len(matches), 1)
        at8 = next(s for s in table.states if s.score_range == ScoreRange(8, 8))
        self.assertEqual(at8.payouts[1].value.value, 0)
        self.assertEqual(at8.payouts[2].value.value, 1)  # integer sportsbook push
        total = joint_states((self.bound["Combined over 20.5"],), at=self.at)
        self.assertEqual([(s.score_range.lower, s.score_range.upper) for s in total.states[:-1]], [(0, 20), (21, None)])

    def test_known_normal_outputs_remain_when_exceptions_or_equality_unknown(self):
        table = joint_states((self.bound["Dallas first-half win"],), at=self.at)
        self.assertIsNotNone(table.states[0].payouts[0].value)
        self.assertIsNone(table.states[1].payouts[0].value)
        self.assertIsNotNone(table.states[2].payouts[0].value)
        conditional = joint_states((self.bound["Dallas YES"], self.bound["Tampa Bay LONG"]), at=self.at, include_exceptions=False)
        self.assertEqual(conditional.coverage, "conditional_completed")
        self.assertEqual(len(conditional.states), 3)
        self.assertEqual(conditional.to_dict()["universe"], "integer_completed_scores_only")

    def test_profiles_roundtrip_share_registry_and_unknown_never_becomes_zero(self):
        for name, profile in self.profiles.items():
            with self.subTest(name=name):
                self.assertEqual(profile.to_dict(), self.raw[name])
        registry = ProfileRegistry(self.profiles.values())
        bound = self.bound["Dallas YES"]
        self.assertIs(registry.get(bound.selection.payout), self.profiles["Dallas YES"])
        raw = deepcopy(self.raw["Dallas YES"])
        raw["noncompleted"]["value"] = "0"
        with self.assertRaises(ValueError):
            PayoutProfile.from_dict(raw)
        with self.assertRaises(ValueError):
            PayoutCell(None, "evidenced", None)
        with self.assertRaises(ValueError):
            ProfileRegistry([self.profiles["Dallas YES"]] * (MAX_PROFILES + 1))

    def test_sibling_stale_rule_expiry_and_forged_binding_rejected(self):
        profile = self.profiles["Dallas YES"]
        with self.assertRaises(ValueError):
            bind_profile(self.selections["Dallas NO"], profile, at=self.at, rule_revision=profile.rule_revision, context=self.context)
        with self.assertRaises(ValueError):
            bind_profile(self.selections["Dallas YES"], profile, at=self.at, rule_revision="amended-current-rule", context=self.context)
        expired = datetime(2026, 10, 9, 0, 15, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            bind_profile(self.selections["Dallas YES"], profile, at=expired, rule_revision=profile.rule_revision, context=self.context)
        with self.assertRaises(ValueError):
            joint_states((self.bound["Dallas YES"],), at=expired)
        with self.assertRaises(ValueError):
            BoundLeg(self.selections["Dallas YES"], profile, "forged", self.context, True, None)
        with self.assertRaises(ValueError):
            ProfileRegistry(self.profiles.values()).get(replace(self.bound["Dallas YES"].selection.payout, side_id="no"))

    def test_rule_amendment_advances_revision_and_estimate_flag_survives(self):
        raw = deepcopy(self.raw["Dallas YES"])
        raw.update(version="payout-profile-2", rule_revision="authored-amendment-2")
        raw["noncompleted"] = dict(value="2/5", status="estimated", reason="Authored all-terminal-refund scenario at original acquisition 2/5")
        amended = PayoutProfile.from_dict(raw)
        current = bind_profile(self.selections["Dallas YES"], amended, at=self.at, rule_revision=amended.rule_revision, context=self.context)
        self.assertNotEqual(current.revision, self.bound["Dallas YES"].revision)
        table = joint_states((current,), at=self.at)
        self.assertNotEqual(table.revision, joint_states((self.bound["Dallas YES"],), at=self.at).revision)
        self.assertEqual(table.coverage, "complete_partition_estimated_payouts")
        self.assertEqual(table.states[-1].payouts[0].value.value, Fraction(2, 5))
        registry = ProfileRegistry((self.profiles["Dallas YES"], amended))
        self.assertIs(registry.get(current.selection.payout), amended)

    def test_72_hour_lifecycle_cashflows_and_us_date_gate_are_local(self):
        context = CompletionContext.from_dict(self.fixture["72_hour_context"])
        kalshi = bind_profile(self.selections["Dallas YES"], self.profiles["Dallas YES"],
                             at=self.at, rule_revision=self.profiles["Dallas YES"].rule_revision, context=context)
        us = bind_profile(self.selections["Dallas SHORT"], self.profiles["Dallas SHORT"],
                         at=self.at, rule_revision=self.profiles["Dallas SHORT"].rule_revision, context=context)
        table = joint_states((kalshi, us), at=self.at)
        self.assertIs(kalshi.normal_eligible, False)
        self.assertIs(us.normal_eligible, True)
        self.assertEqual([p.value.original if p.value else None for p in table.states[2].payouts], [None, "1"])
        self.assertIn("fair-price", table.states[2].payouts[0].reason)
        missing_date = replace(context, rescheduled_date=None)
        unresolved = bind_profile(self.selections["Dallas SHORT"], self.profiles["Dallas SHORT"],
                                  at=self.at, rule_revision=us.profile.rule_revision, context=missing_date)
        self.assertIsNone(unresolved.normal_eligible)
        self.assertIsNone(joint_states((unresolved,), at=self.at).states[2].payouts[0].value)
        self.assertIn("elapsed hours", unresolved.normal_reason)
        # The separate calendar input, rather than the elapsed72h, establishes
        # the US within-two-week condition. Sixteen days explicitly fails.
        outside_date = replace(context, rescheduled_date="2026-10-24")
        outside = bind_profile(self.selections["Dallas SHORT"], self.profiles["Dallas SHORT"],
                               at=self.at, rule_revision=us.profile.rule_revision, context=outside_date)
        self.assertIs(outside.normal_eligible, False)
        self.assertNotEqual(kalshi.revision, self.bound["Dallas YES"].revision)
        self.assertEqual(table.to_dict()["completion_conditions"][0]["context"], context.to_dict())

    def test_overlaps_gaps_contradictions_and_lifecycle_double_count_rejected(self):
        table = joint_states((self.bound["Dallas YES"],), at=self.at)
        with self.assertRaises(ValueError):
            ScoreRange(9, 8)
        gap = tuple(s for s in table.states if s.score_range != ScoreRange(0, 0))
        with self.assertRaises(ValueError):
            validate_states(gap, minimum=None, legs=1, include_exceptions=True)
        overlap = list(table.states)
        overlap[1] = replace(overlap[1], score_range=ScoreRange(-1, 0))
        with self.assertRaises(ValueError):
            validate_states(tuple(overlap), minimum=None, legs=1, include_exceptions=True)
        double = table.states + (JointState("abandoned-second-bucket", "noncompleted", None, EXCEPTION_ALIASES, table.states[-1].payouts),)
        with self.assertRaises(ValueError):
            validate_states(double, minimum=None, legs=1, include_exceptions=True)
        correction = list(table.states)
        correction[1] = replace(correction[1], aliases=("old_result", "corrected_result"))
        with self.assertRaises(ValueError):
            validate_states(tuple(correction), minimum=None, legs=1, include_exceptions=True)

    def test_cross_domain_scope_duplicate_and_missing_leg_inputs_decline_locally(self):
        for legs in [(self.bound["Dallas YES"], self.bound["Combined over 20.5"]),
                     (self.bound["Dallas YES"], self.bound["Dallas first-half win"]),
                     (self.bound["Dallas YES"], self.bound["Dallas YES"])]:
            with self.subTest(legs=legs), self.assertRaises(ValueError):
                joint_states(legs, at=self.at)
        table = joint_states((self.bound["Dallas YES"],), at=self.at)
        missing = tuple(replace(s, payouts=()) for s in table.states)
        with self.assertRaises(ValueError):
            validate_states(missing, minimum=None, legs=1, include_exceptions=True)


if __name__ == "__main__":
    unittest.main()
