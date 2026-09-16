"""Routes for the existing board's multi-game landing page and drilldown."""
import json
from decimal import Decimal
from aiohttp import web
from app.dashboard.opportunity_board import ROOT,load_sessions,present
from app.dashboard.multi_game import MultiOwner,OUTPUT,configuration,saved_rows,project_game,default_point,game_calculation,rank_filter
from app.opportunities.board import SIDES,TEAMS,CANDIDATES
from app.collection.transport_session import reopen


def create_app(output=OUTPUT,owner=None,sessions=None):
    owner=owner or MultiOwner(output,spec_factory=configuration,personal_beta=True)
    legacy=load_sessions() if sessions is None else sessions
    def datasets():
        values={}
        for sid,(p,rows) in legacy.items():
            spec=rows[0]['spec'];src=spec['sources']
            game=dict(id=src['kalshi']['event_id']+'__'+src['polymarket_us']['event_id'],title=p['event'],scheduled_start=p['kickoff'],teams=list(TEAMS),sides={k:dict(v,**({'native_label':'Long' if k.endswith('1315440') else 'Short'} if k.startswith('polymarket') else {})) for k,v in SIDES.items()},sources=src,candidates=CANDIDATES)
            values[sid]=dict(rows=rows,games=[game],coverage=dict(selected=1,found={},common=1,excluded=[],truncated_by_limit=0),live=False,label='Saved · '+p['capture_start']+' · 1 game · Completed')
        for sid in owner.saved():
            saved=saved_rows(owner.output/sid)
            select=next(r for r in saved['rows'] if r['type']=='multi_game_selection')
            values[sid]=dict(rows=saved['rows'],games=select['games'],coverage=select['coverage'],live=False,label=('Local test' if saved['rows'][0]['spec']['mode']=='mock' else 'Saved')+' · '+saved['rows'][0]['observed_at']+' · '+str(len(select['games']))+' games · Completed')
        s=owner.session
        if owner.active() and s and s.journal:
            saved=reopen(s.journal.path);select=next((r for r in saved['rows'] if r['type']=='multi_game_selection'),None)
            if select:values[s.sid]=dict(rows=saved['rows'],games=select['games'],coverage=select['coverage'],live=True,label='Current multi-game scan')
        return values
    @web.middleware
    async def guard(request,handler):
        if request.host not in ('127.0.0.1:'+str(request.url.port),'localhost:'+str(request.url.port)):raise web.HTTPForbidden()
        if request.method=='POST' and request.headers.get('Origin')!='http://'+request.host:raise web.HTTPForbidden()
        try:r=await handler(request)
        except (ValueError,KeyError,ArithmeticError) as exc:return web.json_response({'error':str(exc)},status=422)
        r.headers.update({'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
        return r
    app=web.Application(middlewares=[guard]);app['owner']=owner
    async def state(req):return web.json_response(owner.status())
    async def start(req):
        options=await req.json()
        if not isinstance(options,dict) or set(options)-{'max_games','duration'}:raise ValueError('Unknown scan controls')
        return web.json_response(dict(session=await owner.start(**options)))
    async def stop(req):await owner.stop();return web.json_response(owner.status())
    async def catalog(req):
        items=[]
        for sid,d in datasets().items():
            for g in d['games']:
                timeline,_=project_game(d['rows'],g)
                point=default_point(timeline)
                items.append(dict(id=sid+'~'+g['id'],hash=sid,label=g['title']+' · '+d['label'],game=g,data_mode=d['rows'][0]['spec']['mode'],default_cutoff=timeline.index(point),timeline=[dict(id=p['id'],at=p['at'],label=p['label']) for p in timeline]))
        return web.json_response(items)
    async def calculation(req):
        q=req.query;sid,gid=q['session'].split('~',1);d=datasets()[sid];g=next(g for g in d['games'] if g['id']==gid)
        if q['hash']!=sid:raise ValueError('session identity mismatch')
        timeline,rows=project_game(d['rows'],g);point=next(p for p in timeline if p['id']==q['cutoff'])
        r=present(game_calculation(point,rows,g,q.get('quantity','100'),q.get('scenario','cent'),q.get('probability') or None,q.get('contract')))
        r.update(session=q['session'],hash=sid,live=False)
        return web.json_response(r)
    async def dashboard(req):
        q=req.query;ds=datasets();sid=q.get('capture') or (list(ds)[-1] if ds else None)
        result=dict(status=owner.status(),captures=[dict(id=s,label=d['label']) for s,d in ds.items()],capture=sid,rows=[],coverage=None)
        if not sid:return web.json_response(result)
        d=ds[sid];result.update(coverage=d['coverage'],live=d['live'],last_update=d['rows'][-1]['observed_at'],capture_time=d['rows'][0]['observed_at'],data_mode=d['rows'][0]['spec']['mode'])
        assumptions=json.loads(q.get('assumptions','{}'));view=q.get('view','arb');items=[]
        for g in d['games']:
            timeline,rows=project_game(d['rows'],g,d['live']);point=timeline[-1] if d['live'] else default_point(timeline)
            # Drilldown freezes an actual retained cutoff, never the moving current projection.
            retained=timeline[-2] if d['live'] else point
            r=game_calculation(point,rows,g,q.get('quantity','100'),q.get('scenario','cent'))
            common=dict(game_id=g['id'],game_title=g['title'],start=g['scheduled_start'],session=sid+'~'+g['id'],hash=sid,cutoff=retained['id'],at=point['at'],historical=not d['live'])
            if view=='arb':
                for c in r['candidates']:
                    venues=sorted({l['venue'] for l in c['legs']})
                    items.append(dict({**common,**c},id=g['id']+'~'+c['id'],candidate=c['id'],venues=venues,venue_pair='+'.join(venues),assumption='Normal winner settlement · '+q.get('scenario','cent')+' fee scenario · exceptional outcomes unknown'))
            else:
                for key in g['sides']:
                    assumption=assumptions.get(g['id']+'~'+key,{})
                    p=assumption.get('probability');basis=assumption.get('basis','').strip()
                    if p is not None and not basis:raise ValueError('Probability needs an explicit source or basis')
                    ev=game_calculation(point,rows,g,q.get('quantity','100'),q.get('scenario','cent'),p,key)['ev'];leg=ev['leg'];v=leg['venue']
                    items.append(dict(**common,id=g['id']+'~'+key,candidate='',contract=key,legs=[leg],status=ev['status'],profit=ev['expected_profit'],return_pct=ev['return_pct'],break_even_pct=ev['break_even_pct'],probability=ev['probability'],assumption=basis or 'Assumption needed',venues=[v],venue_pair=v,usable=ev['usable'],modeled_quantity=ev['modeled_quantity'],depth_limited=ev['depth_limited'],raw_gap=None))
        result['rows']=rank_filter(items,q.get('sort','roi'),q.get('positive')=='true',q.get('venue',''),q.get('freshness',''),q.get('search',''))
        result['total_candidates']=len(items)
        return web.json_response(result)
    async def page(req):return web.FileResponse(ROOT/'app/dashboard/opportunity_static/dashboard.html')
    async def game(req):return web.FileResponse(ROOT/'app/dashboard/opportunity_static/index.html')
    async def style(req):return web.FileResponse(ROOT/'app/dashboard/static/style.css')
    async def shared(req):return web.FileResponse(ROOT/'app/dashboard/e5_static/state.js')
    app.add_routes([web.get('/',page),web.get('/game',game),web.get('/style.css',style),web.get('/shared-state.js',shared),web.get('/api/status',state),web.post('/api/start',start),web.post('/api/stop',stop),web.get('/api/dashboard',dashboard),web.get('/api/sessions',catalog),web.get('/api/calculate',calculation)])
    app.router.add_static('/view/',ROOT/'app/dashboard/opportunity_static')
    async def cleanup(app):await owner.close()
    app.on_cleanup.append(cleanup)
    return app
