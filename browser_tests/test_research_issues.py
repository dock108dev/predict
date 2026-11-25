"""Read a retained issue decision through Data and its export."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_tests.test_pregame_current import ASSETS
from browser_tests.test_research_workspace import research_http_fixture


@pytest.mark.parametrize("width", [390, 1366])
def test_data_exposes_saved_issue_decisions_and_evidence_read_only(width):
    date, clock = "2026-11-23", "2026-11-24T22:00:00Z"
    endpoint = "/api/workspace/mens-d1"
    errors = []
    decision = dict(id="decision-1", actor="signed-in user", decided_at=clock,
                    status="accepted_source_limitation", reason="Reviewed the original provider response.",
                    evidence_revision="evidence-revision-a",
                    evidence=[dict(label="Reviewed original receipt", url="/original-receipt")])
    deep_link = f"/data?evidence=mens-d1&scope=mens-d1&date={date}#mens-d1-issues"

    def issue():
        return dict(
            id="capture-issue",
            kind="capture",
            game_id="game-a",
            game_title="Road at Home",
            title="Limited venue inventory",
            reason="The source cannot verify full venue inventory.",
            evidence_revision="evidence-revision-a",
            evidence=[],
            status=decision["status"], latest_decision_id=decision["id"], history=[decision],
        )

    def serve(route):
        parsed = urlsplit(route.request.url)
        params = parse_qs(parsed.query)
        if parsed.path == "/data":
            route.fulfill(path=ASSETS / "data.html")
        elif parsed.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(parsed.path).name)
        elif parsed.path == "/api/workspace/status":
            route.fulfill(json={})
        elif parsed.path == endpoint:
            summary = dict(
                population={},
                capture={},
                markets={},
                reference={},
                trade=dict(variants={}),
                reconciliation=dict(
                    cohort_name="Retained observed cohort",
                    reviewed_games=1,
                    usable_games=0,
                    frozen_games=0,
                    reconstructed_games=0,
                    games_with_trades=0,
                    games_without_qualifiers=0,
                    historical_gaps=1,
                    finals=1,
                    excluded_games=0,
                    other_date_games=1,
                    exhaustive_slate=False,
                ),
            )
            games = [
                dict(
                    id="game-a",
                    title="Road at Home",
                    capture=dict(state="missed"),
                    research_scope="eligible",
                    facets=["result_ledger"],
                ),
                dict(
                    id="game-b",
                    title="Next Eastern date",
                    capture=dict(state="no_task"),
                    research_scope="other_date",
                    facets=["other_date"],
                ),
            ]
            value = dict(
                date=date,
                as_of=clock,
                source_state="active",
                issues=[issue()],
                coverage_summary=summary,
                facets=dict(result_ledger=1, other_date=1),
                offer_counts={},
                games=games,
            )
            headers = (
                {"Content-Disposition": 'attachment; filename="coverage.json"'}
                if params.get("export")
                else {}
            )
            route.fulfill(json=value, headers=headers)
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        context = browser.new_context(viewport={"width": width, "height": 820})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + deep_link)
        ledger = page.locator("#mens-d1-issues")
        ledger.get_by_role("button", name="Accepted and resolved (1)").click()
        ledger.locator(".issue-entry > summary").filter(
            has_text="Road at Home · Limited venue inventory"
        ).click()
        ledger.get_by_text("Decision history · 1", exact=True).click()
        expect(ledger.get_by_role("link", name="Reviewed original receipt")).to_have_attribute(
            "href", base + "/original-receipt"
        )
        expect(ledger.get_by_text("Record a decision", exact=True)).to_have_count(0)
        expect(
            page.get_by_role("link", name="Next Eastern date", exact=False)
        ).to_have_count(0)
        page.get_by_role(
            "link", name="Show all retained occurrence audit rows", exact=True
        ).click()
        expect(
            page.get_by_role("link", name="Next Eastern date", exact=False)
        ).to_be_visible()
        page.go_back()
        expect(
            page.get_by_role("link", name="Next Eastern date", exact=False)
        ).to_have_count(0)

        with page.expect_download() as download:
            page.get_by_role(
                "link", name="Export dated game and coverage ledger"
            ).click()
        exported = json.loads(Path(download.value.path()).read_text())
        assert exported["issues"][0]["history"] == [decision]
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        browser.close()
