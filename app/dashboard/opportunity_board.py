"""Isolated loopback board over two explicitly selected saved real captures."""
import argparse
import json
from aiohttp import web
from app.dashboard import e6_real as historical
from app.dashboard.e6_live import validate_saved
from app.dashboard.e5_preview import isolate_process
from app.collection.transport_session import reopen
from app.opportunities.board import evaluate, display

ROOT=historical.ROOT
SECOND='2a1fa76c-46a3-4fb8-9d55-403b3b5313b7'

def load_sessions():
    first=historical.load_package()
    folder=ROOT/'evidence/e6/live-watch/sessions'/SECOND
    second=validate_saved(folder)
    return {first['session']:(first,reopen(ROOT/historical.JOURNAL)['rows']),
            second['session']:(second,reopen(folder/'observations.jsonl')['rows'])}

def catalog(sessions):
    items=[]
    for sid,(p,_) in sessions.items():
        usable=[i for i,t in enumerate(p['timeline']) if all(c['book'] and c['connection']=='connected' and not c['receipt_stale'] and c['book']['sync']=='synchronized' for c in t['cards'])]
        items.append(dict(id=sid,hash=p['hash'],label=('Initial capture' if sid==historical.SID else 'Live-watch capture')+' · '+p['capture_start'],
            default_cutoff=usable[-1] if usable else len(p['timeline'])-1,
            timeline=[dict(id=t['id'],at=t['at'],label=t['label']) for t in p['timeline']]))
    return items

def present(result):
    for c in result['candidates']:
        c['display']={k:display(c[k],4 if k in ('raw_gap','raw_combined_price') else 2) for k in ('profit','return_pct','cash','notional','fees','raw_gap','raw_combined_price')}
        for leg in c['legs']:leg['display']={k:display(leg[k],4 if k=='ask' else 2) for k in ('ask','cash','fee','notional','top_size','visible_size')}
    ev=result['ev'];ev['display']={k:display(ev[k]) for k in ('expected_payout','expected_profit','return_pct','break_even_pct')}
    ev['leg']['display']={k:display(ev['leg'][k],4 if k=='ask' else 2) for k in ('ask','cash','fee','notional','top_size','visible_size')}
    return result

def create_app(sessions=None):
    sessions=load_sessions() if sessions is None else sessions
    @web.middleware
    async def headers(request,handler):
        if request.host not in (f'127.0.0.1:{request.url.port}',f'localhost:{request.url.port}'):raise web.HTTPForbidden()
        response=await handler(request)
        response.headers.update({'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
        return response
    app=web.Application(middlewares=[headers])
    async def listing(request):return web.json_response(catalog(sessions))
    async def calculation(request):
        try:
            q=request.query
            if any(len(q.getall(k))!=1 for k in q):raise ValueError('Duplicate selection')
            sid=q['session'];package,rows=sessions[sid]
            if q['hash']!=package['hash']:raise ValueError('Saved session identity changed')
            point=next((t for t in package['timeline'] if t['id']==q['cutoff']),None)
            if point is None:raise ValueError('Unknown cutoff')
            result=present(evaluate(point,rows,q.get('quantity','100'),q.get('scenario','cent'),q.get('probability','0.50'),q.get('contract','polymarket_us:1315440')))
            result.update(session=sid,hash=package['hash'],coverage=package['coverage'])
            return web.json_response(result)
        except (KeyError,ValueError) as exc:return web.json_response(dict(error=str(exc)),status=422)
    async def page(request):return web.FileResponse(ROOT/'app/dashboard/opportunity_static/index.html')
    async def style(request):return web.FileResponse(ROOT/'app/dashboard/static/style.css')
    async def state(request):return web.FileResponse(ROOT/'app/dashboard/e5_static/state.js')
    app.router.add_get('/',page);app.router.add_get('/api/sessions',listing);app.router.add_get('/api/calculate',calculation)
    app.router.add_get('/style.css',style);app.router.add_get('/shared-state.js',state)
    app.router.add_static('/view/',ROOT/'app/dashboard/opportunity_static')
    return app

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8782);a=p.parse_args()
    from app.dashboard.multi_game_server import create_app as multi_app
    import psycopg
    def deny(*args,**kwargs):raise PermissionError('File-only board forbids database connections')
    psycopg.connect=psycopg.Connection.connect=psycopg.AsyncConnection.connect=deny
    web.run_app(multi_app(),host='127.0.0.1',port=a.port,access_log=None)

if __name__=='__main__':main()
