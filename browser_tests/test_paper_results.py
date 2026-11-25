"""Check the results-first browser path against versioned, read-only responses."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

from browser_tests.test_pregame_current import ASSETS
from browser_tests.test_research_workspace import research_http_fixture

DAY = "2026-11-23"
CLOCK = "2026-11-24T10:30:00Z"
FIRST, CORRECTED = "a" * 64, "b" * 64
RUN = "c" * 64
GAME = "frozen-game"
TITLE = "East Carolina at Indiana State"
BASE = "/api/research/workspace"
RESULTS = f"{BASE}/runs/{RUN}/results"


def report(revision):
    corrected = revision == CORRECTED
    trade = {
        "id": "trade-a",
        "game_id": GAME,
        "label": "East Carolina",
        "family": "spread",
        "line": "-29/2",
        "venue": "novig",
        "posted_odds": "+669",
        "probability": "12/77",
        "ev": "20154/100000",
        "stake_usd": "75.32",
        "expected_profit_usd": "15.18",
        "return_usd": "579.21" if corrected else "0.00",
        "pnl_usd": "503.89" if corrected else "-75.32",
        "capture_origin": "frozen",
        "grade": {
            "id": "g-" + revision,
            "state": "win" if corrected else "loss",
            "explanation": "East Carolina covered the spread."
            if corrected
            else "East Carolina lost by 1 and did not cover −14.5.",
            "evidence_ids": [f"evidence-{revision[:2]}"],
        },
    }
    summary = {
        "tickets": 1,
        "games": 1,
        "resolved": 1,
        "unresolved": 0,
        "wins": int(corrected),
        "losses": int(not corrected),
        "pushes": 0,
        "voids": 0,
        "stake_usd": trade["stake_usd"],
        "expected_profit_usd": trade["expected_profit_usd"],
        "return_usd": trade["return_usd"],
        "pnl_usd": trade["pnl_usd"],
        "roi": "50389/7532" if corrected else "-1",
        "roi_stake_usd": trade["stake_usd"],
        "unresolved_stake_usd": "0.00",
    }
    portfolio = {
        "summary": summary,
        "tickets": [trade],
        "by_game": {GAME: summary},
        "by_venue": {"novig": summary},
        "by_capture": {"frozen": summary},
    }
    return {
        "status": "graded",
        "coverage": {"captured_games": 2},
        "games": [
            {
                "game_id": GAME,
                "title": TITLE,
                "capture_status": "captured",
                "result": {
                    "state": "final",
                    "away": {"name": "East Carolina"},
                    "home": {"name": "Indiana State"},
                    "away_score": 96 if corrected else 76,
                    "home_score": 77,
                    "observed_at": CLOCK,
                    "evidence": [
                        {"source": "college_basketball_data", "receipt_id": "d" * 64}
                    ],
                },
            },
            {
                "game_id": "no-trades",
                "title": "Visitor at Host",
                "capture_status": "captured",
                "result": {"state": "final"},
            },
            {
                "game_id": "no-capture",
                "title": "Missing at Capture",
                "capture_status": "missed",
                "result": {"state": "pending"},
            },
        ],
        "portfolios": {"best_venue": portfolio, "all_venues": portfolio},
    }


def test_paper_results_journey_refresh_and_exact_history():
    definition = {"version": "fixture-definition", "title": "Paper experiment"}
    run = {
        "id": RUN,
        "title": "Paper experiment",
        "date": DAY,
        "definition_version": definition["version"],
        "coverage": {"captured_games": 2, "missing_tracked_games": 1},
    }
    original = {"count": 1, "unique_games": 1, "turnover_usd": "75.32"}
    selected = {
        "run": run,
        "definition": definition,
        "report": {
            "policy": {"execution": "paper_only"},
            "portfolios": {"best_venue": original, "all_venues": original},
        },
    }
    latest, state = FIRST, "graded"
    requests, errors = [], []

    def serve(route):
        target = urlsplit(route.request.url)
        query = {key: values[0] for key, values in parse_qs(target.query).items()}
        requests.append((route.request.method, target.path, query))
        if target.path == "/research":
            route.fulfill(path=ASSETS / "research-workspace.html")
        elif target.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(target.path).name)
        elif target.path == "/api/workspace/status":
            route.fulfill(json={})
        elif target.path == BASE:
            route.fulfill(json={"definitions": [definition], "runs": [run]})
        elif target.path == f"{BASE}/runs/{RUN}":
            route.fulfill(json=selected)
        elif target.path == RESULTS:
            revision = query.get("version", latest)
            variant = query["variant"]

            def metadata(identity):
                return dict(id=identity, observed_at=CLOCK, processed_at=CLOCK)

            published = report(revision)
            if query.get("export"):
                kind = query["export"]
                payload = {
                    "version": {"id": revision},
                    "variant": variant,
                    "export": kind,
                }
                if kind == "report":
                    payload["report"] = published
                elif kind == "games":
                    payload["rows"] = published["games"]
                else:
                    payload["rows"] = published["portfolios"][variant]["tickets"]
                route.fulfill(
                    json=payload,
                    headers={
                        "Content-Disposition": 'attachment; filename="paper-results.json"'
                    },
                )
                return
            route.fulfill(
                json={
                    "status": {
                        "state": state,
                        "latest_version": latest,
                        "stale": state == "update_pending",
                    },
                    "version": metadata(revision),
                    "versions": [metadata(identity) for identity in {latest, FIRST}],
                    "report": None if query.get("status") else published,
                    "links": {
                        kind: f"{RESULTS}?version={revision}&variant={variant}&export={kind}"
                        for kind in ("report", "games", "trades")
                    },
                }
            )
        elif target.path == f"{BASE}/runs/{RUN}/tickets/trade-a":
            ticket = report(FIRST)["portfolios"]["best_venue"]["tickets"][0]
            route.fulfill(
                json={
                    "ticket": dict(ticket, title=TITLE, kelly_budget_usd="75.32"),
                    "evidence": {
                        "sized_calculation": {
                            "fee": {"cashflows": {"loss": {"net_receipt_usd": "0.00"}}}
                        },
                        "trade": {
                            "kelly": {
                                "reference_bankroll_usd": "10000",
                                "multiplier": "1/4",
                            },
                            "clocks": {"source_at": CLOCK},
                        },
                    },
                }
            )
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 820})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(
            f"{base}/research?section=experiments&definition={definition['version']}"
        )
        summary = page.locator(".paper-result-summary")
        expect(summary).to_contain_text("1 selected ticket graded")
        expect(summary).to_contain_text("1 game without retained T−10 evidence")
        expect(summary).to_contain_text("Complete slate unknown")
        expect(page.get_by_role("heading", name="Games", exact=True)).to_be_visible()
        page.get_by_label("Show games").select_option("missing")
        expect(page.get_by_role("link", name="Missing at Capture")).to_be_visible()
        expect(page.get_by_role("link", name=TITLE)).to_have_count(0)
        page.get_by_label("Show games").select_option("zero")
        page.get_by_role("link", name="Visitor at Host").click()
        expect(page.get_by_text("No trades qualified", exact=False)).to_be_visible()
        page.go_back()
        page.get_by_label("Show games").select_option("all")
        page.get_by_role("link", name=TITLE).click()
        expect(page.locator(".results-score")).to_have_text(
            "Final · East Carolina 76 – Indiana State 77"
        )
        page.get_by_role("link", name="East Carolina -14.5").click()
        trade = page.locator(".paper-result-trade")
        expect(trade).to_contain_text("East Carolina lost by 1")
        expect(trade).to_contain_text("-$75.32")
        expect(trade).to_contain_text("$15.18")
        expect(
            trade.get_by_role("heading", name="Paper sizing and fee treatment")
        ).to_be_visible()
        expect(trade.get_by_text("25.00%")).to_be_visible()
        page.get_by_role("link", name="All qualifying venues").click()
        page.reload()
        expect(trade.get_by_role("heading", name="Frozen quote")).to_be_visible()
        assert "variant=all_venues" in page.url and "trade=trade-a" in page.url
        assert f"date={DAY}" in page.url and f"run={RUN}" in page.url
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for name, kind in [
            ("Export graded report", "report"),
            ("Export game rows", "games"),
            ("Export trade rows", "trades"),
        ]:
            with page.expect_download() as download:
                page.get_by_role("link", name=name, exact=True).click()
            exported = json.loads(Path(download.value.path()).read_text())
            assert exported["version"]["id"] == FIRST
            assert exported["variant"] == "all_venues" and exported["export"] == kind
            if kind == "trades":
                assert exported["rows"][0]["pnl_usd"] == "-75.32"
        assert any(
            query == {"export": "trades", "variant": "all_venues", "version": FIRST}
            for _, path, query in requests
            if path == RESULTS
        )
        state = "update_pending"
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(summary).to_contain_text("Result update pending")
        expect(trade).to_have_count(0)
        expect(page.get_by_role("link", name="Export trade rows")).to_have_count(0)
        page.get_by_role("link", name="Link to this result version").click()
        expect(summary).to_contain_text("Historical result")
        expect(trade).to_contain_text("-$75.32")
        assert f"result={FIRST}" in page.url
        page.get_by_role("link", name="Open latest result").click()
        expect(summary).to_contain_text("Result update pending")
        latest, state = CORRECTED, "graded"
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        expect(trade).to_contain_text("$503.89")
        page.go_back()
        expect(trade).to_contain_text("-$75.32")
        expect(summary).to_contain_text("Historical result")
        assert all(method == "GET" for method, _, _ in requests)
        assert not errors
        browser.close()
