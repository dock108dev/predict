"""Exact fixed-profit paper fills over one cutoff-admitted public book."""

from bisect import bisect_left
from dataclasses import dataclass
from fractions import Fraction as F
from math import ceil, floor

from app.storage.store import stamp

from . import current_pregame, fixed_profit, scanner_kalshi, scanner_polymarket
from .cashflows import exact_wire as wire

VERSION = "public-depth-fixed-profit-1"
NOVIG_PRICE_BANDS = (("0.001", "0.050", "0.001"), ("0.055", "0.945", "0.005"),
                     ("0.950", "0.999", "0.001"))
_BOOK_ERRORS = (ArithmeticError, KeyError, TypeError, ValueError)


def native_limit(quote_price, bands):
    """Highest legal buy price at or below the exact frozen quote."""
    eligible = []
    for start, end, step in (tuple(map(F, band)) for band in bands):
        if not 0 <= start <= end <= 1 or step <= 0:
            raise ValueError("depth_price_grid_unverified")
        if quote_price >= start:
            ticks = (min(quote_price, end) - start) // step
            point = start + ticks * step
            eligible.append(point - step if point == 1 else point)
    return max(eligible, default=F(0))


@dataclass(frozen=True)
class Order:
    price: F
    quantity: int
    per_contract_fee: F
    individually_identified: bool

    def fee(self, quantity, precision, *, fragmented):
        # Every price level in the individual book is complete and the market
        # preserves maker priority. For catalog-only data bound the unknown
        # split between one fill and one maker fill per native contract.
        if fragmented and not self.individually_identified:
            return ceil(self.per_contract_fee / precision) * precision * quantity
        return ceil(self.per_contract_fee * quantity / precision) * precision


class NovigFill:
    def __init__(self, orders, *, payout, precision, fragmented):
        self.orders = orders
        self.payout = payout
        self.precision = precision
        self.fragmented = fragmented
        self.quantity = [0]
        self.purchase = [F(0)]
        self.fees = [F(0)]
        for order in orders:
            self.quantity.append(self.quantity[-1] + order.quantity)
            self.purchase.append(self.purchase[-1] + order.price * payout * order.quantity)
            self.fees.append(self.fees[-1] + order.fee(order.quantity, precision, fragmented=fragmented))

    def amounts(self, quantity):
        previous = bisect_left(self.quantity, quantity) - 1
        order = self.orders[previous]
        take = quantity - self.quantity[previous]
        purchase = self.purchase[previous] + order.price * self.payout * take
        fee = self.fees[previous] + order.fee(take, self.precision, fragmented=self.fragmented)
        return purchase, fee

    def profit(self, quantity):
        return quantity * self.payout - sum(self.amounts(quantity))

    def nearest(self, target, next_profit_tick):
        # Gross increments and fee rounding align to the same millicent grid.
        # A fee increment can leave net profit flat, but cannot push it down.
        available = self.quantity[-1]
        first_at_target = bisect_left(range(1, available + 1), target, key=self.profit) + 1
        quantities = []
        if first_at_target <= available:
            quantities.append(first_at_target)
        if first_at_target > 1:
            lower_profit = self.profit(first_at_target - 1)
            # Use the first occurrence of a plateau for the commitment tie.
            quantities.append(bisect_left(range(1, first_at_target), lower_profit, key=self.profit) + 1)
        chosen = min((quantity for quantity in quantities if self.profit(quantity) > 0), default=None,
            key=lambda quantity: fixed_profit.preference(self.profit(quantity), sum(self.amounts(quantity)),
                                                         quantity, target))
        if chosen is None:
            return None, False
        next_profit = self.profit(available) + next_profit_tick
        full = first_at_target <= available or (next_profit >= target
            and abs(target - self.profit(chosen)) <= abs(target - next_profit))
        return chosen, full

    def detail(self, quantity):
        remaining = quantity
        legs, trace = [], []
        for order in self.orders:
            take = min(remaining, order.quantity)
            legs.append((order.price, take * self.payout))
            trace.append(dict(price=wire(order.price), native_quantity=str(take),
                fee_usd=wire(order.fee(take, self.precision, fragmented=self.fragmented)),
                order_split="individual" if order.individually_identified else
                            "max_fragmentation_bound" if self.fragmented else "single_fill_bound"))
            remaining -= take
            if not remaining:
                break
        purchase, fee = self.amounts(quantity)
        return purchase + fee, legs, purchase, fee, F(0), {}, trace


