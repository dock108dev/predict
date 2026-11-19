"""Cashflow evidence distinguishes one acquisition fee from outcome totals."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)


def test_payout_fee_and_original_age_evidence():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()

        def serve(route):
            name = route.request.url.rsplit("/", 1)[-1]
            if name.endswith(".js"):
                route.fulfill(path=ASSETS / name)
            else:
                route.fulfill(content_type="text/html", body="<main></main>")

        page.route("https://predict.fixture/**", serve)
        page.goto("https://predict.fixture/")
        result = page.evaluate("""async()=>{
          const {feeRows,payoutExample,freshnessText,freshness}=await import('/pregame-evidence.js');
          const {explanation}=await import('/pregame-math.js');
          const row={venue:'kalshi',source:{provider:'kalshi'},
            times:{source_at:'2026-11-18T12:00:00Z',received_at:'2026-11-18T12:00:02Z'},
            calculated_at:'2026-11-18T13:00:00Z',
            fee:{committed_usd:'106.35',entry_usd:'6.35',reserve_usd:'0',cashflows:{
              win:{total_fee_usd:'6.35',settlement_fee_usd:'0',net_receipt_usd:'299'},
              loss:{total_fee_usd:'6.35',settlement_fee_usd:'0',net_receipt_usd:'0'}}},
            reference:{probability:'0.5',prices:[{source_at:'2026-11-18T11:00:00Z'}]},
            raw:{net_ev:'0.1'},display:{net_ev:'+10%'}};
          const plain=structuredClone(row);plain.fee.committed_usd='100';plain.fee.entry_usd='0';
          const missing={...row,reference:null,ev_unavailable_reason:'reference_two_trusted_books_required'};
          return {fees:Object.fromEntries(feeRows(row)),payout:payoutExample(row).textContent,
            plain:payoutExample(plain).textContent,
            age:freshnessText(row,Date.parse('2026-11-18T13:01:00Z')),
            recalculated:freshnessText({...row,calculated_at:'2026-11-18T13:01:00Z'},Date.parse('2026-11-18T13:01:00Z')),
            unknown:freshnessText({...row,times:{source_at:null}},Date.parse('2026-11-18T13:01:00Z')),
            missing:payoutExample(missing).textContent,ev:explanation(missing,'ev'),ageTag:freshness(row).tagName,ageCaution:freshness(row).dataset.caution??null};
        }""")
        assert result["fees"]["Stake / purchase amount"] == "$100.00"
        assert result["fees"]["Total upfront cash committed"] == "$106.35"
        for outcome in ("Winning", "Losing"):
            assert result["fees"][outcome + " additional settlement charge"] == "$0.00"
            assert (
                result["fees"][outcome + " total fees (includes acquisition fee)"]
                == "$6.35"
            )
        assert "$299.00 total returned" in result["payout"]
        assert "$192.65 net profit" in result["payout"]
        assert (
            "$100.00 stake / purchase → $100.00 committed upfront → $299.00 total returned"
            in result["plain"]
        )
        assert "$199.00 net profit" in result["plain"]
        assert result["age"] == result["recalculated"]
        assert "Quote 1h 1m ago" in result["age"]
        assert "Reference 2h 1m ago" in result["age"]
        assert "Historical inputs" not in result["age"]
        assert result["ageTag"] == "SPAN"
        assert result["ageCaution"] is None
        assert "Quote age unknown" in result["unknown"]
        assert "Freshness unverified" not in result["unknown"]
        assert (
            "EV unavailable: reference two trusted books required" in result["missing"]
        )
        assert result["ev"][0] == "EV unavailable"
        browser.close()
