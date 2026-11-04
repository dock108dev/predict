"""Ordinary immutable comparison snapshots; browsing never dispatches providers."""

import asyncio
from datetime import datetime
from functools import lru_cache
from fractions import Fraction
from aiohttp import web
from app.storage.store import connect
from app.storage import comparison_snapshot as snapshots
from app.comparison.snapshot_math import assumptions
from .local_security import read_json, PublicRequestError
from .snapshot_display import presented, search_index


def page_options(query):
    view = query.get("view", "ev")
    if view not in ("ev", "odds", "arbs"):
        raise PublicRequestError("Unknown snapshot view")
    metric = query.get("metric", "gross_return_percent")
    if metric not in (
        "gross_return_percent",
        "conditional_return_percent",
        "net_return_percent",
        "price_difference_cents",
        "minimum_return_percent",
    ):
        raise PublicRequestError("Unknown metric")
    try:
        offset = int(query.get("offset", "0"))
        limit = int(query.get("limit", "25"))
    except ValueError:
        raise PublicRequestError("Invalid page bounds") from None
    if offset < 0 or not 1 <= limit <= 100:
        raise PublicRequestError("Invalid page bounds")
    return view, metric, offset, limit


def page(result, query, *, options=None):
    view, metric, offset, limit = options or page_options(query)
    if result is None:
        return dict(state="empty", defaults=assumptions()[0], provider_requests=0)
    out = {k: v for k, v in result.items() if k not in ("rows", "pairs", "references")}
    out['defaults'] = assumptions()[0]
    rows = result["pairs"] if view == "arbs" else result["rows"]

    names = search_index(result)

    def selected(row):
        return (
            all(
                not query.get(k) or str(row.get(field, "")) == query[k]
                for k, field in (("league", "league"), ("game", "game_key"))
            )
            and (
                not query.get("venue")
                or query["venue"] == row.get("venue")
                or query["venue"] in row.get("venues", [])
            )
            and (not query.get("family") or query["family"] == row["market"]["market"])
            and (all(term in (row["game_title"].casefold() + " " + names.get(row.get("game_key"), "")) for term in query.get("search", "").casefold().split()))
        )

    rows = [r for r in rows if selected(r)]
    if view == "odds":
        from .grouped_odds import group_prices

        bygame = {}
        for r in rows:
            bygame.setdefault(r["game_key"], []).append(r)
        grouped = []
        for prices in bygame.values():
            byid = {r["quote_id"]: r for r in prices}
            grouped.extend(
                dict(g, quotes=[byid[q] for ids in g["cells"].values() for q in ids])
                for g in group_prices(prices)["rows"]
            )
        rows = grouped
        rows.sort(
            key=lambda r: (
                r["quotes"][0]["start_at"],
                r["quotes"][0]["game_title"],
                r["id"],
            )
        )
    else:
        rows = sorted(
            rows,
            key=lambda r: (
                r.get(metric) is None,
                -Fraction(r[metric]) if r.get(metric) is not None else 0,
                r["start_at"],
                r["id"],
            ),
        )
    out.update(
        state="ready",
        view=view,
        metric=metric,
        total=len(rows),
        offset=offset,
        limit=limit,
        rows=rows[offset : offset + limit],
    )
    by_id = {r["id"]: r for r in result["rows"]}
    out["rows"] = [dict(r, quotes=[presented(q) for q in r["quotes"]]) if view == "odds" else presented(r, by_id) for r in out["rows"]]
    out["reference_count"] = len(result["references"])
    coverage = {}
    for quote in (*result["rows"], *result["references"]):
        venue = quote.get("venue")
        if not venue:
            continue
        entry = coverage.setdefault(
            venue, dict(count=0, unknown_clock=0, newest=None, oldest=None)
        )
        entry["count"] += 1
        at = (quote.get("times") or {}).get("source_at")
        if not at:
            entry["unknown_clock"] += 1
            continue
        instant = datetime.fromisoformat(at)
        for key, choose in (("newest", max), ("oldest", min)):
            entry[key] = choose(entry[key], instant) if entry[key] else instant
    for entry in coverage.values():
        for key in ("newest", "oldest"):
            if entry[key]:
                entry[key] = entry[key].isoformat()
    out["coverage"] = coverage
    return out


def history(db, out):
    out["history"] = [
        dict(
            id=r["id"],
            snapshot_id=r["snapshot_id"],
            captured_at=r["captured_at"].isoformat(),
        )
        for r in db.execute(
            """SELECT r.id,r.snapshot_id,s.captured_at FROM comparison_snapshot_result r
           JOIN comparison_snapshot s ON s.id=r.snapshot_id ORDER BY r.calculated_at DESC LIMIT 12"""
        ).fetchall()
    ]
    return out


