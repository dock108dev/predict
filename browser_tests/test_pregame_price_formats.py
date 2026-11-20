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
            name = Path(urlparse(route.request.url).path).name
            if name in ("pregame-prices.js", "bet-journal-defaults.js"):
                route.fulfill(path=ASSETS / name)
            else:
                route.fulfill(content_type="text/html", body="<html></html>")

        page.route("https://predict.fixture/**", serve)
        page.goto("https://predict.fixture/")
        result = page.evaluate("""async()=>{
          const {priceDisplay}=await import('/pregame-prices.js');
          const {suggestedTrades}=await import('/bet-journal-defaults.js');
          const row={venue:'polymarket_us',display:{posted_odds:'+126',after_fees:'+115'},raw:{posted_decimal:'2.26',after_fee_decimal:'2.1468'}};
          // Historical saved terms, not an assertion about today's fee schedule:
          // NCAAF $100 posted +495, $9.90 winning commission => $585.10 receipt.
          // NHL +109, entry fee $0.92, committed 267307/5225 => $105 receipt.
          const commission={id:'saved-commission',venue:'prophetx',posted:{value:'+495',units:'american_odds'},
            raw:{posted_decimal:'5.95',after_fee_decimal:'5.851'},display:{posted_odds:'+495',after_fees:'+485'}};
          const nhl={id:'saved-nhl',venue:'prophetx',posted:{value:'+109',units:'american_odds'},
            raw:{posted_decimal:'2.09',after_fee_decimal:'548625/267307'},display:{posted_odds:'+109',after_fees:'+105'}};
          const before=JSON.stringify(row);
          return {
            unavailable:priceDisplay(row),after:priceDisplay(row,true),
            normalized:priceDisplay({...row,posted:{value:'+126',units:'american_odds'},source:{provider:'sportsgameodds'}}),
            native:priceDisplay({...row,posted:{value:'44.2500',units:'cents_per_contract'}}),
            probability:priceDisplay({...row,posted:{value:'0.4424778761061947',units:'probability'}}),
            decimal:priceDisplay({...row,posted:{value:'2.2600',units:'decimal_odds'}}),
            originalText:priceDisplay({...row,native_price:{text:'43.4800%',format:'percent',value:'43.4800',source_units:'percent'}}),
            american:priceDisplay(commission),missingAfter:priceDisplay({...row,display:{posted_odds:'+126'}},true),
            suggestedCommission:suggestedTrades({kind:'ev',snapshot:commission}),
            suggestedNhl:suggestedTrades({kind:'ev',snapshot:nhl}),unchanged:JSON.stringify(row)===before};
        }""")
        assert result["unavailable"] == dict(
            primary="+126", secondary="", price="Native format unavailable"
        )
        assert result["normalized"] == result["unavailable"]
        assert result["native"] == dict(
            primary="44.2500¢", secondary="(+126)", price=""
        )
        assert result["probability"]["primary"] == "44.24778761061947%"
        assert result["decimal"] == dict(
            primary="2.2600×", secondary="(+126)", price=""
        )
        assert result["originalText"] == dict(
            primary="43.4800%", secondary="(+126)", price=""
        )
        assert result["american"] == dict(primary="+495", secondary="", price="")
        assert result["after"] == dict(primary="+115", secondary="", price="")
        assert result["missingAfter"]["primary"] == "Unavailable"
        assert result["suggestedCommission"] == [
            dict(
                quote_id="saved-commission",
                stake="100",
                price="+495",
                units="american_odds",
            )
        ]
        assert result["suggestedNhl"] == [
            dict(quote_id="saved-nhl", stake="100", price="+109", units="american_odds")
        ]
        assert result["unchanged"]
        browser.close()


@pytest.mark.parametrize("venue", ["novig", "prophetx"])
@pytest.mark.parametrize("width", [1280, 390])
def test_percentage_and_american_on_boards_and_comparisons(venue, width, tmp_path):
    """The shared formatter reaches the shipped list, game and arb renderers."""
    from playwright.sync_api import expect
    from browser_tests.test_pregame_current import offer
    from browser_tests.test_pregame_arb_recovery import pair_fixture

    selected = offer()
    selected.update(
        venue=venue, side="home", posted=dict(value="+126", units="american_odds")
    )
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
        expect(posted.locator(".math-trigger")).to_have_text("+126")
        expect(posted.locator(".price-equivalent")).to_have_text(
            "Native format unavailable"
        )
        expect(after.locator(".math-trigger")).to_have_text("+115")
        expect(after.locator(".american-equivalent")).to_have_count(0)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv("PREDICT_CI_CHROMIUM"))
        page = browser.new_page(viewport=dict(width=width, height=900))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("https://predict.fixture/**", serve)

        page.goto("https://predict.fixture/")
        prices(page.locator(".ticket .posted"), page.locator(".ticket .after"))
        page.screenshot(path=str(evidence / f"{venue}-opportunities{suffix}.png"))
        page.locator(".row-open").click()
        expect(page.locator(".comparison-status")).to_contain_text(
            "complete for this stored snapshot"
        )
        exchange = page.locator("#comparison .exchange-prices tbody tr").first
        prices(exchange.locator("td").nth(1), exchange.locator("td").nth(2))
        page.screenshot(path=str(evidence / f"{venue}-comparison{suffix}.png"))

        page.goto("https://predict.fixture/browse-odds")
        values = page.locator(".game-card .line-values > div")
        prices(values.nth(0), values.nth(1))
        page.screenshot(path=str(evidence / f"{venue}-browse{suffix}.png"))

        page.goto("https://predict.fixture/arbs")
        columns = page.locator(".arb-leg").first.locator(".arb-price-column")
        prices(columns.nth(0), columns.nth(1))
        page.locator(".arb-open").click()
        columns = page.locator("#arb-content .arb-leg").first.locator(
            ".arb-price-column"
        )
        prices(columns.nth(0), columns.nth(1))
        page.screenshot(path=str(evidence / f"{venue}-arbitrage{suffix}.png"))
        assert not errors, errors
        browser.close()
