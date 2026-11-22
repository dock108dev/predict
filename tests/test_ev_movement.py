"""Independent EV signs, exact continuity and cross-checkpoint cashflows."""

from copy import deepcopy
from fractions import Fraction as F

import pytest

from app.comparison import current_pregame as math
from app.research import ev_movement as experiment
from tests.test_research_probability import snapshot as frozen_example


def offer(win="275", *, line="-3", book="kalshi", main=True, probability="0.5",
          coherent="0.6", side="home", fee=None, reason=None):
    record = dict(
        event=dict(id="source-game", home="home", away="away", sport="basketball",
            competition="NBA", title="Away at Home", scheduled_start="2026-11-23T01:00:00Z"),
        market_identity=dict(family="spread", period="full_game", line=line,
                             rules="test-reviewed-two-state-1"),
        selection=dict(participant=side, predicate="cover", signed_line=line),
        result_policy="test-settlement-1", outcome_cardinality=2,
        quote=dict(venue=book, source=dict(provider="sportsgameodds", native_event_id="source-game"),
                   state="available", original=dict(value="+175", units="american_odds"),
                   times=dict(source_at="2026-11-22T22:00:00Z", received_at="2026-11-22T22:00:02Z")),
        comparison_source_metadata=dict(provider_bookmaker_id=book, alternate=not main),
    )
    cash = fee or dict(committed_usd="100", cashflows=dict(
        win=dict(net_receipt_usd=win), loss=dict(net_receipt_usd="0")))
    p = F(probability)
    expected = (p * F(cash["cashflows"]["win"]["net_receipt_usd"]) +
                (1-p)*F(cash["cashflows"]["loss"]["net_receipt_usd"]))/F(cash["committed_usd"])-1
    payload = dict(version=math.VERSION, fee=cash, raw=dict(net_ev=str(expected)),
        calculated_at="2026-11-22T22:00:03Z",
        reference=dict(probability=probability, selection_policy=math.REFERENCE_POLICY, book="fanduel"),
        coherent_probability=dict(probability=coherent, selection_policy=math.COHERENT_POLICY, book="draftkings"))
    return dict(record=record, calculation_payload=payload, fee_input=None, reason=reason)


def checkpoint(*offers):
    return dict(event=dict(scheduled_start="2026-11-23T01:00:00Z"), offers=list(offers),
                times=dict(known_at="2026-11-22T22:00:04Z"))


@pytest.mark.parametrize("a,b,retained,transition", [
    ("180", "180", False, "negative_to_negative"),
    ("180", "220", True, "negative_to_positive"),
    ("220", "180", True, "positive_to_negative"),
    ("220", "220", True, "positive_to_positive"),
    ("200", "220", True, "zero_to_positive"),
    ("220", "200", True, "positive_to_zero"),
    ("200", "200", False, "zero_to_zero"),
])
def test_exact_screen_signs_not_coherent_signs(a, b, retained, transition):
    # Coherent p=.6 makes the180 receipt positive. Selection must still use
    # screen p=.5, whose180 receipt is negative; rounding is never involved.
    result = experiment.compare_checkpoints(checkpoint(offer(a)), checkpoint(offer(b)))
    assert len(result["context"]) == 1
    assert bool(result["cases"]) is retained
    assert result["context"][0]["transition"] == transition
    assert result["context"][0]["early"]["coherent"]["policy"] == math.COHERENT_POLICY


def test_unrounded_tiny_positive_and_unknown_never_become_zero_or_negative():
    early = offer("200.00000000000000000001")
    late = offer("180", reason="fee_applicability_unavailable")
    result = experiment.compare_checkpoints(checkpoint(early), checkpoint(late))
    row = result["cases"][0]
    assert F(row["early"]["screen"]["ev"]) == F(1, 2 * 10**22)
    assert row["late"]["screen"]["ev"] is None
    assert row["transition"] == "incomplete_positive"
    assert row["incomplete"]
    assert row["missing_reasons"] == [dict(checkpoint="late", reason="fee_applicability_unavailable")]


def test_missing_checkpoint_retains_positive_but_does_not_fabricate_transition():
    result = experiment.compare_checkpoints(checkpoint(offer("220")), dict(status="missed", reason="deadline"))
    assert result["cases"][0]["late"] is None
    assert result["cases"][0]["transition"] == "incomplete_positive"
    assert result["cases"][0]["role_link"] == "checkpoint_missing"
    assert result["cases"][0]["missing_reasons"] == [dict(checkpoint="late", reason="deadline")]
    assert result["cases"][0]["early_offer_late_reference"]["reason"] == "checkpoint_or_exact_bet_missing"
    assert not experiment.compare_checkpoints(checkpoint(offer("180")), None)["cases"]
    pending = dict(status="pending", snapshot=None, reason="awaiting_target")
    assert experiment.compare_checkpoints(checkpoint(offer("220")), pending)["cases"][0]["transition"] == "incomplete_positive"
    assert experiment.compare_checkpoints(pending, pending)["context"] == []


