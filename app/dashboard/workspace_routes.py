"""Personal-workspace HTML compatibility without changing API ownership."""
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit

from aiohttp import web

from .local_security import HEADERS, PublicRequestError, read_json

# Keep local selection context, never an arbitrary redirect target.
SELECTION_KEYS = frozenset('search sport date date_from date_to family provider original_bookmaker_id calculation_status max_age_minutes view game bet token revision offset record_offset capture id bet_id quote_key line game_key phase game_capture result_id receipt receipt_offset source_event event_id case context include_context mode data_type market venue league dataset selection saved_bet selected_metric pair pair_revision session hash cutoff quantity scenario candidate contract reference research probability basis rule_version competition season period reference_scope book run campaign variant ticket evidence pull scope coverage_game coverage_filter coverage_job result trade filter trade_filter sort include_alternates from sizing_quote sizing_bet trade_ev trade_sort trade_page ledger_view snapshot schema object rows storage views'.split())
SELECTION_KEYS |= frozenset('game_sport trade_sport trade_family trade_venue trade_rows board_sport board_family board_venue board_offset board_rows data_rows tracked_game'.split())
CATALOG_CONTEXT = {'search', 'sport', 'provider', 'original_bookmaker_id', 'book', 'family', 'calculation_status', 'max_age_minutes', 'game', 'bet', 'reference_scope'}
DATA_PATHS = {'/browse-odds', '/odds', '/raw-odds', '/game', '/replay', '/admin/retained'}
RETIRED_PATHS = {'/arbs', '/scanner', '/my-bets', '/about', '/trading-fees'}
HTML_DESTINATIONS = {
    'dashboard.html': '/', 'experiment-workspace.html': '/experiments',
    'experiments.html': '/experiments', 'research-workspace.html': '/research',
    'research.html': '/research', 'data.html': '/data',
    'settings.html': '/settings', 'admin.html': '/admin',
    'coverage.html': '/data?evidence=mens-d1', 'ev.html': '/',
    'index.html': '/', 'pregame.html': '/data', 'desk.html': '/data',
    'stored.html': '/data', 'raw-odds.html': '/data',
}
PAGES = {'/': 'dashboard.html', '/data': 'data.html',
         '/experiments': 'experiment-workspace.html', '/settings': 'settings.html'}


def destination(request):
    """Keep exact evidence bookmarks usable after retiring the old pages."""
    path = request.path.rstrip('/') or '/'
    if path == '/':
        if 'id' in request.query or set(request.query) & CATALOG_CONTEXT:
            target = '/data'
        else:
            return None
    elif path == '/research':
        if 'id' in request.query and 'revision' in request.query:
            target = '/data?evidence=checkpoints'
        elif request.query.get('section') == 'experiments' or any(
                request.query.get(key) for key in ('campaign', 'run', 'result', 'trade')):
            target = '/experiments'
        elif set(request.query) & CATALOG_CONTEXT:
            target = '/data'
        elif request.query.get('section') in ('coverage', 'quality'):
            target = '/data'
        else:
            target = '/experiments'
    elif path in PAGES:
        if path == '/experiments' and ('id' in request.query or 'context' in request.query):
            target = '/data?evidence=checkpoints'
        elif request.path != path:
            target = path
        else:
            return None
    elif path in DATA_PATHS:
        target = '/data'
    elif path in ('/dashboard', '/ev', '/opportunities'):
        target = '/data' if request.query.get('id') else '/'
    elif path in ('/coverage', '/current/coverage'):
        target = '/data?evidence=mens-d1'
    elif path == '/admin':
        section = request.query.get('section')
        if section == 'database':
            target = '/data?evidence=tables'
        elif section in ('calculations', 'inspection', 'timing', 'quality', 'retained'):
            target = '/data'
        else:
            anchor = {'coverage':'storage', 'usage':'credits', 'sources':'sources',
                      'settings':'preferences'}.get(section, 'collection')
            target = '/settings#' + anchor
    elif path in ('/view', '/view/current'):
        target = '/'
    elif path.startswith('/view/') and (path.endswith('.html') or request.path.endswith('/')):
        name = Path(path).name
        target = '/data' if name == 'dashboard.html' and request.query.get('capture') else HTML_DESTINATIONS.get(name)
        if target in ('/admin', '/research'):
            return destination(SimpleNamespace(path=target, query=request.query))
        if target is None:
            return 'retired'
    elif path in RETIRED_PATHS:
        return 'retired'
    else:
        return None
    parts = urlsplit(target)
    query = {key: value for key, value in request.query.items()
             if key in SELECTION_KEYS and len(value) <= 1024}
    query.update(dict(parse_qsl(parts.query)))
    if parts.path == '/experiments' and query.get('view') == 'schedule':
        query['view'] = 'create'
    if parts.path == '/data' and any(request.query.get(key) for key in ('original_bookmaker_id', 'book', 'venue')):
        query.setdefault('reference_scope', 'all')
        if not query.get('original_bookmaker_id'):
            book = query.get('book') or query.get('venue')
            if not query.get('provider') or query.get('provider') == 'sportsgameodds':
                book = {'polymarket_us': 'polymarket', 'prophetx': 'prophetexchange'}.get(book, book)
            query['original_bookmaker_id'] = book
    back = urlsplit(request.query.get('back', ''))
    if not back.scheme and not back.netloc and back.path in (
            DATA_PATHS | set(PAGES) | {'/research', '/ev', '/opportunities'}):
        back_query = {key: value for key, value in parse_qsl(back.query)
                      if key in SELECTION_KEYS and len(value) <= 1024}
        adapted = destination(SimpleNamespace(path=back.path, query=back_query))
        query['back'] = adapted or back.path + ('?' + urlencode(back_query) if back_query else '')
    # Old links used source_event; the catalog filters exact native event IDs.
    if query.get('source_event') and not query.get('event_id'):
        query['event_id'] = query['source_event']
    return parts.path + ('?' + urlencode(query) if query else '') + ('#' + parts.fragment if parts.fragment else '')


