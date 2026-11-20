"""The personal journal flow, including actual odds edits and mobile layout."""

from copy import deepcopy
from datetime import datetime, timedelta
from fractions import Fraction
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from browser_tests.test_pregame_current import offer

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


class JournalUI:
    """Normal browser requests backed by a disposable, real personal journal."""

    def __init__(self, path, quote):
        from app.dashboard.bet_journal import Journal

        self.journal = Journal(path)
        self.quote = quote
        self.updates, self.reads, self.previews = [], [], []
        self.conflict = self.fail_save = False

    def serve(self, route):
        from app.dashboard.bet_journal import Conflict

        request, url = route.request, urlparse(route.request.url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/bet-journal":
            if request.method == "POST":
                body = request.post_data_json
                key = self.journal.observe(body["kind"], body["snapshot"], manual=True)
                route.fulfill(status=201, json=self.journal.get(key))
            else:
                self.reads.append(q)
                route.fulfill(json=self.journal.list(**q))
        elif url.path.endswith("/preview") and url.path.startswith("/api/bet-journal/"):
            key = url.path.split("/")[-2]
            self.previews.append(deepcopy(request.post_data_json))
            try:
                result = self.journal.preview(key, request.post_data_json)
            except ValueError as error:
                route.fulfill(status=400, json=dict(message=str(error)))
            else:
                route.fulfill(json=result)
        elif url.path.startswith("/api/bet-journal/"):
            key = url.path.rsplit("/", 1)[-1]
            if request.method == "POST":
                changes = request.post_data_json
                self.updates.append(deepcopy(changes))
                if self.conflict:
                    route.fulfill(status=409, json=dict(error="revision_conflict"))
                elif self.fail_save:
                    route.fulfill(
                        status=503,
                        json=dict(error="Stored changes unavailable; retry."),
                    )
                else:
                    try:
                        result = self.journal.update(key, changes)
                    except Conflict:
                        route.fulfill(status=409, json=dict(error="revision_conflict"))
                    except ValueError as error:
                        route.fulfill(status=400, json=dict(message=str(error)))
                    else:
                        route.fulfill(json=result)
            else:
                route.fulfill(json=self.journal.get(key, history=True))
        elif url.path.startswith("/api/pregame"):
            route.fulfill(
                json=dict(
                    rows=[deepcopy(self.quote)],
                    total=1,
                    cursor="one",
                    sportsbooks=[],
                    refresh_at=self.quote["kickoff"],
                    changed=False,
                )
            )
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(
                path=ASSETS
                / ("bet-journal.html" if url.path == "/my-bets" else "pregame.html")
            )


def prophetx_quote():
    from tests.test_fee_pricing import rule

    quote = offer()
    quote["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
    quote["fee"]["evidence"] = dict(database_fee_rule=rule("prophetx"))
    return quote


def edit_bet(page):
    return page.get_by_role("button", name=re.compile(r"^(Set result|Edit bet)$"))


def choose_outcome(page, index, value):
    choice = page.locator(
        f'.journal-outcomes label:has(input[name="outcome-{index}"][value="{value}"])'
    )
    choice.click()
    from playwright.sync_api import expect

    expect(choice.locator("input")).to_be_checked()


def assert_editor_controls_fixed(page):
    from playwright.sync_api import expect

    save, close = page.locator("#save"), page.locator("#editor-close")
    expect(save).to_be_visible()
    expect(close).to_be_visible()
    before = [control.bounding_box()["y"] for control in (save, close)]
    body = page.locator(".journal-editor-body")
    assert body.evaluate("e=>e.scrollHeight>e.clientHeight")
    body.evaluate("e=>e.scrollTop=e.scrollHeight")
    assert body.evaluate("e=>e.scrollTop") > 0
    for control, y in zip((save, close), before):
        box = control.bounding_box()
        assert abs(box["y"] - y) < 1
        assert (
            box["y"] >= 0 and box["y"] + box["height"] <= page.viewport_size["height"]
        )


@pytest.mark.parametrize("width", [1440, 768, 390, 320])
def test_save_ev_edit_actual_odds_record_result_and_keep_original(width, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    quote = prophetx_quote()
    fixture = JournalUI(tmp_path / "personal.sqlite3", quote)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=900))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", fixture.serve)
        page.goto("https://predict.fixture/")
        page.get_by_role("button", name="Compare prices for").click()
        page.get_by_role("button", name="Save ProphetX to My Bets").click()
        page.get_by_role("link", name="Enter actual odds & stake").click()
        expect(page.locator("#editor")).to_be_visible()
        expect(page.locator('[name="stake-0"]')).to_have_value("100")
        expect(page.locator('[name="price-0"]')).to_be_visible()
        assert Fraction(page.locator('[name="price-0"]').input_value()) == 120
        expect(page.locator('[name="entry_fee-0"]')).to_have_count(0)
        page.locator('[name="price-0"]').fill("+110")
        page.get_by_text("More options", exact=True).click()
        page.locator('[name="notes"]').fill("Actual odds moved before placement")
        page.get_by_role("button", name="Save changes", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        page.locator(".journal-details > summary").click()
        expect(page.locator(".journal-details")).to_contain_text("+3.90%")
        expect(page.locator(".journal-details")).to_contain_text(
            "Entry EV changed -4.90 percentage points from the original observation."
        )
        assert fixture.updates[0]["trade"]["legs"][0]["price"] == "+110"
        key = fixture.journal.list(view="bets")["entries"][0]["id"]
        assert fixture.journal.get(key)["entry"]["snapshot"] == quote
        edit_bet(page).click()
        choose_outcome(page, 0, "win")
        page.get_by_role("button", name="Save changes", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        expect(page.locator(".journal-entry")).to_contain_text("$107.80")
        result = fixture.journal.get(key)["entry"]
        assert result["trade"]["result"]["outcomes"] == ["win"]
        assert "receipts_usd" not in fixture.updates[-1]["trade"]["result"]
        assert result["metrics"]["settlement"]["receipts_usd"] == ["207.8"]
        assert result["metrics"]["realized_profit_usd"] == "107.8"
        page.screenshot(path=str(tmp_path / f"journal-placed-{width}.png"))
        edit_bet(page).click()
        fixture.conflict = True
        page.get_by_text("More options", exact=True).click()
        page.locator('[name="notes"]').fill("An unsaved correction")
        page.get_by_role("button", name="Save changes", exact=True).click()
        expect(page.locator("#edit-status")).to_contain_text("another session")
        expect(page.locator('[name="notes"]')).to_have_value("An unsaved correction")
        assert (
            fixture.journal.get(key)["entry"]["notes"]
            == "Actual odds moved before placement"
        )
        page.get_by_role("button", name="Close bet editor").click()
        page.get_by_role("button", name="Opportunity log", exact=True).click()
        expect(page.locator("#log-tab")).to_have_attribute("aria-pressed", "true")
        assert fixture.reads[-1]["view"] == "log"
        page.get_by_label("Opportunity type").select_option("arb")
        expect(page.locator(".journal-entry")).to_have_count(0)
        assert fixture.reads[-1]["kind"] == "arb"
        assert page.evaluate("document.documentElement.scrollWidth===innerWidth")
        assert not errors, errors
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
            arb_return_slippage=".0123",
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
        page.locator(".journal-details > summary").click()
        expect(page.locator(".journal-entry")).to_contain_text("-2.00%")
        expect(page.locator(".journal-entry")).to_contain_text("$200.00 basis")
        entry_ev = page.locator(".journal-details .journal-figure").filter(
            has=page.locator("span", has_text=re.compile(r"^Entry EV$"))
        )
        expect(entry_ev.locator("strong")).to_have_text("Unavailable")
        expect(page.locator(".journal-details")).to_contain_text(
            "Paired return changed +1.23 percentage points from the original observation."
        )
        edit_bet(page).click()
        assert Fraction(page.locator('[name="price-0"]').input_value()) == 120
        expect(page.locator('[name="units-1"]')).to_have_value("probability")
        expect(page.locator('[name="stake-0"]')).to_have_value("100")
        expect(page.locator('[name="stake-1"]')).to_have_value("100")
        expect(page.locator("#editor")).to_contain_text("$200 total stake")
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
            ev_slippage="0",
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
        expect(page.locator(".journal-details")).to_contain_text(
            "Entry EV changed 0.00 percentage points from the original observation."
        )
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
        edit_bet(page).click()
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
        expect(page.locator(".journal-performance-details")).not_to_have_attribute(
            "open", ""
        )
        page.locator(".journal-performance-details > summary").click()
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


@pytest.mark.parametrize("width", [390, 1440])
def test_editor_defaults_and_delete_recovery(width, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    def quoted(odds):
        row = offer()
        row["posted"]["value"] = str(odds)
        row["display"]["posted_odds"] = str(odds)
        row["fee"]["entry_usd"] = "0"
        row["fee"]["cashflows"]["win"] = dict(
            total_fee_usd="0",
            net_receipt_usd=str(100 * (1 + (odds / 100 if odds > 0 else 100 / -odds))),
        )
        return row

    negative, positive = quoted(-150), quoted(300)
    contract = quoted(-300)
    contract.update(venue="kalshi", posted=dict(value="75", units="cents"))
    pair = [quoted(100), quoted(300)]
    pair[1]["id"] = "second-leg"
    cases = [
        ("ev", negative, None, ["150"]),
        ("ev", positive, None, ["100"]),
        ("ev", contract, None, ["300"]),
        (
            "arb",
            dict(game=negative["game"], kickoff=negative["kickoff"], legs=pair),
            None,
            ["133.33", "66.67"],
        ),
        (
            "ev",
            negative,
            dict(
                legs=[
                    dict(
                        quote_id=negative["id"],
                        stake="37",
                        price="-160",
                        units="american_odds",
                        entry_fee="0",
                        win_fee="0",
                        loss_fee="0",
                    )
                ]
            ),
            ["37"],
        ),
    ]
    state = dict(deleted=False, failure=True, entry=None)
    deletes, errors = [], []

    def serve(route):
        request, url = route.request, urlparse(route.request.url)
        if url.path == "/api/bet-journal/entry":
            if request.method == "DELETE":
                deletes.append(request.post_data_json)
                if state["failure"]:
                    route.fulfill(
                        status=503, json=dict(error="Could not delete; retry.")
                    )
                else:
                    state["deleted"] = True
                    route.fulfill(json=dict(deleted=True))
            else:
                route.fulfill(json=dict(entry=state["entry"], history=[]))
        elif url.path == "/api/bet-journal":
            entries = [] if state["deleted"] else [state["entry"]]
            route.fulfill(
                json=dict(entries=entries, total=len(entries), summary={}, monitor={})
            )
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(path=ASSETS / "bet-journal.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=900))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", serve)
        for kind, snapshot, trade, expected in cases:
            state["entry"] = dict(
                id="entry",
                kind=kind,
                snapshot=snapshot,
                decision="saved",
                revision=3,
                notes="",
                trade=trade,
                metrics={},
            )
            page.goto("https://predict.fixture/my-bets?entry=entry")
            expect(page.locator("#editor")).to_be_visible()
            for i, stake in enumerate(expected):
                expect(page.locator(f'[name="stake-{i}"]')).to_have_value(stake)
            expect(page.locator('[name="entry_fee-0"]')).to_have_count(0)
            expect(page.locator('[name="receipt-0"]')).not_to_be_visible()
            page.get_by_text("More options", exact=True).click()
            page.get_by_text(
                "Original snapshot & correction history", exact=True
            ).click()
            assert_editor_controls_fixed(page)
            cancel = page.get_by_role("button", name="Cancel", exact=True)
            expect(cancel).to_have_css("color", "rgb(32, 37, 44)")
            assert page.locator("#editor").evaluate(
                "e => e.scrollWidth <= e.clientWidth"
            )
            page.screenshot(
                path=str(tmp_path / f"editor-{kind}-{expected[0]}-{width}.png")
            )
            cancel.click()
            expect(page.locator("#editor")).not_to_be_visible()
            assert not deletes
        edit_bet(page).click()
        page.get_by_role("button", name="Delete bet", exact=True).click()
        page.get_by_role("button", name="Keep bet", exact=True).click()
        expect(page.locator("#delete-confirmation")).not_to_be_visible()
        assert not deletes
        page.get_by_role("button", name="Delete bet", exact=True).click()
        page.get_by_role("button", name="Delete permanently", exact=True).click()
        expect(page.locator("#edit-status")).to_contain_text("Could not delete")
        expect(page.locator('[name="stake-0"]')).to_have_value("37")
        expect(page.locator("#editor")).to_be_visible()
        state["failure"] = False
        page.get_by_role("button", name="Delete permanently", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        expect(page.locator(".journal-entry")).to_have_count(0)
        expect(page.locator("#results")).to_be_focused()
        assert deletes == [dict(revision=3), dict(revision=3)]
        assert not errors, errors
        browser.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_closing_market_and_fair_odds_show_exact_pick_and_alt_bracket(width, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    row = offer()
    row.update(
        family="total",
        venue="novig",
        selection=dict(predicate="over", signed_line="145.5"),
    )
    close = deepcopy(row)
    close["posted"]["value"] = "+115"
    fair = dict(
        book="draftkings",
        fair_odds="+104",
        basis="exact_line_conservative",
        selection=row["selection"],
        posted_odds="-110",
        source_at=row["times"]["source_at"],
        probability="0.49",
        alternate_lines=[],
        probability_range=None,
    )
    saved = dict(
        id="closing-entry",
        kind="ev",
        snapshot=row,
        revision=1,
        decision="saved",
        trade=None,
        created_at=row["times"]["received_at"],
        metrics=dict(
            close_state="closed", legs=[dict(close_quote=close, closing_fair=fair)]
        ),
    )

    def serve(route):
        url = urlparse(route.request.url)
        if url.path == "/api/bet-journal":
            route.fulfill(json=dict(entries=[saved], total=1, summary={}, monitor={}))
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(path=ASSETS / "bet-journal.html")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=900))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/my-bets")
        page.locator(".journal-details > summary").click()
        closing = page.get_by_role("region", name="Closing prices")
        expect(closing).to_contain_text("Exact-pick close · Novig")
        expect(closing).to_contain_text("Over 145.5 · +115")
        expect(closing).to_contain_text("Closing fair odds · DraftKings")
        expect(closing).to_contain_text("+104")
        expect(closing).to_contain_text("book price -110")
        fair.update(
            basis="alternate_line_interpolation",
            fair_odds="+100",
            posted_odds="-108",
            posted_estimated=True,
            probability="0.5",
            probability_range=["0.4", "0.6"],
            alternate_lines=[
                dict(
                    selection=dict(predicate="over", signed_line="144.5"),
                    fair_odds="-150",
                ),
                dict(
                    selection=dict(predicate="over", signed_line="146.5"),
                    fair_odds="+150",
                ),
            ],
        )
        saved["metrics"]["legs"][0]["close_reference_basis"] = (
            "alternate_line_interpolation"
        )
        page.reload()
        page.locator(".journal-details > summary").click()
        expect(page.locator(".journal-figures")).to_contain_text(
            "Entry EV at close (estimated)"
        )
        expect(closing).to_contain_text("Estimated fair close · DraftKings")
        expect(closing).to_contain_text("estimated book price -108")
        expect(closing).to_contain_text(
            "Over 144.5 · -150 fair ↔ Over 146.5 · +150 fair"
        )
        expect(closing).to_contain_text(
            "Interpolated fair probability 50.00% · range 40.00%–60.00%"
        )
        expect(closing).to_contain_text("Over 145.5 · +115")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(
            path=str(tmp_path / f"closing-bracket-{width}.png"), full_page=True
        )
        assert not errors, errors
        browser.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_single_leg_outcomes_preview_stake_corrections_and_pending(width, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    quote = prophetx_quote()
    fixture = JournalUI(tmp_path / "outcomes.sqlite3", quote)
    key = fixture.journal.observe("ev", quote, manual=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=844))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", fixture.serve)
        page.goto("https://predict.fixture/my-bets?entry=" + key)
        expect(page.locator("#leg-preview-0")).to_contain_text("$217.60")
        prices = page.locator("#leg-preview-0 .journal-entry-prices")
        expect(prices).to_contain_text("Entry · before fees")
        expect(prices).to_contain_text("45.45%")
        expect(prices).to_contain_text("+120")
        expect(prices).to_contain_text("After fees")
        expect(prices).to_contain_text("45.96%")
        page.locator('[name="price-0"]').fill("+110")
        choose_outcome(page, 0, "win")
        expect(page.locator("#settlement-preview")).to_contain_text("$207.80")
        expect(page.locator("#settlement-preview")).to_contain_text("$107.80")
        expect(prices).to_contain_text("47.62%")
        expect(prices).to_contain_text("+110")
        expect(prices).to_contain_text("48.12%")
        expect(prices).to_contain_text("Total paid $100.00")
        assert fixture.previews and not fixture.updates
        assert fixture.journal.get(key)["entry"]["revision"] == 1
        assert fixture.journal.get(key)["entry"]["trade"] is None
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        expect(page.locator(".journal-result-line")).to_contain_text("$107.80")
        expect(page.locator(".journal-entry .journal-entry-prices")).to_contain_text(
            "+110"
        )
        expect(page.locator(".journal-details")).not_to_have_attribute("open", "")
        closed_height = page.locator(".journal-entry").bounding_box()["height"]
        page.locator(".journal-details > summary").click()
        assert page.locator(".journal-entry").bounding_box()["height"] > closed_height
        expect(page.locator(".journal-details")).to_contain_text("+120")
        # Outcomes are re-derived from the corrected fill, not frozen as receipts.
        edit_bet(page).click()
        page.locator('[name="stake-0"]').fill("50")
        expect(page.locator("#settlement-preview")).to_contain_text("$103.90")
        expect(page.locator("#settlement-preview")).to_contain_text("$53.90")
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        result = fixture.journal.get(key)["entry"]
        assert result["trade"]["result"]["outcomes"] == ["win"]
        assert result["metrics"]["settlement"]["receipts_usd"] == ["103.9"]
        assert result["metrics"]["realized_profit_usd"] == "53.9"
        edit_bet(page).click()
        choose_outcome(page, 0, "pending")
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        assert fixture.updates[-1]["trade"]["result"] is None
        assert fixture.journal.get(key)["entry"]["trade"].get("result") is None
        expect(page.locator(".journal-result-line")).to_contain_text("Result pending")
        assert (
            fixture.journal.get(key)["entry"]["metrics"]["realized_profit_usd"] is None
        )
        for outcome, receipt, profit, shown in (
            ("win", "103.9", "53.9", "$53.90"),
            ("loss", "0", "-50", "-$50.00"),
            ("push", "50", "0", "$0.00"),
        ):
            edit_bet(page).click()
            choose_outcome(page, 0, outcome)
            page.locator("#save").click()
            expect(page.locator("#editor")).not_to_be_visible()
            stored = fixture.journal.get(key)["entry"]
            assert stored["trade"]["result"]["outcomes"] == [outcome]
            assert "receipts_usd" not in fixture.updates[-1]["trade"]["result"]
            assert stored["metrics"]["settlement"]["receipts_usd"] == [receipt]
            assert stored["metrics"]["settlement"]["entry_cost_usd"] == "50"
            assert stored["metrics"]["realized_profit_usd"] == profit
            expect(page.locator(".journal-result-line")).to_contain_text(shown)
            assert stored["snapshot"] == quote
        assert not errors, errors
        browser.close()


def journal_arb():
    a = prophetx_quote()
    a["side"] = "home"
    b = deepcopy(a)
    b.update(
        id="book-leg",
        venue="draftkings",
        side="away",
        selection_label="Milwaukee Bucks",
    )
    b["selection"].update(participant="NBA:MIL", signed_line="1.5")
    b["posted"]["value"] = "+110"
    b["raw"].update(posted_decimal="2.1", after_fee_decimal="2.1")
    b["display"].update(posted_odds="+110", after_fees="+110")
    b["fee"].update(
        classification="sportsbook_no_placement_fee",
        entry_usd="0",
        evidence={},
        cashflows=dict(
            win=dict(total_fee_usd="0", net_receipt_usd="210"),
            loss=dict(total_fee_usd="0", net_receipt_usd="0"),
        ),
    )
    return dict(
        id="pair-journal",
        game=a["game"],
        league="NBA",
        kickoff=a["kickoff"],
        family="spread",
        return_rate=".05",
        legs=[a, b],
    )


@pytest.mark.parametrize("width", [390, 1440])
def test_arb_per_leg_outcomes_require_complete_reports_and_keep_net_cash(
    width, tmp_path
):
    from playwright.sync_api import expect, sync_playwright

    pair = journal_arb()
    fixture = JournalUI(tmp_path / "arb-outcomes.sqlite3", pair["legs"][0])
    key = fixture.journal.observe("arb", pair, manual=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=844))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", fixture.serve)
        page.goto("https://predict.fixture/my-bets?entry=" + key)
        for i in range(2):
            page.locator(f'[name="stake-{i}"]').fill("100")
        choose_outcome(page, 0, "win")
        expect(page.locator('[name="outcome-1"][value="pending"]')).to_be_checked()
        page.locator("#save").click()
        expect(page.locator("#editor")).to_be_visible()
        expect(page.locator("#edit-status")).to_contain_text(
            "Pick a result for each leg"
        )
        assert not fixture.updates
        choose_outcome(page, 1, "loss")
        expect(page.locator("#settlement-preview")).to_contain_text("$217.60")
        expect(page.locator("#settlement-preview")).to_contain_text("$17.60")
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        stored = fixture.journal.get(key)["entry"]
        assert stored["trade"]["result"]["outcomes"] == ["win", "loss"]
        assert stored["metrics"]["settlement"]["receipts_usd"] == ["217.6", "0"]
        assert stored["metrics"]["settlement"]["entry_cost_usd"] == "200"
        assert stored["metrics"]["realized_profit_usd"] == "17.6"
        expect(page.locator(".journal-result-line")).to_contain_text("Win / Loss")
        expect(page.locator(".journal-result-line")).to_contain_text("$17.60")
        edit_bet(page).click()
        choose_outcome(page, 0, "push")
        choose_outcome(page, 1, "push")
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        stored = fixture.journal.get(key)["entry"]
        assert stored["metrics"]["settlement"]["receipts_usd"] == ["100", "100"]
        assert stored["metrics"]["realized_profit_usd"] == "0"
        assert stored["snapshot"] == pair
        assert not errors, errors
        browser.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_legacy_receipt_adjustment_failure_conflict_and_correction_keep_history(
    width, tmp_path
):
    from playwright.sync_api import expect, sync_playwright

    quote = prophetx_quote()
    fixture = JournalUI(tmp_path / "legacy.sqlite3", quote)
    key = fixture.journal.observe("ev", quote, manual=True)
    original = fixture.journal.update(
        key,
        dict(
            revision=1,
            decision="placed",
            notes="Retained original note",
            trade=dict(
                automatic=True,
                legs=[
                    dict(
                        quote_id=quote["id"],
                        stake="100",
                        price="+110",
                        units="american_odds",
                    )
                ],
                result=dict(receipts_usd=["205"], notes="Legacy exceptional net cash"),
            ),
        ),
    )["entry"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=844))
        page.route("**/*", fixture.serve)
        page.goto("https://predict.fixture/my-bets?entry=" + key)
        expect(page.locator('[name="manual_result"]')).to_be_checked()
        expect(page.locator('[name="receipt-0"]')).to_have_value("205")
        page.get_by_text("More options", exact=True).click()
        page.locator('[name="notes"]').fill("Corrected note, original returned cash")
        page.get_by_text("Original snapshot & correction history", exact=True).click()
        assert_editor_controls_fixed(page)
        fixture.fail_save = True
        page.locator("#save").click()
        expect(page.locator("#edit-status")).to_contain_text(
            "Stored changes unavailable"
        )
        expect(page.locator('[name="receipt-0"]')).to_have_value("205")
        expect(page.locator('[name="notes"]')).to_have_value(
            "Corrected note, original returned cash"
        )
        assert fixture.journal.get(key)["entry"]["revision"] == original["revision"]
        fixture.fail_save, fixture.conflict = False, True
        page.locator("#save").click()
        expect(page.locator("#edit-status")).to_contain_text("another session")
        expect(page.locator('[name="receipt-0"]')).to_have_value("205")
        fixture.conflict = False
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        stored = fixture.journal.get(key)["entry"]
        assert stored["trade"]["result"]["receipts_usd"] == ["205"]
        assert "outcomes" not in stored["trade"]["result"]
        assert stored["metrics"]["realized_profit_usd"] == "105"
        edit_bet(page).click()
        page.locator('[name="receipt-0"]').fill("204.5")
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        record = fixture.journal.get(key, history=True)
        assert record["entry"]["metrics"]["realized_profit_usd"] == "104.5"
        assert record["entry"]["snapshot"] == quote
        assert record["history"][-2]["trade"]["result"]["receipts_usd"] == ["205"]
        expect(page.locator(".journal-result-line")).to_contain_text("Cash adjustment")
        expect(page.locator(".journal-result-line")).to_contain_text("$104.50")
        # Choosing a modeled outcome hides the retained cash adjustment, so it
        # cannot appear to disagree with the newly calculated net return.
        edit_bet(page).click()
        expect(page.locator('[name="manual_result"]')).to_be_checked()
        expect(page.locator('[name="receipt-0"]')).to_have_value("204.5")
        choose_outcome(page, 0, "win")
        expect(page.locator('[name="manual_result"]')).not_to_be_checked()
        expect(page.locator("#settlement")).not_to_have_attribute("open", "")
        expect(page.locator('[name="receipt-0"]')).not_to_be_visible()
        expect(page.locator("#settlement-preview")).to_contain_text("$207.80")
        expect(page.locator("#settlement-preview")).to_contain_text("$107.80")
        unchanged = fixture.journal.get(key)["entry"]
        assert unchanged["revision"] == record["entry"]["revision"]
        assert unchanged["trade"]["result"]["receipts_usd"] == ["204.5"]
        assert "outcomes" not in unchanged["trade"]["result"]
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        converted = fixture.journal.get(key, history=True)
        assert converted["entry"]["trade"]["result"]["outcomes"] == ["win"]
        assert "receipts_usd" not in converted["entry"]["trade"]["result"]
        assert converted["entry"]["metrics"]["realized_profit_usd"] == "107.8"
        assert converted["history"][-2]["trade"]["result"]["receipts_usd"] == ["204.5"]
        assert converted["entry"]["snapshot"] == quote
        expect(page.locator(".journal-result-line")).to_contain_text("Win")
        expect(page.locator(".journal-result-line")).not_to_contain_text(
            "Cash adjustment"
        )
        browser.close()


def test_outcome_with_unavailable_saved_fees_does_not_invent_zero_profit(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    quote = offer()
    quote["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
    fixture = JournalUI(tmp_path / "unknown-fees.sqlite3", quote)
    key = fixture.journal.observe("ev", quote, manual=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=390, height=844))
        page.route("**/*", fixture.serve)
        page.goto("https://predict.fixture/my-bets?entry=" + key)
        choose_outcome(page, 0, "win")
        expect(page.locator("#settlement-preview")).to_contain_text("Unavailable")
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        stored = fixture.journal.get(key)["entry"]
        assert stored["trade"]["result"]["outcomes"] == ["win"]
        assert stored["metrics"]["settlement"]["state"] == "unavailable"
        assert stored["metrics"]["settlement"]["receipts_usd"] == [None]
        assert stored["metrics"]["realized_profit_usd"] is None
        expect(page.locator(".journal-result-line")).to_contain_text("Unavailable")
        expect(page.locator(".journal-result-line")).not_to_contain_text("$0.00")
        browser.close()


@pytest.mark.parametrize("first_save_succeeds", [True, False])
def test_reopened_same_record_ignores_old_save_completion(
    first_save_succeeds, tmp_path
):
    from app.dashboard.bet_journal import Conflict
    from playwright.sync_api import expect, sync_playwright

    quote = prophetx_quote()
    fixture = JournalUI(tmp_path / "reopened-editor.sqlite3", quote)
    key = fixture.journal.observe("ev", quote, manual=True)
    held = []

    def serve(route):
        if (
            urlparse(route.request.url).path == "/api/bet-journal/" + key
            and route.request.method == "POST"
        ):
            held.append((route, deepcopy(route.request.post_data_json)))
        else:
            fixture.serve(route)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=390, height=844))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Observe completion after the app consumes each response's JSON and the
        # subsequent microtasks run; a response-headers event alone is too early
        # to prove the old catch/finally did not unlock a newly opened editor.
        page.add_init_script("""(() => {
          window.completedWrites=[];const original=window.fetch;
          window.fetch=async(...args)=>{
            const response=await original(...args),url=new URL(String(args[0]),location.href);
            if(args[1]?.method==='POST'&&url.pathname.startsWith('/api/bet-journal/')&&!url.pathname.endsWith('/preview')){
              const json=response.json.bind(response);
              response.json=async()=>{const data=await json();setTimeout(()=>window.completedWrites.push(response.status),0);return data;};
            }return response;
          };
        })()""")
        page.route("**/*", serve)
        page.goto("https://predict.fixture/my-bets?entry=" + key)
        page.get_by_text("More options", exact=True).click()
        page.locator('[name="notes"]').fill("Save A from the closed editor")
        page.locator("#save").click()
        expect(page.locator("#save")).to_be_disabled()
        expect(page.locator('[name="stake-0"]')).to_be_disabled()
        expect(page.locator('[name="price-0"]')).to_be_disabled()
        expect(page.locator('[name="notes"]')).to_be_disabled()
        expect(page.locator("#cancel")).to_be_enabled()
        assert len(held) == 1
        page.locator("#cancel").click()
        expect(page.locator("#editor")).not_to_be_visible()
        edit_bet(page).click()  # Same ID, distinct editor session.
        expect(page.locator('[name="stake-0"]')).to_be_enabled()
        expect(page.locator('[name="price-0"]')).to_be_enabled()
        expect(page.locator("#save")).to_be_enabled()
        page.get_by_text("More options", exact=True).click()
        page.locator('[name="notes"]').fill("Save B from the reopened editor")
        page.locator("#save").click()
        expect(page.locator("#save")).to_be_disabled()
        expect(page.locator('[name="notes"]')).to_be_disabled()
        assert len(held) == 2
        first, first_body = held[0]
        if first_save_succeeds:
            first.fulfill(json=fixture.journal.update(key, first_body))
        else:
            first.fulfill(status=503, json=dict(error="Save A failed"))
        page.wait_for_function("window.completedWrites.length===1")
        if first_save_succeeds:
            expect(page.locator(".journal-entry")).to_contain_text(
                "Save A from the closed editor"
            )
        expect(page.locator("#editor")).to_be_visible()
        expect(page.locator("#save")).to_be_disabled()
        expect(page.locator('[name="stake-0"]')).to_be_disabled()
        expect(page.locator('[name="notes"]')).to_be_disabled()
        expect(page.locator('[name="notes"]')).to_have_value(
            "Save B from the reopened editor"
        )
        expect(page.locator("#edit-status")).to_have_text("Saving changes…")
        second, second_body = held[1]
        assert second_body["notes"] == "Save B from the reopened editor"
        try:
            completed = fixture.journal.update(key, second_body)
        except Conflict:
            assert first_save_succeeds
            second.fulfill(status=409, json=dict(error="revision_conflict"))
        else:
            assert not first_save_succeeds
            second.fulfill(json=completed)
        page.wait_for_function("window.completedWrites.length===2")
        if first_save_succeeds:
            # The second editor owns this genuine conflict and unlocks only
            # after its own response, preserving the unsaved correction.
            expect(page.locator("#editor")).to_be_visible()
            expect(page.locator("#edit-status")).to_contain_text("another session")
            expect(page.locator('[name="notes"]')).to_be_enabled()
            expect(page.locator("#save")).to_be_enabled()
            expect(page.locator('[name="notes"]')).to_have_value(
                "Save B from the reopened editor"
            )
            assert fixture.journal.get(key)["entry"]["notes"] == first_body["notes"]
            page.locator("#cancel").click()
        else:
            expect(page.locator("#editor")).not_to_be_visible()
            expect(page.locator(".journal-entry")).to_contain_text(second_body["notes"])
            assert fixture.journal.get(key)["entry"]["notes"] == second_body["notes"]
        assert fixture.journal.get(key)["entry"]["snapshot"] == quote
        assert not errors, errors
        browser.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_opportunity_log_keeps_only_positive_unique_market_arbs_and_selected_ev(
    width,
    tmp_path,
):
    import sqlite3
    from app.dashboard.bet_journal import digest, encoded
    from playwright.sync_api import expect, sync_playwright

    quote = prophetx_quote()
    quote["selection_label"] = "Historical unpicked EV"
    fixture = JournalUI(tmp_path / "arb-only-log.sqlite3", quote)
    journal = fixture.journal
    at = quote["times"]["received_at"]

    def historical(kind, snapshot, note):
        # Only the disposable fixture bypasses today's discovery policy to
        # reconstruct actual pre-policy records that an existing journal holds.
        rows = snapshot["legs"] if kind == "arb" else [snapshot]
        key = digest(["automatic", kind, [journal.identity(r) for r in rows]])
        with journal.database(write=True) as db:
            db.execute(
                """INSERT INTO entries
                (id,kind,origin,created_at,updated_at,decision,revision,snapshot,notes,trade)
                VALUES(?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    key,
                    kind,
                    "automatic",
                    at,
                    at,
                    "observed",
                    1,
                    encoded(snapshot),
                    note,
                ),
            )
            db.execute(
                "INSERT INTO events VALUES(?,?,?,?)",
                (
                    key,
                    1,
                    at,
                    encoded(dict(decision="observed", notes=note, trade=None)),
                ),
            )
            for row in rows:
                db.execute(
                    "INSERT OR IGNORE INTO tracked VALUES(?,?)",
                    (row["id"], journal.identity(row)),
                )
        return key

    legacy_ev = historical("ev", quote, "Historical automatic EV")
    market_book = journal_arb()
    market_book.update(
        category="market_book", minimum_profit_usd="10", committed_usd="200"
    )
    legacy_book = historical("arb", market_book, "Historical automatic market-book arb")
    saved_book = journal.observe("arb", market_book, manual=True)
    pair = deepcopy(market_book)
    pair.update(
        id="market-market-log",
        category="market_market",
        receipts_usd=["217.6", "210"],
        profits_usd=["17.6", "10"],
    )
    pair["legs"][1].update(id="novig-log-leg", venue="novig")
    pair["legs"][1]["fee"]["classification"] = "exact_public"
    # Positive arb cashflows do not require per-leg sportsbook EV references.
    for leg in pair["legs"]:
        leg.pop("reference", None)
        leg["raw"].pop("net_ev", None)
        leg["display"].pop("net_ev", None)
    arb_key = journal.observe("arb", pair)
    assert arb_key is not None
    assert (
        journal.observe("arb", dict(pair, legs=list(reversed(pair["legs"])))) == arb_key
    )
    moved = deepcopy(pair)
    moved["legs"][0]["posted"]["value"] = "+130"
    moved["legs"][0]["raw"].update(posted_decimal="2.3", after_fee_decimal="2.274")
    moved["legs"][0]["display"].update(posted_odds="+130", after_fees="+127")
    moved["legs"][0]["fee"]["cashflows"]["win"].update(
        total_fee_usd="2.6", net_receipt_usd="227.4"
    )
    assert journal.observe("arb", moved) == arb_key
    manual = {}
    for decision in ("saved", "placed", "passed"):
        chosen = prophetx_quote()
        chosen.update(
            id="selected-" + decision, selection_label="Selected EV " + decision
        )
        key = journal.observe("ev", chosen, manual=True)
        manual[decision] = key
        if decision == "placed":
            journal.update(
                key,
                dict(
                    revision=1,
                    decision="placed",
                    trade=dict(
                        automatic=True,
                        legs=[
                            dict(
                                quote_id=chosen["id"],
                                stake="100",
                                price="+110",
                                units="american_odds",
                            )
                        ],
                        result=dict(outcomes=["win"]),
                    ),
                ),
            )
        elif decision == "passed":
            journal.update(
                key, dict(revision=1, decision="passed", notes="Explicitly declined")
            )
    # Quotes are collected only after an eligible arb or chosen bet owns the
    # identity; an old unpicked EV alone must no longer keep tracking alive.
    journal.quotes([quote], at=at)
    with journal.database() as db:
        legacy_rows = {
            key: tuple(
                db.execute("SELECT * FROM entries WHERE id=?", (key,)).fetchone()
            )
            for key in (legacy_ev, legacy_book)
        }
        legacy_events = [
            tuple(r)
            for r in db.execute("SELECT * FROM events WHERE entry_id=?", (legacy_ev,))
        ]
        shared_quotes = [
            tuple(r)
            for r in db.execute("SELECT * FROM quotes WHERE quote_id=?", (quote["id"],))
        ]
        assert db.execute("SELECT count(*) FROM entries").fetchone()[0] == 7
    assert shared_quotes
    visible = {arb_key, saved_book, manual["saved"], manual["placed"]}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=844))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", fixture.serve)
        page.goto("https://predict.fixture/my-bets")
        expect(page.locator(".journal-entry")).to_have_count(3)
        assert set(
            page.locator(".journal-entry").evaluate_all(
                "es=>es.map(e=>e.dataset.entryId)"
            )
        ) == {saved_book, manual["saved"], manual["placed"]}
        expect(page.locator("#summary")).to_contain_text("$107.80")
        page.get_by_role("button", name="Opportunity log", exact=True).click()
        expect(page.locator(".journal-entry")).to_have_count(4)
        expect(page.locator("#count")).to_have_text("4 records")
        tools = page.locator(".journal-result-tools")
        toolbar = tools.bounding_box()
        first_card = page.locator(".journal-entry").first.bounding_box()
        assert toolbar["y"] + toolbar["height"] <= first_card["y"]
        expect(tools.get_by_role("navigation", name="Journal pages")).to_be_visible()
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        assert page.evaluate("scrollY") > 0
        for selector in ("#previous", "#next"):
            control = page.locator(selector)
            expect(control).to_be_in_viewport()
            box = control.bounding_box()
            assert (
                box["y"] >= 0
                and box["y"] + box["height"] <= page.viewport_size["height"]
            )
            assert control.evaluate(
                "button=>{const r=button.getBoundingClientRect();return button.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}"
            )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        observed = page.locator(
            f'.journal-entry[data-entry-id="{arb_key}"] .journal-observed-arb'
        )
        expect(observed).to_be_visible()
        for value in ("+5.00%", "$10.00", "$200.00"):
            expect(observed).to_contain_text(value)
        expect(observed).not_to_contain_text("Unavailable")
        assert (
            set(
                page.locator(".journal-entry").evaluate_all(
                    "es=>es.map(e=>e.dataset.entryId)"
                )
            )
            == visible
        )
        expect(page.locator("#results")).not_to_contain_text("Historical unpicked EV")
        summary = journal.list(view="log")["summary"]
        assert summary["counts"] == dict(observed=1, saved=2, placed=1)
        assert summary["opportunities"] == 1
        assert summary["settled"] == 1
        assert Fraction(summary["realized_profit_usd"]) == Fraction("107.8")
        page.get_by_label("Opportunity type").select_option("ev")
        expect(page.locator(".journal-entry")).to_have_count(2)
        assert set(
            page.locator(".journal-entry").evaluate_all(
                "es=>es.map(e=>e.dataset.entryId)"
            )
        ) == {manual["saved"], manual["placed"]}
        page.get_by_label("Decision", exact=True).select_option("observed")
        expect(page.locator(".journal-entry")).to_have_count(0)
        expect(page.locator("#count")).to_have_text("0 records")
        assert fixture.reads[-1]["view"] == "log" and fixture.reads[-1]["kind"] == "ev"
        page.get_by_label("Opportunity type").select_option("arb")
        expect(page.locator(".journal-entry")).to_have_count(1)
        expect(page.locator(".journal-entry")).to_have_attribute(
            "data-entry-id", arb_key
        )
        expect(page.locator("#summary")).to_contain_text("$107.80")
        assert not fixture.updates and not errors, errors
        browser.close()
    # Browsing hides excluded data; it cannot silently perform maintenance.
    with journal.database() as db:
        assert {
            key: tuple(
                db.execute("SELECT * FROM entries WHERE id=?", (key,)).fetchone()
            )
            for key in legacy_rows
        } == legacy_rows
        assert [
            tuple(r)
            for r in db.execute("SELECT * FROM events WHERE entry_id=?", (legacy_ev,))
        ] == legacy_events
    assert journal.get(legacy_ev, history=True)["entry"]["snapshot"] == quote

    def retained(key):
        result = journal.get(key, history=True)
        # This link is derived from the old automatic EV row, which cleanup is
        # authorized to remove; selected snapshot/trade/history remain exact.
        result["entry"].pop("opportunity_id", None)
        return result

    protected = {key: retained(key) for key in (*visible, legacy_book)}
    backup = tmp_path / "before-unpicked-ev-prune.sqlite3"
    journal.prune_unpicked_evs(backup_path=backup)
    assert backup.is_file()
    with sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("SELECT count(*) FROM entries").fetchone()[0] == 7
        assert (
            tuple(
                db.execute("SELECT * FROM entries WHERE id=?", (legacy_ev,)).fetchone()
            )
            == legacy_rows[legacy_ev]
        )
        assert (
            db.execute(
                "SELECT count(*) FROM entries WHERE id=?", (manual["passed"],)
            ).fetchone()[0]
            == 1
        )
    with journal.database() as db:
        assert {row[0] for row in db.execute("SELECT id FROM entries")} == set(
            protected
        )
        assert (
            db.execute(
                "SELECT count(*) FROM events WHERE entry_id IN (?,?)",
                (legacy_ev, manual["passed"]),
            ).fetchone()[0]
            == 0
        )
        assert [
            tuple(r)
            for r in db.execute("SELECT * FROM quotes WHERE quote_id=?", (quote["id"],))
        ] == shared_quotes
    assert {key: retained(key) for key in protected} == protected
    assert {entry["id"] for entry in journal.list(view="log")["entries"]} == visible
    assert journal.list(view="log")["summary"]["counts"] == dict(
        observed=1, saved=2, placed=1
    )
