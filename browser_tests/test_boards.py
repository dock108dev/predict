"""Exercise the shipped snapshot dashboard with synthetic inputs and intercepted HTTP."""

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

from app.dashboard.snapshot_api import page as result_page
from app.storage.comparison_snapshot import calculate
from tests.test_snapshot_benchmark import execution, inputs, references


@pytest.mark.parametrize("width", [1280, 390])
def test_saved_board_journey(width):
    assets = (
        Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
    )
    captured = inputs([execution(), execution("no")], references())
    result = calculate(
        captured,
        {
            "scenario": "decisive_only",
            "sizing": "hypothetical_fractional",
            "fees": {"polymarket_us": "0"},
        },
    )
    state = {"fail": False, "stopped": False, "empty": False}
    errors = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        context = browser.new_context(
            viewport={"width": width, "height": 900}, service_workers="block"
        )
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))

        def route(request):
            url = urlparse(request.request.url)
            query = dict(parse_qsl(url.query))
            if url.hostname != "board.invalid":
                errors.append("Unexpected external request")
                request.abort()
            elif url.path.startswith("/current/assets/"):
                request.fulfill(path=assets / Path(url.path).name)
            elif url.path == "/api/admin/current":
                assert request.request.post_data_json == {"action": "stop"}
                state["stopped"] = True
                request.fulfill(json={"stopped": True})
            elif url.path == "/api/comparison-snapshot/details":
                assert query["result_id"] == result["id"]
                row = next(
                    r
                    for r in result["rows"] + result["pairs"]
                    if r["id"] == query["id"]
                )
                ids = row.get("legs", [row["id"]])
                request.fulfill(
                    json=dict(
                        result_id=result["id"],
                        snapshot_id=result["snapshot_id"],
                        row=row,
                        captured_at=result["captured_at"],
                        assumptions=result["assumptions"],
                        originals=[q for q in captured["quotes"] if q["id"] in ids],
                        references=captured["references"],
                    )
                )
            elif url.path == "/api/comparison-snapshot":
                if state["fail"]:
                    request.fulfill(
                        status=503, json={"error": "Temporary read failure"}
                    )
                else:
                    request.fulfill(
                        json=result_page(None if state["empty"] else result, query)
                    )
            elif url.path in ("/odds", "/ev", "/arbs"):
                request.fulfill(path=assets / "stored.html")
            else:
                errors.append("Unexpected path: " + url.path)
                request.abort()

        context.route("**/*", route)
        try:
            page.goto("http://board.invalid/odds")
            expect(page.locator(".odds-grid tr")).to_have_count(3)
            expect(page.locator(".odds-grid")).to_contain_text("Pinnacle")
            page.get_by_role("link", name="EV", exact=True).click()
            expect(page.locator("article")).to_have_count(2)
            details = page.get_by_role("button", name="Details").first
            details.click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_contain_text("Pinnacle Original 1")
            page.keyboard.press("Escape")
            expect(details).to_be_focused()
            page.get_by_role("link", name="Opposing-outcome scenarios").click()
            expect(page.locator("article")).to_contain_text("Assumed scenario minimum")
            page.locator("#league").select_option("NFL")
            expect(page.locator("#content")).to_contain_text("No comparisons match")
            page.locator("#league").select_option("NCAAB")
            expect(page.locator("article")).to_have_count(1)
            state["fail"] = True
            page.locator("#refresh-snapshot").click()
            expect(page.get_by_role("status")).to_contain_text("Refresh failed")
            expect(page.locator("article")).to_have_count(1)
            state["fail"] = False
            page.locator("#latest-snapshot").click()
            expect(page.get_by_role("status")).to_contain_text("Captured")
            page.evaluate("document.documentElement.style.fontSize='20px'")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.locator("#stop").click()
            expect(page.get_by_role("status")).to_contain_text("Collection stopped")
            assert state["stopped"]
            state["empty"] = True
            page.goto("http://board.invalid/ev")
            expect(page.get_by_role("status")).to_contain_text(
                "No comparison snapshot yet"
            )
            expect(page.locator("#refresh-snapshot")).to_be_enabled()
            assert not errors
        finally:
            context.close()
            browser.close()
