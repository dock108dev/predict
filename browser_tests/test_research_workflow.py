"""Data keeps each odds pull and its original response separately inspectable."""

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

from app.dashboard.workspace_routes import PAGES
from browser_tests.test_pregame_current import ASSETS
from browser_tests.test_research_workspace import research_http_fixture


def test_data_keeps_failed_pull_separate_from_previous_captured_evidence(tmp_path):
    day = "2026-11-23"
    received = day + "T19:00:01Z"
    game = dict(title="Away at Home", league="NCAAB", source_event_id="event")
    latest = dict(
        pull_id="newest",
        requested_at=day + "T20:00:00Z",
        state="failed",
        details=dict(event=game, reason="retention_limit"),
    )
    older = dict(
        pull_id="previous",
        requested_at=day + "T19:00:00Z",
        state="complete",
        details=dict(event=game),
        sha256="a" * 64,
    )
    exact = dict(id="b" * 64, received_at=received, provider="sportsgameodds")
    receipt = dict(attempt_id="older-request", received_at=received, original=exact)
    common = dict(
        game=game["title"],
        received_at=received,
        family="moneyline",
        price_units="american_odds",
        starts_at=day + "T21:00:00Z",
    )
    retained = [
        dict(
            common,
            selection="Away",
            original_bookmaker_id="kalshi",
            price="+120",
            available=True,
            calculation=dict(status="negative", net_ev_percent="-5"),
        ),
        dict(
            common,
            selection="Home",
            original_bookmaker_id="novig",
            available=False,
            reason="source_observation_unavailable",
        ),
    ]
    original = tmp_path / "authored-original.json"
    source_bytes = b'{ "data": [] }\n'
    original.write_bytes(source_bytes)
    reads, errors = [], []

    def serve(route):
        url = urlsplit(route.request.url)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path == "/data":
            route.fulfill(path=ASSETS / PAGES[url.path])
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/api/research/data/pulls":
            assert query["date"] == day
            route.fulfill(
                json=dict(
                    offset=0,
                    rows=[
                        dict(pull, event=game, reason=pull["details"].get("reason"))
                        for pull in (latest, older)
                    ],
                )
            )
        elif url.path == "/api/research/data/pull":
            identity = query["pull"]
            reads.append(identity)
            assert query["date"] == day
            pull, rows, receipts = (
                (older, retained, [receipt])
                if identity == older["pull_id"]
                else (latest, [], [])
            )
            route.fulfill(
                json=dict(
                    pull=pull,
                    rows=rows,
                    total_records=len(rows),
                    offset=0,
                    receipts=receipts,
                    receipt_offset=0,
                )
            )
        elif url.path == "/api/research/data/original":
            assert query == dict(id=exact["id"], download="1")
            route.fulfill(
                path=original,
                headers={"Content-Disposition": 'attachment; filename="original.json"'},
            )
        elif url.path == "/api/workspace/collection":
            route.fulfill(json={})
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(
            viewport=dict(width=390, height=820), accept_downloads=True
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{base}/data?evidence=pulls&date={day}")
        expect(page.locator("[data-workspace-nav] a")).to_have_text(
            ["Dashboard", "Data", "Experiments"]
        )
        page.get_by_role("row").filter(has_text="failed").get_by_role(
            "link", name="Open odds pull"
        ).click()
        expect(page.locator("#pull-status")).to_have_text("Recorded pull is failed.")
        expect(
            page.get_by_text(
                "No accepted physical response is recorded for this attempt."
            )
        ).to_be_visible()
        expect(page.get_by_text("retention limit", exact=True)).to_be_visible()
        expect(
            page.get_by_role("link", name="Download original response")
        ).to_have_count(0)

        page.get_by_role("link", name="Back to odds pulls").click()
        page.get_by_role("row").filter(has_text="complete").get_by_role(
            "link", name="Open odds pull"
        ).click()
        expect(page.locator("#pull-status")).to_have_text(
            "Recorded odds pull available."
        )
        expect(page.get_by_text("-5.00%", exact=True)).to_be_visible()
        expect(
            page.get_by_text("source observation unavailable", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("Exact response retained")).to_be_visible()
        with page.expect_download() as captured:
            page.get_by_role("link", name="Download original response").click()
        assert captured.value.path().read_bytes() == source_bytes
        page.reload()
        expect(page.get_by_text("-5.00%", exact=True)).to_be_visible()
        assert reads == ["newest", "previous", "previous"]
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        browser.close()
