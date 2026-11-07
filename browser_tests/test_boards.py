"""Exercise the shipped snapshot dashboard with synthetic inputs and intercepted HTTP."""

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

from app.dashboard.snapshot_api import page as result_page
from app.dashboard.snapshot_display import presented
from app.storage.comparison_snapshot import calculate
from tests.test_snapshot_benchmark import execution, inputs, references


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize(
    "back", ["", "//[invalid", "https://outside.invalid/", "javascript:alert(1)"]
)
def test_saved_board_journey(width, back):
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
    state = {"fail": False, "empty": False}
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
            elif url.path.startswith(("/current/assets/", "/view/current/")):
                request.fulfill(path=assets / Path(url.path).name)
            elif url.path == "/api/admin/status":
                request.fulfill(
                    json=dict(sources=[], dispatch_enabled=False, data_runtime={})
                )
            elif url.path == "/api/comparison-current/lease":
                request.fulfill(
                    json=dict(
                        lease_id="fixture-lease", result_id=result["id"], released=True
                    )
                )
            elif url.path == "/api/comparison-current/updates":
                request.fulfill(json=dict(changed=False))
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
                        row=presented(row, {r["id"]: r for r in result["rows"]}),
                        captured_at=result["captured_at"],
                        assumptions=result["assumptions"],
                        originals=[q for q in captured["quotes"] if q["id"] in ids],
                        references=captured["references"],
                    )
                )
            elif url.path in ("/api/comparison-snapshot", "/api/comparison-current"):
                if state["fail"]:
                    request.fulfill(
                        status=503, json={"error": "Temporary read failure"}
                    )
                else:
                    request.fulfill(
                        json=result_page(None if state["empty"] else result, query)
                    )
            elif url.path in ("/", "/odds", "/ev", "/arbs", "/admin"):
                request.fulfill(path=assets / "stored.html")
            else:
                errors.append("Unexpected path: " + url.path)
                request.abort()

        context.route("**/*", route)
        try:
            page.goto(
                "http://board.invalid/odds?"
                + urlencode({"back": back, "result_id": result["id"]})
            )
            expect(page.locator(".compare-group")).to_have_count(2)
            expect(page.locator("#content")).to_contain_text("Pinnacle")
            page.get_by_role("link", name="Opportunities", exact=True).click()
            expect(page.locator(".compare-group")).to_have_count(2)
            page.get_by_role("button", name="Decimal", exact=True).click()
            why = page.locator(".p-why-button").first
            why.focus()
            page.keyboard.press("Enter")
            expect(page.locator(".math-content")).to_contain_text("per $100")
            page.get_by_role("link", name="Inspect exact inputs in Admin").click()
            expect(page.locator(".inspection")).to_contain_text(
                "Exact calculation records"
            )
            expect(
                page.get_by_role("button", name="Decimal", exact=True)
            ).to_have_attribute("aria-pressed", "true")
            page.reload()
            expect(page.locator(".inspection")).to_be_visible()
            expect(
                page.get_by_role("button", name="Decimal", exact=True)
            ).to_have_attribute("aria-pressed", "true")
            page.locator("#back").click()
            expect(page.locator(".compare-group")).to_have_count(2)
            page.keyboard.press("Escape")
            page.locator("#mode").select_option("arbs")
            expect(page.locator(".compare-group")).to_contain_text("Minimum return")
            page.get_by_role("button", name="NFL", exact=True).click()
            expect(page.locator("#content")).to_contain_text("No results match")
            page.get_by_role("button", name="NCAAB", exact=True).click()
            expect(page.locator(".compare-group")).to_have_count(1)
            state["fail"] = True
            page.locator("#refresh-snapshot").click()
            expect(page.get_by_role("status")).to_contain_text("Refresh failed")
            expect(page.locator(".compare-group")).to_have_count(1)
            state["fail"] = False
            page.locator("#latest-snapshot").click()
            expect(page.locator("#status")).to_have_text("")
            page.evaluate("document.documentElement.style.fontSize='20px'")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            # Collection controls live only in Admin; ordinary browsing is read-only.
            expect(page.locator("#stop")).to_have_count(0)
            state["empty"] = True
            page.goto("http://board.invalid/ev")
            expect(page.get_by_role("status")).to_contain_text(
                "No comparisons available"
            )
            expect(page.locator("#refresh-snapshot")).to_be_enabled()
            assert not errors
        finally:
            context.close()
            browser.close()
