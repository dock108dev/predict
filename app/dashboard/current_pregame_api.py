"""Read-only HTTP boundary for committed current pregame opportunities."""

import asyncio
from time import monotonic

from aiohttp import web

from app.storage.store import connect

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

    def work():
        from app.storage.current_pregame import read

        if request.path.endswith("/arbs"):
            from app.storage.pregame_arbs import read

        started = monotonic()
        with (connector or connect)() as db, db.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            result = read(db, query)
        return dict(result, read_ms=round((monotonic() - started) * 1000, 3))

    try:
        result = await asyncio.to_thread(work)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Invalid current pregame query") from None
    except Exception as exc:
        from app.diagnostics import failure

        failure(__name__, "current_pregame_read", exc)
        return web.json_response(dict(error="current_read_failed"), status=503)
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
