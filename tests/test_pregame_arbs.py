"""Paired cashflows need exact cents, opposite outcomes and post-fee profit."""

from fractions import Fraction as F
from unittest.mock import patch
import pytest
from app.comparison.pregame_arbs import evaluate, reprice
from app.storage.pregame_arbs import book_entry
from app.storage.store import stamp

AT = stamp("2026-11-18T15:00:00Z")


def entry(venue, side, decimal="2.1", line="-1.5"):
    return dict(
        sportsbook=venue == "fanduel",
        payload=dict(
            id=venue + side,
            venue=venue,
            arb_key="same",
            side=side,
            game_key="game",
            game="Away at Home",
            league="NBA",
            kickoff="2026-11-19T00:00:00Z",
            family="spread",
            selection=dict(participant=side, predicate="cover", signed_line=line),
            fee=dict(entry_usd="0", cashflows={}, evidence={}),
            raw=dict(posted_decimal=decimal, after_fee_decimal=decimal),
            display=dict(posted_odds="+110", after_fees="+110"),
        ),
    )


def test_two_sided_return_uses_exact_cents_and_has_no_probability_dependency():
    left, right = entry("novig", "home"), entry("fanduel", "away", line="1.5")
    row = reprice(right, F(4999, 100), at=AT)
    assert row["fee"]["committed_usd"] == "49.99"
    result = evaluate(left, right, at=AT)
    assert result["display_return"] == "+5.00%"
    assert result["minimum_profit_usd"] == "5"
    assert result["committed_usd"] == "100"
    assert result["category"] == "market_book"
    assert not result["execution_qualified"]
    assert result["instant_fill_max_usd"] is None
    assert all("reference" not in leg for leg in result["legs"])
    assert all("net_ev" not in leg["raw"] for leg in result["legs"])


def test_profitable_before_fees_pair_disappears_if_fees_consume_edge():
    left, right = entry("novig", "home"), entry("prophetx", "away", line="1.5")
    original = reprice

    def with_fee(e, amount, *, at):
        row = original(e, amount, at=at)
        row["fee"]["cashflows"]["win"]["net_receipt_usd"] = str(
            F(row["fee"]["cashflows"]["win"]["net_receipt_usd"]) - amount / F(5)
        )
        return row

    with patch("app.comparison.pregame_arbs.reprice", side_effect=with_fee):
        assert evaluate(left, right, at=AT) is None
    assert evaluate(left, right, at=AT)


@pytest.mark.parametrize(
    "change", [{"venue": "novig"}, {"side": "home"}, {"arb_key": "nearby-line"}]
)
def test_noncomplementary_or_same_venue_is_never_an_arb(change):
    left, right = entry("novig", "home"), entry("fanduel", "away")
    right["payload"].update(change)
    assert evaluate(left, right, at=AT) is None


def test_conflicting_explicit_overtime_scopes_are_not_paired():
    left, right = entry("novig", "home"), entry("fanduel", "away")
    for e, value in [(left, "included"), (right, "excluded")]:
        e["payload"]["scoring_scope"] = {"evidence": [{"overtime": value}]}
    assert evaluate(left, right, at=AT) is None


def test_zero_and_negative_pair_margins_never_qualify():
    for decimal in ("2", "1.9"):
        assert (
            evaluate(
                entry("novig", "home", decimal),
                entry("fanduel", "away", decimal),
                at=AT,
            )
            is None
        )


