"""Passive paper backtests and latest-pull previews; no execution endpoints."""

import asyncio
from datetime import date

from aiohttp import web

from app.storage.store import connect, encoded
from .local_security import HEADERS, PublicRequestError


def mount(app):
    gate = asyncio.Semaphore(2)

    async def read(request):
        if set(request.query) - {"date", "export", "revision"} or request.query.get("export") not in (None, "1"):
            raise PublicRequestError("Invalid paper experiment selection.")
        day = request.query.get("date", "2026-11-23")
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
        except ValueError:
            raise PublicRequestError("Use a game date in YYYY-MM-DD format.") from None
        exporting = request.query.get("export") == "1"
        is_latest = request.path.endswith("/latest")
        if exporting and is_latest:
            raise PublicRequestError("Export the frozen backtest rather than a changing preview.")
        revision = request.query.get("revision")
        if revision and (not exporting or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision)):
            raise PublicRequestError("Invalid paper report revision.")

        def work():
            from app.research.paper import report
            from app.research.paper_latest import latest
            with connect() as db, db.transaction():
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                db.execute("SET LOCAL statement_timeout='10s'")
                return latest(db, day) if is_latest else report(db, day, evidence=exporting)

        from app.owned_work import joined_thread
        try:
            async with asyncio.timeout(45), gate:
                value = await joined_thread(__name__, "paper_read_after_cancellation", work)
        except TimeoutError:
            return web.json_response(dict(error="Paper evidence read timed out. Retry the backtest."), status=503, headers=HEADERS)
        if exporting:
            if revision and revision != value["report_revision"]:
                return web.json_response(dict(error="Paper evidence changed. Run the backtest again before exporting."), status=409, headers=HEADERS)
            return web.Response(body=encoded(value), content_type="application/json", headers={**HEADERS,
                "Content-Disposition": f'attachment; filename="predict-paper-{day}.json"'})
        return web.Response(body=encoded(value), content_type="application/json", headers=HEADERS)

    app.router.add_get("/api/research/paper", read)
    app.router.add_get("/api/research/paper/latest", read)
