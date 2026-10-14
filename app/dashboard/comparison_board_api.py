"""Acquisition-free ordinary SQL comparison endpoints."""
import asyncio
from aiohttp import web
import json
from app.storage.store import connect, encoded
from app.storage.current_games import GameStore, engine_binding, utc
from app.storage.comparison_board import discover, choose, saved, catalog, view_bundle, storage_key
from app.comparison.estimated_policy import load
from .query_policy import calculation_policy
from .comparison_board import response, details
from .local_security import PublicRequestError


def mount(app, provider):
    def stopped():return provider.closed or provider.closing or not provider.dispatch
    def read(req,p):
        with connect() as db,db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            store=GameStore(db);view=req.match_info['view']
            if view=='history':
                rows=db.execute('SELECT r.id,r.snapshot_id,r.calculated_at FROM current_game_result r JOIN current_game_snapshot s ON s.id=r.snapshot_id WHERE s.game_key=%s AND s.policy_version=%s ORDER BY r.calculated_at DESC,r.id DESC LIMIT 50',
                    (storage_key(req.query['game'],p),p.revision)).fetchall()
                return dict(version='predict-board-history-1',game_key=req.query['game'],policy_revision=p.revision,
                    results=[dict(result_id=r['id'],snapshot_id=r['snapshot_id'],calculated_at=r['calculated_at'].isoformat()) for r in rows],maximum_results=50,provider_requests=0),False
            if view=='games':return catalog(discover(store))
            bundles=discover(store,benchmark_venue=p.benchmark_venue)
            missing_current=False
            try:b=view_bundle(store,choose(bundles,req.query['game']),p)
            except ValueError:
                if not req.query.get('result_id'):raise
                v=saved(store,req.query['game'],p,result_id=req.query['result_id'])
                row=db.execute('SELECT payload FROM current_game_snapshot WHERE id=%s',(v['snapshot_id'],)).fetchone()
                b=json.loads(row['payload'])['projection']['inputs'];missing_current=True
            if view=='inputs':
                if req.query.get('result_id'):
                    original=saved(store,b['game_key'],p,result_id=req.query['result_id'])
                    snapshot=db.execute('SELECT payload FROM current_game_snapshot WHERE id=%s',(original['snapshot_id'],)).fetchone()
                    b=json.loads(snapshot['payload'])['projection']['inputs']
                out=dict(version='predict-board-inputs-1',inputs=b,provider_requests=0)
                if len(encoded(out))>8*1024*1024:raise ValueError('board_inputs_byte_capacity')
                return out,False
            v=saved(store,b['game_key'],p,result_id=req.query.get('result_id'))
            if v:v['engine_binding_changed']=v['engine_binding']!=engine_binding()
            if req.match_info.get('view')=='details':
                if v is None:raise ValueError('saved_result_absent')
                out=details(v,quote=req.query.get('quote'),pair=req.query.get('pair'),current=dict(b['state_inputs'],events=[]) if missing_current else b['state_inputs'],stopped=stopped(),history=missing_current or req.query.get('history')=='true')
                if len(encoded(out))>8*1024*1024:raise ValueError('board_details_byte_capacity')
                return out,False
            out=response(b,v,p,view=req.match_info['view'],filter=req.query.get('filter','positive'),stopped=stopped(),history=missing_current or req.query.get('history')=='true')
            return out,v is None or v['superseded']
    async def handle(req):
        view=req.match_info['view']
        allowed={'game','amount','ceiling','buffer','sizing_mode','benchmark_venue','benchmark_method','filter','result_id','quote','pair','history'}
        if view not in ('games','odds','ev','arbs','details','inputs','history') or set(req.query)-allowed:raise PublicRequestError('Unsupported comparison board query')
        if view=='games' and req.query:raise PublicRequestError('Catalog does not accept calculation settings')
        if view!='games' and not 1<=len(req.query.get('game',''))<=256:raise PublicRequestError('Exact bounded occurrence required')
        if req.query.get('history','false') not in ('false','true'):raise PublicRequestError('History must be true or false')
        if any(len(v)>256 for v in req.query.values()):raise PublicRequestError('Board query value capacity')
        p=calculation_policy(req.query,load())
        try:
            output=await asyncio.to_thread(read,req,p)
            if view=='games':return web.json_response(dict(output,stopped=stopped()))
            out,pending=output
            if pending and not stopped() and not req.query.get('result_id') and req.query.get('history')!='true':
                provider.database.request(out['game_key'],p)
            return web.json_response(out,status=202 if out.get('delivery_state')=='pending' else 200)
        except ValueError as exc:return web.json_response(dict(error='board_unavailable',reason=str(exc),provider_requests=0),status=409)
        except Exception as exc:return web.json_response(dict(error='database_unavailable',reason=type(exc).__name__,provider_requests=0),status=503)
    app.router.add_get('/api/boards/{view}',handle)
