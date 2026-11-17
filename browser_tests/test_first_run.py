"""Exercise public odds and saved captures without an Admin challenge."""

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pytest

from app.dashboard.replay_api import load
from app.storage import odds_replay
from tests.replay_fixture import write_archives

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


def practice_journey(tab, base):
    from playwright.sync_api import expect

    tab.goto(base + "/arbs")
    tab.get_by_role("link", name="Try a practice example", exact=True).click()
    expect(tab.get_by_role("heading", name="Arbitrage", exact=True)).to_be_visible()
    expect(tab.locator("#desk-mode")).to_have_text("Practice example · simulated odds")
    cards = tab.locator(".opportunity-arb")
    positive = cards.filter(has_text="Harbor Foxes")
    expect(positive).to_contain_text("Modeled profit if the game completes")
    expect(positive).to_contain_text("125")
    expect(positive).to_contain_text("$100.00")
    expect(positive).to_contain_text("$125.00")
    expect(positive).to_contain_text("$25.00")
    expect(positive).to_contain_text("Novig")
    expect(positive).to_contain_text("ProphetX")
    expect(positive.get_by_text("$0.00", exact=True)).to_have_count(2)
    positive.get_by_role("button", name="View payoff calculation ↗").click()
    pair = tab.get_by_role("dialog", name="Pair payoff")
    expect(
        pair.get_by_text("Practice example · simulated odds", exact=True)
    ).to_be_visible()
    expect(pair).to_contain_text("$25.00")
    pair.get_by_text("Calculation details", exact=True).click()
    expect(pair).to_contain_text("void, cancellation, postponement, partial completion")
    expect(pair.locator(".inspection-payoffs tbody tr")).to_have_count(2)
    for state in pair.locator(".inspection-payoffs tbody tr").all():
        expect(state).to_contain_text("$125.00")
        expect(state).to_contain_text("$25.00")
    pair.get_by_role("button", name="Inspect offer and fees").first.click()
    expect(tab.locator("#trade .inspection-mode")).to_have_text(
        "Practice example · simulated odds"
    )
    tab.get_by_role("button", name="Back to pairing").click()
    tab.keyboard.press("Escape")
    expect(
        positive.get_by_role("button", name="View payoff calculation ↗")
    ).to_be_focused()
    shortfall = cards.filter(has_text="Canyon Hawks")
    expect(shortfall).to_contain_text("Shortfall before fees")
    expect(shortfall).to_contain_text("$0.50")
    expect(shortfall).to_contain_text("$99.50")
    expect(shortfall).to_contain_text("Net payoff unavailable")
    expect(cards.filter(has_text="Prairie Bears")).to_contain_text("fewer claims")
    expect(cards.filter(has_text="River Otters")).to_contain_text(
        "joint settlement cashflows"
    )
    tab.get_by_label("Positive only").check()
    expect(cards).to_have_count(1)
    expect(cards.first).to_contain_text("Harbor Foxes")
    tab.get_by_role("checkbox", name="Positive only").uncheck()
    assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")

    tab.goto(base + "/ev")
    tab.get_by_role("link", name="Try a practice example", exact=True).click()
    ticket = tab.locator(".pregame-ticket")
    expect(ticket).to_contain_text("Saint Mary's Gaels")
    expect(ticket).to_contain_text("+2.82%")
    expect(ticket).to_contain_text("$25 unit")
    expect(tab.get_by_label("Calculation basis")).to_be_hidden()
    expect(tab.get_by_label("Rows", exact=True)).to_be_hidden()
    ticket.get_by_role("button", name="Compare prices for", exact=False).click()
    drawer = tab.locator("#trade")
    expect(drawer).to_contain_text("Practice example · simulated odds")
    expect(drawer).to_contain_text("Unit $25")
    expect(drawer).to_contain_text("$0.75")
    expect(drawer).to_contain_text("+2.82%")
    drawer.get_by_text("Calculation and settlement details").click()
    expect(drawer).to_contain_text("$24.25")
    expect(drawer).to_contain_text("$51.41 returned")
    tab.keyboard.press("Escape")
    tab.get_by_role("link", name="Return to Opportunities", exact=True).click()
    expect(tab.get_by_role("heading", name="Opportunities", exact=True)).to_be_visible()


