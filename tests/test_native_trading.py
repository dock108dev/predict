import asyncio
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F

import httpx
import pytest

from app.collection import dashboard_pmus
from app.collection.native_trading_identity import (
    college_reviews,
    link,
    native_event,
    record,
    expected,
)
from app.collection.native_trading_novig import bindings as novig_bindings
from app.storage import native_trading
from tests.test_dashboard_pmus import (
    AT,
    KICKOFF,
    KINDS,
    event,
    market,
    response,
    fee_metadata,
)
from tests.test_novig_experiment_depth import (
    CUTOFF,
    binding,
    market as novig_market,
    receipt as novig_receipt,
    uid,
)


def test_native_alternate_without_any_sgo_trading_quote_has_its_own_price_and_size():
    calls = []

    def serve(req):
        calls.append(req.url.path)
        if req.url.path == "/v1/events":
            family = next(
                k for k, v in KINDS.items() if v == req.url.params["sportsMarketTypes"]
            )
            return response(
                {
                    "events": [
                        event(
                            market(
                                family,
                                line={"spread": 31.5, "total": 221.5}.get(family),
                            )
                        )
                    ]
                }
            )
        return response(
            dict(
                marketData=dict(
                    marketSlug="observed-native-2",
                    state="OPEN",
                    transactTime="2026-11-27T23:49:59Z",
                    bids=[dict(px=dict(currency="USD", value=".7"), qty="1000")],
                    offers=[dict(px=dict(currency="USD", value=".71"), qty="1000")],
                )
            )
        )

    async def run():
        from app.collection.native_experiment_depth import NativeExperimentDepth

        async with NativeExperimentDepth(
            client=httpx.AsyncClient(transport=httpx.MockTransport(serve)),
            now=lambda: AT,
        ) as client:
            catalog = await dashboard_pmus.read(
                client,
                "NBA",
                {},
                at=AT,
                cutoff=AT + timedelta(seconds=2),
                products=fee_metadata(),
                discover_window=(AT, AT + timedelta(hours=24)),
            )
            selected = {cid: b for cid, b in catalog.items() if b["market_id"] == "2"}
            assert len(selected) == 2
            books = await client.read_native(selected, AT + timedelta(seconds=2))
            return catalog, books

    catalog, books = asyncio.run(run())
    assert len(catalog) == 6
    assert calls.count("/v1/markets/observed-native-2/book") == 1
    book = next(b for b in books.values() if b["native_side"] == "Short")
    row = book["_record"]
    assert expected(row)["signed_line"] == "-63/2"
    assert book["levels"] == [dict(price="3/10", quantity="1000")]
    game = link(row["event"], [])
    noev = native_trading.projection(
        row,
        book,
        game,
        None,
        None,
        "reference_exact_pair_unavailable",
        at=AT,
        stake="25",
    )
    assert noev["row"]["posted"]["value"] == "0.3"
    assert noev["row"]["liquidity"]["available_native_quantity"] == "1000"
    assert noev["row"]["liquidity"]["size_status"] == "full_size"
    assert noev["row"]["calculation"]["status"] == "unavailable"
    assert noev["row"]["liquidity"]["modeled_net_ev"] is None
    valued = native_trading.projection(
        row,
        book,
        game,
        dict(probability=".4", fair_odds="+150"),
        AT + timedelta(seconds=20),
        None,
        at=AT,
        stake="25",
    )
    assert valued["row"]["posted"] == noev["row"]["posted"]
    assert F(valued["row"]["liquidity"]["modeled_net_ev"]) > 0
    assert valued["row"]["liquidity"]["modeled_fee_usd"] != "0"


def native():
    return native_event(
        "novig",
        "venue-game",
        "NBA",
        KICKOFF,
        dict(home="NBA:NYK", away="NBA:MIA"),
        dict(home="New York Knicks", away="Miami Heat"),
        proof={"source": "fixture"},
    )


def anchor(event):
    source = deepcopy(event)
    source.update(id="sgo-game", shared_provider_ids={"novig_event": "venue-game"})
    return dict(event=source, canonical_game_id="saved-canonical-game")