def _book(receipt, quote_price, *, bands):
    best_limit = native_limit(quote_price, bands)
    levels = []
    for level in receipt["levels"]:
        price, quantity = F(level["price"]), F(level["quantity"])
        orders = tuple(map(F, level["orders"])) if "orders" in level else None
        if (not 0 < price < 1 or price != native_limit(price, bands) or quantity <= 0
                or (levels and price <= levels[-1][0])
                or (orders is not None and (sum(orders) != quantity or any(size <= 0 for size in orders)))):
            raise ValueError("depth_book_invalid")
        levels.append((price, quantity, orders))
    # Every order at a retained price is included. A discarded worse level
    # or a last retained price at the limit proves no better level is hidden.
    complete = receipt["complete"] is True or bool(levels and levels[-1][0] >= best_limit)
    return best_limit, levels, [(p, q, orders) for p, q, orders in levels if p <= best_limit], complete


def _availability(result, eligible, *, payout, complete):
    result.update(available_native_quantity=wire(sum((q for _, q, _ in eligible), F(0))),
        available_purchase_usd=wire(sum((p * q * payout for p, q, _ in eligible), F(0))),
        available_gross_win_profit_usd=wire(sum(((1 - p) * q * payout for p, q, _ in eligible), F(0))),
        availability_is_lower_bound=not complete)


def _unknown(result, reason):
    result.update(status="unknown", eligible=False, reason=reason)
    return result, None


def _modeled(result, quantity, payout, fill, probability):
    commitment, _, purchase, fee, _, _, trace = fill
    win = quantity * payout - commitment
    ev = probability * quantity * payout / commitment - 1 if probability is not None else None
    result.update(modeled_native_quantity=wire(F(quantity)),
        modeled_average_price=wire(purchase / (quantity * payout)),
        modeled_fee_usd=wire(fee), modeled_stake_usd=wire(commitment), modeled_purchase_usd=wire(purchase),
        modeled_win_profit_usd=wire(win), modeled_net_ev=wire(ev), modeled_fills=trace)
    return ev


