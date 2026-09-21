"""Routes for the existing board's multi-game landing page and drilldown."""
import json
from app.diagnostics import failure
from aiohttp import web
from app.dashboard.local_security import HEADERS,check_browser,calculation_inputs,validate_assumptions
from app.dashboard.opportunity_board import ROOT,load_sessions,present
from app.dashboard.multi_game import MultiOwner,OUTPUT,configuration,saved_rows,project_game,default_point,game_calculation,rank_filter
from app.opportunities.board import SIDES,TEAMS,CANDIDATES
from app.collection.transport_session import reopen
from app.reference.page_estimate import for_saved_game
from app.reference.multi_page import research_row, rank_research


def create_app(output=OUTPUT,owner=None,sessions=None):
    if owner is None:
        from app.dashboard.coverage_owner import CoverageOwner
        owner=CoverageOwner(output,spec_factory=configuration)
    retained_sessions=load_sessions() if sessions is None else sessions
    def datasets():
        values={}
        for sid,(p,rows) in retained_sessions.items():
            spec=rows[0]['spec'];src=spec['sources']
            game=dict(id=src['kalshi']['event_id']+'__'+src['polymarket_us']['event_id'],title=p['event'],scheduled_start=p['kickoff'],teams=list(TEAMS),sides={k:dict(v,**({'native_label':'Long' if k.endswith('1315440') else 'Short'} if k.startswith('polymarket') else {})) for k,v in SIDES.items()},sources=src,candidates=CANDIDATES)
            values[sid]=dict(rows=rows,games=[game],coverage=dict(selected=1,found={},common=1,excluded=[],truncated_by_limit=0),live=False,label='Saved · '+p['capture_start']+' · 1 game · Completed')
        for sid in owner.saved():
            saved=saved_rows(owner.output/sid)
            select=next(r for r in saved['rows'] if r['type']=='multi_game_selection')
            values[sid]=dict(rows=saved['rows'],games=select['games'],coverage=select['coverage'],live=False,label=('Local test' if saved['rows'][0]['spec']['mode']=='mock' else 'Saved')+' · '+saved['rows'][0]['observed_at']+' · '+str(len(select['games']))+' games · Completed')
        s=owner.session
        if owner.active() and s and s.journal and not hasattr(s,'status_coverage'):
            saved=reopen(s.journal.path);select=next((r for r in saved['rows'] if r['type']=='multi_game_selection'),None)
            if select:values[s.sid]=dict(rows=saved['rows'],games=select['games'],coverage=select['coverage'],live=True,label='Current multi-game scan')
        return values
    @web.middleware
    async def guard(request,handler):
        try:
            check_browser(request)
            if request.path in ('/api/dashboard','/api/calculate'):
                q=request.query
                calculation_inputs(q)
                if any(len(q.getall(k))!=1 for k in q):raise ValueError('Duplicate selection')
                choices={'view':('arb','ev','research'),'sort':('roi','dollars'),
                         'scenario':('cent','direct','unknown'),
                         'freshness':('','usable','unavailable'),'positive':('true','false')}
                for key,values in choices.items():
                    if key in q and q[key] not in values:raise ValueError('Unknown '+key+' selection')
            r=await handler(request)
        except web.HTTPException as exc:
            r=web.json_response({'error':exc.reason},status=exc.status)
            if 'Allow' in exc.headers:r.headers['Allow']=exc.headers['Allow']
        except (ValueError,ArithmeticError) as exc:
            r=web.json_response({'error':str(exc)},status=422)
        except (KeyError,StopIteration):
            r=web.json_response({'error':'Unknown selection'},status=422)
        except Exception as exc:
            failure(__name__, 'dashboard_request', exc)
            r=web.json_response({'error':'Local data unavailable'},status=503)
        r.headers.update(HEADERS)
        return r
    app=web.Application(middlewares=[guard],client_max_size=4096);app['owner']=owner
    async def state(req):return web.json_response(owner.status())
    async def coverage_page(req):return web.FileResponse(ROOT/'app/dashboard/opportunity_static/coverage.html')
    app.router.add_get('/coverage',coverage_page)
    async def start(req):
        options=await req.json()
        if not isinstance(options,dict) or set(options)-{'max_games','duration'}:raise ValueError('Unknown scan controls')
        return web.json_response(dict(session=await owner.start(**options)))
    async def stop(req):
        if await req.json()!={}:raise ValueError('Stop does not accept options')
        await owner.stop()
        return web.json_response(owner.status())
    async def catalog(req):
        items=[]
        for sid,d in datasets().items():
            for g in d['games']:
                timeline,_=project_game(d['rows'],g)
                point=default_point(timeline)
                items.append(dict(id=sid+'~'+g['id'],hash=sid,label=g['title']+' · '+d['label'],game=g,data_mode=d['rows'][0]['spec']['mode'],default_cutoff=timeline.index(point),timeline=[dict(id=p['id'],at=p['at'],label=p['label']) for p in timeline]))
        return web.json_response(items)
    async def calculation(req):
        q=req.query;sid,gid=q['session'].split('~',1);d=datasets()[sid];g=next((g for g in d['games'] if g['id']==gid),None)
        if g is None:raise ValueError('Unknown game')
        if q['hash']!=sid:raise ValueError('session identity mismatch')
        timeline,rows=project_game(d['rows'],g);point=next((p for p in timeline if p['id']==q['cutoff']),None)
        if point is None:raise ValueError('Unknown cutoff')
        r=present(game_calculation(point,rows,g,q.get('quantity','100'),q.get('scenario','cent'),q.get('probability') or None,q.get('contract')))
        r.update(session=q['session'],hash=sid,live=False)
        r['page_estimate']=for_saved_game(sid,g,q.get('quantity','100'),q.get('scenario','cent'),live=d['live'])
        return web.json_response(r)
    async def dashboard(req):
        q=req.query
        assumptions=validate_assumptions(json.loads(q.get('assumptions','{}')))
        ds=datasets();sid=q.get('capture') or (list(ds)[-1] if ds else None)
        result=dict(status=owner.status(),captures=[dict(id=s,label=d['label']) for s,d in ds.items()],capture=sid,rows=[],coverage=None)
        if not sid:return web.json_response(result)
        d=ds[sid];result.update(coverage=d['coverage'],live=d['live'],last_update=d['rows'][-1]['observed_at'],capture_time=d['rows'][0]['observed_at'],data_mode=d['rows'][0]['spec']['mode'])
        view=q.get('view','arb');items=[]
        for g in d['games']:
            timeline,rows=project_game(d['rows'],g,d['live']);point=timeline[-1] if d['live'] else default_point(timeline)
            # Drilldown freezes an actual retained cutoff, never the moving current projection.
            retained=timeline[-2] if d['live'] else point
            r=game_calculation(point,rows,g,q.get('quantity','100'),q.get('scenario','cent'))
            common=dict(game_id=g['id'],game_title=g['title'],start=g['scheduled_start'],session=sid+'~'+g['id'],hash=sid,cutoff=retained['id'],at=point['at'],historical=not d['live'])
            if view=='research':
                items.append(research_row(sid,g,q.get('quantity','100'),q.get('scenario','cent'),common,live=d['live']))
            elif view=='arb':
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
        result['rows']=rank_research(items,q.get('sort','roi'),q.get('search','')) if view=='research' else rank_filter(items,q.get('sort','roi'),q.get('positive')=='true',q.get('venue',''),q.get('freshness',''),q.get('search',''))
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
