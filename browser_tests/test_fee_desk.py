"""Exercise the ordinary fee desk at two widths with intercepted API responses."""

import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.comparison.inspection_math import offer_math
from app.comparison.snapshot_fee_outcome import outcome
from app.comparison.snapshot_math import before_fee_pair
from app.dashboard.trade_desk import offer, page
from tests.test_f07_desk import paired
from tests.test_f06_prophetx_retail import AT, retail_row, review
from tests.test_trade_desk import result

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


def data():
    terms = review.__wrapped__()
    old, other = paired("NHL", terms)
    old.update(
        price_revision="old-price",
        economic_revision="old-fee-ref",
        evidence_result_id="old",
        exact_pinnacle_reference_current=False,
    )
    latest = dict(
        retail_row("NHL", "0.10"),
        price_revision="new-price",
        economic_revision="new-fee-ref",
        evidence_result_id="latest",
        exact_pinnacle_reference_current=True,
    )
    latest.update(
        trade_fee=outcome(latest, at=AT, phase="scheduled", review=terms),
        reference=dict(bookmaker="pinnacle", odds=["8", "1.12"], selected=0),
        reference_calculation=dict(
            available=True,
            selected=0,
            probability="7/57",
            fair_decimal_odds="57/7",
            conditioning="Completed-game outcomes",
            overround="1/56",
            pair=[dict(original=dict(value=value)) for value in ("8", "1.12")],
        ),
    )
    stale = dict(
        retail_row("NBA", "0.62"),
        id="expired",
        price_revision="stale",
        economic_revision="stale",
        evidence_result_id="stale",
        exact_pinnacle_reference_current=False,
    )
    stale["trade_fee"] = outcome(
        stale,
        at=AT,
        phase="scheduled",
        review=dict(terms, review_before=AT.isoformat()),
    )
    commission = dict(
        retail_row("NBA", "0.40"),
        id="commission",
        price_revision="commission",
        economic_revision="commission",
        evidence_result_id="commission",
        exact_pinnacle_reference_current=False,
    )
    commission["trade_fee"] = outcome(
        commission, at=AT, phase="scheduled", review=terms
    )
    ev = page(result(old, stale, commission), {}, ("ev", None, 0, 25))
    proof = before_fee_pair(old, other, "pair-a")
    arb_input = dict(old, id="pair-a", legs=[old["id"], other["id"]], before_fees=proof)
    incomplete = deepcopy(arb_input)
    missing = dict(other, id="missing-fee", trade_fee=stale["trade_fee"])
    incomplete.update(
        id="pair-b",
        legs=[old["id"], missing["id"]],
        before_fees=dict(proof, market_key="pair-b"),
    )
    arbs = page(
        result(old, other, missing),
        {"stake": "100"},
        ("arbs", None, 0, 25),
        captured_pairs=[arb_input, incomplete],
        policy="policy",
    )
    details = {
        r["id"] + ":" + r["evidence_result_id"]: dict(
            row=r, inspection=offer_math(r), captured_at=AT.isoformat()
        )
        for r in (old, latest, stale, commission)
    }
    census = dict(
        read_at=AT.isoformat(),
        total=dict(
            covered=3,
            current=4,
            fee_coverage_percent=75,
            exact_pinnacle_reference=2,
            sportsbook_ev=3,
            before_fee_ev=2,
            reviewed_after_fee_ev=0,
            conservative_after_fee_ev=1,
            any_after_fee_ev=1,
            retained_unavailable=12,
        ),
        published_working_prices=8,
        unpublished_working_prices=5,
        coverage_complete=False,
        missing_reasons={"conditional_fee_review_expired_or_not_effective": 1},
        provider_requests=0,
    )
    return ev, arbs, offer(latest), details, census


