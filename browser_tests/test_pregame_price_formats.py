"""Venue price formats preserve stored prices and calculation equivalents."""

from pathlib import Path
import os
from urllib.parse import parse_qs, urlparse
import pytest
from playwright.sync_api import sync_playwright

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


def test_contract_quote_formats_and_legacy_fallback():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page()

        def serve(route):
            if route.request.url.endswith("/pregame-prices.js"):
                route.fulfill(path=ASSETS / "pregame-prices.js")
            else:
                route.fulfill(content_type="text/html", body="<html></html>")

        page.route("https://predict.fixture/**", serve)
        page.goto("https://predict.fixture/")
        result = page.evaluate("""async()=>{
          const {priceDisplay}=await import('/pregame-prices.js');
          const row={venue:'polymarket_us',display:{posted_odds:'+126',after_fees:'+115'},raw:{posted_decimal:'2.26',after_fee_decimal:'2.1468'}};
          const before=JSON.stringify(row);
          const result={poly:priceDisplay(row),after:priceDisplay(row,true),
                  kalshi:priceDisplay({...row,venue:'kalshi',display:{posted_odds:'+119'},raw:{posted_decimal:'2.19'}}),
                  novig:priceDisplay({...row,venue:'novig'}),
                  prophetx:priceDisplay({...row,venue:'prophetx'}),
                  novigAfter:priceDisplay({...row,venue:'novig'},true),
                  prophetxAfter:priceDisplay({...row,venue:'prophetx'},true),
                  novigSlip:priceDisplay({...row,venue:'novig',raw:{posted_decimal:'200/101'}}),
                  prophetxSlip:priceDisplay({...row,venue:'prophetx',raw:{posted_decimal:'1250/649'}}),
                  sportsbook:priceDisplay({...row,venue:'fanduel'}),
                  missing:priceDisplay({...row,raw:{}})};
          return {...result,unchanged:JSON.stringify(row)===before};
        }""")
        assert result["poly"] == dict(
            primary="2.26×", secondary="(+126)", price="44.25% price"
        )
        assert result["after"] == dict(primary="2.15×", secondary="(+115)", price="")
        assert result["kalshi"] == dict(
            primary="45.66¢", secondary="(+119)", price="2.19× payout"
        )
        assert result["sportsbook"]["primary"] == "+126"
        assert result["novig"] == dict(primary="44.25%", secondary="+126", price="")
        assert result["novigAfter"] == dict(
            primary="46.58%", secondary="+115", price=""
        )
        assert result["prophetx"] == dict(
            primary="44.25%", secondary="", price="2.26× payout"
        )
        assert result["prophetxAfter"] == dict(
            primary="46.58%", secondary="", price="Effective price"
        )
        assert result["novigSlip"]["primary"] == "50.5%"
        assert result["prophetxSlip"]["primary"] == "51.92%"
        assert result["missing"]["primary"] == "+126"
        assert result["unchanged"]
        browser.close()


@pytest.mark.parametrize("width", [1280, 390])
def test_novig_percent_and_american_on_boards_and_comparisons(width, tmp_path):
    """The shared formatter reaches the shipped list, game and arb renderers."""
    from playwright.sync_api import expect
    from browser_tests.test_pregame_current import offer
    from browser_tests.test_pregame_arb_recovery import pair_fixture

    selected = offer()
    selected.update(venue="novig", side="home")
    selected["raw"].update(posted_decimal="2.26", after_fee_decimal="2.1468")
    selected["display"].update(posted_odds="+126", after_fees="+115")
    pair = pair_fixture()
    pair["legs"][0] = selected
    game = {key: selected[key] for key in ("game_key", "game", "league", "kickoff")}
    game["rows"] = [selected]
    evidence = Path(os.getenv("PREDICT_PRICE_FORMAT_EVIDENCE", str(tmp_path)))
    evidence.mkdir(parents=True, exist_ok=True)
    suffix = "" if width == 1280 else "-390"

    def serve(route):
        url = urlparse(route.request.url)
        query = parse_qs(url.query)
        if url.path.endswith("/updates"):
            route.fulfill(json=dict(changed=False))
        elif url.path == "/api/pregame/arbs":
            route.fulfill(json=dict(rows=[pair], total=1, cursor="format"))
        elif url.path == "/api/pregame":
            packet = dict(
                rows=[selected], total=1, cursor="format", data_type="monitor"
            )
            if query.get("view") == ["games"]:
                packet.update(rows=[], games=[game])
            route.fulfill(json=packet)
        elif url.path.startswith("/api/"):
            route.fulfill(status=401, json={})
        elif url.path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(url.path).name)
        else:
            route.fulfill(
                path=ASSETS
                / ("pregame-arbs.html" if url.path == "/arbs" else "pregame.html")
            )

    def prices(posted, after):
        for cell, primary, american in (
            (posted, "44.25%", "+126"),
            (after, "46.58%", "+115"),
        ):
            expect(cell.locator(".math-trigger")).to_have_text(primary)
            expect(cell.locator(".american-equivalent")).to_have_text(american)
            expect(cell.locator(".price-equivalent")).to_have_count(0)
            cell.locator(".math-trigger").scroll_into_view_if_needed()
            top = cell.locator(".math-trigger").bounding_box()
            bottom = cell.locator(".american-equivalent").bounding_box()
            assert bottom["y"] >= top["y"] + top["height"] - 1

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=900))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("https://predict.fixture/**", serve)

        page.goto("https://predict.fixture/")
        prices(page.locator(".ticket .posted"), page.locator(".ticket .after"))
        page.screenshot(path=str(evidence / f"novig-opportunities{suffix}.png"))
        page.locator(".row-open").click()
        expect(page.locator(".comparison-status")).to_contain_text(
            "complete for this stored snapshot"
        )
        exchange = page.locator("#comparison .exchange-prices tbody tr").first
        prices(exchange.locator("td").nth(1), exchange.locator("td").nth(2))
        page.screenshot(path=str(evidence / f"novig-comparison{suffix}.png"))

        page.goto("https://predict.fixture/browse-odds")
        values = page.locator(".game-card .line-values > div")
        prices(values.nth(0), values.nth(1))
        page.screenshot(path=str(evidence / f"novig-browse{suffix}.png"))

        page.goto("https://predict.fixture/arbs")
        columns = page.locator(".arb-leg").first.locator(".arb-price-column")
        prices(columns.nth(0), columns.nth(1))
        page.locator(".arb-open").click()
        columns = page.locator("#arb-content .arb-leg").first.locator(
            ".arb-price-column"
        )
        prices(columns.nth(0), columns.nth(1))
        page.screenshot(path=str(evidence / f"novig-arbitrage{suffix}.png"))
        assert not errors, errors
        browser.close()
