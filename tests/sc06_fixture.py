"""Explicit SC06 authored source/model assumptions over real disposable SQL.

No scalar financial results are supplied. This test-only adapter attaches authored
fee/payout/quantity definitions to SQL-decoded quotes, then production readiness,
projection, finance and tickets execute. The ordinary reader has no such adapter.
"""

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from fractions import Fraction
from time import perf_counter
from unittest.mock import patch

from app.comparison.current_dependencies import digest, references
from app.comparison.scanner_readiness import check
from tests.test_d03_current_rows import fixture_records
from tests.test_sc03_finance import AT, authored_finance_fixture
from tests.test_ev05_funded import bind

EVENTS = 500


class Clock:
    def __init__(self):
        self.started = perf_counter()

    def __call__(self):
        return (AT + timedelta(seconds=perf_counter() - self.started)).isoformat()


def records(count=EVENTS, at=None):
    """Two opposing positions per event: native, stake and mixed in rotation.

    Each has two observed depth levels, legal authored grids, nonlinear native
    fees or winning-stake commission, cash acquisition and supported refunds.
    Unique scheduled instants disambiguate 500 explicitly test-only occurrences.
    """
    base = fixture_records()
    out = []
    start_base = datetime.now(timezone.utc).replace(microsecond=0)
    for index in range(count):
        kind = ("native", "stake", "mixed")[index % 3]
        wanted = (
            (("kalshi", "NFL:DEN"), ("polymarket_us", "NFL:SEA"))
            if kind == "native"
            else (
                (("novig", "NFL:DEN"), ("prophetx", "NFL:SEA"))
                if kind == "stake"
                else (("novig", "NFL:DEN"), ("polymarket_us", "NFL:SEA"))
            )
        )
        for leg, (venue, participant) in enumerate(wanted):
            r = deepcopy(
                next(
                    r
                    for r in base
                    if r["quote"]["venue"] == venue
                    and r["selection"]["participant"] == participant
                    and r["selection"]["predicate"] == "win"
                )
            )
            e = r["event"]
            q = r["quote"]
            source = q["source"]
            suffix = f":sc06:{index:03d}"
            e["id"] += suffix
            e["game_id"] = f"authored-sc06-{index}"
            e["stage"] = "regular_season"
            e["title"] = f"Authored SC06 {index:03d} · {kind}"
            e["scheduled_start"] = (
                start_base + timedelta(days=2, minutes=index)
            ).isoformat()
            for key in (
                "shared_provider_ids",
                "current_occurrence_binding",
                "observed_identity_facts",
                "_native",
                "native_metadata",
            ):
                e.pop(key, None)
            # The cloned retained confirmation belongs to its original market.
            # These authored observations use their own source clocks, not a
            # transplanted provider confirmation for another event/book.
            q.pop("book_confirmation", None)
            q.pop("occurrence_match", None)
            q.pop("occurrence_link", None)
            for key in ("native_event_id", "native_market_id", "native_outcome_id"):
                source[key] += suffix
            e["id"] = source["native_event_id"]
            e["shared_provider_ids"] = {"sportradar": f"sc06-authored-{index}"}
            e["season"] = "2026"
            e["home"] = "NFL:DEN"
            e["away"] = "NFL:SEA"
            e["source_participant_roles"] = {"home": "NFL:DEN", "away": "NFL:SEA"}
            r["market_identity"]["season"] = "2026"
            if venue == "polymarket_us":
                source["native_side"] = "Long"
            q["provenance"].update(
                mode="synthetic",
                real_source=False,
                sha256=digest([index, leg, "SC06-authored"]),
            )
            q["times"].update(
                source_at=at or AT.isoformat(),
                received_at=at or AT.isoformat(),
                projected_at=at or AT.isoformat(),
            )
            q.pop("provider_clocks", None)
            if venue in ("novig", "prophetx"):
                top = "2.8" if leg == 0 else "3.1"
                q["original"]["value"] = top
                q["depth"] = [
                    dict(price=top, quantity="80"),
                    dict(price="2.6", quantity="160"),
                ]
            else:
                top = "0.23" if leg == 0 else "0.29"
                q["original"]["value"] = top
                q["depth"] = [
                    dict(price=top, quantity="150"),
                    dict(price="0.37", quantity="300"),
                ]
            q["original"].update(
                native_value=q["original"]["value"],
                native_units=q["original"]["units"],
                transformation="identity",
            )
            # Existing normalized source identity is recalculated from these
            # authored event facts by the actual occurrence resolver.
            from app.comparison.event_links import ordinary_event_key

            r["market_identity"].update(
                event=ordinary_event_key(e),
                scheduled_start=e["scheduled_start"],
                stage="regular_season",
            )
            if r.get("event_scope"):
                r["event_scope"]["native_event_id"] = e["id"]
            r["comparison_scope"] = dict(overtime="included")
            r.setdefault("comparison_source_metadata", {}).update(
                phase="pregame", overtime="included"
            )
            out.append(r)
    assert_authored_originals(out)
    return out


