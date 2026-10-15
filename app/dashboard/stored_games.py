"""Ordinary current boards and explicit retirement of sports archive endpoints."""
from aiohttp import web


def mount(app, provider):
    from .comparison_board_api import mount as mount_boards
    mount_boards(app, provider)

    async def retired(req):
        return web.json_response(dict(
            error='sports_history_unavailable',
            reason='Disposable sports archives were retired. Open the current Odds, EV or Arbs board.',
            current_url='/', provider_requests=0), status=410)

    app.router.add_get('/api/stored/games', retired)
    app.router.add_get('/api/stored/result', retired)
