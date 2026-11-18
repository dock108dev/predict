from copy import deepcopy
from fractions import Fraction as F

import pytest

from app.fees.engine import posted_fee
from app.fees.pricing import validate, select
from app.storage.store import stamp


def rule(venue="kalshi", **changes):
    formulas = {
        "kalshi": ("kalshi_taker", "0.07"),
        "polymarket_us": ("polymarket_taker", "0.095"),
        "novig": ("novig_pregame", "0"),
        "prophetx": ("prophetx_commission", "0.02"),
    }
    formula, rate = formulas[venue]
    return dict(
        id="fixture-" + venue,
        formula=formula,
        rate=rate,
        multiplier="1",
        balance_precision="0.01",
        quantity_step="1",
        league=None,
        effective_from="2026-11-17T00:00:00Z",
        effective_to=None,
        source_url="https://example.com/fixture-fees",
        profile="conservative_public",
        **changes,
    )


@pytest.mark.parametrize(
    "venue,quantity,expected",
    [
        ("kalshi", "100", "1.75"),
        ("kalshi", "1", "0.02"),
        ("polymarket_us", "100", "2.38"),
        ("polymarket_us", "60", "1.42"),
        ("polymarket_us", "20", "0.48"),
        ("novig", "100", "0"),
    ],
)
def test_published_midpoint_fees_and_rounding(venue, quantity, expected):
    q = F(quantity)
    entry, settlement, _ = posted_fee(
        rule(venue), price=F("0.5"), quantity=q, stake=q / 2
    )
    assert entry == F(expected)
    assert settlement == 0


def test_winning_commission_and_nhl_use_different_cashflows():
    entry, win, _ = posted_fee(
        rule("prophetx"), price=F(25, 51), quantity=F(204), stake=F(100)
    )
    assert entry == 0 and win == F("2.08")
    nhl = dict(
        rule("prophetx"), formula="prophetx_nhl_taker", rate="0.035", league="NHL"
    )
    entry, win, _ = posted_fee(nhl, price=F("0.5"), quantity=F(100), stake=F(50))
    assert entry == F("0.88") and win == 0


def test_effective_rules_and_league_override_are_explicit():
    base = rule()
    mlb = dict(base, id="MLB", league="MLB", multiplier="0.5")
    rules = {"kalshi": validate([base, mlb], "kalshi")}
    assert select(rules, "kalshi", "MLB", stamp("2026-11-17T12:00:00Z")) == mlb
    assert select(rules, "kalshi", "NBA", stamp("2026-11-17T12:00:00Z")) == base
    assert select(rules, "kalshi", "NBA", stamp("2026-11-16T12:00:00Z")) is None
    with pytest.raises(ValueError, match="overlapping"):
        validate([base, dict(base, id="second")], "kalshi")


@pytest.mark.parametrize(
    "field,value",
    [
        ("rate", "-0.1"),
        ("rate", "1.1"),
        ("rate", 0.07),
        ("rate", "1e99999999"),
        ("quantity_step", "0"),
        ("balance_precision", "0.1"),
        ("profile", "guess"),
    ],
)
def test_bad_edits_are_rejected(field, value):
    candidate = deepcopy(rule())
    candidate[field] = value
    with pytest.raises((ValueError, ArithmeticError)):
        validate([candidate], "kalshi")


@pytest.mark.parametrize("price", ["0.001", "0.999"])
def test_polymarket_fee_price_scope_is_preserved(price):
    with pytest.raises(ValueError, match="polymarket_fee_price_scope"):
        posted_fee(rule("polymarket_us"), price=F(price), quantity=F(1), stake=F(price))


def test_native_polymarket_product_and_grid_are_checked_with_configured_rules():
    from app.comparison.snapshot_fee_scope import applicability
    from app.fees.pricing import outcome
    from tests.test_f05_polymarket_public import native, AT

    row = native("scheduled", "Long")
    row.update(
        captured_at=AT.isoformat(),
        fee_applicability=applicability(row["original_record"]),
    )
    assert outcome(row, rule("polymarket_us"))["available"]
    bad = deepcopy(row)
    bad["market"]["market"] = "total"
    with pytest.raises(ValueError, match="product_scope"):
        outcome(bad, rule("polymarket_us"))
    bad = deepcopy(row)
    bad["fee_applicability"]["retail"]["values"]["minimumTradeQty"] = "0"
    with pytest.raises(ValueError, match="quantity_or_price_grid"):
        outcome(bad, rule("polymarket_us"))


@pytest.mark.parametrize('venue', ['kalshi', 'polymarket_us', 'novig', 'prophetx'])
@pytest.mark.parametrize('cost', ['0.01', '0.5', '0.99', '7/19', '100/237'])
def test_posted_rounding_envelope_matches_existing_maximum_legal_size(venue, cost):
    from app.comparison.current_pregame import posted_fill
    from app.comparison.pregame_valuation import _fill
    from app.fees.pricing import order

    cost = F(cost)
    configured = dict(rule(venue), quantity_step='0.01')
    variants = [configured]
    if venue == 'kalshi':
        variants.append(dict(configured, balance_precision='0.0001', multiplier='0.5'))
    if venue == 'novig':
        variants.append(dict(configured, rate='0.07'))
    if venue == 'prophetx':
        variants.append(dict(configured, formula='prophetx_nhl_taker', rate='0.035'))
    for fee_rule in variants:
        stake = fee_rule['formula'] == 'prophetx_commission'
        terms = dict(kind='stake' if stake else 'exchange', increment='0.01', minimum='0.01',
                     maximum='100' if stake else None, order_type='straight_stake' if stake else 'taker',
                     asks=[dict(price=str(cost), quantity=str(100 / cost))], revision='authored-grid')
        fees, _, _ = order({}, fee_rule, cost, terms)
        expected, _ = _fill(terms, F(100), cost, fees, F(1))
        actual, _ = posted_fill(terms, F(100), cost, fees, fee_rule)
        assert actual == expected
