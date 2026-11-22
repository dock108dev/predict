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

from browser_tests.test_pregame_current import ASSETS, offer


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

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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


@pytest.mark.parametrize("width", [1440, 390])
def test_received_data_inspection_export_and_missing_cases(width, tmp_path):
    records = [
        record(value) for value in ("positive", "negative", "zero", "unavailable")
    ]
    unmatched = record("unavailable", mapped=False)
    unmatched.update(id="sgo:unmatched", revision="captured-unmatched")
    records.append(unmatched)
    errors, requests = [], []
    frozen_calculation = offer()
    retention = dict(
        retained_bytes=17000,
        total_allocation_bytes=19048,
        byte_cap=33554432,
        observation_bytes=16000,
        observation_byte_cap=25165824,
        retention_dispositions=dict(
            slots=4,
            observation_refusals=3,
            capture_refusals=1,
            observation_affected_slots=2,
            capture_affected_slots=1,
            observation_open_gaps=2,
            capture_open_gaps=0,
        ),
        retention_accounting=dict(
            coverage_started_at="2026-11-22T21:00:00Z",
            prior_first_observed_refusal_at="2026-11-22T20:45:00Z",
            prior_uncounted_window_end="2026-11-22T21:00:00Z",
            prior_refused_attempts=None,
            prior_affected_cases=None,
        ),
    )
    frozen_evidence = dict(
        cohort_id="frozen-cohort",
        records=[
            dict(
                id="immutable-capture",
                kind="capture",
                recorded_at="2026-11-22T20:00:01Z",
                payload=dict(
                    snapshot=dict(
                        inputs=dict(
                            calculation=frozen_calculation,
                            source_record=dict(
                                quote=dict(original=frozen_calculation["posted"])
                            ),
                            fee_input=dict(classification="frozen_fixture_fee"),
                        )
                    )
                ),
            )
        ],
        manifest=dict(record_count=1),
        research_retention=retention,
        provider_requests=0,
    )

    def serve(route):
        url = urlparse(route.request.url)
        q = {key: value[0] for key, value in parse_qs(url.query).items()}
        requests.append((route.request.method, url.path))
        if url.path == "/api/research/catalog":
            selected = [
                row
                for row in records
                if not q.get("calculation_status")
                or row["calculation"]["status"] == q["calculation_status"]
            ]
            route.fulfill(
                json=dict(
                    token="snapshot",
                    rows=selected,
                    total=len(selected),
                    counts=dict(source_events=1),
                    offset=0,
                    next_offset=None,
                    captured_at="2026-11-22T20:00:00Z",
                    population="All received values independent of EV",
                    provider_requests=0,
                )
            )
        elif url.path == "/api/research/input":
            row = deepcopy(next(row for row in records if row["id"] == q["id"]))
            assert q["revision"] == row["revision"] and q["token"] == "snapshot"
            row.update(
                source_input=dict(
                    price_american="+120",
                    provider_bookmaker=row["original_bookmaker_id"],
                ),
                fee_input=None,
                contract=None,
                calculation_payload=offer()
                if row["calculation"]["status"] != "unavailable"
                else None,
                original_response=dict(
                    state="not_recorded", reason="historical_original_bytes_absent"
                ),
                captured_at="2026-11-22T20:00:00Z",
                reproduction="Exact frozen source and result revisions",
            )
            route.fulfill(json=row)
        elif url.path == "/api/research/coverage":
            route.fulfill(
                json=dict(
                    coverage=dict(
                        observed_at="2026-11-22T20:00:00Z",
                        runtime=dict(healthy=True),
                        sources=[
                            dict(
                                provider="novig",
                                acquisition_state="last_receipt_observed",
                                last_received_at="2026-11-22T19:45:00Z",
                                archive_supported=False,
                            )
                        ],
                    ),
                    original_responses=dict(
                        state="bounded_capture",
                        captured_receipts=1,
                        compressed_bytes=100,
                    ),
                )
            )
        elif url.path == "/api/research/cohorts":
            if q.get("export") == "1":
                assert q["id"] == "frozen-cohort"
                route.fulfill(
                    json=frozen_evidence,
                    headers={
                        "Content-Disposition": 'attachment; filename="predict-research-cohort.json"'
                    },
                )
            else:
                route.fulfill(
                    json=dict(
                        cohorts=[
                            dict(id="frozen-cohort", name="Declared fixture population")
                        ],
                        research_retention=retention,
                    )
                )
        elif url.path == "/api/research/read":
            assert route.request.method == "DELETE"
            route.fulfill(json=dict(released=True))
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/research":
            route.fulfill(path=ASSETS / "research.html")
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        context = browser.new_context(
            viewport=dict(width=width, height=900), accept_downloads=True
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/research")
        expect(page.locator("#catalog-rows tr")).to_have_count(5)
        for status in ("positive", "negative", "zero", "unavailable"):
            expect(page.locator("#catalog-rows")).to_contain_text(status)
        expect(page.locator("#catalog-rows")).to_contain_text("unestablished")
        expect(page.locator("#catalog-rows")).to_contain_text("source_local")
        expect(page.locator("#catalog-rows")).to_contain_text("Source: Unknown")
        page.get_by_label("Calculation", exact=True).select_option("negative")
        page.get_by_role("button", name="Apply filters", exact=True).click()
        expect(page.locator("#catalog-rows tr")).to_have_count(1)
        page.get_by_role("button", name="Inspect Orlando", exact=False).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("1. Received source input")
        expect(dialog).to_contain_text("2. Identity & settlement")
        expect(dialog).to_contain_text("3. Probability inputs & policy")
        expect(dialog).to_contain_text("4. Fees, quantity & cashflows")
        expect(dialog).to_contain_text("5. Calculation result")
        expect(dialog).to_contain_text("6. Original-response retention & reproduction")
        with page.expect_download() as exported:
            dialog.get_by_role("link", name="Export this exact input & result").click()
        downloaded = json.loads(Path(exported.value.path()).read_text())
        assert downloaded["revision"] == "captured-negative"
        assert downloaded["source_input"]["price_american"] == "+120"
        dialog.get_by_role("button", name="Close", exact=True).click()
        page.get_by_role("button", name="Clear", exact=True).click()
        expect(page.locator("#catalog-rows tr")).to_have_count(5)
        page.locator('[data-record="sgo:unmatched"] button').click()
        expect(dialog).to_contain_text("fee_unknown")
        expect(dialog).to_contain_text("historical_original_bytes_absent")
        expect(dialog.locator('dt:has-text("Canonical event") + dd')).to_have_text(
            "Unknown"
        )
        dialog.get_by_role("button", name="Close", exact=True).click()
        page.get_by_text("Collection, archive & retention", exact=True).click()
        expect(page.locator("#coverage-content")).to_contain_text(
            "Unsupported archive route"
        )
        page.get_by_text(
            "Declared research populations & evaluation", exact=True
        ).click()
        expect(page.locator("#cohort-content")).to_contain_text(
            "Declared fixture population"
        )
        expect(
            page.locator(
                '#research-retention-status dt:has-text("Earlier refusal attempts") + dd'
            )
        ).to_have_text("Unknown")
        expect(
            page.locator(
                '#research-retention-status dt:has-text("Observation refusal attempts") + dd'
            )
        ).to_have_text("3")
        with page.expect_download() as cohort_exported:
            page.get_by_role("link", name="Export frozen evidence", exact=True).click()
        frozen = json.loads(Path(cohort_exported.value.path()).read_text())
        assert frozen["cohort_id"] == "frozen-cohort"
        assert (
            frozen["research_retention"]["retention_accounting"][
                "prior_refused_attempts"
            ]
            is None
        )
        assert (
            frozen["research_retention"]["retention_dispositions"][
                "observation_refusals"
            ]
            == 3
        )
        snapshot = frozen["records"][0]["payload"]["snapshot"]["inputs"]
        assert (
            snapshot["source_record"]["quote"]["original"]
            == frozen_calculation["posted"]
        )
        assert (
            snapshot["calculation"]["fee"]["cashflows"]
            == frozen_calculation["fee"]["cashflows"]
        )
        assert snapshot["fee_input"]["classification"] == "frozen_fixture_fee"
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(tmp_path / f"research-{width}.png"), full_page=True)
        assert not errors
        assert all(method in ("GET", "DELETE") for method, _ in requests)
        assert not any(path.startswith("/api/pregame/research") for _, path in requests)
        browser.close()
