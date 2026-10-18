"""Ordinary frontend journey with all traffic intercepted; no owner/provider state."""

from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest
from playwright.sync_api import expect, sync_playwright

from app.comparison.calculation_availability import (
    combine,
    result_availability,
    summary,
)

ROOT = Path(__file__).resolve().parents[1]


def current_fixture():
    """Bind retained examples to the current transport contract at their saved clocks."""
    fixture = json.loads((ROOT / "tests/fixtures/ev09-u01-responses.json").read_text())
    game = fixture["ev"]["game_key"]
    identity = dict(
        context_id="authored-context:" + game,
        epoch="authored-reset-1",
        dependency_revision=fixture["ev"]["input_version"],
        policy_revision=fixture["ev"]["policy"]["revision"],
        engine_binding="authored-engine-1",
    )
    for view in ("odds", "ev", "arbs"):
        value = fixture[view]
        value["version"] = "predict-comparison-board-2"
        value["calculation_context"] = dict(
            identity, dependency_revision=value["input_version"]
        )
        for key in ("result_id", "snapshot_id"):
            value.pop(key, None)
        for quote in value["prices"]:
            quote["inputs_identity"].update(
                context_id=identity["context_id"], game_key=game
            )
        availability_items = []
        for row in value["rows"]:
            if view != "odds":
                row["availability"] = result_availability(row, pair=view == "arbs")
                venues = (
                    [leg["venue"] for leg in row["legs"]]
                    if view == "arbs"
                    else [row["venue"]]
                )
                if view != "arbs" or len(set(venues)) == 2:
                    availability_items.append((game, venues, row["availability"]))
            if "details" in row:
                for key in ("result_id", "snapshot_id"):
                    row["details"].pop(key, None)
                row["details"]["context_id"] = identity["context_id"]
        value["availability"] = summary(availability_items, evaluated=view != "odds")
    for kind in ("single", "pair"):
        value = fixture[kind]
        value.update(
            version="predict-board-details-2",
            game_key=game,
            calculation_context=identity,
        )
        for key in ("result_id", "snapshot_id"):
            value.pop(key, None)
            value["original_inputs_identity"].pop(key, None)
        value["original_inputs_identity"]["context_id"] = identity["context_id"]
    return fixture


@pytest.mark.parametrize("width", [1280, 390])
def test_saved_board_journey(width):
    fixture = current_fixture()
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
                assert (
                    query["context_id"][0] == value["calculation_context"]["context_id"]
                )
                assert "result_id" not in query
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
                    version="predict-comparison-slate-2",
                    epoch="authored-reset-1",
                    read_revision="authored-read-1",
                    read_token="authored-browser-read-0001",
                    read_at=value["read_at"],
                    read_expires_at="2026-10-14T01:16:09.650084+00:00",
                    view=view,
                    filter=query["filter"][0],
                    policy=value["policy"],
                    games=[]
                    if state["mode"] == "empty"
                    else fixture["catalog"]["games"],
                    boards=[] if state["mode"] == "empty" else [value],
                    availability=combine(
                        [] if state["mode"] == "empty" else [value["availability"]],
                        games=0 if state["mode"] == "empty" else 1,
                        evaluated=view != "odds",
                    ),
                    stopped=state["stopped"],
                    as_of=value["read_at"],
                    bounds=dict(
                        maximum_games=500, maximum_page_games=50, maximum_bytes=8388608
                    ),
                    coverage=dict(
                        total_games=0
                        if state["mode"] == "empty"
                        else len(fixture["catalog"]["games"]),
                        offset=0,
                        limit=50,
                        returned_games=0
                        if state["mode"] == "empty"
                        else len(fixture["catalog"]["games"]),
                        next_offset=None,
                        complete=True,
                    ),
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
            pair_key = fixture["arbs"]["game_key"] + ":" + fixture["pair"]["pair"]["id"]
            pair_row = page.locator(f'.slate-arb[data-key="{pair_key}"]')
            expect(pair_row).to_have_attribute(
                "data-metric", "buffered_decisive_opposing_margin_usd"
            )
            expect(pair_row.locator(".metric small")).to_have_text(
                "Margin · decisive outcomes only"
            )
            expect(pair_row.locator(".metric strong")).to_have_text("-2.32%")
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
