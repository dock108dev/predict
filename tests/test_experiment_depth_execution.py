from fractions import Fraction as F

import pytest

from app.comparison import scanner_kalshi
from app.comparison.experiment_depth_execution import evaluate, needs_book
from tests.test_paper_experiments import frozen_priced
from tests.test_scanner_kalshi import AT as KALSHI_AT, inputs as kalshi_inputs


AT = "2026-11-27T23:50:00Z"


def levels(*rows):
    return [dict(price=str(price), quantity=str(quantity), **(
        {"orders": list(map(str, orders))} if orders else {})) for price, quantity, *orders in rows]


def receipt(*rows, complete=True, coefficient="0", reason=None):
    return dict(venue="novig", event_id="event", market_id="market", outcome_id="side",
        opposite_outcome_id="opposite", receipt_id="immutable-id", complete=complete, reason=reason,
        payout_usd="1/100", quantity_increment="1", levels=levels(*rows),
        fee=dict(model="novig_v3", coefficient=coefficient, round_usd="1/100000",
                 reason=None if coefficient is not None else "fee_cutover_unverified"))


def price(observed, *, odds="+300", ev=".05", minimum=".04", target=25):
    offer = frozen_priced(odds, venue="novig", ev=ev)
    return evaluate(offer, observed, at=AT, game_key="g", target=target, minimum=minimum)


def test_native_contract_size_compares_pennies_of_payout_not_winning_dollars():
    disposition, calculation = price(receipt(("0.25", 2000), complete=False))
    assert calculation is None
    assert disposition["status"] == "partial_size"
    assert disposition["available_native_quantity"] == "2000"
    assert disposition["available_purchase_usd"] == "5"
    assert disposition["available_gross_win_profit_usd"] == "15"
    assert not disposition["availability_is_lower_bound"]  # best ask equals the limit
    assert not needs_book(receipt(("0.25", 2000), complete=False), quote_price="0.25")


def test_multi_price_fill_and_immutable_receipt_witness():
    disposition, calculation = price(receipt(("0.20", 1000, 150, 850), ("0.25", 3000, 1000, 2000)))
    assert disposition["status"] == "full_size" and disposition["eligible"]
    assert disposition["receipt_id"] == "immutable-id"
    assert disposition["available_native_quantity"] == "4000"
    assert disposition["modeled_native_quantity"] == "3267"
    assert disposition["modeled_purchase_usd"] == "7.6675"
    assert disposition["modeled_win_profit_usd"] == "25.0025"
    assert [fill["native_quantity"] for fill in disposition["modeled_fills"]] == ["150", "850", "1000", "1267"]
    assert F(calculation["raw"]["net_ev"]) == F(disposition["modeled_net_ev"])
    assert F(calculation["fee"]["cashflows"]["win"]["net_receipt_usd"]) == F("32.67")
    assert F(calculation["fee"]["cashflows"]["loss"]["net_profit_usd"]) == -F("7.6675")


@pytest.mark.parametrize("observed,status,reason", [
    (None, "unknown", "no_decision_receipt"),
    (receipt(reason="stale"), "unknown", "stale"),
    (receipt(reason="later_receipt"), "unknown", "later_receipt"),
    (receipt(reason="throttled"), "unknown", "throttled"),
    (receipt(), "confirmed_empty", None),
    (receipt(("0.255", 3000)), "above_limit", None),
    (receipt(("0.24", 2000), complete=False), "unknown", "truncated"),
    (receipt(("0.25", 5000), coefficient=None), "unknown", "fee_cutover_unverified"),
])
def test_unknown_empty_and_price_proofs_are_distinct(observed, status, reason):
    disposition, calculation = price(observed)
    assert disposition["status"] == status
    assert disposition["reason"] == reason
    assert not disposition["eligible"] and calculation is None


def test_conservative_tick_does_not_round_towards_a_worse_price():
    disposition, _ = price(receipt(("0.29", 12000)), odds="+246")
    assert F(disposition["quoted_price"]) == F(100, 346)
    assert disposition["limit_price"] == "0.285"
    assert disposition["status"] == "above_limit"