def _novig_depth(result, receipt, quote_price, *, target, minimum, probability):
    payout = F(receipt["payout_usd"])
    if payout != F("0.01") or F(receipt["quantity_increment"]) != 1:
        raise ValueError("depth_quantity_grid_unverified")
    limit, levels, eligible, complete = _book(receipt, quote_price, bands=NOVIG_PRICE_BANDS)
    _availability(result, eligible, payout=payout, complete=complete)
    result.update(limit_price=wire(limit), best_price=wire(levels[0][0]) if levels else None)
    if not eligible:
        if not complete:
            return _unknown(result, "truncated")
        result.update(status="above_limit" if levels else "confirmed_empty", eligible=False, reason=None)
        return result, None

    terms = receipt["fee"]
    if terms.get("model") != "novig_v3" or terms.get("coefficient") is None:
        return _unknown(result, terms.get("reason") or "fee_schedule_unverified")
    coefficient, precision = F(terms["coefficient"]), F(terms["round_usd"])
    if not 0 <= coefficient <= 1 or precision != F("0.00001"):
        raise ValueError("fee_schedule_unverified")

    def raw_fee(price):
        return coefficient * price * (1 - price) * payout

    orders = []
    for price, quantity, sizes in eligible:
        for size in (sizes if sizes is not None else (quantity,)):
            if size.denominator != 1:
                raise ValueError("depth_quantity_grid_unverified")
            orders.append(Order(price, int(size), raw_fee(price), sizes is not None))

    # At or below the limit a single additional legal contract has at least
    # this much net win. A missing next tick only matters if it can improve
    # the existing fixed-profit nearest-size result.
    next_tick = payout * (1 - limit) - ceil(raw_fee(limit) / precision) * precision
    conservative = NovigFill(orders, payout=payout, precision=precision, fragmented=True)
    quantity, full = conservative.nearest(target, next_tick)
    if quantity is None:
        if coefficient and any(not order.individually_identified for order in orders):
            return _unknown(result, "fee_rounding_ambiguous")
        return _unknown(result, "truncated") if not complete else (dict(result,
            status="partial_size", eligible=False, reason="positive_net_win_unavailable"), None)
    modeled = conservative.detail(quantity)
    commitment, _, purchase, *_ = modeled
    ev = _modeled(result, quantity, payout, modeled, probability)
    passes_ev = minimum is None or ev >= minimum

    if coefficient and any(not order.individually_identified for order in orders):
        optimistic = NovigFill(orders, payout=payout, precision=precision, fragmented=False)
        lower_quantity, lower_full = optimistic.nearest(target, next_tick)
        lower_commitment = sum(optimistic.amounts(quantity))
        lower_ev = probability * payout * quantity / lower_commitment - 1 if probability is not None else None
        lower_passes_ev = minimum is None or lower_ev >= minimum
        result["fee_lower_bound_usd"] = wire(lower_commitment - purchase)
        result["fee_is_upper_bound"] = lower_commitment != commitment
        result["fee_detail_needed"] = (lower_quantity != quantity or lower_commitment != commitment
                                       or lower_full != full)
        if full != lower_full or (full and passes_ev != lower_passes_ev):
            return _unknown(result, "fee_rounding_ambiguous")

    if not full and not complete:
        return _unknown(result, "truncated")
    result.update(status="full_size" if full else "partial_size", eligible=full and passes_ev,
        reason="net_ev_below_minimum" if full and not passes_ev else None)
    return result, modeled if full else None


def _native_fee_curve(venue, receipt, price, step):
    terms = receipt["fee"]
    if venue == "polymarket_us" and terms.get("model") == "polymarket_us_standard_taker_bound":
        return F(terms["coefficient"]) * price * (1 - price) * step, F("0.005")
    if venue == "kalshi" and terms.get("model") == "kalshi_direct_taker_bound":
        model = dict(fee=terms["terms"], grid=dict(price_ranges=receipt["price_bands"]))
        # A 100-tick block aligns the scanner's published fee bound to the
        # balance grid, even if each legal order tick is 0.01 contracts.
        charge = scanner_kalshi.entry_fee(model, [(step * 100, price)]) / 100
        return charge, scanner_kalshi.DIRECT_PRECISION
    raise ValueError("fee_schedule_unverified")


def _nearest_segment(quote_at, *, lower, upper, target, baseline, slope, error):
    """Apply the original nearest-win rule within one price segment's fee envelope."""
    if slope <= 0 or upper < lower:
        return None
    center = (target - baseline) / slope
    seeds = {min(upper, max(lower, ticks)) for ticks in (floor(center), ceil(center))}

    def candidate(ticks):
        commitment, _, profit = quote_at(ticks)
        if profit <= 0:
            return None
        if abs(profit - (baseline + slope * ticks)) > error:
            raise ValueError("depth_fee_rounding_unverified")
        return fixed_profit.preference(profit, commitment, ticks, target), ticks

    seeded = min((choice for ticks in seeds if (choice := candidate(ticks)) is not None), default=None)
    # A positive nearest result can sit just after the first rounded fee. Use
    # the furthest end as a seed if the target-center samples are both zero.
    if seeded is None:
        seeded = candidate(upper)
    if seeded is None:
        return None
    distance = seeded[0][0]
    ahead = max(lower, ceil((target - baseline - distance - error) / slope))
    behind = min(upper, floor((target - baseline + distance + error) / slope))
    return min((choice for ticks in range(ahead, behind + 1) if (choice := candidate(ticks)) is not None),
               default=seeded)[1]


