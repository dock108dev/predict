"""Read committed, fee-qualified market prices and exact opposing book quotes."""

from collections import defaultdict, OrderedDict
from threading import Lock
from fractions import Fraction as F
from itertools import product
from app.comparison import pregame_arbs as math
from app.comparison.current_pregame import reference_key
from app.comparison.sgo_reference import american_probability
from app.comparison.sportsbooks import SPORTSBOOKS
from .current_pregame import configured_routes, utc, read as pregame_read
from .store import hashed, stamp

_CACHE = OrderedDict()
_CACHE_LOCK = Lock()
_PAIR_CACHE = OrderedDict()
_PAIR_CACHE_LIMIT = 4096


def cached_pair(left, right, *, at):
    """Reuse exact immutable source/fee inputs across unrelated game revisions.

    SQL eligibility still runs on every miss of the query cache. Expired fees,
    withdrawal, route changes and kickoff exclude entries before this lookup;
    original quote clocks and the original calculation timestamp stay intact.
    """
    key = (left["cache_identity"], right["cache_identity"])
    with _CACHE_LOCK:
        if key in _PAIR_CACHE:
            _PAIR_CACHE.move_to_end(key)
            return _PAIR_CACHE[key]
        # Concurrent visits share the same immutable calculation rather than
        # multiplying CPU work after a client retries.
        result = math.evaluate(left, right, at=at)
        _PAIR_CACHE[key] = result
        while len(_PAIR_CACHE) > _PAIR_CACHE_LIMIT:
            _PAIR_CACHE.popitem(last=False)
    return result


def observation_clock(entry):
    """Compare instants, not ISO strings with potentially different UTC offsets."""
    times = entry["payload"]["times"]
    return (
        times.get("source_at") is not None,
        stamp(times.get("source_at") or times["received_at"]),
        stamp(times["received_at"]),
        entry["contract_id"],
    )


def book_entry(quote, template, *, at):
    p = template["payload"]
    try:
        if (
            quote.get("event_id") not in p.get("sportsbook_event_ids", [])
            or quote.get("available") is not True
            or quote.get("provider_available", True) is not True
            or quote.get("venue") not in SPORTSBOOKS
            or quote.get("partition") == "three_way"
            or quote.get("phase") != "pregame"
            or quote.get("period") != "game"
            or quote.get("league") != p["league"]
            or quote.get("market") != p["family"]
            or stamp(quote["starts_at"]) != stamp(p["kickoff"])
            or not quote.get("source_at")
            or not stamp(quote["source_at"])
            <= stamp(quote["received_at"])
            <= at
            < stamp(p["kickoff"])
        ):
            return None
        if any(
            quote.get("event_status", {}).get(k)
            for k in (
                "live",
                "started",
                "ended",
                "finalized",
                "cancelled",
                "suspended",
                "delayed",
            )
        ):
            return None
        family, _, line = reference_key(template["record"])
        side = quote["side"]
        if p.get("sportsbook_sides_reversed", {}).get(quote["event_id"]) and side in (
            "home",
            "away",
        ):
            side = {"home": "away", "away": "home"}[side]
        qline = None if family == "moneyline" else F(quote["line"])
        if family == "spread" and side == "away":
            qline = -qline
        if qline != line:
            return None
        decimal = 1 / american_probability(quote["price_american"])
        selection = dict(template["record"]["selection"])
        if family == "total":
            selection.update(predicate=side, signed_line=quote["line"])
        else:
            event = template["record"]["event"]
            selection["participant"] = event[side]
            if family == "spread":
                selection["signed_line"] = quote["line"]
        label = next(
            (
                name
                for name, team in template["record"]["event"]
                .get("participants", {})
                .items()
                if team == selection.get("participant")
            ),
            selection.get("participant"),
        )
        payload = dict(
            p,
            id="book:"
            + hashed(
                [quote["event_id"], quote["venue"], quote["odd_id"], quote["line"]]
            ),
            venue=quote["venue"],
            side=side,
            selection=selection,
            selection_label=label,
            reference=None,
            posted=dict(value=quote["price_american"], units="american_odds"),
            source=dict(provider="sportsgameodds", native_event_id=quote["event_id"]),
            times=dict(source_at=quote["source_at"], received_at=quote["received_at"]),
            raw=dict(posted_decimal=str(decimal), after_fee_decimal=str(decimal)),
            display=dict(
                posted_odds=quote["price_american"], after_fees=quote["price_american"]
            ),
            fee=dict(
                entry_usd="0",
                committed_usd="100",
                classification="sportsbook_no_placement_fee",
                evidence={},
                cashflows={},
            ),
        )
        return dict(payload=payload, sportsbook=True)
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return None