def test_five_minute_difference_needs_both_roles_and_exact_event_link_and_keeps_paper_clock():
    event = native()
    saved = anchor(event)
    saved["event"]["scheduled_start"] = "2026-11-27T23:55:00Z"
    matched = link(event, [saved])
    assert matched["canonical_game_id"] == "saved-canonical-game"
    assert matched["native_start"] == event["scheduled_start"]
    assert matched["sgo_start"] == "2026-11-27T23:55:00Z"
    assert matched["schedule_skew_seconds"] == "300.0"
    assert saved["event"]["scheduled_start"] == "2026-11-27T23:55:00Z"
    saved["event"]["shared_provider_ids"] = {}
    assert link(event, [saved])["status"] == "unresolved"
    saved = anchor(event)
    saved["event"].update(home="NBA:MIA", away="NBA:NYK")
    assert link(event, [saved])["status"] == "unresolved"


def test_separate_meetings_and_doubleheaders_cannot_merge_by_team_labels():
    event = native()
    first, second = anchor(event), anchor(event)
    second["event"]["id"] = "other-sgo-event"
    assert link(event, [first, second])["reason"] == "ambiguous_occurrence"
    event["competition"] = "MLB"
    first["event"]["competition"] = "MLB"
    first["event"]["shared_provider_ids"] = {}
    assert link(event, [first])["status"] == "unresolved"


def test_exact_clock_does_not_override_a_contradictory_typed_venue_link():
    event = native()
    saved = anchor(event)
    saved["event"]["shared_provider_ids"]["novig_event"] = "other-venue-game"
    assert link(event, [saved])["status"] == "unresolved"


def test_typed_link_preserves_canonical_id_through_reschedule_and_beats_clock_only_match():
    event = native()
    saved, weak = anchor(event), anchor(event)
    saved["event"].update(
        scheduled_start="2026-11-28T00:30:00Z", original_start=event["scheduled_start"]
    )
    weak["event"].update(id="other-sgo-event", shared_provider_ids={})
    match = link(event, [weak, saved])
    assert match["canonical_game_id"] == "saved-canonical-game"
    assert match["sgo_event_id"] == "sgo-game"
    assert match["sgo_start"] == "2026-11-28T00:30:00Z"
    assert match["sgo_prior_start"] == match["native_start"] == event["scheduled_start"]


def test_retained_source_event_preserves_matching_through_reschedule_without_typed_link():
    event = native()
    saved = anchor(event)
    saved["event"]["shared_provider_ids"] = {}
    original = link(event, [saved])
    assert original["status"] == "matched"
    no_anchor = link(event, [], prior=original)
    assert no_anchor["sgo_event_id"] == original["sgo_event_id"]
    assert no_anchor["sgo_start"] == original["sgo_start"]
    assert no_anchor["reason"] == "sgo_occurrence_unavailable"
    assert no_anchor["status"] == "unresolved"
    saved["event"]["scheduled_start"] = "2026-11-28T00:15:00Z"
    after = link(event, [saved], prior=original)
    assert after["status"] == "matched"
    assert after["method"] == "retained_source_event_and_both_roles"
    assert after["canonical_game_id"] == original["canonical_game_id"]
    saved["event"]["id"] = "one-different-sgo-occurrence"
    assert link(event, [saved], prior=original)["status"] == "unresolved"


def test_explicit_doubleheader_number_conflict_vetoes_shared_id():
    event = native()
    event.update(competition="MLB", game_number=2)
    saved = anchor(event)
    saved["event"]["game_number"] = 1
    assert link(event, [saved])["status"] == "unresolved"


