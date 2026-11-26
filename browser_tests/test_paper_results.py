"""Check the results-first browser path against versioned, read-only responses."""

import json
import os
import re
from fractions import Fraction
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from app.research.paper_results import _summary
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
                "capture_status": "reconstructed",
                "original_capture_status": "refused",
                "result": {"state": "final"},
            },
            {
                "game_id": "no-capture",
                "title": "Missing at Capture",
                "starts_at": "2026-11-23T22:00:00Z",
                "capture_status": "missed",
                "result": {"state": "pending"},
            },
        ],
        "portfolios": {"best_venue": portfolio, "all_venues": portfolio},
    }


def test_paper_results_journey_refresh_and_exact_history():
    definition = {
        "version": "fixture-definition",
        "title": "Paper experiment",
        "campaign_id": "d" * 64,
    }
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
            totals = published["portfolios"][variant]["summary"]
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
                    "quality": None
                    if query.get("status")
                    else {
                        "version": "quote-freshness-1",
                        "target_age_boundary_seconds": 60,
                        "target_age_clock": "Provider receipt time minus target quote source time.",
                        "provenance": {"frozen": {"summary": totals}},
                        "target_quote_age": {"over_300": totals},
                        "reference_quote_age": {"unknown": totals},
                        "fresh_target_only": {"summary": {**totals, "tickets": 0}},
                    },
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
        browser = runtime.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        page = browser.new_page(viewport={"width": 390, "height": 820})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(
            f"{base}/research?section=experiments&definition={definition['version']}"
        )
        summary = page.locator(".paper-result-summary")
        expect(
            page.get_by_role("link", name="Back to daily & weekly results")
        ).to_have_attribute("href", re.compile("campaign=" + "d" * 64))
        expect(summary).to_contain_text("1 selected ticket graded")
        expect(summary).to_contain_text("1 game without retained T−10 evidence")
        expect(summary).to_contain_text("Complete slate unknown")
        expect(page.get_by_role("heading", name="Trades", exact=True)).to_be_visible()
        expect(page.locator(".result-ledger-selection")).to_have_text(
            "East Carolina -14.5"
        )
        page.get_by_text("Capture provenance and quote freshness", exact=True).click()
        expect(
            page.get_by_role(
                "heading", name="Exploratory target-age screen · ≤60 seconds"
            )
        ).to_be_visible()
        expect(page.get_by_text("Over 300 seconds", exact=True)).to_be_visible()
        expect(page.get_by_text("Unknown timestamp", exact=True)).to_be_visible()
        page.get_by_role("link", name="Games and coverage", exact=True).click()
        expect(page.get_by_role("heading", name="Games", exact=True)).to_be_visible()
        page.get_by_label("Show games").select_option("reconstructed")
        expect(
            page.get_by_role("row").filter(has_text="Visitor at Host")
        ).to_contain_text("Original task refused")
        expect(page.get_by_role("link", name=TITLE)).to_have_count(0)
        page.get_by_label("Show games").select_option("missing")
        expect(page.get_by_role("link", name="Missing at Capture")).to_be_visible()
        page.get_by_label("Show games").select_option("missing_results")
        expect(page.get_by_role("link", name="Missing at Capture")).to_be_visible()
        expect(page.get_by_role("link", name="Visitor at Host")).to_have_count(0)
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


def ledger_report(size=18):
    result = report(FIRST)
    best = result["portfolios"]["best_venue"]
    template = best["tickets"][0]
    games, trades = result["games"], []
    for index in range(size):
        game = f"game-{index:02d}"
        state = ["loss", "pending", "conflicting", "push", "void", "win"][index % 6]
        resolved = state in {"win", "loss", "push", "void"}
        returned = (
            {"win": "15.00", "loss": "0.00"}.get(state, "5.00") if resolved else None
        )
        pnl = {"win": "10.00", "loss": "-5.00"}.get(state, "0.00") if resolved else None
        trade = dict(
            template,
            id=f"trade-{index:02d}",
            game_id=game,
            label=f"University of Lower Allegheny State at Capital Region {index:02d}",
            family="total" if index and index % 3 == 0 else "spread",
            line="+31/2" if index % 2 else "-31/2",
            period="1h",
            venue="novig" if index % 5 else "prophetx",
            ev=f"{10**20 + min(index, 16)}/1000000000000000000000",
            grade=dict(state=state, explanation=f"Witness for ticket {index:02d}"),
            stake_usd="5.00",
            stake_exact_usd="5",
            expected_profit_usd="0.50",
            expected_profit_exact_usd=str(
                Fraction(5)
                * Fraction(f"{10**20 + min(index, 16)}/1000000000000000000000")
            ),
            return_usd=returned,
            return_exact_usd=returned,
            pnl_usd=pnl,
            pnl_exact_usd=pnl,
        )
        trades.append(trade)
        games.append(
            dict(
                game_id=game,
                title=f"Away {index:02d} at Home {index:02d}",
                league="NBA" if index % 2 else "NHL",
                capture_status="captured",
                result={"state": "final"},
            )
        )
    for variant, selected in [("best_venue", trades[:-2]), ("all_venues", trades)]:
        result["portfolios"][variant] = dict(
            tickets=selected,
            summary=_summary(selected),
            by_game={trade["game_id"]: _summary([trade]) for trade in selected},
            by_venue={},
            by_capture={},
        )
    result.update(status="partially_graded")
    return result