def _native_depth(result, receipt, quote_price, *, target, minimum, probability):
    venue = receipt["venue"]
    payout, step = F(receipt["payout_usd"]), F(receipt["quantity_increment"])
    min_quantity = F(receipt.get("quantity_minimum", step))
    if payout != 1 or not 0 < step <= min_quantity or min_quantity % step:
        raise ValueError("depth_quantity_grid_unverified")
    limit, levels, eligible, complete = _book(receipt, quote_price, bands=receipt["price_bands"])
    _availability(result, eligible, payout=payout, complete=complete)
    result.update(limit_price=wire(limit), best_price=wire(levels[0][0]) if levels else None)
    if not eligible:
        if not complete:
            return _unknown(result, "truncated")
        result.update(status="above_limit" if levels else "confirmed_empty", eligible=False, reason=None)
        return result, None

    quantity, purchase, fees, fee_basis = F(0), F(0), F(0), F(0)
    best, legs, trace = None, [], []
    max_profit = F(0)
    for ask, available, _ in eligible:
        ticks = available // step
        if not ticks:
            continue
        fee_slope, error = _native_fee_curve(venue, receipt, ask, step)
        basis = fee_basis if venue == "polymarket_us" else fees

        def quote_at(use):
            cost = purchase + use * step * ask
            if venue == "polymarket_us":
                fills = [(size, p) for p, size in legs] + [(use * step, ask)]
                fee = scanner_polymarket.entry_fee(dict(fee=receipt["fee"]), fills)
            else:
                fee = fees + ceil(fee_slope * use / error) * error
            return cost + fee, fee, quantity + use * step - cost - fee

        chosen = _nearest_segment(quote_at, lower=max(1, ceil((min_quantity - quantity) / step)),
            upper=ticks, target=target, baseline=quantity - purchase - basis,
            slope=step * (1 - ask) - fee_slope, error=error)
        if chosen is not None:
            commitment, entry, profit = quote_at(chosen)
            size = quantity + chosen * step
            rank = fixed_profit.preference(profit, commitment, size, target)
            max_profit = max(max_profit, profit)
            if best is None or rank < best[0]:
                detail = dict(price=wire(ask), native_quantity=wire(chosen * step), fee_usd=wire(entry - fees))
                best = rank, size, (commitment, [*legs, (ask, chosen * step)], commitment - entry,
                                    entry, F(0), {}, [*trace, detail])
        commitment, entry, end_profit = quote_at(ticks)
        max_profit = max(max_profit, end_profit)
        trace.append(dict(price=wire(ask), native_quantity=wire(ticks * step), fee_usd=wire(entry - fees)))
        legs.append((ask, ticks * step))
        quantity += ticks * step
        fees, purchase = entry, commitment - entry
        fee_basis += fee_slope * ticks
    if best is None:
        if not complete:
            return _unknown(result, "truncated")
        result.update(status="partial_size", eligible=False, reason="positive_net_win_unavailable")
        return result, None
    rank, quantity, fill = best
    ev = _modeled(result, quantity, payout, fill, probability)
    result["fee_is_upper_bound"] = True
    # Fee rounding need not be monotone on native 0.01-contract grids. Only a
    # proven crossing marks a full size below the target, unless the smallest
    # possible next legal increment is already farther away than this fill.
    next_fee, error = _native_fee_curve(venue, receipt, limit, step)
    min_next = end_profit + step * (1 - limit) - next_fee - 2 * error
    full = max_profit >= target or min_next - target >= rank[0]
    if not full and not complete:
        return _unknown(result, "truncated")
    passes_ev = ev >= minimum
    result.update(status="full_size" if full else "partial_size", eligible=full and passes_ev,
        reason="net_ev_below_minimum" if full and not passes_ev else None)
    return result, fill if full else None


