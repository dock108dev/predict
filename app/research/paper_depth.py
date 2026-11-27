"""Saved comparisons over the same frozen candidate population."""

from collections import Counter
from fractions import Fraction as F

from app.storage.experiment_depth import POLICY as VERSION
from app.storage.store import stamp

LEAGUES = ("NCAAB",)
SCENARIOS = ("quoted", "novig_band", "no_novig_alternates", "depth")


def receipt_ids(games):
    return {game["depth_receipt_id"] for game in games if game.get("depth_receipt_id")}


def _request_metrics(readings):
    ages = [row["max_response_age_seconds"] for row in readings if row.get("max_response_age_seconds") is not None]
    latency = [row["max_request_latency_ms"] for row in readings if row.get("max_request_latency_ms") is not None]
    return dict(public_requests=sum(row.get("public_requests", 0) for row in readings),
                preparation_requests=sum(row.get("preparation_requests", 0) for row in readings),
                max_response_age_seconds=max(ages, default=None), max_request_latency_ms=max(latency, default=None))


def followup_summary(bundles):
    delays = [(stamp(bundle["known_at"]) - stamp(bundle["target_at"])).total_seconds() for bundle in bundles]
    readings = [bundle["metrics"] for bundle in bundles]
    return dict(games=len(bundles), cache_reuse_sides=sum(row.get("cache_reuse_sides", 0) for row in readings),
                min_observed_delay_seconds=round(min(delays), 3) if delays else None,
                max_observed_delay_seconds=round(max(delays), 3) if delays else None,
                **_request_metrics(readings))


def novig_alternate(ticket):
    evidence = ticket.get("portfolio_selection") or {}
    return ticket["venue"] == "novig" and (
        evidence.get("selected_quote_line_role", evidence.get("line_role")) == "alternate")


def in_novig_band(ticket):
    if not novig_alternate(ticket):
        return True
    return -250 <= F(ticket["posted_odds"]) <= 250


def _pick_fields(ticket):
    fields = ("id", "frozen_quote_id", "equivalent_bet_id", "venue", "family", "side", "line",
              "label", "posted_odds", "probability", "screen_ev", "ev", "cash_commitment_usd",
              "expected_profit_exact_usd", "portfolio_selection")
    return {key: ticket.get(key) for key in fields}


def compare_game(quoted, depth, candidates, *, rank):
    pools = {
        "quoted": quoted,
        "novig_band": [ticket for ticket in quoted if in_novig_band(ticket)],
        "no_novig_alternates": [ticket for ticket in quoted if not novig_alternate(ticket)],
        "depth": depth,
    }
    selected = {name: next(iter(rank(pool)), None) for name, pool in pools.items()}
    dispositions = {row["frozen_quote_id"]: row["depth"] for row in candidates}
    picks = {
        name: dict(_pick_fields(ticket), depth=dispositions.get(ticket["frozen_quote_id"], {
            "status": "unknown", "eligible": False, "reason": "no_exact_depth_candidate",
        })) if ticket else None
        for name, ticket in selected.items()
    }
    original = selected["quoted"]
    controls = [ticket for ticket in candidates if original and novig_alternate(original)
                and ticket["family"] == original["family"] and ticket["venue"] == "novig"
                and ticket["side"] == original["side"]
                and (ticket.get("portfolio_selection") or {}).get("line_role") == "main"]
    # A duplicate or ambiguous main contract is not a verified comparison.
    control = controls[0] if len(controls) == 1 else None
    return dict(picks=picks, quoted_candidates=len(quoted), depth_candidates=len(candidates),
                supported_candidates=len(depth), main_line_control=control)


def _odds_band(odds):
    if odds is None:
        return "unknown"
    value = F(odds)
    return "below_-250" if value < -250 else "above_+250" if value > 250 else "-250_to_+250"


