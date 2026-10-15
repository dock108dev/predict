"""Bounded, coherent pages of the current NFL slate; no saved report dependency."""
from app.dashboard.comparison_board import response
from app.storage.comparison_board import ReadContext, discover, calculate_current, context_identity
from app.storage.current_games import GameStore
from app.storage.store import encoded

VERSION='predict-comparison-slate-2'
MAX_GAMES=500
MAX_PAGE_GAMES=50
MAX_BYTES=8*1024*1024



def read(db,policy, *, view,filter,stopped,offset=0,limit=25,expected_revision=None):
    if not 0<=offset<MAX_GAMES or not 1<=limit<=MAX_PAGE_GAMES:raise ValueError('slate_page_capacity')
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        context=ReadContext(GameStore(db));store=context.store
        if expected_revision and expected_revision!=context.read_revision:raise ValueError('current_slate_changed')
        games=context.catalog()['games'];games.sort(key=lambda g:(g.get('start_at') or '',g['game_key']))
        page=games[offset:offset+limit];captured=[]
        for game in page:
            try:
                bundle=discover(store,benchmark_venue=policy.benchmark_venue,context=context,game=game['game_key'],cache=False)[0]
                bundle['calculation_context']=context_identity(bundle,policy,context)
                captured.append((game,bundle,None))
            except (KeyError,ValueError) as exc:captured.append((game,None,str(exc)))
    # Finance has no open SQL transaction, writer lock or persistent publication.
    boards=[];errors=[]
    for game,bundle,error in captured:
        if error:
            errors.append(dict(game_key=game['game_key'],reason=error));continue
        try:
            value=None if view=='odds' else calculate_current(bundle,policy,context=context)
            boards.append(response(bundle,value,policy,view=view,filter=filter,stopped=stopped,at=context.at))
        except (KeyError,ValueError) as exc:errors.append(dict(game_key=game['game_key'],reason=str(exc)))
    end=offset+len(page);complete=end>=len(games)
    out=dict(version=VERSION,view=view,filter=filter,policy=policy.to_dict(),games=games,boards=boards,errors=errors,stopped=stopped,as_of=context.at,read_revision=context.read_revision,epoch=context.epoch,coverage=dict(total_games=len(games),offset=offset,limit=limit,returned_games=len(page),next_offset=None if complete else end,complete=complete),bounds=dict(maximum_games=MAX_GAMES,maximum_page_games=MAX_PAGE_GAMES,maximum_bytes=MAX_BYTES),provider_requests=0)
    if len(encoded(out))>MAX_BYTES:raise ValueError('slate_response_byte_capacity')
    return out,[]
