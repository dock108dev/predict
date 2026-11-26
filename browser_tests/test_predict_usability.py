"""Use game results, trades, and coverage across the installed pages."""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from app.dashboard.workspace_app import ASSETS, WORKSPACE_ASSETS
from app.dashboard.workspace_routes import PAGES
from app.research.paper_campaigns import configuration
from browser_tests.test_paper_results import BASE, DAY, FIRST, RUN, report
from tests.test_paper_campaigns import fixed_config


def assert_table_fits(region):
    assert region.evaluate("node => node.scrollWidth <= node.clientWidth"), (
        region.evaluate(
            "node => ({visible: node.clientWidth, content: node.scrollWidth})"
        )
    )


def assert_line_fits(region, row, content):
    value = row.get_by_text(content, exact=False).filter(visible=True)
    expect(value).to_be_visible()
    fragments = value.evaluate(
        """(element, content) => {
            const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
            for (let text = walker.nextNode(); text; text = walker.nextNode()) {
                const start = text.data.indexOf(content);
                if (start < 0) continue;
                const range = new Range();
                range.setStart(text, start);
                range.setEnd(text, start + content.length);
                return [...range.getClientRects()].map(({left, right, top}) => ({left, right, top}));
            }
            return [];
        }""",
        content,
    )
    bounds = region.bounding_box()
    assert (
        fragments
        and max(rect["top"] for rect in fragments)
        - min(rect["top"] for rect in fragments)
        <= 1
    ), fragments
    assert all(
        bounds["x"] - 1
        <= rect["left"]
        <= rect["right"]
        <= bounds["x"] + bounds["width"] + 1
        for rect in fragments
    ), fragments


