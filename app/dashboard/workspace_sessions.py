"""Passive compatibility reads of the owner's verified legacy saved sessions."""
import asyncio
from pathlib import Path

from aiohttp import web

from app.owned_work import joined_thread
from app.storage.store import encoded, hashed
from .local_security import HEADERS, PublicRequestError

# Match the existing saved-projection cache's browser-facing memory allocation.
MAX_READ_BYTES = 16 * 1024 * 1024
# The existing session_history reader uses a 64 MiB preallocation limit for flat
# legacy sessions. Apply that bound to the entire selected package before replay.
MAX_INPUT_BYTES = 64 * 1024 * 1024
KEYS = frozenset('capture session hash cutoff contract candidate reference quantity scenario probability basis rule_version game offset'.split())
GENUINE_MODES = {'real', 'production', 'observation', 'current'}


def load_original(folder, cutoff):
    from .session_history import verified, project_rows
    # Source-chain verification and the bounded reducer are sufficient for input
    # evidence. Do not import a later native-review package or evaluate economics.
    source = verified(folder, stream_flat=True)
    snapshot = project_rows(source['rows'], cutoff, native_interpretation='original')
    sid = snapshot['session_id']
    if sid != folder.name and not (folder / 'session' / (sid + '.jsonl')).is_file():
        raise ValueError('saved session identity mismatch')
    snapshot['state'] = ('saved' if source['state'] == 'complete'
                         and 'failure' not in (snapshot.get('stop_reason') or '') else 'incomplete')
    return snapshot


def read_session(owner, query, *, loader=None):
    loader = loader or load_original
    if set(query) - KEYS or any(len(value) > 2048 for value in query.values()):
        raise PublicRequestError('Invalid saved session selection.')
    selected = query.get('session', '')
    sid, separator, game_id = selected.partition('~')
    sid = sid if selected else query.get('capture')
    game_id = game_id if separator else query.get('game')
    if not sid:
        raise PublicRequestError('Choose a retained session.')
    if query.get('hash') and query['hash'] != sid:
        raise PublicRequestError('Saved session identity differs from its bookmark.')
    try:
        offset = int(query.get('offset', 0))
        if not 0 <= offset <= 2147483647:
            raise ValueError()
    except ValueError:
        raise PublicRequestError('Invalid saved session page.') from None
    # Only paths supplied by the existing owner are readable. A bookmark never
    # becomes a filesystem path, and unrelated historical seed packages are not loaded.
    paths = owner.history_paths() if hasattr(owner, 'history_paths') else {}
    folder = paths.get(sid)
    if folder is None:
        raise PublicRequestError('This saved session is not retained on this installation. Its bookmark has not been replaced with current data.')
    folder = Path(folder)
    size = 0
    try:
        for path in folder.rglob('*'):
            if path.is_symlink():
                raise ValueError('saved package contains a symlink')
            if path.is_file():
                size += path.stat().st_size
                if size > MAX_INPUT_BYTES:
                    raise ValueError('saved package exceeds existing input read allocation')
        snapshot = loader(folder, query.get('cutoff') or None)
    except (OSError, ValueError, KeyError):
        raise PublicRequestError('The saved session or exact cutoff could not be verified. Original evidence remains preserved; no latest observation was substituted.') from None
    if snapshot.get('session_id') != sid or snapshot.get('data_mode') not in GENUINE_MODES:
        raise PublicRequestError('This bookmark does not identify a genuine received-data session.')
    games = snapshot.get('games', [])
    contract = query.get('contract')
    if not game_id and contract:
        matches = [g for g in games if contract in g.get('sides', {})]
        if len(matches) == 1:
            game_id = matches[0]['id']
        else:
            raise PublicRequestError('The exact bookmarked contract is not uniquely present at this saved cutoff.')
    selected_game = next((g for g in games if g['id'] == game_id), None) if game_id else None
    if game_id and selected_game is None:
        raise PublicRequestError('The bookmarked game is not present at this exact saved cutoff.')
    if contract and contract not in selected_game.get('sides', {}):
        raise PublicRequestError('The bookmarked contract is not present in this game at the exact saved cutoff.')
    def summary(game):
        return {key:game.get(key) for key in ('id', 'title', 'scheduled_start', 'product_identity', 'sources', 'sides')}
    detail = None
    if selected_game:
        identity = selected_game.get('product_identity')
        detail = dict(game=selected_game, point=snapshot.get('points', {}).get(game_id),
                      source_rows=snapshot.get('rows_by_game', {}).get(game_id, []),
                      references=[r for r in snapshot.get('references', []) if r.get('market_identity') == identity],
                      selected_contract=contract, selected_candidate=query.get('candidate'),
                      request_assumptions={key:query[key] for key in ('quantity', 'scenario', 'probability', 'basis', 'reference', 'rule_version') if key in query})
    out = dict(schema='predict-saved-session-evidence-1', session_id=sid, cutoff=snapshot['durable_cursor'],
               state=snapshot.get('state'), captured_at=snapshot.get('last_update'), data_mode=snapshot['data_mode'],
               games=[summary(g) for g in games[offset:offset+50]], total=len(games), offset=offset,
               next_offset=offset+50 if offset+50 < len(games) else None, selected=detail,
               provider_requests=0, scheduled_calculations=0,
               calculation_note='Verified source inputs at the selected saved cutoff. No new numeric calculation is run; historical request assumptions are preserved separately.')
    out['revision'] = hashed(out)
    if len(encoded(out)) > MAX_READ_BYTES:
        raise PublicRequestError('Selected session evidence exceeds the existing browser read allocation. The original saved session remains preserved.')
    return out


def mount(app, owner, *, loader=None):
    gate = asyncio.Semaphore(1)
    async def evidence(request):
        if gate.locked():
            raise web.HTTPTooManyRequests(reason='Another saved session is being verified; retry after it completes.')
        async with gate:
            value = await joined_thread(__name__, 'saved_session_after_cancellation',
                                        lambda: read_session(owner, dict(request.query), loader=loader))
        return web.json_response(value, headers=HEADERS)
    app.router.add_get('/api/workspace/session', evidence)
