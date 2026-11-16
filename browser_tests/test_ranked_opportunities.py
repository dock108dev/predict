"""Exercise the approved ranked journey at desktop and mobile widths."""

from datetime import datetime
import json
import os
from pathlib import Path
import re
from time import monotonic
from urllib.parse import parse_qs, urlparse

import pytest

from browser_tests.ranked_fixtures import (
    ASSETS,
    BASE,
    DENVER,
    DETROIT,
    START,
    group,
    quote,
)


def test_opportunities_separates_market_families_for_the_same_game():
    from playwright.sync_api import expect, sync_playwright

    market_rows = [
        group(
            key,
            DENVER,
            [quote(key, "kalshi", side, family, line, participant=team)],
            score,
        )
        for key, family, side, line, team, score in (
            ("winner", "winner", "win", None, "Denver", "5"),
            ("over", "total", "over", "205.5", None, "4"),
            ("cover", "spread", "cover", "2.5", "Denver", "3"),
            ("under", "total", "under", "205.5", None, None),
            ("opposite", "spread", "cover", "-2.5", "Minnesota", "1"),
        )
    ]
    estimates_available = True

    def respond(route):
        url = urlparse(route.request.url)
        query = parse_qs(url.query)
        if url.path in ("/ev", "/browse-odds"):
            route.fulfill(path=ASSETS / "desk.html")
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/comparison-current":
            empty_ev = not estimates_available and "browse_odds" not in query
            route.fulfill(
                json=dict(
                    state="ready",
                    rows=[] if empty_ev else market_rows,
                    # An older API may still send the former fallback payload.
                    price_preview=market_rows if empty_ev else [],
                    calculation_reason=(
                        "No eligible two-sided sportsbook reference is available for these offers."
                        if empty_ev
                        else None
                    ),
                    row_kind="games",
                    total=1,
                    page_count=1,
                    phase="pregame",
                    features={"live_enabled": False},
                )
            )
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        tab = browser.new_page()
        tab.route("**/*", respond)
        tab.clock.install(time=datetime.fromisoformat("2026-11-13T00:00:00+00:00"))
        tab.goto(f"{BASE}/ev")
        cards = tab.locator("#results > article")
        expect(cards).to_have_count(3)
        expect(cards.locator("h2")).to_have_text(
            ["Denver to win", "Over 205.5", "Denver to cover +2.5"]
        )
        cards.nth(1).get_by_text("1 more outcome", exact=True).click()
        unranked = cards.nth(1).locator('[data-group-id="under"]')
        expect(unranked.get_by_role("heading", name="Under 205.5")).to_be_visible()
        expect(unranked).to_contain_text(
            "EV unavailable · The sportsbook jurisdiction and applicable market rules are unverified"
        )
        expect(unranked.locator(".desk-offer.desk-best")).to_have_count(0)
        expect(
            cards.nth(2).get_by_role("heading", name="Minnesota to cover -2.5")
        ).to_have_count(0)

        estimates_available = False
        tab.reload()
        results = tab.locator("#results")
        matrices = tab.locator("#results .odds-card")
        expect(
            results.get_by_role("heading", name="No EV estimates available")
        ).to_be_visible()
        expect(
            results.get_by_text(
                "No eligible two-sided sportsbook reference is available for these offers."
            )
        ).to_be_visible()
        expect(matrices).to_have_count(0)
        expect(cards).to_have_count(0)

        results.get_by_role("link", name="Browse odds ↗").click()
        expect(tab).to_have_url(re.compile(r"/browse-odds(?:\?|$)"))
        expect(matrices).to_have_count(1)
        expect(matrices.locator("tbody tr")).to_have_count(5)
        browser.close()


