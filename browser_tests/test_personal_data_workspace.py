"""Bounded Data navigation, exact evidence and shared checkpoint inspection."""

from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

from browser_tests.test_pregame_current import ASSETS
from browser_tests.test_research_workspace import record, research_http_fixture


def test_missing_score_scope_and_settings_diagnostics_on_mobile():
    tracked_game = "a" * 64
    score_reads = []

    def serve(route):
        url = urlparse(route.request.url)
        if url.path in ("/data", "/settings"):
            route.fulfill(path=ASSETS / (url.path[1:] + ".html"))
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/research/data/results":
            score_reads.append(parse_qs(url.query))
            route.fulfill(json=dict(rows=[], offset=0))
        elif url.path == "/api/admin/status":
            route.fulfill(
                json=dict(
                    dispatch_enabled=True,
                    config=dict(aggregate_provider="sportsgameodds"),
                    data_runtime=dict(healthy=True, paused_sources=["kalshi"]),
                    sources=[
                        dict(provider="kalshi"),
                        dict(
                            provider="sportsgameodds",
                            worker_behavior="accounting_hold",
                            next_action="Inspect the pending accounting hold.",
                        ),
                    ],
                    quota=dict(reserved=2, held_uncertain_credits=2),
                )
            )
        elif url.path == "/api/admin/activity-mode":
            route.fulfill(json=dict(settings=dict(monitor_interval_seconds=1800)))
        elif url.path == "/api/workspace/status":
            route.fulfill(
                json=dict(
                    storage={},
                    fee_mode=dict(enabled=False),
                    reference_scope=dict(books=[]),
                    readiness=dict(
                        blockers=[dict(message="Capture storage is full.")],
                        state="blocked",
                    ),
                )
            )
        elif url.path == "/api/workspace/mens-d1/status":
            route.fulfill(
                json=dict(
                    source="college_basketball_data",
                    state="paused",
                    reason="account_hold",
                    credits=dict(held=1),
                    storage={},
                    jobs=[],
                    overdue_jobs=1,
                )
            )
        elif url.path == "/api/workspace/collection":
            route.fulfill(
                json=dict(state="Collecting", problem="Waiting on a credit hold")
            )
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(
            viewport=dict(width=390, height=844), is_mobile=True, has_touch=True
        )
        page.goto(base + "/data?evidence=populations&tracked_game=" + tracked_game)
        expect(page.get_by_role("link", name="Game scores")).to_have_attribute(
            "aria-current", "page"
        )
        expect(page.locator("#data-sporting-results")).to_contain_text(
            "No retained odds-provider score for this game."
        )
        page.locator("#data-result-filters select[name=sport]").select_option("NCAAB")
        page.get_by_role("button", name="Apply filters").click()
        expect(page.locator("#data-sporting-results")).to_contain_text(
            "No retained odds-provider score for this game."
        )
        assert score_reads[-1] == dict(tracked_game=[tracked_game], sport=["NCAAB"])

        page.goto(base + "/settings")
        expect(page.get_by_role("button", name="Stop collection")).to_be_enabled()
        expect(page.get_by_role("checkbox", name="Include fees")).not_to_be_checked()
        expect(page.locator("#retention-readiness")).to_have_text(
            "Capture storage is full."
        )
        expect(page.locator("#source-rows")).to_contain_text("Credit hold")
        expect(page.locator("#source-rows")).to_contain_text("KalshiPaused")
        expect(page.locator("#mens-d1-problem")).to_contain_text("1 past-due job")
        expect(page.locator("#credits")).to_contain_text(
            "CollegeBasketballData API unconfirmed calls1"
        )
        assert not page.locator("#diagnostics").evaluate("element => element.open")
        page.get_by_role("link", name="Inspect unresolved request evidence").click()
        expect(page.locator("#hold-evidence")).to_contain_text('"reserved_exposure": 2')
        page.goto(base + "/settings#mens-d1-jobs")
        expect(
            page.get_by_role("link", name="Open Men’s D1 reconciliation")
        ).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth === window.innerWidth"
        )
        browser.close()


