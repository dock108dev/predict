"""Versioned paper portfolios over frozen evidence. Never submits an order.

Tickets are deterministic projections of immutable T-10 receipts, rather than
claims that a bet was entered at that time. Exports carry their sizing witnesses.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone
from fractions import Fraction as F
from zoneinfo import ZoneInfo

from app.comparison import current_pregame as math
from app.comparison.pregame_valuation import decimal_display, score
from app.storage.store import hashed, stamp
from .ev_movement import exact_bet_identity, offer_measurements

POLICY = dict(
    version="paper-tminus10-quarter-kelly-4pct-1", league="NCAAB",
    default_date="2026-11-23", timezone="America/New_York",
    minimum_ev="1/25", reference_bankroll_usd="10000", kelly_multiplier="1/4",
    sizing_scale_usd="2500", baseline="-110 at 4% EV commits $110 before extra fees",
    checkpoint="late", target_seconds_before_start=600, tolerance_seconds=60,
    portfolios=["best_venue", "all_venues"], intraday_compounding=False,
    budget_cap=None, execution="paper_only; unlimited size at captured posted price; no depth proof",
    selection="unrounded captured screening EV >= 4%; recheck at sized cash commitment",
    fees="preserve each capture's actual fee mode; never silently enable or disable fees",
    duplicates="one ticket per exact bet per venue; best_venue removes venue identity only",
    settlement="decisive sporting results model win/loss; pushes, voids and unverified changes unresolved",
)
POLICY_ID = hashed(POLICY)
SCALE = F(POLICY["sizing_scale_usd"])
MINIMUM = F(POLICY["minimum_ev"])


def cents(value):
    return F(int(F(value) * 100), 100)


def money(value):
    return decimal_display(F(value), 2)


def kelly_budget(payload, *, scale=SCALE):
    fee = payload["fee"]
    committed = F(fee["committed_usd"])
    if committed <= 0 or set(fee["cashflows"]) != {"win", "loss"}:
        raise ValueError("unsupported_cashflow_states")
    p = F(payload["reference"]["probability"])
    if not 0 < p < 1:
        raise ValueError("probability_invalid")
    ratios = {k: F(v["net_receipt_usd"]) / committed - 1 for k, v in fee["cashflows"].items()}
    ev = p * ratios["win"] + (1-p) * ratios["loss"]
    return cents(scale * score(dict(win=p, loss=1-p), ratios, ev) / 10000), ev


def sized_offer(offer, *, at, game_id, minimum=MINIMUM, scale=SCALE):
    """Reprice using captured fee inputs, including quantity grids and rounding.

    Iterate the same Kelly rule at the actual amount; on a rounding oscillation
    use the smaller target. Never scale the original $100 fee receipt linearly.
    """
    original = offer["calculation_payload"]
    if not isinstance(offer.get("fee_input"), dict):
        raise ValueError("captured_fee_inputs_unavailable")
    target, _ = kelly_budget(original, scale=scale)
    seen = set()
    result = None
    for _ in range(12):
        if target <= 0:
            raise ValueError("kelly_below_one_cent")
        priced_target = target
        result = math.calculate(offer["record"], original["reference"], offer["fee_input"],
                                at=stamp(at), game_key=game_id, amount=priced_target)
        next_target, ev = kelly_budget(result, scale=scale)
        committed = F(result["fee"]["committed_usd"])
        if ev < minimum:
            reason = "sized_ev_below_4pct" if minimum == MINIMUM else "sized_ev_below_minimum"
            raise ValueError(reason)
        if next_target == target or next_target in seen:
            if committed <= next_target:
                return result, target
            target = min(target, next_target)
        else:
            seen.add(target)
            target = next_target
    if result and F(result["fee"]["committed_usd"]) <= kelly_budget(result, scale=scale)[0]:
        return result, priced_target
    raise ValueError("kelly_sizing_did_not_converge")


def grade(identity, outcome, sized):
    """Model decisive sporting cashflows; never imply venue settlement."""
    from .records import resolved_side
    data = (outcome or {}).get("data") or {}
    if not data or not data.get("final"):
        return dict(state="unresolved", reason="no_final_sporting_result", pnl_usd=None, released_at=None)
    line = identity["line"]
    if identity["family"] == "spread" and identity["outcome"] == "away":
        line = str(-F(line))
    side, reason = resolved_side(dict(family=identity["family"], period=identity["period"], line=line), data)
    if reason:
        return dict(state="unresolved", reason=reason, pnl_usd=None, released_at=None)
    state = "win" if side == identity["outcome"] else "loss"
    fee = sized["fee"]
    pnl = F(fee["cashflows"][state]["net_receipt_usd"]) - F(fee["committed_usd"])
    return dict(state=state, reason="modeled_from_sporting_result; venue_settlement_unverified",
                pnl_usd=money(pnl), pnl_exact_usd=str(pnl), released_at=(outcome or {}).get("known_at"))


def candidates(snapshot, *, game_id, checkpoint_id, at, outcome=None, minimum=MINIMUM, policy=None):
    policy_id, scale = POLICY_ID, SCALE
    if policy is not None:
        policy_id, minimum, scale = hashed(policy), F(policy["minimum_ev"]), F(policy["sizing_scale_usd"])
    tickets, excluded, conflicts = {}, Counter(), set()
    for index, offer in enumerate(snapshot.get("offers", [])):
        try:
            identity = exact_bet_identity(offer["record"], event_identity=game_id)
            measurement = offer_measurements(offer, offer_index=index, captured_at=at)
            raw_ev = measurement["screen"]["ev"]
            if raw_ev is None:
                excluded[measurement["screen"].get("reason") or "ev_unavailable"] += 1
                continue
            if F(raw_ev) < minimum or F(raw_ev) <= 0:
                excluded["below_minimum_ev"] += 1
                continue
            if policy is not None or minimum == MINIMUM:
                sized, target = sized_offer(offer, at=at, game_id=game_id, minimum=minimum, scale=scale)
            else:
                sized, target = offer["calculation_payload"], None
            key = identity["id"]
            if key in conflicts:
                excluded["conflicting_duplicate_offer"] += 1
                continue
            # Provider/book are delivery identities. Material settlement and
            # scoring terms remain in the cross-venue equivalence key.
            equivalent = {k: v for k, v in identity.items() if k not in ("id", "provider", "book", "venue")}
            fee = sized["fee"]
            ev = F(sized["raw"]["net_ev"])
            ticket = dict(id=hashed([policy_id, checkpoint_id, key]), exact_bet_id=key,
                equivalent_bet_id=hashed(equivalent), game_id=game_id,
                checkpoint_id=checkpoint_id, decision_at=at,
                title=snapshot["event"].get("title") or " at ".join((snapshot["event"].get("away", "Away"), snapshot["event"].get("home", "Home"))),
                starts_at=snapshot["event"]["scheduled_start"], venue=identity["venue"],
                family=identity["family"], period=identity["period"], side=identity["outcome"],
                line=identity["line"], label=sized.get("selection_label") or identity["outcome"],
                posted_odds=(sized.get("display") or {}).get("posted_odds") or str(measurement["price"]),
                probability=measurement["screen"]["probability"], screen_ev=str(F(raw_ev)), ev=str(ev),
                stake_usd=money(fee["committed_usd"]), purchase_usd=money(fee.get("purchase_usd", fee["committed_usd"])),
                cash_commitment_usd=str(F(fee["committed_usd"])),
                kelly_budget_usd=money(target) if target is not None else None,
                expected_profit_usd=money(F(fee["committed_usd"])*ev),
                expected_profit_exact_usd=str(F(fee["committed_usd"])*ev),
                fee_mode=measurement.get("fee_mode") or snapshot.get("fee_mode"),
                times=measurement["times"], identity=identity,
                grading=grade(identity, outcome, sized),
                witness=dict(original_offer=offer, sized_calculation=sized))
            if key in tickets:
                # Conflicting duplicate rows are incomplete evidence, not two bets.
                if tickets[key]["witness"] != ticket["witness"]:
                    del tickets[key]
                    conflicts.add(key)
                    raise ValueError("conflicting_duplicate_offer")
                excluded["duplicate_offer"] += 1
            else:
                if policy is not None:
                    ticket["offer_index"] = index
                tickets[key] = ticket
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            excluded[str(exc) if isinstance(exc, ValueError) else "sizing_inputs_incomplete"] += 1
    return list(tickets.values()), dict(excluded)


def portfolios(tickets, *, as_of):
    best = {}
    for ticket in tickets:
        key = ticket["equivalent_bet_id"]
        if key not in best or (-F(ticket["ev"]), ticket["venue"], ticket["id"]) < (
                -F(best[key]["ev"]), best[key]["venue"], best[key]["id"]):
            best[key] = ticket
    return {name: summarize(values, as_of=as_of) for name, values in
            (("best_venue", list(best.values())), ("all_venues", tickets))}


def summarize(tickets, *, as_of):
    venues, games, flows = defaultdict(F), defaultdict(F), []
    unresolved_games, unresolved_venues = defaultdict(F), defaultdict(F)
    days = set()
    turnover = expected = resolved_expected = pnl = unresolved_turnover = F(0)
    resolved = 0
    zone = ZoneInfo(POLICY["timezone"])
    for ticket in tickets:
        stake = F(ticket.get("cash_commitment_usd", ticket["stake_usd"]))
        profit = F(ticket.get("expected_profit_exact_usd", ticket["expected_profit_usd"]))
        turnover += stake
        expected += profit
        venues[ticket["venue"]] += stake
        games[ticket["game_id"]] += stake
        days.add(stamp(ticket["starts_at"]).astimezone(zone).date())
        flows.append((stamp(ticket["decision_at"]), 1, stake))
        grading = ticket["grading"]
        if grading["pnl_usd"] is not None:
            resolved += 1
            resolved_expected += profit
            pnl += F(grading.get("pnl_exact_usd", grading["pnl_usd"]))
            if grading["released_at"] and stamp(grading["released_at"]) <= stamp(as_of):
                flows.append((stamp(grading["released_at"]), 0, -stake))
        else:
            unresolved_turnover += stake
            unresolved_games[ticket["game_id"]] += stake
            unresolved_venues[ticket["venue"]] += stake
    current = peak = F(0)
    for _, _, amount in sorted(flows):
        current += amount
        peak = max(current, peak)
    return dict(tickets=sorted(tickets, key=lambda t: (t["starts_at"], t["title"], t["family"], t["id"])),
        count=len(tickets), turnover_usd=money(turnover), expected_profit_usd=money(expected),
        unique_games=len(games), days_represented=len(days), resolved_expected_profit_usd=money(resolved_expected),
        peak_committed_usd=money(peak), outstanding_usd=money(current),
        modeled_resolved_pnl_usd=money(pnl), resolved=resolved, unresolved=len(tickets)-resolved,
        unresolved_turnover_usd=money(unresolved_turnover), unresolved_exposure_usd=money(unresolved_turnover),
        unresolved_by_game={k: money(v) for k, v in sorted(unresolved_games.items())},
        unresolved_by_venue={k: money(v) for k, v in sorted(unresolved_venues.items())},
        by_venue={k: money(v) for k, v in sorted(venues.items())},
        by_game={k: money(v) for k, v in sorted(games.items())})


def report(db, day=POLICY["default_date"], *, evidence=False, policy=None):
    """Passive backtest, independent of early-positive retention and live prices."""
    from . import experiment as owner
    date.fromisoformat(day)
    frozen_policy = policy or POLICY
    policy_id = hashed(frozen_policy)
    at = datetime.now(timezone.utc).isoformat()
    games = list(db.execute("""SELECT * FROM public.ev_experiment_game
        WHERE event->>'league'=%s AND
        ((event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date=%s::date
        ORDER BY (event->>'starts_at')::timestamptz,id""", (frozen_policy["league"], day)))
    tickets, dispositions, exclusions = [], [], Counter()
    outcome_evidence = {}
    for game in games:
        checkpoint = owner._checkpoint_view(db, game, "late")
        original_status = checkpoint["status"]
        recovered_id = frozen_policy.get("recovered_checkpoints", {}).get(game["id"])
        if recovered_id:
            index = owner._closure(db, [recovered_id])
            row = index[recovered_id]
            recovered = owner._value(row, index)
            if (row["game_id"] != game["id"] or row["kind"] != "checkpoint"
                    or recovered.get("source_kind") != "retrospective_raw_t10"
                    or recovered["schedule_id"] != game["schedule_id"]
                    or recovered["target_at"] != checkpoint["target_at"]
                    or recovered["deadline_at"] != checkpoint["deadline_at"]
                    or not stamp(checkpoint["target_at"]) <= stamp(recovered["received_at"]) <= stamp(checkpoint["deadline_at"])):
                raise ValueError("recovery_checkpoint_ineligible")
            checkpoint = dict(recovered, id=recovered_id, persisted_at=owner.clock(row["recorded_at"]))
        status = checkpoint["status"]
        entry = dict(game_id=game["id"], title=game["event"]["title"], starts_at=game["event"]["starts_at"],
                     status=status, reason=checkpoint.get("reason"), checkpoint_id=checkpoint.get("id"), tickets=0)
        if status in ("pending", "claimed") and stamp(checkpoint["deadline_at"]) < stamp(at):
            entry.update(status="missed", reason="capture_window_closed")
        if policy is not None:
            entry.update(schedule_id=game["schedule_id"], outcome_id=None if frozen_policy.get("defer_results") else game.get("outcome_id"),
                target_at=checkpoint["target_at"], deadline_at=checkpoint["deadline_at"],
                attempt_ids=[row["id"] for row in db.execute("""SELECT id FROM public.ev_experiment_record
                    WHERE game_id=%s AND kind='attempt' AND checkpoint='late' ORDER BY recorded_at,id""", (game["id"],))])
        if status in ("captured", "reconstructed"):
            snapshot = checkpoint["snapshot"]
            outcome = None
            if game.get("outcome_id") and not frozen_policy.get("defer_results"):
                index = owner._closure(db, [game["outcome_id"]])
                outcome = owner._value(index[game["outcome_id"]], index)
                outcome_evidence[game["id"]] = dict(id=game["outcome_id"], **outcome)
            found, gaps = candidates(snapshot, game_id=game["id"], checkpoint_id=checkpoint["id"],
                at=checkpoint["received_at"] if recovered_id else checkpoint["persisted_at"], outcome=outcome, policy=policy)
            if recovered_id:
                entry.update(original_capture_status=original_status, reconstructed_at=checkpoint["persisted_at"],
                             recovery=checkpoint["recovery"])
                for ticket in found:
                    ticket.update(source_kind="retrospective_raw_t10", reconstructed_at=checkpoint["persisted_at"])
            if frozen_policy.get("defer_results"):
                for ticket in found:
                    ticket["grading"] = dict(state="unresolved", reason="results_integration_deferred", pnl_usd=None, released_at=None)
            if outcome and outcome.get("schedule_id") != checkpoint.get("schedule_id"):
                for ticket in found:
                    ticket["grading"] = dict(state="unresolved", reason="result_schedule_changed", pnl_usd=None, released_at=None)
            tickets.extend(found)
            exclusions.update(gaps)
            entry.update(tickets=len(found), coverage=snapshot.get("coverage"),
                         fee_mode=snapshot.get("fee_mode"), exclusions=gaps)
        dispositions.append(entry)
    values = portfolios(tickets, as_of=at)
    result = dict(policy=deepcopy(frozen_policy), policy_id=policy_id, date=day, as_of=at,
        designation=("Opportunity record only; original frozen checkpoints plus explicitly reconstructed T−10 raw responses; results deferred"
                     if frozen_policy.get("recovered_checkpoints") else
                     "Retrospective paper replay of frozen T−10 evidence; no actual orders or fills"),
        portfolio_revision=hashed([policy_id, day, sorted(t["id"] for t in tickets)]),
        tracked_games=len(games), captured_games=sum(g["status"] == "captured" for g in dispositions),
        games=dispositions, exclusions=dict(exclusions), portfolios=values,
        coverage=("tracked_games_only; no later prices or inferred missing markets" if frozen_policy.get("recovered_checkpoints")
                  else "tracked_games_only; missing/untracked games cannot be reconstructed"),
        outcome_evidence=outcome_evidence if evidence else {}, provider_requests=0, orders_submitted=0)
    if frozen_policy.get("recovered_checkpoints"):
        result["reconstructed_games"] = sum(g["status"] == "reconstructed" for g in dispositions)
    if not evidence:
        for portfolio in values.values():
            portfolio["tickets"] = [{k: v for k, v in t.items() if k != "witness"} for t in portfolio["tickets"]]
    result["report_revision"] = hashed([policy_id, day, dispositions,
        {k: dict(v, tickets=[{a: b for a, b in t.items() if a != "witness"} for t in v["tickets"]])
         for k, v in values.items()}])
    return result
