"""Exercise the approved ranked journey at desktop and mobile widths."""

from copy import deepcopy
from datetime import datetime
from fractions import Fraction
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import pytest
from app.dashboard.trade_desk import public_group

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)
START = "2026-11-13T01:00:00Z"
BASE = "https://predict.fixture"
DENVER = "Denver Nuggets vs. Minnesota Timberwolves"
DETROIT = "Detroit Pistons vs. Washington Wizards"
WASHINGTON = "Washington Commanders vs. New York Giants"


def quote(key, venue, predicate, family, line=None, *, decimal="1.25", **fields):
    payout = Fraction(decimal)
    american = 100 * (payout - 1) if payout >= 2 else -100 / (payout - 1)
    return (
        dict(
            id=key,
            venue=venue,
            current=True,
            odds=dict(decimal=decimal, american=f"{float(american):+.2f}"),
            market=dict(market=family, period="full_game", line=line),
            selection=dict(predicate=predicate, signed_line=line),
            value=None,
            before_fee=None,
            after_fee=None,
            conservative=None,
            reference=None,
            reference_current=False,
            current_until=None,
            calculation_current_until=None,
            participant=None,
            alternate=None,
            reason="sgo_reference_book_rules_unverified",
            cost_per_normal_claim=str(1 / payout),
            captured_at=START,
            price_revision=key + "-price",
            economic_revision=key + "-economics",
            evidence_result_id=key + "-capture",
        )
        | fields
    )


def group(key, game, offers, score=None, **fields):
    return (
        dict(
            id=key,
            game_key=game,
            game_title=game,
            league="NBA",
            start_at=START,
            offers=offers,
            market=offers[0]["market"],
            score=score,
        )
        | fields
    )


def settlement(
    key, title, lead, opposite, score, profit, funding, quantities, costs, fees
):
    payoff = dict(
        available=True,
        minimum_net_profit_usd=profit,
        funding_usd=funding,
        legs=[
            dict(
                available=True,
                acquisition_usd=cost,
                quantity=quantity,
                at_fill_usd=fee,
                settlement_usd={},
                receipts_usd=dict(
                    first_wins=quantity if index == 0 else "0",
                    second_wins=quantity if index == 1 else "0",
                    equality=str(Fraction(quantity) / 2),
                ),
                rounding_trace=[dict(raw=fee, amount=fee)],
                classification="conservative",
            )
            for index, (quantity, cost, fee) in enumerate(
                zip(quantities, costs, fees, strict=True)
            )
        ],
        sizing=dict(quantity=quantities[0], requested_stake_usd="100"),
        states={
            state: dict(net_receipt_usd=quantities[0], net_profit_usd=profit)
            for state in ("first_wins", "second_wins", "equality")
        },
    )
    pair = dict(
        id=key,
        evidence_result_id=key + "-capture",
        legs=[lead["id"], opposite["id"]],
        score=score,
        retail_payoff=payoff,
        inspection=dict(
            funding_usd="100",
            minimum_profit_usd=profit,
            rounding="Whole modeled claims",
            legs=[
                dict(cost_per_claim=item["cost_per_normal_claim"], allocation_usd=cost)
                for item, cost in zip((lead, opposite), costs, strict=True)
            ],
        ),
    )
    return group(key, title, [lead, opposite], score, pairs=[pair])


def test_update_check_keeps_page_and_conceals_expired_estimate():
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
            "Showing the previous results"
        )
        assert list_reads[-1]["browse_id"] == "keep-first-page"
        expect(tab.locator('[data-offer-id="novig-over"]')).to_be_visible()
        expect(score).to_be_visible()

        with tab.expect_response(lambda response: response.status == 503):
            tab.clock.fast_forward(7000)
        expect(score).to_be_hidden()
        expect(tab.locator('[data-offer-id="novig-over"]')).to_contain_text("Last known")

        read_failure = False
        with tab.expect_response(
            lambda response: "/api/comparison-current?" in response.url
        ):
            tab.clock.fast_forward(7000)
        expect(score).to_have_text("+0.70%")
        expect(tab.locator("#previous-results")).to_be_hidden()

        tab.goto(f"{BASE}/ev?phase=live")
        expect(tab).to_have_url(f"{BASE}/ev")
        expect(tab.locator("#phase-tabs")).to_be_hidden()
        assert list_reads[-1]["phase"] == "live"
        browser.close()


