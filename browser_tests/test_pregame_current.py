"""The shipped current-row UI: complete tickets, pinned inspection, cheap updates and recovery."""

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
        expect(page.locator(".ticket")).to_contain_text("+8.80%")
        expect(page.locator(".fair .reference")).to_contain_text("FanDuel (-110)")
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
        page.locator(".exchange-prices .math-trigger").first.focus()
        expect(page.locator(".math-popover:popover-open")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#comparison")).to_be_visible()
        page.get_by_text("Fee and calculation details", exact=True).click()
        expect(page.locator("#comparison")).to_contain_text("$2.40")
        expect(page.locator("#comparison")).to_contain_text("$0.00")
        selected["display"]["net_ev"] = "+9.00%"
        state["revision"] = "two"
        expect(page.locator("#results")).to_contain_text("+9.00%")
        expect(page.locator("#comparison")).to_contain_text("+8.80%")
        page.get_by_role("button", name="Close comparison").click()
        expect(page.get_by_role("button", name="Compare prices")).to_be_focused()
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