def test_main_line_moves_through_exact_alternate_quotes_per_book():
    early = checkpoint(offer("220", line="-3", main=True), offer("180", line="-3.5", main=False),
                       offer("220", line="-4", book="novig", main=True))
    late = checkpoint(offer("180", line="-3", main=False), offer("220", line="-3.5", main=True),
                      offer("220", line="-4", book="novig", main=True))
    result = experiment.compare_checkpoints(early, late)
    kalshi = next(r for r in result["main_line_links"] if r["book"] == "kalshi")
    assert list(map(F, kalshi["early_main_lines"])) == [F(-3)]
    assert list(map(F, kalshi["late_main_lines"])) == [F("-3.5")]
    assert kalshi["movement"] == "changed"
    assert {r["relationship"] for r in kalshi["links"]} == {"main_to_alternate", "alternate_to_main"}
    novig = next(r for r in result["main_line_links"] if r["book"] == "novig")
    assert novig["movement"] == "unchanged"
    assert len(result["context"]) == 3


def test_identity_separates_book_side_line_and_settlement_but_not_role_or_clocks():
    original = offer()["record"]
    identity = experiment.exact_bet_identity(original)["id"]
    for mutate in (
        lambda r: r["comparison_source_metadata"].update(provider_bookmaker_id="novig"),
        lambda r: r["selection"].update(participant="away"),
        lambda r: r["selection"].update(signed_line="-3.5"),
        lambda r: r["market_identity"].update(rules="different-overtime-rules"),
    ):
        changed = deepcopy(original); mutate(changed)
        assert experiment.exact_bet_identity(changed)["id"] != identity
    changed = deepcopy(original)
    changed["comparison_source_metadata"]["alternate"] = True
    changed["quote"]["times"]["received_at"] = "2026-11-22T23:00:00Z"
    changed["quote"]["state"] = "unavailable"
    assert experiment.exact_bet_identity(changed)["id"] == identity


def test_added_and_withdrawn_exact_lines_are_explicit_context_links():
    result = experiment.compare_checkpoints(checkpoint(offer(line="-3")), checkpoint(offer(line="-3.5")))
    assert {r["role_link"] for r in result["cases"]} == {"newly_observed", "no_longer_observed"}
    assert all(r["incomplete"] and r["transition"] == "incomplete_positive" for r in result["cases"])


def test_reference_books_keep_their_own_main_progression_without_becoming_cases():
    early, late = checkpoint(), checkpoint()
    def quote(book, line, alternate):
        return dict(venue=book, market="total", side="over", line=line, alternate=alternate)
    early["raw_quotes"] = [quote("fanduel", "220", False), quote("fanduel", "221", True),
                           quote("draftkings", "222", False)]
    late["raw_quotes"] = [quote("fanduel", "220", True), quote("fanduel", "221", False),
                          quote("draftkings", "222", False)]
    result = experiment.compare_checkpoints(early, late)
    assert not result["cases"] and not result["context"]
    fd = next(r for r in result["main_line_links"] if r["book"] == "fanduel")
    assert fd["early_main_lines"] == ["220"] and fd["late_main_lines"] == ["221"]
    dk = next(r for r in result["main_line_links"] if r["book"] == "draftkings")
    assert dk["movement"] == "unchanged" and dk["early_main_lines"] == ["222"]


def test_inferred_main_is_not_source_reported_main_authority():
    a, b = offer(), offer()
    a["main"] = dict(status="main", source="inferred")
    result = experiment.compare_checkpoints(checkpoint(a), checkpoint(b))
    assert result["main_line_links"][0]["early_main_lines"] == []
    assert result["main_line_links"][0]["movement"] == "unknown"
    assert result["cases"][0]["role_link"] == "unknown_role"


def test_unpriced_received_line_keeps_identity_and_role_without_changing_ingress_default():
    from dataclasses import replace
    from app.collection.sportsgameodds_current_rows import current_rows
    from tests.pregame_fixture import page, parse

    parsed = parse(page())
    quote = deepcopy(next(q for q in parsed.quotes if q["venue"] == "prophetx"))
    quote.update(price_american=None, available=False, alternate=True)
    unpriced = replace(parsed, quotes=(quote,))
    assert current_rows(unpriced, unpriced.receipt_sha256)[0] == []
    retained = current_rows(unpriced, unpriced.receipt_sha256, include_unpriced=True)[0]
    assert len(retained) == 1
    assert retained[0]["quote"]["original"]["value"] is None
    assert retained[0]["quote"]["state"] == "unavailable"
    assert retained[0]["comparison_source_metadata"]["alternate"] is True


