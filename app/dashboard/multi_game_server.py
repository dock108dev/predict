"""Routes for the existing board's multi-game landing page and drilldown."""
import json
import asyncio
from datetime import datetime, timezone
from app.diagnostics import failure
from aiohttp import web
from app.dashboard.local_security import HEADERS,check_browser,read_json,body_limit,IMPORT_BODY_LIMIT
from app.dashboard.query_policy import validate_http_query,validate_assumptions
from app.dashboard.opportunity_board import ROOT,load_sessions,present
from app.dashboard.multi_game import OUTPUT,configuration,saved_rows,project_game,default_point,game_calculation,rank_filter
from app.opportunities.board import SIDES,TEAMS,CANDIDATES
from app.collection.transport_session import reopen
from app.reference.page_estimate import for_saved_game
from app.reference.multi_page import research_row, rank_research

OWNER_KEY = web.AppKey('owner', object)
MAX_UPDATE_CLIENTS = 8


def create_app(output=OUTPUT,owner=None,sessions=None):
    if owner is None:
        from app.dashboard.coverage_owner import CoverageOwner
        owner=CoverageOwner(output,spec_factory=configuration,product_mode=True,pilot_output=ROOT/'evidence/product-sessions')
    retained_sessions=load_sessions() if sessions is None else sessions
    from app.dashboard.saved_snapshot_cache import SavedSnapshotCache
    saved_cache=SavedSnapshotCache()
    def datasets(selected=None, catalog_all=True):
        values={}
        for sid,(p,rows) in retained_sessions.items():
            spec=rows[0]['spec'];src=spec['sources']
            game=dict(id=src['kalshi']['event_id']+'__'+src['polymarket_us']['event_id'],title=p['event'],scheduled_start=p['kickoff'],teams=list(TEAMS),sides={k:dict(v,**({'native_label':'Long' if k.endswith('1315440') else 'Short'} if k.startswith('polymarket') else {})) for k,v in SIDES.items()},sources=src,candidates=CANDIDATES)
            values[sid]=dict(rows=rows,games=[game],coverage=dict(selected=1,found={},common=1,excluded=[],truncated_by_limit=0),live=False,label='Saved · '+p['capture_start']+' · 1 game · Completed')
        for sid in owner.saved():
            try:
                saved=saved_rows(owner.output/sid)
                select=next(r for r in saved['rows'] if r['type']=='multi_game_selection')
                values[sid]=dict(rows=saved['rows'],games=select['games'],coverage=select['coverage'],live=False,label=('Local test' if saved['rows'][0]['spec']['mode']=='mock' else 'Saved')+' · '+saved['rows'][0]['observed_at']+' · '+str(len(select['games']))+' games · Completed')
            except (ValueError,OSError,KeyError,StopIteration) as exc:
                failure(__name__, 'saved_package_read', exc)
                values[sid]=dict(games=[],error='Incomplete saved package; inspect the local log',label='Incomplete · '+sid)
        from app.dashboard import session_history
        if hasattr(owner,'history_paths'):
            paths=owner.history_paths()
            if not catalog_all and not selected:
                selected=owner.session.sid if owner.active() and owner.session else next(reversed(paths),None)
            for sid,folder in paths.items():
                if sid in values or (owner.active() and owner.session and sid==owner.session.sid):continue
                if not catalog_all and sid!=selected:
                    values[sid]=dict(games=[],folder=folder,label='Saved · '+sid+' · select to verify')
                    continue
                try:
                    snapshot=saved_cache.load(folder,session_history.load)
                    values[sid]=dict(product=snapshot,folder=folder,games=snapshot['games'],label=snapshot['data_mode']+' · '+snapshot['state']+' · '+str(snapshot['started_at']))
                except (ValueError,OSError,KeyError) as exc:
                    failure(__name__, 'saved_history_read', exc)
                    values[sid]=dict(games=[],error='Incomplete or corrupt saved package; inspect the local log',label='Incomplete · '+sid)
        if hasattr(owner,'current_snapshot') and owner.session and owner.active():
            snapshot=owner.current_snapshot()
            if snapshot:values[owner.session.sid]=dict(product=snapshot,folder=owner.session.output,games=snapshot['games'],label=snapshot['data_mode']+' · '+snapshot['state'])
        s=owner.session
        if owner.active() and s and s.journal and not hasattr(s,'projection'):
            saved=reopen(s.journal.path);select=next((r for r in saved['rows'] if r['type']=='multi_game_selection'),None)
            if select:values[s.sid]=dict(rows=saved['rows'],games=select['games'],coverage=select['coverage'],live=True,label='Current multi-game scan')
        return values
    def product_cutoff(sid,d,cutoff):
        from app.dashboard import session_history
        if owner.active() and owner.session and sid==owner.session.sid:
            if owner.session.persistence_error:raise ValueError('Persistence failed')
            snapshot=owner.cutoffs.get(cutoff)
            if snapshot is None and not owner.session.segmented_history:
                snapshot=session_history.project_rows(reopen(owner.session.journal.path)['rows'][:owner.session.journal.count],cutoff)
            if snapshot is None:raise ValueError('Older segmented cutoff available after Stop')
            return snapshot
        return session_history.load(d['folder'],cutoff)
    @web.middleware
    async def guard(request,handler):
        try:
            check_browser(request)
            limit=body_limit(request.path)
            if request.method=='POST' and (request.content_length or 0)>limit:
                raise web.HTTPRequestEntityTooLarge(max_size=limit,actual_size=request.content_length)
            if request.path in ('/api/dashboard','/api/calculate','/api/sessions','/api/resolution'):
                validate_http_query(request.query)
            r=await handler(request)
        except web.HTTPException as exc:
            r=web.json_response({'error':exc.reason},status=exc.status)
            for header in ('Allow','Retry-After'):
                if header in exc.headers:r.headers[header]=exc.headers[header]
        except (ValueError,ArithmeticError) as exc:
            r=web.json_response({'error':str(exc)},status=422)
        except (KeyError,StopIteration):
            r=web.json_response({'error':'Unknown selection'},status=422)
        except Exception as exc:
            failure(__name__, 'dashboard_request', exc)
            r=web.json_response({'error':'Local data unavailable'},status=503)
        r.headers.update(HEADERS)
        return r
    app=web.Application(middlewares=[guard],client_max_size=IMPORT_BODY_LIMIT,handler_args={'auto_decompress':False});app[OWNER_KEY]=owner
    async def state(req):return web.json_response(owner.status())
    async def coverage_page(req):return web.FileResponse(ROOT/'app/dashboard/opportunity_static/coverage.html')
    app.router.add_get('/coverage',coverage_page)
    async def start(req):
        options=await read_json(req)
        if not isinstance(options,dict) or set(options)-owner.start_controls:raise ValueError('Unknown scan controls')
        return web.json_response(dict(session=await owner.start(**options)))
    async def stop(req):
        if await read_json(req)!={}:raise ValueError('Stop does not accept options')
        await owner.stop()
        return web.json_response(owner.status())
    async def import_references(req):
        if owner.spec_factory().get('two_source_qualification'):raise ValueError('Reference imports excluded from this frozen prediction-only attempt')
        from app.reference.product import emit_references
        if not owner.active() or not getattr(owner.session,'projection',None):raise ValueError('Start a product session before importing retained references')
        refs=await read_json(req)
        emit_references(owner.session,refs)
        await owner.session.queue.join()
        return web.json_response(dict(imported=len(refs),session=owner.session.sid))
    async def import_resolutions(req):
        if owner.spec_factory().get('two_source_qualification'):raise ValueError('Result imports excluded from this frozen prediction-only attempt')
        from app.resolution.core import emit_records
        if not owner.active() or not getattr(owner.session,'projection',None):raise ValueError('Start a product session before importing retained resolution evidence')
        records=await read_json(req);emit_records(owner.session,records)
        await owner.session.queue.join()
        return web.json_response(dict(imported=len(records),session=owner.session.sid))
    async def resolution(req):
        from app.dashboard import session_history
        from app.resolution.core import resolve
        q=req.query
        sid,gid=q['session'].split('~',1);d=datasets(sid,catalog_all=False)[sid]
        if q['hash']!=sid or 'product' not in d:raise ValueError('Unbound prediction snapshot')
        snap=product_cutoff(sid,d,q['cutoff']);game=next(g for g in snap['games'] if g['id']==gid)
        if (game['product_identity'].get('competition'),game['product_identity'].get('season')) not in (('NFL','2026'),('NBA','2026-2027'),('NCAAF','2026'),('NCAAB','2026-2027'),('MLB','2026'),('NHL','2026-2027')):return web.json_response(dict(options=[],unsupported='Resolution mapping unavailable for this competition/season'))
        paths=owner.history_paths() if hasattr(owner,'history_paths') else {};options=[];unavailable=[]
        # Only completed saved sessions expose resolution history; ongoing imports
        # become reviewable after Stop, keeping acknowledged history authoritative.
        for rsid,folder in paths.items():
            if owner.active() and owner.session and rsid==owner.session.sid:continue
            try:hist=session_history.resolution_history(folder)
            except (ValueError,OSError,KeyError) as exc:
                failure(__name__, 'resolution_history_read', exc)
                unavailable.append(rsid);continue
            if hist['state']!='complete':continue
            for option in hist['options']:
                if any(t and t.get('session_id')==sid and t.get('game_id')==gid and t.get('prediction_cutoff')==q['cutoff'] for t in option['targets']):
                    options.append(dict(session=rsid,**{k:v for k,v in option.items() if k!='targets'}))
        result=dict(options=options,unavailable_sessions=unavailable,limitation='Choose a saved resolution cutoff. Original prediction calculations stay frozen.')
        requested=[q.get(k) for k in ('resolution_session','resolution_cutoff','resolution_asof')]
        if any(requested):
            if not all(requested):raise ValueError('Explicit resolution session, cutoff and as-of required')
            rsid,rcut,asof=requested
            if not any(o['session']==rsid and o['cutoff']==rcut for o in options):raise ValueError('Unknown bound resolution selection')
            hist=session_history.resolution_history(paths[rsid],rcut)
            result['view']=resolve(hist['records'],snap,game,asof,q)
            result['view'].update(resolution_session=rsid,resolution_cutoff=rcut)
        return web.json_response(result)
    async def catalog(req):
        items=[]
        for sid,d in datasets().items():
            if 'product' in d and req.query.get('session','').startswith(sid+'~') and req.query.get('cutoff'):
                snap=product_cutoff(sid,d,req.query['cutoff']);d=dict(d,product=snap,games=snap['games'])
            for g in d['games']:
                if 'product' in d:
                    p=d['product']['points'][g['id']]
                    items.append(dict(id=sid+'~'+g['id'],hash=sid,label=g['title']+' · '+d['label'],game=g,data_mode=d['product']['data_mode'],default_cutoff=0,timeline=[dict(id=p['id'],at=p['at'],label=p['label'])]))
                    continue
                timeline,_=project_game(d['rows'],g)
                point=default_point(timeline)
                items.append(dict(id=sid+'~'+g['id'],hash=sid,label=g['title']+' · '+d['label'],game=g,data_mode=d['rows'][0]['spec']['mode'],default_cutoff=timeline.index(point),timeline=[dict(id=p['id'],at=p['at'],label=p['label']) for p in timeline]))
        return web.json_response(items)
    async def calculation(req):
        q=req.query;sid,gid=q['session'].split('~',1);d=datasets(sid,catalog_all=False)[sid];g=next((g for g in d['games'] if g['id']==gid),None)
        if g is None and 'product' not in d:raise ValueError('Unknown game')
        if q['hash']!=sid:raise ValueError('session identity mismatch')
        if 'product' in d:
            from app.dashboard import session_history,product_view
            snapshot=product_cutoff(sid,d,q['cutoff'])
            g=next(g for g in snapshot['games'] if g['id']==gid)
            from app.dashboard.price_comparison import comparisons
            r=present(product_view.calculate(snapshot,g,q));r['comparisons']=[c for c in comparisons(snapshot,dict(quantity=q.get('quantity','100'))) if c['game_id']==gid or any(a['game_id']==gid for a in c.get('alternatives',[]))];r.update(session=q['session'],hash=sid,live=False,page_estimate=None)
            return web.json_response(r)
        timeline,rows=project_game(d['rows'],g);point=next((p for p in timeline if p['id']==q['cutoff']),None)
        if point is None:raise ValueError('Unknown cutoff')
        r=present(game_calculation(point,rows,g,q.get('quantity','100'),q.get('scenario','cent'),q.get('probability') or None,q.get('contract')))
        r.update(session=q['session'],hash=sid,live=False)
        r['page_estimate']=for_saved_game(sid,g,q.get('quantity','100'),q.get('scenario','cent'),live=d['live'])
        return web.json_response(r)
    def dashboard_payload(q, ds=None, reuse=None):
        if reuse is None:reuse={}
        validate_assumptions(json.loads(q.get('assumptions','{}')))
        ds=datasets(q.get('capture'),catalog_all=False) if ds is None else ds
        if q.get("view", "arb")=="feed":
            from app.dashboard.opportunity_feed import combine
            ev=dashboard_payload(dict(q,view="ev",sort="roi"),ds,reuse)
            arb=dashboard_payload(dict(q,view="arb",sort="roi",capture=ev["capture"] or ""),ds,reuse)
            ev["rows"]=combine(ev["rows"],arb["rows"])
            ev["total_candidates"]=len(ev["rows"])
            return ev
        assumptions=validate_assumptions(json.loads(q.get('assumptions','{}')))
        sid=q.get('capture') or (list(ds)[-1] if ds else None)
        result=dict(status=owner.status(),captures=[dict(id=s,label=d['label']) for s,d in ds.items()],capture=sid,rows=[],coverage=None)
        if not sid:return result
        d=ds[sid]
        if d.get('error'):
            result.update(state='incomplete',error=d['error']);return result
        if 'product' in d:
            from app.dashboard import product_view
            p=d['product'];items=product_view.dashboard(p,q,assumptions,reuse=reuse)
            from app.dashboard.price_comparison import comparisons
            result['comparisons']=comparisons(p,q) if q.get('view')=='ev' else []
            if q.get('view')=='ev':
                from app.dashboard.opportunity_feed import combine
                items=combine(items,[])
            result.update(fee_scenario_locked=bool(p.get('qualification_fee_policy')),rows=items,total_candidates=len(items),live=p['view_mode']=='current',state=p['state'],data_mode=p['data_mode'],capture_time=p['started_at'],last_update=p['last_update'],sources=p['sources'],references=p['references'],market_catalog=p['market_catalog'],durable_cursor=p['durable_cursor'],coverage=dict(selected=len(p['games']),excluded=[m for m in p['market_catalog'] if m.get('reason')],truncated_by_limit=p['comparison_groups_beyond_limit'],sources=p['sources'],generation=p['generation'],refresh=p['refresh']))
            return result
        result.update(coverage=d['coverage'],live=d['live'],last_update=d['rows'][-1]['observed_at'],capture_time=d['rows'][0]['observed_at'],data_mode=d['rows'][0]['spec']['mode'])
        view=q.get('view','arb');items=[]
        for g in d['games']:
            identity=g.get('product_identity',dict(competition='NFL',season='2026',family='moneyline',period='full_game'))
            if any(q.get(k) and identity.get(k)!=q[k] for k in ('competition','season','family','period')):continue
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
                    ev=game_calculation(point,rows,g,q.get('quantity','100'),q.get('scenario','cent'),p,key)['ev'];leg=ev['leg'];v=leg['venue']
                    items.append(dict(**common,id=g['id']+'~'+key,candidate='',contract=key,legs=[leg],status=ev['status'],profit=ev['expected_profit'],return_pct=ev['return_pct'],break_even_pct=ev['break_even_pct'],probability=ev['probability'],assumption=basis or 'Assumption needed',venues=[v],venue_pair=v,usable=ev['usable'],modeled_quantity=ev['modeled_quantity'],depth_limited=ev['depth_limited'],raw_gap=None))
        result['rows']=rank_research(items,q.get('sort','roi'),q.get('search','')) if view=='research' else rank_filter(items,q.get('sort','roi'),q.get('positive')=='true',q.get('venue',''),q.get('freshness',''),q.get('search',''))
        if view=='ev':
            from app.dashboard.opportunity_feed import combine
            result['rows']=combine(result['rows'],[])
        result['total_candidates']=len(items)
        return result
    async def dashboard(req):
        started=datetime.now(timezone.utc).isoformat()
        tick=asyncio.get_running_loop().time()
        payload=dashboard_payload(req.query)
        payload['calculated_at']=datetime.now(timezone.utc).isoformat()
        if payload.get('live'):
            timings=getattr(owner.session,'local_book_timings',{})
            payload['book_pipeline']={l['book_id']:timings[l['book_id']] for c in payload.get('comparisons',[]) for l in c['legs'] if l.get('book_id') in timings}
        payload['request_started_at']=started
        payload['calculation_duration_ms']=(asyncio.get_running_loop().time()-tick)*1000
        payload['publication_prepared_at']=datetime.now(timezone.utc).isoformat()
        return web.json_response(payload)
    update_clients=set()
    async def updates(req):
        # HEAD must not write event bytes or allocate a long-lived subscription.
        headers={'Content-Type':'text/event-stream',**HEADERS}
        if req.method=='HEAD':return web.Response(headers=headers)
        if len(update_clients)>=MAX_UPDATE_CLIENTS:
            raise web.HTTPTooManyRequests(headers={'Retry-After':'1'})
        token=object();update_clients.add(token)
        response=web.StreamResponse(headers=headers)
        previous=None;last_sent=0;loop=asyncio.get_running_loop()
        try:
            await response.prepare(req)
            while req.transport is not None and not req.transport.is_closing():
                session=owner.session
                projection=getattr(session,'projection',None)
                revision=(getattr(session,'sid',None),getattr(projection,'cursor',None),owner.active())
                if revision!=previous or (owner.active() and loop.time()-last_sent>=1):
                    await response.write(('data: '+json.dumps(revision)+'\n\n').encode())
                    previous=revision;last_sent=loop.time()
                elif loop.time()-last_sent>=10:
                    await response.write(b': keepalive\n\n');last_sent=loop.time()
                await asyncio.sleep(.025)
        except ConnectionError:pass  # Browser disconnected; release its slot below.
        finally:update_clients.discard(token)
        return response
    app.router.add_get('/api/updates',updates)
    async def page(req):return web.FileResponse(ROOT/'app/dashboard/opportunity_static/dashboard.html')
    async def game(req):return web.FileResponse(ROOT/'app/dashboard/opportunity_static/index.html')
    async def style(req):return web.FileResponse(ROOT/'app/dashboard/static/style.css')
    async def shared(req):return web.FileResponse(ROOT/'app/dashboard/e5_static/state.js')
    app.add_routes([web.get('/',page),web.get('/game',game),web.get('/style.css',style),web.get('/shared-state.js',shared),web.get('/api/status',state),web.post('/api/start',start),web.post('/api/stop',stop),web.post('/api/references',import_references),web.post('/api/resolutions',import_resolutions),web.get('/api/resolution',resolution),web.get('/api/dashboard',dashboard),web.get('/api/sessions',catalog),web.get('/api/calculate',calculation)])
    app.router.add_static('/view/',ROOT/'app/dashboard/opportunity_static')
    async def cleanup(app):await owner.close()
    app.on_cleanup.append(cleanup)
    return app
