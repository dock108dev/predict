import asyncio
from copy import deepcopy
from datetime import timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.collection.native_trading_identity import native_event
from app.collection.native_trading_prophetx import (
    EVENTS,
    MARKETS,
    TOURNAMENTS,
    MarketData,
    bindings,
)
from app.comparison.experiment_depth_execution import evaluate_at_stake
from app.comparison.native_observation import adopt
from app.storage.store import encoded, stamp

AT = stamp("2026-11-27T23:50:00Z")
STRIKE = "a" * 32
START = "2026-11-28T00:00:00Z"


def event():
    return native_event(
        "prophetx",
        "101",
        "NBA",
        START,
        dict(home="NBA:NYK", away="NBA:MIA"),
        dict(home="New York Knicks", away="Miami Heat"),
        proof=dict(
            path=EVENTS,
            status=200,
            event_status="scheduled",
            event_id="101",
            scheduled_start=START,
            requested_at=(AT - timedelta(seconds=1)).isoformat(),
            date=format_datetime(AT, usegmt=True),
            received_at=AT.isoformat(),
            competitors={
                "home": dict(id=43, name="New York Knicks"),
                "away": dict(id=14, name="Miami Heat"),
            },
        ),
    )


def market():
    selection = dict(
        outcome_id=10,
        strike_id=STRIKE,
        competitor_id=43,
        price=120,
        quantity="110",
        strike="-3.5",
        name="New York Knicks",
    )
    return dict(
        id=3,
        type="spread",
        sub_type="spread",
        category_name="Game Lines",
        selections=[
            [selection, dict(selection, price=110, quantity="20"), deepcopy(selection)]
        ],
    )


def receipt(at=AT):
    return dict(
        date=format_datetime(at, usegmt=True),
        received_at=at.isoformat(),
        age="0",
        sha256="fixture",
    )


def test_affiliate_strike_identity_preserves_units_and_deduplicates_repeated_levels():
    (book,) = bindings(event(), market(), receipt(), at=AT).values()
    assert book["native_strike_id"] == STRIKE and book["native_outcome_id"] == 10
    assert book["quantity_unit"] == "usd_stake"
    assert len(book["levels"]) == 2
    assert [level["quantity"] for level in book["levels"]] == ["110", "20"]
    assert book["_record"]["quote"]["source"]["provider_outcome_id"] == "10"
    assert book["contract"]["signed_line"] == "-7/2"
    assert book["contract"]["phase"] == "pregame"
    assert book["fee"]["reason"] == "prophetx_exact_fee_schedule_unverified"
    assert encoded(book)
    liquidity = evaluate_at_stake(
        book, at=AT, stake="25", probability="3/5", minimum=".04"
    )
    assert liquidity["available_native_quantity"] == "130"
    assert liquidity.get("modeled_net_ev") is None and not liquidity["eligible"]
    bad = market()
    bad["selections"][0][-1]["quantity"] = "500"
    with pytest.raises(ValueError, match="prophetx_duplicate_level_conflict"):
        bindings(event(), bad, receipt(), at=AT)


@pytest.mark.parametrize("outcome", [None, "", "none", False, 0])
def test_affiliate_rejects_unqualified_outcome_id(outcome):
    invalid = market()
    invalid["selections"][0][0]["outcome_id"] = outcome
    with pytest.raises(ValueError, match="prophetx_outcome_identity_unverified"):
        bindings(event(), invalid, receipt(), at=AT)


def test_affiliate_rejects_conflicting_strike_history_and_accepts_an_alternate():
    different_outcome = market()
    different_outcome["selections"][0][-1]["outcome_id"] = 11
    with pytest.raises(ValueError, match="prophetx_strike_identity_conflict"):
        bindings(event(), different_outcome, receipt(), at=AT)

    changed_side = market()
    changed_side["selections"][0].append(
        dict(
            changed_side["selections"][0][0],
            competitor_id=14,
            strike_id="b" * 32,
            strike="3.5",
        )
    )
    with pytest.raises(ValueError, match="prophetx_outcome_identity_conflict"):
        bindings(event(), changed_side, receipt(), at=AT)

    alternate = market()
    alternate["selections"][0].append(
        dict(alternate["selections"][0][0], strike_id="b" * 32, strike="-4.5")
    )
    assert len(bindings(event(), alternate, receipt(), at=AT)) == 2

    (original,) = bindings(event(), market(), receipt(), at=AT).values()
    corrected = market()
    for selection in corrected["selections"][0]:
        selection["outcome_id"] = 11
    later = AT + timedelta(seconds=1)
    (incoming,) = bindings(event(), corrected, receipt(later), at=later).values()
    assert incoming["contract"]["contract_id"] == original["contract"]["contract_id"]
    assert adopt(original, incoming) is original