def selected_references(selection, original, references):
    benchmark = selection.get("snapshot_benchmark")
    if benchmark:
        by_id = {r["id"]: r for r in references}
        return [by_id[i] for i in benchmark["ids"] if i in by_id]
    ref = selection.get("reference")
    record = original.get("original_record")
    if not ref or not record:
        return []
    from app.collection.current_benchmark import key
    from app.comparison.event_links import semantic_market

    # Reconstruct only the same source receipt and market used by attach().
    market = semantic_market(record)
    source = record["quote"]["source"]
    routes = {}
    for candidate in references:
        witness = candidate.get("original_record")
        if not witness:
            continue
        q = witness["quote"]
        # Execution bundles project event IDs; reference witnesses retain the
        # provider's event ID. Require the exact provider occurrence on both.
        if any(q["source"][k] != source[k] for k in ("provider", "native_event_id")):
            continue
        witness_market = semantic_market(witness)
        if (
            q["provenance"]["sha256"] == ref.get("sha256")
            and q["times"]["received_at"] == ref.get("received_at")
            and witness_market == dict(market, event=witness_market["event"])
        ):
            alternate = q["source"]["native_market_id"].startswith("alternate:")
            routes.setdefault(alternate, []).append(candidate)
    matches = []
    for group in routes.values():
        if len(group) != 2:
            continue
        pair = sorted(group, key=lambda r: key(r["original_record"]))
        if (
            [r["original"]["value"] for r in pair] == ref["odds"]
            and [r["times"]["source_at"] for r in pair] == ref["source_at"]
            and key(pair[ref["selected"]]["original_record"])
            == key(dict(record, market_identity=pair[0]["market"]))
        ):
            matches.append(pair)
    return matches[0] if len(matches) == 1 else []


def mount(app):
    # Result IDs are immutable. Hold one decoded revision for ordinary browsing.
    # Resolve the head and renew both retention leases on every read, including hits.
    @lru_cache(maxsize=1)
    def decoded(result_id):
        with connect() as db:
            row = db.execute(
                "SELECT result FROM comparison_snapshot_result WHERE id=%s",
                (result_id,),
            ).fetchone()
            return snapshots.unpack(row["result"]) if row else None

    def leased_result(db, result_id):
        row = db.execute(
            """UPDATE comparison_snapshot_result SET lease_until=now()+interval '2 hours'
            WHERE id=COALESCE(%s,(SELECT result_id FROM comparison_snapshot_head WHERE singleton))
            RETURNING id,snapshot_id""",
            (result_id,),
        ).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE comparison_snapshot SET lease_until=now()+interval '2 hours' WHERE id=%s",
            (row["snapshot_id"],),
        )
        return decoded(row["id"])

    async def read(req):
        options = page_options(req.query)

        def work():
            with connect() as db:
                result = leased_result(db, req.query.get("result_id"))
                if req.query.get("result_id") and result is None:
                    raise PublicRequestError("Selected snapshot expired")
                return history(db, page(result, req.query, options=options))

        return web.json_response(await asyncio.to_thread(work))

    async def operate(req):
        options = page_options(req.query)
        body = await read_json(req)
        if not isinstance(body, dict) or set(body) - {
            "action",
            "assumptions",
            "expected",
        }:
            raise PublicRequestError("Exact snapshot operation required")
        if "assumptions" in body:
            try:
                assumptions(body["assumptions"])
            except (ValueError, TypeError, ArithmeticError) as exc:
                raise PublicRequestError(str(exc)) from None

        def work():
            with connect() as db:
                return history(
                    db,
                    page(
                        snapshots.replace(
                            db,
                            action=body.get("action"),
                            value=body.get("assumptions"),
                            expected=body.get("expected"),
                        ),
                        req.query,
                        options=options,
                    ),
                )

        try:
            return web.json_response(await asyncio.to_thread(work))
        except snapshots.SnapshotOperationError as exc:
            raise PublicRequestError(str(exc)) from None

    async def details(req):
        if not req.query.get("result_id") or not req.query.get("id"):
            raise PublicRequestError("Exact result revision and selection required")

        def work():
            with connect() as db:
                result = leased_result(db, req.query.get("result_id"))
                if result is None:
                    raise PublicRequestError("Selected snapshot expired")
                row = next(
                    (
                        r
                        for r in [*result["rows"], *result["pairs"]]
                        if r["id"] == req.query.get("id")
                    ),
                    None,
                )
                if row is None:
                    raise PublicRequestError("Selection is not in this result revision")
                inputs = snapshots.unpack(
                    db.execute(
                        "SELECT inputs FROM comparison_snapshot WHERE id=%s",
                        (result["snapshot_id"],),
                    ).fetchone()["inputs"]
                )
                ids = row.get("legs", [row["id"]])
                originals = [q for q in inputs["quotes"] if q["id"] in ids]
                by_id = {q["id"]: q for q in originals}
                refs = {}
                from app.comparison.snapshot_named_benchmark import references
                benchmark_refs=references(inputs['quotes'],inputs['references'],result['assumptions'])
                for leg in result["rows"]:
                    if leg["id"] in by_id:
                        for ref in selected_references(
                            leg, by_id[leg["id"]], benchmark_refs
                        ):
                            refs[ref["id"]] = ref
                return dict(
                    result_id=result["id"],
                    snapshot_id=result["snapshot_id"],
                    captured_at=result["captured_at"],
                    assumptions=result["assumptions"],
                    row=presented(row, {r["id"]: r for r in result["rows"]}),
                    benchmark_diagnostics=result.get("benchmark_diagnostics", {}),
                    originals=originals,
                    references=list(refs.values()),
                    provider_requests=0,
                )

        return web.json_response(await asyncio.to_thread(work))

    app.router.add_get("/api/comparison-snapshot", read)
    app.router.add_post("/api/comparison-snapshot", operate)
    app.router.add_get("/api/comparison-snapshot/details", details)