def test_update_check_keeps_pregame_estimate_until_kickoff_and_recovers():
    from playwright.sync_api import expect, sync_playwright

    revision = "a"
    read_failure = False
    list_reads = []
    signals = []

    def respond(route):
        url = urlparse(route.request.url)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path == "/ev":
            route.fulfill(path=ASSETS / "desk.html")
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/comparison-current/updates":
            signals.append(query)
            route.fulfill(
                json=dict(
                    changed=query["after"] != revision,
                    cursor=revision,
                    phase="pregame",
                    features={"live_enabled": False},
                    poll_after_ms=6500,
                )
            )
        elif url.path == "/api/comparison-current":
            list_reads.append(query)
            if read_failure:
                route.fulfill(status=503)
                return
            deadline = "2026-11-13T00:00:20Z" if revision == "a" else START
            value = "1/5" if revision == "a" else "7/10"
            lead = quote(
                "novig-over",
                "novig",
                "over",
                "total",
                "215.5",
                value=value,
                current_until=deadline,
                calculation_current_until=deadline,
            )
            other = quote("novig-under", "novig", "under", "total", "215.5", value="-1")
            route.fulfill(
                json=dict(
                    state="ready",
                    phase="pregame",
                    features={"live_enabled": False},
                    update_cursor=revision,
                    refresh_at=deadline,
                    browse_id="keep-first-page",
                    basis=query["basis"],
                    rows=[
                        group("lead", DETROIT, [lead], value),
                        group("other", DETROIT, [other], "-1"),
                    ],
                    row_kind="games",
                    page_count=1,
                    total=1,
                    publication={},
                )
            )
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        tab = browser.new_page(viewport={"width": 390, "height": 844})
        tab.route("**/*", respond)
        tab.clock.install(time=datetime.fromisoformat("2026-11-13T00:00:00+00:00"))
        tab.goto(f"{BASE}/ev")
        score = tab.locator(".compact-ev-return")
        expect(score).to_have_text("+0.20%")
        expect(tab.locator('[data-offer-id="novig-over"]')).to_have_attribute(
            "aria-label", re.compile("Before-fee estimate")
        )
        expect(tab.get_by_text("1 more outcome")).to_be_visible()
        expect(tab.get_by_label("Calculation basis")).to_have_value("sportsbooks")
        expect(tab.locator("#phase-tabs")).to_be_hidden()
        assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")
        tab.evaluate("window.initialCard = document.querySelector('.opportunity-card')")

        with tab.expect_response(lambda response: "/updates?" in response.url):
            tab.clock.fast_forward(7000)
        assert len(list_reads) == 1
        assert signals[0]["after"] == "a"
        assert tab.evaluate(
            "window.initialCard === document.querySelector('.opportunity-card')"
        )

        revision = "b"
        read_failure = True
        with tab.expect_response(lambda response: response.status == 503):
            tab.clock.fast_forward(7000)
        expect(tab.locator("#previous-results")).to_contain_text(
            "Showing previous results"
        )
        assert "browse_id" not in list_reads[-1]
        expect(tab.locator('[data-offer-id="novig-over"]')).to_be_visible()
        expect(score).to_be_visible()

        with tab.expect_response(lambda response: response.status == 503):
            tab.clock.fast_forward(7000)
        assert len(list_reads) == 3
        expect(tab.locator('[data-offer-id="novig-over"]')).to_be_visible()
        expect(score).to_have_text("+0.20%")

        read_failure = False
        with tab.expect_response(
            lambda response: "/api/comparison-current?" in response.url
        ):
            tab.clock.fast_forward(7000)
        expect(tab.locator('[data-offer-id="novig-over"]')).to_contain_text("+0.70%")
        expect(tab.locator("#previous-results")).to_be_hidden()

        tab.goto(f"{BASE}/ev?phase=live")
        expect(tab).to_have_url(f"{BASE}/ev")
        expect(tab.locator("#phase-tabs")).to_be_hidden()
        assert list_reads[-1]["phase"] == "live"
        tab.clock.set_fixed_time(datetime.fromisoformat(START))
        tab.clock.fast_forward(3_600_000)
        expect(tab.locator('[data-offer-id="novig-over"]')).to_have_count(0)
        browser.close()


