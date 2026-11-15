"""Phone-size navigation through real desk pages and disposable API data."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from app.dashboard.browse_sessions import BrowseSessions
from app.dashboard.replay_api import load as replay_read
from app.dashboard.snapshot_api import page_options
from app.dashboard.trade_desk import page as desk_page
from app.storage import odds_replay
from tests.replay_fixture import write_archives
from tests.test_trade_desk import quote, result

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)
BASE = "https://predict.fixture"
AT = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


class CurrentSlate:
    def __init__(self):
        self.now = 0
        self.browse = BrowseSessions(clock=lambda: self.now)
        self.order = list(range(16))
        self.changed_line = None
        self.drop_token = False
        self.resets = []

    def read(self, query):
        rows, games = [], []
        live = query.get("phase") == "live"
        for position, number in enumerate(self.order):
            start = (
                AT + timedelta(minutes=(1 if not live else -20) + position)
            ).isoformat()
            key = f"detroit-{number}"
            title = f"Detroit vs. Example {number}"
            games.append(
                dict(
                    game_key=key,
                    title=title,
                    league="NBA",
                    start_at=start,
                    participants=[
                        dict(id="home", name="Detroit", role="home"),
                        dict(id="away", name=f"Example {number}", role="away"),
                    ],
                )
            )
            for mobile_venue in ("kalshi", "polymarket_us", "novig", "prophetx"):
                item = quote(f"{key}-{mobile_venue}", mobile_venue)
                if number == self.changed_line:
                    item["market"]["line"] = "3.5"
                    item["selection"]["signed_line"] = "-3.5"
                rows.append(
                    dict(
                        item,
                        game_key=key,
                        game_title=title,
                        start_at=start,
                        game_state="live" if live else "scheduled",
                        source_at=AT.isoformat(),
                        live_native_desk=True,
                    )
                )
        board = dict(
            result(*rows),
            games=games,
            captured_at=AT.isoformat(),
            publication=dict(
                read_at=AT.isoformat(), state="ready", current_prices=len(rows)
            ),
        )
        if self.drop_token:
            query.pop("browse_id", None)

        def enrich(out, **_):
            for row in out["rows"]:
                row["sportsbook_quotes"]["fanduel"] = [
                    dict(price_american="-110", current=True, source_at=AT.isoformat())
                ]

        response = desk_page(
            board, query, page_options(query), browsing=self.browse, enrich=enrich
        )
        response.update(features={"live_enabled": True}, phase=query.get("phase"))
        if response["state"] == "page_changed":
            self.resets.append(response["reason"])
        return response


def intercept(context, current):
    def fulfill(route):
        url = urlsplit(route.request.url)
        assert url.netloc == "predict.fixture"
        path, query = url.path, dict(parse_qsl(url.query, keep_blank_values=True))
        if path == "/api/comparison-current":
            route.fulfill(json=current.read(query))
        elif path == "/api/comparison-current/selection":
            route.fulfill(json={"row": None})
        elif path.startswith("/api/odds-replay"):
            route.fulfill(json=replay_read(query, details=path.endswith("/details")))
        elif path in ("/browse-odds", "/game", "/replay", "/ev"):
            route.fulfill(path=ASSETS / "desk.html")
        elif path.startswith("/view/current/") and (ASSETS / Path(path).name).is_file():
            route.fulfill(path=ASSETS / Path(path).name)
        else:
            route.fulfill(status=404)

    context.route("**/*", fulfill)


def position(card):
    return card.evaluate(
        'card => [scrollY, card.querySelector(".odds-scroll").scrollLeft]'
    )


def inspect_and_return(tab, card, dismiss):
    from playwright.sync_api import expect

    scroll = card.locator(".odds-scroll")
    scroll.scroll_into_view_if_needed()
    scroll.evaluate("element => element.scrollLeft = 46")
    target = scroll.evaluate("""element => Array.from(element.querySelectorAll('[data-offer-id]'))
      .map(button => {
        const {x, y, width, height} = button.getBoundingClientRect();
        const left = x + width / 2, top = y + height / 2;
        return {id:button.dataset.offerId, left, top,
          visible:button.contains(document.elementFromPoint(left, top))};
      }).find(quote => quote.visible)""")
    assert target
    opener = card.locator(f'[data-offer-id="{target["id"]}"]')
    before = position(card)
    assert before[1] > 0
    tab.touchscreen.tap(target["left"], target["top"])
    drawer = tab.locator("#trade")
    expect(drawer).to_be_visible()
    if dismiss == "back":
        tab.go_back()
    else:
        drawer.get_by_role("button", name="Close", exact=True).tap()
    expect(drawer).to_be_hidden()
    expect(opener).to_be_focused()
    assert position(card) == before


def launch_game(tab, card, *, back="link"):
    from playwright.sync_api import expect

    if card.locator("details:not([open]) > summary").count():
        card.locator("details > summary").tap()
    scroll = card.locator(".odds-scroll")
    scroll.evaluate("element => element.scrollLeft = 90")
    opener = card.locator("[data-game-launcher]")
    opener.scroll_into_view_if_needed()
    before = position(card)
    assert before[1] > 0
    basis = tab.locator("[name=basis]").input_value()
    opener.tap()
    expect(tab.locator("#results [data-offer-id]").first).to_be_visible()
    assert tab.locator("[name=basis]").input_value() == basis
    if back == "fallback":
        # WebKit uses the session return record if a same-view referrer is hidden.
        tab.evaluate(
            "Object.defineProperty(document, 'referrer', {value:''});"
            "Object.defineProperty(window, 'navigation', {value:undefined});"
        )
    return before, basis


def return_from_game(tab, back):
    if back == "back":
        tab.go_back()
    else:
        tab.locator("#desk-path").get_by_role("link", name="Back", exact=True).tap()


def swipe_chromium(context, tab, card):
    scroll = card.locator(".odds-scroll")
    scroll.scroll_into_view_if_needed()
    rect = scroll.bounding_box()
    direction = context.new_cdp_session(tab)
    y, x = rect["y"] + 25, rect["x"] + 300
    direction.send(
        "Input.dispatchTouchEvent",
        dict(type="touchStart", touchPoints=[dict(x=x, y=y)]),
    )
    for step in range(1, 9):
        direction.send(
            "Input.dispatchTouchEvent",
            dict(type="touchMove", touchPoints=[dict(x=x - 21 * step, y=y)]),
        )
    direction.send("Input.dispatchTouchEvent", dict(type="touchEnd", touchPoints=[]))
    tab.wait_for_function('document.querySelector(".odds-scroll").scrollLeft > 80')
    direction.detach()


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
def test_phone_comparison_return(engine, tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    write_archives(tmp_path)
    monkeypatch.setattr(odds_replay, "DIRECTORY", tmp_path)
    with sync_playwright() as playwright:
        browser_type = getattr(playwright, engine)
        if engine == "webkit" and not Path(browser_type.executable_path).exists():
            pytest.skip(
                "Install the optional WebKit browser to exercise Safari navigation locally"
            )
        browser = browser_type.launch(
            **(
                {"executable_path": os.environ["PREDICT_CI_CHROMIUM"]}
                if engine == "chromium" and os.getenv("PREDICT_CI_CHROMIUM")
                else {}
            )
        )
        context = browser.new_context(
            viewport={"width": 390, "height": 844}, has_touch=True
        )
        current = CurrentSlate()
        intercept(context, current)
        tab = context.new_page()
        errors = []
        tab.on("pageerror", lambda error: errors.append(str(error)))
        tab.goto(f"{BASE}/browse-odds?search=Detroit&family=spread&basis=reviewed")
        first = tab.locator('[data-game-key="detroit-0"]')
        expect(first).to_be_visible()
        assert tab.evaluate("document.documentElement.scrollWidth === innerWidth")
        expect(tab.locator("#phase-pregame")).to_have_attribute("aria-current", "page")
        expect(tab.locator("#page-range")).to_have_text("1–12 of 16 games")
        expect(tab.locator(".odds-card")).to_have_count(12)
        expect(tab.locator(".odds-matrix")).to_have_count(1)
        if engine == "chromium":
            swipe_chromium(context, tab, first)
        first.locator(".matrix-scroll-cue").tap()
        sportsbook = first.get_by_role(
            "button", name="Sportsbook prices for", exact=False
        )
        sportsbook.tap()
        expect(first.locator(".matrix-sportsbook-popout")).to_be_visible()
        tab.keyboard.press("Escape")
        expect(first.locator(".matrix-sportsbook-popout")).to_be_hidden()
        inspect_and_return(tab, first, "close")
        inspect_and_return(tab, first, "back")

        tab.locator("#next").tap()
        target = tab.locator('[data-game-key="detroit-12"]')
        expect(target).to_be_visible()
        expect(tab.locator("#page-range")).to_have_text("13–16 of 16 games")
        initial_position, basis = launch_game(tab, target, back="fallback")
        return_from_game(tab, "fallback")
        expect(target.locator("[data-game-launcher]")).to_be_focused()
        assert position(target) == initial_position
        assert tab.locator("[name=basis]").input_value() == basis

        launch_game(tab, target)
        current.changed_line = 12
        return_from_game(tab, "link")
        expect(target.locator("[data-game-launcher]")).to_be_focused()
        expect(tab.locator("#notice")).to_contain_text(
            "The previous line left these results"
        )
        expect(target.locator("th[scope=row]")).to_contain_text("-3.5")

        launch_game(tab, target)
        current.now = 901
        current.order = [12, *range(12), 13, 14, 15]
        return_from_game(tab, "back")
        expect(target.locator("[data-game-launcher]")).to_be_focused()
        expect(tab.locator("#previous")).to_be_disabled()
        assert "expired" in current.resets[-1]

        tab.locator("#next").tap()
        removed = tab.locator('[data-game-key="detroit-13"]')
        expect(removed).to_be_visible()
        launch_game(tab, removed)
        current.order.remove(13)
        current.drop_token = True
        return_from_game(tab, "link")
        expect(tab.locator("#notice")).to_contain_text("no longer in these results")
        expect(removed).to_have_count(0)
        expect(tab.locator("[data-game-launcher]:focus")).to_have_count(1)
        expect(tab.locator("[name=search]")).to_have_value("Detroit")
        assert "missing" in current.resets[-1]

        tab.locator("#phase-live").tap()
        expect(tab.locator("#phase-live")).to_have_attribute("aria-current", "page")
        inspect_and_return(tab, target, "back")

        tab.goto(
            f"{BASE}/replay?view=odds&dataset=preview&search=Harbor&family=spread&basis=before"
        )
        practice = tab.locator('[data-game-key="practice-game"]')
        expect(practice.get_by_text("Harbor Foxes vs. Summit Owls")).to_be_visible()
        inspect_and_return(tab, practice, "back")
        initial_position, basis = launch_game(tab, practice, back="fallback")
        return_from_game(tab, "fallback")
        expect(practice.locator("[data-game-launcher]")).to_be_focused()
        assert position(practice) == initial_position
        expect(tab.locator("[name=basis]")).to_have_value(basis)
        expect(tab.locator("#replay-dataset")).to_have_value("preview")

        tab.goto(f"{BASE}/replay?view=ev&dataset=frozen")
        basis_control = tab.locator("[name=basis]")
        basis_control.select_option("reviewed")
        reviewed_result = tab.locator('[data-offer-id="practice-offer-0"]')
        expect(reviewed_result).not_to_contain_text("+10.00%")
        reviewed_result.locator("xpath=ancestor::article").locator(
            "[data-game-launcher]"
        ).tap()
        expect(basis_control).to_have_value("reviewed")
        expect(reviewed_result).not_to_contain_text("+10.00%")
        return_from_game(tab, "link")
        expect(basis_control).to_have_value("reviewed")
        expect(reviewed_result).not_to_contain_text("+10.00%")

        tab.goto(f"{BASE}/replay?view=arbs&dataset=preview")
        payoff = tab.locator("[data-pair-id]").first
        payoff.tap()
        drawer = tab.locator("#trade")
        body = drawer.locator("#trade-body")
        leg = drawer.get_by_role("button", name="Inspect offer and fees").last
        expect(leg).to_be_visible()
        drawer.get_by_text(
            "Exact prices, settlement terms and fee rounding", exact=True
        ).tap()
        parent = body.inner_text()
        for dismiss in ("close", "back", "pair link"):
            drawer.evaluate("element => { element.scrollTop = 48; }")
            leg.scroll_into_view_if_needed()
            leg_scroll = drawer.evaluate("element => element.scrollTop")
            assert leg_scroll > 0
            leg.tap()
            expect(drawer.locator("#back-to-pair")).to_be_visible()
            if dismiss == "back":
                tab.go_back()
            elif dismiss == "pair link":
                drawer.locator("#back-to-pair").tap()
            else:
                drawer.get_by_role("button", name="Close", exact=True).tap()
            expect(leg).to_be_focused()
            assert body.inner_text() == parent
            assert drawer.evaluate("element => element.scrollTop") == leg_scroll
        drawer.get_by_role("button", name="Close", exact=True).tap()
        expect(drawer).to_be_hidden()
        expect(payoff).to_be_focused()
        assert not errors
        browser.close()