def compatibility_middleware():
    @web.middleware
    async def compatibility(request, handler):
        if request.method in ('GET', 'HEAD'):
            dataset = request.query.get('dataset')
            if dataset is not None and request.path.rstrip('/') in ('/replay', '/data'):
                from app.storage.odds_replay import DATASETS

                if dataset not in (*DATASETS, 'retained'):
                    raise PublicRequestError('Unknown replay dataset')
            target = destination(request)
            if target == 'retired':
                return web.Response(status=410, content_type='text/html', headers=HEADERS, text='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Predict · Retired page</title><link rel="stylesheet" href="/view/current/pregame.css"><script type="module" src="/view/current/workspace-nav.js"></script></head><body><header class="masthead"><a class="brand" href="/">Predict</a><nav aria-label="Main" data-workspace-nav></nav></header><main class="board-wrap"><h1>This page is retired</h1><p><a href="/">Open Dashboard</a> or <a href="/data">open Data</a>.</p></main></body></html>''')
            if target:
                raise web.HTTPFound(target)
        return await handler(request)
    return compatibility


def mount(app, static_root):
    from .mens_d1_coverage_api import mount as mount_daily_coverage
    mount_daily_coverage(app, read_only=True)

    async def page(request):
        return web.FileResponse(static_root / 'opportunity_static/current' / PAGES[request.path], headers=HEADERS)

    for route in PAGES:
        app.router.add_get(route, page)

    async def status(request):
        if request.query:
            raise web.HTTPBadRequest(text='Workspace status takes no filters.')
        from app.owned_work import joined_thread
        from app.storage.store import connect
        from app.research.experiment import status as experiment_status
        from app.research.readiness import report as capture_readiness
        from app.comparison.reference_scope import public_scope
        from app.comparison.fee_mode import read as read_fee_mode
        from .pipeline import serial
        def read():
            with connect() as db, db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                db.execute("SET LOCAL statement_timeout='10s'")
                state = experiment_status(db)
                capture = db.execute("""SELECT checkpoint,min(target_at) target_at
                    FROM ev_experiment_task WHERE state='pending' AND checkpoint IN ('early','late') AND deadline_at>=transaction_timestamp()
                    GROUP BY checkpoint ORDER BY min(target_at) LIMIT 1""").fetchone()
                return dict(storage=state['storage'], readiness=capture_readiness(db, state),
                            next_capture=capture, provider_requests=0,
                            scheduled_calculations=0,
                            reference_scope=public_scope(), fee_mode=read_fee_mode(db))
        return web.json_response(serial(await joined_thread(__name__, 'workspace_status_after_cancellation', read)), headers=HEADERS)
    app.router.add_get('/api/workspace/status', status)


    async def fees(request):
        if request.query:
            raise PublicRequestError('Fee settings take no query options.')
        body = await read_json(request)
        if not isinstance(body, dict) or set(body) != {'enabled'} or type(body['enabled']) is not bool:
            raise PublicRequestError('Provide the exact boolean fee setting.')
        from app.owned_work import joined_thread
        from app.storage.store import connect
        from app.comparison.fee_mode import set_enabled

        def write():
            with connect() as db, db.transaction():
                db.execute("SET LOCAL statement_timeout='10s'")
                return set_enabled(db, body['enabled'])
        value = await joined_thread(__name__, 'fee_setting_after_cancellation', write)
        return web.json_response(dict(value, provider_requests=0), headers=HEADERS)
    app.router.add_patch('/api/workspace/fees', fees)
