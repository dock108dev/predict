"""Exact observed book prices must not turn nearby or withdrawn lines into matches."""

from app.storage.pregame_sportsbooks import matching_prices
from app.storage.store import stamp

AT = stamp("2026-11-18T15:00:00Z")
ROW = dict(
    league="NBA",
    family="spread",
    kickoff="2026-11-19T00:00:00Z",
    selection=dict(signed_line="-1.5"),
    reference=dict(
        book="fanduel",
        selected_outcome="home",
        prices=[
            dict(event_id="event-1", side="home", odd_id="points-home-game-sp-home")
        ],
    ),
)
QUOTE = dict(
    event_id="event-1",
    league="NBA",
    market="spread",
    side="home",
    period="game",
    phase="pregame",
    available=True,
    provider_available=True,
    starts_at=ROW["kickoff"],
    line="-1.5",
    price_american="-118",
    venue="fanduel",
    provider="sportsgameodds",
    odd_id="points-home-game-sp-home",
    source_at="2026-11-18T14:00:00Z",
    received_at="2026-11-18T14:01:00Z",
    event_status={},
)


def test_exact_prices_keep_reference_and_other_book_actual_odds():
    results = matching_prices(
        ROW, [QUOTE, dict(QUOTE, venue="draftkings", price_american="-112")], at=AT
    )
    assert [(q["book"], q["posted_odds"], q["is_reference"]) for q in results] == [
        ("fanduel", "-118", True),
        ("draftkings", "-112", False),
    ]


def test_wrong_line_side_event_scope_and_withdrawn_never_substitute():
    alterations = [
        dict(line="-2.5"),
        dict(event_id="other"),
        dict(odd_id="points-away-game-sp-away"),
        dict(period="half"),
        dict(partition="three_way"),
        dict(available=False),
        dict(provider_available=False),
        dict(event_status={"started": True}),
        dict(starts_at="2026-11-20T00:00:00Z"),
        dict(venue="polymarket"),
        dict(venue="betfairexchange"),
        dict(venue="unknown"),
        dict(venue="fliff"),
        dict(price_american="-90"),
        dict(received_at="2026-11-19T14:00:00Z"),
    ]
    for change in alterations:
        assert matching_prices(ROW, [dict(QUOTE, **change)], at=AT) == [], change


def test_latest_observation_and_conflicting_same_clock():
    newer = dict(
        QUOTE,
        source_at="2026-11-18T14:02:00Z",
        received_at="2026-11-18T14:03:00Z",
        price_american="-115",
    )
    assert matching_prices(ROW, [QUOTE, newer], at=AT)[0]["posted_odds"] == "-115"
    assert (
        matching_prices(ROW, [newer, dict(newer, price_american="-116")], at=AT) == []
    )


def test_native_outcome_id_preserves_selection_when_roles_were_canonicalized():
    assert matching_prices(ROW, [dict(QUOTE, side="away")], at=AT)[0]["side"] == "home"


def test_reference_free_matching_maps_reversed_event_roles_without_inventing_ev():
    row = dict(
        ROW,
        reference=None,
        family="moneyline",
        selection={},
        side="home",
        sportsbook_event_ids=["event-1"],
        sportsbook_sides_reversed={"event-1": True},
    )
    correct = dict(QUOTE, market="moneyline", line=None, side="away")
    wrong = dict(correct, side="home", venue="draftkings")
    result = matching_prices(row, [correct, wrong], at=AT)
    assert [(q["book"], q["side"], q["is_reference"]) for q in result] == [
        ("fanduel", "home", False)
    ]
    assert result[0]["source_at"] == QUOTE["source_at"]