def test_data_game_exact_export_checkpoint_and_back():
    experiment = json.loads(
        Path("tests/fixtures/experiment-workspace.json").read_text()
    )
    game = dict(
        id="canonical:game",
        title="Away at Home",
        sport="NCAAB",
        start_at="2026-11-23T01:00:00Z",
        identity_status="canonical",
        records=2,
        books=["polymarket", "prophetx"],
        source_events=[dict(provider="sportsgameodds", event_id="source-event")],
        latest_received_at="2026-11-22T20:00:00Z",
        experiment=dict(id="game-captured", revision=experiment["detail"]["revision"]),
    )
    rows = [record("negative"), record("unavailable")]
    for row in rows:
        row.update(
            game_id=game["id"],
            sport="NCAAB",
            main_role="alternate"
            if row["calculation"]["status"] == "negative"
            else "main",
        )
    reference = record("positive")
    reference.update(
        id="sgo:reference",
        revision="captured-reference",
        game_id=game["id"],
        sport="NCAAB",
        main_role="main",
        original_bookmaker_id="fanduel",
        represented_venue="fanduel",
    )
    rows.append(reference)
    historical = record("positive")
    historical.update(
        id="sgo:historical-exchange",
        revision="captured-historical-exchange",
        game_id=game["id"],
        sport="NCAAB",
        main_role="main",
        original_bookmaker_id="matchbook",
        represented_venue="matchbook",
    )
    rows.append(historical)
    details = {
        row["id"]: dict(
            row,
            captured_at="2026-11-22T20:00:00Z",
            source_input=dict(price_american="+120"),
            original_response=dict(
                state="not_recorded", reason="Historical original absent"
            ),
            calculation_payload=None,
            fee_input=None,
            price_payload=None,
            reproduction="Exact stored source input",
            checkpoint_bet_id="case-pn",
        )
        for row in rows
    }
    requests, errors = [], []

    def serve(route):
        url = urlparse(route.request.url)
        query = {key: value[0] for key, value in parse_qs(url.query).items()}
        requests.append((route.request.method, url.path, query))
        if url.path == "/data":
            route.fulfill(path=ASSETS / (url.path[1:] + ".html"))
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/research/games":
            route.fulfill(
                json=dict(
                    token="frozen-read",
                    captured_at="2026-11-22T20:00:00Z",
                    rows=[game],
                    total=1,
                    offset=0,
                    next_offset=None,
                    counts=dict(canonical_games=1, source_local_games=0),
                )
            )
        elif url.path in ("/api/research/game", "/api/research/catalog"):
            selected = [rows[1]] if query.get("contract_id") == "old-contract" else rows
            route.fulfill(
                json=dict(
                    game=game,
                    token="frozen-read",
                    rows=selected,
                    total=len(selected),
                    offset=0,
                    next_offset=None,
                )
            )
        elif url.path == "/api/research/input":
            assert query["token"] == "frozen-read"
            value = details[query["id"]]
            assert query["revision"] == value["revision"]
            route.fulfill(json=value)
        elif url.path == "/api/research/experiment":
            value = (
                experiment["export"]
                if query.get("export")
                else experiment["detail"]
                if query.get("id")
                else experiment["listing"]
            )
            route.fulfill(json=deepcopy(value))
        elif url.path == "/api/research/read":
            route.fulfill(json=dict(released=True))
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(
            viewport=dict(width=960, height=700), accept_downloads=True
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(
            base + "/data?view=history&sport=NCAAB&date=2026-11-22"
            "&provider=sportsgameodds&reference_scope=selected"
        )
        expect(page.locator("#catalog-status")).to_contain_text("1 game")
        expect(page.locator("nav[aria-label=Main] a")).to_have_count(3)
        expect(
            page.get_by_role("navigation", name="Data sections").get_by_role("link")
        ).to_have_text(["Market history", "Game scores"])
        expect(page.get_by_role("link", name="Men’s D1 reconciliation")).to_be_hidden()
        page.get_by_text("Diagnostics", exact=True).click()
        expect(
            page.get_by_role("link", name="Men’s D1 reconciliation")
        ).to_have_attribute(
            "href", "/data?evidence=mens-d1&scope=mens-d1&date=2026-11-22&view=history"
        )
        expect(page.get_by_role("link", name="Tables", exact=True)).to_have_attribute(
            "href", "/data?evidence=tables"
        )
        page.get_by_text("Diagnostics", exact=True).click()
        expect(
            page.get_by_role("link", name="Create experiment from these filters")
        ).to_have_count(0)
        page.get_by_role("link", name="Open game", exact=True).click()
        expect(page.locator("#game-detail")).to_be_visible()
        expect(page.locator("#game-content")).to_contain_text("Role: alternate")
        expect(page.locator("#game-content")).to_contain_text("Role: main")
        expect(
            page.locator("#game-content").get_by_role("link", name="Odds pulls")
        ).to_have_attribute("href", "/data?evidence=pulls&event_id=source-event")
        expect(
            page.locator("#game-content").get_by_role("link", name="Captures")
        ).to_have_attribute(
            "href",
            "/data?evidence=checkpoints&id=game-captured&revision="
            + experiment["detail"]["revision"]
            + "&event_id=source-event",
        )
        page.locator('[data-record="' + rows[1]["id"] + '"] button').click()
        dialog = page.locator("#input-detail")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("fee_unknown")
        expect(dialog).to_contain_text("Original price+120")
        with page.expect_download() as download:
            dialog.get_by_role("link", name="Export this exact input & result").click()
        exported = json.loads(Path(download.value.path()).read_text())
        assert exported["revision"] == rows[1]["revision"]
        assert exported["calculation"]["net_ev_percent"] is None
        dialog.get_by_role("link", name="Compare this exact bet").click()
        comparison = page.locator("#experiment-detail")
        expect(comparison).to_be_visible()
        expect(comparison).to_contain_text("Exact bet IDcase-pn")
        expect(comparison).to_contain_text("Screening exact EV")
        page.go_back()
        expect(dialog).to_be_visible()
        expect(comparison).not_to_be_visible()
        assert "sport=NCAAB" in page.url and "date=2026-11-22" in page.url
        page.reload()
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("fee_unknown")
        page.get_by_role("button", name="Close", exact=True).click()
        page.locator('[data-record="sgo:reference"] button').click()
        expect(dialog).to_contain_text("Reference only")
        expect(dialog).not_to_contain_text("5. Calculation result")
        expect(page.locator('[data-record="sgo:reference"]')).to_contain_text(
            "Reference only"
        )
        expect(page.locator('[data-record="sgo:reference"]')).not_to_contain_text(
            "Net EV:"
        )
        page.get_by_role("button", name="Close", exact=True).click()
        page.locator('[data-record="sgo:historical-exchange"] button').click()
        expect(dialog).to_contain_text("Trading market context")
        expect(dialog).not_to_contain_text("Reference only")
        expect(page.locator('[data-record="sgo:historical-exchange"]')).to_contain_text(
            "calculation unavailable"
        )
        page.goto(base + "/data?id=old-contract")
        expect(dialog).to_be_visible()
        assert "bet=sgo%3Aunavailable" in page.url
        page.get_by_role("button", name="Close", exact=True).click()
        page.goto(base + "/data?evidence=checkpoints&event_id=source-event")
        expect(page.locator("#experiment-status")).to_contain_text("4 retained cases")
        expect(page.locator("#catalog")).to_be_hidden()
        assert any(
            path == "/api/research/games"
            and query.get("reference_scope") == "selected"
            and query.get("provider") == "sportsgameodds"
            for _, path, query in requests
        )
        assert any(
            path == "/api/research/catalog"
            and query.get("reference_scope") == "all"
            and not query.get("provider")
            for _, path, query in requests
        )
        assert any(
            path == "/api/research/experiment"
            and query.get("event_id") == "source-event"
            for _, path, query in requests
        )
        assert not errors, errors
        assert all(
            method == "GET" or path == "/api/research/read"
            for method, path, _ in requests
        )
        assert all(
            "/api/research/" in path
            or "/view/" in path
            or path in ("/data", "/favicon.ico", "/api/workspace/collection")
            for _, path, _ in requests
        )
        browser.close()


def test_arbitrage_selection_revision_and_supported_filters():
    pair = dict(
        id="pair-one",
        game_key="game",
        game="Away at Home",
        league="NCAAB",
        kickoff="2026-11-23T01:00:00Z",
        family="moneyline",
        category="market_market",
        display_return="2.00%",
        minimum_profit_usd="2",
        committed_usd="100",
        legs=[
            dict(
                venue="kalshi",
                side="home",
                times=dict(source_at="2026-11-22T20:00:00Z"),
            ),
            dict(
                venue="novig", side="away", times=dict(source_at="2026-11-22T20:00:00Z")
            ),
        ],
    )
    errors = []

    def serve(route):
        url = urlparse(route.request.url)
        if url.path == "/data":
            route.fulfill(path=ASSETS / "data.html")
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/pregame/arbs":
            route.fulfill(
                json=dict(rows=[pair], total=1, offset=0, cursor="stored-state")
            )
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(
            base
            + "/data?view=arbitrage&date=2026-11-22&provider=sportsgameodds&calculation_status=negative"
        )
        expect(page.locator("#catalog-status")).to_contain_text(
            "1 stored paired comparisons"
        )
        for field in ("date", "calculation"):
            expect(page.locator("#" + field)).to_be_disabled()
        expect(page.locator("select#provider")).to_have_count(0)
        assert (
            "date=" not in page.url
            and "calculation_status=" not in page.url
            and "provider=sportsgameodds" in page.url
        )
        page.get_by_role("button", name="Inspect calculation", exact=True).click()
        expect(page.locator("#arb-detail")).to_be_visible()
        assert "pair=pair-one" in page.url and "pair_revision=" in page.url
        page.reload()
        expect(page.locator("#arb-detail")).to_be_visible()
        pair["minimum_profit_usd"] = "3"
        page.reload()
        expect(page.locator("#catalog-status")).to_contain_text(
            "selected paired calculation changed"
        )
        expect(page.locator("#arb-detail")).not_to_be_visible()
        assert not errors, errors
        browser.close()


def test_saved_capture_exact_export_restores_automatic_and_manual_links():
    row = dict(
        id="saved-row",
        game_title="Saved Away at Home",
        venue="kalshi",
        side="home",
        line="-4.5",
        original=dict(value="0"),
        times=dict(
            source_at="2026-11-22T19:55:00Z", received_at="2026-11-22T20:00:00Z"
        ),
    )
    detail = dict(
        row=row,
        captured_at="2026-11-22T20:00:00Z",
        inspection=dict(reason="reference_unavailable"),
        originals=dict(received="stored bytes"),
    )
    seen = []

    def serve(route):
        url = urlparse(route.request.url)
        query = {key: value[0] for key, value in parse_qs(url.query).items()}
        seen.append((url.path, query))
        if url.path == "/data":
            route.fulfill(path=ASSETS / "data.html")
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path in ("/api/odds-replay", "/api/comparison-snapshot"):
            route.fulfill(
                json=dict(
                    rows=[row],
                    total=1,
                    result_id="saved-capture",
                    captured_at=detail["captured_at"],
                    replay=dict(id="saved-capture", captured_at=detail["captured_at"]),
                )
            )
        elif url.path.endswith("/details"):
            route.fulfill(json=detail)
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(accept_downloads=True)
        for url, api in (
            (
                "/data?game_key=saved-game&game_capture=saved-capture",
                "/api/odds-replay",
            ),
            (
                "/data?game_key=saved-game&result_id=saved-capture",
                "/api/comparison-snapshot",
            ),
        ):
            page.goto(base + url)
            expect(page.locator("#game-content")).to_contain_text(
                "Saved capture evidence"
            )
            assert any(path == api for path, _ in seen)
            page.get_by_role("button", name="Inspect exact saved observation").click()
            expect(page.locator("#input-detail")).to_contain_text("Source price0")
            assert "saved_bet=saved-row" in page.url
            page.reload()
            expect(page.locator("#input-detail")).to_be_visible()
            with page.expect_download() as downloaded:
                page.get_by_role(
                    "link", name="Export this exact saved observation"
                ).click()
            assert json.loads(Path(downloaded.value.path()).read_text()) == detail
            page.get_by_role("button", name="Close", exact=True).click()
            expect(page.locator("#input-detail")).not_to_be_visible()
            page.wait_for_url(lambda url: "saved_bet=" not in url)
            page.go_back()
            assert "saved_bet=saved-row" in page.url, page.url
            expect(page.locator("#input-detail")).to_be_visible()
        browser.close()


def test_saved_session_exact_cutoff_survives_reload_and_close():
    detail = dict(
        game=dict(
            title="Verified saved game",
            product_identity=dict(line="-4.5"),
            sides={"kalshi:yes:exact": dict(participant="Home", native_label="YES")},
        ),
        point=dict(at="2026-11-22T20:00:00Z", cards=[]),
        source_rows=[dict(price=0)],
        references=[],
        selected_contract="kalshi:yes:exact",
        request_assumptions={},
    )

    def serve(route):
        url = urlparse(route.request.url)
        query = {key: value[0] for key, value in parse_qs(url.query).items()}
        if url.path == "/data":
            route.fulfill(path=ASSETS / "data.html")
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/workspace/session":
            assert (
                query["session"] == "received~game"
                and query["cutoff"] == "fixed-cutoff"
            )
            selected = deepcopy(detail)
            selected["selected_contract"] = query.get("contract")
            route.fulfill(
                json=dict(
                    session_id="received",
                    cutoff="fixed-cutoff",
                    captured_at="2026-11-22T20:00:00Z",
                    state="saved",
                    selected=selected,
                    games=[],
                    calculation_note="No new calculation",
                    provider_requests=0,
                    scheduled_calculations=0,
                )
            )
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(accept_downloads=True)
        page.goto(
            base
            + "/data?session=received~game&hash=received&cutoff=fixed-cutoff&contract=kalshi%3Ayes%3Aexact"
        )
        expect(page.locator("#input-detail")).to_be_visible()
        expect(page.locator("#input-detail")).to_contain_text("fixed-cutoff")
        page.reload()
        expect(page.locator("#input-detail")).to_be_visible()
        with page.expect_download() as download:
            page.get_by_role("link", name="Export this exact saved evidence").click()
        value = json.loads(Path(download.value.path()).read_text())
        assert value["inspection_selection"] == dict(
            session_id="received", cutoff="fixed-cutoff", contract="kalshi:yes:exact"
        )
        assert (
            value["source_evidence"]["cutoff"] == "fixed-cutoff"
            and value["source_evidence"]["selected"]["source_rows"][0]["price"] == 0
        )
        page.get_by_role("button", name="Close", exact=True).click()
        page.wait_for_url(lambda url: "contract=" not in url)
        assert (
            "session=received%7Egame" in page.url or "session=received~game" in page.url
        )
        assert "cutoff=fixed-cutoff" in page.url
        page.go_back()
        expect(page.locator("#input-detail")).to_be_visible()
        browser.close()