def test_experiment_trade_filters_compose_and_more_rows_survive_reload():
    from app.research.paper_campaigns import configuration
    from tests.test_paper_campaigns import fixed_config

    campaign = "f" * 64
    form = fixed_config(name="All-sports paper", scope="all-sports",
                        kelly_comparison=False, start_date=DAY, end_date=DAY, portfolios=["all_venues"])
    del form["kelly_multiplier"], form["reference_bankroll_usd"]
    cfg = dict(configuration(form), id=campaign)
    result = ledger_report(58)
    path = f"{BASE}/campaigns/{campaign}"
    saved = result["portfolios"]["all_venues"]["tickets"]
    selected = dict(run=dict(id=RUN, date=DAY, title=cfg["name"]), definition=dict(campaign_id=campaign,
        sizing_mode="fixed_profit"), report=dict(policy={"execution": "paper_only"},
        portfolios={"all_venues": {"tickets": saved}}))

    def serve(route):
        target = urlsplit(route.request.url).path
        if target == "/experiments":
            route.fulfill(path=ASSETS / "experiment-workspace.html")
        elif target.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(target).name)
        elif target == "/api/workspace/collection":
            route.fulfill(json={})
        elif target == f"{BASE}/campaigns":
            route.fulfill(json=dict(campaigns=[cfg]))
        elif target == f"{path}/days/{DAY}":
            route.fulfill(json=dict(config=cfg, modes={"fixed_profit": dict(run_id=RUN, result_id=FIRST,
                result_state="partially_graded", snapshots=[])}))
        elif target == f"{BASE}/runs/{RUN}":
            route.fulfill(json=selected)
        elif target == RESULTS:
            route.fulfill(json=dict(report=result, version=dict(id=FIRST), status=dict(state="partially_graded")))
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport={"width": 390, "height": 820})
        page.goto(f"{base}/experiments?campaign={campaign}&date={DAY}&variant=all_venues")
        ledger = page.locator(".result-ledger-table")
        rows = ledger.locator("tbody tr")
        expect(rows).to_have_count(50)
        expect(page.locator(".result-metadata")).not_to_have_attribute("open", "")
        page.get_by_label("Rows per page").select_option("100")
        expect(rows).to_have_count(58)
        page.get_by_label("Sport", exact=True).select_option("NBA")
        expect(rows).to_have_count(29)
        page.get_by_label("Bet type").select_option("total")
        expect(rows).to_have_count(10)
        page.get_by_label("Venue", exact=True).select_option("novig")
        expect(rows).to_have_count(8)
        expect(page.locator(".result-ledger-subset")).to_contain_text("8 of 58 trades")
        page.reload()
        expect(page.get_by_label("Rows per page")).to_have_value("100")
        expect(page.get_by_label("Sport", exact=True)).to_have_value("NBA")
        expect(page.get_by_label("Bet type")).to_have_value("total")
        expect(page.get_by_label("Venue", exact=True)).to_have_value("novig")
        expect(rows).to_have_count(8)
        page.get_by_label("Grade", exact=True).select_option("loss")
        expect(page.get_by_text("No trades match the current filters.", exact=True)).to_be_visible()
        page.get_by_role("link", name="Games and coverage", exact=True).click()
        page.get_by_label("Sport", exact=True).select_option("NHL")
        expect(page.locator(".paper-result-games tbody tr")).to_have_count(29)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