@pytest.mark.parametrize(
    "engine,device,viewport",
    [
        pytest.param(
            "chromium", None, {"width": 1360, "height": 850}, id="chromium-desktop"
        ),
        pytest.param(
            "chromium", None, {"width": 390, "height": 820}, id="chromium-phone"
        ),
        pytest.param("webkit", "iPhone 13 Mini", None, id="webkit-iphone-13-mini"),
        pytest.param("webkit", "iPhone 15", None, id="webkit-iphone-15"),
        pytest.param(
            "webkit", "iPhone 13 Mini", {"width": 320, "height": 568}, id="webkit-320px"
        ),
    ],
)
def test_missing_final_keeps_exact_game_and_separate_capture_status(
    engine, device, viewport
):
    campaign = "f" * 64
    game_id = "9" * 64
    game_title = "Ecclesia Royals at Grambling St Tigers"
    graded_title = "Kansas State Wildcats at Gonzaga Bulldogs"
    missed_title = "St. Bonaventure Bonnies at Belmont Bruins"
    config = dict(
        configuration(
            fixed_config(
                name="Win $25 · All sports",
                scope="all-sports",
                target_profit_usd="25",
                start_date=DAY,
                end_date=DAY,
            )
        ),
        id=campaign,
    )
    result = report(FIRST)
    graded = result["games"][0]
    graded.update(title=graded_title, league="NCAAB", starts_at=f"{DAY}T19:30:00Z")
    graded["result"].update(
        away={"name": "Kansas State Wildcats"},
        home={"name": "Gonzaga Bulldogs"},
        away_score=61,
        home_score=101,
    )
    missed = next(
        game for game in result["games"] if game["capture_status"] == "missed"
    )
    missed.update(
        title=missed_title,
        league="NCAAB",
        result=dict(
            state="final",
            away="St. Bonaventure Bonnies",
            home="Belmont Bruins",
            away_score=71,
            home_score=68,
        ),
    )
    trade = result["portfolios"]["best_venue"]["tickets"][0]
    trade["label"] = "Kansas State Wildcats"
    trade["grade"]["explanation"] = "Kansas State failed to cover."
    result["games"] = [game for game in result["games"] if game["title"] != game_title]
    result["games"].append(
        dict(
            game_id=game_id,
            title=game_title,
            league="NCAAB",
            starts_at=f"{DAY}T20:00:00Z",
            capture_status="captured",
            checkpoint_id="b" * 64,
            result=dict(
                state="unresolved",
                reason="retained_final_score_or_participant_binding_unavailable",
            ),
        )
    )
    campaign_path = f"{BASE}/campaigns/{campaign}"
    run_path = f"{BASE}/runs/{RUN}"
    requests, errors = [], []

    def serve(route):
        url = urlsplit(route.request.url)
        path = url.path
        query = parse_qs(url.query)
        assert url.hostname == "predict.fixture" and route.request.method == "GET"
        requests.append((path, query))
        if path in PAGES:
            route.fulfill(path=ASSETS / PAGES[path], content_type="text/html")
        elif path == BASE + "/campaigns":
            route.fulfill(json=dict(campaigns=[config]))
        elif path == campaign_path + "/days/" + DAY:
            route.fulfill(
                json=dict(
                    config=config,
                    modes={
                        mode: dict(
                            run_id=RUN, result_id=FIRST, result_state="partially_graded"
                        )
                        for mode in ("fixed_profit", "kelly")
                    },
                )
            )
        elif path == run_path:
            route.fulfill(
                json=dict(
                    run=dict(id=RUN, date=DAY, title=config["name"]),
                    definition=dict(campaign_id=campaign, sizing_mode="fixed_profit"),
                    report=dict(
                        policy=dict(execution="paper_only"),
                        portfolios=result["portfolios"],
                    ),
                )
            )
        elif path == run_path + "/results":
            route.fulfill(
                json=dict(
                    report=result,
                    version=dict(id=FIRST),
                    status=dict(state="partially_graded"),
                )
            )
        elif path == run_path + "/tickets/trade-a":
            route.fulfill(
                json=dict(
                    ticket=dict(trade, title=graded_title), evidence={"trade": {}}
                )
            )
        elif path == "/api/research/data/results":
            assert query == {"tracked_game": [game_id]}
            route.fulfill(json={"rows": []})
        elif path == "/api/workspace/collection":
            route.fulfill(json={})
        elif path.startswith("/view/current/") and Path(path).name in WORKSPACE_ASSETS:
            route.fulfill(path=ASSETS / Path(path).name)
        else:
            route.fulfill(status=404)

    with sync_playwright() as runtime:
        browser_type = getattr(runtime, engine)
        if engine == "webkit" and not Path(browser_type.executable_path).exists():
            pytest.skip(
                "Install the optional WebKit browser to exercise iPhone layouts locally"
            )
        browser = browser_type.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
            if engine == "chromium"
            else None
        )
        profile = dict(runtime.devices[device]) if device else {}
        if viewport:
            profile["viewport"] = viewport
        page = browser.new_page(**profile)
        page.route("**/*", serve)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://predict.fixture/experiments?campaign={campaign}&date={DAY}")
        page.get_by_role("link", name="Games and coverage", exact=True).click()
        games = page.get_by_role("region", name="Game rows", exact=True)
        graded_link = page.get_by_role("link", name=graded_title, exact=True)
        graded_row = games.locator("tbody tr").filter(has=graded_link)
        missed_link = page.get_by_role("link", name=missed_title, exact=True)
        missed_row = games.locator("tbody tr").filter(has=missed_link)
        expect(graded_link).to_be_visible()
        expect(graded_row).to_contain_text("Final")
        expect(graded_row).to_contain_text("61")
        expect(graded_row).to_contain_text("101")
        expect(
            missed_row.get_by_text("Missed T−10", exact=False).filter(visible=True)
        ).to_be_visible()
        if page.viewport_size["width"] < 500:
            assert_table_fits(games)
            expect(graded_row.locator(".result-game-mobile-score")).to_have_text(
                "Final · Away 61 – Home 101"
            )
            expect(missed_row.locator(".result-game-mobile-score")).to_have_text(
                "Final · Away 71 – Home 68"
            )
            expect(graded_row.locator(".result-game-mobile-financials")).to_be_visible()
            expect(
                missed_row.locator(".result-game-mobile-financials")
            ).not_to_be_visible()
            assert_line_fits(games, graded_row, "Away 61 – Home 101")
            assert_line_fits(games, missed_row, "Away 71 – Home 68")
        else:
            expect(missed_row.get_by_text("Unavailable", exact=True)).to_be_visible()
        assert_line_fits(games, graded_row, "-$75.32")
        graded_link.click()
        detail = page.locator(".paper-result-game")
        expect(detail.get_by_role("heading", name=graded_title)).to_be_visible()
        expect(detail.locator(".results-score")).to_contain_text("61")
        trades = detail.get_by_role("region", name="Game trade rows", exact=True)
        selection = trades.get_by_role(
            "link", name="Kansas State Wildcats -14.5", exact=True
        )
        expect(selection).to_be_visible()
        expect(
            trades.get_by_text("Loss", exact=True).filter(visible=True)
        ).to_be_visible()
        if page.viewport_size["width"] < 500:
            assert_table_fits(trades)
        assert_line_fits(trades, trades.locator("tbody tr"), "-$75.32")
        detail.get_by_label("Bet type", exact=True).select_option("total")
        expect(detail.get_by_text("No trades match this view.")).to_be_visible()
        detail.get_by_label("Bet type", exact=True).select_option("spread")
        with page.expect_response(
            lambda response: (
                urlsplit(response.url).path == run_path + "/tickets/trade-a"
            )
        ) as evidence:
            selection.click()
        assert evidence.value.ok
        exact_trade = detail.locator(".paper-result-trade")
        expect(exact_trade).to_contain_text("Kansas State failed to cover.")
        exact_trade.get_by_role("link", name="Back to game trades").click()
        expect(selection).to_be_visible()
        expect(detail.get_by_label("Bet type", exact=True)).to_have_value("spread")
        detail.get_by_role("link", name="Back to games", exact=True).click()
        filters = page.get_by_label("Show games", exact=True)
        title = page.get_by_role("link", name=game_title, exact=True)
        filters.select_option(label="Missing finals")
        expect(title).to_be_visible()
        filters.select_option(label="Missed captures")
        expect(title).to_have_count(0)
        expect(missed_link).to_be_visible()
        filters.select_option(label="Zero qualifying trades")
        expect(title).to_be_visible()
        filters.select_option(label="Missing finals")
        title.click()
        game = page.locator(".paper-result-game")
        expect(game.get_by_role("heading", name=game_title)).to_be_visible()
        expect(game.locator(".results-score")).to_have_text("Result unresolved")
        expect(
            game.get_by_text("retained final score or participant binding unavailable")
        ).to_be_visible()
        retained = page.locator(".experiment-history").get_by_text(
            "Retained result evidence", exact=True
        )
        expect(retained).to_be_hidden()
        game.get_by_role("button", name="Review game evidence", exact=True).click()
        expect(retained).to_be_visible()
        retained.click()
        for name, evidence in [("Odds pulls", "pulls"), ("Captures", "checkpoints")]:
            query = parse_qs(
                urlsplit(
                    game.get_by_role("link", name=name, exact=True).get_attribute(
                        "href"
                    )
                ).query
            )
            assert query["evidence"] == [evidence] and query["tracked_game"] == [
                game_id
            ]
        game.get_by_role("link", name="Game scores", exact=True).click()
        expect(
            page.get_by_role("heading", name="Game scores", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_text("No retained odds-provider score for this game.")
        ).to_be_visible()
        page.go_back()
        expect(game.get_by_role("heading", name=game_title)).to_be_visible()
        game.get_by_role("link", name="Back to games", exact=True).click()
        expect(filters).to_have_value("missing_results")
        expect(title).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert ("/api/research/data/results", {"tracked_game": [game_id]}) in requests
        assert not errors
        browser.close()
