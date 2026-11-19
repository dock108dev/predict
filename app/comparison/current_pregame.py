"""Posted-price pregame arithmetic over one occurrence's accepted current inputs."""

from fractions import Fraction as F

from app.dashboard.current_contract import price
from app.storage.store import hashed, stamp
from .cashflows import exact_wire as wire
from .pregame_reference import target
from .pregame_valuation import _fill, _cash_state, american, decimal_display, score
from .pregame_valuation_fees import retail_order
from .public_sportsbook_estimate import outcome
from .sgo_reference import (
    BEST_BOOKS,
    OPPOSITE,
    american_probability,
    no_vig_probability,
)
from .snapshot_fee_scope import applicability
from .trade_preview import order_step

VERSION = "predict-current-pregame-6"
REFERENCE_POLICY = "lowest-no-vig-two-trusted-books-2"
MIN_TRUSTED_BOOKS = 2
COMPARISON_USD = F(100)


class ReferenceInputs:
    """Index exact bookmaker pairs once for the affected occurrence."""

    def __init__(self, observations):
        self.groups = {}
        for event_id, rows in observations.items():
            for entry in rows:
                original = entry["facts"]
                q = dict(
                    original, side=original.get("canonical_side", original["side"])
                )
                if (
                    q["venue"] not in BEST_BOOKS
                    or q["period"] != "game"
                    or q["phase"] != "pregame"
                    or q.get("partition") == "three_way"
                ):
                    continue
                try:
                    line = target(q["market"], q["side"], q["line"])
                except (KeyError, ValueError, TypeError, ArithmeticError):
                    continue
                by_event = self.groups.setdefault((q["venue"], q["market"], line), {})
                sides = by_event.setdefault(event_id, {})
                sides[q["side"]] = (
                    None
                    if q["side"] in sides
                    else dict(q, input_id=entry["id"], input_revision=entry["revision"])
                )


def reference_key(record):
    event, market = record["event"], record["market_identity"]
    key = outcome(market["family"], record["selection"], event["home"], event["away"])
    if not key:
        raise ValueError("reference_outcome_identity_conflict")
    family, side, line = key
    scope = (record.get("comparison_source_metadata") or {}).get("scoring_scope") or {}
    if (
        scope.get("conflicts")
        or len(
            {
                r.get("overtime")
                for r in scope.get("evidence", ())
                if r.get("overtime") in ("included", "excluded")
            }
        )
        > 1
    ):
        raise ValueError("reference_scoring_scope_conflict")
    return family, side, target(family, side, line)


def reference(record, observations, *, at):
    """Use the lowest eligible no-vig win probability for this exact bet."""
    family, side, line = reference_key(record)
    return select_reference(
        observations,
        family=family,
        side=side,
        line=line,
        start=record["event"]["scheduled_start"],
        at=at,
    )


def reference_candidates(observations, *, family, side, line, start, at):
    """Complete same-book pairs with the shared source/receipt/occurrence guards."""
    inputs = (
        observations
        if isinstance(observations, ReferenceInputs)
        else ReferenceInputs(observations)
    )
    candidates = []
    for book in BEST_BOOKS:
        pairs = []
        for event_id, sides in inputs.groups.get((book, family, line), {}).items():
            a, b = sides.get(side), sides.get(OPPOSITE[side])
            if not a or not b:
                continue
            try:
                if not all(
                    q["available"] is True
                    and q.get("source_at")
                    and stamp(q["source_at"])
                    <= stamp(q["received_at"])
                    <= at
                    < stamp(start)
                    for q in (a, b)
                ):
                    continue
                for q in (a, b):
                    american_probability(q["price_american"])
            except (ValueError, TypeError, ArithmeticError):
                continue
            if (
                a["odd_id"] == b["opposing_odd_id"]
                and b["odd_id"] == a["opposing_odd_id"]
                and a["odd_id"] != b["odd_id"]
            ):
                pairs.append((event_id, a, b))
        if len(pairs) == 1:
            event_id, a, b = pairs[0]
            probability = no_vig_probability(
                american_probability(a["price_american"]),
                american_probability(b["price_american"]),
            )
            candidates.append(
                dict(
                    book=book,
                    probability=wire(probability),
                    fair_decimal_odds=wire(1 / probability),
                    fair_odds=american(1 / probability),
                    prices=[a, b],
                    event_id=event_id,
                    market=dict(family=family, period="full_game", line=wire(line)),
                    selected_outcome=side,
                    conditioning="decisive_completed_game",
                )
            )
    return candidates


