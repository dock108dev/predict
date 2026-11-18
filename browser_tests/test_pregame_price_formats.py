"""Contract-market equivalents preserve quoted price and American comparison values."""

from pathlib import Path
from playwright.sync_api import sync_playwright

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


def test_contract_quote_formats_and_legacy_fallback():
    with sync_playwright() as p:
        browser = p.chromium.launch()
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
          return {poly:priceDisplay(row),after:priceDisplay(row,true),
                  kalshi:priceDisplay({...row,venue:'kalshi',display:{posted_odds:'+119'},raw:{posted_decimal:'2.19'}}),
                  sportsbook:priceDisplay({...row,venue:'novig'}),
                  missing:priceDisplay({...row,raw:{}})};
        }""")
        assert result["poly"] == dict(
            primary="2.26×", secondary="(+126)", price="44.25% price"
        )
        assert result["after"] == dict(primary="2.15×", secondary="(+115)", price="")
        assert result["kalshi"] == dict(
            primary="45.66¢", secondary="(+119)", price="2.19× payout"
        )
        assert result["sportsbook"]["primary"] == "+126"
        assert result["missing"]["primary"] == "+126"
        browser.close()
