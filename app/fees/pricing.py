"""Editable pregame fee rules stored with the existing public schedule records."""

from copy import deepcopy
from fractions import Fraction as F

from psycopg.types.json import Jsonb

from app.storage.store import hashed, stamp

KEYS = {
    "kalshi": "kalshi:exchange",
    "polymarket_us": "polymarket_us:standard_sports",
    "novig": "novig:pregame_straight",
    "prophetx": "prophetx",
}
FORMULAS = {
    "kalshi_taker",
    "polymarket_taker",
    "novig_pregame",
    "prophetx_commission",
    "prophetx_nhl_taker",
}


def validate(rules, venue):
    if not isinstance(rules, list) or not rules or len(rules) > 64:
        raise ValueError("fee_rules_require_between_1_and_64_rules")
    ids = set()
    for rule in rules:
        if set(rule) != {
            "id",
            "formula",
            "rate",
            "multiplier",
            "balance_precision",
            "quantity_step",
            "league",
            "effective_from",
            "effective_to",
            "source_url",
            "profile",
        }:
            raise ValueError("fee_rule_fields")
        if not isinstance(rule["id"], str) or not rule["id"] or rule["id"] in ids:
            raise ValueError("fee_rule_id")
        ids.add(rule["id"])
        formula = rule["formula"]
        if formula not in FORMULAS or not formula.startswith(venue.replace("_us", "")):
            raise ValueError("fee_rule_formula_scope")
        for field in ("rate", "multiplier", "balance_precision", "quantity_step"):
            if not isinstance(rule[field], str) or len(rule[field]) > 40:
                raise ValueError("fee_rule_decimal_string")
            from .engine import number

            value = F(number(rule[field]))
            if value < 0 or field != "rate" and value == 0:
                raise ValueError("fee_rule_positive_terms")
        if F(rule["rate"]) > 1 or rule["balance_precision"] not in ("0.01", "0.0001"):
            raise ValueError("fee_rule_rate_or_precision")
        if rule["league"] not in (None, "NFL", "NCAAF", "NBA", "NCAAB", "MLB", "NHL"):
            raise ValueError("fee_rule_league")
        start = stamp(rule["effective_from"])
        if rule["effective_to"] and stamp(rule["effective_to"]) <= start:
            raise ValueError("fee_rule_interval")
        if not isinstance(rule["source_url"], str) or not rule["source_url"].startswith(
            "https://"
        ):
            raise ValueError("fee_rule_source")
        if rule["profile"] not in ("account", "conservative_public"):
            raise ValueError("fee_rule_profile")
    for i, a in enumerate(rules):
        for b in rules[i + 1 :]:
            if (
                a["league"] == b["league"]
                and (
                    not a["effective_to"]
                    or stamp(b["effective_from"]) < stamp(a["effective_to"])
                )
                and (
                    not b["effective_to"]
                    or stamp(a["effective_from"]) < stamp(b["effective_to"])
                )
            ):
                raise ValueError("fee_rule_overlapping_intervals")
    return deepcopy(rules)


def read(db, *, include_blocked=False):
    return {
        venue: validate(r["rules"], venue)
        if include_blocked or not r["blocked"]
        else []
        for r in db.execute("""
        SELECT venue,state->'pricing_rules' AS rules,state ? 'review_required' AS blocked
        FROM public_fee_schedule WHERE state ? 'pricing_rules' """)
        for venue, key in KEYS.items()
        if key == r["venue"]
    }


def write(db, venue, rules):
    rules = validate(rules, venue)
    key = KEYS[venue]
    db.execute(
        """INSERT INTO public_fee_schedule(venue,state) VALUES (%s,%s)
        ON CONFLICT(venue) DO UPDATE SET state=public_fee_schedule.state || excluded.state""",
        (key, Jsonb(dict(pricing_rules=rules))),
    )


def select(rules, venue, league, at):
    active = [
        r
        for r in rules.get(venue, ())
        if r["league"] in (None, league)
        and stamp(r["effective_from"]) <= at
        and (not r["effective_to"] or at < stamp(r["effective_to"]))
    ]
    specific = [r for r in active if r["league"] == league]
    chosen = specific or active
    if len(chosen) > 1:
        raise ValueError("fee_rule_ambiguous")
    return chosen[0] if chosen else None


def next_change(rules, venue, league, at):
    future = [
        r["effective_from"]
        for r in rules.get(venue, ())
        if r["league"] in (None, league) and stamp(r["effective_from"]) > at
    ]
    return min(future, key=stamp, default=None)


def order(row, rule, cost, terms):
    from app.fees.engine import posted_fee

    def evaluated(levels, stake):
        quantity = (
            stake / cost if terms["kind"] == "stake" else sum(q for _, q in levels)
        )
        entry, settlement, trace = posted_fee(
            rule, price=cost, quantity=quantity, stake=stake
        )
        return (
            entry,
            F(0),
            dict(settlement_fee_usd={"win": str(settlement), "loss": "0"}),
            trace,
        )

    evidence = (row.get("trade_fee") or {}).get("evidence") or dict(
        database_fee_rule=rule, revision=hashed(rule)
    )
    return evaluated, evidence, None


