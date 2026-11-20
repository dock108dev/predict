"""Read-only HTTP boundary for committed current pregame opportunities."""

import asyncio
from time import monotonic
from threading import Event

from aiohttp import web
from psycopg.errors import QueryCanceled

from app.storage.store import connect

READ_DEADLINE_SECONDS = 10
# Complete current-slate scans measured 16–21s on the shared deployed host.
# Keep cold computation bounded, cancellable and separate from ordinary 10s reads.
ARBITRAGE_READ_DEADLINE_SECONDS = 30

RETIRED = frozenset(
    (
        "unit_usd",
        "preview_amount",
        "board",
        "board_id",
        "board_cursor",
        "basis",
        "group",
    )
)


async def response(request, *, connector=None):
    if RETIRED & request.query.keys():
        return web.json_response(
            dict(
                error="amount_specific_board_retired",
                message="Use current pregame rows without a unit size or calculation mode.",
            ),
            status=410,
        )
    query = dict(request.query)
    if request.path.endswith("/updates"):
        query["updates"] = "1"
    if request.path.endswith("/selection"):
        query["id"] = query.get("quote_key") or query.get("id", "")
    if query.get("browse_odds") == "1":
        query["browse"] = "1"

    cancelled = Event()
    read_seconds = (
        ARBITRAGE_READ_DEADLINE_SECONDS
        if request.path.endswith("/arbs")
        else READ_DEADLINE_SECONDS
    )
    deadline = monotonic() + read_seconds

    def work():
        from app.storage.current_pregame import read

        if request.path.endswith("/arbs"):
            from app.storage.pregame_arbs import read

        started = monotonic()
        with (connector or connect)() as db, db.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            # Keep an abandoned read from occupying SQL indefinitely. Python
            # pairing also checks this same request deadline between groups.
            db.execute("SET LOCAL statement_timeout='8s'")
            from app.collection.activity_mode import read_status
            from app.storage.pregame_cohorts import select as select_cohort

            mode = read_status(db)
            if query.get("mode_status") == "1":
                return dict(
                    activity_mode=mode, provider_requests=0, scheduled_calculations=0
                )
            browse = query.get("browse") == "1" or query.get("view") in (
                "games",
                "game",
            )
            kind = query.get("data_type") or ("all" if browse else mode["mode"])
            query["data_type"] = kind
            query.pop("_scope_seconds", None)
            scope = (
                mode["settings"]["live_window_seconds"]
                if kind == "live"
                else mode["settings"]["monitor_horizon_seconds"]
                if kind == "monitor"
                else None
            )
            if scope:
                query["_scope_seconds"] = str(scope)
            select_cohort(db, kind)
            if request.path.endswith("/research"):
                from app.storage.pregame_research import research
                from app.storage.current_pregame import utc

                return research(db, research_body, at=utc())
            if request.path.endswith("/arbs"):
                result = read(
                    db,
                    query,
                    can_continue=lambda: (
                        not cancelled.is_set() and monotonic() < deadline
                    ),
                )
            else:
                result = read(db, query)
            from app.storage.pregame_quote_evidence import enrich

            if query.get("bet_id") or query.get("id"):
                result["rows"] = enrich(db, result.get("rows", []))
            elif request.path.endswith("/arbs"):
                legs = [leg for pair in result["rows"] for leg in pair["legs"]]
                evidence = enrich(db, legs)
                result = dict(
                    result,
                    rows=[
                        dict(pair, legs=evidence[i * 2 : i * 2 + 2])
                        for i, pair in enumerate(result["rows"])
                    ],
                )
        return dict(
            result,
            data_type=kind,
            activity_mode=mode,
            read_ms=round((monotonic() - started) * 1000, 3),
        )

    research_body = None
    if request.path.endswith("/research"):
        from .local_security import read_json

        research_body = await read_json(request)
    try:
        async with asyncio.timeout(read_seconds):
            result = await asyncio.to_thread(work)
    except (TimeoutError, QueryCanceled):
        return web.json_response(
            dict(
                error="current_read_timeout",
                message="Stored comparisons took too long. Retry to verify prices.",
            ),
            status=503,
        )
    except (TypeError, ValueError) as exc:
        from app.storage.pregame_research import ChangedInputs

        if isinstance(exc, ChangedInputs):
            return web.json_response(dict(error=str(exc)), status=409)
        if research_body is not None:
            return web.json_response(
                dict(
                    error="This amount cannot be evaluated with the retained inputs. Enter a cash budget with cents precision or check current alternatives."
                ),
                status=422,
            )
        raise web.HTTPBadRequest(text="Invalid current pregame query") from None
    except Exception as exc:
        from app.diagnostics import failure

        failure(__name__, "current_pregame_read", exc)
        return web.json_response(dict(error="current_read_failed"), status=503)
    finally:
        cancelled.set()
    return web.json_response(result, headers={"Cache-Control": "no-store"})


def mount(app):
    async def health(request):
        def probe():
            with connect() as db, db.transaction():
                db.execute("SET TRANSACTION READ ONLY")
                db.execute(
                    "SELECT revision FROM current_pregame_revision WHERE singleton"
                ).fetchone()
                db.execute(
                    "SELECT contract_id FROM current_pregame_calculation LIMIT 1"
                ).fetchone()
            return dict(read_available=True)

        try:
            return web.json_response(await asyncio.to_thread(probe))
        except Exception:
            return web.json_response(dict(read_available=False), status=503)

    app.router.add_get("/api/health", health)
    app.router.add_get("/api/pregame", response)
    app.router.add_get("/api/pregame/arbs", response)
    app.router.add_get("/api/pregame/updates", response)
    app.router.add_post("/api/pregame/research", response)