def test_fee_ceils_per_maker_and_can_change_ev_qualification():
    # One-unit fills each cost $0.00006 at .25 and coefficient .03.
    exact, _ = price(receipt(("0.25", 5000, 1, 1, 4998), coefficient=".03"), ev=".063501")
    assert [fill["fee_usd"] for fill in exact["modeled_fills"][:2]] == ["0.00006", "0.00006"]
    assert exact["modeled_fee_usd"] == "0.18896"
    assert exact["status"] == "full_size" and exact["eligible"]

    aggregated = receipt(("0.25", 5000), coefficient=".03")
    ambiguous, calculation = price(aggregated, ev=".063501")
    assert ambiguous["reason"] == "fee_rounding_ambiguous"
    assert ambiguous["status"] == "unknown" and calculation is None
    assert needs_book(aggregated, quote_price=F(1, 4), minimum=F(4, 100), probability=F(".26587525"))

    below, calculation = price(aggregated, ev=".05")
    assert below["status"] == "full_size" and below["reason"] == "net_ev_below_minimum"
    assert below["fee_is_upper_bound"] and not below["eligible"] and calculation is None


def test_nearest_size_allows_the_lower_native_increment_and_ties_take_lower_cost():
    book = receipt(("0.25", 4))
    higher, _ = price(book, target=F(".030"))
    assert higher["status"] == "full_size"
    assert higher["modeled_native_quantity"] == "4"
    assert higher["modeled_win_profit_usd"] == "0.03"

    disposition, calculation = price(book, target=F(".02625"))
    assert disposition["status"] == "full_size" and calculation is not None
    assert disposition["modeled_native_quantity"] == "3"
    assert disposition["modeled_win_profit_usd"] == "0.0225"


def test_capped_book_retains_observed_capacity_lower_bound():
    observed = receipt(("0.2", 1000), complete=False)
    disposition, calculation = price(observed)
    assert disposition["status"] == "unknown" and calculation is None
    assert disposition["availability_is_lower_bound"]
    assert disposition["available_native_quantity"] == "1000"
    assert needs_book(observed, quote_price=F("0.25"))


@pytest.mark.parametrize("reason", ["timeout", "throttled", "stale", "older_book_top_conflict"])
def test_failed_detail_preserves_only_explicitly_qualified_catalog_capacity(reason):
    observed = receipt(("0.2", 1000), complete=False, reason=reason)
    unavailable, calculation = price(observed)
    assert unavailable["status"] == "unknown" and calculation is None
    assert "available_native_quantity" not in unavailable

    admitted, calculation = price(dict(observed, catalog_lower_bound=True))
    assert admitted["status"] == "unknown" and not admitted["eligible"] and calculation is None
    assert admitted["reason"] == reason
    assert admitted["availability_is_lower_bound"]
    assert admitted["available_native_quantity"] == "1000"
    assert admitted["available_purchase_usd"] == "2"


def test_polymarket_uses_native_contract_quantity_and_rounded_fee_across_prices():
    offer = frozen_priced("+300", venue="polymarket_us", ev=".12")
    book = dict(receipt(("0.2", 5), ("0.25", 100)), venue="polymarket_us", payout_usd="1",
                quantity_increment=".01", price_bands=[[".01", ".99", ".01"]],
                fee=dict(model="polymarket_us_standard_taker_bound", coefficient=".095"))
    disposition, calculation = evaluate(offer, book, at=AT, game_key="g", target=25, minimum=".04")
    assert disposition["status"] == "full_size" and disposition["eligible"]
    assert disposition["modeled_native_quantity"] == "33.79"
    assert disposition["modeled_purchase_usd"] == "8.1975"
    assert disposition["modeled_fee_usd"] == "0.59"
    assert F(calculation["fee"]["cashflows"]["win"]["net_profit_usd"]) == F("25.0025")


def test_kalshi_prices_reviewed_schedule_on_whole_claims_and_reuses_cashflows():
    quote, evidence = kalshi_inputs()
    terms = scanner_kalshi.resolve(quote, evidence, at=KALSHI_AT)
    offer = frozen_priced("+100", venue="kalshi", ev=".12")
    book = dict(receipt(("0.48", 100)), venue="kalshi", payout_usd="1", quantity_increment="1",
                price_bands=terms["grid"]["price_ranges"],
                fee=dict(model="kalshi_direct_taker_bound", terms=terms["fee"]))
    disposition, calculation = evaluate(offer, book, at=KALSHI_AT, game_key="g", target=25, minimum=".04")
    assert disposition["status"] == "full_size" and disposition["eligible"]
    assert disposition["modeled_native_quantity"] == "50"
    assert disposition["modeled_purchase_usd"] == "24"
    expected_fee = scanner_kalshi.entry_fee(terms, [(F(50), F("0.48"))])
    assert F(disposition["modeled_fee_usd"]) == expected_fee == F("0.875")
    assert F(calculation["fee"]["cashflows"]["win"]["net_profit_usd"]) == F("25.125")
