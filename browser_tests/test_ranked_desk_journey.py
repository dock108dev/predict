"""Exercise the complete ranked and Browse Odds journey."""

from copy import deepcopy
from fractions import Fraction
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import pytest
from app.dashboard.trade_desk import public_group

from browser_tests.ranked_fixtures import (
    ASSETS,
    BASE,
    DENVER,
    DETROIT,
    START,
    WASHINGTON,
    ranked_fixtures,
)


@pytest.mark.parametrize("width", [1440, 390])
def test_ranked_and_browse_journey(width, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    ev, detroit, denver, _, arbs = ranked_fixtures()
    original_quote = detroit["offers"][0]
    original_quote["desk_quote_key"] = "a" * 64
    latest_quote = dict(
        original_quote,
        id="new-desk-projection",
        odds=dict(american="-400", decimal="1.25"),
        cost_per_normal_claim="0.80",
        price_revision="pmus-detroit-latest-price",
        economic_revision="pmus-detroit-latest-economics",
        evidence_result_id="pmus-detroit-latest-capture",
    )
    revised_quote = dict(
        latest_quote,
        trade_fee=dict(latest_quote["trade_fee"], trade_fee_usd="0.02"),
        economic_revision="pmus-detroit-revised-economics",
        evidence_result_id="pmus-detroit-revised-capture",
    )
    detroit_evidence = {
        offer["evidence_result_id"]: offer
        for offer in (original_quote, latest_quote, revised_quote)
    }
    errors = []
    provider_requests = []
    unavailable = False
    browse_failure = False
    hide_game_prices = False
    current_quote = latest_quote
    change_during_adoption = False
    withdraw_selection = False
    different_line = False
    pair_replacement = "original"
    pair_reads = 0
    sized_pairs = []
    inspected = []

    def respond(route):
        nonlocal current_quote, pair_reads
        url = urlparse(route.request.url)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.hostname != "predict.fixture":
            provider_requests.append(url.hostname)
            route.abort()
            return
        if url.path in ("/", "/ev", "/arbs", "/browse-odds", "/game"):
            route.fulfill(
                path=ASSETS / "desk.html", headers={"Referrer-Policy": "no-referrer"}
            )
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/comparison-current":
            assert "last_known" not in query
            if (
                browse_failure
                and query.get("browse_odds") == "1"
                and not query.get("game_key")
            ):
                route.fulfill(status=503)
                return
            if query.get("view") == "arbs":
                assert "stake" not in query
                rows = deepcopy(arbs)
                if query.get("game_key") == WASHINGTON:
                    pair_reads += 1
                    if pair_replacement == "stable" or (
                        pair_replacement == "changes" and pair_reads % 2 == 0
                    ):
                        pair = rows[1]["pairs"][0]
                        pair["retail_payoff"]["minimum_net_profit_usd"] = "-4.99"
                        pair["retail_payoff"]["funding_usd"] = "103.99"
                        pair["retail_payoff"]["legs"][1]["at_fill_usd"] = "2.29"
                        pair["score"] = str(
                            100 * Fraction("-4.99") / Fraction("103.99")
                        )
                        for state in pair["retail_payoff"]["states"].values():
                            state["net_profit_usd"] = "-4.99"
            elif query.get("browse_odds") == "1":
                rows = deepcopy(
                    denver if query.get("game_key") == DENVER else [detroit, *denver]
                )
                if query.get("lines") == "main":
                    rows = [
                        row for row in rows if not row["offers"][0].get("alternate")
                    ]
            elif unavailable:
                rows = []
            else:
                assert query.get("lines") in ("main", "all")
                rows = ev
            if query.get("game_key"):
                rows = [row for row in rows if row["game_key"] == query["game_key"]]
                if hide_game_prices:
                    rows = []
            ranked = sum(row["score"] is not None for row in rows)
            if query.get("positive"):
                rows = [
                    row
                    for row in rows
                    if row["score"] is not None and Fraction(row["score"]) > 0
                ]
            if query.get("summary") == "1":
                rows = [public_group(row, query.get("basis")) for row in rows]
            route.fulfill(
                json=dict(
                    state="ready",
                    rows=rows,
                    games=[
                        dict(
                            game_key=DENVER, title=DENVER, start_at=START, league="NBA"
                        )
                    ],
                    total=len(rows),
                    matched_offer_count=12,
                    matched_outcome_count=4,
                    ranked_group_count=ranked,
                    ranking_stake="100" if query.get("view") == "arbs" else None,
                    publication=dict(
                        current_prices=12,
                        read_at="2026-11-13T00:00:00Z",
                        published_at="2026-11-12T23:59:54Z",
                        sources={
                            "sportsgameodds": {
                                "state": "held",
                                "reason_code": "sgo_charge_unresolved",
                            }
                        }
                        if unavailable
                        else {},
                    ),
                    calculation_reason="The sportsbook reference source is on hold.",
                )
            )
        elif url.path == "/api/comparison-current/selection":
            row = current_quote
            if different_line:
                row = dict(
                    row,
                    market=dict(row["market"], line="206.5"),
                    selection=dict(row["selection"], signed_line="206.5"),
                )
            route.fulfill(json={"row": None if withdraw_selection else row})
        elif url.path == "/api/comparison-current/lease":
            route.fulfill(json={"lease_id": "fixture"})
        elif url.path == "/api/comparison-snapshot/details":
            if "stake" in query:
                pair = deepcopy(arbs[1]["pairs"][0])
                assert query == dict(
                    id=pair["id"],
                    result_id=pair["evidence_result_id"],
                    lease_id="fixture",
                    stake="150",
                )
                sized_pairs.append(pair["id"])
                pair["inspection"]["funding_usd"] = "150"
                pair["retail_payoff"]["sizing"]["requested_stake_usd"] = "150"
                route.fulfill(json=pair)
                return
            inspected.append(query["id"])
            for arb in arbs:
                pair = arb["pairs"][0]
                if pair["id"] == query["id"]:
                    route.fulfill(json=dict(pair, offers=arb["offers"]))
                    return
            cost = "0.81"
            if query["id"] in (original_quote["id"], latest_quote["id"]):
                selected = detroit_evidence[query["result_id"]]
                cost = selected["cost_per_normal_claim"]
                # Publish the fee change after the adoption request has found exact evidence.
                if change_during_adoption and selected is latest_quote:
                    current_quote = revised_quote
            else:
                selected = next(
                    offer
                    for row in [*ev, detroit, *denver]
                    for offer in row["offers"]
                    if offer["id"] == query["id"]
                )
            route.fulfill(
                json=dict(
                    captured_at=START,
                    row=selected,
                    desk_offer=selected,
                    inspection=dict(
                        identity={},
                        original=dict(value=cost, units="usd"),
                        source={},
                        before_fees=dict(cost_usd=cost),
                        fair_reference=dict(available=False),
                    ),
                )
            )
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        with browser.new_context(
            viewport={"width": width, "height": 850}, service_workers="block"
        ) as context:
            context.route("**/*", respond)
            if width == 390:
                context.add_init_script(
                    "Object.defineProperty(window, 'navigation', {value: undefined})"
                )
            tab = context.new_page()
            tab.clock.set_fixed_time("2026-11-13T00:00:00Z")
            tab.on("pageerror", lambda error: errors.append(str(error)))
            tab.goto(BASE)
            expect(tab.get_by_role("heading", name="Opportunities")).to_be_visible()
            tab.get_by_label("Calculation basis").select_option("reviewed")
            cards = tab.locator(".opportunity-card")
            expect(cards).to_have_count(2)
            expect(cards.first).to_contain_text("+3.26%")
            market = cards.first.locator(".compact-ev-market")
            prices = market.get_by_role("group", name="Prediction market offers")
            expect(
                market.get_by_role("heading", name="Denver to cover +2.5")
            ).to_be_visible()
            expect(prices.get_by_role("button")).to_have_text(
                [
                    "Polymarket US+117.39+3.26%",
                    "Kalshi-108.33-8.21%",
                ]
            )
            assert all(
                price.bounding_box()["height"] >= 44
                for price in prices.get_by_role("button").all()
            )
            books = cards.first.get_by_role(
                "group", name="Fair odds and sportsbook quotes"
            )
            expect(books).to_contain_text("Fair odds +102")
            expect(books.locator(":scope > span")).to_have_text(
                [
                    "Fair odds +102",
                    "DraftKings -108Used for fair odds",
                    "FanDuel -111",
                    "Caesars -115Last known",
                ]
            )
            assert market.bounding_box()["y"] < books.bounding_box()["y"]
            if width == 1440:
                title_box = market.get_by_role("heading").bounding_box()
                prices_box = prices.bounding_box()
                assert (
                    abs(
                        (title_box["y"] + title_box["height"] / 2)
                        - (prices_box["y"] + prices_box["height"] / 2)
                    )
                    < 7
                )
            expect(cards.first).not_to_contain_text("Current")
            expect(cards.first).not_to_contain_text("Comparison sportsbook")
            expect(cards.first).not_to_contain_text("-112")
            expect(cards.last).to_contain_text("-3.00%")
            assert not inspected
            cards.first.get_by_role(
                "button", name="View trade details: Polymarket US", exact=False
            ).press("Enter")
            fair = tab.get_by_role(
                "dialog", name="Polymarket US · Denver to cover +2.5"
            )
            expect(fair.get_by_text("-112", exact=False).first).to_be_visible()
            math = fair.get_by_role("heading", name="Before-fee cashflows")
            expect(math).to_be_hidden()
            fair.get_by_text("Calculations and settlement", exact=True).click()
            expect(
                fair.get_by_role("heading", name="Before-fee cashflows")
            ).to_be_visible()
            assert inspected == ["pmus-denver"]
            tab.keyboard.press("Escape")
            expect(
                tab.get_by_text(
                    "Open a quote to see its source and receipt times.", exact=True
                )
            ).to_have_count(0)
            expect(tab.get_by_role("link", name="Arbitrage")).to_be_visible()
            tab.screenshot(path=tmp_path / f"ranked-ev-{width}.png")
            tab.get_by_role("checkbox", name="Positive only").check()
            expect(cards).to_have_count(1)
            tab.get_by_role("checkbox", name="Positive only").uncheck()
            expect(cards).to_have_count(2)

            cards.first.get_by_role("link", name="Open game ↗").press("Enter")
            expect(tab.get_by_role("heading", name=DENVER)).to_be_visible()
            expect(tab.get_by_label("Calculation basis")).to_have_value("reviewed")
            expect(tab.get_by_label("Alternate lines")).not_to_be_checked()
            expect(tab.locator(".odds-matrix tbody tr")).to_have_count(2)
            tab.get_by_label("Alternate lines").check()
            expect(tab.locator(".odds-matrix tbody tr")).to_have_count(5)
            expect(tab.locator(".odds-matrix .matrix-outcome")).to_have_text(
                [
                    "Denver to cover -2.5",
                    "Minnesota to cover +2.5",
                    "Denver to cover +2.5",
                    "Minnesota to cover -2.5",
                    "Denver to cover +3.5",
                ]
            )
            expect(tab.get_by_role("columnheader", name="Novig")).to_be_visible()
            expect(
                tab.get_by_role("columnheader", name="Polymarket US")
            ).to_be_visible()
            expect(
                tab.get_by_role("columnheader", name="EV", exact=True)
            ).to_have_count(0)
            expect(
                tab.locator(".odds-matrix thead tr").first.locator("th")
            ).to_have_text(
                ["Outcome", "Kalshi", "Polymarket US", "Novig", "ProphetX", "Fair odds"]
            )
            fair = (
                tab.get_by_role("row")
                .filter(has_text="Denver to cover +2.5")
                .locator(".matrix-fair-odds")
            )
            expect(fair).to_contain_text("+102")
            expect(fair).to_contain_text("DraftKings")
            expect(tab.get_by_role("columnheader", name="DraftKings")).to_have_count(0)
            popout = tab.get_by_role("region", name="Sportsbook prices")
            expect(popout).to_have_count(0)
            tab.get_by_role(
                "button", name="Same-line sportsbook quotes for Denver to cover +2.5"
            ).click()
            expect(popout).to_be_visible()
            expect(popout).to_contain_text("-108")
            tab.keyboard.press("Escape")
            expect(popout).to_have_count(0)
            for key, value in (("pmus-denver", "+3.26%"), ("kalshi-denver", "-8.21%")):
                price = tab.locator(f'[data-offer-id="{key}"]')
                expect(price).to_contain_text(f"{value} EV")
                expect(price).to_have_accessible_name(
                    re.compile(re.escape(f"{value} Verified after-fee EV"))
                )
            expect(tab.locator('[data-offer-id="kalshi-minnesota"]')).to_contain_text(
                "EV unavailable"
            )
            if width == 390:
                matrix = tab.locator(".odds-scroll")
                assert matrix.evaluate("el => el.scrollWidth > el.clientWidth")
                # Opening the sportsbook popout can already scroll to the last column.
                matrix.evaluate("el => { el.scrollLeft = el.scrollWidth; }")
                first_columns = tab.get_by_role(
                    "button", name="Scroll to the first odds column"
                )
                expect(first_columns).to_be_visible()
                first_columns.click()
                tab.wait_for_function(
                    "document.querySelector('.odds-scroll').scrollLeft === 0"
                )
                more_columns = tab.locator(".matrix-scroll-cue")
                expect(more_columns).to_be_visible()
                more_columns.click()
                tab.wait_for_function(
                    "document.querySelector('.odds-scroll').scrollLeft > 0"
                )
                assert tab.get_by_role(
                    "rowheader", name="Denver to cover +2.5", exact=False
                ).evaluate(
                    "(el) => Math.abs(el.getBoundingClientRect().left - el.closest('.odds-scroll').getBoundingClientRect().left) < 2"
                )
            tab.get_by_label("Alternate lines").uncheck()
            expect(tab.locator(".odds-matrix tbody tr")).to_have_count(2)
            hide_game_prices = True
            tab.get_by_role("button", name="Refresh list").click()
            expect(
                tab.get_by_role("heading", name="No prices available for this matchup")
            ).to_be_visible()
            expect(tab.get_by_role("heading", name=DENVER)).to_be_visible()
            expect(tab.get_by_label("Last-known prices")).not_to_be_visible()
            expect(tab.locator('[data-offer-id="novig-denver"]')).to_have_count(0)
            hide_game_prices = False
            tab.get_by_role("navigation", name="Current view").get_by_role(
                "link", name="Back"
            ).click()
            expect(cards).to_have_count(2)
            expect(tab.get_by_label("Calculation basis")).to_have_value("reviewed")

            unavailable = True
            tab.get_by_role("button", name="Refresh list").click()
            expect(
                tab.get_by_role("heading", name="No EV estimates available")
            ).to_be_visible()
            expect(
                tab.get_by_text("The sportsbook reference source is on hold.")
            ).to_be_visible()
            expect(tab.locator("#notice")).to_contain_text(
                "SportsGameOdds updates are on hold pending provider reconciliation"
            )
            expect(tab.locator("#results .odds-card")).to_have_count(0)
            expect(cards).to_have_count(0)
            tab.get_by_role("link", name="Find my game ↗").click()
            expect(tab.get_by_role("heading", name=DETROIT)).to_be_visible()
            quote_button = tab.locator('[data-offer-id="pmus-detroit"]')
            expect(quote_button).not_to_contain_text("20s ago")
            assert quote_button.get_attribute("title") is None
            matrices = tab.locator(".odds-matrix")
            expect(matrices).to_have_count(2)
            positions = [
                matrix.get_by_role("columnheader", name="Kalshi").bounding_box()["x"]
                for matrix in matrices.all()
            ]
            assert abs(positions[0] - positions[1]) < 1
            tab.get_by_role("button", name="Filters", exact=True).click()
            tab.get_by_role("dialog", name="Filter results").get_by_label(
                "Winner"
            ).uncheck()
            tab.get_by_role("dialog", name="Filter results").get_by_label(
                "Total"
            ).uncheck()
            tab.get_by_role("button", name="Done").click()
            expect(
                tab.get_by_role("button", name="Clear Spread filter")
            ).to_be_visible()
            tab.locator(".odds-card").filter(has_text=DENVER).get_by_role(
                "link", name="Open game ↗"
            ).click()
            expect(
                tab.get_by_role("button", name="Spreads", exact=True)
            ).to_have_attribute("aria-pressed", "true")
            browse_failure = True
            tab.get_by_role("navigation", name="Current view").get_by_role(
                "link", name="Back"
            ).click()
            expect(
                tab.get_by_role("button", name="Clear Spread filter")
            ).to_be_visible()
            expect(tab.locator("#notice")).to_contain_text("Prices could not be loaded")
            expect(tab.locator(".odds-card")).to_have_count(0)
            browse_failure = False
            tab.get_by_role("button", name="Retry").press("Enter")
            expect(tab.locator("#notice")).not_to_contain_text(
                "Prices could not be loaded"
            )
            restored_game = (
                tab.locator(".odds-card")
                .filter(has_text=DENVER)
                .get_by_role("link", name="Open game ↗")
            )
            expect(restored_game).to_be_focused()
            restored_game.click()
            tab.go_back()
            expect(
                tab.get_by_role("button", name="Clear Spread filter")
            ).to_be_visible()
            tab.get_by_role("button", name="Clear Spread filter").click()
            tab.locator('[data-calculation-id="pmus-denver"]').press("Enter")
            expect(tab.locator("#trade [data-inspection-ev]")).to_have_text(
                "Current at inspection"
            )
            withdraw_selection = True
            with tab.expect_response(
                lambda response: (
                    urlparse(response.url).path == "/api/comparison-current/selection"
                )
            ):
                tab.evaluate("document.getElementById('refresh-list').click()")
            expect(tab.locator("#trade [data-inspection-price]")).to_have_text(
                "Price at inspection"
            )
            expect(tab.locator("#trade [data-inspection-ev]")).to_have_text(
                "EV at inspection"
            )
            withdraw_selection = False
            tab.keyboard.press("Escape")
            expect(tab.locator("#trade")).to_be_hidden()
            quote_button.press("Enter")
            drawer = tab.get_by_role("dialog", name="Polymarket US · Over 205.5")
            expect(drawer.get_by_text("$0.81 per $1 payout")).to_be_visible()
            drawer.get_by_text("Quote times", exact=True).click()
            times = drawer.locator("details", has_text="Quote times").locator(
                ".inspection-facts"
            )
            expect(times.locator("dt")).to_have_text(
                [
                    "Original source update",
                    "Book confirmation",
                    "Collector receipt",
                    "Price capture",
                    "Board publication",
                ]
            )
            expect(times.locator("dd")).to_have_text(
                [
                    "2026-11-12T23:59:40Z",
                    "2026-11-12T23:59:52Z",
                    "2026-11-12T23:59:53Z",
                    START,
                    "2026-11-12T23:59:54Z",
                ]
            )
            expect(
                drawer.locator(".inspection-tiles").get_by_text("$0.01", exact=True)
            ).to_be_visible()
            expect(
                drawer.get_by_text(
                    "The sportsbook jurisdiction and applicable market rules are unverified."
                )
            ).to_be_visible()

            different_line = True
            drawer.get_by_role("button", name="Use latest prices").click()
            expect(drawer.get_by_role("status")).to_contain_text(
                "The latest price is for a different exact outcome."
            )
            expect(drawer.get_by_text("$0.81 per $1 payout")).to_be_visible()
            different_line = False
            change_during_adoption = True
            passive_read = tab.evaluate(
                """async id => {
                    const query = new URLSearchParams({id, layout: 'desk', basis: 'reviewed', phase: 'pregame'});
                    const response = await fetch(`/api/comparison-current/selection?${query}`);
                    return (await response.json()).row.evidence_result_id;
                }""",
                original_quote["id"],
            )
            assert passive_read == latest_quote["evidence_result_id"]
            drawer.get_by_role("button", name="Use latest prices").click()
            expect(
                drawer.get_by_text(
                    "The price, fee, or reference changed during adoption.", exact=False
                )
            ).to_be_visible()
            expect(drawer.get_by_text("$0.81 per $1 payout")).to_be_visible()
            drawer.get_by_role("button", name="Use latest prices").click()
            expect(drawer.get_by_text("$0.80 per $1 payout")).to_be_visible()
            expect(
                drawer.locator(".inspection-tiles").get_by_text("$0.02", exact=True)
            ).to_be_visible()
            drawer.get_by_role("button", name="Use latest prices").click()
            expect(drawer.get_by_role("status")).to_contain_text("No newer quote")
            tab.keyboard.press("Escape")
            expect(quote_button).to_be_focused()

            tab.goto(BASE + "/arbs")
            expect(cards).to_have_count(2)
            expect(cards.last.locator(".arb-card-legs li")).to_have_count(2)
            expect(cards.last.locator(".arb-payoff")).to_contain_text("$104.03")
            expect(cards.last.locator(".arb-payoff")).to_contain_text(
                "Worst profit/loss"
            )
            expect(cards.first).to_contain_text("+0.89%")
            expect(cards.last).to_contain_text("-4.84%")
            tab.screenshot(path=tmp_path / f"ranked-arb-{width}.png")
            cards.last.get_by_role("button", name="View payoff calculation ↗").press(
                "Enter"
            )
            payoff = tab.get_by_role("dialog", name="Pair payoff")
            expect(payoff.get_by_text("$104.03", exact=True)).to_be_visible()
            assert "arb-washington" in inspected
            expect(
                payoff.locator(".inspection-payoffs").get_by_text(
                    "Tie or exact-line settlement"
                )
            ).to_be_visible()
            expect(payoff.locator(".inspection-payoffs tr").last).to_contain_text(
                "-$5.03"
            )
            payoff.get_by_text(
                "Exact prices, settlement terms and fee rounding", exact=True
            ).click()
            expect(payoff.get_by_text("Payout by leg")).to_be_visible()
            expect(
                payoff.get_by_text("Kalshi $49.50 · Polymarket US $49.50")
            ).to_be_visible()
            payoff.get_by_text("Sized fee rounding").first.click()
            expect(payoff.get_by_text("Raw fee").first).to_be_visible()
            pair_replacement = "changes"
            pair_reads = 0
            payoff.get_by_role("button", name="Use latest prices").click()
            expect(
                payoff.get_by_text("The pair changed during adoption.", exact=False)
            ).to_be_visible()
            expect(payoff.locator(".inspection-payoffs tr").last).to_contain_text(
                "-$5.03"
            )
            pair_replacement = "stable"
            payoff.get_by_role("button", name="Use latest prices").click()
            expect(payoff.locator(".inspection-payoffs tr").last).to_contain_text(
                "-$4.99"
            )
            payoff.get_by_label("Total stake before fees ($)").fill("150")
            payoff.get_by_role("button", name="Size this pair").click()
            applied_stake = payoff.get_by_text("Stake used before fees", exact=True)
            expect(applied_stake.locator("xpath=following-sibling::dd")).to_have_text(
                "$150.00"
            )
            assert sized_pairs == [arbs[1]["pairs"][0]["id"]]
            expect(cards.first).to_contain_text("+0.89%")
            assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")
        browser.close()
    assert not errors, errors
    assert not provider_requests, provider_requests