def select_reference(observations, *, family, side, line, start, at):
    """Shared selector for collection and source-preserving snapshot revaluation."""
    candidates = reference_candidates(
        observations, family=family, side=side, line=line, start=start, at=at
    )
    if not candidates:
        raise ValueError("reference_exact_pair_unavailable")
    if len(candidates) < MIN_TRUSTED_BOOKS:
        raise ValueError("reference_two_trusted_books_required")
    # Lower fair win probability lowers EV for every supported long bet. Only
    # complete same-book pairs compete; priority is a deterministic tie-break.
    selected = min(
        candidates,
        key=lambda item: (F(item["probability"]), BEST_BOOKS.index(item["book"])),
    )
    return dict(
        selected,
        selection_policy=REFERENCE_POLICY,
        required_trusted_books=MIN_TRUSTED_BOOKS,
        trusted_book_count=len(candidates),
        # Line eligibility keeps its established priority evidence;
        # changing an EV benchmark must not relabel main/alternate lines.
        main_line_evidence=all(
            q.get("alternate") is False for q in candidates[0]["prices"]
        ),
        main_line_reference_book=candidates[0]["book"],
        candidate_probabilities={
            item["book"]: item["probability"] for item in candidates
        },
    )


def posted_fill(terms, amount, cost, fees, rule):
    """Find the maximum legal posted-price size inside the fee rounding envelope."""
    if not rule:
        return _fill(terms, amount, cost, fees, F(1))
    from app.fees.engine import posted_fee_bounds

    step = F(terms["increment"])
    stake_order = terms["kind"] == "stake"
    unit_cost = F(1) if stake_order else cost
    raw_rate, error = (F(0), F(0)) if stake_order else posted_fee_bounds(rule, cost)
    tick = step * (unit_cost + raw_rate)
    lower = max(F(1), (amount - error) // tick)
    upper = min((amount + error) // tick, amount // (step * unit_cost))

    def order(ticks):
        size = ticks * step
        legs = [(unit_cost, size)]
        wager = unit_cost * size
        entry, reserve, cash, trace = fees(legs, wager)
        return wager + entry + reserve, legs, wager, entry, reserve, cash, trace

    best = order(lower)
    if best[0] > amount:
        raise ValueError("fee_comparison_basis_invalid")
    while lower < upper:
        middle = (lower + upper + 1) // 2
        candidate = order(middle)
        if candidate[0] <= amount:
            lower, best = middle, candidate
        else:
            upper = middle - 1
    return best, None


def calculate(record, ref, fee, *, at, game_key, amount=COMPARISON_USD):
    """Use tested fee, cashflow and score functions; depth never enters this model."""
    q, market = record["quote"], record["market_identity"]
    from app.storage.current_rows import contract_id

    cid = contract_id(record)
    row = dict(
        id=cid,
        venue=q["venue"],
        league=record["event"]["competition"],
        source=q["source"],
        original=q["original"],
        times=q["times"],
        captured_at=at.isoformat(),
        start_at=record["event"]["scheduled_start"],
        game_state="scheduled",
        market=dict(
            market="winner" if market["family"] == "moneyline" else market["family"],
            period=market["period"],
        ),
        fee_applicability=applicability(record),
        trade_fee=fee,
    )
    cost = price(row)
    if not 0 < cost < 1:
        raise ValueError("posted_price_invalid")
    quantity_step = order_step(row)
    if configured := (fee.get("evidence") or {}).get("database_fee_rule"):
        if q["source"]["provider"] == "sportsgameodds":
            quantity_step = (
                None
                if configured["formula"] == "prophetx_commission"
                else F(configured["quantity_step"])
            )
    stake = (
        q["original"]["units"] in ("american_odds", "decimal_odds")
        and quantity_step is None
    )
    step = F("0.01") if stake else quantity_step or F(1)
    terms = dict(
        kind="stake" if stake else "exchange",
        order_type="straight_stake" if stake else "taker",
        increment=wire(step),
        minimum=wire(step),
        maximum=wire(amount) if stake else None,
        evidence_class="public_estimate",
        pricing_model="posted_price",
        revision=VERSION,
    )
    if not stake:
        terms["asks"] = [dict(price=wire(cost), quantity=wire(amount / cost))]
    fees, evidence, _ = retail_order(row, terms, cost, fee)
    (committed, legs, wager, entry, reserve, cash, trace), reason = posted_fill(
        terms,
        amount,
        cost,
        fees,
        (fee.get("evidence") or {}).get("database_fee_rule"),
    )
    # Posted-price normalization accepts the largest legal quantity below $100;
    # the execution preview's fill tolerance is not an eligibility condition.
    if committed <= 0:
        raise ValueError(reason or "fee_comparison_basis_invalid")
    gross = wager / cost if stake else sum(quantity for _, quantity in legs)
    settlement = dict(
        venue_rules=dict(cashflow_states={"win": "ordinary_win", "loss": "zero"})
    )
    states = {}
    for state in ("win", "loss"):
        _, states[state] = _cash_state(
            state,
            ordinary_win=gross,
            stake=wager,
            committed=committed,
            entry=entry,
            reserve=reserve,
            fee_terms=cash,
            settlement=settlement,
        )
    after = F(states["win"]["net_receipt_usd"]) / committed
    ev, opportunity = None, None
    if ref is not None:
        ev, _, opportunity = cashflow_values(ref, states, committed)
    selection = record["selection"]
    side = outcome(
        market["family"], selection, record["event"]["home"], record["event"]["away"]
    )[1]
    canonical_line = reference_key(record)[2]
    bet = hashed(
        [game_key, market["period"], market["family"], wire(canonical_line), side]
    )
    main = main_line(record, ref or {"prices": [{}]})
    result = dict(
        id=cid,
        game_key=game_key,
        bet_id=bet,
        venue=q["venue"],
        league=row["league"],
        game=record["event"]["title"],
        kickoff=row["start_at"],
        family=market["family"],
        period=market["period"],
        selection=selection,
        selection_label=next(
            (
                name
                for name, team in record["event"].get("participants", {}).items()
                if team == selection.get("participant")
            ),
            selection.get("participant"),
        ),
        main=main,
        posted=q["original"],
        source=q["source"],
        times=q["times"],
        reference=ref,
        arb_key=hashed(
            [game_key, market["period"], market["family"], wire(canonical_line)]
        ),
        side=side,
        scoring_scope=(record.get("comparison_source_metadata") or {}).get(
            "scoring_scope"
        ),
        fee=dict(
            evidence=evidence,
            classification=fee["classification"],
            cashflows=states,
            entry_usd=wire(entry),
            reserve_usd=wire(reserve),
            rounding_trace=trace,
            comparison_basis_usd=wire(amount),
            committed_usd=wire(committed),
        ),
        raw=dict(
            posted_decimal=wire(1 / cost),
            after_fee_decimal=wire(after),
            fair_decimal=ref["fair_decimal_odds"] if ref else None,
            net_ev=wire(ev) if ev is not None else None,
            opportunity_score=wire(opportunity) if opportunity is not None else None,
            expected_profit_usd=wire(committed * ev) if ev is not None else None,
        ),
        display=dict(
            posted_odds=american(1 / cost),
            after_fees=american(after) or decimal_display(after, 4),
            fair_odds=ref["fair_odds"] if ref else None,
            net_ev=decimal_display(ev * 100, signed=True) + "%"
            if ev is not None
            else None,
            opportunity_score=decimal_display(opportunity, 0)
            if opportunity is not None
            else None,
        ),
        version=VERSION,
        calculated_at=at.isoformat(),
    )

    return result


def cashflow_values(reference, states, committed):
    p = F(reference["probability"])
    probabilities = dict(win=p, loss=1 - p)
    ratios = {
        state: F(value["net_receipt_usd"]) / committed - 1
        for state, value in states.items()
    }
    ev = sum(probabilities[state] * ratios[state] for state in states)
    after = F(states["win"]["net_receipt_usd"]) / committed
    return ev, after, score(probabilities, ratios, ev)


def revalue_reference(payload, reference, *, at):
    """Revalue a frozen offer; original prices, cashflows, fees and clocks survive."""
    from copy import deepcopy

    result = deepcopy(payload)
    committed = F(result["fee"]["committed_usd"])
    ev, _, opportunity = cashflow_values(
        reference, result["fee"]["cashflows"], committed
    )
    result.update(reference=reference, version=VERSION, calculated_at=at.isoformat())
    result["raw"].update(
        fair_decimal=reference["fair_decimal_odds"],
        net_ev=wire(ev) if ev is not None else None,
        opportunity_score=wire(opportunity) if opportunity is not None else None,
        expected_profit_usd=wire(committed * ev) if ev is not None else None,
    )
    result["display"].update(
        fair_odds=reference["fair_odds"],
        net_ev=decimal_display(ev * 100, signed=True) + "%",
        opportunity_score=decimal_display(opportunity, 0),
    )
    result["input_revision"] = hashed(
        [payload["input_revision"], REFERENCE_POLICY, reference]
    )
    return result


def main_line(record, reference):
    alternate = (record.get("comparison_source_metadata") or {}).get("alternate")
    if record["market_identity"]["family"] == "moneyline":
        return alternate is not True
    return (
        alternate is False
        or alternate is not True
        and reference.get(
            "main_line_evidence",
            all(p.get("alternate") is False for p in reference["prices"]),
        )
    )
