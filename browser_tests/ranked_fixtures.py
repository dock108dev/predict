"""Authored ranked comparison payloads shared by the desk journeys."""

from fractions import Fraction
from pathlib import Path

ASSETS = (
    Path(__file__).resolve().parents[1] / "app/dashboard/opportunity_static/current"
)
BASE = "https://predict.fixture"

START = "2026-11-13T01:00:00Z"
DENVER = "Denver Nuggets vs. Minnesota Timberwolves"
DETROIT = "Detroit Pistons vs. Washington Wizards"
WASHINGTON = "Washington Commanders vs. New York Giants"


def quote(key, venue, predicate, family, line=None, *, decimal="1.25", **fields):
    payout = Fraction(decimal)
    american = 100 * (payout - 1) if payout >= 2 else -100 / (payout - 1)
    return (
        dict(
            id=key,
            venue=venue,
            current=True,
            odds=dict(decimal=decimal, american=f"{float(american):+.2f}"),
            market=dict(market=family, period="full_game", line=line),
            selection=dict(predicate=predicate, signed_line=line),
            value=None,
            before_fee=None,
            after_fee=None,
            conservative=None,
            reference=None,
            reference_current=False,
            current_until=None,
            calculation_current_until=None,
            participant=None,
            alternate=None,
            reason="sgo_reference_book_rules_unverified",
            cost_per_normal_claim=str(1 / payout),
            captured_at=START,
            price_revision=key + "-price",
            economic_revision=key + "-economics",
            evidence_result_id=key + "-capture",
        )
        | fields
    )


def group(key, game, offers, score=None, **fields):
    return (
        dict(
            id=key,
            game_key=game,
            game_title=game,
            league="NBA",
            start_at=START,
            offers=offers,
            market=offers[0]["market"],
            score=score,
        )
        | fields
    )


def settlement(
    key, title, lead, opposite, score, profit, funding, quantities, costs, fees
):
    payoff = dict(
        available=True,
        minimum_net_profit_usd=profit,
        funding_usd=funding,
        legs=[
            dict(
                available=True,
                acquisition_usd=cost,
                quantity=quantity,
                at_fill_usd=fee,
                settlement_usd={},
                receipts_usd=dict(
                    first_wins=quantity if index == 0 else "0",
                    second_wins=quantity if index == 1 else "0",
                    equality=str(Fraction(quantity) / 2),
                ),
                rounding_trace=[dict(raw=fee, amount=fee)],
                classification="conservative",
            )
            for index, (quantity, cost, fee) in enumerate(
                zip(quantities, costs, fees, strict=True)
            )
        ],
        sizing=dict(quantity=quantities[0], requested_stake_usd="100"),
        states={
            state: dict(net_receipt_usd=quantities[0], net_profit_usd=profit)
            for state in ("first_wins", "second_wins", "equality")
        },
    )
    pair = dict(
        id=key,
        evidence_result_id=key + "-capture",
        legs=[lead["id"], opposite["id"]],
        score=score,
        retail_payoff=payoff,
        inspection=dict(
            funding_usd="100",
            minimum_profit_usd=profit,
            rounding="Whole modeled claims",
            legs=[
                dict(cost_per_claim=item["cost_per_normal_claim"], allocation_usd=cost)
                for item, cost in zip((lead, opposite), costs, strict=True)
            ],
        ),
    )
    return group(key, title, [lead, opposite], score, pairs=[pair])


