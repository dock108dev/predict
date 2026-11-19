"""Arbitrage request recovery preserves evidence and remains usable on touch devices."""

import asyncio
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_tests.test_pregame_current import ASSETS, offer


def pair_fixture():
    a = offer()
    a.update(venue="novig", side="home")
    a.pop("reference")
    a["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
    b = deepcopy(a)
    b.update(id="book", venue="draftkings", side="away")
    return dict(
        id="pair",
        game=a["game"],
        league=a["league"],
        kickoff=a["kickoff"],
        family="spread",
        category="market_book",
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


def test_arb_deadline_retry_supersession_partial_and_retained_failure():
    from playwright.async_api import async_playwright, expect

    async def journey():
        state = {"mode": "held"}
        requests, held = [], []
        pair = pair_fixture()

        async def serve(route):
            url = urlparse(route.request.url)
            q = parse_qs(url.query)
            if url.path.endswith("/updates"):
                await route.fulfill(json={"changed": False})
            elif url.path == "/api/pregame/arbs":
                requests.append(q)
                if state["mode"] == "held" or q.get("venue") == ["kalshi"]:
                    held.append(route)
                    return
                if state["mode"] == "failed":
                    await route.fulfill(status=503, json={})
                    return
                empty = state["mode"] in ("empty", "excluded")
                await route.fulfill(
                    json=dict(
                        rows=[] if empty else [pair],
                        total=0 if empty else 1,
                        cursor="one",
                        sportsbooks=["draftkings"],
                        partial=state["mode"] == "partial",
                        excluded_pairs=1 if state["mode"] == "excluded" else 0,
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
            page = await browser.new_page()
            await page.clock.install()
            await page.route("**/*", serve)
            await page.goto("http://predict.fixture/arbs")
            await expect(page.locator("#results")).to_have_attribute(
                "data-state", "loading"
            )
            await expect(page.locator('a[href*="dataset=practice"]')).to_have_count(0)
            await page.clock.fast_forward(35001)
            await expect(page.locator("#results")).to_have_attribute(
                "data-state", "failed"
            )
            await expect(page.locator("#error")).to_contain_text("timed out")
            await expect(page.locator("#error")).not_to_contain_text("synthetic")
            # A retry is not queued behind the abandoned request.
            state["mode"] = "empty"
            await page.get_by_role("button", name="Refresh", exact=True).click()
            await expect(page.locator("#results")).to_have_attribute(
                "data-state", "empty"
            )
            state["mode"] = "loaded"
            await page.locator("#refresh").click()
            await expect(page.locator("#results")).to_have_attribute(
                "data-state", "loaded"
            )
            source_before = await page.locator(
                ".arb-leg .quote-evidence"
            ).first.get_attribute("title")
            state["mode"] = "failed"
            await page.locator("#refresh").click()
            await expect(page.locator("#results")).to_have_attribute(
                "data-state", "partial"
            )
            await expect(page.locator(".arb-card")).to_have_count(1)
            await expect(page.locator("#error")).to_contain_text(
                "could not be verified"
            )
            assert (
                await page.locator(".arb-leg .quote-evidence").first.get_attribute(
                    "title"
                )
                == source_before
            )
            state["mode"] = "partial"
            await page.locator("#refresh").click()
            await expect(page.locator("#count")).to_contain_text(
                "Partial comparison results"
            )
            state["mode"] = "excluded"
            await page.locator("#refresh").click()
            await expect(page.locator("#results")).to_have_attribute(
                "data-state", "partial"
            )
            await expect(page.locator("#count")).to_contain_text(
                "1 pair could not be modeled"
            )
            await expect(page.locator("#results")).to_contain_text(
                "No positive pair in the completed comparisons"
            )
            state["mode"] = "loaded"
            await page.locator("#venue").select_option("kalshi")
            await page.wait_for_function(
                "document.querySelector('#results').dataset.state==='loading'"
            )
            await page.clock.run_for(1)
            await page.locator("#venue").select_option("novig")
            await page.clock.run_for(1)
            await expect(page.locator("#results")).to_have_attribute(
                "data-state", "loaded"
            )
            for route in held:
                await route.fulfill(json=dict(rows=[], total=0, cursor="obsolete"))
            await page.clock.run_for(1)
            await expect(page.locator(".arb-card")).to_have_count(1)
            await expect(page.locator("#venue")).to_have_value("novig")
            assert any(q.get("venue") == ["novig"] for q in requests)
            await browser.close()

    asyncio.run(journey())


def test_arb_touch_scroll_stable_close_and_keyboard_filter(tmp_path):
    from playwright.async_api import async_playwright, expect

    async def journey():
        pair = pair_fixture()
        pairs = [dict(pair, id=f"pair-{i}") for i in range(12)]

        async def serve(route):
            url = urlparse(route.request.url)
            if url.path.endswith("/updates"):
                await route.fulfill(json={"changed": False})
            elif url.path.startswith("/api/pregame/arbs"):
                await route.fulfill(json=dict(rows=pairs, total=12, cursor="one"))
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
            context = await browser.new_context(
                viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
            )
            page = await context.new_page()
            await page.route("**/*", serve)
            await page.goto("http://predict.fixture/arbs")
            search = page.get_by_role("searchbox", name="Search teams")
            await search.tap()
            await page.keyboard.type("Orlando")
            await expect(search).to_have_value("Orlando")
            await expect(page.locator("#results")).to_have_attribute(
                "data-state", "loaded"
            )
            await page.locator(".arb-open").nth(3).scroll_into_view_if_needed()
            await page.locator(".arb-open").nth(3).tap()
            await expect(page.locator("#arb-details")).to_be_visible()
            close = page.get_by_role("button", name="Close arbitrage comparison")
            await page.get_by_text(
                "Fees for this modeled allocation", exact=True
            ).first.tap()
            await expect(page.locator("#arb-content")).to_contain_text(
                "Acquisition fee (included upfront)"
            )
            await expect(page.locator("#arb-content")).to_contain_text(
                "Winning additional settlement charge"
            )
            before = await close.bounding_box()
            scroll_before = await page.evaluate("scrollY")
            await page.get_by_text(
                "How this comparison is calculated", exact=True
            ).tap()
            # Touch events exercise the browser's scrolling path rather than changing scrollTop.
            body = await page.locator("#arb-content").bounding_box()
            x, y = body["x"] + body["width"] / 2, body["y"] + body["height"] - 30
            session = await context.new_cdp_session(page)
            await session.send(
                "Input.dispatchTouchEvent",
                {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]},
            )
            for step in range(1, 8):
                await session.send(
                    "Input.dispatchTouchEvent",
                    {
                        "type": "touchMove",
                        "touchPoints": [{"x": x, "y": y - step * 35}],
                    },
                )
            await session.send(
                "Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}
            )
            await expect(close).to_be_visible()
            after = await close.bounding_box()
            assert abs(before["y"] - after["y"]) < 1
            assert await page.locator("#arb-content").evaluate("e=>e.scrollTop") > 0
            assert await page.evaluate("scrollY") == scroll_before
            await close.tap()
            await expect(page.locator(".arb-open").nth(3)).to_be_focused()
            assert await page.evaluate("scrollY") == scroll_before
            await expect(search).to_have_value("Orlando")
            await page.screenshot(path=str(tmp_path / "arbitrage-touch-return.png"))
            await browser.close()

    asyncio.run(journey())
