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


def test_dashboard_reconnects_and_coalesces_fallback_while_catching_up():
    import asyncio

    from aiohttp import web
    from aiohttp.test_utils import TestServer
    from playwright.async_api import async_playwright, expect

    async def journey():
        now = datetime.now(timezone.utc)
        opening = asyncio.Event()
        held = asyncio.Event()
        release = asyncio.Event()
        finish = asyncio.Event()
        stream_scopes = []
        board_scopes = []
        failed_reads = []
        row = dict(
            offer(),
            venue="novig",
            pull_id="committed-pull",
            id="committed-offer",
            line="-1.5",
            eligible_until=(now + timedelta(seconds=60)).isoformat(),
            calculation={"status": "positive"},
        )

        async def page_response(_request):
            return web.FileResponse(ASSETS / "dashboard.html")

        async def board(request):
            board_scopes.append(dict(request.query))
            if len(board_scopes) == 2:
                held.set()
                await release.wait()
            rows = (
                [row]
                if opening.is_set() and request.query.get("sport") == "NCAAB"
                else []
            )
            return web.json_response(
                dict(rows=rows, total=len(rows), offset=0, read_at=now.isoformat())
            )

        async def stream(request):
            stream_scopes.append(dict(request.query))
            if len(stream_scopes) == 1:
                raise web.HTTPServiceUnavailable(headers={"Retry-After": "2"})
            await opening.wait()
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            # A book committed while the stream was down, so no revision notice follows.
            await response.write(b'data: {"ready":true}\n\n')
            await finish.wait()
            return response

        app = web.Application()
        app.router.add_get("/", page_response)
        app.router.add_get("/api/research/dashboard", board)
        app.router.add_get("/api/research/dashboard-updates", stream)
        app.router.add_static("/view/current", ASSETS)
        async with TestServer(app) as server, async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page()
            await page.clock.install(time=now - timedelta(hours=4))
            await page.add_init_script("""(() => {
              window.streams = [];
              window.EventSource = class extends EventSource {
                constructor(...args) { super(...args); streams.push(this); }
              };
              window.setDashboardHidden = hidden => {
                Object.defineProperty(document, 'hidden', {configurable: true, value: hidden});
                document.dispatchEvent(new Event('visibilitychange'));
              };
            })()""")
            page.on(
                "requestfailed",
                lambda request: (
                    failed_reads.append(request.failure)
                    if urlparse(request.url).path == "/api/research/dashboard"
                    else None
                ),
            )
            try:
                url = server.make_url(
                    "/?board_view=all&board_venue=novig&board_sport=NCAAB&board_family=total"
                )
                await page.goto(str(url))
                await page.wait_for_function(
                    "() => streams[0]?.readyState === EventSource.CLOSED"
                )
                await expect(
                    page.get_by_role("button", name="Reload saved prices")
                ).to_be_enabled()
                await expect(page.locator("#dashboard-rows > tr")).to_have_count(0)
                assert len(stream_scopes) == len(board_scopes) == 1
                # Let the retry reach the server near the scheduled poll without
                # advancing the in-flight read past its own request timeout.
                await page.clock.fast_forward(25000)
                opening.set()
                await asyncio.wait_for(held.wait(), 5)
                await page.clock.fast_forward(7000)
                assert len(board_scopes) == 2
                release.set()
                await expect(
                    page.locator('[data-quote="committed-pull:committed-offer"]')
                ).to_be_visible()
                await expect(
                    page.get_by_role("button", name="Reload saved prices")
                ).to_be_enabled()
                assert len(board_scopes) == 3 and not failed_reads
                assert stream_scopes == [dict(sport="NCAAB", family="total")] * 2
                assert all(
                    scope["sport"] == "NCAAB" and scope["venue"] == "novig"
                    for scope in board_scopes
                )

                await page.evaluate("setDashboardHidden(true)")
                assert await page.evaluate(
                    "streams[1].readyState === EventSource.CLOSED"
                )
                await page.clock.fast_forward(30000)
                assert len(stream_scopes) == 2
                await page.evaluate("setDashboardHidden(false)")
                await page.wait_for_function(
                    "() => streams[2]?.readyState === EventSource.OPEN"
                )
                # The reconnect delivers the same saved frame after the server-time
                # expiry. The slow browser and older frame cannot requalify it.
                await expect(
                    page.get_by_role("button", name="Reload saved prices")
                ).to_be_enabled()
                await expect(
                    page.locator('[data-quote="committed-pull:committed-offer"]')
                ).to_have_count(0)
                await page.get_by_role("combobox", name="Sport").select_option("NBA")
                await page.wait_for_function(
                    "() => streams[3]?.readyState === EventSource.OPEN"
                )
                assert await page.evaluate(
                    "streams[2].readyState === EventSource.CLOSED"
                )
                assert stream_scopes[-1] == dict(sport="NBA", family="total")
                await page.get_by_role("combobox", name="Venue").select_option("")
                assert await page.evaluate(
                    "streams[3].readyState === EventSource.CLOSED"
                )
                await page.clock.fast_forward(30000)
                assert len(stream_scopes) == 4
            finally:
                release.set()
                finish.set()
                await browser.close()

    asyncio.run(journey())


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
    row["liquidity"] = dict(
        status="full_size",
        eligible=True,
        intended_stake_usd="100",
        modeled_stake_usd="100",
        modeled_net_ev="0.105",
        available_purchase_usd="132",
        modeled_average_price="0.4",
        modeled_fee_usd="1.85",
        book_received_at=row["times"]["received_at"],
        valid_until=row["eligible_until"],
    )
    public_book = dict(
        market_id="exact-native-market",
        outcome_id="exact-native-outcome",
        levels=[dict(price="0.4", quantity="330")],
    )
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
        if (
            url.hostname == "predict.fixture"
            and url.path == "/api/research/dashboard-liquidity"
            and route.request.method == "POST"
        ):
            requests.append(url.path)
            assert route.request.post_data_json == dict(key, amount="25")
            route.fulfill(
                json={
                    "provider_requests": 0,
                    "result": {
                        "liquidity": dict(
                            row["liquidity"],
                            intended_stake_usd="25",
                            modeled_stake_usd="25",
                            modeled_net_ev="0.12",
                            modeled_fee_usd="0.46",
                        ),
                        "liquidity_evidence": public_book,
                    },
                }
            )
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
            route.fulfill(
                json={
                    "provider_requests": 0,
                    "coverage": [
                        dict(
                            venue="prophetx",
                            league="NBA",
                            family="spread",
                            main=True,
                            opportunities=4,
                            assessable=2,
                            full_size=1,
                            ev_assessable=2,
                            intended_stake_usd="400",
                            observed_supported_stake_usd="120",
                            reasons={"book_unobserved": 2},
                        )
                    ],
                }
            )
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
            params = (
                dict(expected, liquidity="1")
                if url.path == "/api/research/market"
                else expected
            )
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
        expect(
            table.get_by_text("Full size · +10.50% at $100.00", exact=False)
        ).to_be_visible()
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
        expect(
            inspector.get_by_role("heading", name="Liquidity at $100.00")
        ).to_be_visible()
        inspector.get_by_text("Public book evidence", exact=True).click()
        expect(inspector.get_by_text("exact-native-market", exact=True)).to_be_visible()
        inspector.get_by_role("button", name="$25", exact=True).click()
        expect(
            inspector.get_by_role("heading", name="Liquidity at $25.00")
        ).to_be_visible()
        expect(
            inspector.get_by_text("Full size · +12.00% at $25.00", exact=False)
        ).to_be_visible()
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


