"""Read-only HTTP boundary for committed current pregame opportunities."""

import asyncio
from time import monotonic
from threading import Event

from aiohttp import web
from psycopg.errors import QueryCanceled

from app.storage.store import connect

READ_DEADLINE_SECONDS = 10

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
    deadline = monotonic() + READ_DEADLINE_SECONDS

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
        return dict(result, read_ms=round((monotonic() - started) * 1000, 3))

    try:
        async with asyncio.timeout(READ_DEADLINE_SECONDS):
            result = await asyncio.to_thread(work)
    except (TimeoutError, QueryCanceled):
        return web.json_response(
            dict(
                error="current_read_timeout",
                message="Stored comparisons took too long. Retry to verify prices.",
            ),
            status=503,
        )
    except (TypeError, ValueError):
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
