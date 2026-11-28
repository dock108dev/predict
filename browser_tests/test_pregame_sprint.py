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
            await page.goto("https://predict.fixture/opportunities")
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


@pytest.mark.parametrize("game_reply_before_back", [True, False])
def test_touch_back_to_game_preserves_context_and_unavailable_ev(
    game_reply_before_back,
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
            await expect(page.locator("dialog[open]")).to_have_count(0)
            search = page.get_by_role("searchbox", name="Search teams")
            await search.tap()
            await page.keyboard.type("Milwaukee")
            await expect(search).to_have_value("Milwaukee")
            await page.locator("#board-advanced > summary").tap()
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
            # A slow game response may replace the main-line opener while its
            # comparison is shown. Only one dialog stays open; Back must restore
            # the exact line in the game, rather than its duplicate on the board.
            initial_line = page.locator("#game-content .line-open").first
            await initial_line.evaluate(
                "button=>button.addEventListener('pointerdown',event=>event.preventDefault())"
            )
            await initial_line.tap()
            await expect(page.locator("#comparison")).to_be_visible()
            await expect(page.locator("#game-lines")).not_to_be_visible()
            await expect(page.locator("dialog[open]")).to_have_count(1)
            if game_reply_before_back:
                game_release.set()
                await expect(page.locator("#game-content .line-open")).to_have_count(20)
            await page.locator("#comparison-back").tap()
            await expect(page.locator("#comparison")).not_to_be_visible()
            await expect(page.locator("#game-lines")).to_be_visible()
            await expect(page.locator("dialog[open]")).to_have_count(1)
            await expect(
                page.locator('#game-content .line-open[data-quote-id="quote-0"]')
            ).to_be_focused()
            if not game_reply_before_back:
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
            back = page.locator("#comparison-back")
            comparison_y = (await back.bounding_box())["y"]
            await expect(page.locator("#game-lines")).not_to_be_visible()
            await expect(page.locator("dialog[open]")).to_have_count(1)
            await page.get_by_text("Fee and calculation details", exact=True).tap()
            await swipe(session, 180, 700, 250)
            await page.wait_for_function(
                "document.querySelector('#comparison-content').scrollTop > 0"
            )
            assert abs((await back.bounding_box())["y"] - comparison_y) < 1
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
            await back.tap()
            await expect(page.locator("#comparison")).not_to_be_visible()
            await expect(page.locator("#game-lines")).to_be_visible()
            await expect(page.locator("dialog[open]")).to_have_count(1)
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
                    closeHit:(() => {const b=document.querySelector('#comparison-back').getBoundingClientRect();
                        return document.elementsFromPoint(b.x+b.width/2,b.y+b.height/2)
                            .map(e=>({id:e.id,tag:e.tagName,className:e.className}));})()
                })""")
                print("Back-to-game diagnostic: " + json.dumps(diagnostic))
                directory = Path(
                    os.getenv(
                        "PREDICT_CI_REPORT_ROOT", ".local/usability-sprint/linux-focus"
                    )
                )
                directory.mkdir(parents=True, exist_ok=True)
                stem = "back-to-game-" + str(game_reply_before_back)
                (directory / (stem + ".json")).write_text(
                    json.dumps(diagnostic, indent=2)
                )
                await page.screenshot(path=str(directory / (stem + ".png")))
                raise
            # If Linux consumed native click synthesis during the fling, model
            # the delayed compatibility click after the game returns. It must
            # not close the restored game or steal the selected line's focus.
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


def test_touch_calculation_close_after_scroll_preserves_comparison_and_return():
    """One touch dismisses scrolled math without dismissing its comparison."""
    from playwright.async_api import async_playwright, expect

    async def journey():
        selected = offer()
        selected["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
        selected["fee"]["cashflows"]["win"]["gross_receipt_usd"] = "220"
        selected["fee"]["evidence"] = dict(
            database_fee_rule=dict(formula="prophetx_commission", rate="0.02")
        )
        selected["fee"]["rounding_trace"] = [
            dict(raw="2.4", entry="0", settlement="2.4")
        ]
        errors = []

        async def serve(route):
            url = urlparse(route.request.url)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if route.request.method != "GET":
                errors.append("Unexpected mutating request")
                await route.abort()
            elif url.path.endswith("/updates"):
                await route.fulfill(json=dict(changed=False))
            elif url.path == "/api/pregame":
                packet = dict(
                    cursor="one",
                    rows=[selected],
                    total=1,
                    refresh_at=selected["kickoff"],
                    sportsbooks=[],
                )
                if q.get("view") == "games":
                    packet.update(
                        rows=[],
                        games=[
                            dict(
                                game_key=selected["game_key"],
                                game=selected["game"],
                                league=selected["league"],
                                kickoff=selected["kickoff"],
                                rows=[selected],
                            )
                        ],
                    )
                await route.fulfill(json=packet)
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
                viewport=dict(width=320, height=568),
                is_mobile=True,
                has_touch=True,
                device_scale_factor=1,
            )
            page = await context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.route("**/*", serve)
            await page.goto("https://predict.fixture/browse-odds")
            game = page.locator(".game-open")
            await game.tap()
            line = page.locator("#game-content .line-open")
            await expect(line).to_be_visible()
            await line.tap()
            await expect(page.locator(".comparison-status")).to_contain_text("complete")
            await expect(page.locator("#game-lines")).not_to_be_visible()
            trigger = (
                page.locator(".exchange-prices tbody td")
                .nth(2)
                .locator(".math-trigger")
            )
            await trigger.tap()
            popover = page.locator(".math-popover:popover-open")
            await expect(popover).to_be_visible()
            await expect(popover).to_contain_text("Commission = rate × gross profit")
            await expect(popover).to_contain_text("$2.40")
            body = popover.locator(".math-body")
            assert await body.evaluate("e=>e.scrollHeight>e.clientHeight")
            close = page.get_by_role("button", name="Close calculation", exact=True)
            close_y = (await close.bounding_box())["y"]
            box = await body.bounding_box()
            x, start_y, end_y = (
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] - 20,
                box["y"] + 20,
            )
            session = await context.new_cdp_session(page)
            await session.send(
                "Input.dispatchTouchEvent",
                dict(type="touchStart", touchPoints=[dict(x=x, y=start_y)]),
            )
            for index in range(1, 9):
                await session.send(
                    "Input.dispatchTouchEvent",
                    dict(
                        type="touchMove",
                        touchPoints=[
                            dict(x=x, y=start_y + (end_y - start_y) * index / 8)
                        ],
                    ),
                )
            await session.send(
                "Input.dispatchTouchEvent", dict(type="touchEnd", touchPoints=[])
            )
            await page.wait_for_function(
                "document.querySelector('.math-popover:popover-open .math-body').scrollTop>0"
            )
            assert abs((await close.bounding_box())["y"] - close_y) < 1
            # Tap during kinetic scrolling: do not wait for a settled fling or
            # issue a second tap that would conceal a missing synthesized click.
            await close.tap()
            await expect(page.locator(".math-popover:popover-open")).to_have_count(0)
            await expect(page.locator("#comparison")).to_be_visible()
            await expect(page.locator("dialog[open]")).to_have_count(1)
            await expect(trigger).to_be_focused()
            await page.locator("#comparison-back").tap()
            await expect(page.locator("#game-lines")).to_be_visible()
            await expect(line).to_be_focused()
            await line.tap()
            await expect(page.locator("#comparison")).to_be_visible()
            await page.get_by_role("button", name="Close comparison", exact=True).tap()
            await expect(page.locator("dialog[open]")).to_have_count(0)
            await expect(game).to_be_focused()
            assert not errors, errors
            await browser.close()

    asyncio.run(journey())


@pytest.mark.parametrize("width", [1440, 390, 320])
def test_research_amounts_never_save_and_navigation_restores_scope(width, tmp_path):
    from playwright.sync_api import sync_playwright, expect

    row = offer()
    row["game"] = (
        "A very long visiting college basketball team at Another very long home university"
    )
    row["raw"].update(
        posted_decimal="2.2", after_fee_decimal="2.176", expected_profit_usd="8.8"
    )
    writes, queries, research = [], [], []

    def serve(route):
        url = urlparse(route.request.url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/pregame/research":
            body = route.request.post_data_json
            research.append(body)
            if body["amount"] == "26":
                route.fulfill(
                    status=409, json={"error": "The retained price inputs changed."}
                )
                return
            modeled = deepcopy(row)
            amount = body["amount"]
            # Authored outputs: UI must consume supplied model results, not scale $100.
            modeled["fee"].update(
                committed_usd=amount,
                entry_usd="0.13",
                purchase_usd=str(float(amount) - 0.13),
            )
            modeled["fee"]["cashflows"]["win"]["net_receipt_usd"] = (
                "53.47" if amount == "25" else "1088.17"
            )
            modeled["raw"]["expected_profit_usd"] = (
                "1.73" if amount == "25" else "44.09"
            )
            route.fulfill(
                json=dict(result=modeled, research_only=True, journal_writes=0)
            )
        elif url.path.startswith("/api/bet-journal"):
            writes.append(route.request.post_data_json)
            route.fulfill(status=503, json={})
        elif url.path.endswith("/updates"):
            route.fulfill(json={"changed": False})
        elif url.path == "/api/pregame":
            queries.append(q)
            route.fulfill(
                json=dict(
                    cursor="one",
                    rows=[row],
                    total=1,
                    sportsbooks=[],
                    refresh_at=row["kickoff"],
                )
            )
        elif url.path.startswith("/view/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(
                path=ASSETS / ("about.html" if url.path == "/about" else "pregame.html")
            )

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 844})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", serve)
        page.goto("http://predict.fixture/opportunities")
        page.locator(".row-open").click()
        expect(page.locator(".amount-result")).to_contain_text(
            "expected profit of $8.80"
        )
        page.get_by_role("button", name="$25", exact=True).click()
        expect(page.locator(".amount-result")).to_contain_text("$53.47")
        expect(page.locator(".amount-result")).to_contain_text(
            "expected profit of $1.73"
        )
        page.get_by_role("button", name="$500", exact=True).click()
        expect(page.locator(".amount-result")).to_contain_text("$1088.17")
        expect(page.locator(".size-evidence")).to_contain_text("Unknown")
        assert [r["amount"] for r in research] == ["25", "500"]
        assert not writes
        page.get_by_role("spinbutton", name="Illustrative cash budget").fill("26")
        page.get_by_role("button", name="Evaluate amount", exact=True).click()
        expect(page.locator(".amount-research > [role=status]")).to_contain_text(
            "inputs changed"
        )
        expect(page.locator(".amount-result")).to_contain_text("$1088.17")
        expect(page.locator(".comparison-record")).to_contain_text("Recording actions")
        page.get_by_role("button", name="Record bet", exact=True).click()
        expect(page.locator(".comparison-record")).to_contain_text("save unconfirmed")
        assert len(writes) == 1
        assert writes[0]["snapshot"]["fee"]["committed_usd"] == "100"
        expect(page.get_by_role("button", name="Retry record bet")).to_be_enabled()
        assert page.evaluate("document.documentElement.scrollWidth===innerWidth")
        page.screenshot(path=str(tmp_path / f"research-{width}.png"))
        page.get_by_role("button", name="Close comparison", exact=True).click()
        page.get_by_role("searchbox", name="Search teams").fill("Orlando")
        page.locator("#board-advanced > summary").click()
        page.locator("#family").select_option("total")
        page.locator("#max-age").fill("15")
        expect(page.locator("#active-filters")).to_contain_text("15m")
        page.goto("http://predict.fixture/about")
        page.go_back()
        expect(page.get_by_role("searchbox", name="Search teams")).to_have_value(
            "Orlando"
        )
        expect(page.locator("#family")).to_have_value("total")
        expect(page.locator("#max-age")).to_have_value("15")
        expect(page.locator("#active-filters")).to_contain_text("15m")
        expect(page.locator("#request-status")).to_have_text("")
        assert queries[-1]["family"] == "total"
        assert queries[-1]["max_age_minutes"] == "15"
        page.get_by_role("link", name="Browse odds", exact=True).click()
        page.get_by_role("searchbox", name="Search teams").fill("Bucks")
        page.get_by_role("link", name="Opportunities", exact=True).click()
        expect(page.get_by_role("searchbox", name="Search teams")).to_have_value(
            "Orlando"
        )
        page.get_by_role("link", name="Browse odds", exact=True).click()
        expect(page.get_by_role("searchbox", name="Search teams")).to_have_value(
            "Bucks"
        )
        assert not errors, errors
        browser.close()


def test_historical_comparison_from_game_checks_current_alternatives():
    from playwright.sync_api import sync_playwright, expect

    row = offer()
    row["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
    state = {"retired": False, "revision": "one"}
    game_reads = []

    def serve(route):
        url = urlparse(route.request.url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path.endswith("/updates"):
            route.fulfill(json=dict(changed=q.get("after") != state["revision"]))
        elif url.path == "/api/pregame":
            rows = [] if q.get("bet_id") and state["retired"] else [row]
            if q.get("view") == "game":
                game_reads.append(q)
            packet = dict(
                cursor=state["revision"],
                rows=rows,
                total=len(rows),
                refresh_at=row["kickoff"],
            )
            if q.get("view") == "games":
                packet.update(
                    rows=[],
                    games=[
                        {
                            **{
                                k: row[k]
                                for k in ("game_key", "game", "league", "kickoff")
                            },
                            "rows": [row],
                        }
                    ],
                )
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
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.route("**/*", serve)
        page.goto("http://predict.fixture/browse-odds")
        page.locator(".game-open").click()
        page.locator("#game-content .line-open").first.click()
        state.update(retired=True, revision="two")
        expect(page.locator(".comparison-status")).to_contain_text("Historical")
        expect(page.locator(".selected-summary")).to_contain_text("+120")
        page.get_by_role(
            "button", name="Check current alternatives", exact=True
        ).click()
        expect(page.locator("#game-lines")).to_be_visible()
        expect(page.locator("#game-content .line-open")).to_be_visible()
        expect(page.locator("#game-content")).not_to_contain_text("Loading alternate")
        assert len(game_reads) == 2
        browser.close()


def test_modeled_dashboard_ev_and_payout_use_each_calculations_fee_assumption():
    from playwright.sync_api import expect, sync_playwright

    row = offer()
    saved = dict(status="full_size", intended_stake_usd="100", modeled_stake_usd="99.96",
        modeled_win_profit_usd="1566.04", modeled_net_ev=".5421", modeled_fee_usd="0",
        fee_is_upper_bound=True, fee_mode={"enabled": False}, valid_until=row["kickoff"])
    row.update(venue="kalshi", market_id="fixture-market", pull_id="native:saved", revision="saved",
        native_source={"provider": "kalshi"}, eligible_until=row["kickoff"],
        calculation={"status": "positive", "net_ev_percent": "54.21"}, liquidity=saved)
    row["posted"]["native_price_probability"] = "0.06"
    book = dict(event_id="fixture-event", market_id="fixture-market", outcome_id="fixture-side",
                valid_until=row["kickoff"])
    detail = dict(liquidity=saved, native_offer=dict(row=row, book=book, game_link={},
                                                   fee_mode={"enabled": False}))
    zero_fee_preview = dict(saved, intended_stake_usd="25", modeled_stake_usd="25",
        modeled_win_profit_usd="12.50", modeled_net_ev=".12", fee_is_upper_bound=False,
        fee_mode={"enabled": True})
    unavailable_preview = dict(status="unknown", intended_stake_usd="500",
        reason="fee_schedule_unverified", fee_mode={"enabled": True})

    def serve(route):
        path = urlparse(route.request.url).path
        if path == "/":
            route.fulfill(path=ASSETS / "dashboard.html")
        elif path == "/api/research/dashboard":
            route.fulfill(json=dict(rows=[row], total=1, source_authority="official_venue_apis"))
        elif path == "/api/research/market":
            route.fulfill(json=detail)
        elif path == "/api/research/dashboard-liquidity":
            amount = route.request.post_data_json["amount"]
            result = {"25": zero_fee_preview, "500": unavailable_preview}[amount]
            route.fulfill(json=dict(result={"liquidity": result}, provider_requests=0))
        elif (asset := ASSETS / Path(path).name).is_file():
            route.fulfill(path=asset)
        else:
            route.fulfill(status=404)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.route("**/*", serve)
        page.goto("http://predict.fixture/")
        expect(page.get_by_role("table").get_by_text("+54.21% at $99.96 · Fees excluded", exact=False)).to_be_visible()
        page.get_by_role("button", name="View evidence", exact=False).click()
        result = page.get_by_role("dialog").locator(".amount-result")
        expect(result.get_by_text("$1,566.04 · Fees excluded", exact=True)).to_be_visible()
        expect(result.get_by_text("+54.21% · Fees excluded", exact=True)).to_be_visible()
        expect(result.get_by_text("Up to $0.00", exact=True)).to_have_count(0)
        page.get_by_role("button", name="$25", exact=True).click()
        expect(result.get_by_text("$12.50 · Fees included", exact=True)).to_be_visible()
        expect(result.get_by_text("+12.00% · Fees included", exact=True)).to_be_visible()
        expect(result.get_by_text("$0.00", exact=True)).to_be_visible()
        expect(result.get_by_text("Fees excluded", exact=False)).to_have_count(0)
        page.get_by_role("button", name="$500", exact=True).click()
        expect(result.get_by_text("The applicable fee schedule is unverified.")).to_be_visible()
        expect(result.get_by_text("Fees included", exact=False)).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        browser.close()
