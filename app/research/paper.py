"""Versioned paper portfolios over frozen evidence. Never submits an order.

Tickets are deterministic projections of immutable T-10 receipts, rather than
claims that a bet was entered at that time. Exports carry their sizing witnesses.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction as F
from zoneinfo import ZoneInfo

from app.comparison import current_pregame as math
from app.comparison import fixed_profit
from app.comparison.pregame_valuation import decimal_display, score
from app.storage.store import hashed, stamp
from . import paper_depth
from .ev_movement import _role, exact_bet_identity, offer_measurements

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
FIXED_PROFIT_RULE = fixed_profit.RULE
KELLY_RULE = "iterative-posted-fees-cent-budget-1"
MAIN_FIRST_ONE_PER_GAME = "main_first_one_per_game"
MAIN_SPREADS_TOTALS = "main_spreads_totals"


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


def _line_scope(identity):
    return hashed([identity["family"], identity["period"], identity["settlement"]])


def _comparable_line(identity):
    line = F(identity["line"])
    # The away side's +3 and the home side's −3 describe the same spread line.
    return -line if identity["family"] == "spread" and identity["outcome"] == "away" else line


def _main_anchors(snapshot, game_id):
    """Use observed venue roles, including main offers that will fail eligibility."""
    anchors = defaultdict(lambda: defaultdict(dict))
    for index, offer in enumerate(snapshot.get("offers", [])):
        try:
            record = offer["record"]
            if record["quote"]["state"] != "available" or _role(record)["status"] != "main":
                continue
            identity = exact_bet_identity(record, event_identity=game_id)
            if identity["family"] == "moneyline":
                continue
            line = _comparable_line(identity)
            anchors[_line_scope(identity)][identity["venue"]].setdefault(line, index)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            continue
    return anchors


def _selection_evidence(identity, line_role, anchors):
    evidence = dict(line_role=line_role)
    if identity["family"] == "moneyline":
        if identity["settlement"]["outcome_cardinality"] == 2:
            return dict(evidence, tier="main", basis="two_way_moneyline")
        return dict(evidence, tier="unranked", reason="two_way_moneyline_unverified")

    venue = identity["venue"]
    sources = anchors.get(_line_scope(identity), {})
    if venue in sources:
        entries = {line: (venue, index) for line, index in sources[venue].items()}
        basis = "venue_main_line"
    else:
        entries = {line: (other, index) for other in sorted(sources, reverse=True)
                   for line, index in sources[other].items()}
        basis = "other_venue_main_line"
    if len(entries) != 1:
        reason = "main_line_anchor_conflict" if entries else "main_line_anchor_unavailable"
        return dict(evidence, tier="unranked", reason=reason)
    (line, (anchor_venue, offer_index)), = entries.items()
    distance = abs(_comparable_line(identity) - line)
    tier = "main" if line_role == "main" and venue == anchor_venue and distance == 0 else "nearby_alternate"
    return dict(evidence, tier=tier, basis=basis, distance_points=str(distance),
                anchor=dict(line=str(line), venue=anchor_venue, offer_index=offer_index))


def _market_exclusion(record, alternate_price_floor):
    market = record["market_identity"]
    if market["period"] != "full_game" or market["family"] not in ("spread", "total"):
        return "outside_selected_market_scope"
    role = _role(record)["status"]
    if role == "main":
        return None
    if role != "alternate" or alternate_price_floor is None:
        return "line_role_outside_selected_market_scope"
    quote = record["quote"]
    try:
        if quote["original"]["units"] not in ("american_odds", "decimal_odds", "cents_per_contract", "usd_per_contract"):
            return "alternate_posted_odds_unavailable"
        price = math.price(quote)
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return "alternate_posted_odds_unavailable"
    if not 0 < price < 1:
        return "alternate_posted_odds_unavailable"
    if price <= alternate_price_floor:
        return "alternate_posted_odds_at_or_above_limit"
    return None


def _depth_candidate(offer, measurement, identity, index, quote_id, anchors, depth, *, target, minimum):
    from app.comparison import experiment_depth_execution
    from app.storage import experiment_depth

    record = offer["record"]
    receipt = experiment_depth.receipt_for(offer, depth["observations"])
    if receipt is None:
        venue = identity["venue"]
        reason = ("authenticated_taker_depth_unavailable" if venue == "prophetx"
                  else depth["source_gaps"].get(venue) or depth["reason"])
        if reason:
            receipt = {"reason": reason}
    result, calculation = experiment_depth_execution.evaluate(offer, receipt, at=depth["target_at"],
        game_key=identity["event"], target=target, minimum=minimum, **depth["execution_version"])
    # A selected order trace is already retained in sized_calculation.fee.
    # Rejected and partial cases can be reevaluated from the immutable bundle.
    result.pop("modeled_fills", None)
    if receipt and receipt.get("receipt_refs"):
        result["receipt_refs"] = receipt["receipt_refs"]
    selection = _selection_evidence(identity, _role(record)["status"], anchors)
    row = dict(frozen_quote_id=quote_id, offer_index=index, exact_bet_id=identity["id"],
        venue=identity["venue"], family=identity["family"], period=identity["period"],
        side=identity["outcome"], line=identity["line"], portfolio_selection=selection,
        label=(offer.get("calculation_payload") or {}).get("selection_label") or identity["outcome"],
        posted_odds=(offer.get("calculation_payload", {}).get("display") or {}).get("posted_odds"),
        screen_ev=measurement["screen"]["ev"], depth=result)
    depth["candidates"].append(row)
    return result, calculation


def candidates(snapshot, *, game_id, checkpoint_id, at, outcome=None, minimum=MINIMUM, policy=None, counts=None,
               depth=None):
    policy_id, scale, mode, target_profit, minimum_stake = POLICY_ID, SCALE, None, None, None
    if policy is not None:
        policy_id, minimum = hashed(policy), F(policy["minimum_ev"])
        if policy.get("minimum_stake_usd") is not None:
            minimum_stake = F(policy["minimum_stake_usd"])
        mode = policy.get("sizing_mode")
        if mode == "fixed_profit":
            if policy.get("sizing_rule") != FIXED_PROFIT_RULE:
                raise ValueError("fixed_profit_rule_unsupported")
            target_profit = F(policy["target_profit_usd"])
        else:
            scale = F(policy["sizing_scale_usd"])
    anchors = (_main_anchors(snapshot, game_id)
               if policy and policy.get("portfolio_rule") == MAIN_FIRST_ONE_PER_GAME else None)
    limit_market = policy and policy.get("market_scope") == MAIN_SPREADS_TOTALS
    alternate_odds = policy.get("alternate_odds_below") if limit_market else None
    # Winning $400 profit on $100 stake implies an exact contract price of 1/5.
    alternate_price_floor = 100 / (100 + F(alternate_odds)) if alternate_odds is not None else None
    tickets, excluded, conflicts = {}, Counter(), set()
    for index, offer in enumerate(snapshot.get("offers", [])):
        sizing_stage = False
        exclusion_details = None
        try:
            if limit_market and (reason := _market_exclusion(offer["record"], alternate_price_floor)):
                excluded[reason] += 1
                continue
            identity = exact_bet_identity(offer["record"], event_identity=game_id)
            measurement = offer_measurements(offer, offer_index=index, captured_at=at)
            raw_ev = measurement["screen"]["ev"]
            if raw_ev is None:
                excluded[measurement["screen"].get("reason") or "ev_unavailable"] += 1
                continue
            if counts is not None:
                counts["evaluated_offers"] += 1
            passes_screen = F(raw_ev) >= minimum and F(raw_ev) > 0
            # A same-side main line can supply the capacity control even when it fails EV.
            is_control = (depth is not None and identity["venue"] == "novig"
                          and _role(offer["record"])["status"] == "main")
            if not passes_screen and not is_control:
                excluded["below_minimum_ev"] += 1
                continue
            key = identity["id"]
            quote_id = hashed([checkpoint_id, index, key]) if mode or minimum_stake is not None else None
            sizing_stage = True
            if depth is not None:
                execution, sized = _depth_candidate(offer, measurement, identity, index, quote_id, anchors,
                    depth, target=target_profit, minimum=minimum)
                if not passes_screen:
                    execution.update(eligible=False, selection_exclusion="below_minimum_screen_ev")
                    excluded["below_minimum_ev"] += 1
                    continue
                if not execution["eligible"]:
                    raise ValueError(execution["reason"] or execution["status"])
                target = None
            elif mode == "fixed_profit":
                if not isinstance(offer.get("fee_input"), dict):
                    raise ValueError("captured_fee_inputs_unavailable")
                sized = fixed_profit.calculate(offer, at=stamp(at), game_key=game_id, target=target_profit)
                target = None
                if F(sized["raw"]["net_ev"]) < minimum:
                    reason = "sized_ev_below_4pct" if minimum == MINIMUM else "sized_ev_below_minimum"
                    raise ValueError(reason)
            elif policy is not None or minimum == MINIMUM:
                sized, target = sized_offer(offer, at=at, game_id=game_id, minimum=minimum, scale=scale)
            else:
                sized, target = offer["calculation_payload"], None
            if minimum_stake is not None:
                commitment = F(sized["fee"]["committed_usd"])
                if commitment < minimum_stake:
                    if depth is not None:
                        execution.update(eligible=False, selection_exclusion="sized_stake_below_minimum")
                    exclusion_details = dict(cash_commitment_usd=str(commitment),
                        minimum_stake_usd=str(minimum_stake), sized_ev=str(F(sized["raw"]["net_ev"])))
                    raise ValueError("sized_stake_below_minimum")
            sizing_stage = False
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
            if mode:
                sizing = (sized["sizing"] if mode == "fixed_profit" else dict(mode="kelly",
                    rule=policy.get("sizing_rule", KELLY_RULE), kelly_budget_usd=str(target),
                    reference_bankroll_usd=policy.get("reference_bankroll_usd"),
                    kelly_multiplier=policy.get("kelly_multiplier")))
                ticket.update(frozen_quote_id=quote_id, sizing=sizing)
            if depth is not None:
                ticket["depth"] = execution
                ticket["fee_mode"] = dict(version=execution["version"], enabled=True,
                    assumption="Versioned public venue fees applied to modeled book fills.")
            if anchors is not None:
                ticket["portfolio_selection"] = _selection_evidence(identity, _role(offer["record"])["status"], anchors)
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
        except (ValueError, KeyError, TypeError, ArithmeticError, OSError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "sizing_inputs_incomplete"
            excluded[reason] += 1
            if sizing_stage and counts is not None and quote_id is not None:
                counts.setdefault("sizing_exclusions", []).append(dict(frozen_quote_id=quote_id,
                    offer_index=index, exact_bet_id=key, reason=reason, **(exclusion_details or {})))
    return list(tickets.values()), dict(excluded)


def best_order(ticket):
    return -F(ticket["ev"]), ticket["venue"], ticket.get("frozen_quote_id") or ticket["id"]


def _main_order(ticket):
    evidence = ticket["portfolio_selection"]
    return (evidence["tier"] != "main", F(evidence.get("distance_points", 0)), -F(ticket["probability"]))


def best_tickets(tickets, portfolio_rule=None):
    """Use the top sized EV quote per bet, optionally after choosing one bet per game."""
    best = {}
    ranked = {}
    for ticket in tickets:
        key = ticket["equivalent_bet_id"]
        if key not in best or best_order(ticket) < best_order(best[key]):
            best[key] = ticket
        if (portfolio_rule == MAIN_FIRST_ONE_PER_GAME
                and ticket.get("portfolio_selection", {}).get("tier") in ("main", "nearby_alternate")):
            order = _main_order(ticket), best_order(ticket)
            if key not in ranked or order < ranked[key][0]:
                ranked[key] = order, ticket
    if portfolio_rule != MAIN_FIRST_ONE_PER_GAME:
        return list(best.values())

    games = {}
    for bet, ((rank, _), witness) in ranked.items():
        quote = best[bet]
        game = quote["game_id"]
        order = rank, best_order(quote)
        if game not in games or order < games[game][0]:
            evidence = dict(witness["portfolio_selection"],
                ranked_quote_venue=witness["venue"], ranked_quote_id=witness.get("frozen_quote_id") or witness["id"],
                fair_probability=witness["probability"],
                selected_quote_line_role=quote.get("portfolio_selection", {}).get("line_role", "unknown"))
            games[game] = order, dict(quote, portfolio_selection=evidence)
    return [games[game][1] for game in sorted(games)]


def portfolios(tickets, *, as_of, portfolio_rule=None):
    return {name: summarize(values, as_of=as_of) for name, values in
            (("best_venue", best_tickets(tickets, portfolio_rule)), ("all_venues", tickets))}


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


def scoped_candidates(entry, checkpoint, policy, *, depth_bundle=None):
    """Reprice a saved checkpoint and report its observed and evaluated offers."""
    snapshot = checkpoint["snapshot"]
    counts = dict(observed_offer_count=len(snapshot.get("offers", [])), evaluated_offers=0)
    reconstructed = entry["status"] == "reconstructed"
    at = checkpoint["received_at"] if reconstructed else checkpoint["persisted_at"]
    depth = None
    if policy.get("depth_policy"):
        depth = dict(target_at=checkpoint["target_at"], candidates=[],
                     observations=(depth_bundle or {}).get("observations", {}),
                     reason=(depth_bundle or {}).get("reason"),
                     source_gaps=(depth_bundle or {}).get("source_gaps", {}),
                     execution_version=({"version": policy["depth_execution_version"]}
                                        if policy.get("depth_execution_version") else {}))
        entry["depth_receipt_id"] = (depth_bundle or {}).get("id")
        if depth_bundle:
            entry["depth_metrics"] = depth_bundle.get("metrics", {})
    tickets, gaps = candidates(snapshot, game_id=entry["game_id"], checkpoint_id=entry["checkpoint_id"],
                               at=at, policy=policy, counts=counts, depth=depth)
    if depth is not None:
        quoted_policy = {key: value for key, value in policy.items()
                         if key not in ("depth_policy", "depth_receipts", "depth_execution_version")}
        quoted_policy["execution"] = POLICY["execution"]
        quoted, _ = candidates(snapshot, game_id=entry["game_id"], checkpoint_id=entry["checkpoint_id"],
                               at=at, policy=quoted_policy)
        entry.update(depth_candidates=depth["candidates"],
                     depth_comparison=paper_depth.compare_game(quoted, tickets, depth["candidates"],
                         rank=lambda pool: best_tickets(pool, policy["portfolio_rule"])))
    entry.update(counts, tickets=len(tickets), coverage=snapshot.get("coverage"),
                 fee_mode=snapshot.get("fee_mode"), exclusions=gaps,
                 **{key: checkpoint.get(key) for key in
                    ("requested_at", "received_at", "known_at", "persisted_at")})
    for ticket in tickets:
        ticket["grading"] = dict(state="unresolved", reason="results_integration_deferred", pnl_usd=None, released_at=None)
        if reconstructed:
            ticket.update(source_kind="retrospective_raw_t10", reconstructed_at=checkpoint["persisted_at"])
    return tickets, gaps


def _replay_games(db, day, at, policy, population):
    """Yield one game and verified retained checkpoint at a time."""
    from . import experiment as owner
    from .mens_d1 import in_paper_cohort

    frozen_policy = policy or POLICY
    reconciled = population is not None and population["kind"] == "reconciled_occurrences"
    leagues = frozen_policy.get("leagues")
    replay_start = frozen_policy.get("retained_replay_start_at")
    prospective_start = frozen_policy.get("prospective_start_at")
    begin = stamp(replay_start or prospective_start) if replay_start or prospective_start else None
    end = stamp(frozen_policy["decision_before"]) if frozen_policy.get("decision_before") else None
    games = list(db.execute("""SELECT g.* FROM public.ev_experiment_game g
        WHERE event->>'league'=ANY(%s) AND
        ((event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date=%s::date
        AND (NOT %s OR EXISTS (SELECT 1 FROM public.ev_experiment_task t
            WHERE t.game_id=g.id AND t.checkpoint='late'
                AND (%s::timestamptz IS NULL OR t.target_at>=%s)
                AND (%s::timestamptz IS NULL OR t.target_at<%s)))
        ORDER BY (event->>'starts_at')::timestamptz,id""",
        (list(leagues) if leagues is not None else [frozen_policy["league"]], day,
         reconciled or leagues is not None or bool(begin or end), begin, begin, end, end)))
    untracked = []
    if population is not None:
        by_provider = {game["event"]["source_event_id"]: game["id"] for game in games}
        for row in population["games"]:
            row["game_id"] = by_provider.get(row.get("provider_event_id"))
            if not in_paper_cohort(row) or row["game_id"]:
                continue
            if not reconciled:
                continue
            if begin or end:
                if not row.get("starts_at"):
                    continue
                target = stamp(row["starts_at"]) - timedelta(seconds=owner.LATE_SECONDS)
                if (begin and target < begin) or (end and target >= end):
                    continue
            row["game_id"] = hashed([day, row["occurrence_id"], "absent_capture_task"])
            untracked.append(dict(game_id=row["game_id"], occurrence_id=row["occurrence_id"],
                title=row.get("title") or row["occurrence_id"], starts_at=row.get("starts_at"),
                status="no_task", reason="no_retained_t10_capture_task", checkpoint_id=None, tickets=0,
                schedule_id=None, outcome_id=None, attempt_ids=[]))
        eligible = {row["game_id"] for row in population["games"] if in_paper_cohort(row)}
        games = [game for game in games if game["id"] in eligible]
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
        if replay_start:
            entry["decision_mode"] = ("retained_replay" if stamp(checkpoint["target_at"]) < stamp(prospective_start)
                                      else "prospective")
        if leagues is not None:
            entry["league"] = game["event"]["league"]
        if status in ("pending", "claimed") and stamp(checkpoint["deadline_at"]) < stamp(at):
            entry.update(status="missed", reason="capture_window_closed")
        if policy is not None:
            entry.update(schedule_id=game["schedule_id"], outcome_id=None if frozen_policy.get("defer_results") else game.get("outcome_id"),
                target_at=checkpoint["target_at"], deadline_at=checkpoint["deadline_at"],
                attempt_ids=[row["id"] for row in db.execute("""SELECT id FROM public.ev_experiment_record
                    WHERE game_id=%s AND kind='attempt' AND checkpoint='late' ORDER BY recorded_at,id""", (game["id"],))])
        if recovered_id and status in ("captured", "reconstructed"):
            entry.update(original_capture_status=original_status, reconstructed_at=checkpoint["persisted_at"],
                         recovery=checkpoint["recovery"])
        yield game, entry, checkpoint, recovered_id
    for entry in untracked:
        yield None, entry, None, None


def scoped_reports(db, day, policies, *, population=None, as_of=None, evidence=False):
    """Price each sizing mode on the same frozen checkpoint before advancing to the next game."""
    date.fromisoformat(day)
    at = (stamp(as_of) if as_of is not None else datetime.now(timezone.utc)).isoformat()
    shared = policies[0]
    frozen = shared or POLICY
    binding_fields = ("league", "leagues", "recovered_checkpoints", "defer_results",
                      "retained_replay_start_at", "prospective_start_at", "decision_before")
    if any(policy is None or any(policy.get(key) != frozen.get(key) for key in binding_fields)
           for policy in policies[1:]):
        raise ValueError("paper_replay_checkpoint_policy_mismatch")
    bundles = {}
    depth_ids = {identity for policy in policies if policy for identity in policy.get("depth_receipts", {}).values()}
    if depth_ids:
        from app.storage import experiment_depth

        bundles = experiment_depth.read_ids(db, depth_ids)
        if depth_ids != bundles.keys():
            raise ValueError("paper_depth_receipts_unavailable")
    replays = [(policy or POLICY, [], [], Counter()) for policy in policies]
    for _, entry, checkpoint, _ in _replay_games(db, day, at, shared, population):
        for policy, dispositions, tickets, exclusions in replays:
            disposition = dict(entry)
            if entry["status"] in ("captured", "reconstructed"):
                bundle_id = policy.get("depth_receipts", {}).get(entry["game_id"])
                bundle = bundles.get(bundle_id) if entry["status"] == "captured" else None
                if bundle and (bundle["game_id"] != entry["game_id"] or bundle["schedule_id"] != entry["schedule_id"]
                               or stamp(bundle["target_at"]) != stamp(checkpoint["target_at"])):
                    raise ValueError("paper_depth_receipt_checkpoint_mismatch")
                found, gaps = scoped_candidates(disposition, checkpoint, policy, depth_bundle=bundle)
                tickets.extend(found)
                exclusions.update(gaps)
            dispositions.append(disposition)
    return [assemble(day, at, policy, dispositions, tickets, exclusions,
                     evidence=evidence, population=deepcopy(population) if len(policies) > 1 else population)
            for policy, dispositions, tickets, exclusions in replays]


def report(db, day=POLICY["default_date"], *, evidence=False, policy=None, population=None, as_of=None):
    """Passive backtest, independent of early-positive retention and live prices."""
    from . import experiment as owner

    if population is not None or (policy and policy.get("depth_policy")):
        return scoped_reports(db, day, [policy], population=population, as_of=as_of, evidence=evidence)[0]
    date.fromisoformat(day)
    frozen_policy = policy or POLICY
    at = (stamp(as_of) if as_of is not None else datetime.now(timezone.utc)).isoformat()
    tickets, dispositions, exclusions = [], [], Counter()
    outcome_evidence = {}
    for game, entry, checkpoint, recovered_id in _replay_games(db, day, at, policy, None):
        if entry["status"] in ("captured", "reconstructed"):
            snapshot = checkpoint["snapshot"]
            outcome = None
            if game.get("outcome_id") and not frozen_policy.get("defer_results"):
                index = owner._closure(db, [game["outcome_id"]])
                outcome = owner._value(index[game["outcome_id"]], index)
                outcome_evidence[game["id"]] = dict(id=game["outcome_id"], **outcome)
            found, gaps = candidates(snapshot, game_id=game["id"], checkpoint_id=checkpoint["id"],
                at=checkpoint["received_at"] if recovered_id else checkpoint["persisted_at"], outcome=outcome, policy=policy)
            if recovered_id:
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
    return assemble(day, at, frozen_policy, dispositions, tickets, exclusions,
                    outcome_evidence=outcome_evidence, evidence=evidence)


def assemble(day, at, frozen_policy, dispositions, tickets, exclusions, *,
             outcome_evidence=None, evidence=False, population=None):
    policy_id = hashed(frozen_policy)
    rule = frozen_policy.get("portfolio_rule")
    values = portfolios(tickets, as_of=at, portfolio_rule=rule)
    if rule == MAIN_FIRST_ONE_PER_GAME:
        values["all_venues"]["candidate_pool_only"] = True
        selected_games = {ticket["game_id"] for ticket in values["best_venue"]["tickets"]}
        tiers = defaultdict(Counter)
        for ticket in tickets:
            tiers[ticket["game_id"]][ticket["portfolio_selection"]["tier"]] += 1
        for game in dispositions:
            if game["status"] in ("captured", "reconstructed"):
                game["tickets"] = int(game["game_id"] in selected_games)
                game["selection_audit"] = dict(tiers[game["game_id"]])
    result = dict(policy=deepcopy(frozen_policy), policy_id=policy_id, date=day, as_of=at,
        designation=("Opportunity record only; original frozen checkpoints plus explicitly reconstructed T−10 raw responses; results deferred"
                     if frozen_policy.get("recovered_checkpoints") else
                     "Retrospective paper replay of frozen T−10 evidence; no actual orders or fills"),
        portfolio_revision=hashed([policy_id, day, sorted(t["id"] for t in tickets)]),
        tracked_games=sum(g["status"] != "no_task" for g in dispositions),
        captured_games=sum(g["status"] == "captured" for g in dispositions),
        games=dispositions, exclusions=dict(exclusions), portfolios=values,
        coverage=("tracked_games_only; no later prices or inferred missing markets" if frozen_policy.get("recovered_checkpoints")
                  else "tracked_games_only; missing/untracked games cannot be reconstructed"),
        outcome_evidence=(outcome_evidence or {}) if evidence else {}, provider_requests=0, orders_submitted=0)
    if population is not None:
        result.update(population=population, coverage=population["kind"],
                      designation="Men’s D1 opportunity analysis. Sporting results are reported separately.")
    if frozen_policy.get("recovered_checkpoints"):
        result["reconstructed_games"] = sum(g["status"] == "reconstructed" for g in dispositions)
    if frozen_policy.get("depth_policy"):
        result["depth_analysis"] = paper_depth.summarize(dispositions, version=frozen_policy["depth_policy"])
        result["designation"] = ("Paper replay of frozen " + result["depth_analysis"]["scope"]
                                 + " with public displayed capacity.")
    if not evidence:
        for portfolio in values.values():
            portfolio["tickets"] = [{k: v for k, v in t.items() if k != "witness"} for t in portfolio["tickets"]]
    result["report_revision"] = hashed([policy_id, day, dispositions,
        {k: dict(v, tickets=[{a: b for a, b in t.items() if a != "witness"} for t in v["tickets"]])
         for k, v in values.items()}])
    return result