@pytest.mark.parametrize("width", [1360, 390])
def test_native_alternate_retains_price_and_depth_without_reference(width):
    from playwright.sync_api import expect, sync_playwright

    from tests.test_liquidity_execution import admitted, preview

    now = datetime.now(timezone.utc)
    listing_expiry = (now + timedelta(minutes=5)).isoformat()
    key = {
        "market_id": "canonical:fixture|spread|full_game",
        "pull_id": "native:fixture-revision",
        "offer_id": "novig-alternate",
        "revision": "fixture-revision",
    }
    book = admitted(
        (".25", 2000, 2000), (".4", 12500, 12500), coefficient=".03", line="-3.5"
    )
    book.update(
        event_id="official-event",
        market_id="official-market",
        outcome_id="official-home",
        native_side="buy",
    )

    def valuation(stake, observed=book):
        return dict(
            preview(observed, stake=stake, probability=None), valid_until=listing_expiry
        )

    row = dict(
        **{k: v for k, v in key.items() if k != "offer_id"},
        id=key["offer_id"],
        native_source={"provider": "novig"},
        venue="novig",
        league="NCAAB",
        game="Away University at Home University",
        kickoff=(now + timedelta(hours=1)).isoformat(),
        line="-3.5",
        line_role="alternate",
        period="full_game",
        family="spread",
        selection_label="Home University",
        eligible_until=listing_expiry,
        posted={"value": "0.0025", "native_price_probability": "0.25"},
        display={"posted_odds": "+300", "fair_odds": None, "net_ev": None},
        calculation={"status": "unavailable", "net_ev_percent": None},
        times={"source_at": now.isoformat()},
        liquidity=valuation("100"),
    )
    payload = {
        "native_offer": {
            "row": row,
            "book": book,
            "game_link": {
                "canonical_game_id": "canonical:fixture",
                "sgo_event_id": "sgo-event",
                "method": "both_roles_exact_schedule",
            },
            "reference": None,
            "reference_reason": "exact_sportsbook_line_unavailable",
            "sgo_comparison": [],
        },
        "liquidity": row["liquidity"],
        "liquidity_evidence": book,
    }
    stale = dict(
        row,
        id="stale-offer",
        line="-4.5",
        eligible_until=now.isoformat(),
        book_status="stale",
        liquidity=dict(status="unknown", reason="stale_book"),
    )
    unobserved = dict(
        stale,
        id="unobserved-offer",
        line="-5.5",
        book_status="unobserved",
        liquidity=dict(status="unknown", reason="book_unobserved"),
    )
    refreshed = dict(
        book,
        levels=[dict(price=".30", quantity="2000", orders=["2000"]), book["levels"][1]],
    )
    preview_offer = dict(
        row,
        revision="newer-revision",
        posted={"value": "0.003", "native_price_probability": "0.3"},
        display={"posted_odds": "+233", "fair_odds": None, "net_ev": None},
    )
    previews = []
    errors = []

    def serve(route):
        url = urlparse(route.request.url)
        if url.path == "/":
            route.fulfill(path=ASSETS / "dashboard.html", content_type="text/html")
        elif url.path == "/api/research/dashboard":
            assert parse_qs(url.query)["view"] == ["all"]
            route.fulfill(
                json={
                    "rows": [row, stale, unobserved],
                    "total": 3,
                    "offset": 0,
                    "source_authority": "official_venue_apis",
                }
            )
        elif url.path == "/api/research/dashboard-coverage":
            assert not url.query
            route.fulfill(
                json={
                    "coverage": [
                        dict(
                            venue="novig",
                            league="NCAAB",
                            family="spread",
                            line_role="alternate",
                            opportunities=2,
                            priority_offers=1,
                            exact_matches=2,
                            priority_exact_matches=1,
                            fresh_books=1,
                            priority_fresh_books=1,
                            usable_references=0,
                            priority_usable_references=0,
                            full_size=0,
                            priority_full_size=0,
                            ev_assessable=0,
                            priority_ev_assessable=0,
                            reasons={"stale_book": 1, "reference_unavailable": 1},
                            priority_reasons={"reference_unavailable": 1},
                        )
                    ]
                }
            )
        elif url.path == "/api/research/market":
            assert parse_qs(url.query) == {
                k: [v] for k, v in dict(key, liquidity="1").items()
            }
            route.fulfill(json=payload)
        elif url.path == "/api/research/dashboard-liquidity":
            assert route.request.method == "POST"
            amount = route.request.post_data_json["amount"]
            assert amount in ("25", "100", "500")
            assert route.request.post_data_json == dict(key, amount=amount)
            previews.append(route.request.post_data_json)
            route.fulfill(
                json={
                    "result": {
                        "liquidity": valuation(amount, refreshed),
                        "liquidity_evidence": refreshed,
                        "preview_offer": preview_offer,
                    },
                    "provider_requests": 0,
                }
            )
        elif url.path == "/api/research/market-export":
            assert parse_qs(url.query) == {k: [v] for k, v in key.items()}
            route.fulfill(
                json=payload,
                headers={
                    "Content-Disposition": 'attachment; filename="predict-market-evidence.json"'
                },
            )
        elif (asset := ASSETS / Path(url.path).name).is_file():
            route.fulfill(path=asset)
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 850})
        page.route("**/*", serve)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://predict.fixture/?board_view=all")
        table = page.get_by_role("table", name="All venue offers")
        expect(table.get_by_text("25% (+300)", exact=True)).to_have_count(1)
        expect(table.get_by_text("EV unavailable", exact=True)).to_have_count(3)
        expect(table.get_by_text("$5.00 at posted price", exact=True)).to_be_visible()
        expect(
            table.get_by_text("$55.00 across displayed levels", exact=True)
        ).to_be_visible()
        expect(page.locator("#dashboard-rows > tr")).to_have_count(3)
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        fresh_row = table.get_by_role("row").filter(has_text="Home University -3.5")
        expired_row = table.get_by_role("row").filter(has_text="Home University -4.5")
        unobserved_row = table.get_by_role("row").filter(
            has_text="Home University -5.5"
        )
        expect(
            fresh_row.get_by_text(re.compile(r"Fresh book · \$[\d.]+ supported"))
        ).to_be_visible()
        expect(expired_row.get_by_text("Book expired", exact=False)).to_be_visible()
        expect(expired_row.get_by_text("supported", exact=False)).to_have_count(0)
        expect(unobserved_row.get_by_text("Depth unknown", exact=True)).to_be_visible()
        table.get_by_role(
            "button", name=re.compile(r"Home University -3\.5.*View evidence")
        ).click()
        dialog = page.get_by_role("dialog")
        expect(
            dialog.get_by_text("Exact sportsbook reference unavailable.", exact=True)
        ).to_be_visible()
        expect(dialog.get_by_text("canonical:fixture", exact=True)).to_be_visible()
        expect(
            dialog.get_by_role("heading", name="Liquidity at $100.00")
        ).to_have_count(1)
        for amount, modeled_cash, average_price in [
            (25, "$25.00", "36.99¢"),
            (100, "$57.03", "38.62¢"),
            (500, "$57.03", "38.62¢"),
        ]:
            dialog.get_by_role("button", name=f"${amount}", exact=True).click()
            details = dialog.locator(".liquidity-details")
            expect(
                details.get_by_role("heading", name=f"Liquidity at ${amount}.00")
            ).to_be_visible()
            expect(details.get_by_text(modeled_cash, exact=True)).to_be_visible()
            expect(details.get_by_text(average_price, exact=True)).to_be_visible()
            expect(
                details.get_by_text(
                    "Full size" if amount == 25 else "Partial size", exact=False
                )
            ).to_be_visible()
        expect(dialog.get_by_text("Modeled fee", exact=True)).to_be_visible()
        expect(dialog.get_by_text("Modeled net EV", exact=True)).to_have_count(0)
        expect(dialog.get_by_text("25% (+300)", exact=True)).to_be_visible()
        expect(dialog.get_by_text("30% (+233)", exact=True)).to_be_visible()
        with page.expect_download() as transfer:
            dialog.get_by_role("link", name="Export saved evidence").click()
        assert "official-home" in transfer.value.path().read_text()
        dialog.get_by_role("button", name="Close", exact=True).click()
        coverage = page.locator("#dashboard-liquidity-coverage")
        coverage.get_by_text("Liquidity coverage", exact=True).click()
        expect(coverage.get_by_text("24-hour slate and next 2 hours")).to_be_visible()
        expect(
            coverage.get_by_role("cell", name=re.compile("stale book 1"))
        ).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        assert [request["amount"] for request in previews] == ["25", "100", "500"]
        assert not errors