def assert_authored_originals(rows):
    """Independent exact current-contract identity rule over admitted originals."""
    from app.dashboard.current_contract import bounded_decimal

    for row in rows:
        original = row["quote"]["original"]
        bounded_decimal(original["native_value"])
        bounded_decimal(original["value"])
        if (
            original["transformation"] != "identity"
            or original["native_value"] != original["value"]
            or original["native_units"] != original["units"]
        ):
            raise AssertionError(
                "SC06 authored original native transform conflicts with canonical price"
            )


def _template(venue):
    kind = "stake" if venue in ("novig", "prophetx") else "native"
    _, _, xs, _ = authored_finance_fixture(kind=kind)
    return next(x for x in xs.values() if x["quote"]["venue"] == venue)


TEMPLATES = {
    venue: _template(venue)
    for venue in ("kalshi", "polymarket_us", "novig", "prophetx")
}


def attach_authored(q, event, group):
    """Author definitions against the exact SQL quote identity and original clock."""
    template = deepcopy(TEMPLATES[q["venue"]])
    profiles = template["profiles"]
    old = template["quote"]
    values = references(old, profiles)
    q["comparison_input_refs"] = deepcopy(old["comparison_input_refs"])
    q["comparison_input_status"] = deepcopy(old["comparison_input_status"])
    q["native_contract"] = dict(
        version="predict-native-contract-1",
        source=deepcopy(q["source"]),
        predicate=deepcopy(q["binding"]["selection"]),
        wording=dict(rule_note="Explicit test-only SC06 assumption"),
        result_policy=group.get("result_policy", "authored"),
        scope=dict(period="full_game", overtime="included"),
        material_sha256="a" * 64,
    )
    q["native_contract"]["id"] = "native-contract:" + digest(q["native_contract"])
    identity = deepcopy(values["identity"]["payload"])
    selected = identity["selection"]
    roles = {p["role"]: p["id"] for p in event["participants"]}
    participant = q["binding"]["selection"]["participant"]
    selected["event"].update(
        occurrence_id=event["id"],
        league="NFL",
        home_id=roles["home"],
        away_id=roles["away"],
    )
    selected["participant_id"] = participant
    selected["predicate"]["operator"] = "gt" if participant == roles["home"] else "lt"
    selected["native"].update(
        venue=q["venue"],
        event_id=q["source"]["native_event_id"],
        market_id=q["source"]["native_market_id"],
        instrument_id=q["source"]["native_outcome_id"],
        side_id=q["source"]["native_side"],
    )
    identity["current_selection_binding"] = deepcopy(q["binding"]["selection"])
    identity["current_scope_binding"] = dict(occurrence_id=event["id"])
    bind(q, profiles, "identity", identity)
    payout = deepcopy(values["payout"]["payload"])
    from app.comparison.domain import CanonicalSelection
    from app.comparison.payouts import selection_digest

    payout.update(
        native_key=[
            q["venue"],
            *[
                q["source"][k]
                for k in (
                    "native_event_id",
                    "native_market_id",
                    "native_outcome_id",
                    "native_side",
                )
            ],
        ],
        selection_sha256=selection_digest(CanonicalSelection.from_dict(selected)),
    )
    win = q["original"]["value"] if q["original"]["units"] == "decimal_odds" else "1"
    if q["original"]["units"] != "decimal_odds":
        payout["noncompleted"]["value"] = "0.5"
    for field, value in (
        ("above", win if participant == roles["home"] else "0"),
        ("below", "0" if participant == roles["home"] else win),
    ):
        payout[field]["value"] = value
    bind(q, profiles, "payout", payout)
    # Exercise the actual nonlinear quadratic/order rounding owners and
    # stake winning-gain commission, rather than SC03's zero-fee examples.
    from tests.test_comparison_net_costs import setup_case

    _, _, fee_case = setup_case(q["venue"])
    fee_rule = deepcopy(fee_case["registry"].data["rules"][0])
    fee_rule.update(market_id=None, event_id=None, series_id=None)
    if q["venue"] in ("novig", "prophetx"):
        fee_rule["unit"] = dict(
            unit="stake_usd",
            face_usd_per_native=None,
            quantity_scale=None,
            price_scale=None,
        )
        fee_rule["terms"] = dict(
            basis="net_gain",
            rate="0.015" if q["venue"] == "novig" else "0.02",
            grid_usd="0.01",
            rounding="ceiling",
            aggregation="order",
            role="taker",
            allow_fee_adjustment=False,
        )
    fee_payload = dict(rule=fee_rule, flat_entry_fee_usd="0.01")
    if q["venue"] in ("kalshi", "polymarket_us"):
        fee_payload.update(
            engine_context=deepcopy(fee_case["engine_context"]),
            engine_registry=deepcopy(fee_case["engine_registry"].data),
        )
        fee_payload["engine_context"].update(
            market_id=q["source"]["native_market_id"],
            event_id=q["source"]["native_event_id"],
            trade_time=q["times"]["source_at"],
            calculation_time=q["times"]["source_at"],
        )
        fee_payload["engine_context"]["kalshi_metadata"]["event_id"] = q["source"][
            "native_event_id"
        ]
    bind(
        q,
        profiles,
        "fee",
        __import__("json").loads(__import__("json").dumps(fee_payload)),
    )
    # Legal authored grid, meaningful allocation depth and independent funding.
    bind(
        q,
        profiles,
        "quantity",
        dict(
            grid=dict(
                minimum_native="1"
                if q["original"]["units"] != "decimal_odds"
                else "20",
                increment_native="1"
                if q["original"]["units"] != "decimal_odds"
                else "20",
                legal_price_tick=None,
            ),
            grid_qualification="authored_sc06_supported_assumption",
            actual_grid_qualified=True,
        ),
    )
    # No fabricated EV probability. Retain explicit absent optional evidence.
    q["comparison_input_refs"]["refs"]["reference"] = None
    q["comparison_input_refs"]["refs"]["probability"] = None
    for kind in ("fee", "payout"):
        recipe = q["comparison_input_status"][kind]["estimate_content"]
        recipe.update(
            native_key=payout["native_key"],
            selection=deepcopy(q["binding"]["selection"]),
            native_contract_id=q["native_contract"]["id"],
            home_id=roles["home"],
        )
        recipe["id"] = digest({k: v for k, v in recipe.items() if k != "id"})
    return profiles


