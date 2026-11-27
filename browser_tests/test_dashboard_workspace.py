"""Dashboard board, immutable evidence, and freshness states through the normal UI."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import pytest

from browser_tests.test_pregame_current import offer

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


@pytest.mark.parametrize("width", [1360, 390])
def test_dashboard_keeps_board_and_reads_the_exact_offer(width):
    from playwright.sync_api import expect, sync_playwright

    full = offer()
    full["raw"].update(posted_decimal="11/5", after_fee_decimal="272/125")
    full["fee_mode"] = {"enabled": False}
    key = dict(
        market_id="canonical:fixture|spread|full_game",
        pull_id="covering-pull",
        offer_id="exact-offer",
        revision="offer-revision",
    )
    detail = dict(
        id=key["offer_id"],
        revision=key["revision"],
        calculation_payload=full,
        calculation={"status": "positive", "net_ev_percent": "44/5"},
    )
    row = dict(
        full,
        **{k: v for k, v in key.items() if k != "offer_id"},
        eligible_until=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        calculation=detail["calculation"],
        line="-1.5",
    )
    row["id"] = key["offer_id"]
    row["liquidity"] = dict(status="full_size", eligible=True, intended_stake_usd="100",
        modeled_stake_usd="100", modeled_net_ev="0.105", available_purchase_usd="132",
        modeled_average_price="0.4", modeled_fee_usd="1.85", book_received_at=row["times"]["received_at"],
        valid_until=row["eligible_until"])
    public_book = dict(market_id="exact-native-market", outcome_id="exact-native-outcome",
                       levels=[dict(price="0.4", quantity="330")])
    listing = {"rows": [row], "total": 1, "offset": 0}
    cbb = "South Carolina Gamecocks at Arizona State Sun Devils"
    cbb_rows = []
    for family, label, line in [
        ("moneyline", "Arizona State Sun Devils", None),
        ("spread", "Arizona State Sun Devils", "-3.5"),
        ("total", "Over", "152.5"),
    ]:
        exact = dict(
            row,
            game=cbb,
            league="NCAAB",
            family=family,
            line_role="alternate" if family == "spread" else "main",
            selection_label=label,
            line=line,
            market_id=f"canonical:cbb|{family}|full_game",
            pull_id="cbb-pull",
            venue="novig",
            id=f"novig-{family}",
            revision=f"novig-{family}-revision",
        )
        other = dict(
            exact,
            venue="kalshi",
            id=f"kalshi-{family}",
            revision=f"kalshi-{family}-revision",
        )
        cbb_rows.append(dict(exact, bet_id=f"exact-{family}", other_quotes=[other]))
    alternative = cbb_rows[1]["other_quotes"][0]
    mode = {"state": "ready"}
    requests = []
    errors = []

    def serve(route):
        url = urlparse(route.request.url)
        if url.hostname == "predict.fixture" and url.path == "/api/research/dashboard-liquidity" and route.request.method == "POST":
            requests.append(url.path)
            assert route.request.post_data_json == dict(key, amount="25")
            route.fulfill(json={"provider_requests": 0, "result": {
                "liquidity": dict(row["liquidity"], intended_stake_usd="25", modeled_stake_usd="25",
                                  modeled_net_ev="0.12", modeled_fee_usd="0.46"),
                "liquidity_evidence": public_book,
            }})
            return
        if url.hostname != "predict.fixture" or route.request.method != "GET":
            errors.append("Unexpected external or mutating request")
            route.abort()
            return
        requests.append(url.path)
        if url.path == "/":
            route.fulfill(path=ASSETS / "dashboard.html", content_type="text/html")
        elif url.path == "/api/research/dashboard":
            if mode["state"] == "failed":
                route.fulfill(status=503, json={})
                return
            if mode["state"] == "ready":
                route.fulfill(json=listing)
                return
            if mode["state"] in ("grouped", "partial"):
                route.fulfill(
                    json={
                        "rows": cbb_rows,
                        "total": 3,
                        "offset": 0,
                        "availability": {
                            "price_available": True,
                            "pull_incomplete": mode["state"] == "partial",
                        },
                    }
                )
                return
            states = {
                "empty": {"price_available": True},
                "missing": {"price_available": True, "inputs_unavailable": True},
                "expired": {"expired_positive": True},
            }
            route.fulfill(
                json={
                    "rows": [],
                    "total": 0,
                    "offset": 0,
                    "availability": states[mode["state"]],
                }
            )
        elif url.path == "/api/research/dashboard-coverage":
            assert parse_qs(url.query) == {}
            route.fulfill(json={"provider_requests": 0, "coverage": [
                dict(venue="prophetx", league="NBA", family="spread", main=True, opportunities=4,
                     assessable=2, full_size=1, ev_assessable=2, intended_stake_usd="400",
                     observed_supported_stake_usd="120", reasons={"book_unobserved":2})
            ]})
        elif url.path in ("/api/research/market", "/api/research/market-export"):
            expected = (
                key
                if mode["state"] == "ready"
                else {
                    field: alternative[field]
                    for field in ("market_id", "pull_id", "revision")
                }
                | {"offer_id": alternative["id"]}
            )
            params = dict(expected, liquidity="1") if url.path == "/api/research/market" else expected
            assert parse_qs(url.query) == {k: [v] for k, v in params.items()}
            route.fulfill(
                json={
                    "selected_offer": dict(
                        detail, id=expected["offer_id"], revision=expected["revision"]
                    ),
                    "liquidity": row["liquidity"],
                    "liquidity_evidence": public_book,
                },
                headers={
                    "Content-Disposition": 'attachment; filename="predict-market-evidence.json"'
                }
                if url.path.endswith("-export")
                else {},
            )
        elif url.path.startswith("/api/"):
            # The shared status check is read-only and independent of the board.
            route.fulfill(status=503, json={})
        elif (asset := ASSETS / Path(url.path).name).suffix in {
            ".css",
            ".js",
            ".woff2",
            ".ttf",
        } and asset.is_file():
            route.fulfill(path=asset)
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 850})
        page.route("**/*", serve)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://predict.fixture/")
        table = page.get_by_role("table", name="Current +EV opportunities")
        expect(table).to_be_visible()
        expect(
            table.get_by_role("columnheader", name="EV", exact=True)
        ).to_have_attribute("aria-sort", "descending")
        for value in ("+100", "+120"):
            expect(
                table.get_by_role("cell", name=re.compile(re.escape(value) + "$"))
            ).to_be_visible()
        expect(table.get_by_text("Quote +8.80%", exact=True)).to_be_visible()
        expect(table.get_by_text("Full size · +10.50% at $100.00", exact=False)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        trigger = table.get_by_role(
            "button",
            name="Orlando Magic -1.5 · Milwaukee Bucks at Orlando Magic · ProphetX · View evidence",
        )
        trigger.focus()
        trigger.press("Enter")
        inspector = page.get_by_role("dialog")
        expect(
            inspector.get_by_role("heading", name="Reference prices")
        ).to_be_visible()
        expect(inspector.get_by_role("heading", name="Liquidity at $100.00")).to_be_visible()
        inspector.get_by_text("Public book evidence", exact=True).click()
        expect(inspector.get_by_text("exact-native-market", exact=True)).to_be_visible()
        inspector.get_by_role("button", name="$25", exact=True).click()
        expect(inspector.get_by_role("heading", name="Liquidity at $25.00")).to_be_visible()
        expect(inspector.get_by_text("Full size · +12.00% at $25.00", exact=False)).to_be_visible()
        expect(inspector.get_by_text("$0 modeled fees", exact=False)).to_be_visible()
        expect(
            inspector.get_by_text("home (this bet) · -110", exact=False)
        ).to_be_visible()
        inspector.get_by_text("Net expected value", exact=True).click()
        expect(
            inspector.get_by_text(
                "Net EV = p × win return + (1 − p) × loss return.", exact=True
            )
        ).to_be_visible()
        expect(
            inspector.get_by_role("link", name="Open original odds pull in Data")
        ).to_have_attribute(
            "href", "/data?evidence=pulls&pull=covering-pull&sport=NBA&family=spread"
        )
        with page.expect_download() as transfer:
            inspector.get_by_role("link", name="Export this calculation").click()
        assert "offer-revision" in transfer.value.path().read_text()
        assert urlparse(page.url).path == "/"
        inspector.get_by_role("button", name="Close", exact=True).click()
        expect(trigger).to_be_focused()
        expect(table).to_be_visible()
        coverage = page.locator("#dashboard-liquidity-coverage")
        coverage.get_by_text("Liquidity coverage", exact=True).click()
        expect(coverage.get_by_role("cell", name="30.0%", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        coverage.get_by_text("Liquidity coverage", exact=True).click()

        expect(page.get_by_label("Rows per page")).to_have_value("50")
        page.get_by_label("Sport", exact=True).select_option("NBA")
        page.get_by_label("Bet type", exact=True).select_option("spread")
        page.get_by_label("Venue", exact=True).select_option("prophetx")
        with page.expect_response(
            lambda response: (
                urlparse(response.url).path == "/api/research/dashboard"
                and parse_qs(urlparse(response.url).query).get("limit") == ["100"]
            )
        ) as result:
            page.get_by_label("Rows per page").select_option("100")
        assert parse_qs(urlparse(result.value.url).query) == {
            "sport": ["NBA"],
            "family": ["spread"],
            "venue": ["prophetx"],
            "limit": ["100"],
            "offset": ["0"],
        }
        assert parse_qs(urlparse(page.url).query) == {
            "board_sport": ["NBA"],
            "board_family": ["spread"],
            "board_venue": ["prophetx"],
            "board_rows": ["100"],
        }
        page.reload()
        expect(page.get_by_label("Sport", exact=True)).to_have_value("NBA")
        expect(page.get_by_label("Bet type", exact=True)).to_have_value("spread")
        expect(page.get_by_label("Venue", exact=True)).to_have_value("prophetx")
        expect(table).to_be_visible()
        page.get_by_role("button", name="Clear filters").click()
        expect(page.get_by_label("Sport", exact=True)).to_have_value("")
        expect(page.get_by_label("Rows per page")).to_have_value("100")
        expect(table).to_be_visible()

        status = page.locator("#dashboard-status")
        mode["state"] = "grouped"
        page.get_by_label("Sport", exact=True).select_option("NCAAB")
        game_rows = page.locator("#dashboard-rows > tr")
        expect(game_rows).to_have_count(3)
        expect(status).to_be_empty()
        expect(page.locator("#dashboard-page")).to_have_text("1–3 of 3 bets")
        expect(game_rows.nth(1)).to_contain_text(cbb)
        expect(game_rows.nth(1)).to_contain_text("Novig")
        expect(game_rows.nth(1)).to_contain_text("Alternate")
        other_quotes = game_rows.nth(1).get_by_text("1 other quote", exact=True)
        other_quotes.click()
        other_trigger = game_rows.nth(1).get_by_role(
            "button", name=re.compile("Kalshi · View evidence$")
        )
        expect(other_trigger).to_be_visible()
        other_trigger.click()
        expect(
            inspector.get_by_role(
                "heading", name="Arizona State Sun Devils -3.5 · Kalshi"
            )
        ).to_be_visible()
        expect(
            inspector.get_by_role("heading", name="Reference prices")
        ).to_be_visible()
        inspector.get_by_role("button", name="Close", exact=True).click()
        expect(other_trigger).to_be_focused()
        expect(game_rows).to_have_count(3)
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        mode["state"] = "partial"
        page.get_by_role("button", name="Reload saved prices").click()
        expect(status).to_have_text("Some odds pulls are incomplete.")
        expect(other_trigger).to_be_visible()
        diagnostics = page.locator("#diagnostics")
        diagnostics.get_by_text("Diagnostics", exact=True).click()
        expect(
            diagnostics.get_by_role("link", name="Men’s D1 collection jobs")
        ).to_have_attribute("href", "/settings#mens-d1-jobs")
        page.get_by_role("button", name="Clear filters").click()
        expect(table).to_be_visible()

        for state, text in [
            ("expired", "stale or withdrawn inputs"),
            ("missing", "Some calculations are unavailable."),
            ("empty", "No current +EV opportunities"),
            ("failed", "Current opportunities are unavailable."),
        ]:
            mode["state"] = state
            page.get_by_role("button", name="Reload saved prices").click()
            expect(status).to_contain_text(text)
            expect(table).to_be_hidden()
        assert requests.count("/api/research/market") == 2
        assert requests.count("/api/research/dashboard-liquidity") == 1
        assert not errors
