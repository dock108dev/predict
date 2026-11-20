"""Validate reported fills and derive stake-only prices/fees from frozen quotes."""

from datetime import datetime, timezone
from fractions import Fraction

from app.comparison.scanner_readiness import EXECUTION_VENUES


def clock():
    return datetime.now(timezone.utc).isoformat()


def instant(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("A timestamp with a timezone is required")
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.utcoffset() is None:
        raise ValueError("A timestamp with a timezone is required")
    return parsed


def legs(snapshot, kind):
    return snapshot["legs"] if kind == "arb" else [snapshot]


def number(value, *, positive=False, probability=False, signed=False):
    if isinstance(value, bool) or value is None or len(str(value)) > 100:
        raise ValueError("Enter finite numbers for prices, amounts and fees")
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        raise ValueError("Enter finite numbers for prices, amounts and fees") from None
    if abs(result) > 1_000_000_000 or (
        not signed and (result <= 0 if positive else result < 0)
    ):
        raise ValueError("Amounts must be positive and fees cannot be negative")
    if probability and result >= 1:
        raise ValueError("Contract prices must be between 0 and 1")
    return result


def validate_trade(trade, entry, decision, *, clock=clock):
    if trade is None:
        if decision == "placed":
            raise ValueError("Enter the actual trade before marking it placed")
        return
    if not isinstance(trade, dict) or set(trade) - {"legs", "placed_at", "result"}:
        raise ValueError("Unknown trade fields")
    rows = trade.get("legs", [])
    original = legs(entry["snapshot"], entry["kind"])
    if not isinstance(rows, list) or len(rows) != len(original):
        raise ValueError("Record the price and cashflows for every original leg")
    for actual, quoted in zip(rows, original):
        if not isinstance(actual, dict) or set(actual) - {
            "quote_id",
            "stake",
            "price",
            "units",
            "entry_fee",
            "win_fee",
            "loss_fee",
            "fee_basis",
            "venue",
        }:
            raise ValueError("Unknown trade leg fields")
        if actual.get("quote_id") != quoted["id"]:
            raise ValueError("The trade must retain its original selections and venues")
        if actual.get("venue"):
            from app.comparison.sportsbooks import SPORTSBOOKS

            if actual["venue"] not in (*EXECUTION_VENUES, *SPORTSBOOKS):
                raise ValueError("Choose a supported actual venue")
        for key in ("stake", "price", "units", "entry_fee", "win_fee", "loss_fee"):
            value = actual.get(key)
            if value in (None, ""):
                if decision == "placed" and not (
                    key in ("entry_fee", "win_fee", "loss_fee")
                    and actual.get("fee_basis") == "unavailable"
                ):
                    raise ValueError(
                        "Placed trades need actual prices, stakes and explicit fees"
                    )
                continue
            if key == "units":
                if value not in ("american_odds", "probability"):
                    raise ValueError(
                        "Use American odds or a contract price between 0 and 1"
                    )
            elif key == "price":
                if actual.get("units") == "american_odds":
                    try:
                        price = Fraction(str(value))
                    except (ValueError, ZeroDivisionError):
                        raise ValueError("Invalid American odds") from None
                    if not 100 <= abs(price) <= 1_000_000:
                        raise ValueError(
                            "American odds must be at least +100 or at most -100"
                        )
                else:
                    number(value, positive=True, probability=True)
            else:
                number(value, positive=key == "stake")
    placed_at = trade.get("placed_at")
    if decision == "placed" and not placed_at:
        raise ValueError("Record when the trade was placed")
    if placed_at:
        if instant(placed_at) > instant(clock()):
            raise ValueError("Placement cannot be in the future")
    result = trade.get("result")
    if result is not None:
        if (
            decision != "placed"
            or not isinstance(result, dict)
            or set(result) - {"outcomes", "receipts_usd", "settled_at", "notes"}
        ):
            raise ValueError("Results belong to placed trades")
        if "outcomes" in result:
            outcomes = result["outcomes"]
            if "receipts_usd" in result:
                raise ValueError("Choose outcomes or explicit returned cash, not both")
            if (
                not isinstance(outcomes, list)
                or len(outcomes) != len(original)
                or any(
                    not isinstance(value, str) or value not in ("win", "loss", "push")
                    for value in outcomes
                )
            ):
                raise ValueError("Choose Win, Loss or Tie / Push for each leg")
        else:
            receipts = result.get("receipts_usd")
            if not isinstance(receipts, list) or len(receipts) != len(original):
                raise ValueError("Record net returned cash for each leg")
            for receipt in receipts:
                number(receipt, signed=True)
        if not result.get("settled_at"):
            raise ValueError("Record the settlement time")
        settled = instant(result["settled_at"])
        if not placed_at or not instant(placed_at) <= settled <= instant(clock()):
            raise ValueError(
                "Settlement must follow placement and cannot be in the future"
            )
        if len(str(result.get("notes", ""))) > 4000:
            raise ValueError("Result notes are limited to 4000 characters")


def automatic_trade(trade, entry, decision, *, clock=clock):
    """Resolve a stake-only report using its frozen book price and fee terms."""
    if not isinstance(trade, dict) or trade.get("automatic") is not True:
        return trade
    if set(trade) - {"automatic", "legs", "placed_at", "result"}:
        raise ValueError("Unknown trade fields")
    from .bet_journal_metrics import decimal_price, posted_decimal
    from app.comparison.cashflows import exact_wire
    from app.comparison.sportsbooks import SPORTSBOOKS
    from app.fees.engine import posted_fee

    originals = legs(entry["snapshot"], entry["kind"])
    reports = trade.get("legs")
    if not isinstance(reports, list) or len(reports) != len(originals):
        raise ValueError("Enter the stake for each leg")
    previous = entry.get("trade") or {}
    result = dict(
        legs=[], placed_at=trade.get("placed_at") or previous.get("placed_at")
    )
    if decision == "placed" and not result["placed_at"]:
        result["placed_at"] = clock()
    for i, (report, row) in enumerate(zip(reports, originals)):
        if not isinstance(report, dict) or set(report) - {
            "quote_id",
            "stake",
            "price",
            "units",
            "venue",
            "entry_fee",
            "win_fee",
            "loss_fee",
        }:
            raise ValueError("Supply the stake and optional actual odds for each leg")
        if report.get("quote_id") != row["id"]:
            raise ValueError("The trade must retain its original selections and venues")
        stake = number(report.get("stake"), positive=True)
        decimal = posted_decimal(row)
        units = (
            "probability"
            if row["venue"] in ("kalshi", "polymarket_us")
            else "american_odds"
        )
        price = (
            1 / decimal
            if units == "probability"
            else (100 * (decimal - 1) if decimal >= 2 else -100 / (decimal - 1))
        )
        if report.get("price") not in (None, ""):
            price, units = report["price"], report.get("units", units)
            number(price, signed=True)
            decimal = decimal_price(price, units)
        actual = dict(
            quote_id=row["id"], stake=exact_wire(stake), price=str(price), units=units
        )
        venue = report.get("venue") or row["venue"]
        if venue not in (*EXECUTION_VENUES, *SPORTSBOOKS):
            raise ValueError("Choose a supported actual venue")
        if "venue" in report:
            actual["venue"] = venue
        fee_keys = ("entry_fee", "win_fee", "loss_fee")
        if any(k in report for k in fee_keys):
            actual.update({k: exact_wire(number(report.get(k))) for k in fee_keys})
            actual["fee_basis"] = "user_reported"
            result["legs"].append(actual)
            continue
        if venue != row["venue"]:
            raise ValueError("Enter actual fees when changing the venue")
        old = (previous.get("legs") or [])[i : i + 1]
        if old and (
            (old[0].get("venue") or row["venue"]) == venue
            and all(
                old[0].get(k) not in (None, "") for k in ("stake", "price", "units")
            )
            and old[0].get("quote_id") == row["id"]
            and Fraction(str(old[0].get("stake"))) == stake
            and decimal_price(old[0].get("price"), old[0].get("units")) == decimal
            and (
                old[0].get("fee_basis") == "unavailable"
                or all(
                    old[0].get(k) not in (None, "")
                    for k in ("entry_fee", "win_fee", "loss_fee")
                )
            )
        ):
            # Keep explicitly recorded charges when only notes/result change.
            actual.update(
                {
                    k: old[0].get(k)
                    for k in ("entry_fee", "win_fee", "loss_fee", "fee_basis")
                    if k in old[0]
                }
            )
        else:
            fee = row.get("fee") or {}
            rule = (fee.get("evidence") or {}).get("database_fee_rule")
            actual.update(
                entry_fee=None, win_fee=None, loss_fee=None, fee_basis="unavailable"
            )
            if rule:
                try:
                    entry_fee, winning, _ = posted_fee(
                        rule, price=1 / decimal, quantity=stake * decimal, stake=stake
                    )
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    # Older saved schedules can be incomplete or unsupported.
                    # Recording a stake still succeeds with unknown charges.
                    pass
                else:
                    actual.update(
                        entry_fee=exact_wire(entry_fee),
                        win_fee=exact_wire(winning),
                        loss_fee="0",
                        fee_basis="saved_book_schedule",
                    )
            elif row["venue"] in SPORTSBOOKS or (
                fee.get("classification") == "exact_public"
                and row["venue"] == "novig"
                and all(
                    Fraction(str(value)) == 0
                    for value in (
                        fee.get("entry_usd", "-1"),
                        fee.get("cashflows", {})
                        .get("win", {})
                        .get("total_fee_usd", "-1"),
                        fee.get("cashflows", {})
                        .get("loss", {})
                        .get("total_fee_usd", "-1"),
                    )
                )
            ):
                actual.update(
                    entry_fee="0",
                    win_fee="0",
                    loss_fee="0",
                    fee_basis="saved_book_schedule",
                )
        result["legs"].append(actual)
    settlement = trade.get("result", previous.get("result"))
    if settlement is not None:
        if not isinstance(settlement, dict):
            raise ValueError("Results belong to placed trades")
        result["result"] = dict(settlement)
        if not result["result"].get("settled_at"):
            result["result"]["settled_at"] = clock()
    return result
