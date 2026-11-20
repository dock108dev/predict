"""Exact journal cashflows and explicitly timestamped pregame comparisons.

Closing value means the last quote we actually retained before scheduled kickoff,
not a certified exchange closing price. All returns are ratios, not percentages.
"""

from datetime import datetime, timezone
from fractions import Fraction as F

from app.comparison.cashflows import exact_wire as wire


def instant(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("Timestamp required")
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.utcoffset() is None:
        raise ValueError("Timezone required")
    return parsed


def fraction(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("Exact number required")
    return F(str(value))


def decimal_price(price, units):
    value = fraction(price)
    if units == "probability" and 0 < value < 1:
        return 1 / value
    if units == "american_odds" and abs(value) >= 100:
        return 1 + value / 100 if value > 0 else 1 + 100 / -value
    if units == "decimal_odds" and value > 1:
        return value
    raise ValueError("Unsupported price")


def posted_decimal(row):
    raw = (row.get("raw") or {}).get("posted_decimal")
    if raw is not None:
        value = fraction(raw)
        if value > 1:
            return value
    posted = row.get("posted") or {}
    units = posted.get("units")
    value = posted.get("value")
    if units in ("cents", "price_cents"):
        return decimal_price(fraction(value) / 100, "probability")
    if units in ("probability", "contract_price", "price", "dollars"):
        return decimal_price(value, "probability")
    return decimal_price(value, units)


def closing_fair(row, original, probability):
    if row is None or probability is None:
        return None
    from app.comparison.pregame_valuation import american

    ref = row["reference"]
    side = ref.get("selected_outcome", original.get("side"))
    selected = next((q for q in ref["prices"] if q.get("side") == side), None)
    basis = ref.get("closing_basis", "exact_line")

    def selection(value):
        result = dict(original["selection"])
        if value is not None:
            line = fraction(value)
            result["signed_line"] = wire(
                -line if original["family"] == "spread" and side == "away" else line
            )
        return result

    brackets = [
        dict(bound, selection=selection(bound["line"]))
        for bound in ref.get("alternate_lines", [])
    ]
    return dict(
        book=ref["book"],
        fair_odds=american(1 / probability) if 0 < probability < 1 else None,
        probability=wire(probability),
        basis=basis,
        selection=selection((ref.get("market") or {}).get("line")),
        posted_odds=ref.get("estimated_posted_odds")
        if brackets
        else selected.get("price_american")
        if selected
        else None,
        posted_estimated=bool(brackets),
        source_at=min(ref["prices"], key=lambda q: instant(q["source_at"]))[
            "source_at"
        ],
        observed_at=row["observed_at"],
        alternate_lines=brackets,
        probability_range=ref.get("probability_range"),
    )


def _same_quote(row, original):
    # Contract aliases can change, but an exact selection/line, venue and scheduled
    # occurrence must never borrow a different line's attractive closing price.
    if row.get("venue") != original.get("venue"):
        return False
    try:
        if instant(row["kickoff"]) != instant(original["kickoff"]):
            return False
    except (KeyError, TypeError, ValueError):
        return False

    # Human labels can change independently of the economic selection. Keep all
    # other selection fields exact, including participant, predicate and line.
    def normalized(value):
        selection = value.get("selection")
        return (
            dict(
                value,
                selection={
                    key: item for key, item in selection.items() if key != "label"
                },
            )
            if isinstance(selection, dict)
            else value
        )

    row, original = normalized(row), normalized(original)
    keys = ("game_key", "family", "period", "selection")
    if any(
        original.get(key) is not None
        and row.get(key) is not None
        and row[key] != original[key]
        for key in keys
    ):
        return False
    if row.get("id") == original.get("id"):
        return True
    # Sportsbook rows can inherit a template's bet_id for its opposite side.
    # Native aliases therefore need the actual occurrence and selection fields.
    return all(
        original.get(key) is not None and row.get(key) == original[key] for key in keys
    )


def _pregame_clock(row, cutoff):
    try:
        times = row["times"]
        source = instant(times["source_at"])
        received = instant(times["received_at"])
        observed = instant(row["observed_at"])
        if source <= received <= observed and observed < cutoff:
            return source, received, observed
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _probability(row, cutoff, *, known_at=None):
    """A probability cannot acquire an earlier knowledge time than its inputs."""
    try:
        reference = row["reference"]
        from app.comparison.sgo_reference import BEST_BOOKS

        contributors = reference.get("candidate_probabilities") or {}
        if (
            sum(
                book in BEST_BOOKS and 0 < fraction(value) < 1
                for book, value in contributors.items()
            )
            < 2
        ):
            return None
        probability = fraction(reference["probability"])
        if not 0 <= probability <= 1 or not reference.get("prices"):
            return None
        for quote in reference["prices"]:
            source = instant(quote["source_at"])
            received = instant(quote.get("received_at") or quote["source_at"])
            knowledge = known_at or instant(row["observed_at"])
            if not source <= received < cutoff or received > knowledge:
                return None
        return probability
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def actual_cashflows(actual):
    """The shared exact fill calculation for previews and reported outcomes."""
    cash = dict(cost=None, win=None, loss=None, push=None, decimal=None)
    try:
        stake = fraction(actual["stake"])
        if stake <= 0:
            return cash
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return cash
    cash["push"] = stake
    try:
        entry = fraction(actual["entry_fee"])
        if entry >= 0:
            cash["cost"] = stake + entry
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    try:
        cash["decimal"] = decimal_price(actual["price"], actual["units"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    for outcome in ("win", "loss"):
        try:
            charge = fraction(actual[outcome + "_fee"])
            if charge < 0:
                continue
            cash[outcome] = (
                stake * cash["decimal"] if outcome == "win" else 0
            ) - charge
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
    return cash


def _cashflows(row, actual=None):
    if actual is None:
        fee = row["fee"]
        committed = fraction(fee["committed_usd"])
        win = fraction(fee["cashflows"]["win"]["net_receipt_usd"])
        loss = fraction(fee["cashflows"]["loss"]["net_receipt_usd"])
        decimal = posted_decimal(row)
    else:
        cash = actual_cashflows(actual)
        if any(cash[key] is None for key in ("cost", "win", "loss", "decimal")):
            raise ValueError("Positive stake and explicit nonnegative fees required")
        committed, win, loss, decimal = (
            cash[key] for key in ("cost", "win", "loss", "decimal")
        )
    if committed <= 0:
        raise ValueError("Positive committed cash required")
    return dict(cost=committed, win=win, loss=loss, decimal=decimal)


def settlement_result(trade, count, *, now):
    """Apply reported outcomes to actual pre-fee fills and recorded charges.

    A push reports a stake refund. Recorded entry charges remain incurred;
    winning/loss charges do not apply. Explicit net receipts remain authoritative
    for legacy reports and settlement adjustments such as refunded entry fees.
    """
    settlement = (trade or {}).get("result")
    if not settlement:
        return None
    outcomes = settlement.get("outcomes")
    report = dict(
        basis="reported_outcomes" if outcomes is not None else "reported_receipts",
        state="unavailable",
        outcomes=outcomes,
        receipts_usd=[None] * count,
        total_receipts_usd=None,
        entry_cost_usd=None,
        profit_usd=None,
        roi=None,
        reason="Actual entry costs or outcome fees are unavailable.",
    )
    try:
        if not settlement.get("settled_at") or instant(settlement["settled_at"]) > now:
            return dict(
                report, state="pending", reason="Settlement time has not been reached."
            )
        actuals = trade["legs"]
        if len(actuals) != count or (outcomes is not None and len(outcomes) != count):
            return report
        costs, receipts = [], []
        for index, actual in enumerate(actuals):
            cash = actual_cashflows(actual)
            costs.append(cash["cost"])
            try:
                if outcomes is None:
                    receipt = fraction(settlement["receipts_usd"][index])
                elif outcomes[index] in ("win", "loss", "push"):
                    receipt = cash[outcomes[index]]
                else:
                    raise ValueError("Unknown outcome")
                receipts.append(receipt)
            except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
                receipts.append(None)
        report["receipts_usd"] = [
            wire(value) if value is not None else None for value in receipts
        ]
        if all(value is not None for value in costs):
            cost = sum(costs)
            report["entry_cost_usd"] = wire(cost)
        if all(value is not None for value in receipts):
            report["total_receipts_usd"] = wire(sum(receipts))
        if all(value is not None for value in costs + receipts) and sum(costs) > 0:
            cost, profit = sum(costs), sum(receipts) - sum(costs)
            report.update(
                state="calculated",
                reason=None,
                profit_usd=wire(profit),
                roi=wire(profit / cost),
            )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    return report


def _ev(cash, probability):
    if cash is None or probability is None:
        return None
    return probability * cash["win"] + (1 - probability) * cash["loss"] - cash["cost"]


def _complementary(originals, reference_rows):
    if len(originals) != 2 or any(r is None for r in reference_rows):
        return False
    a, b = originals
    sides = {a.get("side"), b.get("side")}
    if sides not in ({"home", "away"}, {"over", "under"}):
        return False
    if not a.get("arb_key") or a.get("arb_key") != b.get("arb_key"):
        return False
    refs = [r.get("reference") or {} for r in reference_rows]
    if not refs[0].get("book") or refs[0].get("book") != refs[1].get("book"):
        return False
    # A book changing between two leg reads is not a single complementary model.
    keys = lambda ref: sorted(
        (p.get("side"), p.get("price_american"), p.get("source_at"))
        for p in ref.get("prices", [])
    )
    return keys(refs[0]) == keys(refs[1])


def analyze(entry, quotes, at=None):
    """Calculate a frozen decision's modeled/reported performance without I/O."""
    now = instant(at) if at is not None else datetime.now(timezone.utc)
    snapshot = entry["snapshot"]
    originals = snapshot["legs"] if entry["kind"] == "arb" else [snapshot]
    kickoff = instant(snapshot["kickoff"])
    created = instant(entry["created_at"])
    closed = now >= kickoff
    trade = entry.get("trade")
    actual_legs = (trade or {}).get("legs") or []
    result = dict(
        basis="reported_trade" if trade else "observed_model",
        scope_note="Modeled EV uses decisive completed-game cashflows. Reported results use selected outcomes or explicit receipts. Closing value uses the last retained pregame observation; quote and reference clocks may differ.",
        prospective_observation=created < kickoff,
        entry_probability_basis="Latest retained exact fair reference known by the reported placement time."
        if trade
        else "The original opportunity reference known when the opportunity was recorded.",
        close_state="closed" if closed else "tracking",
        kickoff=kickoff.isoformat(),
        observed_ev=(snapshot.get("raw") or {}).get("net_ev"),
        observed_arb_return=snapshot.get("return_rate"),
        entry_ev=None,
        entry_ev_usd=None,
        close_ev=None,
        close_ev_usd=None,
        close_market_ev=None,
        entry_cost_usd=None,
        entry_min_profit_usd=None,
        entry_arb_return=None,
        close_min_profit_usd=None,
        close_arb_return=None,
        close_cost_usd=None,
        close_basis="Each leg's stored closing comparison cashflows; not a repriced fill or a rebalanced order.",
        realized_profit_usd=None,
        realized_roi=None,
        settlement=None,
        legs=[],
        reasons=[],
        ev_slippage=None,
        arb_return_slippage=None,
        realized_minus_entry_ev_usd=None,
    )
    cashflows, closing_cashflows, entry_references, closing_references = [], [], [], []
    entry_probabilities, closing_probabilities = [], []
    for index, original in enumerate(originals):
        original_copy = dict(original, observed_at=entry["created_at"])
        candidates = [
            row for row in [*quotes, original_copy] if _same_quote(row, original)
        ]
        valid = [
            (clock, row)
            for row in candidates
            if (clock := _pregame_clock(row, min(kickoff, now))) is not None
        ]

        def latest_key(item):
            clock, row = item
            # A saved arb allocation is the entry model, not a new quote basis.
            # For the same source/receipt prefer the monitored source comparison
            # even if the user saved their differently sized snapshot later.
            return clock[0], clock[1], row is not original_copy, clock[2]

        market_valid = [
            item for item in valid if not item[1].get("journal_reference_only")
        ]
        latest = max(market_valid, key=latest_key)[1] if market_valid else None
        reference_candidates = [
            (clock, row)
            for clock, row in valid
            if _probability(row, min(kickoff, now)) is not None
        ]
        close_reference = (
            max(
                reference_candidates,
                key=lambda item: (
                    item[0][2],
                    bool(item[1].get("journal_reference_only")),
                ),
            )[1]
            if closed and reference_candidates
            else None
        )
        try:
            entry_at = instant(trade["placed_at"]) if trade else created
        except (KeyError, TypeError, ValueError):
            entry_at = None
        entry_candidates = [
            (clock, row)
            for clock, row in valid
            if entry_at is not None
            and clock[2] <= entry_at
            and (row.get("reference") or {}).get("closing_basis")
            not in (
                "harder_line_probability_lower_bound",
                "alternate_line_interpolation",
            )
            and _probability(row, min(kickoff, now), known_at=entry_at) is not None
        ]
        # A reported fill uses only references already retained by placement.
        # The original opportunity keeps its explicitly pinned decision model.
        if trade:
            entry_reference = (
                max(entry_candidates, key=latest_key)[1] if entry_candidates else None
            )
        else:
            entry_reference = (
                original_copy
                if _probability(original_copy, min(kickoff, now), known_at=created)
                is not None
                else None
            )
        p_entry = (
            _probability(entry_reference, min(kickoff, now), known_at=entry_at)
            if entry_reference
            else None
        )
        p_close = _probability(close_reference, kickoff) if close_reference else None
        actual = next(
            (leg for leg in actual_legs if leg.get("quote_id") == original.get("id")),
            None,
        )
        if actual is None and len(actual_legs) == len(originals):
            actual = actual_legs[index]
        try:
            cash = (
                _cashflows(original, actual if trade else None)
                if not trade or actual is not None
                else None
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            cash = None
        close_quote = latest if closed else None
        try:
            close_cash = _cashflows(close_quote) if close_quote else None
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            close_cash = None
        preview_cash = actual_cashflows(actual) if actual else cash or {}
        leg = dict(
            quote_id=original["id"],
            venue=original.get("venue"),
            observed_price=original.get("posted"),
            entry_decimal=wire(preview_cash.get("decimal")),
            cashflows={
                name + "_usd": wire(preview_cash.get(key))
                for name, key in (
                    ("entry_cost", "cost"),
                    ("win_receipt", "win"),
                    ("loss_receipt", "loss"),
                    ("push_receipt", "push"),
                )
            },
            entry_probability=wire(p_entry),
            close_probability=wire(p_close),
            entry_reference_book=(entry_reference or {})
            .get("reference", {})
            .get("book")
            if entry_reference
            else None,
            entry_reference_quote=entry_reference,
            entry_reference_at=entry_reference.get("observed_at")
            if entry_reference
            else None,
            entry_reference_gap_seconds=max(
                (entry_at - instant(p["source_at"])).total_seconds()
                for p in entry_reference["reference"]["prices"]
            )
            if entry_reference and entry_at
            else None,
            close_reference_book=(close_reference or {})
            .get("reference", {})
            .get("book")
            if close_reference
            else None,
            close_quote=close_quote,
            latest_quote=latest,
            close_reference_quote=close_reference,
            closing_fair=closing_fair(close_reference, original, p_close),
            close_reference_basis=(close_reference or {})
            .get("reference", {})
            .get("closing_basis", "exact_line"),
            close_gap_seconds=(
                kickoff - instant(close_quote["times"]["source_at"])
            ).total_seconds()
            if close_quote
            else None,
            reference_gap_seconds=max(
                (kickoff - instant(p["source_at"])).total_seconds()
                for p in close_reference["reference"]["prices"]
            )
            if close_reference
            else None,
            clv=None,
            fair_clv=None,
            probability_move=wire(p_close - p_entry)
            if p_entry is not None and p_close is not None
            else None,
            price_slippage=None,
            entry_ev=None,
            close_ev=None,
            reason=None,
        )
        if cash:
            try:
                leg["price_slippage"] = wire(
                    cash["decimal"] / posted_decimal(original) - 1
                )
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                pass
            leg["entry_ev"] = (
                wire(_ev(cash, p_entry) / cash["cost"]) if p_entry is not None else None
            )
            leg["close_ev"] = (
                wire(_ev(cash, p_close) / cash["cost"]) if p_close is not None else None
            )
            leg["fair_clv"] = (
                wire(cash["decimal"] * p_close - 1) if p_close is not None else None
            )
            try:
                if close_quote:
                    leg["clv"] = wire(cash["decimal"] / posted_decimal(close_quote) - 1)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                pass
        else:
            leg["reason"] = "After-fee cashflows are unavailable for this saved quote."
        if not latest:
            leg["reason"] = (
                "No quote with source, receipt and saved clocks before kickoff was retained."
            )
        if closed and not close_reference:
            result["reasons"].append(
                "A retained exact closing fair reference is unavailable for "
                + str(original.get("venue"))
                + "."
            )
        cashflows.append(cash)
        closing_cashflows.append(close_cash)
        entry_references.append(entry_reference)
        closing_references.append(close_reference)
        entry_probabilities.append(p_entry)
        closing_probabilities.append(p_close)
        result["legs"].append(leg)
    if closed and any(leg["close_quote"] is None for leg in result["legs"]):
        result["close_state"] = "missing"
    if all(cash is not None for cash in cashflows):
        cost = sum(cash["cost"] for cash in cashflows)
        result["entry_cost_usd"] = wire(cost)
        for label, probabilities, references in (
            ("entry", entry_probabilities, entry_references),
            ("close", closing_probabilities, closing_references),
        ):
            if all(p is not None for p in probabilities) and (
                len(originals) == 1
                or (_complementary(originals, references) and sum(probabilities) == 1)
            ):
                value = sum(
                    _ev(cash, probability)
                    for cash, probability in zip(cashflows, probabilities)
                )
                result[label + "_ev_usd"] = wire(value)
                result[label + "_ev"] = wire(value / cost)
        if len(originals) == 2:
            profits = [
                cashflows[0]["win"] + cashflows[1]["loss"] - cost,
                cashflows[0]["loss"] + cashflows[1]["win"] - cost,
            ]
            result["entry_min_profit_usd"] = wire(min(profits))
            result["entry_arb_return"] = wire(min(profits) / cost)
    if entry.get("decision") == "placed":
        settlement = settlement_result(trade, len(originals), now=now)
        result["settlement"] = settlement
        if settlement and settlement["state"] == "calculated":
            result["entry_cost_usd"] = settlement["entry_cost_usd"]
            result["realized_profit_usd"] = settlement["profit_usd"]
            result["realized_roi"] = settlement["roi"]
    if closed and all(cash is not None for cash in closing_cashflows):
        cost = sum(cash["cost"] for cash in closing_cashflows)
        result["close_cost_usd"] = wire(cost)
        if len(originals) == 2:
            profits = [
                closing_cashflows[0]["win"] + closing_cashflows[1]["loss"] - cost,
                closing_cashflows[0]["loss"] + closing_cashflows[1]["win"] - cost,
            ]
            result["close_min_profit_usd"] = wire(min(profits))
            result["close_arb_return"] = wire(min(profits) / cost)
        if all(p is not None for p in closing_probabilities) and (
            len(originals) == 1
            or (
                _complementary(originals, closing_references)
                and sum(closing_probabilities) == 1
            )
        ):
            result["close_market_ev"] = wire(
                sum(
                    _ev(cash, probability)
                    for cash, probability in zip(
                        closing_cashflows, closing_probabilities
                    )
                )
                / cost
            )
    if len(originals) == 2 and result["entry_ev"] is None:
        result["reasons"].append(
            "Arb expected value needs one consistent complementary fair reference; the paired minimum is a separate metric."
        )
    if trade and any(cash is None for cash in cashflows):
        result["reasons"].append(
            "Actual cashflows are incomplete; observed model fees are not substituted."
        )
    for actual_key, observed_key, destination in (
        ("entry_ev", "observed_ev", "ev_slippage"),
        ("entry_arb_return", "observed_arb_return", "arb_return_slippage"),
    ):
        if (
            trade
            and result.get(actual_key) is not None
            and result.get(observed_key) is not None
        ):
            result[destination] = wire(
                fraction(result[actual_key]) - fraction(result[observed_key])
            )
    if result["realized_profit_usd"] is not None and result["entry_ev_usd"] is not None:
        result["realized_minus_entry_ev_usd"] = wire(
            fraction(result["realized_profit_usd"]) - fraction(result["entry_ev_usd"])
        )
    return result
