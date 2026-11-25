"""Grid-constrained paper profit targets over an immutable posted quote."""

from fractions import Fraction as F
from functools import lru_cache
from math import ceil, floor

from app.fees.engine import posted_fee_bounds

from . import current_pregame, fee_mode
from .cashflows import exact_wire as wire
from .pregame_valuation_fees import retail_order

RULE = "nearest-positive-net-win-lower-commitment-1"


def _grid(record, row, terms, cost, original):
    quote, source = record["quote"], row["source"]
    metadata = record.get("comparison_source_metadata") or {}
    if source["provider"] == quote["venue"] == "polymarket_us":
        from .snapshot_polymarket_fee import quantity_grid

        grid = quantity_grid(row)
        if grid is None:
            raise ValueError("fixed_profit_price_or_quantity_grid_unavailable")
        step, tick = F(grid["increment_contracts"]), F(grid["price_tick_usd"])
        if step <= 0 or tick <= 0 or cost % tick:
            raise ValueError("fixed_profit_price_or_quantity_grid_conflict")
        return step, tick, "captured_native_order_grid"
    if source["provider"] == quote["venue"] == "kalshi":
        from .scanner_kalshi import _market_grid

        observed = metadata.get("selected_market_observation") or {}
        grid, _ = _market_grid(quote, dict(selected_market_observation=observed,
                                          material_sha256=observed.get("material_sha256")))
        tick = min(step for start, end, step in (tuple(map(F, band)) for band in grid["price_ranges"])
                   if start <= cost <= end and not (cost - start) % step)
        return F(grid["increment"]), tick, "captured_native_order_grid"
    # Aggregate American prices are paper odds and may convert to recurring
    # implied USD claim prices. Preserve the frozen paper increment and odds.
    raw_step = original["fee"].get("quantity_increment")
    if raw_step is None or F(raw_step) <= 0:
        raise ValueError("fixed_profit_quantity_increment_unavailable")
    if "quantity" not in original["fee"] or ((original["fee"]["quantity"] is None) != (terms["kind"] == "stake")):
        raise ValueError("fixed_profit_quantity_unit_unavailable")
    return F(raw_step), None, "captured_paper_increment"


def _fee_model(row, terms, cost, fee):
    """Return the original fill pricer and a bound for the one-price fee curve."""
    if fee_mode.assumed_zero(fee):
        pricer, evidence, _ = fee_mode.zero_order(fee)
        return pricer, evidence, F(0), F(0)
    pricer, evidence, _ = retail_order(row, terms, cost, fee)
    if rule := (fee.get("evidence") or {}).get("database_fee_rule"):
        if rule["formula"] == "prophetx_commission":
            rate = F(rule["rate"]) * (1 - cost)
            return pricer, evidence, rate, F("0.01") if rate else F(0)
        return pricer, evidence, *posted_fee_bounds(rule, cost)
    if bounds := getattr(pricer, "win_fee_bounds", None):
        return pricer, evidence, *bounds()
    raise ValueError("fixed_profit_fee_rounding_unverified")


def _plateau_neighbors(quote_at, target, first, last, profit_per_tick):
    """Skip sub-cent quantity grids within one constant rounded-charge step."""
    def charge_at(ticks):
        return profit_per_tick * ticks - quote_at(ticks)[0]

    while first <= last:
        charge = charge_at(first)
        lo, hi = first, last
        # At one frozen price every supported rounded charge is nondecreasing.
        # For balance rounding that charge is total commitment, including cost.
        while lo < hi:
            middle = (lo + hi + 1) // 2
            if charge_at(middle) == charge:
                lo = middle
            else:
                hi = middle - 1
        position = (target + charge) / profit_per_tick
        for ticks in {floor(position), ceil(position)}:
            yield min(lo, max(first, ticks))
        first = lo + 1