def test_kalshi_related_family_ticks_share_occurrence_and_keep_exact_native_identity():
    event = native_event(
        "kalshi",
        "KXNBASPREAD-GAME",
        "NBA",
        KICKOFF,
        dict(home="NBA:NYK", away="NBA:MIA"),
        dict(home="NYK", away="MIA"),
        proof={"source": "milestone"},
        occurrence_id="KXNBAGAME-GAME",
        occurrence_links=("KXNBAGAME-GAME", "KXNBASPREAD-GAME", "KXNBATOTAL-GAME"),
    )
    saved = anchor(event)
    saved["event"]["shared_provider_ids"] = {"kalshi_event": "KXNBAGAME-GAME"}
    assert link(event, [saved])["canonical_game_id"] == "saved-canonical-game"
    assert link(event, [])["canonical_game_id"] == "source:kalshi:KXNBAGAME-GAME"
    offer = record(
        "kalshi",
        event,
        "spread-market",
        "yes",
        "yes",
        "spread",
        "home",
        "-2.5",
        settlement={},
    )
    assert offer["quote"]["source"]["native_event_id"] == "KXNBASPREAD-GAME"


def test_current_d1_aliases_match_both_sgo_roles_and_reject_unreviewed_or_reversed_roles():
    native_roles = dict(home="NCAAB:M:D1:NCAA340", away="NCAAB:M:D1:NCAA83")
    source_roles = {
        role: f"sportsgameodds:NCAAB:sgo-game:{role}" for role in native_roles
    }
    event = native_event(
        "polymarket_us",
        "263982",
        "NCAAB",
        KICKOFF,
        native_roles,
        dict(home="La Salle", away="Bucknell"),
        proof={"fixture": "native-participant-ids"},
    )
    source = dict(
        id="sgo-game",
        competition="NCAAB",
        scheduled_start=event["scheduled_start"],
        **source_roles,
        participants={
            "La Salle": source_roles["home"],
            "Bucknell Bison": source_roles["away"],
        },
    )
    saved = dict(event=source, canonical_game_id="pre-existing-game")
    result = link(event, [saved])
    assert result["canonical_game_id"] == "pre-existing-game"
    assert result["roles"] == native_roles
    aliases = result["evidence"]["college_review"]["sportsgameodds"]
    assert aliases["home"]["method"] == "exact_institutional_alias"
    assert aliases["away"]["method"] == "reviewed_season_alias"
    source["participants"] = {
        "La Salle": source_roles["away"],
        "Bucknell Bison": source_roles["home"],
    }
    assert link(event, [saved])["status"] == "unresolved"
    source["participants"] = {
        "La Salle": source_roles["home"],
        "Bucknell Bisons": source_roles["away"],
    }
    assert link(event, [saved])["status"] == "unresolved"


@pytest.mark.parametrize("sgo_id", sorted(college_reviews()["events"]))
def test_reviewed_college_aliases_map_each_role_without_rewriting_event_ids(sgo_id):
    review = college_reviews()["events"][sgo_id]
    league = review["league"]
    teams = review["teams"]
    subjects = {role: evidence["novig_subject"] for role, evidence in teams.items()}
    nicknames = {
        role: evidence["novig_outcome"].split()[0] for role, evidence in teams.items()
    }
    event = native_event(
        "novig",
        review["novig_event"],
        league,
        review["official_start"],
        {role: "novig:team:" + value for role, value in subjects.items()},
        nicknames,
        proof={"subjects": subjects},
    )
    original_keys = {role: f"sportsgameodds:{league}:{sgo_id}:{role}" for role in teams}
    source = dict(
        id=sgo_id,
        competition=league,
        scheduled_start=review["official_start"],
        **original_keys,
        participants={p["sgo_name"]: original_keys[role] for role, p in teams.items()},
        shared_provider_ids={"novig_event": review["novig_event"]},
    )
    saved = dict(event=source, canonical_game_id="pre-existing-game")
    result = link(event, [saved])
    assert result["canonical_game_id"] == "pre-existing-game"
    assert result["roles"] == {
        role: evidence["canonical"] for role, evidence in teams.items()
    }
    assert (
        result["evidence"]["college_review"]["novig"]["home"]["novig_market"]
        == review["novig_market"]
    )
    assert {role: source[role] for role in teams} == original_keys
    event["native_role_evidence"]["subjects"] = {
        "home": subjects["away"],
        "away": subjects["home"],
    }
    assert link(event, [saved])["status"] == "unresolved"