def test_campaign_trade_filters_span_dates_and_open_exact_daily_evidence():
    from app.research.paper_campaigns import configuration
    from tests.test_paper_campaigns import fixed_config

    campaign = "f" * 64
    later_date, later_run, later_result = "2026-11-24", "e" * 64, CORRECTED
    pending_date, pending_run, pending_ticket = "2026-11-25", "d" * 64, "0" * 64
    form = fixed_config(name="Win $25 · All sports", scope="all-sports", target_profit_usd="25",
                        start_date=DAY, end_date=pending_date, portfolios=["all_venues"],
                        kelly_comparison=False)
    del form["kelly_multiplier"], form["reference_bankroll_usd"]
    cfg = dict(configuration(form), id=campaign)
    results = ledger_report(58)
    tickets = results["portfolios"]["all_venues"]["tickets"]
    games = {game["game_id"]: game for game in results["games"]}
    pending = tickets[33]
    later_trades = tickets[29:33] + tickets[34:]
    pending.update(id=pending_ticket, grade=dict(state="pending"), return_usd=None, pnl_usd=None,
                   return_exact_usd=None, pnl_exact_usd=None)
    later_report = dict(results, games=[games[trade["game_id"]] for trade in later_trades],
                        portfolios={"all_venues": dict(tickets=later_trades, summary=_summary(later_trades))})
    overview = []
    for day, run, result_id, selected in [(DAY, RUN, FIRST, tickets[:29]),
                                         (later_date, later_run, later_result, later_trades),
                                         (pending_date, pending_run, None, [pending])]:
        overview.extend(dict(trade, game_date=day, run_id=run, result_id=result_id,
                             league=games[trade["game_id"]]["league"],
                             game_title=games[trade["game_id"]]["title"], screen_ev="1/25")
                        for trade in selected)
    path = f"{BASE}/campaigns/{campaign}"
    run_path = f"{BASE}/runs/{later_run}"
    pending_path = f"{BASE}/runs/{pending_run}"
    evidence_path = f"{run_path}/tickets/trade-39"
    pending_evidence = f"{pending_path}/tickets/{pending_ticket}"
    requests = []

    def serve(route):
        target = urlsplit(route.request.url)
        endpoint = target.path
        requests.append((endpoint, parse_qs(target.query)))
        if endpoint == "/experiments":
            route.fulfill(path=ASSETS / "experiment-workspace.html")
        elif endpoint.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(endpoint).name)
        elif endpoint == "/api/workspace/collection":
            route.fulfill(json={})
        elif endpoint == f"{BASE}/campaigns":
            route.fulfill(json=dict(campaigns=[cfg]))
        elif endpoint == path:
            route.fulfill(json=dict(days=[], mode="fixed_profit"))
        elif endpoint == f"{path}/trades":
            route.fulfill(json=dict(id=campaign, mode="fixed_profit", variant="all_venues", trades=overview))
        elif endpoint in {f"{path}/days/{later_date}", f"{path}/days/{pending_date}"}:
            awaiting = endpoint.endswith(pending_date)
            route.fulfill(json=dict(config=cfg, modes={"fixed_profit": dict(
                run_id=pending_run if awaiting else later_run, result_id=None if awaiting else later_result,
                result_state="awaiting_results" if awaiting else "partially_graded", snapshots=[])}))
        elif endpoint in {run_path, pending_path}:
            awaiting = endpoint == pending_path
            route.fulfill(json=dict(run=dict(id=pending_run if awaiting else later_run,
                date=pending_date if awaiting else later_date, title=cfg["name"]),
                definition=dict(campaign_id=campaign, sizing_mode="fixed_profit"),
                report=dict(policy=dict(execution="paper_only"), portfolios={"all_venues": dict(tickets=[pending])}
                            if awaiting else later_report["portfolios"])))
        elif endpoint == f"{run_path}/results":
            route.fulfill(json=dict(report=later_report, version=dict(id=later_result), status=dict(state="partially_graded")))
        elif endpoint == f"{pending_path}/results":
            route.fulfill(json=dict(report=None, status=dict(state="awaiting_results")))
        elif endpoint in {evidence_path, pending_evidence}:
            item = dict(pending, title="Awaiting result") if endpoint == pending_evidence else tickets[39]
            route.fulfill(json=dict(ticket=item,
                                    evidence={"trade": {"clocks": {"source_at": CLOCK}}}))
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport={"width": 390, "height": 820})
        page.goto(f"{base}/experiments?campaign={campaign}&variant=all_venues")
        page.get_by_role("link", name="All trades", exact=True).click()
        expect(page.get_by_role("link", name="All trades", exact=True)).to_have_attribute("aria-current", "page")
        rows = page.locator(".result-ledger-table tbody tr")
        expect(rows).to_have_count(50)
        page.get_by_label("Rows per page").select_option("100")
        expect(rows).to_have_count(58)
        assert (f"{path}/trades", {"variant": ["all_venues"], "mode": ["fixed_profit"]}) in requests
        assert not any("/days/" in endpoint or "/runs/" in endpoint for endpoint, _ in requests)
        page.get_by_label("Sport", exact=True).select_option("NBA")
        page.get_by_label("Bet type", exact=True).select_option("total")
        page.get_by_label("Venue", exact=True).select_option("novig")
        expect(rows).to_have_count(8)
        for tab in ("All trades", "By day"):
            href = page.get_by_role("link", name=tab, exact=True).get_attribute("href")
            filters = parse_qs(urlsplit(href).query)
            assert filters["trade_sport"] == ["NBA"]
            assert filters["trade_family"] == ["total"]
            assert filters["trade_venue"] == ["novig"]
        expect(rows.filter(has_text="Away 03 at Home 03")).to_contain_text("Nov 23")
        expect(rows.filter(has_text="Away 39 at Home 39")).to_contain_text("Nov 24")
        page.get_by_label("Grade", exact=True).select_option("unresolved")
        expect(rows).to_have_count(1)
        expect(rows.first).to_contain_text("Pending result")
        expect(rows.first).to_contain_text("Nov 25")
        with page.expect_response(lambda response: urlsplit(response.url).path == pending_evidence):
            rows.first.locator(".result-ledger-selection").click()
        expect(page.get_by_role("dialog", name="Saved paper trade")).to_contain_text("Awaiting result")
        query = parse_qs(urlsplit(page.url).query)
        assert query["run"] == [pending_run] and query["ticket"] == [pending_ticket]
        assert "result" not in query
        page.go_back()
        expect(rows).to_have_count(1)
        page.go_back()
        expect(rows).to_have_count(8)
        page.reload()
        expect(rows).to_have_count(8)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        with page.expect_response(lambda response: urlsplit(response.url).path == evidence_path):
            rows.filter(has_text="Away 39 at Home 39").locator(".result-ledger-selection").click()
        expect(page.locator("#trade-inspector")).to_contain_text("Witness for ticket 39")
        query = parse_qs(urlsplit(page.url).query)
        assert query["date"] == [later_date]
        assert query["run"] == [later_run]
        assert query["result"] == [later_result]
        page.go_back()
        expect(rows).to_have_count(8)
        expect(page.get_by_label("Sport", exact=True)).to_have_value("NBA")
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_flat_ledger_exact_order_population_and_inspector_navigation(width):
    results = ledger_report(52)
    trades = results["portfolios"]["all_venues"]["tickets"]
    tickets = {trade["id"]: trade for trade in trades}
    originals = [
        dict(trade, screen_ev="1/25" if index < 26 else "2/25")
        for index, trade in enumerate(trades)
    ]
    expected = [
        ticket["id"]
        for ticket in sorted(
            trades, key=lambda ticket: (-Fraction(ticket["ev"]), ticket["id"])
        )
    ]
    errors, requests = [], []

    def serve(route):
        target = urlsplit(route.request.url)
        path = target.path
        requests.append((route.request.method, path))
        if path == "/research":
            route.fulfill(path=ASSETS / "research-workspace.html")
        elif path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(path).name)
        elif path == "/api/workspace/status":
            route.fulfill(json={})
        elif path == BASE:
            route.fulfill(json={"definitions": [], "runs": []})
        elif path == f"{BASE}/runs/{RUN}":
            route.fulfill(
                json=dict(
                    run=dict(id=RUN, date=DAY, title="Paper universe"),
                    definition={},
                    report=dict(
                        policy={"execution": "paper_only"},
                        portfolios={
                            "best_venue": {},
                            "all_venues": {"tickets": originals},
                        },
                    ),
                )
            )
        elif path == RESULTS:
            route.fulfill(
                json=dict(
                    report=results,
                    version={"id": FIRST},
                    status={"state": "partially_graded"},
                    quality={
                        "fresh_target_only": {
                            "buckets": [
                                {"minimum": "1/25", "maximum": "2/25"},
                                {"minimum": "2/25", "maximum": None},
                            ]
                        }
                    },
                )
            )
        elif path.startswith(f"{BASE}/runs/{RUN}/tickets/"):
            trade = tickets[path.rsplit("/", 1)[1]]
            route.fulfill(
                json=dict(
                    ticket=dict(trade, title=f"Frozen {trade['label']}"),
                    evidence={"trade": {"clocks": {"source_at": CLOCK}}},
                )
            )
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        page = browser.new_page(viewport={"width": width, "height": 820})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(
            f"{base}/research?section=experiments&date={DAY}&run={RUN}&variant=all_venues&result={FIRST}&trade_rows=25"
        )
        ledger = page.locator(".result-ledger-table")
        inspector = page.locator("#trade-inspector")
        expect(page.locator(".paper-result-summary")).to_contain_text(
            "Partially graded"
        )
        expect(page.locator(".paper-result-summary")).to_contain_text(
            "ROI uses $170.00 in resolved stake"
        )
        expect(ledger.locator("tbody tr")).to_have_count(25)
        seen = []
        for size in (25, 25, 2):
            rows = ledger.locator("a.result-ledger-selection")
            expect(rows).to_have_count(size)
            seen.extend(
                parse_qs(urlsplit(href).query)["trade"][0]
                for href in rows.evaluate_all("(rows) => rows.map(row => row.href)")
            )
            next_page = page.get_by_role("link", name="Next", exact=True)
            if size == 25:
                next_page.click()
        assert seen == expected
        assert all(
            key not in parse_qs(urlsplit(page.url).query)
            for key in ("game", "ledger_view")
        )
        assert not any("/tickets/" in path for _, path in requests)
        inspector.get_by_text(
            "Trade calculation and frozen evidence", exact=True
        ).click()
        expect(inspector.get_by_role("heading", name="Frozen quote")).to_be_visible()
        page.get_by_role("link", name="Previous", exact=True).click()
        expect(inspector.get_by_role("heading", name="Frozen quote")).to_have_count(0)
        page.get_by_role("link", name="Next", exact=True).click()
        pick = ledger.locator("a.result-ledger-selection").last
        expect(pick).to_contain_text("-15.5")
        expect(pick).to_contain_text("University of Lower Allegheny State")
        pick.click()
        expect(inspector).to_contain_text("Witness for ticket 00")
        expect(inspector).to_contain_text("Quote age at receipt")
        assert [
            path.rsplit("/", 1)[-1] for _, path in requests if "/tickets/" in path
        ] == ["trade-01", "trade-00"]
        expect(inspector).to_contain_text("Away 00 at Home 00")
        assert parse_qs(urlsplit(page.url).query)["trade"] == ["trade-00"]
        page.reload()
        expect(inspector).to_contain_text("Witness for ticket 00")
        page.get_by_role("link", name="Previous", exact=True).click()
        page.get_by_role("link", name="Previous", exact=True).click()
        expect(ledger.locator("a.result-ledger-selection").first).to_have_attribute(
            "href", re.compile("trade=trade-16")
        )
        expect(inspector).to_contain_text("Witness for ticket 00")
        page.get_by_label("Grade", exact=True).select_option("unresolved")
        expect(ledger.locator("tbody tr")).to_have_count(18)
        assert parse_qs(urlsplit(page.url).query)["trade_filter"] == ["unresolved"]
        expect(inspector).not_to_contain_text("Witness for ticket 00")
        assert parse_qs(urlsplit(page.url).query)["trade_page"] == ["1"]
        page.go_back()
        expect(inspector).to_contain_text("Witness for ticket 00")
        page.get_by_label("Screening EV", exact=True).select_option("1/25")
        expect(page.locator(".result-ledger-subset")).to_contain_text("26 of 52 trades")
        expect(page.locator(".result-ledger-subset")).to_contain_text("Staked $130.00")
        page.get_by_role("link", name="Next", exact=True).click()
        expect(ledger.locator("a.result-ledger-selection")).to_have_attribute(
            "href", re.compile("trade=trade-00")
        )
        page.get_by_label("Sort trades").select_option("ev_asc")
        expect(ledger.locator("a.result-ledger-selection").first).to_have_attribute(
            "href", re.compile("trade=trade-00")
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert all(method == "GET" for method, _ in requests)
        assert not errors
        browser.close()