def _nearest(quote_at, target, slope, rounding, profit_per_tick):
    """Find the global closest positive result using the fee rounding envelope.

    Tick profit need not be monotone. A rounded fee jump can exceed one tick's
    improvement, so search every tick that can tie or beat our seeded distance.
    """
    if slope <= 0:
        raise ValueError("fixed_profit_positive_win_unavailable")
    seeds = {max(1, floor(target / slope)), max(1, ceil((target + rounding) / slope))}

    def evaluate(ticks):
        profit, fill = quote_at(ticks)
        if abs(profit - slope * ticks) > rounding:
            raise ValueError("fixed_profit_fee_rounding_unverified")
        return ((abs(profit - target), fill[0], ticks), profit, fill) if profit > 0 else None

    best = min((result for ticks in seeds if (result := evaluate(ticks)) is not None), default=None)
    if best is None:
        raise ValueError("fixed_profit_positive_win_unavailable")
    distance = best[0][0]
    first = max(1, ceil((target - distance - rounding) / slope))
    last = floor((target + distance + rounding) / slope)
    neighbors = (range(first, last + 1) if last - first <= 32 else
                 _plateau_neighbors(quote_at, target, first, last, profit_per_tick))
    for ticks in neighbors:
        if ticks in seeds:
            continue
        candidate = evaluate(ticks)
        if candidate is not None and candidate < best:
            best = candidate
    return best[0][2], best[1], best[2]


def calculate(offer, *, at, game_key, target):
    """Reprice the quantity whose positive net win profit best fits the target."""
    record, original, fee = (offer[key] for key in ("record", "calculation_payload", "fee_input"))
    if target <= 0:
        raise ValueError("fixed_profit_target_invalid")
    contract = current_pregame.posted_contract(record, fee, at=at, amount=current_pregame.COMPARISON_USD)
    row, cost, terms = contract
    if F(original["raw"]["posted_decimal"]) * cost != 1:
        raise ValueError("fixed_profit_frozen_odds_mismatch")
    step, price_tick, grid_basis = _grid(record, row, terms, cost, original)
    terms.update(increment=wire(step), minimum=wire(step))
    stake = terms["kind"] == "stake"
    if not stake:
        terms["asks"] = [dict(price=wire(cost), quantity=wire(step))]
    pricer, evidence, rate, error = _fee_model(row, terms, cost, fee)
    unit_price = F(1) if stake else cost
    claims_per_tick = step / cost if stake else step
    slope = claims_per_tick * (1 - cost - rate)
    profit_per_tick = claims_per_tick if row["venue"] == "kalshi" else claims_per_tick * (1 - cost)

    @lru_cache(maxsize=64)
    def quote_at(ticks):
        quantity = ticks * step
        wager = unit_price * quantity
        legs = [(unit_price, quantity)]
        entry, reserve, cash, trace = pricer(legs, wager)
        committed = wager + entry + reserve
        win = current_pregame.posted_cash_state("win", ticks * claims_per_tick, wager,
                                                committed, entry, reserve, cash)
        return F(win["net_profit_usd"]), (committed, legs, wager, entry, reserve, cash, trace)

    ticks, win, fill = _nearest(quote_at, target, slope, error, profit_per_tick)
    calculation = current_pregame.posted_calculation(record, original["reference"], fee, at=at,
        game_key=game_key, amount=fill[0], contract=contract, fill=fill, evidence=evidence)
    calculation["sizing"] = dict(mode="fixed_profit", rule=RULE, target_profit_usd=wire(target),
        modeled_win_profit_usd=wire(win), profit_difference_usd=wire(win - target),
        ideal_purchase_usd=wire(target / (1 / cost - 1)), quantity=wire(ticks * step),
        quantity_increment=wire(step), quantity_unit="stake_usd" if stake else "usd_payout_claims",
        commitment_increment_usd=wire(unit_price * step) if not rate and not error else None,
        price_increment=wire(price_tick) if price_tick is not None else None, grid_basis=grid_basis)
    return calculation
