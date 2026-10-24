"""Pure bounded native catalog selection and admission diagnostics.

No credentials, transport, clock or mutable worker lifecycle belongs here.
"""

import json
from . import coverage


def book_material(venue, event, market):
    """Native image identity, independent of derived comparison enrichment."""
    from .native_review_contract import project, CURRENT_POLICY, ELIGIBILITY
    from app.dashboard.session_projection import stable
    def original(row, *, event=False):
        raw=row.get('_native') or row.get('native_metadata') or {}
        if event:raw={k:v for k,v in raw.items() if k!='markets'}
        try:terms=project(venue,raw,event=event,policy=CURRENT_POLICY)
        except (ValueError,TypeError):terms=raw  # Unknown changes remain material.
        return dict(terms=terms,eligibility={k:raw[k] for k in ELIGIBILITY[venue] if k in raw})
    return stable(dict(event_id=event['id'],market_id=market['id'],parent=market['event_id'],
        scheduled_start=event.get('scheduled_start'),competition=event.get('competition'),
        native_event=original(event,event=True),native_market=original(market),
        sides=market.get('sides'),terms=market.get('terms'),status=market.get('status'),
        family=market.get('market_type'),period=market.get('period'),slug=market.get('native_slug')))


def balanced_markets(markets, cap, families, *, events=None, offset=0, priority=()):
    """Round robin across league, family and period within one source budget."""
    events = events or {}
    by_event = {}
    for market in markets:
        family = (
            market.get("v1_raw_binding", {})
            .get("identity", {})
            .get("family", market.get("market_type"))
        )
        if family not in families:
            continue
        league = events.get(market.get("event_id"), {}).get("competition", "unknown")
        period = (
            market.get("v1_raw_binding", {})
            .get("identity", {})
            .get("period", market.get("period"))
            or "unknown"
        )
        by_event.setdefault((league, family, period), {}).setdefault(
            market.get("event_id"), []
        ).append(market)
    pools = {}
    for key, events_in_cell in by_event.items():
        event_ids = fair_order(sorted(events_in_cell), offset)
        event_ids.sort(
            key=lambda eid: not any(m["id"] in priority for m in events_in_cell[eid])
        )
        for eid, rows in events_in_cell.items():
            events_in_cell[eid] = sorted(
                rows, key=lambda market: market["id"] not in priority
            )
        pools[key] = []
        while any(events_in_cell.values()):
            for eid in event_ids:
                if events_in_cell[eid]:
                    pools[key].append(events_in_cell[eid].pop(0))
        pools[key] = fair_order(pools[key], offset // max(1, len(by_event)))
    keys = sorted(pools, key=lambda key: (key[0], families.index(key[1]), key[2]))
    if keys:
        shift = offset % len(keys)
        keys = keys[shift:] + keys[:shift]
    chosen = []
    while len(chosen) < cap and any(pools.values()):
        for key in keys:
            if pools[key] and len(chosen) < cap:
                chosen.append(pools[key].pop(0))
    return chosen


def overlap_event_keys(event):
    """Conservative scheduling hints; the occurrence resolver still owns identity."""
    result = set()
    raw = event.get("_native") or event.get("native_metadata") or {}
    shared = dict(event.get("shared_provider_ids", {}))
    if raw.get("sportradarGameId"):
        shared["sportradar"] = str(raw["sportradarGameId"])
    for fact in event.get("observed_identity_facts", []):
        if fact.get("source_provider") == "sportradar" and fact.get("source_id"):
            shared["sportradar"] = str(fact["source_id"])
    league = event.get("competition")
    result.update(
        ("shared", league, provider, str(value))
        for provider, value in shared.items()
        if value
    )
    roles = event.get("source_participant_roles") or {
        r: event.get(r) for r in ("home", "away")
    }
    start = event.get("scheduled_start")
    number = event.get("game_number", raw.get("gameNumber"))
    if (
        set(roles) == {"home", "away"}
        and None not in roles.values()
        and len(set(roles.values())) == 2
        and start
        and (league != "MLB" or type(number) is int)
    ):
        try:
            result.add(
                (
                    "occurrence",
                    league,
                    coverage.stamp(start).isoformat(),
                    roles["home"],
                    roles["away"],
                    number,
                )
            )
        except (ValueError, TypeError, AttributeError):
            pass
    return result


def overlapping_markets(catalog, others):
    """Rank exact known occurrence/family/period/predicate peers inside fair cells."""
    from .v1_comparison import predicates

    def entries(cat):
        events = {e["id"]: e for e in cat.get("events", []) if not e.get("exclusion")}
        result = []
        for market in cat.get("markets", []):
            event = events.get(market.get("event_id"))
            binding = market.get("v1_raw_binding", {})
            if (
                not event
                or market.get("exclusion")
                or binding.get("status") != "BOUND_RAW_PREDICATE"
            ):
                continue
            try:
                keys = {
                    json.dumps(predicate, sort_keys=True)
                    for _, predicate, _ in predicates(binding)
                }
            except (ValueError, KeyError, TypeError):
                continue
            result.append((market, overlap_event_keys(event), keys))
        return result

    peers = [entry for other in others for entry in entries(other)]
    return {
        market["id"]
        for market, events, keys in entries(catalog)
        if any(
            events & peer_events
            and keys & peer_keys
            and (market.get("market_type"), market.get("period"))
            == (peer.get("market_type"), peer.get("period"))
            for peer, peer_events, peer_keys in peers
        )
    }


def identity_diagnostics(catalog, selected=(), byte_cap=24 * 1024):
    """Bounded existing admission facts; no parser or admission decisions change."""
    entries = [
        dict(kind="event", id=e["id"], reason=e["exclusion"])
        for e in catalog["events"]
        if e.get("exclusion")
    ]
    for market in sorted(catalog["markets"], key=lambda m: m["id"] not in selected):
        binding = market.get("v1_raw_binding") or {}
        reason = (
            market.get("subscription_exclusion")
            or market.get("exclusion")
            or market.get("parse_exclusion")
        )
        if not reason and binding.get("status") != "IDENTITY_BLOCKED":
            continue
        blockers = binding.get("blockers", [])
        bounded = [str(value)[:256] for value in blockers[:6]]
        entries.append(
            dict(
                kind="market",
                id=market["id"],
                reason=reason or "native_binding_incomplete",
                binding_status=binding.get("status"),
                binding_blockers=bounded,
                binding_blockers_truncated=len(blockers) > 6
                or any(len(str(value)) > 256 for value in blockers[:6]),
                source_predicate_present=bool(binding.get("source_predicate")),
                predicate_present=bool(binding.get("predicate")),
            )
        )
    kept = []
    size = 2
    for entry in entries:
        length = len(json.dumps(entry, separators=(",", ":")).encode()) + 1
        if len(kept) >= 200 or size + length > byte_cap:
            continue
        kept.append(entry)
        size += length
    return kept, len(entries) - len(kept)


def fair_order(values, offset):
    values = list(values)
    if not values:
        return values
    offset %= len(values)
    return values[offset:] + values[:offset]


def fair_metadata_bindings(event, native, families, offset=0, cap=3):
    """Select exact embedded locators fairly without increasing request bounds.

    Native ID ordering can put an entire winner ladder before the first spread
    or total. Keep one opportunity per represented family, then rotate within
    each family on later normal discovery passes. Unknown retained locators
    stay eligible rather than acquiring a fabricated family.
    """
    from app.adapters.polymarket_us import full_game_family

    by_id = {
        str(m.get("id")): m for m in native.get("markets", []) if isinstance(m, dict)
    }
    pools = {}
    for binding in event.get("market_bindings", []):
        family = full_game_family(by_id.get(binding["id"], {}).get("sportsMarketType"))
        if family is not None and family not in families:
            continue
        pools.setdefault(family or "unknown", []).append(binding)
    keys = [family for family in families if family in pools] + (
        ["unknown"] if "unknown" in pools else []
    )
    keys = fair_order(keys, offset)
    pools = {
        key: fair_order(sorted(rows, key=lambda r: r["id"]), offset)
        for key, rows in pools.items()
    }
    chosen = []
    while len(chosen) < cap and any(pools.values()):
        for key in keys:
            if pools[key] and len(chosen) < cap:
                chosen.append(pools[key].pop(0))
    return chosen


def unique_metadata_counts(markets, venue):
    """Unique native units in captured metadata, before bounded projection."""
    outcomes = set()
    for market in markets:
        if venue == "kalshi":
            outcomes.update((market["id"], side) for side in ("yes", "no"))
        else:
            sides = market["_native"].get("marketSides")
            if not isinstance(sides, list) or any(
                not isinstance(s, dict) or s.get("id") is None for s in sides
            ):
                return dict(
                    games=len({m["event_id"] for m in markets}),
                    markets=len({m["id"] for m in markets}),
                    quotes=None,
                )
            outcomes.update((market["id"], str(side["id"])) for side in sides)
    return dict(
        games=len({m["event_id"] for m in markets}),
        markets=len({m["id"] for m in markets}),
        quotes=len(outcomes),
    )


CATALOG_BYTES = 2 * 1024 * 1024
QUARANTINE_HEADROOM = 32 * 1024


def catalog_selection(events, native_events, markets, families, offset):
    """Choose whole native records before expansion; one common bounded pool.

    The reservation allows repeated terms/provenance in the derived schema.
    An exact serialized check still guards the completed local proposal. Large
    entries are skipped, never shortened, and never consume another request.
    """
    by_event = {e["id"]: e for e in events}
    parent_cost = {
        eid: 8192
        + 8
        * len(
            json.dumps(
                {k: v for k, v in native_events.get(eid, {}).items() if k != "markets"},
                default=str,
            ).encode()
        )
        for eid in by_event
    }
    market_cost = {
        id(m): 8192 + 8 * len(json.dumps(m.get("_native", {}), default=str).encode())
        for m in markets
    }
    # Individually infeasible records cannot pin the rotating feasible ladder.
    # They remain counted as omitted, with their complete receipts untouched.
    feasible = [
        m
        for m in markets
        if m["event_id"] in by_event
        and 128 * 1024 + parent_cost[m["event_id"]] + market_cost[id(m)]
        <= CATALOG_BYTES
    ]
    ordered = balanced_markets(
        feasible, len(feasible), families, events=by_event, offset=offset
    )
    selected = []
    parents = []
    reserved = 128 * 1024
    for market in ordered:
        eid = market["event_id"]
        if eid not in by_event or market["id"] in selected:
            continue
        # US selected children also remain in the retained parent's packaging.
        cost = market_cost[id(market)]
        if eid not in parents:
            cost += parent_cost[eid]
        if reserved + cost > CATALOG_BYTES:
            continue
        if len(selected) >= 72:
            break
        selected.append(market["id"])
        reserved += cost
        if eid not in parents:
            parents.append(eid)
    # Empty metadata can still report a genuine empty native event catalog.
    if not ordered:
        for event in fair_order(events, offset):
            own = {
                k: v
                for k, v in native_events.get(event["id"], {}).items()
                if k != "markets"
            }
            cost = 8192 + 8 * len(json.dumps(own, default=str).encode())
            if reserved + cost <= CATALOG_BYTES:
                parents.append(event["id"])
                reserved += cost
    return dict(events=parents, markets=selected), dict(
        candidate_events=len(by_event),
        candidate_markets=len({m["id"] for m in markets}),
        supported_family_candidates=len(
            {m["id"] for m in markets if m.get("market_type") in families}
        ),
        selected_events=len(parents),
        selected_markets=len(selected),
        reserved_bytes=reserved,
        omitted_events=len(by_event) - len(parents),
        omitted_markets=len({m["id"] for m in markets}) - len(selected),
    )