def test_cross_reference_preserves_early_cashflows_instead_of_rebuying_late():
    early_fee = dict(committed_usd="101", cashflows=dict(
        win=dict(net_receipt_usd="275"), loss=dict(net_receipt_usd="0")))
    late_fee = dict(committed_usd="110", cashflows=dict(
        win=dict(net_receipt_usd="220"), loss=dict(net_receipt_usd="0")))
    early = offer(probability="0.4", fee=early_fee)
    late = offer(probability="0.6", fee=late_fee)
    original = deepcopy(early)
    row = experiment.compare_checkpoints(checkpoint(early), checkpoint(late))["cases"][0]
    assert F(row["early"]["screen"]["ev"]) == F(9, 101)
    assert F(row["late"]["screen"]["ev"]) == F(1, 5)
    assert F(row["early_offer_late_reference"]["screen"]["ev"]) == F(64, 101)
    assert early == original


def test_wrong_screen_policy_and_withdrawn_prices_cannot_supply_signs():
    early = offer()
    early["calculation_payload"]["reference"]["selection_policy"] = math.COHERENT_POLICY
    late = offer()
    late["record"]["quote"]["state"] = "unavailable"
    result = experiment.compare_checkpoints(checkpoint(early), checkpoint(late))
    assert not result["cases"]
    row = result["context"][0]
    assert row["early"]["screen"]["reason"] == "recorded_probability_policy_mismatch"
    assert row["late"]["screen"]["reason"] == "price_withdrawn"


def test_rescheduled_contract_continuity_stays_explicit_and_unasserted():
    early, late = checkpoint(offer()), checkpoint(offer())
    late["event"]["scheduled_start"] = "2026-11-24T01:00:00Z"
    row = experiment.compare_checkpoints(early, late)["cases"][0]
    assert row["transition"] == "rescheduled_incomplete"
    assert row["early_offer_late_reference"]["screen"] is None
    assert row["early_offer_late_reference"]["reason"] == "rescheduled_settlement_continuity_unverified"


@pytest.mark.parametrize("a,b,reason", [
    ("2026-11-23T00:50:20Z", "2026-11-23T00:50:10Z", "checkpoint_observation_order_unestablished"),
    ("2026-11-23T00:50:01Z", "2026-11-23T00:50:10Z", "late_discovery_no_pre_target_baseline"),
])
def test_late_discovery_and_reversed_checkpoint_order_never_assert_transition(a,b,reason):
    first = dict(checkpoint="early", status="captured", known_at=a, snapshot=checkpoint(offer()))
    late = dict(checkpoint="late", status="captured", known_at=b,
                target_at="2026-11-23T00:50:00Z", snapshot=checkpoint(offer()))
    row = experiment.compare_checkpoints(first,late)["cases"][0]
    assert row["incomplete"] and row["transition"] == "timing_incomplete"
    assert row["early_offer_late_reference"]["reason"] == reason


def test_offline_reproduction_checks_stored_cashflows_and_original_policy_pairs():
    frozen = frozen_example("275")
    payload = frozen["inputs"]["calculation"]
    payload["raw"]["net_ev"] = "0.1"
    row = offer()
    row["record"]["market_identity"]["family"] = "moneyline"
    row["record"]["selection"].update(predicate="win", signed_line=None)
    row["record"]["event"]["scheduled_start"] = payload["kickoff"]
    row["calculation_payload"] = payload
    assert experiment.reproduce_checkpoint(checkpoint(row))["numeric_screen_results"] == 1
    row["calculation_payload"]["raw"]["net_ev"] = "0.2"
    with pytest.raises(ValueError, match="screen_cashflow_reproduction"):
        experiment.reproduce_checkpoint(checkpoint(row))


def test_outcomes_score_observed_scope_without_settlement_or_fills():
    result = experiment.compare_checkpoints(checkpoint(offer()), checkpoint(offer()))
    scored = experiment.score_comparison(result, dict(final=True, result="completed", home_score=110, away_score=100))
    screen = next(r for r in scored["reports"] if r["checkpoint"] == "early" and r["policy"] == "screen")
    assert screen["records"] == 1 and screen["distinct_events"] == 1
    assert F(screen["mean_brier"]) == F(1, 4)
    assert "selection_biased" in scored["scope"]
    assert scored["venue_settlement"] is None and scored["actual_fills"] is None
    pending = experiment.score_comparison(result, dict(final=False))
    assert all(r["records"] == 0 for r in pending["reports"])
    missing = experiment.score_comparison(result, None)
    assert missing["exclusions"] == {"no_sporting_outcome_yet": 1}
    assert all(r["mean_brier"] is None for r in missing["reports"])