def test_desk_reports_outage_without_old_quotes_then_recovers_on_refresh():
    from playwright.sync_api import expect, sync_playwright

    from app.storage.store import stamp

    observed = "2026-11-13T00:00:00+00:00"
    version = 0
    detail_reads = []

    def page():
        price = ("+104", "+110", "+118")[version]
        offer = quote(
            "poly",
            "polymarket_us",
            "win",
            "winner",
            None,
            participant="Denver",
            value="2",
        )
        offer["odds"] = {"american": price}
        result = dict(
            state="ready",
            phase="pregame",
            update_cursor=str(version),
            features={"live_enabled": False, "auto_update": True},
            basis="sportsbooks",
            row_kind="games",
            page_count=1,
            total=1,
            rows=[group("winner", DENVER, [offer], "2")],
            publication={"read_at": observed},
        )
        return result

    def respond(route):
        url = urlparse(route.request.url)
        if url.path == "/browse-odds":
            route.fulfill(path=ASSETS / "desk.html")
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/comparison-current":
            route.fulfill(json=page()) if version else route.fulfill(status=503)
        elif url.path == "/api/comparison-current/updates":
            route.fulfill(
                json={
                    "changed": parse_qs(url.query)["after"] != [str(version)],
                    "poll_after_ms": 6500,
                }
            )
        elif url.path == "/api/comparison-current/selection":
            detail_reads.append(url.path)
            route.fulfill(status=503)
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        tab = browser.new_page()
        tab.route("**/*", respond)
        tab.clock.install(time=stamp(observed))
        tab.goto(f"{BASE}/browse-odds")
        price = tab.locator('[data-offer-id="poly"]')
        expect(tab.locator("#notice")).to_contain_text("Prices could not be loaded.")
        expect(price).to_have_count(0)
        assert not detail_reads
        version = 1
        start = monotonic()
        tab.locator("#refresh-list").click()
        expect(price).to_contain_text("+110")
        paint_seconds = monotonic() - start

        version = 2
        with tab.expect_response(
            lambda response: "/api/comparison-current?" in response.url
        ):
            tab.clock.fast_forward(6600)
        expect(price).to_contain_text("+118")
        browser.close()
    if report := os.environ.get("PREDICT_CI_REPORT_ROOT"):
        (Path(report) / "desk-paint.json").write_text(
            json.dumps(
                dict(
                    fixture="desk-browser-intercept-recovery-v2", seconds=paint_seconds
                ),
                indent=2,
            )
            + "\n"
        )


