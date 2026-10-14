"""Ordinary frontend journey with all traffic intercepted; no owner/provider state."""

from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width", [1280, 390])
def test_saved_board_journey(width):
    fixture = json.loads((ROOT / "tests/fixtures/ev09-u01-responses.json").read_text())
    state = {"mode": "normal", "stopped": False}
    errors = []
    assets = ROOT / "app/dashboard/opportunity_static/current"
    with sync_playwright() as driver:
        options = {"headless": True}
        if os.environ.get("PREDICT_CI_CHROMIUM"):
            options["executable_path"] = os.environ["PREDICT_CI_CHROMIUM"]
        browser = driver.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": width, "height": 900},
            timezone_id="America/New_York",
            service_workers="block",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request):
            u = urlparse(request.request.url)
            if u.hostname != "board.invalid":
                errors.append("Unexpected external browser request")
                request.abort()
                return
            query = parse_qs(u.query)
            if u.path.startswith("/current/assets/"):
                name = Path(u.path).name
                request.fulfill(
                    path=str(assets / name),
                    content_type="text/javascript"
                    if name.endswith(".js")
                    else "text/css",
                )
                return
            if not u.path.startswith("/api/"):
                request.fulfill(
                    path=str(assets / "stored.html"), content_type="text/html"
                )
                return
            if u.path == "/api/admin/current":
                assert json.loads(request.request.post_data)["action"] == "stop"
                state["stopped"] = True
                request.fulfill(json={"stopped": True})
                return
            view = u.path.rsplit("/", 1)[-1]
            if state["mode"] == "failure":
                request.fulfill(
                    status=503, json={"error": "Saved reads temporarily unavailable"}
                )
                return
            if view == "details":
                value = fixture["pair" if "pair" in query else "single"]
            else:
                assert view == "slate"
                view = query["view"][0]
                value = deepcopy(fixture[view])
                value["filter"] = query["filter"][0]
                if view != "odds" and value["filter"] != "all":
                    value["rows"] = [
                        r
                        for r in value["rows"]
                        if r["classification"][
                            "positive_rule_sensitive_eligible"
                            if value["filter"] == "hedges"
                            else "main_positive_eligible"
                        ]
                    ]
                value["empty_reason"] = (
                    "No positive EV found"
                    if view == "ev"
                    else "No estimated arbitrage found"
                )
                if state["stopped"]:
                    value["delivery_state"] = "stopped"
                value = dict(
                    version="predict-comparison-slate-1",
                    view=view,
                    filter=query["filter"][0],
                    policy=value["policy"],
                    games=[]
                    if state["mode"] == "empty"
                    else fixture["catalog"]["games"],
                    boards=[] if state["mode"] == "empty" else [value],
                    stopped=state["stopped"],
                    as_of=value["read_at"],
                    bounds=dict(maximum_games=200, maximum_bytes=8388608),
                )
            request.fulfill(json=value)

        context.route("**/*", route)
        try:
            page.goto("http://board.invalid/")
            page.wait_for_selector(".team")
            assert page.locator(".team").count() == 2
            page.goto("http://board.invalid/ev")
            page.wait_for_selector(".empty")
            page.get_by_role("button", name="Show all comparisons", exact=True).click()
            page.wait_for_selector(".slate-result")
            page.locator(
                'button[data-key="'
                + fixture["ev"]["game_key"]
                + ":"
                + fixture["single"]["quote"]["id"]
                + '"]'
            ).click()
            page.wait_for_selector("#detail-content dl")
            page.keyboard.press("Shift+Tab")
            assert page.evaluate(
                "document.getElementById('details').contains(document.activeElement)"
            )
            page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement.id") == "close-details"
            page.keyboard.press("Escape")
            assert (
                page.evaluate("document.activeElement.dataset.key")
                == fixture["ev"]["game_key"] + ":" + fixture["single"]["quote"]["id"]
            )
            page.goto("http://board.invalid/arbs")
            page.wait_for_selector(".empty")
            page.get_by_role("button", name="Show all comparisons", exact=True).click()
            page.wait_for_selector(".slate-arb .metric")
            page.locator(
                'button[data-key="'
                + fixture["arbs"]["game_key"]
                + ":"
                + fixture["pair"]["pair"]["id"]
                + '"]'
            ).click()
            page.wait_for_selector("#detail-content dl")
            page.keyboard.press("Escape")
            state["mode"] = "failure"
            page.reload()
            page.wait_for_selector("#retry:not([hidden])")
            state["mode"] = "normal"
            page.locator("#retry").click()
            page.wait_for_selector(".empty")
            page.get_by_role("button", name="Show all comparisons", exact=True).click()
            page.wait_for_selector(".slate-arb")
            page.evaluate("document.documentElement.style.fontSize='20px'")
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.locator("#stop").click()
            page.wait_for_function(
                "document.getElementById('status').textContent.includes('Collection stopped')"
            )
            assert page.locator("#stop").is_disabled()
            state["mode"] = "empty"
            page.reload()
            page.wait_for_selector(".empty")
            assert not page.locator("#settings").is_visible()
            assert (
                page.get_by_role("link", name="Check sources in Admin").get_attribute(
                    "href"
                )
                == "/admin"
            )
            assert not errors
        except Exception:
            target = ROOT / "test-results/browser"
            target.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target / f"failure-{width}.png"))
            raise
        finally:
            context.close()
            browser.close()
