"""Small acquisition-free SQL reads for the ordinary installation."""
import asyncio
import json
from aiohttp import web
from app.storage.store import connect
from app.storage.current_games import GameStore,age_result
from app.comparison.estimated_policy import load
from .query_policy import calculation_policy
from .local_security import PublicRequestError


def mount(app,provider):
    from .comparison_board_api import mount as mount_boards
    mount_boards(app,provider)
    def read(key,policy,result_id=None):
        with connect() as db:
            store=GameStore(db)
            if result_id:
                row=db.execute('SELECT payload FROM current_game_result WHERE id=%s',(result_id,)).fetchone()
                if not row:raise ValueError('saved_result_absent')
                value=json.loads(row['payload']);value.update(result_id=result_id,superseded=True)
                if value['game_key']!=key:raise ValueError('saved_result_game_conflict')
                return age_result(value)
            return store.result(key,policy)
    async def catalog(req):
        if req.query:raise PublicRequestError('Unsupported stored game catalog query')
        def rows():
            with connect() as db:
                values=db.execute("SELECT game_key,input_version,payload::jsonb->'event' AS event FROM current_game_projection ORDER BY game_key LIMIT 200").fetchall()
                return [dict(game_key=r['game_key'],input_version=r['input_version'],title=r['event']['title'],
                    start_at=r['event']['scheduled_start'],source=r['game_key'].split(':')[0]) for r in values]
        try:return web.json_response(dict(games=await asyncio.to_thread(rows),selected=provider.database.selected,
            storage=provider.database.status(),stopped=not provider.dispatch))
        except Exception as exc:return web.json_response(dict(error='database_unavailable',reason=type(exc).__name__,storage=provider.database.status()),status=503)
    async def result(req):
        if set(req.query)-{'game','ceiling','buffer','amount','sizing_mode','benchmark_venue','benchmark_method','result_id','quote','pair'}:raise PublicRequestError('Unsupported saved calculation query')
        key=req.query.get('game','')
        if not key or len(key)>256:raise PublicRequestError('Exact bounded source-local game required')
        policy=calculation_policy(req.query,load())
        try:
            value=await asyncio.to_thread(read,key,policy,req.query.get('result_id'))
            if value is None:
                if provider.database.error and provider.database.failures>=5:return web.json_response(dict(error='saved_calculation_unavailable',reason=provider.database.error),status=503)
                if provider.closed or provider.closing:return web.json_response(dict(error='updates_stopped'),status=410)
                provider.database.request(key,policy)
                return web.json_response(dict(state='calculating',storage=provider.database.status()),status=202)
            if value['superseded'] and not provider.closed and not req.query.get('result_id'):provider.database.request(key,policy)
            if provider.closed or provider.closing or not provider.dispatch:
                value['status']='historical';value['stopped']=True
            state=value['state']
            if value.get('stopped'):
                from .current_contract import quotes_of
                for e in state['events']:
                    for p in e.get('funded_pairs',[]):
                        p['ranking_eligible']=False
                        if 'classification' in p:
                            p['classification']['main_positive_eligible']=False
                            p['classification']['positive_rule_sensitive_eligible']=False
                    for g in e['groups']:
                        for o in g['outcomes']:
                            for q in quotes_of(o):
                                estimate=q['calculations'].get('funded_estimate',{})
                                estimate['ranking_eligible']=False
                                if 'classification' in estimate:
                                    estimate['classification']['main_positive_eligible']=False
                                    estimate['classification']['positive_rule_sensitive_eligible']=False
            if req.query.get('quote') or req.query.get('pair'):
                from .current_contract import quotes_of
                quotes=[q for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]
                quote=next((q for q in quotes if q['id']==req.query.get('quote')),None)
                pair=next((p for e in state['events'] for p in e.get('funded_pairs',[]) if p['id']==req.query.get('pair')),None)
                if not quote and not pair:raise ValueError('exact_saved_selection_absent')
                return web.json_response(dict(result_id=value['result_id'],snapshot_id=value['snapshot_id'],game_key=key,
                    as_of=value['as_of'],status=value['status'],policy=value['policy'],quote=quote,pair=pair,
                    leg_quotes=[q for q in quotes if pair and q['id'] in {l['quote_id'] for l in pair['legs']}],envelope_ids=value['envelope_ids']))
            from app.comparison.estimated_ev import compact
            from app.comparison.estimated_pair import compact as pair_compact
            from .current_contract import quotes_of
            for e in state['events']:
                e['groups']=[g for g in e['groups'] if g['market']=='winner' and g['period']=='full_game']
                e['funded_pairs']=[pair_compact(p) for p in e.get('funded_pairs',[])]
                for g in e['groups']:
                    for o in g['outcomes']:
                        for q in quotes_of(o):
                            q['calculations']={'funded_estimate':compact(q['calculations']['funded_estimate'])}
                            q.pop('comparison_input_refs',None);q.pop('comparison_input_status',None)
            state.pop('comparison_profiles',None)
            value['owner_policy']=load().to_dict();value['storage']=provider.database.status()
            return web.json_response(value)
        except ValueError as exc:return web.json_response(dict(error='saved_result_unavailable',reason=str(exc)),status=409)
        except Exception as exc:return web.json_response(dict(error='database_unavailable',reason=type(exc).__name__,storage=provider.database.status()),status=503)
    app.router.add_get('/api/stored/games',catalog)
    app.router.add_get('/api/stored/result',result)