@pytest.mark.parametrize("width", [1440, 390])
def test_ev_updates_prices_without_reranking_or_displacing_a_reader(width):
    from playwright.sync_api import expect, sync_playwright

    revision = "a"
    reads = []

    def respond(route):
        url = urlparse(route.request.url)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path in ("/ev", "/browse-odds"):
            route.fulfill(path=ASSETS / "desk.html")
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/comparison-current/updates":
            route.fulfill(
                json=dict(changed=query["after"] != revision, cursor=revision)
            )
        elif url.path == "/api/comparison-current":
            reads.append(query)
            if revision == "c" and query.get("browse_id") == "original":
                route.fulfill(json=dict(state="page_changed"))
                return
            kalshi = quote(
                "native-current:exact-kalshi"
                if revision == "c"
                else "detroit-over-kalshi",
                "kalshi",
                "over",
                "total",
                "205.5",
                desk_quote_key="exact-kalshi",
                decimal={"a": "5/4", "b": "3/2", "c": "4/3"}[revision],
                value="2.3",
            )
            novig = quote(
                "detroit-over-novig",
                "novig",
                "over",
                "total",
                "205.5",
                value="1.8",
                desk_quote_key="another-contract" if revision == "c" else "exact-novig",
            )
            under = quote(
                "detroit-under", "novig", "under", "total", "205.5", value="3.1"
            )
            denver = quote("denver-over", "kalshi", "over", "total", "198.5", value="4")
            lead = kalshi if revision == "a" else novig
            match = group(
                "detroit-over",
                DETROIT,
                [kalshi, novig] if lead == kalshi else [novig, kalshi],
                lead["value"],
                score_source={"id": lead["id"]},
            )
            nested = group("detroit-under", DETROIT, [under], under["value"])
            other = group("denver-over", DENVER, [denver], denver["value"])
            more = [
                group(
                    f"game-{i}",
                    f"Game {i}",
                    [quote(f"offer-{i}", "novig", "over", "total", "198.5")],
                )
                for i in range(8)
            ]
            rows = [match, nested, other] if revision == "a" else [other, nested, match]
            route.fulfill(
                json=dict(
                    state="ready",
                    phase="pregame",
                    features={"live_enabled": False},
                    update_cursor=revision,
                    browse_id="original" if revision != "c" else "new",
                    basis=query["basis"],
                    rows=[*rows, *more],
                    row_kind="games",
                    page_count=10,
                    total=10,
                    publication={},
                )
            )
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        tab = browser.new_page(viewport={"width": width, "height": 720})
        tab.route("**/*", respond)
        tab.clock.install(time=datetime.fromisoformat("2026-11-13T00:00:00+00:00"))
        tab.goto(f"{BASE}/ev")
        first = tab.locator("#results > article").first
        over = tab.locator('[data-group-id="detroit-over"]')
        under = tab.locator('[data-group-id="detroit-under"] > .compact-ev-market h2')
        disclosure = first.locator("summary")
        expect(first).to_have_attribute("data-group-id", "detroit-over")
        disclosure.click()
        expect(disclosure).to_be_focused()
        expect(under).to_be_visible()
        under.evaluate(
            "heading => window.scrollBy(0, heading.getBoundingClientRect().top - 45)"
        )
        anchor_top = under.bounding_box()["y"]
        kalshi_chip = over.locator('[data-offer-id="detroit-over-kalshi"]')
        ranked_chips = over.locator(".compact-prices").first.locator(":scope > button")
        expect(ranked_chips.first).to_have_attribute(
            "data-offer-id", "detroit-over-kalshi"
        )
        expect(kalshi_chip).to_contain_text("-400")

        revision = "b"
        with tab.expect_response(
            lambda response: "/api/comparison-current?" in response.url
        ):
            tab.clock.fast_forward(13000)
        expect(kalshi_chip).to_contain_text("-200")
        expect(first).to_have_attribute("data-group-id", "detroit-over")
        expect(ranked_chips.first).to_have_attribute(
            "data-offer-id", "detroit-over-novig"
        )
        expect(disclosure).to_be_focused()
        expect(under).to_be_visible()
        assert abs(under.bounding_box()["y"] - anchor_top) <= 1
        expect(tab.locator("#updates-ready")).to_be_visible()

        revision = "c"
        kalshi_chip.evaluate("node => node.focus({preventScroll:true})")
        with tab.expect_response(
            lambda response: (
                "/api/comparison-current?" in response.url
                and "browse_id" not in response.url
            )
        ):
            tab.clock.fast_forward(13000)
        expect(first).to_have_attribute("data-group-id", "detroit-over")
        renewed = over.locator('[data-offer-id="native-current:exact-kalshi"]')
        expect(renewed).to_contain_text("-300")
        expect(renewed).to_be_focused()
        expect(over.locator('[data-offer-id="detroit-over-novig"]')).to_have_attribute(
            "data-desk-quote-key", "another-contract"
        )
        assert abs(under.bounding_box()["y"] - anchor_top) <= 1

        tab.locator("#refresh-list").evaluate("button => button.click()")
        expect(first).to_have_attribute("data-group-id", "denver-over")
        expect(tab.locator("#updates-ready")).to_be_hidden()
        expect(
            tab.locator('[data-group-id="detroit-under"] details')
        ).to_have_attribute("open", "")
        assert abs(under.bounding_box()["y"] - anchor_top) <= 1
        if width == 390:
            revision = "a"
            tab.goto(f"{BASE}/browse-odds")
            table = tab.locator(".odds-scroll").first
            expect(table).to_be_visible()
            scroll_left = table.evaluate(
                "region => { region.scrollLeft = 120; region.focus({preventScroll:true}); return region.scrollLeft; }"
            )
            assert scroll_left > 0
            revision = "b"
            with tab.expect_response(
                lambda response: "/api/comparison-current?" in response.url
            ):
                tab.clock.fast_forward(13000)
            expect(
                tab.locator('[data-offer-id="detroit-over-kalshi"]')
            ).to_contain_text("-200")
            expect(table).to_be_focused()
            assert table.evaluate("region => region.scrollLeft") == scroll_left
        browser.close()