def test_affiliate_refreshes_expired_pregame_evidence_and_keeps_stale_status_unqualified():
    now = [AT]
    event_age = [0]
    paths = []

    def serve(request):
        path = request.url.path.removeprefix("/partner")
        paths.append((path, tuple(request.url.params.items())))
        if path == TOURNAMENTS:
            data = {"tournaments": [{"id": 132, "name": "NBA"}]}
        elif path == EVENTS:
            data = {
                "sport_events": [
                    dict(
                        event_id=101,
                        tournament_id=132,
                        status="scheduled",
                        scheduled=START,
                        competitors=[
                            dict(side="home", name="New York Knicks", id=43),
                            dict(side="away", name="Miami Heat", id=14),
                        ],
                    )
                ]
            }
        else:
            assert path == MARKETS
            data = {"101": [market()]}
        headers = {
            "Date": format_datetime(now[0], usegmt=True),
            "Age": str(event_age[0] if path == EVENTS else 0),
        }
        return httpx.Response(200, json={"data": data}, headers=headers)

    async def run():
        client = MarketData(
            {"api_key": "fixture-key", "tournaments": {"NBA": "132"}},
            now=lambda: now[0],
            allowed=lambda: True,
            http=httpx.AsyncClient(transport=httpx.MockTransport(serve)),
        )
        try:
            books, reason = await client.discover(
                "NBA",
                AT,
                stamp(START) + timedelta(seconds=1),
                AT + timedelta(seconds=3),
            )
            assert reason is None
            (book,) = books.values()
            assert book["contract"]["phase"] == "pregame"
            assert sum(path == EVENTS for path, _ in paths) == 1

            now[0] += timedelta(seconds=31)
            event_age[0] = 90
            books, reason = await client.refresh({"101"}, now[0] + timedelta(seconds=3))
            assert reason is None
            (unverified,) = books.values()
            assert unverified["contract"]["phase"] == "unverified"
            assert unverified["levels"] == book["levels"]
            decision = evaluate_at_stake(
                unverified, at=now[0], stake="25", probability="3/5", minimum=".04"
            )
            assert (
                not decision["eligible"]
                and decision["reason"] == "depth_pregame_phase_unverified"
            )
            assert (EVENTS, (("event_ids", "101"),)) in paths

            now[0] += timedelta(seconds=1)
            event_age[0] = 0
            qualified, reason = await client.refresh(
                {"101"}, now[0] + timedelta(seconds=3)
            )
            assert reason is None
            (qualified,) = qualified.values()
            assert qualified["contract"]["phase"] == "pregame"
        finally:
            await client.close()

    asyncio.run(run())


def test_affiliate_read_only_throttle_holds_and_recovers_without_trading_routes():
    clock = [AT]
    calls = []

    async def run():
        def serve(req):
            calls.append(req.url.path)
            assert req.method == "GET" and req.headers["Authorization"] == "fixture-key"
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "60"})
            return httpx.Response(200, json={"data": {"tournaments": []}})

        client = MarketData(
            {"api_key": "fixture-key", "tournaments": {"NBA": "1"}},
            now=lambda: clock[0],
            allowed=lambda: True,
            http=httpx.AsyncClient(transport=httpx.MockTransport(serve)),
        )
        try:
            result = await client.get(
                "/affiliate/get_tournaments", {}, clock[0] + timedelta(seconds=3)
            )
            assert result[2] == "throttled"
            assert "fixture-key" not in str(result)
            assert (
                await client.get(
                    "/affiliate/get_tournaments", {}, clock[0] + timedelta(seconds=3)
                )
            )[2] == "deferred"
            assert len(calls) == 1
            clock[0] += timedelta(seconds=61)
            assert (
                await client.get(
                    "/affiliate/get_tournaments", {}, clock[0] + timedelta(seconds=3)
                )
            )[2] is None
            with pytest.raises(ValueError, match="read_only"):
                await client.get(
                    "/v4/mm/submit_order", {}, clock[0] + timedelta(seconds=3)
                )
        finally:
            await client.close()

    asyncio.run(run())
    assert len(calls) == 2


def test_affiliate_tournament_must_be_exact_once_and_batch_covers_shorter_consumer():
    async def run():
        requested = asyncio.Event()
        release = asyncio.Event()
        paths = []
        now = [AT]

        async def serve(req):
            paths.append(req.url.path)
            if req.url.path.endswith("get_tournaments"):
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "tournaments": [
                                {"id": 132, "name": "NBA"},
                                {"id": 31, "name": "NFL"},
                            ]
                        }
                    },
                )
            requested.set()
            await release.wait()
            return httpx.Response(200, json={"data": {"101": [], "102": []}})

        client = MarketData(
            {"api_key": "fixture-key", "tournaments": {"NBA": "132", "NHL": "31"}},
            now=lambda: now[0],
            allowed=lambda: True,
            http=httpx.AsyncClient(transport=httpx.MockTransport(serve)),
        )
        cutoff = AT + timedelta(seconds=3)
        try:
            proof, reason = await client.qualify_tournament("NBA", cutoff)
            assert reason is None
            assert proof["tournament_id"] == "132"
            assert await client.qualify_tournament("NHL", cutoff) == (
                None,
                "prophetx_tournament_league_conflict",
            )
            assert await client.qualify_tournament("NCAAB", cutoff) == (
                None,
                "prophetx_tournament_mapping_required",
            )
            client.config["tournaments"].update(NFL="31", NCAAB="031")
            assert await client.qualify_tournament("NCAAB", cutoff) == (
                None,
                "prophetx_tournament_league_conflict",
            )
            assert await client.qualify_tournament("NFL", cutoff) == (
                None,
                "prophetx_tournament_mapping_duplicate",
            )
            client.config["tournaments"].update(NCAAB="678", NCAAF="0678")
            assert await client.qualify_tournament("NCAAB", cutoff) == (
                None,
                "prophetx_tournament_mapping_duplicate",
            )
            first = asyncio.create_task(
                client.get(MARKETS, {"event_ids": "101,102"}, cutoff)
            )
            await requested.wait()
            shorter = asyncio.create_task(
                client.get(MARKETS, {"event_ids": "101"}, AT + timedelta(seconds=1))
            )
            await asyncio.sleep(0)
            now[0] += timedelta(seconds=2)
            release.set()
            data, book_proof, reason = await first
            assert reason is None and set(data) == {"101", "102"}
            assert book_proof["requested_at"] == AT.isoformat()
            assert book_proof["received_at"] == now[0].isoformat()
            assert await shorter == (None, None, "deferred")
            assert paths == ["/partner/affiliate/get_tournaments", "/partner" + MARKETS]
        finally:
            await client.close()

    asyncio.run(run())