def test_novig_native_discovery_binds_both_roles_and_enumerates_unrepresented_lines():
    chosen = dict(binding(line="-10.5"), selected_side="away", league="NCAAB")
    raw = novig_market(chosen, dict(price="0.75", qty=2000))
    proof = novig_receipt()
    proof["status"] = 200
    raw["receipt"] = proof
    native = dict(
        eventId=uid(1), league="NCAAB", status="OPEN_PREGAME", startsTs=raw["startsTs"]
    )
    output = novig_bindings(native, {raw["marketId"]: raw}, proof, at=CUTOFF)
    assert len(output) == 2
    selected = next(
        b for b in output.values() if b["contract"]["selected_side"] == "away"
    )
    assert selected["contract"]["signed_line"] == "-21/2"
    assert selected["levels"] == [dict(price="1/4", quantity="2000")]
    assert selected["_record"]["quote"]["source"]["provider"] == "novig"
    assert selected["_record"]["event"]["home"] != selected["_record"]["event"]["away"]
    wrong = deepcopy(raw)
    wrong["outcomes"][0]["subjectId"] = wrong["outcomes"][1]["subjectId"]
    with pytest.raises(ValueError, match="novig_subject_role_conflict"):
        novig_bindings(native, {raw["marketId"]: wrong}, proof, at=CUTOFF)


def test_exact_reference_pair_is_independent_of_trading_quote_and_expires_on_its_source_clock():
    event = native()
    row = record(
        "novig", event, "m", "o", "buy", "spread", "home", "-3.5", settlement={}
    )
    game = dict(status="matched", sgo_event_id="sgo-game")
    observations = []
    for book in ("fanduel", "draftkings"):
        for side, line in (("home", "-3.5"), ("away", "3.5")):
            observations.append(
                dict(
                    id=book + side,
                    revision="one",
                    facts=dict(
                        venue=book,
                        phase="pregame",
                        market="spread",
                        period="game",
                        side=side,
                        line=line,
                        available=True,
                        source_at=AT.isoformat(),
                        received_at=AT.isoformat(),
                        price_american="-110",
                        odd_id=side,
                        opposing_odd_id="away" if side == "home" else "home",
                    ),
                )
            )
    ref, expires, reason = native_trading.reference(row, game, observations, at=AT)
    assert reason is None and F(ref["probability"]) == F(1, 2)
    assert expires == AT + native_trading.REFERENCE_AGE
    # A different line is not an exact reference, even when price is identical.
    row["selection"]["signed_line"] = "-4.5"
    assert native_trading.reference(row, game, observations, at=AT)[0] is None
    row["selection"]["signed_line"] = "-3.5"
    assert (
        native_trading.reference(
            row, game, observations, at=AT + timedelta(minutes=16)
        )[0]
        is None
    )


def test_native_price_disagreement_retains_both_prices_and_observation_skew():
    event = native()
    row = record(
        "novig", event, "m", "o", "buy", "spread", "home", "-3.5", settlement={}
    )
    book = dict(
        venue="novig",
        source_at="2026-11-27T23:49:59Z",
        received_at=AT.isoformat(),
        levels=[dict(price=".3", quantity="100")],
    )
    observation = dict(
        id="sgo-quote",
        revision="one",
        facts=dict(
            venue="novig",
            market="spread",
            period="game",
            side="home",
            line="-3.5",
            price_american="+150",
            source_at="2026-11-27T23:48:00Z",
            received_at=AT.isoformat(),
        ),
    )
    (compared,) = native_trading.audit(row, book, [observation])
    assert F(compared["price_difference"]) == F("-0.1")
    assert F(compared["time_skew_seconds"]) == 119
    assert compared["comparison"] == "time_skew"
    assert book["levels"][0]["price"] == ".3"
    observation["facts"]["source_at"] = "2026-11-27T23:49:59Z"
    assert (
        native_trading.audit(row, book, [observation])[0]["comparison"]
        == "comparable_window"
    )
    observation["facts"]["line"] = "-4.5"
    assert native_trading.audit(row, book, [observation]) == []