class AuthoredAdapters:
    """Scoped test-owned qualification, no production model or clock mutation."""

    def __enter__(self):
        from app.storage.comparison_board import ReadContext
        from app.storage import scanner_readiness

        original = ReadContext.bundles
        real_instrument = scanner_readiness.instrument

        def bundles(context, **kwargs):
            values = original(context, **kwargs)
            for value in values:
                state = value["state_inputs"]
                all_profiles = {}
                from app.dashboard.current_contract import quotes_of

                for event in state["events"]:
                    for group in event["groups"]:
                        for outcome in group["outcomes"]:
                            for q in quotes_of(outcome):
                                all_profiles.update(attach_authored(q, event, group))
                state["comparison_profiles"] = all_profiles
            return values

        def instrument(q, profiles, event, group, **kwargs):
            result = real_instrument(q, profiles, event, group, **kwargs)
            # SQL decoded authored source assumptions supply actual depth and
            # terms; production source qualification remains deliberately open.
            for kind in ("execution", "contract"):
                codes = result["checks"][kind]["reason_codes"]
                if (
                    kind == "execution"
                    and q["venue"] in ("novig", "prophetx")
                    and q.get("depth")
                ):
                    # The fixture declares SQL-persisted stake observations;
                    # aggregate production sources normally supply no depth.
                    if all(
                        Fraction(d["price"]) >= 1 and Fraction(d["quantity"]) > 0
                        for d in q["depth"]
                    ):
                        codes = [x for x in codes if x != "observed_depth_missing"]
                result["checks"][kind] = check(codes)
            if q["venue"] in ("kalshi", "polymarket_us") and kwargs.get("book") is None:
                # Header supplied by authored native book SQL below, normally
                # no fallback here; missing headers keep an explicit test failure.
                result["checks"]["execution"] = check(
                    [
                        *result["checks"]["execution"]["reason_codes"],
                        "sc06_authored_book_missing",
                    ]
                )
            return result

        self.patches = [
            patch.object(ReadContext, "bundles", bundles),
            patch.object(scanner_readiness, "instrument", instrument),
        ]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *args):
        for p in reversed(self.patches):
            p.stop()


def native_books(rows):
    """Same actual normalized native-book transaction path, exact SQL depth."""
    result = []
    for r in rows:
        q = r["quote"]
        if q["venue"] not in ("kalshi", "polymarket_us"):
            continue
        result.append(
            dict(
                quantity_unit="contracts",
                sequence="authored-sc06",
                state="active",
                sync="synchronized",
                raw=dict(
                    exchange_at=q["times"]["source_at"],
                    received_at=q["times"]["received_at"],
                    ref=dict(
                        venue=q["venue"],
                        event_id=q["source"]["native_event_id"],
                        market_id=q["source"]["native_market_id"],
                    ),
                ),
                outcomes=[
                    dict(
                        outcome_id=q["source"]["native_outcome_id"],
                        bids=None,
                        asks=dict(
                            depth="full",
                            levels=[
                                dict(
                                    price=dict(
                                        value=l["price"], unit="usd_per_contract"
                                    ),
                                    quantity=dict(
                                        value=l["quantity"], unit="contracts"
                                    ),
                                )
                                for l in q["depth"]
                            ],
                        ),
                    )
                ],
            )
        )
    return result
