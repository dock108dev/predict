"""Personal research inspection across status, provenance and captured export."""

import json
import mimetypes
import os
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

from app.dashboard.workspace_routes import PAGES
from browser_tests.test_pregame_current import ASSETS, offer


def test_daily_research_keeps_current_and_saved_versions_independent():
    day = "2026-11-24"
    older, latest = "a" * 64, "b" * 64
    late = "2026-11-24T20:00:00Z"
    runs = [
        dict(id=run_id, summary={"title": "Men’s D1"}, observed_at=late)
        for run_id in (latest, older)
    ]
    summary = dict(
        population=dict(
            provider_known_games=4,
            revision="dated-slate",
            source_eligible_games=4,
            source_returned_mens_games=4,
            source_eligible_known_before_tminus10=4,
        ),
        capture=dict(current_frozen=2, current_denominator=4),
        markets={},
        reference={},
        trade=dict(variants={}),
        results=dict(denominator=4, states=dict(pending=4)),
    )
    coverage_reads, errors = [], []

    def serve(route):
        url = urlparse(route.request.url)
        query = parse_qs(url.query)
        if url.path == "/api/workspace/mens-d1":
            run = query.get("run", [None])[0]
            coverage_reads.append(run)
            value = dict(
                date=day,
                as_of=late,
                source_state="active",
                population_revision="dated-slate",
                coverage_summary=summary,
                runs=runs[:1],
                analysis_run=runs[0],
                run=next(
                    (candidate for candidate in runs if candidate["id"] == run), None
                ),
                facets={},
                offer_counts={},
                games=[],
                missing_items=[],
            )
            route.fulfill(json=value)
        elif url.path in ("/api/workspace/status", "/api/workspace/collection"):
            route.fulfill(json={})
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
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{base}/data?evidence=mens-d1&scope=mens-d1&date={day}")
        current = page.get_by_role("link", name="Current evidence", exact=True)
        expect(current).to_have_attribute("aria-current", "true")
        assert "run=" not in page.url
        expect(
            page.get_by_role("link", name="Open Experiments for this date", exact=True)
        ).to_have_attribute("href", f"/experiments?scope=mens-d1&date={day}")
        versions = page.locator("details").filter(
            has_text="Saved experiment versions for this date"
        )
        versions.locator("summary").click()
        expect(versions.locator(f'a[href*="run={older}"]')).to_have_count(0)
        versions.locator(f'a[href*="run={latest}"]').click()
        saved = page.get_by_role("link", name="Saved Nov 24", exact=False)
        expect(saved).to_have_attribute(
            "href", f"/data?evidence=mens-d1&scope=mens-d1&date={day}&run={latest}"
        )
        page.reload()
        expect(saved).to_have_attribute("aria-current", "true")
        page.goto(f"{base}/data?evidence=mens-d1&scope=mens-d1&date={day}&run={older}")
        expect(saved).to_have_attribute(
            "href", f"/data?evidence=mens-d1&scope=mens-d1&date={day}&run={older}"
        )
        current.click()
        expect(current).to_have_attribute("aria-current", "true")
        assert "run=" not in page.url
        assert coverage_reads == [None, latest, latest, older, None]
        assert not errors
        browser.close()


