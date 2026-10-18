"""Disposable loopback scanner preview; authored responses, no provider imports."""
import argparse
import asyncio
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import resource
from pathlib import Path
from aiohttp import web
from tests.sc04_fixture import AT

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'app/dashboard/opportunity_static/current'


def create_app():
    fixture = json.loads((ROOT / 'tests/fixtures/sc04/workload.json').read_text())
    state = dict(revision=1, epoch='authored-sc04-epoch-1', mode='ready', delay=0, conflict=False, mismatch=False)
    app = web.Application()
    requests = []

    async def control(req):
        value = await req.json()
        state.update(value)
        return web.json_response(dict(state=state, requests=requests[-256:], peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if __import__('sys').platform=='darwin' else 1024)))

    async def client(req):
        manifest = json.loads((ASSETS / 'scanner-runtime.json').read_text())
        return web.json_response(dict(protocol='predict-opportunity-scanner-1', asset_revision='incompatible' if state['mismatch'] else manifest['asset_revision'], assets_valid=True))

    def response(query, saved):
        page = deepcopy(fixture['page'])
        filters = {k:sorted(query.get(k, '').split(',')) if query.get(k) else [] for k in ('venues','sports','leagues','markets','periods')}
        filters.update(category=query.get('category', 'covered_outcome_arb'), minimum_edge=query.get('minimum_edge'), minimum_size=query.get('minimum_size'))
        offset = int(query.get('offset', 0))
        rows = deepcopy(fixture['rows'])
        category = filters['category']
        basis = {'covered_outcome_arb':'net_complete_minimum_return_percent','conditional_hedge':'net_decisive_minimum_return_percent','ev':'net_expected_return_percent'}[category]
        for row in rows:
            row.update(category=category, metric_basis=basis)
            row['id'] = row['opportunity_id']+':'+category
            if category=='conditional_hedge':
                row.update(settlement_complete=False, conditioning='decisive_outcomes_only', reasons=['adverse_settlement_case'])
            if category=='ev':
                row.update(current=int(row['opportunity_id'].split(':')[-1])%2==0, conditioning='probability_based')
            if saved['revision']>1:
                row['dependency_revision'] += ':'+str(saved['revision'])
                row['economic_revision'] += ':'+str(saved['revision'])
        if saved['revision']%2==0:
            rows[0]['metric'] = dict(value='6.49', display='+6.49')
            rows[0], rows[1] = rows[1], rows[0]
        if saved['mode']=='withdrawn': rows=rows[1:]
        if saved['mode']=='expiry':
            for row in rows: row['expires_at']=AT.isoformat()
        if saved['mode']=='long':
            for row in rows:
                row['event_context']['title'] += ' · Extremely long original participant and market name with retained exact contract meaning'
                for p in row['positions']: p['predicate']['participant'] += ' · Extremely long native instrument description'
        def matches(row):
            return (not filters['venues'] or set(row['venues']).issubset(filters['venues'])) and all(not filters[k] or row[key] in filters[k] for k,key in (('sports','sport'),('leagues','league'),('markets','market'),('periods','period'))) and (filters['minimum_edge'] is None or Fraction(row['metric']['value'])>=Fraction(filters['minimum_edge'])) and (filters['minimum_size'] is None or Fraction(row['supported_capital_usd'])>=Fraction(filters['minimum_size']))
        rows = [r for r in rows if matches(r)]
        mode = saved['mode']
        if mode in ('zero','waiting','unavailable','stopped','unsupported'): rows=[]
        total=len(rows)
        query_id=sha256(json.dumps(dict(filters=filters,offset=offset,limit=100),sort_keys=True).encode()).hexdigest()
        since=query.get('since')
        wire_mode='snapshot' if since is None else 'resync' if query.get('epoch')!=saved['epoch'] or query.get('query_id')!=query_id or int(since)>saved['revision'] else 'unchanged' if int(since)==saved['revision'] else 'replace_page'
        output=rows[offset:offset+100]
        page.update(mode=wire_mode, epoch=saved['epoch'], query_id=query_id, publication_revision=saved['revision'], filters=filters, metric_basis=basis,
                    total_matching=total, offset=offset, limit=100, next_offset=offset+100 if offset+100<total else None,
                    rows=[] if wire_mode=='unchanged' else output,ranked_ids=[r['id'] for r in output],expires_at=min((r['expires_at'] for r in output),default=None))
        page['coverage'].update(state={'zero':'evaluated_zero','waiting':'not_evaluated','unavailable':'unavailable','partial':'partial','stopped':'stopped','unsupported':'unavailable'}.get(mode,'evaluated_positive'),
                                complete=mode not in ('partial','waiting','unavailable','stopped','unsupported'),no_qualifying_opportunities=mode=='zero',
                                evaluated_pairs=0 if mode=='waiting' else 65 if mode=='partial' else 130,qualifying_pairs=total)
        if mode=='unavailable':page['coverage']['errors']=['authored_shared_failure']
        if mode=='unsupported':page['unsupported_filters']=['authored_scope_unsupported']
        return page

    async def scanner(req):
        requests.append(dict(path=req.path,query=dict(req.query)))
        if len(requests)>256:del requests[:-256]
        saved=deepcopy(state)
        if saved['delay']:await asyncio.sleep(min(saved['delay'],2))
        if saved['mode']=='transport':return web.json_response(dict(error='authored_transport_loss'),status=503)
        if 'expected_revision' in req.query and (saved['conflict'] or int(req.query['expected_revision'])!=saved['revision']):
            state['conflict']=False
            return web.json_response(dict(error='scanner_page_revision_changed'),status=409)
        return web.json_response(response(req.query,saved))

    async def stop(req):
        assert await req.json()=={'action':'stop'}
        state.update(mode='stopped',revision=state['revision']+1)
        return web.json_response(dict(stopped=True))

    async def asset(req):
        name=req.match_info['name']
        if name not in ('scanner.js','scanner.css','stored.js','stored.css','board-client.js','board-read.js'):raise web.HTTPNotFound()
        return web.FileResponse(ASSETS/name)

    async def shell(req):
        html=(ASSETS/'scanner.html').read_text().replace('<body>','<body><div style="padding:5px 12px;background:#fff0cc;font:12px system-ui">Authored SC04 preview · no current source or ticket authority · zero provider requests</div>')
        return web.Response(text=html,content_type='text/html')

    app.router.add_post('/__test/state',control)
    app.router.add_get('/api/scanner/client',client)
    app.router.add_get('/api/scanner',scanner)
    app.router.add_post('/api/admin/current',stop)
    app.router.add_get('/current/assets/{name}',asset)
    app.router.add_get('/{tail:.*}',shell)
    # Expose the response builder for schema checks without starting a collector.
    app['response_builder']=response
    app['authored_state']=state
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8799)
    args=parser.parse_args()
    web.run_app(create_app(),host='127.0.0.1',port=args.port,print=None)
