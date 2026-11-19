"""Exact cross-book closes precede conservative harder-line estimates."""

from fractions import Fraction as F
from app.dashboard.journal_closing_reference import choose
from app.storage.store import stamp
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


def test_missing_exact_line_interpolates_between_same_book_alternates():
    rows = pair("draftkings", "+150", "-150", line="-26.5") + pair(
        "draftkings", "-150", "+150", line="-24.5"
    )
    ref = choose(ORIGINAL, {"event": rows}, at=AT)
    assert ref["closing_basis"] == "alternate_line_interpolation"
    assert ref["book"] == "draftkings"
    assert F(ref["probability"]) == F(1, 2)
    assert ref["fair_odds"] == "+100"
    assert ref["estimated_posted_odds"] == "+100"
    assert ref["probability_range"] == ["0.4", "0.6"]
    assert [b["line"] for b in ref["alternate_lines"]] == ["-26.5", "-24.5"]
    assert len(ref["prices"]) == 4
    assert ref["trusted_book_count"] == 2


def test_interpolation_weights_distance_and_never_joins_different_books():
    rows = pair("draftkings", "+150", "-150", line="-27.5") + pair(
        "draftkings", "-150", "+150", line="-24.5"
    )
    ref = choose(ORIGINAL, {"event": rows}, at=AT)
    assert F(ref["probability"]) == F(8, 15)
    assert ref["fair_odds"] == "-114"
    unmatched = make_pair(
        "draftkings", "+150", "-150", line="-26.5", starts_at=START
    ) + make_pair("fanduel", "-150", "+150", line="-24.5", starts_at=START)
    assert choose(ORIGINAL, {"event": unmatched}, at=AT) is None


def test_total_over_and_under_interpolate_in_opposite_directions():
    from copy import deepcopy

    rows = pair("draftkings", "-150", "+150", line="144.5") + pair(
        "draftkings", "+150", "-150", line="146.5"
    )
    for row in rows:
        q = row["facts"]
        q.update(
            market="total",
            line=str(abs(F(q["line"]))),
            side="over" if q["side"] == "home" else "under",
            odd_id="over" if q["odd_id"] == "home" else "under",
            opposing_odd_id="over" if q["opposing_odd_id"] == "home" else "under",
        )
    for side in ("over", "under"):
        original = dict(
            ORIGINAL,
            family="total",
            side=side,
            selection=dict(predicate=side, signed_line="145.5"),
        )
        ref = choose(original, {"event": deepcopy(rows)}, at=AT)
        assert ref["closing_basis"] == "alternate_line_interpolation"
        assert ref["fair_odds"] == "+100"
        assert ref["market"]["line"] == "145.5"


def test_interpolated_best_book_uses_lowest_qualified_estimate():
    rows = (
        make_pair("fanduel", "-110", "-110", line="-26.5", starts_at=START)
        + make_pair("fanduel", "-300", "+300", line="-24.5", starts_at=START)
        + make_pair("draftkings", "+150", "-150", line="-26.5", starts_at=START)
        + make_pair("draftkings", "-150", "+150", line="-24.5", starts_at=START)
    )
    ref = choose(ORIGINAL, {"event": rows}, at=AT)
    assert ref["book"] == "draftkings"
    assert F(ref["candidate_probabilities"]["fanduel"]) == F(5, 8)
    assert F(ref["candidate_probabilities"]["draftkings"]) == F(1, 2)


def test_crossed_alternate_probabilities_do_not_create_an_estimate_or_bound():
    rows = pair("draftkings", "-150", "+150", line="-26.5") + pair(
        "draftkings", "+150", "-150", line="-24.5"
    )
    assert choose(ORIGINAL, {"event": rows}, at=AT) is None


def test_alternate_bracket_survives_journal_storage_and_closing_measurement(tmp_path):
    from copy import deepcopy
    from datetime import timedelta
    from app.dashboard.bet_journal import Journal
    from app.dashboard.bet_journal_metrics import analyze
    from browser_tests.test_pregame_current import offer

    original = offer()
    original.update(ORIGINAL, side="home")
    original["times"] = dict(
        source_at="2026-11-18T15:00:00Z", received_at="2026-11-18T15:01:00Z"
    )
    rows = pair("draftkings", "+150", "-150", line="-26.5") + pair(
        "draftkings", "-150", "+150", line="-24.5"
    )
    reference = choose(original, {"event": rows}, at=AT)
    journal = Journal(tmp_path / "journal.sqlite3")
    key = journal.observe("ev", original, manual=True, at=AT)
    reference_only = deepcopy(original)
    reference_only.update(reference=reference, journal_reference_only=True)
    assert journal.quotes([reference_only], at=AT) == 1
    record = Journal(journal.path).get(key, history=True)
    assert (
        record["quotes"][0]["reference"]["alternate_lines"]
        == reference["alternate_lines"]
    )
    result = analyze(
        record["entry"], record["quotes"], at=stamp(START) + timedelta(minutes=1)
    )
    fair = result["legs"][0]["closing_fair"]
    assert fair["fair_odds"] == "+100"
    assert fair["basis"] == "alternate_line_interpolation"
    assert fair["posted_estimated"] is True
    assert fair["posted_odds"] == "+100"
    assert [q["selection"]["signed_line"] for q in fair["alternate_lines"]] == [
        "-26.5",
        "-24.5",
    ]
    assert result["legs"][0]["close_quote"]["posted"] == original["posted"]