def read(db, query, *, at=None, can_continue=None):
    at = at or utc()

    def checkpoint():
        if can_continue is not None and not can_continue():
            raise TimeoutError("arbitrage_read_cancelled")

    checkpoint()
    limit = max(1, min(100, int(query.get("limit", "30"))))
    offset = max(0, int(query.get("offset", "0")))
    cursor = pregame_read(db, {"updates": "1"}, at=at)["cursor"]
    identity = (
        db.info.host,
        db.info.port,
        db.info.dbname,
        cursor,
        tuple(sorted((k, v) for k, v in query.items() if k not in ("limit", "offset"))),
    )
    with _CACHE_LOCK:
        cached = _CACHE.get(identity)
        if cached is not None and (
            cached["refresh_at"] is None or at < stamp(cached["refresh_at"])
        ):
            _CACHE.move_to_end(identity)
            return dict(
                cached,
                rows=cached["rows"][offset : offset + limit],
                offset=offset,
                limit=limit,
            )
    routes = configured_routes(db)
    checkpoint()
    # A queued source/fee change suppresses stale calculations before rebuilding.
    filters, parameters = [], [at, at, at]
    for name in ("league", "family"):
        if query.get(name):
            filters.append("p.payload->>'" + name + "'=%s")
            parameters.append(query[name])
    if query.get("search"):
        filters.append("p.payload->>'game' ILIKE %s")
        parameters.append("%" + query["search"][:150] + "%")
    entries = list(
        db.execute(
            """SELECT p.* FROM current_pregame_price p
        JOIN current_contract c ON c.id=p.contract_id
        JOIN current_offer_storage o ON o.contract_id=c.id JOIN current_event e ON e.id=c.event_id
        WHERE p.start_at>%s AND p.valid_until>%s AND e.scheduled_start::timestamptz>%s
          AND o.facts->>'state' IS DISTINCT FROM 'unavailable'
          AND NOT EXISTS(SELECT 1 FROM sgo_line_presence lp WHERE lp.quote_id=o.sgo_quote_id AND lp.expired)
          AND NOT EXISTS(SELECT 1 FROM current_pregame_work w WHERE w.provider=e.provider AND w.native_event_id=e.native_event_id)
          AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(p.payload->'sportsbook_event_ids') ref(event_id)
            JOIN current_pregame_work w ON w.provider='sportsgameodds' AND w.native_event_id=ref.event_id)
          AND NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{"live":true}'::jsonb)
          AND NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{"ended":true}'::jsonb)
          AND COALESCE(e.facts#>>'{status,status}','') NOT IN ('cancelled','final','suspended','started','delayed')
        """
            + (" AND " + " AND ".join(filters) if filters else "")
            + " ORDER BY p.game_key,p.contract_id",
            parameters,
        )
    )
    entries = [
        e
        for e in entries
        if e["payload"]["source"]["provider"] == routes.get(e["payload"]["venue"])
    ]
    # Prefer newest native alias, never whichever stale alias yields more profit.
    unique = {}
    for entry in entries:
        checkpoint()
        p = entry["payload"]
        key = (p["game_key"], p["arb_key"], p["side"], p["venue"])
        if query.get("league") and p["league"] != query["league"]:
            continue
        if query.get("family") and p["family"] != query["family"]:
            continue
        if query.get("search", "").casefold() not in p["game"].casefold():
            continue
        previous = unique.get(key)
        if previous is None or observation_clock(entry) > observation_clock(previous):
            unique[key] = entry
    entries = list(unique.values())
    event_ids = sorted(
        {eid for e in entries for eid in e["payload"].get("sportsbook_event_ids", [])}
    )
    quotes = (
        [
            r["facts"]
            for r in db.execute(
                "SELECT facts FROM current_sgo_reference WHERE event_id=ANY(%s)",
                (event_ids,),
            )
        ]
        if event_ids
        else []
    )
    by_event = defaultdict(list)
    for q in quotes:
        try:
            line = None if q["market"] == "moneyline" else F(q["line"])
            if q["market"] == "spread" and q["side"] == "away":
                line = -line
            by_event[(q["event_id"], q["market"], line)].append(q)
        except (KeyError, ValueError, TypeError, ArithmeticError):
            continue
    grouped = defaultdict(lambda: defaultdict(list))
    for entry in entries:
        grouped[entry["payload"]["arb_key"]][entry["payload"]["side"]].append(entry)
    results = []
    evaluated = 0
    excluded = 0
    for sides in grouped.values():
        checkpoint()
        all_markets = [e for side in sides.values() for e in side]
        books = {}
        ambiguous = set()
        entry = all_markets[0]
        family, _, line = reference_key(entry["record"])
        for eid in {
            eid
            for e in all_markets
            for eid in e["payload"].get("sportsbook_event_ids", [])
        }:
            lookup_line = (
                -line
                if family == "spread"
                and entry["payload"].get("sportsbook_sides_reversed", {}).get(eid)
                else line
            )
            for quote in by_event[(eid, family, lookup_line)]:
                book = book_entry(quote, entry, at=at)
                if not book:
                    continue
                key = (book["payload"]["venue"], book["payload"]["side"])
                prior = books.get(key)
                clock = lambda b: stamp(b["payload"]["times"]["source_at"])
                if prior and clock(book) < clock(prior):
                    continue
                if (
                    prior
                    and clock(book) == clock(prior)
                    and prior["payload"]["posted"] != book["payload"]["posted"]
                ):
                    ambiguous.add(key)
                elif prior is None or clock(book) > clock(prior):
                    ambiguous.discard(key)
                books[key] = book
        candidates = list(all_markets) + [
            v for k, v in books.items() if k not in ambiguous
        ]
        first = [e for e in candidates if e["payload"]["side"] in ("home", "over")]
        second = [e for e in candidates if e["payload"]["side"] in ("away", "under")]
        for candidate in candidates:
            payload = candidate["payload"]
            candidate["cache_identity"] = hashed(
                [
                    payload["id"],
                    payload.get("input_revision"),
                    payload["raw"],
                    payload.get("times"),
                    payload.get("scoring_scope"),
                    candidate.get("fee_input"),
                    None if payload.get("input_revision") else candidate.get("record"),
                ]
            )
            candidate["acquisition_probability"] = 1 / F(
                candidate["payload"]["raw"]["posted_decimal"]
            )
        for a, b in product(first, second):
            checkpoint()
            if a.get("sportsbook") and b.get("sportsbook"):
                continue
            if query.get("book") and not any(
                e.get("sportsbook") and e["payload"]["venue"] == query["book"]
                for e in (a, b)
            ):
                continue
            if query.get("venue") and query["venue"] not in (
                a["payload"]["venue"],
                b["payload"]["venue"],
            ):
                continue
            category = (
                "market_book"
                if a.get("sportsbook") or b.get("sportsbook")
                else "market_market"
            )
            if query.get("category") and query["category"] != category:
                continue
            evaluated += 1
            # Most pairs cannot beat even the pre-fee price. Do not repeatedly
            # decode fractions or rebuild fee orders for those combinations.
            if (
                a["payload"]["venue"] == b["payload"]["venue"]
                or a["acquisition_probability"] + b["acquisition_probability"] >= 1
            ):
                continue
            try:
                pair = cached_pair(a, b, at=at)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                excluded += 1
                continue
            if pair:
                results.append(pair)
        # Each entry belongs to this exact arb group. Its cent-allocation memo
        # has no use after the group and must not accumulate across the slate.
        for candidate in candidates:
            candidate.pop("_reprice_cache", None)
    results.sort(key=lambda p: (-F(p["return_rate"]), p["kickoff"], p["id"]))
    deadline = min((e["valid_until"] for e in entries), default=None)
    packet = dict(
        schema="predict-pregame-arbs-1",
        rows=results,
        total=len(results),
        offset=offset,
        limit=limit,
        cursor=cursor,
        provider_requests=0,
        scheduled_calculations=0,
        evaluated_pairs=evaluated,
        excluded_pairs=excluded,
        refresh_at=deadline.isoformat() if deadline else None,
        conditioning="decisive_completed_game",
        instant_fill_max_usd=None,
        sportsbooks=sorted(
            {
                q["venue"]
                for q in quotes
                if q.get("venue") in SPORTSBOOKS and q.get("available") is True
            }
        ),
    )

    with _CACHE_LOCK:
        _CACHE[identity] = packet
        while len(_CACHE) > 8:
            _CACHE.popitem(last=False)
    return dict(packet, rows=results[offset : offset + limit])
