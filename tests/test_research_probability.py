"""Independent exact examples distinguish a screen from a coherent model."""

from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F

import pytest

from app.comparison import current_pregame as math
from app.research.calculation import freeze, reproduce
from app.research.records import resolved_side, scores
from app.storage.store import stamp

AT = stamp("2026-11-22T16:00:00Z")
START = "2026-11-23T00:00:00Z"


def pair(book, home, away, *, family="moneyline", line=None):
    sides = ("over", "under") if family == "total" else ("home", "away")
    return [dict(id=book + side, revision="one", facts=dict(
        venue=book, market=family, period="game", phase="pregame", side=side,
        line=None if line is None else str(F(line) if i == 0 or family == "total" else -F(line)),
        price_american=price, available=True, source_at="2026-11-22T15:58:00Z",
        received_at="2026-11-22T15:59:00Z", odd_id=side, opposing_odd_id=sides[1-i],
    )) for i, (side, price) in enumerate(zip(sides, (home, away)))]


def record(side="home", family="moneyline", line=None):
    selection = dict(predicate=side, signed_line=line) if family == "total" else dict(
        participant=side, predicate="win" if family == "moneyline" else "cover", signed_line=line,
    )
    return dict(event=dict(home="home", away="away", scheduled_start=START),
                market_identity=dict(family=family), selection=selection)


def snapshot(receipt, *, probability="2/5", fee="0", committed="100"):
    observations = {"event": pair("fanduel", "+150", "-150") + pair("draftkings", "-150", "+150")}
    ref = math.coherent_reference(record(), observations, at=AT)
    assert F(ref["probability"]) == F(probability)
    return freeze(dict(
        id="offer", game_key="game", kickoff=START, calculated_at=AT.isoformat(),
        selection=record()["selection"], times=dict(source_at=AT.isoformat(), received_at=AT.isoformat()),
        coherent_probability=ref, reference=math.reference(record(), observations, at=AT),
        fee=dict(committed_usd=committed, entry_usd=fee,
                 cashflows=dict(win=dict(net_receipt_usd=receipt), loss=dict(net_receipt_usd="0"))),
        raw=dict(net_ev="0"),
    ))


def test_independently_selected_screens_are_not_one_probability_distribution():
    observations = {"event": pair("fanduel", "+150", "-150") + pair("draftkings", "-150", "+150")}
    home = math.reference(record(), observations, at=AT)
    away = math.reference(record("away"), observations, at=AT)
    assert F(home["probability"]) + F(away["probability"]) == F(4, 5)
    baseline = math.coherent_reference(record(), observations, at=AT)
    other = math.coherent_reference(record("away"), observations, at=AT)
    assert baseline["book"] == other["book"] == "fanduel"
    assert baseline["baseline_id"] == other["baseline_id"]
    assert baseline["probabilities"] == {"home": "0.4", "away": "0.6"}
    assert F(baseline["probability"]) + F(other["probability"]) == 1
    later = math.coherent_reference(record(), observations, at=AT+timedelta(minutes=1))
    assert later["cutoff"] != baseline["cutoff"]
    assert later["baseline_id"] != baseline["baseline_id"]
    assert math.probability_inputs(later) == math.probability_inputs(baseline)


@pytest.mark.parametrize("win,expected", [("275", "1/10"), ("225", "-1/10"), ("250", "0")])
def test_independent_positive_negative_zero_exact_cashflows(win, expected):
    saved = snapshot(win)
    assert F(reproduce(saved)["net_ev"]) == F(expected)
    assert F(reproduce(saved)["expected_profit_usd"]) == F(expected) * 100
    original = deepcopy(saved)
    # A later selection policy cannot rewrite the immutable prior inputs/result.
    altered = deepcopy(saved)
    altered["inputs"]["calculation"]["coherent_probability"]["policy_version"] = "new-policy"
    with pytest.raises(ValueError, match="integrity"):
        reproduce(altered)
    assert saved == original


def test_rounded_cash_commitment_and_unknown_fees_remain_exact():
    # One dollar of entry cost changes the break-even 250 receipt to -1/101.
    saved = snapshot("250", fee="1", committed="101")
    assert F(reproduce(saved)["net_ev"]) == -F(1, 101)
    source = deepcopy(saved["inputs"]["calculation"])
    source["fee"] = None
    result = reproduce(freeze(source))
    assert result["status"] == "probability_only"
    assert result["net_ev"] is None
    source["coherent_probability"] = dict(policy_version=math.COHERENT_POLICY,
        probability=None, probabilities=None, reason="reference_missing")
    assert reproduce(freeze(source))["probability"] is None