def first_use(tab, base, archive_directory):
    from playwright.sync_api import expect

    tab.goto(base + "/")
    expect(tab.get_by_role("heading", name="Opportunities")).to_be_visible()
    expect(
        tab.get_by_role("heading", name="Choose a unit size to rank offers after fees.")
    ).to_be_visible()
    expect(tab.get_by_role("link", name="Arbitrage")).to_be_visible()
    expect(tab.get_by_label("Unit size")).to_have_value("")
    expect(
        tab.locator("#results").get_by_role("link", name="Browse Odds")
    ).to_be_visible()
    expect(tab.get_by_role("button", name="Filters", exact=True)).to_be_hidden()
    unit = tab.get_by_label("Unit size")
    unit.select_option("custom")
    custom = tab.get_by_label("Custom amount in dollars")
    custom.fill("12.345")
    custom.press("Enter")
    assert not custom.evaluate("input => input.validity.valid")
    custom.fill("19.37")
    custom.press("Enter")
    expect(
        tab.get_by_role("heading", name="Calculating opportunities for $19.37")
    ).to_be_visible()
    tab.goto(base + "/ev")
    expect(unit).to_have_value("19.37")
    unit.select_option("custom")
    expect(custom).to_have_value("19.37")
    custom.press("Escape")
    expect(unit).to_have_value("19.37")
    saved = tab.get_by_role("link", name="Saved odds", exact=True)
    expect(saved).to_have_count(1)
    tab.get_by_role("link", name="Admin", exact=True).click()
    tab.get_by_role("link", name="Sources", exact=True).click()
    setup = tab.locator("#source-setup")
    expect(setup.locator("summary")).to_be_visible()
    setup.locator("summary").focus()
    tab.keyboard.press("Space")
    expect(setup).to_contain_text("check-config")
    expect(setup.get_by_text("Native keys", exact=False)).to_be_visible()
    tab.get_by_role("link", name="Settings", exact=True).click()
    tab.get_by_label("Time zone").select_option("UTC")
    tab.get_by_label("Odds format").select_option("decimal")
    tab.get_by_role("link", name="EV", exact=True).click()
    expect(tab.get_by_label("Calculation basis")).to_be_hidden()
    tab.reload()
    expect(tab.get_by_label("Calculation basis")).to_be_hidden()
    expect(tab.get_by_text("Synthetic practice", exact=False)).to_have_count(0)
    tab.get_by_role("link", name="Saved odds").click()
    expect(tab.get_by_text("Saved odds · prices at capture")).to_be_visible()
    expect(tab.get_by_label("Calculation basis")).to_have_value("before")
    expect(tab.get_by_label("Odds format")).to_have_value("decimal")
    expect(tab.locator("#notice")).to_contain_text("UTC")
    search = tab.get_by_role("searchbox", name="Search teams")
    search.fill("no such team")
    expect(
        tab.get_by_role("heading", name="No results for “no such team”")
    ).to_be_visible()
    tab.get_by_role("button", name="Clear search").click()
    expect(search).to_have_value("")
    search.fill("Harbor Foxes")
    offer = tab.locator('[data-offer-id="practice-offer-0"]')
    expect(offer).to_contain_text("2.20")
    offer.press("Enter")
    trade = tab.get_by_role("dialog", name="Novig · Harbor Foxes to win")
    expect(trade).to_contain_text("Original price")
    expect(trade).to_contain_text(
        "The recorded inputs do not establish venue fees or fill evidence"
    )
    expect(trade).to_contain_text("Authored scenario time")
    expect(trade).not_to_contain_text("undefined")
    trade.get_by_text("Calculations and settlement", exact=True).click()
    expect(
        trade.get_by_text("returns $22.00 total, including $12.00 profit", exact=False)
    ).to_be_visible()
    expect(trade.get_by_role("button", name="Use latest prices")).to_be_hidden()
    tab.keyboard.press("Escape")
    expect(offer).to_be_focused()

    tab.get_by_label("Calculation basis").select_option("reviewed")
    expect(offer).not_to_contain_text("+8.91%")
    expect(offer).not_to_contain_text("+10.00%")
    tab.get_by_role("link", name="Open game ↗").first.click()
    expect(tab.get_by_label("Calculation basis")).to_have_value("reviewed")
    tab.get_by_role("button", name="Spreads", exact=True).click()
    expect(tab.locator('[data-offer-id="practice-offer-spread-1"]')).to_contain_text(
        "1.91"
    )
    tab.get_by_label("Replay dataset").select_option("preview")
    expect(
        tab.get_by_role("heading", name="Harbor Foxes vs. Summit Owls")
    ).to_be_visible()
    expect(tab.get_by_role("button", name="Spreads", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(tab.locator('[data-offer-id="practice-offer-spread-1"]')).to_contain_text(
        "1.87"
    )
    tab.get_by_role("button", name="Totals", exact=True).click()
    expect(tab.locator('[data-offer-id="practice-offer-total-1"]')).to_contain_text(
        "1.95"
    )
    tab.get_by_label("Replay dataset").select_option("frozen")

    tab.get_by_role("navigation", name="Replay views").get_by_role(
        "link", name="Arbitrage"
    ).click()
    inspect = tab.get_by_role("button", name="View payoff calculation ↗").first
    inspect.press("Enter")
    pair = tab.get_by_role("dialog", name="Pair payoff")
    expect(pair).to_contain_text("Harbor Foxes")
    expect(pair).to_contain_text("Summit Owls")
    expect(pair).to_contain_text("Both leg fees are needed to calculate net settlement")
    expect(pair).not_to_contain_text("-$4.097")
    expect(pair.get_by_text("Lowest payout before fees", exact=True)).to_be_visible()
    expect(pair.get_by_role("spinbutton")).to_have_count(0)
    pair.get_by_role("button", name="Inspect offer and fees").first.click()
    expect(trade).to_contain_text(
        "The recorded inputs do not establish venue fees or fill evidence"
    )
    trade.get_by_role("button", name="Back to pairing").click()
    tab.keyboard.press("Escape")
    expect(inspect).to_be_focused()

    filters = tab.get_by_role("button", name="Filters", exact=True)
    inspect.press("Enter")
    expect(pair).to_be_visible()
    # The native dialog restores focus before the app receives its close event.
    # Focus can already have moved to a different control by then.
    focused_after_close = tab.evaluate("""async () => {
      const drawer = document.getElementById('trade');
      const closed = new Promise(resolve => drawer.addEventListener('close',
        () => resolve(document.activeElement.id), {once: true}));
      drawer.close();
      document.getElementById('open-filters').focus();
      return await closed;
    }""")
    assert focused_after_close == "open-filters"
    filters.press("Enter")
    panel = tab.get_by_role("dialog", name="Filter results")
    expect(panel).to_be_visible()
    panel.get_by_text("Sorting and return thresholds").focus()
    tab.keyboard.press("Space")
    tab.keyboard.press("Escape")
    expect(filters).to_be_focused()
    tab.get_by_label("Positive only").check()
    expect(tab.get_by_role("heading", name="No positive results")).to_be_visible()
    tab.get_by_role("button", name="Show unavailable pairings").press("Enter")
    expect(inspect).to_be_visible()
    filters.press("Enter")
    panel.get_by_label("ProphetX").uncheck()
    panel.get_by_role("button", name="Done").press("Enter")
    expect(
        tab.get_by_role("heading", name="No arbitrage calculations available")
    ).to_be_visible()
    tab.get_by_role("button", name="Clear Except ProphetX filter").press("Enter")
    expect(inspect).to_be_visible()
    tab.get_by_label("Replay dataset").select_option("preview")
    expect(inspect).to_be_visible()
    expect(tab.locator(".desk-best").filter(has_text="2.10")).to_have_count(1)
    assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")

    (archive_directory / "frozen.sqlite3").unlink()
    tab.get_by_label("Replay dataset").select_option("frozen")
    expect(
        tab.get_by_role("heading", name="This saved capture is unavailable")
    ).to_be_visible()
    expect(tab.get_by_role("link", name="Browse current odds")).to_be_visible()
    expect(tab.get_by_text("Synthetic practice", exact=False)).to_have_count(0)
    history = tab.get_by_role("button", name="Session history")
    history.press("Enter")
    history_panel = tab.get_by_role("dialog", name="Diagnostic session history")
    expect(history_panel).to_contain_text("retained events")
    with tab.expect_download() as exported:
        history_panel.get_by_role("button", name="Export session JSON").press("Enter")
    assert exported.value.suggested_filename.startswith("predict-session-")
    tab.keyboard.press("Escape")
    expect(history).to_be_focused()


@pytest.mark.parametrize("width", [1440, 390])
def test_first_use_without_credentials(width, tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    write_archives(tmp_path)
    monkeypatch.setattr(odds_replay, "DIRECTORY", tmp_path)
    reads = []
    unexpected = []
    base = "https://predict.fixture"

    def respond(route):
        url = urlparse(route.request.url)
        params = dict(parse_qsl(url.query))
        if url.hostname != "predict.fixture" or route.request.method != "GET":
            unexpected.append((url.hostname, route.request.method))
            route.abort()
        elif url.path == "/api/comparison-current":
            reads.append(params)
            route.fulfill(
                json={
                    "schema": "predict-pregame-board-1",
                    "state": "valuation_pending"
                    if params.get("unit_usd")
                    else "unit_needed",
                    "rows": [],
                    "selected_usd": params.get("unit_usd"),
                }
            )
        elif url.path.startswith("/api/odds-replay"):
            replay = load(params, details=url.path.endswith("/details"))
            assert replay["provider_requests"] == 0
            route.fulfill(json=replay)
        elif url.path.startswith("/api/admin/"):
            if urlparse(route.request.frame.url).path == "/admin":
                route.fulfill(json={"data_runtime": {"healthy": False}})
            else:
                unexpected.append(("public Admin read", route.request.url))
                route.fulfill(
                    status=401, headers={"WWW-Authenticate": 'Basic realm="Admin"'}
                )
        elif url.path in ("/", "/ev", "/arbs", "/replay", "/admin"):
            route.fulfill(
                path=ASSETS / ("admin.html" if url.path == "/admin" else "desk.html")
            )
        elif url.path.startswith(("/view/current/", "/current/assets/")):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        with browser.new_context(
            viewport={"width": width, "height": 950}, timezone_id="America/Los_Angeles"
        ) as context:
            context.route("**/*", respond)
            tab = context.new_page()
            tab.set_default_timeout(6000)
            errors = []
            tab.on("pageerror", lambda error: errors.append(str(error)))
            first_use(tab, base, tmp_path)
            practice_journey(tab, base)
            expect(tab.get_by_label("Unit size")).to_have_value("19.37")
            if width == 390:
                tab.add_style_tag(
                    content="html { font-size: 200%; } .desk-app { font-size: .9375rem; }"
                )
                nav = tab.get_by_role("navigation", name="Predict", exact=True)
                assert nav.get_by_role("link", name="Opportunities").evaluate("""link => {
                    const text = document.createRange();
                    text.selectNodeContents(link);
                    return text.getClientRects().length === 1;
                }""")
                assert tab.evaluate(
                    "document.documentElement.scrollWidth === innerWidth"
                )
            assert reads and all("timezone" not in params for params in reads)
            assert not errors, errors
        browser.close()
    assert not unexpected, unexpected
