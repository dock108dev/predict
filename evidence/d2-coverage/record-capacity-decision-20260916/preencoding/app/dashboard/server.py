"""Fixed loopback API, same-origin scan controls and allowlisted public projections."""
import asyncio,json,secrets,re
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from aiohttp import web
from app.dashboard.controller import Controller
from app.dashboard import repository
from app.dashboard.views import age_view

ORIGIN='http://127.0.0.1:8765'
STATIC=Path(__file__).parent/'static'

def response(data,status=200):
    return web.Response(text=json.dumps(data,default=lambda v:v.isoformat() if isinstance(v,datetime) else str(v) if isinstance(v,Decimal) else None,allow_nan=False),status=status,content_type='application/json')

def identifier(s):
    if not re.fullmatch(r'[A-Za-z0-9:_-]{1,100}',s):raise web.HTTPBadRequest(text='Invalid identifier')
    return s


def create_app(controller=None):
    ctl=controller or Controller();token=secrets.token_urlsafe(32)
    @web.middleware
    async def guard(request,handler):
        if request.headers.get('Host')!='127.0.0.1:8765':return response({'error':'Use the local dashboard address'},403)
        if request.headers.get('Sec-Fetch-Site')=='cross-site':return response({'error':'Cross-origin request denied'},403)
        if request.method=='POST':
            if request.headers.get('Origin')!=ORIGIN or not secrets.compare_digest(request.headers.get('X-Scan-Token',''),token) or request.content_type!='application/json':
                return response({'error':'Scan control request denied'},403)
        try:r=await handler(request)
        except (LookupError,ValueError):r=response({'error':'Invalid request or unavailable saved data. Check your selection and scan settings.'},400)
        except RuntimeError:r=response({'error':'A scan or calculation is already active. Stop it before starting another.'},409)
        except web.HTTPException:raise
        except Exception:r=response({'error':'Local data is unavailable. Check the project database; scan controls remain safe.'},503)
        r.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        r.headers['Cache-Control']='no-store';r.headers['X-Content-Type-Options']='nosniff'
        return r
    app=web.Application(middlewares=[guard],client_max_size=4096);app['controller']=ctl
    async def index(req):return web.FileResponse(STATIC/'index.html')
    async def asset(req):
        name=req.match_info['name']
        if name not in ('app.js','style.css'):raise web.HTTPNotFound()
        return web.FileResponse(STATIC/name)
    async def state(req):
        active=ctl.state=='scanning'
        return response(dict(state=ctl.state,mode=ctl.mode,sid=ctl.sid,limits=ctl.limits,started_at=ctl.started_at,error=ctl.error,
            csrf=token,venues=ctl.status,messages=ctl.messages,queue=ctl.queue.qsize(),depth_busy=ctl.depth_busy,
            view=age_view(ctl.view,active=active,health=ctl.status)))
    async def start(req):
        data=await req.json()
        if not isinstance(data,dict) or set(data)-{'mode','limits'} or not isinstance(data.get('limits',{}),dict):raise ValueError('Invalid scan settings')
        return response(await ctl.start(data.get('mode','live'),data.get('limits',{})),202)
    async def stop(req):
        data=await req.json()
        if data!={}:raise ValueError('Stop does not accept options')
        ctl.request_stop('Stopped by owner');return response({'state':ctl.state},202)
    async def sessions(req):return response(await asyncio.to_thread(repository.list_sessions))
    async def session(req):
        v=await asyncio.to_thread(repository.saved_view,identifier(req.match_info['sid']))
        return response(age_view(v,active=False))
    async def hist(req):return response(await asyncio.to_thread(repository.history,identifier(req.match_info['sid']),identifier(req.match_info['cid'])))
    async def depth(req):
        data=await req.json()
        if set(data)!={'candidate'}:raise ValueError('Select one candidate')
        return response(await ctl.depth(identifier(data['candidate'])))
    async def saved_depth(req):return response(await asyncio.to_thread(repository.saved_depth,identifier(req.match_info['sid']),identifier(req.match_info['cid'])))
    app.router.add_get('/',index);app.router.add_get('/assets/{name}',asset);app.router.add_get('/api/state',state)
    app.router.add_post('/api/start',start);app.router.add_post('/api/stop',stop);app.router.add_post('/api/depth',depth)
    app.router.add_get('/api/sessions',sessions);app.router.add_get('/api/sessions/{sid}',session)
    app.router.add_get('/api/sessions/{sid}/history/{cid}',hist);app.router.add_get('/api/sessions/{sid}/depth/{cid}',saved_depth)
    async def cleanup(app):await ctl.close()
    app.on_cleanup.append(cleanup)
    return app
