"""Authored loopback only: real ticket backend/finance and disposable SQL reads.

No production flag enables authored destinations. This factory is test-owned.
SQL capture is real, but its partition is substituted by expressly authored
qualified finance inputs after the SQL connection closes, as in SC03.
"""
import asyncio
from copy import deepcopy
import json
import resource
import sys
from pathlib import Path
from aiohttp import web
from app.dashboard.scanner_api import mount
from app.dashboard.scanner_client_api import mount as mount_client
from app.comparison.scanner_destinations import Destinations
from tests.sc03_fixture import ready
from tests.test_sc03_tickets import catalog
from tests.test_sc03_finance import AT
from tests import test_sc02_sql as sql

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'app/dashboard/opportunity_static/current'


def create_app(connector=None):
    app=web.Application()
    provider=sql.SQL.provider(None)
    scanner=mount(app,provider)
    scanner.start=lambda:None
    scanner.connector=connector or sql.SQL.connect
    scanner.clock=lambda:AT.isoformat()
    tickets=scanner.tickets
    tickets.allow_authored=True
    tickets.clock=lambda:AT.isoformat()
    current={};requests=[];witness=[];state=dict(delay=0,transport=False)
    original_capture=scanner._capture
    def reset(kind='native',amount='100'):
        p,f,x,row=ready(kind=kind,amount=amount)
        current.update(frame=f,inputs=x)
        scanner.projection=p;tickets.projection=p
        tickets.destinations=Destinations(catalog(f['instruments']))
        return row
    reset()
    def fresh():
        if connector:
            f,x,meta,ms=original_capture()
            witness.append(dict(actual_sql_revision=meta['current_rows_revision'],sql_capture_ms=ms,instruments=len(f['instruments']),ticket_partition='authored_substitution'))
            if len(witness)>256:del witness[:-256]
        return deepcopy(current['frame']),deepcopy(current['inputs'])
    tickets.fresh=fresh
    @web.middleware
    async def observe(req,handler):
        requests.append(dict(path=req.path,method=req.method))
        if len(requests)>512:del requests[:-512]
        if req.path.startswith('/api/scanner/ticket'):
            if state['transport']:return web.json_response(dict(error='authored_transport_loss'),status=503)
            if state['delay']:await asyncio.sleep(state['delay'])
        return await handler(req)
    app.middlewares.append(observe)
    async def control(req):
        value=await req.json();action=value.get('action')
        if action=='fixture':reset(value.get('kind','native'),value.get('amount','100'))
        elif action=='transitions':
            p=scanner.projection
            fixture=json.loads((ROOT/'tests/fixtures/sc04/workload.json').read_text())
            p.rows={r['id']:r for r in deepcopy(fixture['rows'])}
            p.pending.clear();p.errors=[];p.state='evaluated_positive'
            p.receipts={r['pair_id']:dict(qualifying=True) for r in p.rows.values()}
            p.transitions.censor('authored_transition_baseline')
            p._publish(deepcopy(p.rows),'evaluated')
            current['transition_rows']=deepcopy(p.rows)
        elif action=='transition_change':
            p=scanner.projection;rows=deepcopy(p.rows);key=value.get('row') or list(rows)[0]
            r=rows[key];r['metric']['value']=value.get('edge','20');r['supported_capital_usd']=value.get('size','500')
            r['dependency_revision']+=':changed';r['economic_revision']+=':changed'
            p._publish(rows,'evaluated')
        elif action=='rank_only':
            p=scanner.projection;p._publish(dict(reversed(list(p.rows.items()))),'evaluated')
        elif action=='overflow':
            p=scanner.projection
            for _ in range(130):p._publish(deepcopy(p.rows),'evaluated')
        elif action=='transition_remove':
            p=scanner.projection;rows=deepcopy(p.rows);rows.pop(value['row']);p._publish(rows,'evaluated')
        elif action=='transition_restore':
            p=scanner.projection;rows=deepcopy(p.rows);rows[value['row']]=deepcopy(current['transition_rows'][value['row']]);p._publish(rows,'evaluated')
        elif action=='change':
            x=current['inputs'];key=next(iter(x));x[key]['quote']['original']['value']=value.get('price','0.21')
            scanner.projection.ingest(current['frame'],x)
            while scanner.projection.pending:scanner.projection.drain()
        elif action=='loss':
            key=next(iter(current['inputs']));current['inputs'][key]['quote']['depth']=[dict(price='0.9',quantity='10000')]
            scanner.projection.ingest(current['frame'],current['inputs'])
            while scanner.projection.pending:scanner.projection.drain()
        elif action=='missing':tickets.destinations=Destinations()
        elif action=='expiry':tickets.clock=lambda:current['frame']['pairs'][0]['expires_at']
        elif action=='ttl':
            for slot in tickets.clients.values():slot['ttl']=tickets.timer()-1
        elif action=='stop':provider.dispatch=False;scanner.projection.stop()
        elif action=='epoch':scanner.projection.epoch='authored-epoch-reset'
        elif action=='withdraw':current['frame']['pairs']=[];scanner.projection.frame['pairs']=[];scanner.projection.rows={}
        elif action=='unknown':current['frame']['pairs'][0]['input_check']['state']='unavailable';scanner.projection.frame['pairs'][0]['input_check']['state']='unavailable'
        elif action=='transport':state['transport']=value.get('enabled',True)
        elif action=='delay':state['delay']=value.get('seconds',0)
        elif action=='restart':provider.dispatch=True;tickets.clock=lambda:AT.isoformat();reset()
        return web.json_response(dict(peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),provider_requests=0,financial_evaluations=scanner.projection.evaluations,requests=requests,witness=witness,sql_capture_enabled=connector is not None))
    async def stop(req):provider.dispatch=False;scanner.projection.stop();return web.json_response(dict(stopped=True))
    async def asset(req):
        name=req.match_info['name']
        if name not in ('scanner.js','scanner.css','board-client.js'):raise web.HTTPNotFound()
        return web.FileResponse(ASSETS/name)
    async def shell(req):
        return web.Response(text=(ASSETS/'scanner.html').read_text().replace('<body>','<body><p style="background:#fff0cc;padding:4px 12px;font-size:12px">Authored SC05 preview · invented qualified routes · zero provider requests · no source/installed authority</p>'),content_type='text/html')
    mount_client(app)
    app.router.add_post('/__test/state',control)
    app.router.add_post('/api/admin/current',stop)
    app.router.add_get('/current/assets/{name}',asset)
    app.router.add_get('/{tail:.*}',shell)
    return app


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    import os
    portable=os.environ.get('SC05_PORTABLE')=='1'
    if not portable:sql.SQL.setUpClass()
    try:web.run_app(create_app(None if portable else sql.SQL.connect),host='127.0.0.1',port=args.port,print=None)
    finally:
        if not portable:sql.SQL.tearDownClass()