def fixtures():
    detroit = quote(
        "pmus-detroit",
        "polymarket_us",
        "over",
        "total",
        "205.5",
        decimal="100/81",
        source_clock_at="2026-11-12T23:59:40Z",
        confirmed_at="2026-11-12T23:59:52Z",
        received_at="2026-11-12T23:59:53Z",
        price_basis="native_book",
        trade_fee=dict(
            available=True,
            trade_fee_usd="0.01",
            classification="conservative",
            quantity="1",
            quantity_unit="USD normal claim",
            fill_count=1,
            fee_cashflows={},
        ),
    )
    other_detroit = [
        quote("kalshi-detroit", "kalshi", "over", "total", "205.5", decimal="24/19"),
        quote(
            "novig-detroit",
            "novig",
            "over",
            "total",
            "205.5",
            decimal="99/79",
            source_provider="sportsgameodds",
        ),
    ]
    denver_fair = dict(
        available=True,
        venue="draftkings",
        probability="1431/2887",
        contributors=[
            dict(
                venue="draftkings",
                inputs=[
                    dict(label="Denver +2.5", price_american="-108", source_at=START),
                    dict(
                        label="Minnesota −2.5", price_american="-112", source_at=START
                    ),
                ],
            )
        ],
    )
    denver_ev = str(100 * (Fraction("1431/2887") / Fraction("0.48") - 1))
    denver = quote(
        "pmus-denver",
        "polymarket_us",
        "cover",
        "spread",
        "2.5",
        participant="Denver",
        decimal="50/23",
        value=denver_ev,
        conservative=denver_ev,
        reason=None,
        reference_current=True,
        reference=dict(american="+102", decimal="2887/1431"),
        fair_reference=dict(books=["draftkings"], method="single"),
        reference_calculation=denver_fair,
    )
    kalshi_denver = quote(
        "kalshi-denver",
        "kalshi",
        "cover",
        "spread",
        "2.5",
        participant="Denver",
        decimal="25/13",
        value="-8.21",
        conservative="-8.21",
        reason=None,
    )
    minnesota = quote(
        "kalshi-minnesota",
        "kalshi",
        "cover",
        "spread",
        "-2.5",
        participant="Minnesota",
        decimal="100/49",
    )
    alternate = quote(
        "kalshi-denver-alt",
        "kalshi",
        "cover",
        "spread",
        "3.5",
        participant="Denver",
        alternate=True,
    )
    last_known = quote(
        "novig-denver",
        "novig",
        "cover",
        "spread",
        "2.5",
        participant="Denver",
        current=False,
        reason="Price expired",
        source_at="2026-11-12T07:00:00Z",
        source_provider="sportsgameodds",
    )
    negative = quote(
        "kalshi-washington",
        "kalshi",
        "win",
        "winner",
        participant="Washington",
        value="-3",
        conservative="-3",
        reason=None,
    )
    ev = [
        group(
            "ev-denver",
            DENVER,
            [denver, kalshi_denver],
            denver_ev,
            sportsbook_quotes={
                "draftkings": [dict(price_american="-107", current=True)],
                "fanduel": [dict(price_american="-111", current=True)],
                "caesars": [dict(price_american="-115", current=False)],
            },
        ),
        group(
            "ev-washington",
            WASHINGTON,
            [negative],
            "-3",
            sportsbook_quotes={
                "fanduel": [dict(price_american="-108", current=True)],
                "betmgm": [dict(price_american="-110", current=True)],
            },
        ),
    ]
    detroit_group = group("ev-detroit", DETROIT, [detroit, *other_detroit])
    denver_matrix = [
        ev[0],
        group("minnesota", DENVER, [minnesota]),
        group("denver-alt", DENVER, [alternate]),
        group(
            "a-denver-other-sign",
            DENVER,
            [
                quote(
                    "denver-other-sign",
                    "kalshi",
                    "cover",
                    "spread",
                    "-2.5",
                    participant="Denver",
                    alternate=True,
                )
            ],
        ),
        group(
            "z-minnesota-other-sign",
            DENVER,
            [
                quote(
                    "minnesota-other-sign",
                    "kalshi",
                    "cover",
                    "spread",
                    "2.5",
                    participant="Minnesota",
                    alternate=True,
                )
            ],
        ),
    ]
    arbs = [
        settlement(
            "arb-denver",
            DENVER,
            minnesota,
            denver,
            str(100 * Fraction("0.93") / Fraction("104.07")),
            "0.93",
            "104.07",
            ("105", "105"),
            ("51.45", "48.30"),
            ("1.84", "2.48"),
        ),
        settlement(
            "arb-washington",
            WASHINGTON,
            quote(
                "giants",
                "kalshi",
                "win",
                "winner",
                participant="Giants",
                decimal="25/14",
            ),
            quote(
                "washington",
                "polymarket_us",
                "win",
                "winner",
                participant="Washington",
                decimal="20/9",
            ),
            str(100 * Fraction("-5.03") / Fraction("104.03")),
            "-5.03",
            "104.03",
            ("99", "99"),
            ("55.44", "44.55"),
            ("1.71", "2.33"),
        ),
    ]
    return ev, detroit_group, denver_matrix, last_known, arbs


