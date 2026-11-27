import asyncio
from copy import deepcopy
from datetime import timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.collection.native_trading_identity import native_event
from app.collection.native_trading_prophetx import MarketData, bindings
from app.storage.store import encoded, stamp

AT = stamp("2026-11-27T23:50:00Z")


def event():
    return native_event(
        "prophetx",
        "101",
        "NBA",
        "2026-11-28T00:00:00Z",
        dict(home="NBA:NYK", away="NBA:MIA"),
        dict(home="New York Knicks", away="Miami Heat"),
        proof=dict(
            received_at=AT.isoformat(),
            competitors={
                "home": dict(id=43, name="New York Knicks"),
                "away": dict(id=14, name="Miami Heat"),
            },
        ),
    )


def test_affiliate_strike_identity_preserves_units_and_deduplicates_repeated_levels():
    selection = dict(
        outcome_id=10,
        strike_id="native-strike",
        competitor_id=43,
        price=120,
        quantity="110",
        strike="-3.5",
        name="New York Knicks",
    )
    market = dict(
        id=3,
        type="spread",
        sub_type="spread",
        category_name="Game Lines",
        selections=[
            [selection, dict(selection, price=110, quantity="20"), deepcopy(selection)]
        ],
    )
    receipt = dict(
        date=format_datetime(AT, usegmt=True),
        received_at=AT.isoformat(),
        age="0",
        sha256="fixture",
    )
    (book,) = bindings(event(), market, receipt, at=AT).values()
    assert (
        book["native_strike_id"] == "native-strike" and book["native_outcome_id"] == 10
    )
    assert book["quantity_unit"] == "usd_stake"
    assert len(book["levels"]) == 2
    assert [level["quantity"] for level in book["levels"]] == ["110", "20"]
    assert book["_record"]["quote"]["source"]["provider_outcome_id"] == "10"
    assert book["contract"]["signed_line"] == "-7/2"
    assert book["fee"]["reason"] == "prophetx_exact_fee_schedule_unverified"
    assert encoded(book)
    bad = deepcopy(market)
    bad["selections"][0][-1]["quantity"] = "500"
    with pytest.raises(ValueError, match="prophetx_duplicate_level_conflict"):
        bindings(event(), bad, receipt, at=AT)


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