def test_posted_pregame_preview_updates_with_the_board_and_can_be_held():
    from playwright.sync_api import expect, sync_playwright

    key = "a" * 64
    selected = quote("posted", "prophetx", "win", "winner", None, participant="Denver")
    selected.update(
        posted_price=True,
        current=True,
        desk_quote_key=key,
        current_until=START,
        cost_per_normal_claim="0.5",
    )
    revision = 0
    prices = ["+100", "+104", "+110"]
    reads = {"list": 0, "selection": 0}

    def offer():
        return dict(
            selected,
            odds={
                "american": prices[revision],
                "decimal": ["2", "2.04", "2.1"][revision],
            },
            price_revision=str(revision),
            economic_revision=str(revision),
            value=None,
        )

    def respond(route):
        url = urlparse(route.request.url)
        if url.path in ("/ev", "/browse-odds", "/game"):
            route.fulfill(path=ASSETS / "desk.html")
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/comparison-current":
            reads["list"] += 1
            body = group("posted-group", DENVER, [offer()], None)
            route.fulfill(
                json=dict(
                    state="ready",
                    rows=[body],
                    phase="pregame",
                    total=1,
                    features=dict(live_enabled=False, auto_update=True),
                    update_cursor=str(revision),
                    refresh_at=START,
                )
            )
        elif url.path == "/api/comparison-current/updates":
            after = parse_qs(url.query)["after"][0]
            route.fulfill(
                json=dict(
                    changed=after != str(revision),
                    cursor=str(revision),
                    poll_after_ms=1000,
                )
            )
        elif url.path == "/api/comparison-current/selection":
            reads["selection"] += 1
            budget = parse_qs(url.query)["preview_amount"][0]
            route.fulfill(
                json=dict(
                    row=dict(
                        offer(),
                        start_at=START,
                        trade_preview=dict(
                            available=True,
                            fee_available=True,
                            amount_usd=budget,
                            upfront_usd=budget,
                            fee_timing="commission_deducted_from_winning_market_gains",
                            fee_at_entry_usd="0",
                            fee_if_win_usd="0.21",
                            net_win_payout_usd="20.19",
                            net_win_profit_usd="10.19",
                            net_loss_usd=budget,
                            modeled=True,
                        ),
                    )
                )
            )
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        tab = browser.new_page()
        errors = []
        tab.on("pageerror", lambda err: errors.append(str(err)))
        tab.route("**/*", respond)
        tab.clock.install(time=datetime.fromisoformat("2026-11-13T00:00:00+00:00"))
        tab.goto(f"{BASE}/browse-odds")
        toggle = tab.get_by_role("checkbox", name="Auto-update")
        expect(toggle).to_be_visible()
        expect(toggle).to_be_checked()
        tile = tab.locator("#results [data-desk-quote-key]").first
        expect(tile).to_contain_text("+100")
        tab.clock.fast_forward(35_000)
        expect(tile).to_contain_text("+100")
        expect(tile).not_to_contain_text("Last known")
        tile.click()
        detail = tab.get_by_role("dialog", name="ProphetX · Denver to win")
        expect(detail).to_contain_text("$20.19 returned")
        expect(detail.get_by_role("button", name="Use latest prices")).to_be_hidden()
        amount = detail.get_by_label("Maximum upfront cost")
        amount.fill("15")
        amount.press("Tab")
        expect(detail).to_contain_text("$15.00 loss")

        revision = 1
        tab.clock.fast_forward(18_000)
        expect(detail).to_contain_text("+104")
        expect(tile).to_contain_text("+104")
        expect(amount).to_have_value("15")
        detail.get_by_role("button", name="Close").click()
        toggle.uncheck()
        before = dict(reads)
        revision = 2
        tab.clock.fast_forward(20_000)
        expect(tile).to_contain_text("+104")
        assert reads == before
        tile.click()
        expect(detail).to_contain_text("+104")
        detail.get_by_role("button", name="Refresh", exact=True).click()
        expect(detail).to_contain_text("+110")
        expect(tile).to_contain_text("+110")
        detail.get_by_role("button", name="Close").click()
        tab.reload()
        expect(toggle).not_to_be_checked()
        expect(tile).to_contain_text("+110")
        before = dict(reads)
        tab.clock.fast_forward(3_600_000)
        expect(tile).to_have_count(0)
        assert reads == before
        assert not errors, errors
        browser.close()