@contextmanager
def research_http_fixture(serve):
    """Use real loopback HTTP so browser-owned attachments cross the wire."""

    class Route:
        def __init__(self, handler):
            self.handler = handler
            self.request = SimpleNamespace(
                url="http://" + handler.headers["Host"] + handler.path,
                method=handler.command,
            )
            if handler.command == "POST":
                self.request.post_data_json = json.loads(
                    handler.rfile.read(int(handler.headers.get("Content-Length", 0)))
                )

        def fulfill(self, *, json=None, path=None, status=200, headers=None):
            import json as json_module

            if path is not None:
                body = Path(path).read_bytes()
                kind = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            else:
                body = json_module.dumps(json).encode()
                kind = "application/json"
            self.handler.send_response(status)
            for key, value in {
                "Content-Type": kind,
                "Content-Length": str(len(body)),
                **(headers or {}),
            }.items():
                self.handler.send_header(key, value)
            self.handler.end_headers()
            self.handler.wfile.write(body)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            serve(Route(self))

        do_DELETE = do_GET
        do_POST = do_GET

        def log_message(self, *_):
            pass

    class Server(ThreadingHTTPServer):
        # Chromium loads the workspace module graph in parallel on each navigation.
        request_queue_size = 64

    server = Server(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def record(status, *, mapped=True):
    return dict(
        id="sgo:" + status,
        revision="captured-" + status,
        kind="sgo",
        title="Orlando Magic at Milwaukee Bucks",
        sport="NBA",
        family="spread",
        period="game",
        provider="sportsgameodds",
        original_bookmaker_id="polymarket" if status == "unavailable" else "prophetx",
        represented_venue="polymarket_us" if status == "unavailable" else "prophetx",
        venue_equivalence="unestablished"
        if status == "unavailable"
        else "provider_identity_only",
        event_id="source-event",
        source_market_id="points-home-game-sp-home",
        outcome="home",
        line="-1.5",
        price="+120",
        price_units="american_odds",
        available=status != "unavailable",
        availability_reason="source_withdrawn" if status == "unavailable" else None,
        identity=dict(
            event_id="event" if mapped else None,
            contract_id="contract" if mapped else None,
            market=dict(period="full_game"),
            mapping_status="normalized" if mapped else "source_local",
            settlement="unverified",
        ),
        times=dict(source_at=None, received_at="2026-11-22T20:00:00Z"),
        calculation=dict(
            status=status,
            reason="fee_unknown" if status == "unavailable" else None,
            net_ev_percent={"positive": "5", "negative": "-5", "zero": "0"}.get(status),
            freshness="expired",
        ),
    )


@pytest.mark.parametrize(
    "width,scale",
    [(1440, 1), (390, 1), (960, 1.5)],
    ids=["desktop", "mobile", "zoom150-equivalent"],
)
def test_data_retains_exact_received_evidence_and_unknown_provenance(
    width, scale, tmp_path
):
    retained = {
        "canonical:fixture": [
            record(status) for status in ("positive", "negative", "zero", "unavailable")
        ],
        "source:sportsgameodds:unmatched": [record("unavailable", mapped=False)],
    }
    unmatched = retained["source:sportsgameodds:unmatched"][0]
    unmatched.update(
        id="sgo:unmatched", revision="captured-unmatched", event_id="unmatched"
    )
    games = {
        identity: dict(
            id=identity,
            title=rows[0]["title"],
            sport="NBA",
            start_at="2026-11-23T01:00:00Z",
            identity_status=rows[0]["identity"]["mapping_status"],
            latest_received_at=rows[0]["times"]["received_at"],
            records=len(rows),
            books=[row["original_bookmaker_id"] for row in rows],
            calculation_counts={row["calculation"]["status"]: 1 for row in rows},
            source_events=[
                dict(provider="sportsgameodds", event_id=rows[0]["event_id"])
            ],
        )
        for identity, rows in retained.items()
    }
    games["canonical:fixture"]["identity_status"] = "canonical"
    calculation = offer()
    requests, errors = [], []

    def serve(route):
        url = urlparse(route.request.url)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        requests.append((route.request.method, url.path))
        if url.path == "/data":
            route.fulfill(path=ASSETS / PAGES[url.path])
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/research/games":
            status = query.get("calculation_status")
            rows = [
                game
                for game in games.values()
                if not status or status in game["calculation_counts"]
            ]
            route.fulfill(
                json=dict(
                    token="frozen-data",
                    rows=rows,
                    total=len(rows),
                    offset=0,
                    next_offset=None,
                    captured_at="2026-11-22T20:00:00Z",
                )
            )
        elif url.path == "/api/research/game":
            assert query["token"] == "frozen-data"
            game = games[query["game_id"]]
            rows = retained[game["id"]]
            route.fulfill(
                json=dict(game=game, rows=rows, total=len(rows), next_offset=None)
            )
        elif url.path == "/api/research/input":
            assert query["token"] == "frozen-data"
            selected = deepcopy(
                next(
                    row
                    for row in retained[query["game_id"]]
                    if row["id"] == query["id"]
                )
            )
            assert query["revision"] == selected["revision"]
            selected.update(
                source_input=dict(
                    price_american="+120",
                    provider_bookmaker=selected["original_bookmaker_id"],
                ),
                original_response=dict(
                    state="not_recorded", reason="historical_original_bytes_absent"
                ),
                calculation_payload=calculation if selected["available"] else None,
                fee_input=dict(classification="frozen_fixture_fee")
                if selected["available"]
                else None,
                captured_at="2026-11-22T20:00:00Z",
                reproduction="Exact frozen source and result revisions",
            )
            route.fulfill(json=selected)
        elif url.path == "/api/research/read":
            assert route.request.method == "DELETE"
            route.fulfill(json=dict(released=True))
        elif url.path == "/api/workspace/collection":
            route.fulfill(json={})
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(
            viewport=dict(width=width, height=round(900 / scale)),
            device_scale_factor=scale,
            accept_downloads=True,
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        history = base + "/data?view=history"
        page.goto(history)
        expect(page.locator("#catalog-rows tr")).to_have_count(2)
        expect(page.locator("#catalog-rows")).to_contain_text("Source-local game")
        page.get_by_label("Calculation", exact=True).select_option("negative")
        page.get_by_role("button", name="Apply filters", exact=True).click()
        expect(page.locator("#catalog-status")).to_contain_text(
            "1 game · negative EV filter"
        )
        page.get_by_role("link", name="Open game", exact=True).click()
        expect(page.locator("#game-content tr[data-record]")).to_have_count(4)
        expect(page.locator("#game-content")).to_contain_text("Source: Not recorded")

        page.locator('[data-record="sgo:negative"] button').click()
        dialog = page.get_by_role("dialog")
        page.get_by_text(
            "Source identities, revisions, exact arithmetic and reproduction evidence"
        ).click()
        for heading in (
            "1. Received source input",
            "2. Identity & settlement",
            "3. Probability inputs & policy",
            "4. Fees, quantity & cashflows",
            "5. Calculation result",
            "6. Original-response retention & reproduction",
        ):
            expect(dialog.get_by_role("heading", name=heading)).to_be_visible()
        with page.expect_download() as download:
            dialog.get_by_role("link", name="Export this exact input & result").click()
        exported = json.loads(Path(download.value.path()).read_text())
        assert exported["revision"] == "captured-negative"
        assert exported["source_input"]["price_american"] == "+120"
        assert (
            exported["calculation_payload"]["fee"]["cashflows"]
            == calculation["fee"]["cashflows"]
        )
        assert exported["fee_input"]["classification"] == "frozen_fixture_fee"

        page.goto(history)
        page.locator('[data-game="source:sportsgameodds:unmatched"]').get_by_role(
            "link", name="Open game", exact=True
        ).click()
        page.locator('[data-record="sgo:unmatched"] button').click()
        page.get_by_text(
            "Source identities, revisions, exact arithmetic and reproduction evidence"
        ).click()
        expect(dialog).to_contain_text("fee_unknown")
        expect(dialog).to_contain_text("historical_original_bytes_absent")
        expect(dialog.locator('dt:has-text("Canonical event") + dd')).to_have_text(
            "Not recorded"
        )
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(
            path=str(tmp_path / f"data-evidence-{width}.png"), full_page=True
        )
        assert not errors
        assert all(method in ("GET", "DELETE") for method, _ in requests)
        assert not any(path.startswith("/api/pregame/research") for _, path in requests)
        browser.close()
