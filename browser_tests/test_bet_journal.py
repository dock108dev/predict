"""The personal journal flow, including actual odds edits and mobile layout."""

from copy import deepcopy
from datetime import datetime, timedelta
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from browser_tests.test_pregame_current import offer

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


@pytest.mark.parametrize("width", [1440, 768, 390, 320])
def test_save_ev_edit_actual_odds_record_result_and_keep_original(width, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    quote = offer()
    entry = dict(
        id="saved-ev",
        kind="ev",
        snapshot=deepcopy(quote),
        revision=1,
        decision="saved",
        notes="",
        trade=None,
        created_at=quote["times"]["received_at"],
        updated_at=quote["times"]["received_at"],
        metrics=dict(
            basis="observed_model",
            observed_ev="0.088",
            entry_ev="0.088",
            close_ev=None,
            realized_profit_usd=None,
            close_state="tracking",
            legs=[],
        ),
    )
    updates, errors, reads = [], [], []
    state = dict(saved=False, conflict=False)

    def serve(route):
        request = route.request
        url = urlparse(request.url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/bet-journal" and request.method == "POST":
            body = request.post_data_json
            assert body["kind"] == "ev"
            assert body["snapshot"]["display"]["posted_odds"] == "+120"
            state["saved"] = True
            route.fulfill(status=201, json=dict(entry=deepcopy(entry)))
        elif url.path == "/api/bet-journal/saved-ev":
            if request.method == "POST":
                changes = request.post_data_json
                updates.append(changes)
                if state["conflict"]:
                    route.fulfill(status=409, json=dict(error="revision_conflict"))
                    return
                entry.update(changes)
                entry["revision"] += 1
                entry["metrics"]["basis"] = "reported_trade"
                entry["metrics"]["entry_ev"] = ".05"
                if (entry["trade"] or {}).get("result"):
                    entry["metrics"]["realized_profit_usd"] = "110"
                    entry["metrics"]["realized_roi"] = "1.1"
                route.fulfill(json=dict(entry=deepcopy(entry)))
            else:
                route.fulfill(
                    json=dict(
                        entry=deepcopy(entry),
                        history=[dict(revision=1, decision="saved")],
                    )
                )
        elif url.path == "/api/bet-journal":
            reads.append(q)
            selected = (
                [deepcopy(entry)]
                if state["saved"] and (not q.get("kind") or q["kind"] == entry["kind"])
                else []
            )
            route.fulfill(
                json=dict(
                    entries=selected,
                    total=len(selected),
                    offset=0,
                    limit=100,
                    summary=dict(
                        counts={entry["decision"]: int(state["saved"])},
                        settled=int(bool((entry["trade"] or {}).get("result"))),
                        realized_profit_usd="110",
                    ),
                    monitor=dict(
                        monitor_state="running",
                        monitor_checked_at=quote["times"]["received_at"],
                    ),
                )
            )
        elif url.path.startswith("/api/pregame"):
            route.fulfill(
                json=dict(
                    rows=[deepcopy(quote)],
                    total=1,
                    cursor="one",
                    sportsbooks=[],
                    refresh_at=quote["kickoff"],
                    changed=False,
                )
            )
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        elif url.path == "/my-bets":
            route.fulfill(path=ASSETS / "bet-journal.html")
        else:
            route.fulfill(path=ASSETS / "pregame.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=900))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/")
        page.get_by_role("button", name="Compare prices for").click()
        page.get_by_role("button", name="Save ProphetX to My Bets").click()
        page.get_by_role("link", name="Enter actual odds & stake").click()
        expect(page.locator("#editor")).to_be_visible()
        expect(page.locator("#editor")).to_contain_text("Original quotes stay fixed")
        page.locator('[name="decision"]').last.select_option("placed")
        page.locator('[name="stake-0"]').fill("100")
        page.locator('[name="price-0"]').fill("+110")
        for name in ["entry_fee", "win_fee", "loss_fee"]:
            page.locator(f'[name="{name}-0"]').fill("0")
        page.locator('[name="notes"]').fill("Actual odds moved before placement")
        page.get_by_role("button", name="Save changes", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        expect(page.locator(".journal-entry")).to_contain_text("Actual entry EV")
        assert updates[0]["trade"]["legs"][0]["price"] == "+110"
        assert entry["snapshot"]["posted"]["value"] == "+120"
        page.get_by_role("button", name="Edit trade").click()
        page.locator('[name="receipt-0"]').fill("210")
        now = datetime.now().replace(microsecond=0).isoformat()
        page.locator('[name="settled_at"]').fill(now)
        page.locator('[name="result_notes"]').fill("Won, net cash returned")
        page.get_by_role("button", name="Save changes", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        expect(page.locator(".journal-entry")).to_contain_text("$110.00")
        page.screenshot(path=str(tmp_path / f"journal-placed-{width}.png"))
        page.get_by_role("button", name="Edit trade").click()
        state["conflict"] = True
        page.locator('[name="notes"]').fill("An unsaved correction")
        page.get_by_role("button", name="Save changes", exact=True).click()
        expect(page.locator("#edit-status")).to_contain_text("another session")
        expect(page.locator('[name="notes"]')).to_have_value("An unsaved correction")
        page.get_by_role("button", name="Close bet editor").click()
        page.get_by_role("button", name="Opportunity log", exact=True).click()
        expect(page.locator("#log-tab")).to_have_attribute("aria-pressed", "true")
        assert reads[-1]["view"] == "log"
        page.get_by_label("Opportunity type").select_option("arb")
        expect(page.locator(".journal-entry")).to_have_count(0)
        assert reads[-1]["kind"] == "arb"
        assert page.evaluate("document.documentElement.scrollWidth===innerWidth")
        assert not errors
        page.screenshot(path=str(tmp_path / f"journal-{width}.png"))
        browser.close()


def test_arb_has_independent_actual_prices_and_explains_close_basis():
    from playwright.sync_api import expect, sync_playwright

    a = offer()
    b = deepcopy(a)
    b.update(id="other-leg", venue="kalshi", selection_label="Milwaukee Bucks")
    entry = dict(
        id="arb-1",
        kind="arb",
        snapshot=dict(
            game=a["game"],
            league="NBA",
            kickoff=a["kickoff"],
            return_rate=".05",
            legs=[a, b],
        ),
        revision=1,
        decision="saved",
        created_at=a["times"]["received_at"],
        metrics=dict(
            basis="observed_model",
            close_state="closed",
            observed_arb_return=".05",
            close_arb_return="-.02",
            close_min_profit_usd="-4",
            close_cost_usd="200",
            legs=[],
        ),
    )
    errors = []

    def serve(route):
        url = urlparse(route.request.url)
        if url.path == "/api/bet-journal/arb-1":
            route.fulfill(json=dict(entry=entry, history=[]))
        elif url.path == "/api/bet-journal":
            route.fulfill(json=dict(entries=[entry], total=1, summary={}, monitor={}))
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(path=ASSETS / "bet-journal.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=390, height=900))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/my-bets")
        expect(page.locator(".journal-entry")).to_contain_text("-2.00%")
        expect(page.locator(".journal-entry")).to_contain_text("$200.00 basis")
        expect(page.locator(".journal-entry")).to_contain_text("Entry EV Unavailable")
        page.get_by_role("button", name="Edit trade").click()
        expect(page.locator('[name="price-0"]')).to_have_value("+120")
        expect(page.locator('[name="units-1"]')).to_have_value("probability")
        expect(page.locator('[name="stake-0"]')).to_have_value("")
        expect(page.locator('[name="stake-1"]')).to_have_value("")
        assert not errors
        browser.close()


def test_quote_history_is_lazy_paged_and_keeps_negative_ev():
    from playwright.sync_api import expect, sync_playwright

    quote = offer()
    entry = dict(
        id="history-ev",
        kind="ev",
        snapshot=deepcopy(quote),
        revision=1,
        decision="saved",
        notes="",
        trade=None,
        created_at=quote["times"]["received_at"],
        metrics=dict(
            basis="observed_model",
            observed_ev=".088",
            entry_ev=".088",
            close_state="tracking",
            legs=[],
        ),
    )
    at = datetime.fromisoformat(quote["times"]["received_at"])
    trail = []
    for i in range(105):
        row = deepcopy(quote)
        clock = (at + timedelta(seconds=i)).isoformat()
        row.update(observed_at=clock, times=dict(source_at=clock, received_at=clock))
        if i == 0:
            row["raw"]["net_ev"] = "-.02"
            row["posted"]["value"] = "+150"
        trail.append(row)
    reads = []

    def serve(route):
        url = urlparse(route.request.url)
        reads.append(url.path)
        if url.path == "/api/bet-journal/history-ev":
            route.fulfill(json=dict(entry=entry, history=[], quotes=trail))
        elif url.path == "/api/bet-journal":
            route.fulfill(json=dict(entries=[entry], total=1, summary={}, monitor={}))
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(path=ASSETS / "bet-journal.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=390, height=900))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/my-bets")
        expect(page.locator(".journal-entry")).to_be_visible()
        assert "/api/bet-journal/history-ev" not in reads
        page.locator(".journal-details > summary").click()
        page.get_by_text("Quote history", exact=True).click()
        expect(page.locator(".journal-history-list li")).to_have_count(100)
        expect(page.locator(".journal-history")).to_contain_text("6–105 of 105")
        page.get_by_role("button", name="← Older", exact=True).click()
        expect(page.locator(".journal-history-list li")).to_have_count(5)
        expect(page.locator(".journal-history-list")).to_contain_text("Net EV -2.00%")
        expect(page.locator(".journal-history-list")).to_contain_text("+150")
        expect(page.locator(".journal-history-list")).to_contain_text(
            "Fair reference: FanDuel"
        )
        expect(page.locator(".journal-history-list")).to_contain_text("Recorded")
        expect(page.locator(".journal-history-list")).to_contain_text("Source")
        expect(page.locator(".journal-history-list")).to_contain_text("Received")
        page.get_by_role("button", name="Newer →", exact=True).click()
        expect(page.locator(".journal-history-list li")).to_have_count(100)
        assert reads.count("/api/bet-journal/history-ev") == 1
        page.get_by_role("button", name="Edit trade").click()
        expect(page.locator("#audit-data")).to_contain_text('"quote_observations"')
        browser.close()


def test_empty_journal_keeps_performance_coverage_explicit():
    from playwright.sync_api import expect, sync_playwright

    summary = dict(
        counts={},
        settled=0,
        realized_profit_usd=None,
        expected_profit_usd=None,
        expected_count=0,
        average_price_clv=None,
        clv_leg_count=0,
        closes_due=0,
        closes_captured=0,
        realized_minus_expected_usd=None,
        matched_settled_count=0,
        realized_roi=None,
    )

    def serve(route):
        url = urlparse(route.request.url)
        if url.path == "/api/bet-journal":
            route.fulfill(json=dict(entries=[], total=0, summary=summary, monitor={}))
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(path=ASSETS / "bet-journal.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=390, height=900))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/my-bets")
        expect(page.locator("#performance")).to_contain_text(
            "Entry expected profitUnavailable0 trades"
        )
        expect(page.locator("#performance")).to_contain_text(
            "Settled ROIUnavailable0 settled"
        )
        expect(page.locator("#performance")).to_contain_text(
            "Mean price CLVUnavailable0 legs · before fees"
        )
        expect(page.locator("#performance")).to_contain_text(
            "Closes captured0 / 0No closes due yet"
        )
        expect(page.locator("#performance")).to_contain_text(
            "Result − expectedUnavailable0 matched settled"
        )
        expect(page.locator("#results")).to_contain_text(
            "Your next bet starts with a saved quote"
        )
        assert page.evaluate("document.documentElement.scrollWidth===innerWidth")
        browser.close()