def ranked_fixtures():
    detroit = quote(
        "pmus-detroit",
        "polymarket_us",
        "over",
        "total",
        "205.5",
        decimal="100/81",
        source_clock_at="2026-11-12T23:59:40Z",
        confirmed_at="2026-11-12T23:59:52Z",
        received_at="2026-11-12T23:59:53Z",
        price_basis="native_book",
        trade_fee=dict(
            available=True,
            trade_fee_usd="0.01",
            classification="conservative",
            quantity="1",
            quantity_unit="USD normal claim",
            fill_count=1,
            fee_cashflows={},
        ),
    )
    other_detroit = [
        quote("kalshi-detroit", "kalshi", "over", "total", "205.5", decimal="24/19"),
        quote(
            "novig-detroit",
            "novig",
            "over",
            "total",
            "205.5",
            decimal="99/79",
            source_provider="sportsgameodds",
        ),
    ]
    denver_fair = dict(
        available=True,
        venue="draftkings",
        probability="1431/2887",
        contributors=[
            dict(
                venue="draftkings",
                inputs=[
                    dict(label="Denver +2.5", price_american="-108", source_at=START),
                    dict(
                        label="Minnesota −2.5", price_american="-112", source_at=START
                    ),
                ],
            )
        ],
    )
    denver_ev = str(100 * (Fraction("1431/2887") / Fraction("0.48") - 1))
    denver = quote(
        "pmus-denver",
        "polymarket_us",
        "cover",
        "spread",
        "2.5",
        participant="Denver",
        decimal="50/23",
        value=denver_ev,
        conservative=denver_ev,
        reason=None,
        reference_current=True,
        reference=dict(american="+102", decimal="2887/1431"),
        fair_reference=dict(books=["draftkings"], method="single"),
        reference_calculation=denver_fair,
    )
    kalshi_denver = quote(
        "kalshi-denver",
        "kalshi",
        "cover",
        "spread",
        "2.5",
        participant="Denver",
        decimal="25/13",
        value="-8.21",
        conservative="-8.21",
        reason=None,
    )
    minnesota = quote(
        "kalshi-minnesota",
        "kalshi",
        "cover",
        "spread",
        "-2.5",
        participant="Minnesota",
        decimal="100/49",
    )
    alternate = quote(
        "kalshi-denver-alt",
        "kalshi",
        "cover",
        "spread",
        "3.5",
        participant="Denver",
        alternate=True,
    )
    last_known = quote(
        "novig-denver",
        "novig",
        "cover",
        "spread",
        "2.5",
        participant="Denver",
        current=False,
        reason="Price expired",
        source_at="2026-11-12T07:00:00Z",
        source_provider="sportsgameodds",
    )
    negative = quote(
        "kalshi-washington",
        "kalshi",
        "win",
        "winner",
        participant="Washington",
        value="-3",
        conservative="-3",
        reason=None,
    )
    ev = [
        group(
            "ev-denver",
            DENVER,
            [denver, kalshi_denver],
            denver_ev,
            sportsbook_quotes={
                "draftkings": [dict(price_american="-107", current=True)],
                "fanduel": [dict(price_american="-111", current=True)],
                "caesars": [dict(price_american="-115", current=False)],
            },
        ),
        group(
            "ev-washington",
            WASHINGTON,
            [negative],
            "-3",
            sportsbook_quotes={
                "fanduel": [dict(price_american="-108", current=True)],
                "betmgm": [dict(price_american="-110", current=True)],
            },
        ),
    ]
    detroit_group = group("ev-detroit", DETROIT, [detroit, *other_detroit])
    denver_matrix = [
        ev[0],
        group("minnesota", DENVER, [minnesota]),
        group("denver-alt", DENVER, [alternate]),
        group(
            "a-denver-other-sign",
            DENVER,
            [
                quote(
                    "denver-other-sign",
                    "kalshi",
                    "cover",
                    "spread",
                    "-2.5",
                    participant="Denver",
                    alternate=True,
                )
            ],
        ),
        group(
            "z-minnesota-other-sign",
            DENVER,
            [
                quote(
                    "minnesota-other-sign",
                    "kalshi",
                    "cover",
                    "spread",
                    "2.5",
                    participant="Minnesota",
                    alternate=True,
                )
            ],
        ),
    ]
    arbs = [
        settlement(
            "arb-denver",
            DENVER,
            minnesota,
            denver,
            str(100 * Fraction("0.93") / Fraction("104.07")),
            "0.93",
            "104.07",
            ("105", "105"),
            ("51.45", "48.30"),
            ("1.84", "2.48"),
        ),
        settlement(
            "arb-washington",
            WASHINGTON,
            quote(
                "giants",
                "kalshi",
                "win",
                "winner",
                participant="Giants",
                decimal="25/14",
            ),
            quote(
                "washington",
                "polymarket_us",
                "win",
                "winner",
                participant="Washington",
                decimal="20/9",
            ),
            str(100 * Fraction("-5.03") / Fraction("104.03")),
            "-5.03",
            "104.03",
            ("99", "99"),
            ("55.44", "44.55"),
            ("1.71", "2.33"),
        ),
    ]
    return ev, detroit_group, denver_matrix, last_known, arbs
