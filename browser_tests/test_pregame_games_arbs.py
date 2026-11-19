"""Game-first and two-sided normal flows at desktop and phone widths."""

from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pytest
from browser_tests.test_pregame_current import ASSETS, offer


@pytest.mark.parametrize("width", [1440, 768, 390, 320])
def test_grouped_game_expand_compare_and_focus(width, tmp_path):
    from playwright.sync_api import sync_playwright, expect

    main = offer()
    main["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
    alt = deepcopy(main)
    alt.update(id="alternate", bet_id="alternate-bet", main=False)
    alt["selection"]["signed_line"] = "-2.5"
    other = deepcopy(main)
    other.update(id="opposite", bet_id="opposite-bet", family="total")
    other["selection"] = dict(predicate="under", signed_line="220.5")
    requests = []
    errors = []
    state = {"failed": False}

    def serve(route):
        url = urlparse(route.request.url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path.startswith("/api/pregame"):
            requests.append(q)
            if url.path.endswith("/updates"):
                route.fulfill(json={"changed": False})
                return
            if state["failed"]:
                route.fulfill(status=503, json={})
                return
            packet = dict(
                cursor="one",
                rows=[main, other, alt] if q.get("view") == "game" else [main],
                total=3 if q.get("view") == "game" else 1,
                refresh_at=main["kickoff"],
            )
            if q.get("view") == "games":
                packet.update(
                    rows=[],
                    games=[
                        dict(
                            game_key=main["game_key"],
                            game=main["game"],
                            league=main["league"],
                            kickoff=main["kickoff"],
                            rows=[main, other],
                        )
                    ],
                )
            if q.get("bet_id"):
                packet["sportsbooks"] = [
                    dict(
                        book="draftkings",
                        posted_odds="-105",
                        source_at=main["times"]["source_at"],
                    )
                ]
            route.fulfill(json=packet)
        else:
            route.fulfill(
                path=ASSETS
                / (
                    Path(url.path).name
                    if url.path.startswith("/view/")
                    else "pregame.html"
                )
            )

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", serve)
        page.goto("http://predict.fixture/browse-odds")
        expect(page.locator(".game-card")).to_have_count(1)
        expect(page.locator("#count")).to_have_text("1 game")
        expect(page.locator("#sort-order")).to_have_text("Game start time ↑")
        expect(page.locator("#results .game-bet")).to_have_count(2)
        expect(page.locator("#results")).to_contain_text("45.45%")
        expect(page.locator("#results")).not_to_contain_text("-2.5")
        expect(page.locator("#alternates-field")).to_be_hidden()
        assert requests[0]["view"] == "games"
        assert all(
            "Main" not in text
            for text in page.locator("#results .line-venue").all_text_contents()
        )
        page.locator("#results .math-trigger").first.click()
        expect(page.locator(".math-popover:popover-open")).to_be_visible()
        expect(page.locator("#game-lines")).not_to_be_visible()
        page.keyboard.press("Escape")
        page.locator(".game-open").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#game-content .game-bet")).to_have_count(3)
        expect(page.locator("#game-content")).to_contain_text("Alternate")
        page.locator("#game-content .line-open").first.click()
        expect(page.locator("#comparison")).to_be_visible()
        expect(page.locator(".sportsbook-prices")).to_contain_text("DraftKings")
        expect(page.locator("#game-lines")).not_to_be_visible()
        expect(page.locator("dialog[open]")).to_have_count(1)
        page.locator("#comparison-back").click()
        expect(page.locator("#comparison")).not_to_be_visible()
        expect(page.locator("dialog[open]")).to_have_count(1)
        expect(page.locator("#game-content .line-open").first).to_be_focused()
        # Close comparison exits to the board directly, without reopening a game.
        page.locator("#game-content .line-open").first.click()
        page.get_by_role("button", name="Close comparison").click()
        expect(page.locator("dialog[open]")).to_have_count(0)
        expect(page.locator(".game-open")).to_be_focused()
        assert page.evaluate("document.documentElement.scrollWidth===innerWidth")
        if width == 390:
            page.evaluate("document.documentElement.style.fontSize='125%'")
            assert page.evaluate("document.documentElement.scrollWidth===innerWidth")
        state["failed"] = True
        page.locator("#refresh").click()
        expect(page.locator("#error")).to_contain_text("preserved")
        expect(page.locator(".game-card")).to_have_count(1)
        assert not errors
        page.screenshot(path=str(tmp_path / f"games-{width}.png"))
        browser.close()


@pytest.mark.parametrize("width", [1440, 768, 390, 320])
@pytest.mark.parametrize("second_venue", ["draftkings", "kalshi"])
def test_after_fee_arbs_show_both_legs_without_sportsbook_ev(
    width, second_venue, tmp_path
):
    from playwright.sync_api import sync_playwright, expect

    a = offer()
    a.update(venue="polymarket_us", side="home")
    a["raw"] = dict(posted_decimal="2.2", after_fee_decimal="2.176")
    a.pop("reference")
    b = deepcopy(a)
    b.update(
        id="book", venue=second_venue, side="away", selection_label="Milwaukee Bucks"
    )
    b["selection"]["signed_line"] = "1.5"
    pair = dict(
        id="pair",
        game=a["game"],
        league=a["league"],
        kickoff=a["kickoff"],
        family="spread",
        category="market_book" if second_venue == "draftkings" else "market_market",
        legs=[a, b],
        committed_usd="100",
        minimum_profit_usd="5",
        display_return="+5.00%",
        profits_usd=["5", "6"],
        receipts_usd=["105", "106"],
        unused_usd="0",
        settlement_note="Decisive completed game only.",
        liquidity_note="Instant-fill maximum unknown.",
    )
    errors = []
    queries = []
    state = {"failed": False}

    def serve(route):
        url = urlparse(route.request.url)
        if url.path.endswith("/updates"):
            route.fulfill(json={"changed": False})
            return
        if url.path == "/api/pregame/arbs":
            queries.append(parse_qs(url.query))
            if state["failed"]:
                route.fulfill(status=503, json={})
                return
            route.fulfill(
                json=dict(rows=[pair], total=1, cursor="one", refresh_at=a["kickoff"])
            )
            return
        route.fulfill(
            path=ASSETS
            / (
                Path(url.path).name
                if url.path.startswith("/view/")
                else "pregame-arbs.html"
            )
        )

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", serve)
        page.goto("http://predict.fixture/arbs")
        expect(page.locator(".arb-card")).to_have_count(1)
        expect(page.locator(".arb-card")).to_contain_text("Polymarket US")
        expect(page.locator(".arb-card")).to_contain_text(
            "DraftKings" if second_venue == "draftkings" else "Kalshi"
        )
        expect(page.locator(".arb-card")).to_contain_text("Instant size unknown")
        # Posted and net values sit beside each other on both legs, including native contract prices.
        for prices in page.locator("#results .arb-prices").all():
            posted, after = prices.locator(".arb-price-column").all()
            assert abs(posted.bounding_box()["y"] - after.bounding_box()["y"]) < 1
            assert posted.bounding_box()["x"] < after.bounding_box()["x"]
        expect(page.locator("#results")).not_to_contain_text("Fair")
        expect(page.locator("#results")).not_to_contain_text("EV")
        expect(page.locator("#results")).not_to_contain_text("Score")
        page.locator("#results .math-trigger").first.click()
        expect(page.locator(".math-popover:popover-open")).to_be_visible()
        expect(page.locator("#arb-details")).not_to_be_visible()
        page.keyboard.press("Escape")
        page.locator(".arb-open").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#arb-details")).to_be_visible()
        expect(page.locator(".arb-states tbody tr")).to_have_count(2)
        expect(page.locator("#arb-details")).to_contain_text("$5.00")
        page.get_by_text("How this comparison is calculated", exact=True).click()
        expect(page.locator("#arb-details")).to_contain_text(
            "No sportsbook fair probability or EV is used"
        )
        page.get_by_role("button", name="Close arbitrage comparison").click()
        expect(page.locator(".arb-open")).to_be_focused()
        page.locator("#board-advanced > summary").click()
        page.locator("#category").select_option("market_book")
        with page.expect_response(lambda r: "/api/pregame/arbs?" in r.url):
            page.locator("#refresh").click()
        assert any(q.get("category") == ["market_book"] for q in queries)
        assert page.evaluate("document.documentElement.scrollWidth===innerWidth")
        state["failed"] = True
        page.locator("#refresh").click()
        expect(page.locator("#error")).to_contain_text("preserved")
        expect(page.locator(".arb-card")).to_have_count(1)
        assert not errors
        page.screenshot(path=str(tmp_path / f"arbs-{width}.png"))
        browser.close()


def test_arb_filters_survive_delayed_reads_empty_results_and_poll_failures():
    import asyncio
    from playwright.async_api import async_playwright, expect

    async def journey():
        a = offer()
        a.update(venue="novig", side="home")
        a.pop("reference")
        a["raw"] = {"posted_decimal": "2.2", "after_fee_decimal": "2.176"}
        b = deepcopy(a)
        b.update(id="book", venue="draftkings", side="away")
        pair = dict(
            id="pair",
            game=a["game"],
            league=a["league"],
            kickoff=a["kickoff"],
            family="spread",
            category="market_book",
            legs=[a, b],
            display_return="+5.00%",
        )
        held, released = asyncio.Event(), asyncio.Event()
        state = {"updates_failed": False}

        async def serve(route):
            url = urlparse(route.request.url)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path.endswith("/updates"):
                await route.fulfill(status=503, json={}) if state[
                    "updates_failed"
                ] else await route.fulfill(json={"changed": False})
            elif url.path == "/api/pregame/arbs":
                # Older data omits the selected book: rendering it would clear the filter.
                if q.get("venue") == "kalshi":
                    held.set()
                    await released.wait()
                    await route.fulfill(
                        json=dict(
                            rows=[], total=0, cursor="old", sportsbooks=["fanduel"]
                        )
                    )
                    return
                empty = q.get("search") == "missing"
                await route.fulfill(
                    json=dict(
                        rows=[] if empty else [pair],
                        total=0 if empty else 1,
                        cursor="one",
                        sportsbooks=[] if empty else ["fanduel", "draftkings"],
                    )
                )
            else:
                await route.fulfill(
                    path=ASSETS
                    / (
                        Path(url.path).name
                        if url.path.startswith("/view/")
                        else "pregame-arbs.html"
                    )
                )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 390, "height": 900})
            await page.route("**/*", serve)
            await page.goto("http://predict.fixture/arbs")
            await expect(page.locator(".arb-card")).to_have_count(1)
            await expect(
                page.locator(".arb-card .arb-price-column").first
            ).to_contain_text("45.45%")
            await page.locator("#board-advanced > summary").click()
            async with page.expect_response(lambda r: "/api/pregame/arbs?" in r.url):
                await page.locator("#book").select_option("draftkings")
            await page.locator("#venue").select_option("kalshi")
            await asyncio.wait_for(held.wait(), 5)
            await page.locator("#venue").select_option("novig")
            released.set()
            await expect(page.locator(".arb-card")).to_have_count(1)
            await expect(page.locator("#book")).to_have_value("draftkings")
            await expect(page.locator("#venue")).to_have_value("novig")
            await page.get_by_role("searchbox", name="Search teams").fill("missing")
            await expect(page.locator(".arb-card")).to_have_count(0)
            await expect(page.locator("#book")).to_have_value("draftkings")
            state["updates_failed"] = True
            await expect(page.locator("#error")).to_contain_text("Update check failed")
            state["updates_failed"] = False
            await expect(page.locator("#error")).to_be_hidden()
            await browser.close()

    asyncio.run(journey())
