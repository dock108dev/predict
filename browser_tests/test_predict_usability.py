"""Investigate an unresolved final across the installed Experiments and Data pages."""

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from app.dashboard.workspace_app import ASSETS, WORKSPACE_ASSETS
from app.dashboard.workspace_routes import PAGES
from app.research.paper_campaigns import configuration
from browser_tests.test_paper_results import BASE, DAY, FIRST, RUN, report
from tests.test_paper_campaigns import fixed_config


@pytest.mark.parametrize("width,height", [(1360, 850), (390, 820)])
def test_missing_final_keeps_exact_game_and_separate_capture_status(width, height):
    campaign = "f" * 64
    game_id = "9" * 64
    game_title = "Ecclesia Royals at Grambling St Tigers"
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
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport=dict(width=width, height=height))
        page.route("**/*", serve)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://predict.fixture/experiments?campaign={campaign}&date={DAY}")
        page.get_by_role("link", name="Games and coverage", exact=True).click()
        filters = page.get_by_label("Show games", exact=True)
        title = page.get_by_role("link", name=game_title, exact=True)
        filters.select_option(label="Missing finals")
        expect(title).to_be_visible()
        filters.select_option(label="Missed captures")
        expect(title).to_have_count(0)
        expect(
            page.get_by_role("link", name="Missing at Capture", exact=True)
        ).to_be_visible()
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
