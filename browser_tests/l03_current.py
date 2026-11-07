"""Authored current-API browser races; routes cannot reach providers or owner SQL.

Run: .venv/bin/python -m browser_tests.l03_current
"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright
from app.dashboard.snapshot_api import page
from app.comparison.snapshot_math import assumptions
from tests.test_l03_ranking import source

ASSETS = Path("app/dashboard/opportunity_static/current")
OUTPUT = Path("test-results/l03/browser-fixture")


async def main(output=OUTPUT):
    output.mkdir(parents=True, exist_ok=True)
    rows = [
        source(i, v, str(100 - i))
        for i in range(60)
        for v in ("novig", "polymarket_us")
    ]
    for r in rows:
        r.update(
            captured_at="2026-11-04T23:00:00Z",
            times=dict(received_at="2026-11-04T23:00:00Z"),
            source=dict(provider=r["venue"], native_market_id=r["id"]),
            economic_revision="econ-1",
        )
    state = dict(generation=1, rows=rows, removed=False, unavailable=False)
    evidence = {
        r["evidence_result_id"]: {
            q["id"]: deepcopy(q)
            for q in rows
            if q["evidence_result_id"] == r["evidence_result_id"]
        }
        for r in rows
    }
    leases = {}
    events = []
    errors = []
    token_count = 0
    slow = asyncio.Event()
    held = asyncio.Event()

    def result():
        return dict(
            id=f"root-{state['generation']}",
            generation=state["generation"],
            cursor=str(state["generation"]),
            rows=state["rows"],
            pairs=[],
            references=[],
            games=[],
            captured_at="2026-11-04T23:00:00Z",
            assumptions=assumptions()[0],
            publication=dict(
                state="partial", current_prices=len(rows), retained_prices=0
            ),
        )

    async with async_playwright() as driver:
        browser = await driver.chromium.launch(headless=True)
        context = await browser.new_context(viewport=dict(width=1280, height=900))

        async def route(req):
            nonlocal token_count
            url = urlparse(req.request.url)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            assert url.hostname == "l03.invalid", (
                "Fixture never reaches installed app or external host"
            )
            if url.path.startswith("/current/assets/"):
                return await req.fulfill(path=str(ASSETS / Path(url.path).name))
            if url.path == "/api/comparison-current/updates":
                return await req.fulfill(
                    json=dict(
                        changed=q.get("after") != str(state["generation"]),
                        cursor=str(state["generation"]),
                        generation=state["generation"],
                    )
                )
            if url.path == "/api/comparison-current/selection":
                r = next((r for r in state["rows"] if r["id"] == q["id"]), None)
                return await req.fulfill(
                    json=dict(
                        result_id=result()["id"],
                        generation=state["generation"],
                        cursor=str(state["generation"]),
                        row=None if state["removed"] else r,
                        state="removed"
                        if state["removed"]
                        else "unavailable"
                        if state["unavailable"]
                        else "ready",
                        assumptions=assumptions()[0],
                    )
                )
            if url.path == "/api/comparison-current/lease":
                if req.request.method == "DELETE":
                    assert req.request.headers.get("content-type") == "application/json"
                    leases.pop(q["lease_id"], None)
                    events.append("release")
                    return await req.fulfill(json={"released": True})
                body = req.request.post_data_json
                token_count += 1
                token = f"token-{token_count}"
                leases[token] = body["result_id"]
                events.append("retain")
                return await req.fulfill(
                    json=dict(lease_id=token, result_id=body["result_id"])
                )
            if url.path == "/api/comparison-snapshot/details":
                events.append("details")
                return await req.fulfill(
                    json=dict(
                        result_id=q["result_id"],
                        evidence_result_id=q["result_id"],
                        row=evidence[q["result_id"]][q["id"]],
                        captured_at="2026-11-04T23:00:00Z",
                        assumptions=assumptions()[0],
                        originals=[],
                        references=[],
                    )
                )
            if url.path == "/api/comparison-current":
                v = result()
                if (
                    int(q.get("offset", "0"))
                    and q.get("expected_cursor") != v["cursor"]
                ):
                    return await req.fulfill(
                        json=dict(
                            state="page_changed",
                            rows=[],
                            generation=v["generation"],
                            cursor=v["cursor"],
                        )
                    )
                answer = page(v, q)
                if q.get("search") == "Game 1":
                    held.set()
                    await slow.wait()
                return await req.fulfill(json=answer)
            assert not url.path.startswith("/api/"), url.path
            return await req.fulfill(
                path=str(ASSETS / "stored.html"), content_type="text/html"
            )

        await context.route("**/*", route)
        tab = await context.new_page()
        tab.on("pageerror", lambda e: errors.append(str(e)))
        await tab.goto("http://l03.invalid/")
        await tab.wait_for_selector(".compare-group")
        assert await tab.locator("#sort").input_value() == "conditional_return_percent"
        await tab.locator(".p-why-button").first.click()
        await tab.wait_for_selector("#math-inspection[data-evidence-result-id]")
        member = await tab.locator("#math-inspection").get_attribute(
            "data-evidence-result-id"
        )
        selected = state["rows"][0]["id"]
        # New source price and independent reference economics, preserving exact ID.
        r = deepcopy(state["rows"][0])
        r.update(
            economic_revision="reference-2",
            price_revision="price-2",
            evidence_result_id="new-member",
            conditional_return_percent="-20",
        )
        r["original"]["value"] = "1.5"
        state["rows"][0] = r
        evidence["new-member"] = {selected: deepcopy(r)}
        state["generation"] = 2
        await tab.wait_for_function("document.body.dataset.publicationGeneration==='2'")
        await tab.wait_for_selector("#selection-update")
        assert (
            await tab.locator("#math-inspection").get_attribute(
                "data-evidence-result-id"
            )
            == member
        )
        assert (
            "+100.00% → -20.00%" in await tab.locator("#selection-update").inner_text()
        )
        # Confirmation-only head keeps the notice DOM and user focus intact.
        await tab.locator("#adopt-selection").focus()
        await tab.locator("#selection-update").evaluate(
            '(e)=>e.dataset.retainedMarker="yes"'
        )
        state["generation"] = 3
        await tab.wait_for_function("document.body.dataset.publicationGeneration==='3'")
        await tab.wait_for_timeout(100)
        assert (
            await tab.locator("#selection-update").get_attribute("data-retained-marker")
            == "yes"
        )
        assert await tab.evaluate("document.activeElement.id") == "adopt-selection"
        events.clear()
        await tab.locator("#adopt-selection").click()
        await tab.wait_for_function(
            "document.querySelector('#math-inspection').dataset.evidenceResultId==='new-member'"
        )
        await tab.wait_for_timeout(100)
        assert events.index("details") < events.index("release")
        assert len(leases) == 1
        state["unavailable"] = True
        state["generation"] = 4
        await tab.wait_for_function("document.body.dataset.publicationGeneration==='4'")
        # Actual withdrawal changes authority facts even without a new member.
        r["price_current"] = False
        r["current_reasons"] = ["updates_stopped"]
        state["generation"] = 5
        await tab.wait_for_selector("#adopt-selection[disabled]")
        assert (
            "unavailable"
            in (await tab.locator("#selection-update").inner_text()).lower()
        )
        await tab.keyboard.press("Escape")
        await tab.wait_for_selector("#math-inspection", state="detached")
        assert await tab.evaluate(
            "document.activeElement.matches('.p-why-button,#content')"
        )
        # Slow old response cannot overwrite a later search in the same generation.
        await tab.locator("#search").fill("Game 1")
        await asyncio.wait_for(held.wait(), 5)
        await tab.locator("#search").fill("Game 2")
        await tab.wait_for_timeout(500)
        await tab.wait_for_function(
            "document.querySelector('.p-game')?.textContent==='Game 2'"
        )
        slow.set()
        await tab.wait_for_timeout(300)
        assert await tab.locator(".p-game").first.inner_text() == "Game 2"
        await tab.locator("#search").fill("")
        await tab.wait_for_timeout(500)
        await tab.get_by_role("button", name="Next", exact=True).click()
        await tab.wait_for_function(
            "new URL(location.href).searchParams.get('offset')==='25'"
        )
        state["generation"] = 6
        await tab.get_by_role("button", name="Next", exact=True).click()
        await tab.wait_for_function(
            "new URL(location.href).searchParams.get('offset')==='0'"
        )
        assert await tab.locator(".compare-group").count() == 25
        assert not errors, errors
        await tab.screenshot(path=str(output / "coherent-page.png"))
        await tab.wait_for_timeout(100)
        assert not leases
        (output / "result.json").write_text(
            json.dumps(
                dict(
                    passed=True,
                    checks=[
                        "default fees",
                        "exact pin",
                        "list advancement",
                        "material old/latest",
                        "confirmation suppression",
                        "atomic adoption",
                        "withdrawal",
                        "Escape focus",
                        "concurrent responses",
                        "pagination reset",
                        "lease release",
                    ],
                    errors=errors,
                ),
                indent=2,
            )
        )
        await browser.close()
        print(
            "PASS L03 browser: live list, pinned context, explicit adoption, controls, focus, response and pagination races"
        )


if __name__ == "__main__":
    asyncio.run(main())
