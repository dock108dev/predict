"""Checkpoint comparisons through normal clicks, missing plots and fixed exports."""

from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_tests.test_pregame_current import ASSETS
from browser_tests.test_research_workspace import research_http_fixture


@pytest.mark.parametrize(
    "width,scale",
    [(1440, 1), (390, 1), (960, 1.5)],
    ids=["desktop", "mobile", "zoom150-equivalent"],
)
def test_exact_checkpoint_comparison_context_and_captured_download(
    width, scale, tmp_path
):
    fixture = json.loads(Path("tests/fixtures/experiment-workspace.json").read_text())
    requests, errors = [], []
    state = dict(revision=fixture["detail"]["revision"], exports=0)

    def serve(route):
        url = urlparse(route.request.url)
        query = {key: value[0] for key, value in parse_qs(url.query).items()}
        requests.append((route.request.method, url.path, query))
        if url.path == "/api/research/experiment":
            if query.get("id"):
                if query.get("revision") != state["revision"]:
                    route.fulfill(
                        json=dict(
                            error="Checkpoint evidence changed; refresh comparisons."
                        ),
                        status=409,
                    )
                elif query.get("export") == "1":
                    state["exports"] += 1
                    route.fulfill(
                        json=fixture["export"],
                        headers={
                            "Content-Disposition": 'attachment; filename="predict-early-late-game.json"'
                        },
                    )
                else:
                    route.fulfill(json=fixture["detail"])
            else:
                value = deepcopy(fixture["listing"])
                if not query.get("include_context"):
                    assert all(row["retain_case"] for row in value["cases"])
                route.fulfill(json=value)
        elif url.path == "/api/research/catalog":
            route.fulfill(
                json=dict(
                    token="catalog-read",
                    rows=[],
                    total=0,
                    counts=dict(source_events=0),
                    offset=0,
                    next_offset=None,
                    captured_at="2026-11-22T20:00:00Z",
                    population="Received source records",
                )
            )
        elif url.path == "/api/research/read":
            route.fulfill(json=dict(released=True))
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/data":
            route.fulfill(path=ASSETS / "data.html")
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        context = browser.new_context(
            viewport=dict(width=width, height=round(1000 / scale)),
            device_scale_factor=scale,
            accept_downloads=True,
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/data?evidence=checkpoints&context=0")
        expect(page.locator("#experiment-status")).to_contain_text("4 retained cases")
        expect(page.locator("#experiment-cases [data-case]")).to_have_count(4)
        expect(page.locator("#experiment-cases")).to_contain_text(
            "positive to negative"
        )
        expect(page.locator("#experiment-cases")).to_contain_text(
            "negative to positive"
        )
        expect(page.locator("#experiment-cases")).to_contain_text("incomplete positive")
        expect(page.locator("#experiment-cases")).not_to_contain_text(
            "negative to negative"
        )
        page.locator('#experiment-cases [data-case="case-pn"]').click()
        dialog = page.locator("#experiment-detail")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("Screening exact EV")
        expect(dialog).to_contain_text("Coherent exact EV")
        expect(dialog).to_contain_text(
            "early offer using the late probability reference"
        )
        expect(dialog).to_contain_text("synthetic_fixture_fee")
        expect(dialog).to_contain_text("main to alternate")
        expect(dialog).to_contain_text("alternate to main")
        expect(dialog).to_contain_text("source_reported")
        expect(dialog).to_contain_text("inferred")
        expect(dialog).not_to_contain_text("[object Object]")
        expect(dialog.locator(".experiment-plot svg")).to_have_count(3)
        expect(dialog.locator("[data-main=source_reported]")).to_have_count(6)
        # Unknown fees remove EV while the retained offered price and reference
        # probability remain known: 3 EV gaps, 1 price gap and 1 probability gap.
        assert dialog.locator("[data-missing=true]").count() == 5
        assert dialog.locator("svg polyline, svg path:not([data-missing])").count() == 0
        expect(dialog.locator("#experiment-plot-period")).to_have_value("full_game")
        expect(dialog).to_contain_text("Complete market established")
        expect(dialog).to_contain_text("selection_biased")
        dialog.locator("#experiment-plot-book").select_option("fanduel")
        expect(dialog.locator(".experiment-plot svg")).to_have_count(1)
        expect(dialog.locator(".experiment-plot")).to_contain_text(
            "Offered decimal price"
        )
        expect(dialog).to_contain_text(
            "Reference only: offered-price observations"
        )
        dialog.locator('[data-context="reference-fd-1"]').click()
        expect(dialog).to_contain_text("fanduel-early--3")
        expect(dialog).to_contain_text("fanduel-late--3")
        dialog.locator("#experiment-plot-book").select_option("kalshi")

        link = dialog.get_by_role(
            "link", name="Export this captured game & all dependencies"
        )
        expect(link).to_be_visible()
        bounds = link.evaluate("""link=>{
          const box=link.getBoundingClientRect(), outer=link.closest('dialog').getBoundingClientRect();
          return {fragments:link.getClientRects().length,left:box.left,right:box.right,outerLeft:outer.left,outerRight:outer.right};
        }""")
        assert bounds["fragments"] == 1
        assert bounds["left"] >= bounds["outerLeft"]
        assert bounds["right"] <= bounds["outerRight"]

        # A later checkpoint/outcome revision must not change the prepared file.
        state["revision"] = "b" * 64
        with page.expect_download() as download:
            link.click()
        exported = json.loads(Path(download.value.path()).read_text())
        assert exported == fixture["export"]
        assert exported["revision"] == fixture["detail"]["revision"]
        assert (
            exported["dependencies"][0]["payload"]["record"]["quote"]["original"][
                "value"
            ]
            == "+120"
        )
        assert exported["manifest"]["shared_dependency_count"] == 1
        assert exported["provider_requests"] == 0
        assert state["exports"] == 1

        dialog.locator("#experiment-plot-policy").select_option("coherent")
        expect(dialog.locator(".experiment-plot").first).to_contain_text("Coherent EV")
        expect(dialog.locator(".experiment-plot").first).to_contain_text("Missing")
        page.screenshot(
            path=str(tmp_path / f"experiment-inspector-{width}.png"), full_page=True
        )
        dialog.get_by_role("button", name="Close comparison").click()
        expect(dialog).not_to_be_visible()

        page.locator("#experiment-context").check()
        expect(page.locator("#experiment-games")).to_contain_text(
            "Inspect market context"
        )
        page.locator("#experiment-games button").click()
        expect(dialog).to_contain_text("refresh comparisons")
        dialog.get_by_role("button", name="Close comparison").click()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(
            path=str(tmp_path / f"experiment-retained-{width}.png"), full_page=True
        )
        assert not errors
        assert all(method in ("GET", "DELETE") for method, _, _ in requests)
        assert not any(
            path.startswith("/api/") and ("acquire" in path or "capture" in path)
            for _, path, _ in requests
        )
        browser.close()
