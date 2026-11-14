"""Exercise the credential-free desk journey against authored replay inputs."""

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pytest

from app.dashboard.replay_api import load
from app.storage import odds_replay

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


def first_use(tab, base):
    from playwright.sync_api import expect

    tab.goto(base + "/")
    expect(tab.get_by_role("heading", name="Opportunities")).to_be_visible()
    expect(
        tab.get_by_role("heading", name="Price updates are temporarily unavailable")
    ).to_be_visible()
    expect(tab.get_by_role("link", name="Arbitrage")).to_be_visible()
    expect(tab.get_by_role("button", name="Retry price updates")).to_be_visible()
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
    tab.get_by_label("Calculation basis").select_option("conservative")
    tab.reload()
    expect(tab.get_by_label("Calculation basis")).to_have_value("conservative")
    tab.get_by_role("link", name="Open replay").click()
    expect(
        tab.get_by_text("Synthetic practice · fictional prices and inputs")
    ).to_be_visible()
    expect(tab.get_by_label("Calculation basis")).to_have_value("before")
    expect(tab.get_by_label("Odds format")).to_have_value("decimal")
    expect(tab.locator("#notice")).to_contain_text("UTC")
    search = tab.get_by_role("searchbox", name="Search teams")
    search.fill("no such team")
    expect(
        tab.get_by_role("heading", name="No offers match these filters")
    ).to_be_visible()
    search.fill("Harbor Foxes")
    offer = tab.locator('[data-offer-id="practice-offer-0"]')
    expect(offer).to_contain_text("2.20")
    offer.press("Enter")
    trade = tab.get_by_role("dialog", name="Novig · Harbor Foxes to win")
    expect(trade).to_contain_text("Original price")
    expect(trade).to_contain_text("Fictional trading fee")
    expect(trade).to_contain_text("1.00% of the acquisition cost")
    expect(trade).not_to_contain_text("undefined")
    expect(trade).to_contain_text("returns $22.00 total, including $12.00 profit")
    expect(trade.get_by_role("button", name="Use latest prices")).to_be_hidden()
    tab.keyboard.press("Escape")
    expect(offer).to_be_focused()

    tab.get_by_label("Calculation basis").select_option(label="EV after fictional fees")
    expect(offer).to_contain_text("+8.91% EV")
    tab.get_by_role("link", name="Open game ↗").first.click()
    tab.get_by_role("button", name="Spreads", exact=True).click()
    expect(tab.locator('[data-offer-id="practice-offer-spread-1"]')).to_contain_text(
        "1.91"
    )
    tab.get_by_label("Price step").select_option("changed")
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
    tab.get_by_label("Price step").select_option("initial")

    tab.get_by_role("navigation", name="Replay views").get_by_role(
        "link", name="Arbitrage"
    ).click()
    inspect = tab.get_by_role("button", name="View payoff calculation ↗").first
    inspect.press("Enter")
    pair = tab.get_by_role("dialog", name="Arbitrage calculation")
    expect(pair).to_contain_text("Harbor Foxes")
    expect(pair).to_contain_text("Summit Owls")
    expect(pair).to_contain_text("Worst modeled profit/loss")
    expect(pair).to_contain_text("-$4.097")
    expect(pair).to_contain_text("Lowest payout")
    expect(pair).to_contain_text("$97.46")
    expect(inspect.locator("xpath=ancestor::article")).not_to_contain_text(
        "Unavailable on"
    )
    pair.get_by_role("button", name="Inspect offer and fees").first.click()
    expect(trade).to_contain_text(
        "Fictional fee for this pairing · $0.443 at fill on $44.30"
    )
    trade.get_by_role("button", name="Back to pairing").click()
    tab.keyboard.press("Escape")
    expect(inspect).to_be_focused()

    amount = tab.get_by_label("Total stake before fees ($)")
    assert amount.evaluate("""input => {
      input.value = '300';
      input.dispatchEvent(new Event('input', {bubbles:true}));
      return document.querySelector('[data-pair-id]').disabled;
    }""")
    expect(inspect).to_be_enabled()
    inspect.click()
    expect(pair).to_contain_text("Calculated for a $300.00 stake before fees")
    tab.keyboard.press("Escape")
    amount.fill("100")
    expect(inspect).to_be_enabled()

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
    tab.get_by_role("button", name="Clear return filters").press("Enter")
    expect(inspect).to_be_visible()
    filters.press("Enter")
    panel.get_by_label("ProphetX").uncheck()
    panel.get_by_role("button", name="Done").press("Enter")
    expect(
        tab.get_by_role("heading", name="No arbitrage calculations available")
    ).to_be_visible()
    tab.get_by_role("button", name="Clear Except ProphetX filter").press("Enter")
    expect(inspect).to_be_visible()
    tab.get_by_label("Price step").select_option("changed")
    expect(inspect).to_be_visible()
    expect(tab.locator(".desk-best").filter(has_text="2.10")).to_have_count(1)
    assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")

    tab.get_by_label("Dataset").select_option("frozen")
    expect(
        tab.get_by_role("heading", name="This saved capture is unavailable")
    ).to_be_visible()
    tab.get_by_role("link", name="Try synthetic practice").click()
    expect(
        tab.get_by_text("Synthetic practice · fictional prices and inputs")
    ).to_be_visible()
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
    from playwright.sync_api import sync_playwright

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
                    "state": "initializing",
                    "publication": {
                        "data_runtime": {"healthy": False},
                        "current_prices": 0,
                    },
                }
            )
        elif url.path.startswith("/api/odds-replay"):
            replay = load(params, details=url.path.endswith("/details"))
            assert replay["provider_requests"] == 0
            route.fulfill(json=replay)
        elif url.path == "/api/admin/status":
            route.fulfill(json={"data_runtime": {"healthy": False}})
        elif url.path in ("/", "/ev", "/replay", "/admin"):
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
            first_use(tab, base)
            assert reads[0]["timezone"] == "America/Los_Angeles"
            assert reads[-1]["timezone"] == "UTC"
            assert not errors, errors
        browser.close()
    assert not unexpected, unexpected
