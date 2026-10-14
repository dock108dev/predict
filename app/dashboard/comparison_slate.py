"""One bounded, acquisition-free read of all upcoming NFL comparison boards."""
from datetime import datetime, timezone

from app.dashboard.comparison_board import response
from app.storage.comparison_board import ReadContext, discover, saved, view_bundle
from app.storage.current_games import GameStore
from app.storage.store import encoded

VERSION = 'predict-comparison-slate-1'
MAX_GAMES = 200
MAX_BYTES = 8 * 1024 * 1024


def upcoming(game, at):
    start = game.get('start_at')
    if not start:
        return True
    try:
        return datetime.fromisoformat(start.replace('Z', '+00:00')) > at
    except (TypeError, ValueError):
        return True


def read(db, policy, *, view, filter, stopped):
    at = datetime.now(timezone.utc)
    store = GameStore(db)
    context = ReadContext(store, at=at.isoformat())
    games = [g for g in context.catalog()['games'] if upcoming(g, at)]
    games.sort(key=lambda g: (g.get('start_at') or '', g['game_key']))
    if len(games) > MAX_GAMES:
        raise ValueError('slate_game_capacity')
    boards, errors, pending = [], [], []
    for game in games:
        key = game['game_key']
        selected,bundle,value=None,None,None
        try:
            selected=discover(store,benchmark_venue=policy.benchmark_venue,context=context,game=key,cache=False)
            if len(selected)!=1 or selected[0]['game_key']!=key:
                raise ValueError('board_occurrence_absent_or_ambiguous')
            bundle = view_bundle(store, selected[0], policy, context=context)
            value = saved(store, key, policy, context=context)
            if value is not None:
                value['engine_binding_changed'] = value['engine_binding'] != context.engine
            board = response(bundle, value, policy, view=view, filter=filter, stopped=stopped)
            boards.append(board)
            if value is None or value['superseded']:
                pending.append(key)
        except (KeyError, ValueError):
            errors.append(dict(game_key=key, reason='game_inputs_unavailable'))
        finally:
            selected,bundle,value=None,None,None
    out = dict(version=VERSION, view=view, filter=filter, policy=policy.to_dict(),
               games=games, boards=boards, errors=errors, stopped=stopped,
               as_of=at.isoformat(), bounds=dict(maximum_games=MAX_GAMES, maximum_bytes=MAX_BYTES),
               provider_requests=0)
    if len(encoded(out)) > MAX_BYTES:
        raise ValueError('slate_response_byte_capacity')
    return out, pending


def schedule(database, keys, policy):
    """Fairly admit visible requests into the unchanged bounded local queue.

    One cursor follows the current requested policy. Persistently changing early
    games cannot consume every freed slot before later visible games are tried.
    Existing queued work/generations retain their identities and order.
    """
    if getattr(database, 'closed', False):
        return
    keys=list(dict.fromkeys(keys))
    if len(keys)>MAX_GAMES:raise ValueError('slate_game_capacity')
    if not keys:return
    cursor=getattr(database,'_slate_schedule_cursor',None)
    start=(keys.index(cursor[1])+1)%len(keys) if cursor and cursor[0]==policy.revision and cursor[1] in keys else 0
    ordered=keys[start:]+keys[:start]
    remaining = getattr(database, 'MAX_PENDING', 4)
    for key in ordered:
        queue = getattr(database, 'pending', {})
        if (key, policy.revision) in queue:
            continue
        if len(queue) >= remaining:
            break
        try:
            database.request(key, policy)
            database._slate_schedule_cursor=(policy.revision,key)
        except ValueError:
            break
