"""L04 actual bundle presentation, accessibility and exact-member regression checks.

Intercepted fixtures cannot reach owner SQL or any provider. L03 owns race tests.
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
OUTPUT = Path("test-results/l04/fixture")

# Check visible text against its effective solid background, including disabled
# controls, notice, rank tint and focus actions in both appearances.
CONTRAST = """() => {
 const rgb=s=>(s.match(/[\\d.]+/g)||[]).map(Number);
 const lum=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
 const fails=[];let minimum=99,count=0;
 for(const e of document.querySelectorAll('body *')){
  if(!e.checkVisibility()||!Array.from(e.childNodes).some(n=>n.nodeType===3&&n.textContent.trim()))continue;
  const s=getComputedStyle(e);let bg=null;
  for(let p=e;p;p=p.parentElement){const c=rgb(getComputedStyle(p).backgroundColor);if(c.length===3||c[3]===1){bg=c;break;}}
  if(!bg)continue;const fg=rgb(s.color);if(fg.length<3)continue;
  const a=lum(fg),b=lum(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);minimum=Math.min(minimum,ratio);count++;
  if(ratio<4.5)fails.push({text:e.textContent.slice(0,70),ratio,color:s.color,bg});
 }
 return {minimum,count,fails};
}"""


async def main(output=OUTPUT):
    output.mkdir(parents=True, exist_ok=True)
    rows = [
        source(0, v, value, estimate="2")
        for v, value in [
            ("kalshi", None),
            ("polymarket_us", "0"),
            ("novig", "5"),
            ("prophetx", "-3"),
        ]
    ]
    for r in rows:
        r.update(
            participant_label="Baltimore Ravens",
            game_title="Baltimore Ravens at Jacksonville Jaguars",
            captured_at="2026-11-04T23:00:00Z",
            gross_return_percent="6",
            times={"source_at": "2026-11-04T22:59:00Z"},
            source={"native_market_id": r["id"]},
            probability="1/2",
            cost_per_normal_claim="1/2",
            native_side="Long",
        )
        r["selection"]["label"] = "Baltimore Ravens"
        r["reference"] = {
            "odds": ["1.91", "1.95"],
            "selected": 0,
            "bookmaker": "novig",
        }
        r["reference_calculation"] = {
            "available": True,
            "venue": "novig",
            "selected": 0,
            "probability": "1/2",
            "overround": "1/20",
            "fair_decimal_odds": "2",
            "pair": [
                {
                    "id": f"ref-{i}",
                    "selection": {"label": label, "predicate": "win"},
                    "original": {"value": value, "units": "decimal_odds"},
                }
                for i, label, value in [
                    (0, "Baltimore Ravens", "1.91"),
                    (1, "Jacksonville Jaguars", "1.95"),
                ]
            ],
        }
        r["conditional_trade_benchmark"].update(
            quantity="1",
            quantity_unit="USD normal claim",
            fill_count=1,
            liquidity_role="taker",
            trade_fee_usd="0",
            normalization_risk_usd="1/2",
            scenario_net_usd="1/40",
            formula="Fixture exact fee formula",
            condition="Fixture reviewed schedule",
            evidence={"version": "fixture-review"},
        )
    rows[0]["gross_return_percent"] = None
    rows[0]["probability"] = None
    rows[0]["probability_missing"] = "finance_pending"
    rows[0]["conditional_trade_benchmark"] = {
        "available": False,
        "reason": "finance_pending",
    }
    rows[0]["reference_calculation"]["available"] = False
    rows[0]["current_reasons"] = ["settings_replaced"]
    # Retained member has old math; the displayed withdrawn value must stay null.
    evidence = {r["id"]: deepcopy(r) for r in rows}
    evidence[rows[0]["id"]]["conditional_return_percent"] = "88"
    state = {"mode": "populated", "generation": 1, "rows": rows}
    leases = {}
    errors = []
    results = []

    def result():
        return dict(
            id="root",
            snapshot_id="snapshot",
            generation=state["generation"],
            cursor=str(state["generation"]),
            rows=state["rows"],
            pairs=[],
            references=[],
            games=[],
            assumptions=assumptions({"benchmark_venue": "novig"})[0],
            captured_at="2026-11-04T23:00:00Z",
            publication=dict(state="partial", current_prices=4, retained_prices=0),
        )

    async with async_playwright() as driver:
        browser = await driver.chromium.launch()
        context = await browser.new_context(viewport=dict(width=1280, height=900))

        async def route(req):
            u = urlparse(req.request.url)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            assert u.hostname == "l04.invalid"
            if u.path.startswith(("/current/assets/", "/view/current/")):
                return await req.fulfill(path=str(ASSETS / Path(u.path).name))
            if u.path.endswith("/updates"):
                return await req.fulfill(
                    json=dict(changed=q.get("after") != str(state["generation"]))
                )
            if u.path.endswith("/lease"):
                if req.request.method == "DELETE":
                    assert req.request.headers.get("content-type") == "application/json"
                    leases.pop(q["lease_id"], None)
                    return await req.fulfill(json={"released": True})
                token = "lease-" + str(len(leases) + 1)
                leases[token] = "member"
                return await req.fulfill(json=dict(lease_id=token, result_id="member"))
            if u.path.endswith("/details"):
                return await req.fulfill(
                    json=dict(
                        row=evidence[q["id"]],
                        assumptions=dict(
                            assumptions({"benchmark_venue": "novig"})[0], amount="123"
                        ),
                        originals=[],
                        references=[],
                        result_id="member",
                        evidence_result_id="member",
                        captured_at="2026-11-04T23:00:00Z",
                    )
                )
            if u.path.endswith("/selection"):
                row = next(
                    r
                    for g in page(result(), dict(group="outcome"))["rows"]
                    for r in g["quotes"]
                    if r["id"] == q["id"]
                )
                return await req.fulfill(
                    json=dict(
                        row=row,
                        state="ready",
                        result_id="root",
                        assumptions=assumptions({"benchmark_venue": "novig"})[0],
                    )
                )
            if u.path == "/api/comparison-current":
                if state["mode"] == "error":
                    return await req.fulfill(
                        status=503, json={"reason": "Fixture unavailable"}
                    )
                if state["mode"] == "pending":
                    return await req.fulfill(
                        json=dict(
                            state="initializing",
                            rows=[],
                            generation=state["generation"],
                        )
                    )
                data = result()
                if state["mode"] == "empty":
                    data["rows"] = []
                return await req.fulfill(json=page(data, q))
            assert not u.path.startswith("/api/"), u.path
            return await req.fulfill(
                path=str(ASSETS / "stored.html"), content_type="text/html"
            )

        await context.route("**/*", route)
        tab = await context.new_page()
        tab.on("pageerror", lambda e: errors.append(str(e)))
        await tab.goto("http://l04.invalid/")
        await tab.wait_for_selector(".compare-group")
        assert await tab.locator(".compare-table thead th").count() == 4
        assert await tab.locator(".compare-table tbody tr").count() == 4
        assert (
            await tab.locator(".sets-rank").get_attribute("data-row") == rows[2]["id"]
        )
        assert (
            "Jacksonville Jaguars to win"
            in await tab.locator(".compare-references").inner_text()
        )
        for width, height in [(1280, 900), (600, 602), (390, 844)]:
            await tab.set_viewport_size(dict(width=width, height=height))
            await tab.evaluate("scrollTo(0,0)")
            assert await tab.evaluate(
                "document.documentElement.scrollWidth<=innerWidth"
            )
            for scheme in ["light", "dark"]:
                await tab.emulate_media(color_scheme=scheme, reduced_motion="reduce")
                check = await tab.evaluate(CONTRAST)
                assert not check["fails"], check
                results.append(dict(width=width, scheme=scheme, contrast=check))
                await tab.screenshot(path=str(output / f"list-{width}-{scheme}.png"))
        await tab.set_viewport_size(dict(width=600, height=602))
        await tab.emulate_media(color_scheme="light")
        await tab.locator('[data-row="00000-kalshi"] .p-why-button').click()
        await tab.wait_for_selector(".math-content")
        assert await tab.get_by_role("heading", name="Novig fair price").is_visible()
        assert await tab.locator("#inspection-source option").count() == 4
        assert "88" not in await tab.locator(".math-values").inner_text()
        await tab.get_by_text("Retained arithmetic & exact inputs", exact=True).click()
        assert "$123.00" in await tab.locator(".math-content").inner_text()
        assert "+88.00%" in await tab.locator(".math-content").inner_text()
        await tab.keyboard.press("Escape")
        assert (
            await tab.evaluate(
                "document.activeElement.closest('[data-row]').dataset.row"
            )
            == "00000-kalshi"
        )
        await tab.locator('[data-row="00000-novig"] .p-why-button').click()
        await tab.wait_for_selector(".math-content")
        await tab.locator("#inspection-source").select_option("00000-polymarket_us")
        await tab.wait_for_function(
            "document.querySelector('#inspection-source').value==='00000-polymarket_us' && document.querySelector('.math-price').textContent.includes('Polymarket US')"
        )
        await tab.locator("#inspection-source").select_option("00000-novig")
        await tab.wait_for_function(
            "document.querySelector('.math-price').textContent.includes('Novig')"
        )
        # Reference and fee changes without offered-price movement.
        rows[2]["reference_calculation"]["pair"][0]["original"]["value"] = "1.97"
        rows[2]["probability"] = "51/100"
        rows[2]["conditional_trade_benchmark"]["trade_fee_usd"] = "1/100"
        state["generation"] += 1
        await tab.wait_for_selector("#selection-update")
        notice = await tab.locator("#selection-update").inner_text()
        assert (
            "Novig reference" in notice
            and "1.91" in notice
            and "1.97" in notice
            and "Reviewed fees" in notice
        )
        for scheme in ["light", "dark"]:
            await tab.emulate_media(color_scheme=scheme)
            check = await tab.evaluate(CONTRAST)
            assert not check["fails"], check
            results.append(dict(state="notice", scheme=scheme, contrast=check))
            await tab.screenshot(path=str(output / f"drawer-update-{scheme}.png"))
        await tab.keyboard.press("Escape")
        await tab.get_by_role("button", name="Decimal", exact=True).click()
        assert (
            await tab.locator(".compare-table [data-american]").first.inner_text()
            == "2.00"
        )
        await tab.evaluate("document.documentElement.style.fontSize='200%'")
        await tab.set_viewport_size(dict(width=390, height=844))
        await tab.evaluate("scrollTo(0,0)")
        assert await tab.evaluate("document.documentElement.scrollWidth<=innerWidth")
        await tab.screenshot(path=str(output / "enlarged-390.png"))
        await tab.evaluate("document.documentElement.style.fontSize=''")
        for mode in ["empty", "pending", "error"]:
            state["mode"] = mode
            await tab.reload()
            expected = {
                "empty": "No results match",
                "pending": "Synchronizing sources",
                "error": "Read failed",
            }[mode]
            await tab.get_by_text(expected, exact=False).first.wait_for()
            await tab.screenshot(path=str(output / f"{mode}.png"))
        assert not errors, errors
        await tab.wait_for_timeout(100)
        assert not leases, leases
        (output / "result.json").write_text(
            json.dumps(dict(passed=True, checks=results, errors=errors), indent=2)
        )
        await browser.close()
        print(
            "PASS L04 bundle: four sources, ranking, named references, member assumptions, null economics, source switch, reference/fee notice, contrast, sizes, enlarged text, odds, focus, empty/pending/error"
        )


if __name__ == "__main__":
    asyncio.run(main())
