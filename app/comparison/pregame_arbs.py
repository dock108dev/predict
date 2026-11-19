"""Reference-free, exact-fee two-sided price comparisons, never fill promises."""

from fractions import Fraction as F
from copy import deepcopy
from app.comparison import current_pregame as prices
from app.comparison.cashflows import exact_wire as wire
from app.comparison.pregame_valuation import decimal_display
from app.comparison.sgo_reference import OPPOSITE
from app.storage.store import hashed

BUDGET = F(100)


def reprice(entry, amount, *, at):
    # One quote participates in many opposing pairs. Binary searches repeatedly
    # ask for the same cent allocation; reuse that exact fee/order result.
    # Return independent nested cashflows because the selected legs are edited
    # for presentation and callers must not change the retained sample.
    cache = entry.setdefault("_reprice_cache", {})
    key = (at, amount)
    if key not in cache:
        if len(cache) >= 256:
            cache.clear()
        cache[key] = _reprice(entry, amount, at=at)
    return deepcopy(cache[key])


def _reprice(entry, amount, *, at):
    if entry.get("record"):
        return prices.calculate(
            entry["record"],
            None,
            entry["fee_input"],
            at=at,
            game_key=entry["payload"]["game_key"],
            amount=amount,
        )
    # Ordinary sportsbook stakes use cents; no placement commission assumed.
    original = entry["payload"]
    stake = F(amount * 100 // 1, 100)
    if not stake:
        raise ValueError("stake_rounds_to_zero")
    gross = stake * F(original["raw"]["posted_decimal"])
    return dict(
        original,
        fee=dict(
            original["fee"],
            committed_usd=wire(stake),
            cashflows=dict(
                win=dict(net_receipt_usd=wire(gross), total_fee_usd="0"),
                loss=dict(net_receipt_usd="0", total_fee_usd="0"),
            ),
        ),
    )


def scoped(entry):
    scope = entry["payload"].get("scoring_scope") or {}
    if scope.get("conflicts"):
        raise ValueError("scoring_scope_conflict")
    values = {
        r.get("overtime")
        for r in scope.get("evidence", [])
        if r.get("overtime") in ("included", "excluded")
    }
    if len(values) > 1:
        raise ValueError("scoring_scope_conflict")
    return next(iter(values), None)


def evaluate(left, right, *, at):
    """Balance on legal order grids inside $100. No global-optimum claim."""
    a, b = left["payload"], right["payload"]
    if (
        a["venue"] == b["venue"]
        or a["arb_key"] != b["arb_key"]
        or OPPOSITE.get(a["side"]) != b["side"]
    ):
        return None
    sa, sb = scoped(left), scoped(right)
    if sa and sb and sa != sb:
        return None
    # With nonnegative fees, a non-arb before fees cannot become one after fees.
    if 1 / F(a["raw"]["posted_decimal"]) + 1 / F(b["raw"]["posted_decimal"]) >= 1:
        return None
    best = None

    def sample(cents):
        nonlocal best
        try:
            legs = [
                reprice(left, F(cents, 100), at=at),
                reprice(right, BUDGET - F(cents, 100), at=at),
            ]
        except (ValueError, KeyError, TypeError, ArithmeticError):
            return None
        committed = sum(F(r["fee"]["committed_usd"]) for r in legs)
        if not 0 < committed <= BUDGET:
            return None
        receipts = [
            F(legs[0]["fee"]["cashflows"]["win"]["net_receipt_usd"])
            + F(legs[1]["fee"]["cashflows"]["loss"]["net_receipt_usd"]),
            F(legs[1]["fee"]["cashflows"]["win"]["net_receipt_usd"])
            + F(legs[0]["fee"]["cashflows"]["loss"]["net_receipt_usd"]),
        ]
        profits = [r - committed for r in receipts]
        rate = min(profits) / committed
        value = dict(
            legs=legs,
            committed=committed,
            receipts=receipts,
            profits=profits,
            rate=rate,
        )
        if best is None or (rate, committed) > (best["rate"], best["committed"]):
            best = value
        return receipts[0] - receipts[1]

    low, high = 1, 9999
    while low <= high:
        middle = (low + high) // 2
        difference = sample(middle)
        if difference is None:
            # Tiny budgets may be below a venue's quantity grid.
            break
        if difference < 0:
            low = middle + 1
        else:
            high = middle - 1
    for cents in range(max(1, low - 3), min(9999, low + 3) + 1):
        sample(cents)
    if not best or best["rate"] <= 0:
        return None
    for leg in best["legs"]:
        # No probability-derived values enter the arb response.
        leg.pop("reference", None)
        leg["raw"] = {
            k: v
            for k, v in leg["raw"].items()
            if k in ("posted_decimal", "after_fee_decimal")
        }
        leg["display"] = {
            k: v
            for k, v in leg["display"].items()
            if k in ("posted_odds", "after_fees")
        }
    category = (
        "market_book"
        if any(e.get("sportsbook") for e in (left, right))
        else "market_market"
    )
    return dict(
        id=hashed(sorted([a["id"], b["id"]])),
        game_key=a["game_key"],
        game=a["game"],
        league=a["league"],
        kickoff=a["kickoff"],
        family=a["family"],
        category=category,
        legs=best["legs"],
        basis_usd=wire(BUDGET),
        committed_usd=wire(best["committed"]),
        unused_usd=wire(BUDGET - best["committed"]),
        receipts_usd=[wire(v) for v in best["receipts"]],
        profits_usd=[wire(v) for v in best["profits"]],
        minimum_profit_usd=wire(min(best["profits"])),
        return_rate=wire(best["rate"]),
        display_return=decimal_display(100 * best["rate"], signed=True) + "%",
        conditioning="decisive_completed_game",
        execution_qualified=False,
        instant_fill_max_usd=None,
        settlement_note="Matching full-game scoring assumed. Pushes, ties, voids and exceptional settlements are not covered.",
        liquidity_note="Instantly fillable size is unknown. Verify both official order books; the $100 allocation is illustrative.",
    )