def run(browser, width, output):
    from playwright.sync_api import expect

    ev, arbs, latest, details, census = data()
    context = browser.new_context(
        viewport={"width": width, "height": 980},
        accept_downloads=True,
        service_workers="block",
    )
    tab = context.new_page()
    errors = []
    schedule_unavailable = False
    tab.on("pageerror", lambda error: errors.append(str(error)))

    def fulfill(route):
        url = urlparse(route.request.url)
        params = parse_qs(url.query)
        path = url.path
        if path == "/api/admin/fee-schedules" and schedule_unavailable:
            route.fulfill(status=503, json={"reason": "Fixture schedule failure"})
            return
        body = {
            "/api/comparison-current": arbs if params.get("view") == ["arbs"] else ev,
            "/api/comparison-current/selection": {"row": latest},
            "/api/comparison-current/lease": {"lease_id": "fixture"},
            "/api/comparison-current/fee-coverage": census,
            "/api/coverage": {
                "schema": "predict-broad-coverage-1",
                "mode": "current",
                "cells": [],
                "global_totals": {},
                "captured_at": AT.isoformat(),
            },
            "/api/admin/fee-schedules": {
                "state": "awaiting_verification",
                "products": [
                    {
                        "venue": "kalshi",
                        "state": "market_terms_verified",
                        "standing_public_terms": True,
                        "recheck_due_at": AT.isoformat(),
                        "source_url": "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
                    },
                    {
                        "venue": "polymarket_us",
                        "state": "awaiting_verification",
                        "source_url": "http://schedule.invalid/",
                    },
                ],
            },
            "/api/admin/status": {"sources": []},
        }.get(path)
        if path == "/api/comparison-snapshot/details":
            body = details[params["id"][0] + ":" + params["result_id"][0]]
        if body is not None:
            route.fulfill(json=body)
        elif path in ("/ev", "/arbs", "/admin", "/current/coverage"):
            route.fulfill(
                path=ASSETS
                / {
                    "/ev": "desk.html",
                    "/arbs": "desk.html",
                    "/admin": "admin.html",
                    "/current/coverage": "coverage.html",
                }[path]
            )
        elif (
            path.startswith(("/view/current/", "/current/assets/"))
            and (ASSETS / Path(path).name).is_file()
        ):
            route.fulfill(path=ASSETS / Path(path).name)
        else:
            route.fulfill(status=404)

    context.route("**/*", fulfill)
    base = "https://predict.fixture"
    tab.goto(base + "/ev")
    card = tab.locator('[data-offer-id="prophetx-offer"]')
    expect(card).to_contain_text("An exact two-sided sportsbook match is missing")
    commission = tab.locator('[data-offer-id="commission"]')
    assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")
    commission.press("Enter")
    expect(tab.locator("#trade")).to_contain_text("$0.02")
    expect(tab.locator("#trade")).to_contain_text("Winning settlement")
    expect(tab.locator("#trade")).to_contain_text("Fee if it loses")
    tab.keyboard.press("Escape")
    expect(commission).to_be_focused()
    card.press("Enter")
    drawer = tab.locator("#trade")
    expect(drawer).to_contain_text("Modeled size")
    expect(drawer).to_contain_text("An exact current sportsbook match is unavailable")
    expect(drawer).to_contain_text("$0.01")
    tab.locator("#latest").press("Enter")
    expect(drawer).to_contain_text("$0.00")
    expect(drawer).to_contain_text("8 decimal")
    assert drawer.evaluate("(el) => el.scrollWidth <= el.clientWidth")
    drawer.screenshot(path=output / f"ev-drawer-{width}.png")
    tab.goto(base + "/arbs")
    expect(tab.get_by_text("$10.17 worst modeled result")).to_be_visible()
    expect(tab.get_by_text("Net payoff unavailable")).to_be_visible()
    inspect = tab.get_by_role("button", name="View payoff calculation ↗").first
    inspect.press("Enter")
    expect(drawer).to_contain_text("$44.44")
    expect(drawer).to_contain_text("$55.56")
    expect(drawer).to_contain_text("$0.93")
    expect(drawer).to_contain_text("$10.17")
    assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")
    drawer.screenshot(path=output / f"arb-drawer-{width}.png")
    tab.keyboard.press("Escape")
    expect(inspect).to_be_focused()
    tab.goto(base + "/current/coverage")
    expect(tab.locator("#fee-census")).to_contain_text("3 of 4 current offers")
    expect(tab.locator("#fee-census")).to_contain_text("5 working prices unpublished")
    expect(tab.locator("#fee-census")).to_contain_text(
        "Sportsbook EV estimates before fees"
    )
    expect(tab.locator("#fee-census")).to_contain_text(
        "The full provider offer count is unknown"
    )
    with tab.expect_download() as exported:
        tab.locator("#export-fee-census").click()
    assert exported.value.suggested_filename == "predict-fee-coverage.json"
    tab.clock.install()
    tab.goto(base + "/admin?section=fees")
    expect(tab.locator("#admin-fee-census")).to_contain_text(
        "Exact Pinnacle references"
    )
    expect(tab.locator("#admin-fee-census")).to_contain_text(
        "Sportsbook EV estimates before fees"
    )
    expect(tab.locator("#admin-fee-census")).to_contain_text(
        "0 reviewed fees · 1 conservative"
    )
    schedules = tab.locator("#other-public-fee-schedules")
    expect(schedules).to_contain_text("Market terms verified · PDF recheck unavailable")
    expect(schedules).to_contain_text("Standing public terms")
    expect(schedules).to_contain_text("Recheck due")
    expect(schedules.get_by_role("link", name="Official fee source")).to_have_count(1)
    expect(schedules.get_by_role("link")).to_have_attribute(
        "href", "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
    )
    assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")
    schedule_unavailable = True
    tab.clock.run_for(5000)
    notice = tab.locator("#fee-schedules-status")
    expect(notice).to_contain_text("Displayed review dates may be out of date")
    expect(notice).to_be_visible()
    expect(schedules).to_contain_text("Kalshi")
    tab.locator('[data-panel="fees"]').screenshot(
        path=output / "fee-schedules-failure.png"
    )
    schedule_unavailable = False
    tab.clock.run_for(5000)
    expect(notice).to_be_hidden()
    assert not errors, errors
    context.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_ordinary_fee_desk(width, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        try:
            run(browser, width, tmp_path)
        finally:
            browser.close()
