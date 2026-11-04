"""Disposable UI01 browser states. No database, credentials or provider operations.

Run: .venv/bin/python -m tests.ui01_fixture_server
"""
import asyncio
from copy import deepcopy
from pathlib import Path
from aiohttp import web
from app.comparison.snapshot_math import assumptions
from app.dashboard.snapshot_api import page
from app.dashboard.snapshot_display import presented

ASSETS=Path(__file__).resolve().parents[1]/'app/dashboard/opportunity_static/current'


def fixture():
    rows=[]
    for i in range(32):
        r=dict(id=str(i),quote_id=str(i),kind='single',game_key='fixture-game',
            game_title='FIXTURE · Baltimore Ravens at Jacksonville Jaguars',league='NFL',
            start_at='2026-11-06T01:00:00+00:00',market={'market':'winner','period':'full_game'},
            venue='novig',native_side='bookmaker_outcome',selection={'participant':'NFL:BAL','predicate':'win'},
            original={'value':'2.00','units':'decimal_odds','payout':'1'},common_odds={'supported':True},
            cost_per_normal_claim='1/2',probability=f'{115-i}/200' if i<31 else None,gross_return_percent=str(15-i) if i<31 else None,
            net_return_percent=None,price_difference_cents=None,math={'missing':['upfront fee rate','sizing/depth assumption']},
            source_state='budget_delayed',times={},same_outcome={'supported':False},reference=None,
            probability_missing='Exact benchmark missing' if i==31 else None)
        rows.append(r)
    return dict(id='fixture-1',snapshot_id='fixture-capture',captured_at='2026-11-03T22:20:04+00:00',calculated_at='2026-11-03T22:20:05+00:00',
        rows=rows,pairs=[],references=[],games=[dict(game_key='fixture-game',title=rows[0]['game_title'],league='NFL',participants=[dict(id='NFL:BAL',name='Baltimore Ravens')])],assumptions=assumptions()[0],sources={},issues=[],scope={'leagues':['NFL','NCAAF','NBA','NCAAB','MLB','NHL']},counts={'observations':32})


def app():
    state=fixture();revision=1;refreshes=0
    async def shell(req):return web.FileResponse(ASSETS/'stored.html')
    async def asset(req):return web.FileResponse(ASSETS/req.match_info['name'])
    async def snapshot(req):
        nonlocal state,revision,refreshes
        if req.method=='POST':
            body=await req.json();await asyncio.sleep(.6)
            if body['action']=='refresh':
                refreshes+=1
                if refreshes==1:return web.json_response({'error':'Injected local refresh failure'},status=503)
            elif body.get('assumptions',{}).get('amount')=='13':return web.json_response({'error':'Injected recalculation failure'},status=503)
            revision+=1;state=deepcopy(state);state['id']='fixture-'+str(revision)
            if body['action']=='recalculate':state['assumptions']=assumptions(body['assumptions'])[0]
        if req.query.get('search')=='slow':await asyncio.sleep(.7)
        return web.json_response(page(state,req.query))
    async def details(req):
        row=next(r for r in state['rows'] if r['id']==req.query['id'])
        return web.json_response(dict(result_id=state['id'],snapshot_id=state['snapshot_id'],captured_at=state['captured_at'],row=presented(row),originals=[row],references=[],assumptions=state['assumptions']))
    instance=web.Application()
    for path in ['/','/odds','/ev','/arbs','/admin']:instance.router.add_get(path,shell)
    instance.router.add_get('/current/assets/{name}',asset)
    instance.router.add_get('/view/current/{name}',asset)
    instance.router.add_get('/api/comparison-snapshot',snapshot)
    instance.router.add_post('/api/comparison-snapshot',snapshot)
    instance.router.add_get('/api/comparison-snapshot/details',details)
    return instance


if __name__=='__main__':web.run_app(app(),host='127.0.0.1',port=8789)