def test_recorded_policy_survives_a_new_default_policy(monkeypatch):
    saved = snapshot("275")
    monkeypatch.setattr(math, "COHERENT_POLICY", "future-draftkings-first-2")
    monkeypatch.setitem(math.COHERENT_POLICIES, "future-draftkings-first-2", ("draftkings", "fanduel"))
    assert F(reproduce(saved)["probability"]) == F(2, 5)
    assert F(reproduce(saved)["net_ev"]) == F(1, 10)


def test_aggregated_display_alias_cannot_establish_native_us_fee_applicability():
    from app.comparison.snapshot_fee_scope import provider_venue_fee_reason
    alias = dict(quote=dict(venue="polymarket_us", source=dict(provider="sportsgameodds")),
                 comparison_source_metadata=dict(provider_bookmaker_id="polymarket"))
    assert provider_venue_fee_reason(alias) == "provider_venue_fee_applicability_unestablished"
    native = deepcopy(alias)
    native["quote"]["source"]["provider"] = "polymarket_us"
    assert provider_venue_fee_reason(native) is None


def test_priority_fallback_optional_book_and_self_exclusion():
    rows = {"event": pair("betonline", "+125", "-125") + pair("draftkings", "-110", "-110")}
    default = math.coherent_reference(record(), rows, at=AT)
    assert default["book"] == "draftkings"
    optional = math.coherent_reference(record(), rows, at=AT, policy=math.EXPANSION_POLICY)
    assert optional["book"] == "betonline"
    assert F(optional["probability"]) == F(4, 9)
    excluded = math.coherent_reference(record(), rows, at=AT,
        policy=math.EXPANSION_POLICY, evaluated_book="betonline")
    assert excluded["book"] == "draftkings"
    assert math.reference_key(record())[0] == "moneyline"
    with pytest.raises(ValueError, match="two_trusted"):
        math.reference(record(), rows, at=AT)


@pytest.mark.parametrize("family,line,home,away,side,reason", [
    ("moneyline", None, 20, 10, "home", None),
    ("moneyline", None, 10, 10, None, "tie_or_push_outside_decisive_conditioning"),
    ("spread", "-3.5", 20, 17, "away", None),
    ("spread", "-3", 20, 17, None, "tie_or_push_outside_decisive_conditioning"),
    ("total", "37.5", 20, 17, "under", None),
])
def test_game_outcomes_do_not_invent_exceptional_probability_mass(family, line, home, away, side, reason):
    actual = resolved_side(dict(family=family, period="full_game", line=line),
        dict(final=True, result="completed", home_score=home, away_score=away))
    assert actual == (side, reason)


def test_independent_brier_and_log_loss_example():
    values = scores("1/4", 1)
    assert F(values["brier"]) == F(9, 16)
    assert float(values["log_loss"]) == pytest.approx(1.3862943611198906)


@pytest.mark.parametrize("family,line", [("spread", "-1.25"), ("total", "47.75")])
def test_retained_quarter_line_is_not_scored_as_binary_settlement(family, line):
    from app.comparison.pregame_reference import target

    anchor = "over" if family == "total" else "home"
    assert target(family, anchor, line) == F(line)
    assert resolved_side(dict(family=family, period="full_game", line=line),
        dict(final=True, result="completed", home_score=30, away_score=20)) == (
            None, "outcome_line_settlement_unsupported")
    selected = record(anchor, family, line)
    selected["quote"] = dict(source=dict(provider="sportsgameodds"), original=dict(units="american_odds"))
    assert math.posted_settlement_reason(selected) == "posted_line_settlement_unestablished"
    native = deepcopy(selected)
    native["quote"] = dict(source=dict(provider="kalshi"), original=dict(units="usd_per_contract"))
    assert math.posted_settlement_reason(native) is None
    references = {"event": pair("fanduel", "-110", "-110", family=family, line=line)}
    # Original version-one arithmetic remains reproducible; only the new
    # qualification boundary withholds an unsupported settlement interpretation.
    legacy = math.coherent_reference(selected, references, at=AT)
    saved = freeze(dict(kickoff=START, coherent_probability=legacy, fee=None))
    assert F(reproduce(saved)["probability"]) == F(1, 2)
    with pytest.raises(ValueError, match="reference_line_settlement_unsupported"):
        math.qualified_coherent_reference(selected, references, at=AT)


@pytest.mark.parametrize("family,line", [("spread", "-3.5"), ("total", "47.5")])
def test_other_exact_market_pairs_reproduce(family, line):
    ref = math.coherent_reference(record("over" if family == "total" else "home", family, line),
        {"event": pair("fanduel", "-110", "-110", family=family, line=line)}, at=AT)
    saved = freeze(dict(kickoff=START, coherent_probability=ref, fee=None))
    assert F(reproduce(saved)["probability"]) == F(1, 2)