def _available_support(picks):
    sizes = Counter(pick["depth"]["status"] for pick in picks)
    usable = len(picks) - sizes["unknown"]
    full = sizes["full_size"]
    total_stake = sum((F(pick["cash_commitment_usd"]) for pick in picks), F(0))
    supported_stake = sum((F(pick["cash_commitment_usd"]) for pick in picks
                           if pick["depth"]["status"] == "full_size"), F(0))
    usable_stake = sum((F(pick["cash_commitment_usd"]) for pick in picks
                        if pick["depth"]["status"] != "unknown"), F(0))
    gross_capacity_stake = sum((F(pick["cash_commitment_usd"]) * min(
        F(1), F(pick["depth"].get("available_gross_win_profit_usd") or 0) / 25)
        for pick in picks), F(0))
    unknown_reasons = Counter(pick["depth"].get("reason") or "unknown" for pick in picks
                              if pick["depth"]["status"] == "unknown")
    return dict(targeted_picks=len(picks), usable_books=usable, full_size=full,
                clears_depth_policy=sum(bool(pick["depth"]["eligible"]) for pick in picks),
                full_size_per_target=str(F(full, len(picks))) if picks else None,
                full_size_per_usable=str(F(full, usable)) if usable else None,
                targeted_stake_usd=str(total_stake), usable_stake_usd=str(usable_stake),
                supported_stake_usd=str(supported_stake), stake_weighted_full_size_per_target=(
                    str(supported_stake / total_stake) if total_stake else None),
                stake_weighted_full_size_per_usable=(
                    str(supported_stake / usable_stake) if usable_stake else None),
                stake_weighted_displayed_capacity=(
                    str(gross_capacity_stake / total_stake) if total_stake else None),
                dispositions=dict(sizes), unknown_reasons=dict(unknown_reasons))


def summarize(games):
    comparisons = [game["depth_comparison"] for game in games if game.get("depth_comparison")]
    picks = {name: [comparison["picks"][name] for comparison in comparisons if comparison["picks"][name]]
             for name in SCENARIOS}
    original = picks["quoted"]
    dimensions = {
        "line_role": lambda pick: (pick.get("portfolio_selection") or {}).get(
            "selected_quote_line_role", (pick.get("portfolio_selection") or {}).get("line_role", "unknown")),
        "odds_band": lambda pick: _odds_band(pick["posted_odds"]),
        "distance_from_main": lambda pick: (pick.get("portfolio_selection") or {}).get("distance_points", "unknown"),
        "family": lambda pick: pick["family"],
        "venue": lambda pick: pick["venue"],
    }
    cohorts = {}
    for name, key in dimensions.items():
        groups = {}
        for pick in original:
            groups.setdefault(key(pick), []).append(pick)
        cohorts[name] = {label: _available_support(group) for label, group in sorted(groups.items())}
    scenario_totals = {}
    for name in SCENARIOS:
        changes = [(item["picks"]["quoted"], item["picks"][name]) for item in comparisons]
        scenario_totals[name] = dict(_available_support(picks[name]),
            replacements=sum(bool(before and after and before["frozen_quote_id"] != after["frozen_quote_id"])
                             for before, after in changes),
            games_without_pick=sum(after is None for _, after in changes),
            quoted_picks_removed=sum(bool(before and not after) for before, after in changes),
            new_picks=sum(bool(after and not before) for before, after in changes),
            expected_profit_usd=str(sum((F(pick["expected_profit_exact_usd"]) for pick in picks[name]), F(0))))
    controls = [item["main_line_control"] for item in comparisons if item["main_line_control"]]
    return dict(version=VERSION, scope="NCAAB full-game spreads and totals",
                frozen_game_decisions=len(comparisons), venue_receipt_games=sum(bool(game.get("depth_receipt_id"))
                                                                              for game in games),
                capture_states=dict(Counter(game.get("status", "unknown") for game in games)),
                request_metrics=_request_metrics([game["depth_metrics"] for game in games if game.get("depth_metrics")]),
                quoted_candidates=sum(item["quoted_candidates"] for item in comparisons),
                evaluated_depth_candidates=sum(item["depth_candidates"] for item in comparisons),
                scenarios=scenario_totals, cohorts=cohorts, main_line_controls=dict(
                    documented=len(controls), dispositions=dict(Counter(row["depth"]["status"] for row in controls))))
