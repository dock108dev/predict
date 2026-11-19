"""Recovery, truthful completeness, and touch inspection on the shipped pregame UI."""

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from browser_tests.test_pregame_current import ASSETS, offer


def test_comparison_completeness_failure_deadline_and_superseded_filters():
    from playwright.async_api import async_playwright, expect

    async def journey():
        selected = offer()
        selected["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
        state = {"comparison": "held", "slow": False}
        comparison_wait, comparison_release = asyncio.Event(), asyncio.Event()
        slow_wait, slow_release = asyncio.Event(), asyncio.Event()
        errors = []

        async def serve(route):
            url = urlparse(route.request.url)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path.endswith("/updates"):
                await route.fulfill(json={"changed": False})
            elif url.path == "/api/pregame":
                if q.get("bet_id") and state["comparison"] == "held":
                    comparison_wait.set()
                    await comparison_release.wait()
                if q.get("bet_id") and state["comparison"] == "failed":
                    await route.fulfill(status=503, json={})
                    return
                if q.get("search") == "slow":
                    slow_wait.set()
                    await slow_release.wait()
                row = deepcopy(selected)
                if q.get("search") == "new":
                    row["selection_label"] = "New exact selection"
                await route.fulfill(
                    json={
                        "cursor": "one",
                        "rows": [row],
                        "total": 1,
                        "refresh_at": row["kickoff"],
                        "sportsbooks": [
                            {
                                "book": "draftkings",
                                "posted_odds": "-105",
                                "source_at": row["times"]["source_at"],
                            }
                        ]
                        if state["comparison"] == "loaded"
                        else [],
                    }
                )
            else:
                await route.fulfill(
                    path=ASSETS
                    / (
                        Path(url.path).name
                        if url.path.startswith("/view/")
                        else "pregame.html"
                    ),
                    headers={
                        "Content-Security-Policy": "default-src 'self'; connect-src 'self'"
                    },
                )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.route("**/*", serve)
            await page.goto("https://predict.fixture/")
            await expect(page.locator(".row-open")).to_be_visible()
            await page.locator(".ticket").evaluate("e=>e.dataset.retained='yes'")
            async with page.expect_response(lambda r: "/api/pregame?" in r.url):
                await page.locator("#refresh").click()
            await expect(page.locator("#refresh")).to_be_enabled()
            await expect(page.locator(".ticket")).to_have_attribute(
                "data-retained", "yes"
            )
            await page.locator(".row-open").click()
            await asyncio.wait_for(comparison_wait.wait(), 3)
            await expect(page.locator("#comparison")).to_be_visible()
            await expect(page.locator(".comparison-status")).to_contain_text(
                "incomplete"
            )
            await expect(page.locator("#comparison-content")).not_to_contain_text(
                "No other sportsbooks"
            )
            await expect(page.locator(".exchange-prices")).to_contain_text("ProphetX")
            state["comparison"] = "failed"
            comparison_release.set()
            await expect(page.locator(".comparison-status")).to_contain_text(
                "Comparison failed"
            )
            await expect(page.locator(".exchange-prices")).to_contain_text("ProphetX")
            state["comparison"] = "loaded"
            await page.get_by_role("button", name="Retry comparison").click()
            await expect(page.locator(".sportsbook-prices")).to_contain_text(
                "DraftKings"
            )
            await expect(page.locator(".comparison-status")).to_contain_text(
                "complete for this stored snapshot"
            )
            await page.get_by_role("button", name="Close comparison").click()
            await page.get_by_role("searchbox", name="Search teams").fill("slow")
            await asyncio.wait_for(slow_wait.wait(), 3)
            await page.get_by_role("searchbox", name="Search teams").fill("new")
            # A pending older read cannot hold up the new filter's results.
            await expect(page.locator(".row-open")).to_contain_text(
                "New exact selection"
            )
            slow_release.set()
            await expect(page.locator(".row-open")).to_contain_text(
                "New exact selection"
            )
            # Exercise the real request deadline using a controlled browser clock.
            await page.clock.install()
            slow_release.clear()
            slow_wait.clear()
            await page.get_by_role("searchbox", name="Search teams").fill("slow")
            await page.clock.fast_forward(200)
            await asyncio.wait_for(slow_wait.wait(), 3)
            await page.clock.fast_forward(12050)
            await expect(page.locator("#error")).to_contain_text("timed out")
            await expect(page.locator("#error")).to_contain_text("preserved")
            await expect(page.locator("#refresh")).to_be_enabled()
            slow_release.set()
            await page.get_by_role("searchbox", name="Search teams").fill("new")
            await page.clock.fast_forward(200)
            await expect(page.locator("#error")).to_be_hidden()
            assert not errors, errors
            await browser.close()

    asyncio.run(journey())


@pytest.mark.parametrize("game_reply_before_close", [True, False])
def test_touch_nested_dialogs_preserve_context_and_unavailable_ev(
    game_reply_before_close,
):
    from playwright.async_api import async_playwright, expect

    async def swipe(session, x, start_y, end_y):
        await session.send(
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": [{"x": x, "y": start_y}]},
        )
        for index in range(1, 9):
            await session.send(
                "Input.dispatchTouchEvent",
                {
                    "type": "touchMove",
                    "touchPoints": [
                        {"x": x, "y": start_y + (end_y - start_y) * index / 8}
                    ],
                },
            )
        await session.send(
            "Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}
        )

    async def journey():
        base = offer()
        base["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
        rows = []
        for i in range(20):
            row = deepcopy(base)
            row.update(id=f"quote-{i}", bet_id=f"line-{i}", main=i == 0)
            row["selection"]["signed_line"] = str(-i - 0.5)
            rows.append(row)
        unavailable = rows[-1]
        unavailable.update(
            reference=None, ev_unavailable_reason="exact_reference_pair_missing"
        )
        unavailable["raw"].update(
            net_ev=None, fair_decimal=None, opportunity_score=None
        )
        unavailable["display"].update(
            net_ev=None, fair_odds=None, opportunity_score=None
        )
        games = [
            dict(
                game_key=f"game-{i}",
                game=base["game"] + f" {i}",
                league=base["league"],
                kickoff=base["kickoff"],
                rows=[rows[0]],
            )
            for i in range(12)
        ]
        errors = []
        game_wait, game_release = asyncio.Event(), asyncio.Event()
        game_state = {"failed_once": False}

        async def serve(route):
            url = urlparse(route.request.url)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path.endswith("/updates"):
                await route.fulfill(json={"changed": False})
            elif url.path == "/api/pregame":
                if q.get("view") == "game":
                    if not game_state["failed_once"]:
                        game_state["failed_once"] = True
                        await route.fulfill(status=503, json={})
                        return
                    game_wait.set()
                    await game_release.wait()
                selected = (
                    [next((r for r in rows if r["bet_id"] == q["bet_id"]), base)]
                    if q.get("bet_id")
                    else rows
                )
                await route.fulfill(
                    json=dict(
                        cursor="one",
                        rows=[] if q.get("view") == "games" else selected,
                        games=games,
                        total=12 if q.get("view") == "games" else len(selected),
                        refresh_at=base["kickoff"],
                        sportsbooks=[],
                    )
                )
            else:
                await route.fulfill(
                    path=ASSETS
                    / (
                        Path(url.path).name
                        if url.path.startswith("/view/")
                        else "pregame.html"
                    ),
                    headers={
                        "Content-Security-Policy": "default-src 'self'; connect-src 'self'"
                    },
                )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            context = await browser.new_context(
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                device_scale_factor=2,
            )
            page = await context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.route("**/*", serve)
            await page.goto("https://predict.fixture/browse-odds")
            # The first exact pick is directly comparable without opening all lines.
            await page.locator("#results .line-open").first.tap()
            await expect(page.locator("#comparison")).to_be_visible()
            await page.get_by_role("button", name="Close comparison").tap()
            search = page.get_by_role("searchbox", name="Search teams")
            await search.tap()
            await page.keyboard.type("Milwaukee")
            await expect(search).to_have_value("Milwaukee")
            async with page.expect_response(
                lambda r: "/api/pregame?" in r.url and "league=NBA" in r.url
            ):
                await page.locator("#league").select_option("NBA")
            await expect(page.locator("#refresh")).to_be_enabled()
            await page.locator(".game-open").nth(8).scroll_into_view_if_needed()
            before_page = await page.evaluate("scrollY")
            assert before_page > 0
            # Some touch platforms dispatch a tap without focusing its button.
            # Prevent only native focus; the real pointer click must still open it.
            await (
                page.locator(".game-open")
                .nth(8)
                .evaluate(
                    "button=>button.addEventListener('pointerdown',event=>event.preventDefault())"
                )
            )
            await page.locator(".game-open").nth(8).tap()
            await expect(page.locator("#game-content")).to_contain_text(
                "Alternate lines could not be loaded. Main lines are preserved."
            )
            await page.get_by_role("button", name="Retry", exact=True).tap()
            await asyncio.wait_for(game_wait.wait(), 3)
            await expect(page.locator("#game-content .line-open")).to_have_count(1)
            # A slow game response replaces the main-line opener behind its quote.
            # The same quote also exists on the inert main page; return to the
            # replacement inside the open game dialog, preserving that context.
            initial_line = page.locator("#game-content .line-open").first
            await initial_line.evaluate(
                "button=>button.addEventListener('pointerdown',event=>event.preventDefault())"
            )
            await initial_line.tap()
            await expect(page.locator("#comparison")).to_be_visible()
            if game_reply_before_close:
                game_release.set()
                await expect(page.locator("#game-content .line-open")).to_have_count(20)
            await page.get_by_role("button", name="Close comparison").tap()
            await expect(
                page.locator('#game-content .line-open[data-quote-id="quote-0"]')
            ).to_be_focused()
            if not game_reply_before_close:
                game_release.set()
                await expect(page.locator("#game-content .line-open")).to_have_count(20)
                await expect(
                    page.locator('#game-content .line-open[data-quote-id="quote-0"]')
                ).to_be_focused()
            close = page.get_by_role("button", name="Close game lines")
            close_y = (await close.bounding_box())["y"]
            session = await context.new_cdp_session(page)
            await swipe(session, 180, 700, 250)
            await page.wait_for_function(
                "document.querySelector('#game-content').scrollTop > 0"
            )
            assert abs((await close.bounding_box())["y"] - close_y) < 1
            # Inspect the retained price lacking a usable reference probability.
            line = page.locator('#game-content .line-open[data-quote-id="quote-19"]')
            await line.scroll_into_view_if_needed()
            parent_scroll = await page.locator("#game-content").evaluate(
                "e=>e.scrollTop"
            )
            await line.evaluate(
                "button=>button.addEventListener('pointerdown',event=>event.preventDefault())"
            )
            await line.tap()
            await expect(page.locator("#comparison")).to_be_visible()
            await expect(page.locator("#comparison-content")).to_contain_text(
                "EV unavailable"
            )
            await expect(page.locator("#comparison-content")).to_contain_text(
                "exact reference pair missing"
            )
            close_comparison = page.get_by_role("button", name="Close comparison")
            comparison_y = (await close_comparison.bounding_box())["y"]
            await page.get_by_text("Fee and calculation details", exact=True).tap()
            await swipe(session, 180, 700, 250)
            await page.wait_for_function(
                "document.querySelector('#comparison-content').scrollTop > 0"
            )
            assert abs((await close_comparison.bounding_box())["y"] - comparison_y) < 1
            await page.evaluate("""() => {
                window.closeProbe=[];
                for(const type of ['pointerdown','pointerup','click','focusin','close'])
                    document.addEventListener(type,event=>{
                        const target=event.target;
                        window.closeProbe.push({type,time:performance.now(),id:target.id,
                            tag:target.tagName,focusKey:target.dataset?.focusKey,
                            pointerType:event.pointerType,
                            active:document.activeElement?.outerHTML.slice(0,500)});
                    },true);
            }""")
            await close_comparison.tap()
            try:
                await expect(line).to_be_focused()
            except AssertionError:
                diagnostic = await page.evaluate("""() => ({
                    events:window.closeProbe,
                    active:document.activeElement?.outerHTML,
                    dialogs:[...document.querySelectorAll('dialog')].map(e=>({id:e.id,open:e.open})),
                    popovers:[...document.querySelectorAll(':popover-open')].map(e=>e.outerHTML.slice(0,1000)),
                    scrolls:{page:scrollY,game:document.querySelector('#game-content').scrollTop,
                        comparison:document.querySelector('#comparison-content').scrollTop},
                    closeHit:(() => {const b=document.querySelector('#close').getBoundingClientRect();
                        return document.elementsFromPoint(b.x+b.width/2,b.y+b.height/2)
                            .map(e=>({id:e.id,tag:e.tagName,className:e.className}));})()
                })""")
                print("Nested close diagnostic: " + json.dumps(diagnostic))
                directory = Path(
                    os.getenv(
                        "PREDICT_CI_REPORT_ROOT", ".local/usability-sprint/linux-focus"
                    )
                )
                directory.mkdir(parents=True, exist_ok=True)
                stem = "nested-close-" + str(game_reply_before_close)
                (directory / (stem + ".json")).write_text(
                    json.dumps(diagnostic, indent=2)
                )
                await page.screenshot(path=str(directory / (stem + ".png")))
                raise
            # If Linux consumed native click synthesis during the fling, model
            # that touch's delayed compatibility click landing on the parent
            # close control at the same fixed coordinates. It must not close it.
            if not await page.evaluate(
                "()=>window.closeProbe.some(event=>event.type==='click')"
            ):
                await page.locator("#game-close").dispatch_event("click", {"detail": 1})
                await expect(page.locator("#game-lines")).to_be_visible()
                await expect(line).to_be_focused()
            assert (
                abs(
                    await page.locator("#game-content").evaluate("e=>e.scrollTop")
                    - parent_scroll
                )
                < 2
            )
            await close.tap()
            await expect(page.locator(".game-open").nth(8)).to_be_focused()
            await expect(page.locator("body")).not_to_have_css("position", "fixed")
            assert abs(await page.evaluate("scrollY") - before_page) < 2
            await expect(search).to_have_value("Milwaukee")
            await expect(page.locator("#league")).to_have_value("NBA")
            assert not errors, errors
            await browser.close()

    asyncio.run(journey())
