"""Current-row comparison reads and transient financial calculation endpoints."""
import asyncio
from aiohttp import web
from app.storage.store import connect, encoded
from app.storage.current_games import GameStore
from app.storage.comparison_board import ReadContext, discover, calculate_current, context_identity
from app.comparison.estimated_policy import load
from .query_policy import calculation_policy
from .comparison_board import response, details, entries, quote_key
from .local_security import PublicRequestError
from .comparison_slate import MAX_BYTES
from app.comparison.calculation_availability import result_availability


def mount(app,provider):
    from .scanner_api import mount as mount_scanner
    mount_scanner(app,provider)
    def stopped():return provider.closed or provider.closing or not provider.dispatch
    read_lock=asyncio.Lock()
    pending_reads=0
    def read(req,p):
        view=req.match_info['view']
        if view=='readiness':
            from copy import deepcopy
            from app.comparison.scanner_readiness import Selection
            from app.storage.scanner_readiness import read as readiness_read
            from app.storage.current_games import utc
            selected=Selection(**{k:tuple(req.query[k].split(',')) for k in req.query})
            states=deepcopy(provider.states)
            if stopped():
                states={v:dict(state='stopped') for v in selected.venues}
            with connect() as db:
                return readiness_read(db,config=deepcopy(provider.config),authority=provider.config.get('authority'),
                                      at=utc(),selection=selected,source_status=states)
        with connect() as db:
            if view=='slate':
                from .comparison_slate import read as slate_read
                return slate_read(db,p,view=req.query.get('view','odds'),filter=req.query.get('filter','positive'),stopped=stopped(),offset=int(req.query.get('offset','0')),limit=int(req.query.get('limit','25')),expected_revision=req.query.get('expected_revision'))[0]
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                context=ReadContext(GameStore(db))
                if view=='games':return dict(context.catalog(),stopped=stopped())
                bundle=discover(context.store,benchmark_venue=p.benchmark_venue,context=context,game=req.query['game'])[0]
                identity=context_identity(bundle,p,context);bundle['calculation_context']=identity
                if view in ('details','inputs') and req.query.get('context_id')!=identity['context_id']:raise ValueError('current_inputs_changed_or_removed')
        # Captured typed inputs are detached before any financial calculation.
        if view=='inputs':
            quote=req.query.get('quote')
            q=next((q for _,_,q in entries(bundle['state_inputs']) if quote_key(q)==quote),None)
            if q is None:raise ValueError('current_selection_removed')
            out=dict(version='predict-board-inputs-2',game_key=bundle['game_key'],quote_id=quote,calculation_context=identity,evidence=dict(event=bundle['state_inputs']['events'][0]['title'],selection=q['binding']['selection'],source=q['source'],original=q['original'],times=q['times'],native_contract=q.get('native_contract'),provenance=q.get('provenance'),benchmark=bundle['benchmark'],representation=bundle['representation']),provider_requests=0)
        elif view=='details':
            value=calculate_current(bundle,p,context=context,details=True,selected_quote=req.query.get('quote'),selected_pair=req.query.get('pair'))
            out=details(value,quote=req.query.get('quote'),pair=req.query.get('pair'),at=context.at,current=bundle['state_inputs'],stopped=stopped())
        else:
            value=None if view=='odds' else calculate_current(bundle,p,context=context)
            out=response(bundle,value,p,view=view,filter=req.query.get('filter','positive'),at=context.at,stopped=stopped())
        if len(encoded(out))>MAX_BYTES:raise ValueError('board_response_byte_capacity')
        return out
    def controlled_read(req,p):
        from app.comparison.calculation_control import cancellation,checkpoint
        initially_stopped=stopped()
        with cancellation(lambda:not initially_stopped and stopped()):
            out=read(req,p)
            checkpoint()
            return out
    async def handle(req):
        nonlocal pending_reads
        view=req.match_info['view']
        if view=='history' or req.query.get('history')=='true' or req.query.get('result_id'):
            return web.json_response(dict(error='sports_history_unavailable',reason='Ordinary sports history was retired; select a current comparison.',provider_requests=0),status=410)
        allowed={'game','amount','ceiling','buffer','sizing_mode','benchmark_venue','benchmark_method','filter','context_id','quote','pair'}
        if view=='slate':allowed=(allowed-{'game','context_id','quote','pair'})|{'view','offset','limit','expected_revision'}
        if view=='readiness':allowed={'venues','sports','leagues','markets','periods'}
        if view not in ('readiness','games','slate','odds','ev','arbs','details','inputs') or set(req.query)-allowed:raise PublicRequestError('Unsupported current comparison query')
        if view=='games' and req.query:raise PublicRequestError('Catalog does not accept calculation settings')
        if view not in ('readiness','games','slate') and not 1<=len(req.query.get('game',''))<=256:raise PublicRequestError('Exact bounded occurrence required')
        if view=='slate' and req.query.get('view','odds') not in ('odds','ev','arbs'):raise PublicRequestError('Unsupported slate view')
        if req.query.get('filter','positive') not in ('positive','all','hedges'):raise PublicRequestError('Unsupported comparison filter')
        if view in ('details','inputs') and not req.query.get('context_id'):raise PublicRequestError('Expected current context required')
        if any(len(v)>256 for v in req.query.values()):raise PublicRequestError('Comparison query value capacity')
        if view=='readiness':
            from app.comparison.scanner_readiness import Selection
            try:Selection(**{k:tuple(req.query[k].split(',')) for k in req.query})
            except ValueError as exc:raise PublicRequestError(str(exc)) from None
        p=None if view=='readiness' else calculation_policy(req.query,load())
        if pending_reads>=5:return web.json_response(dict(error='current_read_busy',reason='Current comparison read capacity; retry shortly.',provider_requests=0),status=429)
        pending_reads+=1
        try:
            async with read_lock:
                task=asyncio.create_task(asyncio.to_thread(controlled_read,req,p))
                try:out=await asyncio.shield(task)
                except asyncio.CancelledError:
                    # A disconnected request cannot release the memory slot while its worker lives.
                    try:await asyncio.shield(task)
                    finally:raise
            if view=='slate':
                out['storage']=provider.database.status()
                if len(encoded(out))>MAX_BYTES:raise ValueError('board_response_byte_capacity')
            return web.json_response(out)
        except ValueError as exc:return web.json_response(dict(error='current_inputs_unavailable',reason=str(exc),availability=result_availability(dict(reasons=['calculation_read_failed'])),provider_requests=0),status=409)
        except Exception as exc:
            from app.comparison.calculation_control import CalculationStopped
            if isinstance(exc,CalculationStopped):return web.json_response(dict(error='current_read_stopped',reason='Updates stopped during calculation; reopen the current view.',provider_requests=0),status=409)
            return web.json_response(dict(error='database_unavailable',reason=type(exc).__name__,availability=result_availability(dict(reasons=['calculation_read_failed'])),provider_requests=0),status=503)
        finally:pending_reads-=1
    app.router.add_get('/api/boards/{view}',handle)
