"""The shipped current-row UI: complete tickets, live inspection, cheap updates and recovery."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


def offer():
    at = datetime.now(timezone.utc)
    clock = at.isoformat()
    kickoff = (at + timedelta(hours=2)).isoformat()
    return dict(
        id="a" * 64,
        bet_id="exact-home-spread",
        game_key="occurrence-1",
        game="Milwaukee Bucks at Orlando Magic",
        league="NBA",
        venue="prophetx",
        kickoff=kickoff,
        family="spread",
        period="full_game",
        selection=dict(participant="NBA:ORL", predicate="cover", signed_line="-1.5"),
        selection_label="Orlando Magic",
        main=True,
        posted=dict(value="+120", units="american_odds"),
        source=dict(provider="sportsgameodds"),
        times=dict(source_at=clock, received_at=clock),
        calculated_at=clock,
        reference=dict(
            book="fanduel",
            selected_outcome="home",
            probability="0.5",
            candidate_probabilities={"fanduel": "0.5", "draftkings": "0.51"},
            fair_decimal_odds="2",
            fair_odds="+100",
            prices=[
                dict(side=side, price_american="-110", source_at=clock)
                for side in ("home", "away")
            ],
        ),
        fee=dict(
            classification="conservative",
            entry_usd="0",
            committed_usd="100",
            cashflows=dict(
                win=dict(total_fee_usd="2.4", net_receipt_usd="217.6"),
                loss=dict(total_fee_usd="0", net_receipt_usd="0"),
            ),
        ),
        raw=dict(net_ev="0.088", opportunity_score="748.299319727891"),
        display=dict(
            posted_odds="+120",
            after_fees="+118",
            fair_odds="+100",
            net_ev="+8.80%",
            opportunity_score="748",
        ),
    )


@pytest.mark.parametrize("width", [1440, 768, 390])
def test_current_pregame_journey(width, tmp_path):
    from playwright.sync_api import sync_playwright, expect

    selected = offer()
    state = dict(revision="one", failed=False, empty=False)
    requests = []
    errors = []

    def serve(route):
        url = urlparse(route.request.url)
        if url.hostname != "predict.fixture" or route.request.method != "GET":
            errors.append("Unexpected external or mutating request")
            route.abort()
            return
        if url.path.startswith("/api/pregame"):
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            requests.append((url.path, query))
            assert not {"unit_usd", "basis", "board_id", "board_cursor"} & query.keys()
            if state["failed"]:
                route.fulfill(status=503, json={"error": "authored_read_failure"})
                return
            data = dict(
                schema="predict-current-pregame-1",
                state="ready",
                cursor=state["revision"],
                rows=[]
                if state["empty"] or query.get("search")
                else [deepcopy(selected)],
                total=0 if state["empty"] or query.get("search") else 1,
                provider_requests=0,
                scheduled_calculations=0,
                refresh_at=selected["kickoff"],
            )
            if query.get("bet_id"):
                data["sportsbooks"] = [
                    dict(
                        book="fanduel",
                        posted_odds="-110",
                        source_at=selected["times"]["source_at"],
                        is_reference=True,
                    ),
                    dict(
                        book="draftkings",
                        posted_odds="-115",
                        source_at=selected["times"]["source_at"],
                    ),
                ]
            if url.path.endswith("/updates"):
                data = dict(
                    cursor=state["revision"],
                    changed=query.get("after") != state["revision"],
                )
            route.fulfill(json=data)
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/about":
            route.fulfill(path=ASSETS / "about.html")
        else:
            route.fulfill(path=ASSETS / "pregame.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=900))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/")
        expect(page.locator(".ticket")).to_have_count(1)
        expect(page.get_by_role("navigation", name="Pages")).to_be_hidden()
        expect(page.locator(".ticket")).to_contain_text("+8.80%")
        expect(page.locator(".fair .reference")).to_contain_text("FanDuel (-110)")
        for label in ("Search teams", "League", "Market", "Venue"):
            expect(page.locator(".filter-label", has_text=label)).to_be_visible()
        for kind in ("after", "fair", "ev", "score"):
            trigger = page.locator(f"#results .{kind} .math-trigger")
            trigger.hover()
            expect(page.locator(".math-popover:popover-open")).to_be_visible()
            page.keyboard.press("Escape")
            trigger.focus()
            expect(page.locator(".math-popover:popover-open")).to_be_visible()
            page.keyboard.press("Escape")
        expect(
            page.locator("select[name=basis],#board-unit,[name=unit_usd]")
        ).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth===innerWidth")
        expect(page.locator(".compare")).to_have_count(0)
        # Blank row space opens comparison, while the math and game link stay separate.
        page.locator(".ticket").click(position={"x": 8, "y": 8})
        expect(page.locator("#comparison")).to_be_visible()
        expect(page.locator(".sportsbook-prices")).to_contain_text("DraftKings")
        expect(page.locator(".sportsbook-prices")).to_contain_text("-115")
        # Every quote figure and its save control fit the comparison at phone width.
        table = page.locator(".exchange-prices")
        expect(table.get_by_role("columnheader")).to_have_count(7)
        if width == 390:
            assert table.evaluate("e => e.scrollWidth <= e.clientWidth")
            bounds = table.bounding_box()
            for cell in table.locator("tbody td").all():
                box = cell.bounding_box()
                assert box["x"] >= bounds["x"] - 1
                assert box["x"] + box["width"] <= bounds["x"] + bounds["width"] + 1
        expect(
            page.get_by_role("button", name="Save ProphetX to My Bets")
        ).to_be_visible()
        page.locator(".exchange-prices .math-trigger").first.focus()
        expect(page.locator(".math-popover:popover-open")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#comparison")).to_be_visible()
        page.get_by_text("Fee and calculation details", exact=True).click()
        expect(page.locator("#comparison")).to_contain_text("$2.40")
        expect(page.locator("#comparison")).to_contain_text("$0.00")
        page.get_by_text("Fee and calculation details", exact=True).focus()
        selected["display"]["net_ev"] = "+9.00%"
        state["revision"] = "two"
        expect(page.locator("#results")).to_contain_text("+9.00%")
        expect(page.locator("#comparison")).to_contain_text("+9.00%")
        expect(
            page.get_by_text("Fee and calculation details", exact=True)
        ).to_be_focused()
        page.get_by_role("button", name="Close comparison").click()
        expect(page.get_by_role("button", name="Compare prices")).to_be_focused()
        # A withdrawn exact line clears the open drawer and its save controls.
        page.get_by_role("button", name="Compare prices").click()
        state["empty"] = True
        state["revision"] = "three"
        expect(page.locator("#comparison")).to_contain_text(
            "This line is no longer available"
        )
        expect(page.locator("#comparison .exchange-prices")).to_have_count(0)
        expect(page.locator("#comparison .journal-action")).to_have_count(0)
        page.get_by_role("button", name="Close comparison").click()
        state["empty"] = False
        state["revision"] = "four"
        expect(page.locator(".ticket")).to_have_count(1)
        before = len([r for r in requests if r[0] == "/api/pregame"])
        # One unchanged status poll must not reread the list.
        with page.expect_response(lambda r: "/updates" in r.url):
            page.locator("#count").click()
        assert len([r for r in requests if r[0] == "/api/pregame"]) == before
        state["failed"] = True
        page.get_by_role("button", name="Refresh").click()
        expect(page.locator("#error")).to_be_visible()
        expect(page.locator("#results")).to_contain_text("+9.00%")
        state["failed"] = False
        page.get_by_role("link", name="Open Game:").click()
        expect(page).to_have_url(
            __import__("re").compile(r"/game\?game_key=occurrence-1")
        )
        expect(page.locator(".game-bet")).to_have_count(1)
        assert any(q.get("game_key") == "occurrence-1" for _, q in requests)
        page.screenshot(path=str(tmp_path / f"pregame-{width}.png"), full_page=True)
        page.get_by_role("searchbox", name="Search teams").fill("unknown")
        expect(page.locator(".ticket")).to_have_count(0)
        expect(page.locator("#results")).to_contain_text("No odds match")
        # First-read failure must not claim previously rendered prices exist.
        state["failed"] = True
        page.goto("https://predict.fixture/")
        expect(page.locator("#error")).to_contain_text("Choose Refresh to retry")
        expect(page.locator("#error")).not_to_contain_text("preserved")
        expect(page.locator(".status-line")).to_be_hidden()
        expect(page.get_by_role("navigation", name="Pages")).to_be_hidden()
        state["failed"] = False
        state["empty"] = False
        selected["game"] = (
            "A very long legitimate university team name at Another unusually long university team name"
        )
        page.get_by_role("button", name="Refresh").click()
        expect(page.locator(".ticket")).to_have_count(1)
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        compare = page.get_by_role("button", name="Compare prices").first
        compare.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#comparison")).to_be_visible()
        page.keyboard.press("Escape")
        expect(compare).to_be_focused()
        compare.focus()
        page.keyboard.press("Space")
        expect(page.locator("#comparison")).to_be_visible()
        page.keyboard.press("Escape")
        page.locator(".board-info .about-link").click()
        expect(
            page.get_by_role("heading", name="About this board", exact=True)
        ).to_be_visible()
        expect(page.locator("main")).to_contain_text("Fair odds are derived")
        expect(page.locator("main")).to_contain_text("Prices may be delayed")
        expect(page.locator("main")).to_contain_text(
            "not personalized financial advice"
        )
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.get_by_role("link", name="Back to opportunities", exact=True).click()
        expect(page.locator(".ticket")).to_have_count(1)
        assert not errors, errors
        browser.close()


def test_pending_save_survives_new_prices_and_refresh_reports_pending():
    from playwright.sync_api import sync_playwright, expect

    selected = offer()
    state = dict(revision="one", hold_read=False, total=1)
    pending_saves, pending_reads = [], []

    def packet():
        return dict(
            cursor=state["revision"],
            rows=[deepcopy(selected)],
            total=state["total"],
            refresh_at=selected["kickoff"],
        )

    def serve(route):
        url = urlparse(route.request.url)
        if url.path == "/api/bet-journal":
            pending_saves.append(route)
        elif url.path.endswith("/updates"):
            q = parse_qs(url.query)
            route.fulfill(json=dict(changed=q.get("after") != [state["revision"]]))
        elif url.path == "/api/pregame":
            if state["hold_read"]:
                pending_reads.append(route)
            else:
                route.fulfill(json=packet())
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(path=ASSETS / "pregame.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=390, height=844))
        page.route("**/*", serve)
        page.goto("http://predict.fixture/")
        page.get_by_role("button", name="Compare prices for").click()
        save = page.get_by_role("button", name="Save ProphetX to My Bets")
        save.click()
        expect(save).to_be_disabled()
        selected["posted"]["value"] = "+130"
        selected["display"].update(posted_odds="+130", net_ev="+9.00%")
        state["revision"] = "two"
        expect(page.locator(".exchange-prices")).to_contain_text("+130")
        expect(save).to_be_disabled()
        first = pending_saves.pop(0)
        assert first.request.post_data_json["snapshot"]["posted"]["value"] == "+120"
        first.fulfill(status=201, json=dict(entry=dict(id="original-quote")))
        expect(page.locator("#comparison")).to_contain_text("Earlier quote saved.")
        expect(save).to_be_enabled()
        save.click()
        expect(save).to_be_disabled()
        second = pending_saves.pop(0)
        assert second.request.post_data_json["snapshot"]["posted"]["value"] == "+130"
        second.fulfill(status=201, json=dict(entry=dict(id="newer-quote")))
        expect(page.locator("#comparison")).not_to_contain_text("Earlier quote saved.")
        expect(
            page.get_by_role("link", name="Enter actual odds & stake")
        ).to_have_attribute("href", "/my-bets?entry=newer-quote")
        page.get_by_role("button", name="Close comparison").click()
        state["hold_read"] = True
        refresh = page.get_by_role("button", name="Refresh", exact=True)
        refresh.click()
        expect(refresh).to_be_disabled()
        expect(refresh).to_have_attribute("aria-busy", "true")
        state["hold_read"] = False
        for route in pending_reads:
            route.fulfill(json=packet())
        expect(refresh).to_be_enabled()
        expect(refresh).not_to_have_attribute("aria-busy", "true")
        # One-page cleanup must leave genuine pagination reachable.
        state.update(total=31, revision="three")
        expect(page.get_by_role("navigation", name="Pages")).to_be_visible()
        page.get_by_role("button", name="Next →", exact=True).click()
        expect(page.locator("#page")).to_have_text("31–31 of 31")
        expect(
            page.get_by_role("button", name="← Previous", exact=True)
        ).to_be_enabled()
        # If the live population shrinks, preserve the way back from page two.
        state.update(total=1, revision="four")
        expect(page.locator("#count")).to_have_text("1 opportunity")
        expect(page.get_by_role("navigation", name="Pages")).to_be_visible()
        page.get_by_role("button", name="← Previous", exact=True).click()
        expect(page.get_by_role("navigation", name="Pages")).to_be_hidden()
        browser.close()


@pytest.mark.parametrize("width", [1440, 600, 390])
def test_ranking_dropdown_defaults_growth_persists_and_resets_page(width):
    from playwright.sync_api import sync_playwright, expect

    requests, errors = [], []
    labels = {
        "growth": ("Kelly growth", "Growth", "log bp", "1.234"),
        "ev": ("Net EV", "Net EV", "%", "+8.80%"),
        "score": ("Kelly fraction", "Kelly", "fraction × 10,000", "748"),
        "balanced": ("Balanced (experimental)", "Balanced", "index", "812.34"),
        "edge": ("Probability edge", "Edge", "pp", "+4.000"),
    }

    def serve(route):
        url = urlparse(route.request.url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path.endswith("/updates"):
            route.fulfill(json=dict(changed=False))
        elif url.path == "/api/pregame":
            requests.append(q)
            selected = q.get("sort", "growth")
            label, column, unit, shown = labels[selected]
            row = offer()
            row["ranking"] = dict(
                method=selected,
                label=label,
                column=column,
                unit=unit,
                display=shown,
                value="1.234",
            )
            route.fulfill(
                json=dict(
                    cursor=selected,
                    sort=selected,
                    rows=[row],
                    total=31,
                    refresh_at=row["kickoff"],
                )
            )
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(path=ASSETS / "pregame.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=900))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", serve)
        page.goto("http://predict.fixture/")
        ranking = page.get_by_role("combobox", name="Rank by")
        from app.storage.pregame_ranking import catalog

        expect(ranking.locator("option")).to_have_text(
            [info["label"] for info in catalog()["methods"].values()]
        )
        expect(ranking).to_have_value("growth")
        expect(page.locator(".ticket .score .math-trigger")).to_have_text("1.234")
        assert requests[-1]["sort"] == "growth"
        if width == 1440:
            unsupported = page.evaluate(
                """async row => {
                const {addMath} = await import('/view/current/pregame-math.js');
                const cell = document.createElement('div');
                cell.innerHTML = '<span>0</span>';
                try { addMath(cell, row, 'retired-score-detail'); return null; }
                catch (error) { return error.message; }
            }""",
                offer(),
            )
            assert unsupported == "Unsupported calculation detail: retired-score-detail"
            # display:contents metadata must not move growth under the Price heading.
            for header, cell in (
                ("#ranking-column", ".ticket .score"),
                (".board-columns > span:nth-child(5)", ".ticket .posted"),
            ):
                heading = page.locator(header).bounding_box()
                figure = page.locator(cell).bounding_box()
                assert abs(heading["x"] - figure["x"]) < 1
                assert abs(heading["width"] - figure["width"]) < 1
        page.locator(".ticket .score .math-trigger").focus()
        expect(page.locator(".math-popover:popover-open")).to_contain_text(
            "Growth = 10,000"
        )
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Next →", exact=True).click()
        expect(page.locator("#page")).to_have_text("31–31 of 31")
        for selected in ("ev", "score", "balanced", "edge", "growth"):
            ranking.select_option(selected)
            expect(page.locator(".ticket .score .math-trigger")).to_have_text(
                labels[selected][3]
            )
            expect(page.locator("#page")).to_have_text("1–30 of 31")
            assert requests[-1]["sort"] == selected
            assert requests[-1]["offset"] == "0"
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        ranking.select_option("ev")
        expect(page.locator(".ticket .score .math-trigger")).to_have_text("+8.80%")
        page.reload()
        expect(ranking).to_have_value("ev")
        expect(page.locator(".ticket .score .math-trigger")).to_have_text("+8.80%")
        page.get_by_role("button", name="Compare prices for").click()
        expect(page.locator(".exchange-prices")).to_contain_text("+8.80%")
        assert requests[-1]["sort"] == "ev"
        page.keyboard.press("Escape")
        page.goto("http://predict.fixture/browse-odds")
        expect(ranking).to_be_hidden()
        expect(page.locator("#sort-order")).to_contain_text("Game start time")
        assert not errors
        browser.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_background_redraw_preserves_focus_after_comparison_closes(width):
    from playwright.sync_api import sync_playwright, expect

    selected = offer()
    state = dict(hold=False, empty=False, revision="one")
    pending, errors = [], []

    def packet():
        return dict(
            cursor=state["revision"],
            rows=[] if state["empty"] else [deepcopy(selected)],
            total=0 if state["empty"] else 1,
            refresh_at=selected["kickoff"],
        )

    def serve(route):
        url = urlparse(route.request.url)
        if url.path.endswith("/updates"):
            route.fulfill(json=dict(changed=False))
        elif url.path == "/api/pregame":
            if state["hold"] and "bet_id" not in parse_qs(url.query):
                pending.append(route)
            else:
                route.fulfill(json=packet())
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(path=ASSETS / "pregame.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=900))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/")
        compare = page.get_by_role("button", name="Compare prices for")
        expect(compare).to_be_visible()

        def start_read():
            state["hold"] = True
            # Dispatch the real refresh handler without moving keyboard focus;
            # the held response models a background read already in flight.
            with page.expect_request(
                lambda request: (
                    urlparse(request.url).path == "/api/pregame"
                    and "bet_id" not in parse_qs(urlparse(request.url).query)
                )
            ):
                page.evaluate("document.getElementById('refresh').click()")
            expect(
                page.get_by_role("button", name="Refresh", exact=True)
            ).to_be_disabled()
            assert len(pending) == 1

        def finish_read():
            state["hold"] = False
            pending.pop().fulfill(json=packet())
            expect(
                page.get_by_role("button", name="Refresh", exact=True)
            ).to_be_enabled()

        def close_comparison():
            # Native focus restoration precedes the queued close event. Wait for
            # the app's close handler before interacting with another control.
            dialog = page.locator("#comparison")
            dialog.evaluate("""dialog => {
                dialog.testClosed = false;
                dialog.addEventListener('close', () => dialog.testClosed = true,
                    {once: true});
            }""")
            page.keyboard.press("Escape")
            expect(dialog).to_have_js_property("testClosed", True)
            expect(dialog).not_to_be_visible()
            expect(compare).to_be_focused()

        start_read()
        compare.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#comparison")).to_be_visible()
        close = page.get_by_role("button", name="Close comparison")
        close.focus()
        selected["display"]["posted_odds"] = "+130"
        state["revision"] = "two"
        finish_read()
        expect(page.locator("#results .posted")).to_contain_text("+130")
        expect(close).to_be_focused()  # A list update must not steal dialog focus.
        close_comparison()

        start_read()
        selected["display"]["posted_odds"] = "+140"
        state["revision"] = "three"
        finish_read()
        expect(page.locator("#results .posted")).to_contain_text("+140")
        expect(compare).to_be_focused()  # The restored button survives later reads.
        page.keyboard.press("Space")
        expect(page.locator("#comparison")).to_be_visible()
        close_comparison()

        metric = page.locator("#results .ev .math-trigger")
        metric.focus()
        expect(page.locator(".math-popover:popover-open")).to_be_visible()
        start_read()
        selected["display"]["net_ev"] = "+9.50%"
        state["revision"] = "four"
        finish_read()
        expect(metric).to_have_text("+9.50%")
        expect(metric).to_be_focused()
        expect(page.locator(".math-popover:popover-open")).to_be_visible()
        page.keyboard.press("Escape")

        start_read()
        state.update(empty=True, revision="five")
        finish_read()
        expect(page.locator(".ticket")).to_have_count(0)
        expect(page.locator("#results")).to_be_focused()
        assert not errors, errors
        browser.close()