@pytest.mark.parametrize("native", [False, True])
def test_open_dashboard_amount_expires_then_rechecks_same_selection(native):
    from playwright.sync_api import expect, sync_playwright

    now = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)
    original_expiry = (now + timedelta(seconds=20)).isoformat()
    quote = offer()
    quote["raw"].update(posted_decimal="11/5", after_fee_decimal="272/125")
    quote["fee_mode"] = {"enabled": False}
    key = dict(
        market_id="canonical:fixture|spread|full_game",
        pull_id="fixture-pull",
        offer_id="opened-offer",
        revision="opened-revision",
    )
    fresh = dict(
        status="full_size",
        size_status="full_size",
        intended_stake_usd="100",
        modeled_stake_usd="100",
        modeled_net_ev=".105",
        modeled_average_price=".4",
        available_purchase_usd="132",
        modeled_fee_usd="1.85",
        modeled_win_profit_usd="148.15",
        valid_until=original_expiry,
        book_received_at=now.isoformat(),
    )
    book = dict(
        event_id="saved-event",
        market_id="saved-market",
        outcome_id="saved-outcome",
        levels=[dict(price=".4", quantity="330")],
        valid_until=original_expiry,
        received_at=now.isoformat(),
    )
    calculation = dict(status="positive", net_ev_percent="44/5")
    row = dict(
        quote,
        id=key["offer_id"],
        revision=key["revision"],
        market_id=key["market_id"],
        pull_id=key["pull_id"],
        eligible_until=(now + timedelta(minutes=5)).isoformat(),
        kickoff=(now + timedelta(hours=1)).isoformat(),
        line="-1.5",
        liquidity=fresh,
        calculation=calculation,
    )
    detail = dict(
        liquidity=fresh,
        liquidity_evidence=book,
        selected_offer=dict(
            id=row["id"],
            revision=row["revision"],
            calculation_payload=quote,
            calculation=calculation,
        ),
    )
    if native:
        row["native_source"] = dict(provider=row["venue"])
        detail["native_offer"] = dict(
            row=row,
            book=book,
            game_link=dict(canonical_game_id="canonical:fixture"),
            reference=quote["reference"],
            sgo_comparison=[],
        )
    previews = []

    def serve(route):
        path = urlparse(route.request.url).path
        if path == "/":
            route.fulfill(path=ASSETS / "dashboard.html", content_type="text/html")
        elif path == "/api/research/dashboard":
            route.fulfill(
                json=dict(rows=[row], total=1, offset=0, read_at=now.isoformat())
            )
        elif path == "/api/research/market":
            route.fulfill(json=dict(detail, read_at=now.isoformat()))
        elif path == "/api/research/dashboard-liquidity":
            request = route.request.post_data_json
            previews.append(request)
            if request["amount"] == "500":
                reason = (
                    "stale_book"
                    if len(previews) == 1
                    else "native_observation_superseded"
                )
                result = dict(
                    liquidity=dict(
                        status="unknown",
                        size_status="unknown",
                        reason=reason,
                        intended_stake_usd="500",
                    ),
                    liquidity_evidence=None,
                )
            else:
                result = dict(
                    liquidity=dict(
                        fresh,
                        intended_stake_usd="25",
                        modeled_stake_usd="24.80",
                        modeled_net_ev=".12",
                        available_purchase_usd="61.50",
                        valid_until=(now + timedelta(seconds=85)).isoformat(),
                        reference_valid_until=(now + timedelta(seconds=40)).isoformat(),
                    ),
                    liquidity_evidence=dict(
                        book, levels=[dict(price=".4", quantity="150")]
                    ),
                )
            route.fulfill(
                json=dict(
                    result=result,
                    provider_requests=0,
                    orders_submitted=0,
                    read_at=now.isoformat(),
                )
            )
        elif (asset := ASSETS / Path(path).name).is_file():
            route.fulfill(path=asset)
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.clock.install(time=now - timedelta(hours=4))
        page.route("**/*", serve)
        page.goto("http://predict.fixture/?board_view=all")
        page.get_by_role("button", name=re.compile("View evidence")).click()
        dialog = page.get_by_role("dialog")
        amount = dialog.locator(".amount-research")
        output = amount.locator(".amount-result")
        status = amount.get_by_role("status")
        budget = amount.get_by_role("spinbutton", name="Cash budget")
        budget.fill("500")
        expect(output.get_by_text("Full size", exact=False)).to_be_visible()
        expect(output.get_by_text("Supported cash budget", exact=True)).to_be_visible()
        output.get_by_text("Public book evidence", exact=False).click()
        expect(output.get_by_text("330 native units", exact=False)).to_be_visible()

        page.clock.fast_forward(21_000)
        expect(output.get_by_text("Depth unknown", exact=False)).to_be_visible()
        expect(output.get_by_text("Full size", exact=False)).to_have_count(0)
        expect(output.get_by_text("Supported cash budget", exact=True)).to_have_count(0)
        expect(output.get_by_text("330 native units", exact=False)).to_be_visible()
        expect(status).to_have_text(
            "The book has expired. Evaluate amount to check for a fresh book."
        )
        expect(budget).to_have_value("500")
        output.get_by_text("Earlier size estimate (expired)", exact=True).click()
        expect(output.get_by_text("Modeled cash", exact=True)).to_be_visible()

        amount.get_by_role("button", name="Evaluate amount").click()
        expect(
            output.get_by_role("heading", name="Liquidity at $500.00")
        ).to_be_visible()
        expect(status).not_to_contain_text("Modeled for up to")
        expect(output.get_by_text("330 native units", exact=False)).to_be_visible()
        amount.get_by_role("button", name="Evaluate amount").click()
        expect(status).to_contain_text("The saved book changed. Evaluate amount")
        expect(budget).to_have_value("500")
        amount.get_by_role("button", name="$25", exact=True).click()
        expect(status).to_contain_text(
            "The current book models $24.80 of $25.00 requested."
        )
        expect(output.get_by_text("Full size · +12.00%", exact=False)).to_be_visible()
        expect(output.get_by_text("150 native units", exact=False)).to_be_visible()
        expect(
            output.get_by_text("Earlier size estimate (expired)", exact=True)
        ).to_have_count(0)
        assert previews == [dict(key, amount=amount) for amount in ("500", "500", "25")]

        set_hidden = """hidden => {
            Object.defineProperty(document, 'hidden', {configurable: true, value: hidden});
            document.dispatchEvent(new Event('visibilitychange'));
        }"""
        page.evaluate(set_hidden, True)
        page.clock.fast_forward(20_000)
        page.evaluate(set_hidden, False)
        expect(output.get_by_text("Full size", exact=False)).to_be_visible()
        expect(output.get_by_text("Modeled net EV", exact=True)).to_have_count(0)
        expect(status).to_contain_text("The fair reference expired.")
        dialog.get_by_role("button", name="Close", exact=True).click()
        expect(dialog).to_be_hidden()
        page.clock.fast_forward(60_000)
        assert len(previews) == 3
