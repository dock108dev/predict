"""Conservative probability selection uses complete exact pairs, not one price."""

from copy import deepcopy
from fractions import Fraction as F
import pytest
from app.comparison.current_pregame import (
    reference,
    revalue_reference,
    main_line,
    REFERENCE_POLICY,
)
from app.storage.store import stamp

AT = stamp("2026-11-18T16:00:00Z")
START = "2026-11-19T03:30:00Z"
RECORD = dict(
    event=dict(home="home", away="away", scheduled_start=START),
    market_identity=dict(family="spread"),
    selection=dict(participant="home", predicate="cover", signed_line="-33.5"),
)


def pair(book, home, away, line="-33.5", **extra):
    return [
        dict(
            id=book + side,
            revision="one",
            facts=dict(
                venue=book,
                market="spread",
                period="game",
                phase="pregame",
                side=side,
                line=str(F(line) if side == "home" else -F(line)),
                price_american=price,
                available=True,
                source_at="2026-11-18T15:00:00Z",
                received_at="2026-11-18T15:01:00Z",
                odd_id=side,
                opposing_odd_id=opposite,
                alternate=False,
                **extra,
            ),
        )
        for side, opposite, price in [("home", "away", home), ("away", "home", away)]
    ]


def test_ucla_lowest_probability_and_tie_order_preserve_same_book_pair():
    quotes = (
        pair("fanduel", "-110", "-110")
        + pair("draftkings", "-105", "-115")
        + pair("betmgm", "-105", "-115")
    )
    result = reference(RECORD, {"event": quotes}, at=AT)
    assert result["book"] == "draftkings"
    assert F(result["probability"]) == F(903, 1846)
    assert result["fair_odds"] == "+104"
    assert [p["price_american"] for p in result["prices"]] == ["-105", "-115"]
    assert result["selection_policy"] == REFERENCE_POLICY
    assert F(result["candidate_probabilities"]["fanduel"]) == F(1, 2)


def test_lower_raw_implied_probability_can_have_higher_no_vig_probability():
    # DK's -105 looks less favorable for the bet, but its opposite -101 reverses
    # that conclusion after margin removal. FanDuel's full pair is conservative.
    quotes = pair("fanduel", "-110", "-130") + pair("draftkings", "-105", "-101")
    assert reference(RECORD, {"event": quotes}, at=AT)["book"] == "fanduel"


def test_incomplete_withdrawn_wrong_line_duplicate_and_future_pairs_do_not_win():
    valid = pair("fanduel", "-110", "-110")
    variants = [
        pair("draftkings", "+150", "-180")[:1],
        pair("draftkings", "+150", "-180", line="-34.5"),
    ]
    for field, value in [
        ("available", False),
        ("source_at", "2026-11-18T17:00:00Z"),
        ("opposing_odd_id", "wrong"),
    ]:
        broken = pair("draftkings", "+150", "-180")
        broken[0]["facts"][field] = value
        variants.append(broken)
    duplicate = pair("draftkings", "+150", "-180")
    duplicate.append(deepcopy(duplicate[0]))
    variants.append(duplicate)
    for broken in variants:
        with pytest.raises(ValueError, match="reference_two_trusted_books_required"):
            reference(RECORD, {"event": valid + broken}, at=AT)
    with pytest.raises(ValueError, match="reference_exact_pair_unavailable"):
        reference(RECORD, {"event": valid}, at=stamp(START))


def test_snapshot_revaluation_changes_only_reference_dependent_values():
    ref = reference(
        RECORD,
        {"event": pair("fanduel", "-110", "-110") + pair("draftkings", "-105", "-115")},
        at=AT,
    )
    original = dict(
        version="old",
        input_revision="old",
        times={"source_at": "original"},
        posted={"value": "+115"},
        fee=dict(
            committed_usd="100",
            entry_usd="0",
            cashflows={
                "win": {"net_receipt_usd": "215"},
                "loss": {"net_receipt_usd": "0"},
            },
        ),
        raw=dict(posted_decimal="2.15", after_fee_decimal="2.15"),
        display=dict(posted_odds="+115", after_fees="+115"),
    )
    result = revalue_reference(original, ref, at=AT)
    assert result["display"]["net_ev"] == "+5.17%"
    assert result["display"]["opportunity_score"] == "450"
    for key in ("fee", "posted", "times"):
        assert result[key] == original[key]
    assert original["version"] == "old"


def test_reference_selection_does_not_relabel_established_main_line_evidence():
    fd = pair("fanduel", "-110", "-110")
    dk = pair("draftkings", "-105", "-115")
    for entry in dk:
        entry["facts"]["alternate"] = None
    result = reference(RECORD, {"event": fd + dk}, at=AT)
    assert result["book"] == "draftkings"
    assert result["main_line_reference_book"] == "fanduel"
    assert main_line(RECORD, result) is False
    main_offer = dict(RECORD, comparison_source_metadata=dict(alternate=False))
    assert main_line(main_offer, result) is True
    for entry in fd:
        entry["facts"]["alternate"] = None
    for entry in dk:
        entry["facts"]["alternate"] = False
    result = reference(RECORD, {"event": fd + dk}, at=AT)
    assert main_line(RECORD, result) is False


def test_one_trusted_book_plus_untrusted_books_cannot_qualify():
    quotes = pair("fanduel", "-8000", "+2500")
    for book in ("betrsportsbook", "boylesports", "casumo", "paddypower"):
        quotes += pair(book, "-10000", "+3000")
    with pytest.raises(ValueError, match="reference_two_trusted_books_required"):
        reference(RECORD, {"event": quotes}, at=AT)
    quotes += pair("draftkings", "-7000", "+2200")
    result = reference(RECORD, {"event": quotes}, at=AT)
    assert result["trusted_book_count"] == 2
    assert set(result["candidate_probabilities"]) == {"fanduel", "draftkings"}
