"""Browser endpoints for retained paper research and original evidence."""

import asyncio
import re

from aiohttp import web

from app.collection.odds_http import BudgetStop
from app.owned_work import joined_thread
from app.research import workspace
from app.storage.store import connect, encoded
from .local_security import HEADERS, PublicRequestError, read_json

BASE = "/api/research/workspace"


def _response(value, *, filename=None):
    headers = dict(HEADERS)
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return web.Response(body=encoded(value), content_type="application/json", headers=headers)


def _identity(value):
    if not workspace.HASH.fullmatch(value):
        raise PublicRequestError("Select a saved research identity.")
    return value


def mount(app):
    gate = asyncio.Semaphore(2)

    async def work(fn, *args, read_only=True, **kwargs):
        def operation():
            with connect() as db:
                db.execute("SET statement_timeout='10s'")
                if not read_only:
                    return fn(db, *args, **kwargs)
                with db.transaction():
                    db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    return fn(db, *args, **kwargs)

        try:
            async with asyncio.timeout(45), gate:
                return await joined_thread(__name__, "research_workspace_after_cancellation", operation)
        except workspace.UnknownSelection as exc:
            raise web.HTTPNotFound(reason=str(exc)) from None
        except workspace.SelectionError as exc:
            raise PublicRequestError(str(exc)) from None
        except BudgetStop:
            raise web.HTTPServiceUnavailable(reason="Research storage has insufficient free disk for this replay.") from None
        except TimeoutError:
            raise web.HTTPServiceUnavailable(reason="The research workspace is busy. Retry shortly.",
                                             headers={"Retry-After": "1"}) from None

    async def index(request):
        if request.query:
            raise PublicRequestError("The research workspace takes no filters.")
        return _response(await work(workspace.index))

    async def run(request):
        query = dict(request.query)
        if query not in ({}, {"export": "1"}):
            raise PublicRequestError("Invalid saved run view.")
        identity = _identity(request.match_info["run_id"])
        value = await work(workspace.run_detail, identity, export=bool(query))
        return _response(value, filename=f'predict-research-{value["run"]["date"]}-{identity[:12]}.json' if query else None)

    async def replay(request):
        if request.query:
            raise PublicRequestError("Replay options belong in the JSON body.")
        body = await read_json(request)
        fields = {"date", "definition_version"}
        if not isinstance(body, dict) or not fields <= set(body) or set(body) - fields - {"assumptions", "experiment"}:
            raise PublicRequestError("Provide the Eastern game date and experiment definition version.")
        version = body["definition_version"]
        if not isinstance(version, str) or not re.fullmatch(r"[0-9a-z-]{1,64}", version):
            raise PublicRequestError("Select an experiment definition version.")
        try:
            day = workspace.game_day(body["date"])
            values = workspace.assumptions(body.get("assumptions", {}))
            registration = workspace.experiment_registration(body["experiment"]) if "experiment" in body else None
        except workspace.SelectionError as exc:
            raise PublicRequestError(str(exc)) from None
        return _response(await work(workspace.replay, day, version, values, registration=registration, read_only=False))

    async def ticket(request):
        if request.query:
            raise PublicRequestError("The saved ticket takes no filters.")
        identity = _identity(request.match_info["run_id"])
        return _response(await work(workspace.ticket_detail, identity, _identity(request.match_info["ticket_id"])))

    async def evidence(request):
        query = dict(request.query)
        if query not in ({}, {"export": "1"}, {"raw": "1"}):
            raise PublicRequestError("Invalid research evidence view.")
        identity = _identity(request.match_info["run_id"])
        game = _identity(request.match_info["game_id"])
        if "raw" in query:
            digest, body = await work(workspace.raw_response, identity, game)
            return web.Response(body=body, content_type="application/json", headers={**HEADERS,
                "Content-Disposition": f'attachment; filename="predict-original-{digest}.json"'})
        value = await work(workspace.game_evidence, identity, game, export=bool(query))
        return _response(value, filename=f"predict-checkpoint-{game[:12]}.json" if query else None)

    app.router.add_get(BASE, index)
    app.router.add_post(BASE + "/runs", replay)
    app.router.add_get(BASE + "/runs/{run_id}", run)
    app.router.add_get(BASE + "/runs/{run_id}/tickets/{ticket_id}", ticket)
    app.router.add_get(BASE + "/runs/{run_id}/evidence/{game_id}", evidence)