def test_book_prices_require_exact_event_market_line_availability_and_clock():
    template = entry("novig", "home")
    template["payload"]["sportsbook_event_ids"] = ["event"]
    template["record"] = dict(
        market_identity={"family": "spread"},
        event={
            "home": "home",
            "away": "away",
            "participants": {"Home": "home", "Away": "away"},
        },
        selection=template["payload"]["selection"],
    )
    quote = dict(
        event_id="event",
        venue="fanduel",
        market="spread",
        side="away",
        line="1.5",
        phase="pregame",
        period="game",
        league="NBA",
        available=True,
        provider_available=True,
        starts_at=template["payload"]["kickoff"],
        source_at="2026-11-18T14:00:00Z",
        received_at="2026-11-18T14:01:00Z",
        price_american="-105",
        odd_id="away",
        event_status={},
    )
    result = book_entry(quote, template, at=AT)
    assert result["payload"]["selection"]["participant"] == "away"
    assert result["payload"]["selection_label"] == "Away"
    assert result["payload"]["posted"]["value"] == "-105"
    for change in [
        dict(venue="betfairexchange"),
        dict(venue="unknown"),
        dict(venue="fliff"),
        dict(event_id="different"),
        dict(line="2.5"),
        dict(available=False),
        dict(provider_available=False),
        dict(period="half"),
        dict(partition="three_way"),
        dict(event_status={"started": True}),
        dict(price_american="-90"),
        dict(source_at="2026-11-18T16:00:00Z"),
        dict(starts_at="2026-11-20T00:00:00Z"),
    ]:
        assert book_entry(dict(quote, **change), template, at=AT) is None
    template["record"]["market_identity"]["family"] = "moneyline"
    template["record"]["selection"].pop("signed_line")
    template["record"]["selection"]["predicate"] = "win"
    template["payload"]["family"] = "moneyline"
    assert book_entry(dict(quote, market="moneyline", line=None), template, at=AT)


def test_offer_aliases_order_by_instant_not_timestamp_spelling():
    from app.storage.pregame_arbs import observation_clock

    later = {
        "contract_id": "later",
        "payload": {
            "times": {
                "source_at": "2026-11-18T12:00:00-05:00",
                "received_at": "2026-11-18T17:01:00Z",
            }
        },
    }
    earlier = {
        "contract_id": "earlier",
        "payload": {
            "times": {
                "source_at": "2026-11-18T16:00:00Z",
                "received_at": "2026-11-18T17:01:00Z",
            }
        },
    }
    assert max([earlier, later], key=observation_clock)["contract_id"] == "later"


def test_reprice_memo_preserves_nested_samples_and_binds_evaluation_clock():
    from app.comparison import pregame_arbs as module
    from datetime import timedelta
    from unittest.mock import patch

    row = entry("novig", "home")
    with patch.object(module, "_reprice", wraps=module._reprice) as work:
        first = module.reprice(row, F(50), at=AT)
        first["fee"]["cashflows"]["win"]["net_receipt_usd"] = "0"
        again = module.reprice(row, F(50), at=AT)
        assert again["fee"]["cashflows"]["win"]["net_receipt_usd"] == "105"
        assert work.call_count == 1
        module.reprice(row, F(50), at=AT + timedelta(seconds=1))
        module.reprice(row, F(51), at=AT)
        assert work.call_count == 3


def test_cancelled_arb_read_stops_before_any_sql_or_calculation():
    from app.storage.pregame_arbs import read

    with pytest.raises(TimeoutError, match="arbitrage_read_cancelled"):
        read(None, {}, at=AT, can_continue=lambda: False)


def test_api_deadline_cooperatively_stops_background_pair_work():
    import asyncio
    import threading
    from contextlib import nullcontext
    from types import SimpleNamespace
    from aiohttp.test_utils import make_mocked_request
    from app.collection.activity_mode import DEFAULT_SETTINGS
    from app.dashboard import current_pregame_api as api

    entered = threading.Event()
    stopped = threading.Event()
    statements = []
    db = SimpleNamespace(
        transaction=nullcontext, execute=lambda sql: statements.append(sql)
    )

    def slow_read(db, query, *, can_continue):
        assert query["data_type"] == "monitor"
        assert query["_scope_seconds"] == str(
            DEFAULT_SETTINGS["monitor_horizon_seconds"]
        )
        entered.set()
        while can_continue():
            stopped.wait(0.001)
        stopped.set()
        raise TimeoutError("arbitrage_read_cancelled")

    async def scenario():
        with (
            patch.object(api, "ARBITRAGE_READ_DEADLINE_SECONDS", 0.02),
            patch(
                "app.collection.activity_mode.read_status",
                return_value=dict(
                    mode="monitor",
                    settings=DEFAULT_SETTINGS,
                ),
            ),
            patch("app.storage.pregame_arbs.read", side_effect=slow_read),
        ):
            response = await api.response(
                make_mocked_request("GET", "/api/pregame/arbs"),
                connector=lambda: nullcontext(db),
            )
            assert response.status == 503
            assert b"current_read_timeout" in response.body

    asyncio.run(scenario())
    assert entered.is_set()
    assert stopped.is_set()
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in statements
    assert "SET LOCAL statement_timeout='8s'" in statements
