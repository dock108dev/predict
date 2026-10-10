"""Loopback synthetic Start/Stop and saved-reopen surface with an isolated owner."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import signal
from aiohttp import web
from app.collection.environment import Environment
from app.collection.session import Session,checked
from app.collection.storage import Repository
from app.collection.synthetic import WallClock
from app.reference.fixtures import before
from app.collection.reopen import reopen
from app.dashboard.local_security import HEADERS, check_browser, read_json, PublicRequestError
from app.dashboard.query_policy import validate_unique_query
from app.diagnostics import failure

ROOT=Path(__file__).resolve().parents[2]
BODY_LIMIT=2048


def create_app(env,output):
    app=web.Application(client_max_size=BODY_LIMIT,handler_args={'auto_decompress':False})
    import fcntl
    owner_lock=(env.root/'owner.lock').open('a')
    fcntl.flock(owner_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    app['owner_lock']=owner_lock
    app['env']=env;app['output']=Path(output);app['output'].mkdir(parents=True,exist_ok=True)
    app['session']=None;app['lock']=asyncio.Lock();app['reader']=ThreadPoolExecutor(1,thread_name_prefix='e6-saved-reader');app['reading']=False;app['active_requests']=0
    origin=datetime.fromisoformat(before(7200))+timedelta(seconds=max(0,datetime.now().timestamp()-(env.root/'e6-environment.json').stat().st_mtime))
    app['clock']=WallClock(origin.isoformat())
    with env.connect() as db:
        app['recovered']=Repository(db,output,checked({})).recover()
    async def page(request):return web.FileResponse(ROOT/'app/collection/static/index.html')
    async def asset(request):return web.FileResponse(ROOT/'app/collection/static/watch.js')
    async def css(request):return web.FileResponse(ROOT/'app/dashboard/static/style.css')
    async def local_css(request):return web.FileResponse(ROOT/'app/collection/static/watch.css')
    async def status(request):
        s=app['session'];result=s.status() if s else dict(state='idle',synthetic=True,recovered=app['recovered'])
        result['saved']=[p.parent.name for p in app['output'].glob('*/manifest.json')][:8]
        # UI receives the latest compact projection, never the expanding dependency bundle.
        if result.get('view'):result['view']=project(result['view'])
        result['books']=[] if not s else [dict(venue=k,ask=b['levels'][0][0],at=b['known_at']) for k,b in s.books.items()]
        return web.json_response(result)
    async def start(request):
        async with app['lock']:
            previous=app['session']
            if previous and previous.task and not previous.task.done():raise web.HTTPConflict(text='session is running or stopping')
            with env.connect() as check_db:
                count=check_db.execute('SELECT count(*) AS n FROM capture_session WHERE provenance=%s',('E6 bounded injected synthetic collection',)).fetchone()['n']
            if count>=8:raise web.HTTPConflict(text='eight-session environment limit; retain evidence and use fresh environment')
            body=await read_json(request,max_size=BODY_LIMIT);limits=checked(body)
            if previous:previous.repo.db.close()
            repo=Repository(env.connect(),output,limits)
            s=Session(repo,app['clock'],output,limits);app['session']=s
            try:await s.start()
            except Exception:
                repo.db.close();s.dbworker.shutdown();s.calcworker.shutdown();raise
            return web.json_response(dict(id=s.sid,state=s.state))
    async def stop(request):
        if await read_json(request,max_size=BODY_LIMIT)!={}:raise web.HTTPUnprocessableEntity(reason='Stop accepts an empty object')
        s=app['session']
        if s:await s.stop()
        return await status(request)
    async def saved(request):
        sid=request.match_info['sid']
        if len(sid)!=36 or any(c not in 'abcdef0123456789-' for c in sid):raise web.HTTPBadRequest()
        if app['reading']:raise web.HTTPConflict(text='saved replay already in progress')
        app['reading']=True
        try:
            result=await asyncio.get_running_loop().run_in_executor(app['reader'],reopen,app['output']/sid)
            result['snapshots']=[project(x) for x in result['snapshots']]
            return web.json_response(result)
        finally:app['reading']=False
    @web.middleware
    async def guard(request,handler):
        try:
            check_browser(request)
            validate_unique_query(request.query)
            if request.method=='POST' and (request.content_length or 0)>BODY_LIMIT:
                raise web.HTTPRequestEntityTooLarge(max_size=BODY_LIMIT,actual_size=request.content_length)
            if app['active_requests']>=8:raise web.HTTPServiceUnavailable(reason='bounded request capacity')
            app['active_requests']+=1
            try:response=await handler(request)
            finally:app['active_requests']-=1
        except web.HTTPException as exc:
            response=web.json_response({'error':exc.reason},status=exc.status)
            if exc.status==408:response.force_close()
            if 'Allow' in exc.headers:response.headers['Allow']=exc.headers['Allow']
        except PublicRequestError as exc:
            response=web.json_response({'error':str(exc)},status=422)
        except (ValueError,FileNotFoundError) as exc:
            failure(__name__,'synthetic_collection_request',exc)
            response=web.json_response({'error':'Invalid input or unavailable synthetic data'},status=422)
        except Exception as exc:
            failure(__name__,'synthetic_collection_request',exc)
            response=web.json_response({'error':'Synthetic data unavailable'},status=503)
        response.headers.update(HEADERS)
        return response
    app.middlewares.append(guard)
    app.add_routes([web.get('/',page),web.get('/watch.js',asset),web.get('/style.css',css),web.get('/watch.css',local_css),web.get('/api/status',status),
                    web.post('/api/start',start),web.post('/api/stop',stop),web.get('/api/saved/{sid}',saved)])
    async def cleanup(app):
        if app['session']:
            await app['session'].stop();app['session'].repo.db.close()
        app['reader'].shutdown(wait=True)
        app['owner_lock'].close()
    app.on_cleanup.append(cleanup)
    return app


def project(snapshot):
    from copy import deepcopy
    e=snapshot['estimate'];a=snapshot['audit'];context=snapshot.get('session_context')
    eligible=context is not None and context['eligible']
    receipts={r['data']['id']:r['data']['received_at'] for r in json.loads(e['dependencies'])['payload']['records'] if r['type']=='Receipt'}
    references=sorted([dict(receipt=c['receipt_id'],at=receipts[c['receipt_id']],odds=c['original_odds'],provider_read=c['provider_last_read'],included=c['included'],reasons=c['reasons']) for c in e['candidates']],key=lambda r:(r['at'],r['receipt']))
    signals=[] if not a else deepcopy(a['signals'])
    if not eligible:
        for row in signals:
            row['engine_diagnostic_net_total_usd']=row['net_total_usd']
            for key in ('net_total_usd','net_per_contract_usd','return_fraction'):row[key]=None
            row['status']='unavailable';row['reasons']=[*row['reasons'],'session_health_unavailable_or_unrecorded']
    return dict(references=references,books=[] if not a else [dict(venue=b['observation']['quote']['raw']['ref']['venue'],ask=b['levels'][0][0],at=b['known_at']) for b in a['inputs']['market']['books']],cutoff=snapshot['cutoff'],session_context=context,probability=e['conditional_target_probability'] if eligible else None,status=e['status'] if eligible else 'unavailable',
                reasons=e['reasons'],signals=signals,estimate_id=None if not a else a['estimate_id'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--environment',required=True);p.add_argument('--output',required=True);p.add_argument('--port',type=int,default=8786);args=p.parse_args()
    web.run_app(create_app(Environment(args.environment),args.output),host='127.0.0.1',port=args.port,print=None)
if __name__=='__main__':main()
