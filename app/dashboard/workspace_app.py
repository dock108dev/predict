"""The installed Predict application and its retained-evidence routes."""

from pathlib import Path

from aiohttp import web

from . import (
    activity_mode_api,
    admin_database,
    current_pregame_api,
    raw_price_api,
    replay_api,
    research_api,
    snapshot_api,
    workspace_routes,
    workspace_sessions,
)
from .local_security import IMPORT_BODY_LIMIT
from .request_guard import dashboard_guard
from .workspace_collection import mount as mount_collection

ROOT = Path(__file__).parent
ASSETS = ROOT / 'opportunity_static/current'
# Only these modules and styles are part of the installed pages' import graph.
# Legacy fixture renderers remain available to their offline harnesses.
WORKSPACE_ASSETS = frozenset("""
    admin-database.css admin-database.js barlow-semi-condensed-600.ttf
    board-client.js board-contract.js board-elements.js board-read.js board-values.js
    comparison-board.js dashboard.css dashboard.js data-browser.css data-captures.js
    data-evidence.js data-market.js data-sessions.js data-workbench.js data.js
    desk-preferences.js experiment-depth.js experiment-populations.js experiment-workspace.css
    experiment-workspace.js experiment.js ibm-plex-sans.woff2 manrope.ttf
    mens-d1-coverage.js predict-icon.png pregame-evidence.js pregame-explanation.js
    pregame-labels.js pregame-prices.js pregame-ranking.js pregame.css
    research-campaigns.js research-issues.js research-ledger.js research-quality.js
    research-results.js research-run.js research-workspace.css research.css
    settings-accounting.js settings.css settings.js workbench-shell.css
    workspace-format.js workspace-nav.js workspace-scope.js workspace-ui.js
""".split())


def create_app(provider, owner):
    app = web.Application(
        middlewares=[dashboard_guard(provider, logger=__name__),
                     workspace_routes.compatibility_middleware()],
        client_max_size=IMPORT_BODY_LIMIT,
        handler_args={'auto_decompress': False},
    )
    workspace_routes.mount(app, ROOT)
    workspace_sessions.mount(app, owner)
    current_pregame_api.mount(app, health_only=True)
    activity_mode_api.mount(app, read_only=True)
    admin_database.mount(app)
    research_api.mount(app, campaigns_only=True)
    snapshot_api.mount(app, retained_only=True)
    replay_api.mount(app)
    raw_price_api.mount(app)
    mount_collection(app, provider)
    async def asset(request):
        name = request.match_info['name']
        if name not in WORKSPACE_ASSETS:
            raise web.HTTPNotFound()
        return web.FileResponse(ASSETS / name)

    async def close(_app):
        await owner.close()

    app.router.add_get('/view/current/{name}', asset)
    app.on_cleanup.append(close)
    return app