def needs_book(receipt, *, quote_price, target=25, minimum=None, probability=None):
    """Ask for detail only when its tail or its maker split can change paper evidence."""
    if receipt.get("reason"):
        return False
    try:
        result, _ = _novig_depth({}, receipt, F(quote_price), target=F(target),
            minimum=F(minimum) if minimum is not None else None,
            probability=F(probability) if probability is not None else None)
    except _BOOK_ERRORS:
        return False
    return result.get("reason") in ("truncated", "fee_rounding_ambiguous") or bool(
        result.get("status") == "full_size" and result.get("fee_detail_needed"))


def evaluate(offer, receipt, *, at, game_key, target, minimum):
    """Return the depth disposition and, for a qualified fill, its gradeable cashflows."""
    record, original = offer["record"], offer["calculation_payload"]
    payout = F(original["raw"]["posted_decimal"])
    quote_price, target, minimum = 1 / payout, F(target), F(minimum)
    if not 0 < quote_price < 1 or target <= 0:
        raise ValueError("depth_frozen_price_or_target_invalid")
    result = dict(version=VERSION, target_profit_usd=wire(target), quoted_price=wire(quote_price),
        intended_stake_usd=wire(target / (payout - 1)))
    if not receipt:
        return _unknown(result, "no_decision_receipt")
    result.update({key: receipt[key] for key in ("venue", "event_id", "market_id", "outcome_id",
        "opposite_outcome_id", "receipt_id", "receipt_ids", "receipt_refs") if key in receipt})
    if receipt.get("reason"):
        if receipt.get("venue") == record["quote"]["venue"] == "novig" and receipt.get("catalog_lower_bound") is True:
            # A second-tier failure does not erase the already-qualified first
            # image. Preserve its capacity for analysis; its execution remains unknown.
            try:
                limit, levels, eligible, _ = _book(receipt, quote_price, bands=NOVIG_PRICE_BANDS)
                if F(receipt["payout_usd"]) == F("0.01"):
                    _availability(result, eligible, payout=F("0.01"), complete=False)
                    result.update(limit_price=wire(limit), best_price=wire(levels[0][0]) if levels else None,
                                  capacity_evidence="qualified_catalog_lower_bound")
            except _BOOK_ERRORS:
                pass
        return _unknown(result, receipt["reason"])
    if receipt.get("venue") != record["quote"]["venue"]:
        return _unknown(result, "receipt_venue_mismatch")
    if receipt["venue"] not in ("novig", "kalshi", "polymarket_us"):
        return _unknown(result, "unsupported_venue")

    try:
        reference = original["reference"]
        value = _novig_depth if receipt["venue"] == "novig" else _native_depth
        result, fill = value(result, receipt, quote_price, target=target,
            minimum=minimum, probability=F(reference["probability"]))
        if fill is None or not result["eligible"]:
            return result, None
        depth_fee = dict(classification="public_depth_fee_model", available=True, evidence=receipt["fee"])
        at = stamp(at)
        row, cost, terms = current_pregame.posted_contract(record, depth_fee, at=at, amount=fill[0])
        if cost != quote_price:
            return _unknown(result, "depth_frozen_odds_mismatch")
        terms.update(kind="exchange", increment=wire(F(receipt["payout_usd"]) * F(receipt["quantity_increment"])))
        calculation = current_pregame.posted_calculation(record, reference, depth_fee, at=at,
            game_key=game_key, amount=fill[0], contract=(row, cost, terms), fill=fill, evidence=receipt["fee"])
    except _BOOK_ERRORS as exc:
        return _unknown(result, str(exc) if isinstance(exc, ValueError) else "depth_inputs_invalid")
    calculation["sizing"] = dict(mode="fixed_profit", rule=fixed_profit.RULE, execution_rule=VERSION,
        target_profit_usd=wire(target), modeled_win_profit_usd=result["modeled_win_profit_usd"],
        profit_difference_usd=wire(F(result["modeled_win_profit_usd"]) - target),
        ideal_purchase_usd=result["intended_stake_usd"], quantity=result["modeled_native_quantity"],
        quantity_increment=receipt["quantity_increment"], quantity_unit="native_contracts",
        price_increment=None, grid_basis="public_native_order_grid")
    return result, calculation
