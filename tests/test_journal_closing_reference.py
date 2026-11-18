"""Exact cross-book closes precede conservative harder-line estimates."""

from fractions import Fraction as F
from app.dashboard.journal_closing_reference import choose
from tests.test_current_pregame_reference_policy import pair as make_pair, AT, START


def pair(*args, **kwargs):
    return make_pair(*args, starts_at=START, **kwargs) + make_pair(
        "caesars", *args[1:], starts_at=START, **kwargs
    )


ORIGINAL = dict(
    family="spread", side="home", kickoff=START, selection=dict(signed_line="-25.5")
)


def test_exact_other_book_wins_before_harder_line_bound():
    ref = choose(
        ORIGINAL,
        {
            "event": pair("draftkings", "-105", "-115", line="-25.5")
            + pair("fanduel", "+150", "-180", line="-26.5")
        },
        at=AT,
    )
    assert ref["book"] == "draftkings"
    assert ref["closing_basis"] == "exact_line_conservative"


def test_lowest_no_vig_exact_pair_across_books():
    ref = choose(
        ORIGINAL,
        {
            "event": pair("fanduel", "-110", "-110", line="-25.5")
            + pair("draftkings", "+110", "-130", line="-25.5")
        },
        at=AT,
    )
    assert ref["book"] == "draftkings"


def test_rescheduled_event_cannot_supply_the_old_occurrence_close():
    rows = pair("fanduel", "-110", "-110", line="-25.5")
    for row in rows:
        row["facts"]["starts_at"] = "2026-11-20T03:30:00Z"
    assert choose(ORIGINAL, {"event": rows}, at=AT) is None


def test_missing_line_uses_harder_neighbor_not_easier_main():
    ref = choose(
        ORIGINAL,
        {
            "event": pair("draftkings", "+110", "-130", line="-26.5")
            + pair("fanduel", "-150", "+130", line="-24.5")
        },
        at=AT,
    )
    assert ref["closing_basis"] == "harder_line_probability_lower_bound"
    assert ref["bound_line"] == "-26.5"
    assert F(ref["target_line"]) == F("-25.5")
    assert (
        choose(
            ORIGINAL, {"event": pair("fanduel", "-150", "+130", line="-24.5")}, at=AT
        )
        is None
    )


def test_away_spread_harder_direction_is_reversed():
    original = dict(ORIGINAL, side="away", selection=dict(signed_line="25.5"))
    ref = choose(
        original, {"event": pair("draftkings", "-110", "-110", line="-24.5")}, at=AT
    )
    assert ref["bound_line"] == "-24.5"


def test_reference_only_bound_changes_ev_without_inventing_a_new_market_quote():
    from copy import deepcopy
    from app.dashboard.bet_journal_metrics import analyze
    from tests.test_bet_journal_metrics import quote, entry, AFTER, CLOSE

    original = quote()
    current = quote(clock="2026-11-18T13:30:00+00:00", odds="+110")
    bound = deepcopy(original)
    bound.update(observed_at=CLOSE, journal_reference_only=True)
    bound["reference"] = quote(clock=CLOSE, probability="0.4")["reference"]
    bound["reference"]["closing_basis"] = "harder_line_probability_lower_bound"
    result = analyze(entry(original), [current, bound], at=AFTER)
    assert result["legs"][0]["close_probability"] == "0.4"
    assert result["legs"][0]["close_quote"]["posted"]["value"] == "+110"
    assert (
        result["legs"][0]["close_reference_basis"]
        == "harder_line_probability_lower_bound"
    )


def test_nearby_estimate_also_requires_two_trusted_books_at_its_line():
    rows = make_pair("fanduel", "-110", "-110", line="-26.5", starts_at=START)
    assert choose(ORIGINAL, {"event": rows}, at=AT) is None