def test_overlapping_book_consumers_share_one_receipt_without_redating_it():
    from app.collection.native_experiment_depth import NativeExperimentDepth
    from tests.test_native_experiment_depth import binding

    calls = []

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def serve(req):
            calls.append(req.url.path)
            entered.set()
            await release.wait()
            return response(
                {
                    "orderbook_fp": {
                        "yes_dollars": [[".4", "200"]],
                        "no_dollars": [[".7", "100"]],
                    }
                }
            )

        async with NativeExperimentDepth(
            client=httpx.AsyncClient(transport=httpx.MockTransport(serve)),
            now=lambda: AT,
        ) as client:
            first = asyncio.create_task(
                client.read_native(
                    {"yes": binding("kalshi", "same", "yes", "no")},
                    AT + timedelta(seconds=1),
                )
            )
            await entered.wait()
            second = asyncio.create_task(
                client.read_native(
                    {"no": binding("kalshi", "same", "no", "yes")},
                    AT + timedelta(seconds=1),
                )
            )
            await asyncio.sleep(0)
            release.set()
            return await asyncio.gather(first, second)

    first, second = asyncio.run(run())
    assert len(calls) == 1
    assert first["yes"]["receipts"] == second["no"]["receipts"]


def test_fee_setting_changes_valuation_without_mutating_native_terms_or_book_expiry():
    from tests.test_liquidity_execution import admitted

    event = native()
    row = record(
        "novig", event, "m", "o", "buy", "spread", "home", "-3.5", settlement={}
    )
    book = admitted((".25", 50000), league="NBA", line="-3.5", coefficient=".03")
    book["contract"] = dict(book["contract"], **expected(row))
    source = deepcopy(book)
    game = link(event, [])
    included = native_trading.projection(
        row,
        book,
        game,
        dict(probability=".4"),
        AT + timedelta(seconds=3),
        None,
        at=AT,
        fee_mode={"enabled": True},
    )
    excluded = native_trading.projection(
        row,
        book,
        game,
        dict(probability=".4"),
        AT + timedelta(seconds=3),
        None,
        at=AT,
        fee_mode={"enabled": False},
    )
    assert F(included["row"]["liquidity"]["modeled_fee_usd"]) > 0
    assert excluded["row"]["liquidity"]["modeled_fee_usd"] == "0"
    assert book == source


def test_kalshi_enumerates_exact_native_outcomes_without_sgo_offer_candidates():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.collection.dashboard_kalshi import Catalog

    ticker = "KXNBAGAME-26NOV27MIANYK"
    markets = [
        dict(
            ticker=ticker + "-" + side,
            event_ticker=ticker,
            status="active",
            strike_type="structured",
            custom_strike={"basketball_team": side},
            yes_sub_title=label,
            rules_primary="If "
            + label
            + " wins the game, then the market resolves to Yes.",
        )
        for side, label in (("home-id", "New York Knicks"), ("away-id", "Miami Heat"))
    ]
    milestone = dict(
        id="official-milestone",
        start_date=KICKOFF,
        related_event_tickers=[ticker],
        details=dict(
            home_team_id="home-id",
            away_team_id="away-id",
            main_game_event_ticker=ticker,
        ),
    )
    proof = dict(received_at=AT.isoformat(), sha256="native-catalog-proof")
    catalog = Catalog()
    catalog.get = AsyncMock(
        return_value=(
            dict(
                cursor="",
                events=[
                    dict(
                        event_ticker=ticker, series_ticker="KXNBAGAME", markets=markets
                    )
                ],
            ),
            proof,
            None,
        )
    )
    output = asyncio.run(
        catalog._event(
            SimpleNamespace(now=lambda: AT),
            "NBA",
            {},
            milestone,
            proof,
            AT + timedelta(seconds=2),
            discover=True,
        )
    )
    assert len(output) == 2
    records = [entries[0][0]["_record"] for entries in output.values()]
    assert {r["selection"]["participant"] for r in records} == {"NBA:NYK", "NBA:MIA"}
    assert {r["quote"]["source"]["provider"] for r in records} == {"kalshi"}
    assert len({r["quote"]["source"]["native_market_id"] for r in records}) == 2
