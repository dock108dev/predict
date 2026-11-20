"""Observed opportunity-log eligibility, saved picks and lazy closing analysis."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import os
import re
from urllib.parse import urlparse

import pytest

from browser_tests.journal_fixture import JournalUI, journal_arb, prophetx_quote


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
    # A real fee-qualified arb quote can explicitly lack a fair reference. Give
    # that tracked Novig leg qualified source/receipt/observation clocks so the
    # normal log read must analyze it, rather than quietly discarding the row.
    null_clock = datetime.now(timezone.utc).isoformat()
    reference_free = deepcopy(pair["legs"][1])
    reference_free.update(
        reference=None, times=dict(source_at=null_clock, received_at=null_clock)
    )
    assert journal.quotes([reference_free], at=null_clock) == 1
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
        expect(page.locator(".journal-entry")).to_have_count(1)
        assert set(
            page.locator(".journal-entry").evaluate_all(
                "es=>es.map(e=>e.dataset.entryId)"
            )
        ) == {manual["placed"]}
        page.get_by_role("button", name="Saved research", exact=True).click()
        expect(page.locator(".journal-entry")).to_have_count(2)
        assert set(
            page.locator(".journal-entry").evaluate_all(
                "es=>es.map(e=>e.dataset.entryId)"
            )
        ) == {saved_book, manual["saved"]}
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
        arb_card = page.locator(f'.journal-entry[data-entry-id="{arb_key}"]')
        expect(arb_card.locator(".journal-details")).not_to_have_attribute("open", "")
        visible_legs = arb_card.locator(":scope > p.journal-observed")
        expect(visible_legs).to_be_visible()
        expect(visible_legs).to_contain_text(
            "ProphetX · Orlando Magic -1.5 · 45.45% (+120)"
        )
        expect(visible_legs).to_contain_text(
            "Novig · Milwaukee Bucks +1.5 · 47.62% (+110)"
        )
        observed = arb_card.locator(".journal-observed-arb")
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
        analyzed = next(
            entry
            for entry in journal.list(view="log", decision="observed")["entries"]
            if entry["id"] == arb_key
        )
        metrics = analyzed["metrics"]
        assert Fraction(metrics["entry_arb_return"]) == Fraction(".05")
        assert metrics["entry_cost_usd"] == "200"
        assert metrics["entry_min_profit_usd"] == "10"
        assert metrics["entry_ev"] is None
        latest = metrics["legs"][1]["latest_quote"]
        assert "reference" in latest and latest["reference"] is None
        assert latest["times"] == dict(source_at=null_clock, received_at=null_clock)
        assert latest["observed_at"] == null_clock
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


def test_observed_arb_details_load_full_closes_lazily_and_retry_without_losing_focus(
    tmp_path,
):
    from playwright.sync_api import expect, sync_playwright

    now = datetime.now(timezone.utc)
    kickoff = now - timedelta(minutes=1)
    original_at = kickoff - timedelta(minutes=3)
    created_at = kickoff - timedelta(minutes=2)
    source_close = kickoff - timedelta(seconds=10)
    received_close = kickoff - timedelta(seconds=9)
    observed_close = kickoff - timedelta(seconds=8)
    pair = journal_arb()
    pair.update(
        category="market_market",
        minimum_profit_usd="10",
        committed_usd="200",
        kickoff=kickoff.isoformat(),
    )
    pair["legs"][1].update(id="lazy-novig-close", venue="novig")
    pair["legs"][1]["fee"]["classification"] = "exact_public"
    for leg in pair["legs"]:
        leg.update(
            kickoff=kickoff.isoformat(),
            times=dict(
                source_at=original_at.isoformat(), received_at=original_at.isoformat()
            ),
            reference=None,
            calculated_at=created_at.isoformat(),
        )
        leg["raw"].pop("net_ev", None)
        leg["display"].pop("net_ev", None)
    fixture = JournalUI(tmp_path / "lazy-observed.sqlite3", pair["legs"][0])
    key = fixture.journal.observe("arb", pair, at=created_at)
    closing = deepcopy(pair["legs"])
    for leg in closing:
        leg["times"] = dict(
            source_at=source_close.isoformat(), received_at=received_close.isoformat()
        )
        leg["calculated_at"] = observed_close.isoformat()
    assert fixture.journal.quotes(closing, at=observed_close) == 2
    state, pending = dict(fail=True), []

    def serve(route):
        if (
            route.request.method == "GET"
            and urlparse(route.request.url).path == "/api/bet-journal/" + key
        ):
            fixture.detail_reads.append(key)
            if state["fail"]:
                route.fulfill(
                    status=503, json=dict(error="fixture_detail_read_unavailable")
                )
            else:
                pending.append(route)
        else:
            fixture.serve(route)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=390, height=844))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/my-bets?view=log")
        card = page.locator(".journal-entry")
        expect(card).to_have_count(1)
        assert fixture.reads[-1]["defer_observed"] == "1"
        initial = fixture.list_packets[-1]["entries"][0]
        assert initial["metrics"] == dict(deferred=True, close_state="closed")
        assert initial["snapshot"] == pair
        assert not fixture.detail_reads
        primary = card.locator(":scope > .journal-observed")
        expect(primary).to_be_visible()
        expect(primary).to_contain_text("ProphetX · Orlando Magic -1.5 · 45.45% (+120)")
        expect(primary).to_contain_text("Novig · Milwaukee Bucks +1.5 · 47.62% (+110)")
        expect(card.locator(".journal-observed-arb")).to_contain_text("+5.00%")
        details = card.locator(".journal-details")
        expect(details).not_to_have_attribute("open", "")
        expect(details.locator(":scope > p[role=status]")).to_have_text(
            "Open to load closing prices and analysis."
        )
        expect(details.get_by_role("region", name="Closing prices")).to_have_count(0)
        summary = details.locator(":scope > summary")
        summary.evaluate("e=>e.dataset.originalDisclosure='yes'")
        summary.focus()
        page.keyboard.press("Enter")
        expect(details).to_have_attribute("open", "")
        expect(details).to_contain_text("Close and reopen to retry")
        expect(card).to_have_count(1)
        expect(primary).to_be_visible()
        expect(summary).to_be_focused()
        state["fail"] = False
        summary.click()
        expect(details).not_to_have_attribute("open", "")
        with page.expect_request(
            lambda request: (
                request.method == "GET"
                and urlparse(request.url).path == "/api/bet-journal/" + key
            )
        ):
            summary.focus()
            page.keyboard.press("Enter")
        expect(details).to_have_attribute("open", "")
        expect(summary).to_be_focused()
        assert len(pending) == 1
        expect(details.locator(":scope > p[role=status]")).to_have_text(
            "Loading closing prices and analysis…"
        )
        pending.pop().fulfill(json=fixture.journal.get(key, history=True))
        closes = details.get_by_role("region", name="Closing prices")
        expect(closes).to_be_visible()
        expect(closes).to_contain_text("Orlando Magic -1.5 · 45.45% (+120)")
        expect(closes).to_contain_text("Milwaukee Bucks +1.5 · 47.62% (+110)")
        close_math = details.locator(".journal-figure").filter(
            has=page.locator(
                "span", has_text=re.compile(r"^Closing quote model return$")
            )
        )
        expect(close_math.locator("strong")).to_have_text("+5.00%")
        expect(close_math).to_contain_text("$10.00 modeled profit")
        expect(close_math).to_contain_text("$200.00 basis")
        expect(details).to_have_attribute("open", "")
        expect(summary).to_have_attribute("data-original-disclosure", "yes")
        expect(summary).to_be_focused()
        expect(page.locator("dialog[open]")).to_have_count(0)
        assert fixture.detail_reads == [key, key]
        stored = fixture.journal.get(key, history=True)
        assert stored["entry"]["revision"] == 1
        assert stored["entry"]["snapshot"] == pair
        assert stored["entry"]["metrics"]["close_arb_return"] == "0.05"
        assert all(
            leg["close_quote"]["times"]["source_at"] == source_close.isoformat()
            for leg in stored["entry"]["metrics"]["legs"]
        )
        assert not fixture.updates and not errors, errors
        browser.close()
