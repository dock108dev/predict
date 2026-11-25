"""Authenticated owner controls. GETs never renew activity or collect prices."""

import asyncio
from aiohttp import web
from app.collection import activity_mode
from .local_security import read_json


def mount(app, *, read_only=False):
    async def get(request):
        return web.json_response(await asyncio.to_thread(activity_mode.read_status))

    async def patch(request):
        body = await read_json(request)
        if not isinstance(body, dict) or not body or set(body) - {"mode", "settings"}:
            raise web.HTTPBadRequest(text="Exact activity mode/settings required")
        try:
            result = await asyncio.to_thread(activity_mode.patch, **body)
        except ValueError:
            raise web.HTTPBadRequest(text="Invalid activity mode or settings") from None
        return web.json_response(result)

    async def activity(request):
        if await read_json(request) != {}:
            raise web.HTTPBadRequest(text="Empty owner activity object required")
        return web.json_response(await asyncio.to_thread(activity_mode.activity))

    app.router.add_get("/api/admin/activity-mode", get)
    if not read_only:
        app.router.add_patch("/api/admin/activity-mode", patch)
        app.router.add_post("/api/admin/activity-mode/activity", activity)