def outcome(row, rule, *, review=None):
    from app.dashboard.current_contract import price
    from app.fees.engine import posted_fee
    from app.comparison.cashflows import exact_wire

    market, source, original = row["market"], row["source"], row["original"]
    if market["period"] != "full_game" or market["market"] not in (
        "winner",
        "spread",
        "total",
    ):
        raise ValueError("fee_rule_product_scope")
    provider, venue = source["provider"], row["venue"]
    extra = {}
    if provider == "sportsgameodds":
        if (
            source.get("native_side") != "bookmaker_outcome"
            or original["units"] != "american_odds"
        ):
            raise ValueError("fee_rule_source_scope")
    elif provider == venue == "kalshi":
        from app.comparison.snapshot_fee_scope import kalshi_fee_context
        from .engine import kalshi_terms

        context, _, evidence = kalshi_fee_context(
            row, review, stamp(row["captured_at"])
        )
        native = kalshi_terms(context, row["captured_at"])
        if native["fee_type"] not in (
            "quadratic",
            "quadratic_with_maker_fees",
            "quadratic_with_combo_maker_fees",
        ):
            raise ValueError("fee_rule_native_product_scope")
        rule = dict(
            rule,
            multiplier=str(max(F(rule["multiplier"]), F(native["fee_multiplier"]))),
        )
        extra.update(
            metadata_revision=evidence["metadata_revision"],
            next_change_at=evidence["review_before"],
        )
    elif provider == venue == "polymarket_us":
        from app.collection.public_contracts import load

        scope = row.get("fee_applicability") or {}
        native = load("us_types", scope.get("native_market_type"))
        if (
            native["period"] != market["period"]
            or native["family"] != market["market"].replace("winner", "moneyline")
            or row["league"] not in native["competitions"]
            or scope.get("native_key")
            != [
                venue,
                source["native_event_id"],
                source["native_market_id"],
                source["native_outcome_id"],
                source["native_side"],
            ]
            or source["native_side"] not in ("Long", "Short")
            or F(original.get("payout", "0")) != 1
        ):
            raise ValueError("fee_rule_native_product_scope")
        values = scope.get("retail", {}).get("values") or {}
        minimum, tick = F(values["minimumTradeQty"]), F(values["orderPriceMinTickSize"])
        if minimum <= 0 or tick <= 0 or price(row) % tick:
            raise ValueError("fee_rule_native_quantity_or_price_grid")
    else:
        raise ValueError("fee_rule_source_scope")
    cost = price(row)
    entry, settlement, trace = posted_fee(rule, price=cost, quantity=F(1), stake=cost)
    return dict(
        available=True,
        reason=None,
        classification="account_configured"
        if rule["profile"] == "account"
        else "conservative",
        liquidity_role="taker",
        quantity="1",
        quantity_unit="USD payout contracts",
        fill_count=1,
        fee_payment="winning_settlement" if settlement else "at_fill",
        trade_fee_usd=exact_wire(entry + settlement),
        evidence=dict(
            database_fee_rule=rule,
            revision=hashed(rule),
            source_url=rule["source_url"],
            reviewed_at=rule["effective_from"],
            review_before=rule["effective_to"],
            **extra,
        ),
        details=dict(rounding_trace=trace),
    )


def seed(db, *, at):
    """Copy applicable reviewed terms once; later refreshes preserve configured rules."""
    from app.comparison.snapshot_fee_outcome import reviews
    from . import product_schedules, schedule_lifecycle
    from .evidence import applies

    products = product_schedules.read_all(db)
    prophetx = schedule_lifecycle.read(db)
    existing = read(db)
    inserted = []
    for venue, base in reviews(at).items():
        if venue in existing:
            continue
        row = dict(venue=venue, game_state="scheduled")
        terms = (
            schedule_lifecycle.for_offer(prophetx, row, at, fallback=base)
            if venue == "prophetx"
            else product_schedules.for_offer(products, row, at, fallback=base)
        )
        if not terms or terms.get("unavailable_reason") or not applies(terms, at):
            continue
        formula = {
            "kalshi": "kalshi_taker",
            "polymarket_us": "polymarket_taker",
            "novig": "novig_pregame",
            "prophetx": "prophetx_commission",
        }[venue]
        rule = dict(
            id=terms["version"],
            formula=formula,
            rate=terms["fee_rate"],
            multiplier="1",
            balance_precision="0.01",
            quantity_step="0.01" if venue in ("novig", "prophetx") else "1",
            league=None,
            effective_from=terms.get("published_effective_from")
            or terms["reviewed_at"],
            effective_to=terms.get("next_change_at"),
            source_url=terms["source_url"],
            profile="conservative_public",
        )
        rules = [rule]
        if venue == "kalshi":
            import json
            from pathlib import Path

            root = Path(__file__).resolve().parents[2]
            body = json.loads((root / terms["path"]).read_bytes())
            by_league = {}
            for item in body["series"].values():
                multiplier = F(str(item["response"]["series"]["fee_multiplier"]))
                by_league[item["league"]] = max(
                    multiplier, by_league.get(item["league"], F(0))
                )
            for league, multiplier in by_league.items():
                if multiplier != F(rule["multiplier"]):
                    from app.comparison.cashflows import exact_wire

                    rules.append(
                        dict(
                            rule,
                            id=rule["id"] + ":" + league,
                            league=league,
                            multiplier=exact_wire(multiplier),
                        )
                    )
        if venue == "prophetx" and terms.get("nhl_taker_coefficient") is not None:
            rules.append(
                dict(
                    rule,
                    id=rule["id"] + ":NHL",
                    formula="prophetx_nhl_taker",
                    league="NHL",
                    rate=terms["nhl_taker_coefficient"],
                    quantity_step="1",
                )
            )
        write(db, venue, rules)
        inserted.append(venue)
    return inserted