@pytest.mark.parametrize("width", [1440, 390])
def test_ranked_and_browse_journey(width, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    ev, detroit, denver, _, arbs = fixtures()
    original_quote = detroit["offers"][0]
    latest_quote = dict(
        original_quote,
        odds=dict(american="-400", decimal="1.25"),
        cost_per_normal_claim="0.80",
        price_revision="pmus-detroit-latest-price",
        economic_revision="pmus-detroit-latest-economics",
        evidence_result_id="pmus-detroit-latest-capture",
    )
    revised_quote = dict(
        latest_quote,
        trade_fee=dict(latest_quote["trade_fee"], trade_fee_usd="0.02"),
        economic_revision="pmus-detroit-revised-economics",
        evidence_result_id="pmus-detroit-revised-capture",
    )
    detroit_evidence = {
        offer["evidence_result_id"]: offer
        for offer in (original_quote, latest_quote, revised_quote)
    }
    errors = []
    provider_requests = []
    unavailable = False
    show_current_prices = False
    browse_failure = False
    hide_game_prices = False
    current_quote = latest_quote
    change_during_adoption = False
    withdraw_selection = False
    pair_replacement = "original"
    pair_reads = 0
    sized_pairs = []
    inspected = []

    def respond(route):
        nonlocal current_quote, pair_reads
        url = urlparse(route.request.url)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.hostname != "predict.fixture":
            provider_requests.append(url.hostname)
            route.abort()
            return
        if url.path in ("/", "/ev", "/arbs", "/browse-odds", "/game"):
            route.fulfill(
                path=ASSETS / "desk.html", headers={"Referrer-Policy": "no-referrer"}
            )
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/comparison-current":
            assert "last_known" not in query
            if (
                browse_failure
                and query.get("browse_odds") == "1"
                and not query.get("game_key")
            ):
                route.fulfill(status=503)
                return
            if query.get("view") == "arbs":
                assert "stake" not in query
                rows = deepcopy(arbs)
                if query.get("game_key") == WASHINGTON:
                    pair_reads += 1
                    if pair_replacement == "stable" or (
                        pair_replacement == "changes" and pair_reads % 2 == 0
                    ):
                        pair = rows[1]["pairs"][0]
                        pair["retail_payoff"]["minimum_net_profit_usd"] = "-4.99"
                        pair["retail_payoff"]["funding_usd"] = "103.99"
                        pair["retail_payoff"]["legs"][1]["at_fill_usd"] = "2.29"
                        pair["score"] = str(
                            100 * Fraction("-4.99") / Fraction("103.99")
                        )
                        for state in pair["retail_payoff"]["states"].values():
                            state["net_profit_usd"] = "-4.99"
            elif query.get("browse_odds") == "1":
                rows = deepcopy(
                    denver if query.get("game_key") == DENVER else [detroit, *denver]
                )
                if query.get("lines") == "main":
                    rows = [
                        row for row in rows if not row["offers"][0].get("alternate")
                    ]
            elif unavailable:
                rows = []
            else:
                assert query.get("lines") in ("main", "all")
                rows = ev
            if query.get("game_key"):
                rows = [row for row in rows if row["game_key"] == query["game_key"]]
                if hide_game_prices:
                    rows = []
            ranked = sum(row["score"] is not None for row in rows)
            if query.get("positive"):
                rows = [
                    row
                    for row in rows
                    if row["score"] is not None and Fraction(row["score"]) > 0
                ]
            if query.get("summary") == "1":
                rows = [public_group(row, query.get("basis")) for row in rows]
            route.fulfill(
                json=dict(
                    state="ready",
                    rows=rows,
                    price_preview=(
                        [public_group(detroit, query.get("basis"))]
                        if show_current_prices and not rows and query.get("ranked")
                        else []
                    ),
                    games=[
                        dict(
                            game_key=DENVER, title=DENVER, start_at=START, league="NBA"
                        )
                    ],
                    total=len(rows),
                    matched_offer_count=12,
                    matched_outcome_count=4,
                    ranked_group_count=ranked,
                    ranking_stake="100" if query.get("view") == "arbs" else None,
                    publication=dict(
                        current_prices=12,
                        read_at="2026-11-13T00:00:00Z",
                        published_at="2026-11-12T23:59:54Z",
                        sources={
                            "sportsgameodds": {
                                "state": "held",
                                "reason_code": "sgo_charge_unresolved",
                            }
                        }
                        if unavailable
                        else {},
                    ),
                    calculation_reason="The sportsbook reference source is on hold.",
                )
            )
        elif url.path == "/api/comparison-current/selection":
            route.fulfill(json={"row": None if withdraw_selection else current_quote})
        elif url.path == "/api/comparison-current/lease":
            route.fulfill(json={"lease_id": "fixture"})
        elif url.path == "/api/comparison-snapshot/details":
            if "stake" in query:
                pair = deepcopy(arbs[1]["pairs"][0])
                assert query == dict(
                    id=pair["id"],
                    result_id=pair["evidence_result_id"],
                    lease_id="fixture",
                    stake="150",
                )
                sized_pairs.append(pair["id"])
                pair["inspection"]["funding_usd"] = "150"
                pair["retail_payoff"]["sizing"]["requested_stake_usd"] = "150"
                route.fulfill(json=pair)
                return
            inspected.append(query["id"])
            for arb in arbs:
                pair = arb["pairs"][0]
                if pair["id"] == query["id"]:
                    route.fulfill(json=dict(pair, offers=arb["offers"]))
                    return
            cost = "0.81"
            if query["id"] == original_quote["id"]:
                selected = detroit_evidence[query["result_id"]]
                cost = selected["cost_per_normal_claim"]
                # Publish the fee change after the adoption request has found exact evidence.
                if change_during_adoption and selected is latest_quote:
                    current_quote = revised_quote
            else:
                selected = next(
                    offer
                    for row in [*ev, detroit, *denver]
                    for offer in row["offers"]
                    if offer["id"] == query["id"]
                )
            route.fulfill(
                json=dict(
                    captured_at=START,
                    row=selected,
                    desk_offer=selected,
                    inspection=dict(
                        identity={},
                        original=dict(value=cost, units="usd"),
                        source={},
                        before_fees=dict(cost_usd=cost),
                        fair_reference=dict(available=False),
                    ),
                )
            )
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        with browser.new_context(
            viewport={"width": width, "height": 850}, service_workers="block"
        ) as context:
            context.route("**/*", respond)
            if width == 390:
                context.add_init_script(
                    "Object.defineProperty(window, 'navigation', {value: undefined})"
                )
            tab = context.new_page()
            tab.clock.set_fixed_time("2026-11-13T00:00:00Z")
            tab.on("pageerror", lambda error: errors.append(str(error)))
            tab.goto(BASE)
            expect(tab.get_by_role("heading", name="Opportunities")).to_be_visible()
            tab.get_by_label("Calculation basis").select_option("reviewed")
            cards = tab.locator(".opportunity-card")
            expect(cards).to_have_count(2)
            expect(cards.first).to_contain_text("+3.26%")
            market = cards.first.locator(".compact-ev-market")
            prices = market.get_by_role("group", name="Prediction market offers")
            expect(market.get_by_role("heading", name="Denver to cover +2.5")).to_be_visible()
            expect(prices.get_by_role("button")).to_have_text([
                "Polymarket US+117.39+3.26%", "Kalshi-108.33-8.21%",
            ])
            books = cards.first.get_by_role("group", name="Fair odds and sportsbook quotes")
            expect(books).to_contain_text("Fair odds +102")
            expect(books.locator(":scope > span")).to_have_text([
                "Fair odds +102", "DraftKings -108Used for fair odds", "FanDuel -111", "Caesars -115Last known",
            ])
            assert market.bounding_box()["y"] < books.bounding_box()["y"]
            if width == 1440:
                assert abs(market.get_by_role("heading").bounding_box()["y"] - prices.bounding_box()["y"]) < 7
            expect(cards.first).not_to_contain_text("Current")
            expect(cards.first).not_to_contain_text("Comparison sportsbook")
            expect(cards.first).not_to_contain_text("-112")
            expect(cards.last).to_contain_text("-3.00%")
            assert not inspected
            cards.first.get_by_role(
                "button", name="View trade details: Polymarket US", exact=False
            ).press("Enter")
            fair = tab.get_by_role(
                "dialog", name="Polymarket US · Denver to cover +2.5"
            )
            expect(fair.get_by_text("-112", exact=False).first).to_be_visible()
            expect(fair.get_by_role("heading", name="Before-fee cashflows")).to_be_visible()
            assert inspected == ["pmus-denver"]
            tab.keyboard.press("Escape")
            expect(
                tab.get_by_text(
                    "Open a quote to see its source and receipt times.", exact=True
                )
            ).to_have_count(0)
            expect(tab.get_by_role("link", name="Arbitrage")).to_be_visible()
            tab.screenshot(path=tmp_path / f"ranked-ev-{width}.png")
            tab.get_by_role("checkbox", name="Positive only").check()
            expect(cards).to_have_count(1)
            tab.get_by_role("checkbox", name="Positive only").uncheck()
            expect(cards).to_have_count(2)

            cards.first.get_by_role("link", name="Open game ↗").press("Enter")
            expect(tab.get_by_role("heading", name=DENVER)).to_be_visible()
            expect(tab.get_by_label("Calculation basis")).to_have_value("reviewed")
            expect(tab.get_by_label("Alternate lines")).not_to_be_checked()
            expect(tab.locator(".odds-matrix tbody tr")).to_have_count(2)
            tab.get_by_label("Alternate lines").check()
            expect(tab.locator(".odds-matrix tbody tr")).to_have_count(5)
            expect(tab.locator(".odds-matrix tbody th")).to_have_text(
                [
                    "Denver to cover -2.5",
                    "Minnesota to cover +2.5",
                    "Denver to cover +2.5",
                    "Minnesota to cover -2.5",
                    "Denver to cover +3.5",
                ]
            )
            expect(tab.get_by_role("columnheader", name="Novig")).to_be_visible()
            expect(
                tab.get_by_role("columnheader", name="Polymarket US")
            ).to_be_visible()
            expect(
                tab.get_by_role("columnheader", name="EV", exact=True)
            ).to_have_count(0)
            expect(
                tab.locator(".odds-matrix thead tr").first.locator("th")
            ).to_have_text(["Exact outcome", "Prediction markets", "Fair odds"])
            fair = (
                tab.get_by_role("row")
                .filter(has_text="Denver to cover +2.5")
                .locator(".matrix-fair-odds")
            )
            expect(fair).to_contain_text("+102")
            expect(fair).to_contain_text("DraftKings")
            expect(tab.get_by_role("columnheader", name="DraftKings")).to_have_count(0)
            popout = tab.get_by_role("region", name="Sportsbook prices")
            expect(popout).to_have_count(0)
            fair.get_by_role(
                "button", name="Sportsbook prices for Denver to cover +2.5"
            ).click()
            expect(popout).to_be_visible()
            expect(popout).to_contain_text("-108")
            tab.keyboard.press("Escape")
            expect(popout).to_have_count(0)
            expect(tab.locator('[data-offer-id="pmus-denver"]')).to_contain_text(
                "+3.26% After-fee EV"
            )
            expect(tab.locator('[data-offer-id="kalshi-denver"]')).to_contain_text(
                "-8.21% After-fee EV"
            )
            expect(
                tab.locator('[data-offer-id="kalshi-minnesota"]')
            ).not_to_contain_text("EV")
            if width == 390:
                matrix = tab.locator(".odds-scroll")
                assert matrix.evaluate("el => el.scrollWidth > el.clientWidth")
                # Opening the sportsbook popout can already scroll to the last column.
                matrix.evaluate("el => { el.scrollLeft = el.scrollWidth; }")
                first_columns = tab.get_by_role(
                    "button", name="Scroll to the first odds column"
                )
                expect(first_columns).to_be_visible()
                first_columns.click()
                tab.wait_for_function(
                    "document.querySelector('.odds-scroll').scrollLeft === 0"
                )
                more_columns = tab.get_by_role(
                    "button", name="Scroll to see more odds columns"
                )
                expect(more_columns).to_be_visible()
                more_columns.click()
                tab.wait_for_function(
                    "document.querySelector('.odds-scroll').scrollLeft > 0"
                )
                assert tab.get_by_role(
                    "rowheader", name="Denver to cover +2.5", exact=False
                ).evaluate(
                    "(el) => Math.abs(el.getBoundingClientRect().left - el.closest('.odds-scroll').getBoundingClientRect().left) < 2"
                )
            tab.get_by_label("Alternate lines").uncheck()
            expect(tab.locator(".odds-matrix tbody tr")).to_have_count(2)
            hide_game_prices = True
            tab.get_by_role("button", name="Refresh list").click()
            expect(
                tab.get_by_role("heading", name="No prices available for this matchup")
            ).to_be_visible()
            expect(tab.get_by_role("heading", name=DENVER)).to_be_visible()
            expect(tab.get_by_label("Last-known prices")).not_to_be_visible()
            expect(tab.locator('[data-offer-id="novig-denver"]')).to_have_count(0)
            hide_game_prices = False
            tab.get_by_role("navigation", name="Current view").get_by_role(
                "link", name="Back"
            ).click()
            expect(cards).to_have_count(2)
            expect(tab.get_by_label("Calculation basis")).to_have_value("reviewed")

            unavailable = True
            tab.get_by_role("button", name="Refresh list").click()
            expect(
                tab.get_by_role("heading", name="No matching EV comparisons")
            ).to_be_visible()
            expect(
                tab.get_by_text("The sportsbook reference source is on hold.")
            ).to_be_visible()
            expect(tab.locator("#notice")).to_contain_text(
                "SportsGameOdds updates are on hold pending provider reconciliation"
            )
            show_current_prices = True
            tab.get_by_role("button", name="Refresh list").click()
            expect(tab.get_by_role("heading", name="Current prices")).to_be_visible()
            expect(
                tab.locator(".odds-card").get_by_role("heading", name=DETROIT)
            ).to_be_visible()
            expect(cards).to_have_count(0)
            show_current_prices = False
            tab.get_by_role("link", name="Find my game ↗").click()
            expect(tab.get_by_role("heading", name=DETROIT)).to_be_visible()
            quote_button = tab.locator('[data-offer-id="pmus-detroit"]')
            expect(quote_button).not_to_contain_text("20s ago")
            assert quote_button.get_attribute("title") is None
            tab.get_by_role("button", name="Filters", exact=True).click()
            tab.get_by_role("dialog", name="Filter results").get_by_label(
                "Winner"
            ).uncheck()
            tab.get_by_role("dialog", name="Filter results").get_by_label(
                "Total"
            ).uncheck()
            tab.get_by_role("button", name="Done").click()
            expect(
                tab.get_by_role("button", name="Clear Spread filter")
            ).to_be_visible()
            tab.locator(".odds-card").filter(has_text=DENVER).get_by_role(
                "link", name="Open game ↗"
            ).click()
            expect(
                tab.get_by_role("button", name="Spreads", exact=True)
            ).to_have_attribute("aria-pressed", "true")
            browse_failure = True
            tab.get_by_role("navigation", name="Current view").get_by_role(
                "link", name="Back"
            ).click()
            expect(
                tab.get_by_role("button", name="Clear Spread filter")
            ).to_be_visible()
            expect(tab.locator("#notice")).to_contain_text("Prices could not be loaded")
            expect(tab.locator(".odds-card")).to_have_count(0)
            browse_failure = False
            tab.get_by_role("button", name="Refresh list").click()
            expect(tab.locator("#notice")).not_to_contain_text(
                "Prices could not be loaded"
            )
            tab.locator(".odds-card").filter(has_text=DENVER).get_by_role(
                "link", name="Open game ↗"
            ).click()
            tab.go_back()
            expect(
                tab.get_by_role("button", name="Clear Spread filter")
            ).to_be_visible()
            tab.get_by_role("button", name="Clear Spread filter").click()
            tab.locator('[data-calculation-id="pmus-denver"]').press("Enter")
            expect(tab.locator("#trade [data-inspection-ev]")).to_have_text(
                "Current at inspection"
            )
            withdraw_selection = True
            with tab.expect_response(
                lambda response: (
                    urlparse(response.url).path == "/api/comparison-current/selection"
                )
            ):
                tab.evaluate("document.getElementById('refresh-list').click()")
            expect(tab.locator("#trade [data-inspection-price]")).to_have_text(
                "Price at inspection"
            )
            expect(tab.locator("#trade [data-inspection-ev]")).to_have_text(
                "EV at inspection"
            )
            withdraw_selection = False
            tab.keyboard.press("Escape")
            expect(tab.locator("#trade")).to_be_hidden()
            quote_button.press("Enter")
            drawer = tab.get_by_role("dialog", name="Polymarket US · Over 205.5")
            expect(drawer.get_by_text("$0.81 per $1 payout")).to_be_visible()
            drawer.get_by_text("Quote times", exact=True).click()
            times = drawer.locator(".inspection-facts").first
            expect(times.locator("dt")).to_have_text(
                [
                    "Original source update",
                    "Book confirmation",
                    "Collector receipt",
                    "Price capture",
                    "Board publication",
                ]
            )
            expect(times.locator("dd")).to_have_text(
                [
                    "2026-11-12T23:59:40Z",
                    "2026-11-12T23:59:52Z",
                    "2026-11-12T23:59:53Z",
                    START,
                    "2026-11-12T23:59:54Z",
                ]
            )
            expect(
                drawer.locator(".inspection-tiles").get_by_text("$0.01", exact=True)
            ).to_be_visible()
            expect(
                drawer.get_by_text(
                    "The sportsbook jurisdiction and applicable market rules are unverified."
                )
            ).to_be_visible()

            change_during_adoption = True
            passive_read = tab.evaluate(
                """async id => {
                    const query = new URLSearchParams({id, layout: 'desk', basis: 'reviewed', phase: 'pregame'});
                    const response = await fetch(`/api/comparison-current/selection?${query}`);
                    return (await response.json()).row.evidence_result_id;
                }""",
                original_quote["id"],
            )
            assert passive_read == latest_quote["evidence_result_id"]
            drawer.get_by_role("button", name="Use latest prices").click()
            expect(
                drawer.get_by_text(
                    "The price, fee, or reference changed during adoption.", exact=False
                )
            ).to_be_visible()
            expect(drawer.get_by_text("$0.81 per $1 payout")).to_be_visible()
            drawer.get_by_role("button", name="Use latest prices").click()
            expect(drawer.get_by_text("$0.80 per $1 payout")).to_be_visible()
            expect(
                drawer.locator(".inspection-tiles").get_by_text("$0.02", exact=True)
            ).to_be_visible()
            drawer.get_by_role("button", name="Use latest prices").click()
            expect(drawer.get_by_role("status")).to_contain_text("No newer quote")
            tab.keyboard.press("Escape")
            expect(quote_button).to_be_focused()

            tab.goto(BASE + "/arbs")
            expect(cards).to_have_count(2)
            expect(cards.last.locator(".arb-card-legs li")).to_have_count(2)
            expect(cards.last).to_contain_text("$104.03")
            expect(cards.first).to_contain_text("+0.89%")
            expect(cards.last).to_contain_text("-4.84%")
            tab.screenshot(path=tmp_path / f"ranked-arb-{width}.png")
            cards.last.get_by_role("button", name="View payoff calculation ↗").press(
                "Enter"
            )
            payoff = tab.get_by_role("dialog", name="Pair payoff")
            expect(payoff.get_by_text("$104.03", exact=True)).to_be_visible()
            assert "arb-washington" in inspected
            expect(
                payoff.locator(".inspection-payoffs").get_by_text(
                    "Tie or exact-line settlement"
                )
            ).to_be_visible()
            expect(payoff.locator(".inspection-payoffs tr").last).to_contain_text(
                "-$5.03"
            )
            payoff.get_by_text(
                "Exact prices, settlement terms and fee rounding", exact=True
            ).click()
            expect(payoff.get_by_text("Payout by leg")).to_be_visible()
            expect(
                payoff.get_by_text("Kalshi $49.50 · Polymarket US $49.50")
            ).to_be_visible()
            payoff.get_by_text("Sized fee rounding").first.click()
            expect(payoff.get_by_text("Raw fee").first).to_be_visible()
            pair_replacement = "changes"
            pair_reads = 0
            payoff.get_by_role("button", name="Use latest prices").click()
            expect(
                payoff.get_by_text("The pair changed during adoption.", exact=False)
            ).to_be_visible()
            expect(payoff.locator(".inspection-payoffs tr").last).to_contain_text(
                "-$5.03"
            )
            pair_replacement = "stable"
            payoff.get_by_role("button", name="Use latest prices").click()
            expect(payoff.locator(".inspection-payoffs tr").last).to_contain_text(
                "-$4.99"
            )
            payoff.get_by_label("Total stake before fees ($)").fill("150")
            payoff.get_by_role("button", name="Size this pair").click()
            expect(
                payoff.get_by_text(
                    "Calculated for a $150.00 stake before fees", exact=False
                )
            ).to_be_visible()
            assert sized_pairs == [arbs[1]["pairs"][0]["id"]]
            expect(cards.first).to_contain_text("+0.89%")
            assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")
        browser.close()
    assert not errors, errors
    assert not provider_requests, provider_requests
