"""Run only the isolated U1/U2 populated test workflow; no source ownership."""
import argparse
from copy import deepcopy
from aiohttp import web
from app.dashboard.multi_game_server import create_app
from app.dashboard.current_state import CURRENT_KEY
from app.dashboard.local_security import read_json
from tests.current_fixture import fixture, InjectedTestProvider, rebind
from tests.test_current_state import owner


def test_app():
    provider=InjectedTestProvider();app=create_app(owner=owner(),sessions={},current_provider=provider)
    async def change(req):
        options=await read_json(req)
        if set(options)-{'scenario'}:raise ValueError('Unknown test controls')
        store=app[CURRENT_KEY];raw=fixture(2 if options['scenario']=='update' else 1);raw['state_revision']=store.snapshot()['state_revision']+1;raw['runtime_id']=store.snapshot()['runtime_id']
        scenario=options['scenario']
        if scenario=='restart':raw['runtime_id']='syn:runtime-'+str(raw['state_revision'])
        if scenario=='expire':
            for lease in store.leases.values():lease['deadline']=store.monotonic()-1
            return web.json_response({'expired':True})
        if scenario=='remove':raw['events']=raw['events'][1:]
        if scenario=='insert':
            event=deepcopy(raw['events'][-1]);event['event_discriminator']='syn:inserted';event['title']='Synthetic inserted game';event['start_at']='2026-10-04T16:30:00+00:00';
            for g in event['groups']:
                for o in g['outcomes']:
                    for q in o['quotes'].values():
                        for key in ('native_event_id','native_market_id','native_outcome_id'):q['source'][key]+=':insert'
            raw['events'].insert(0,event);rebind(raw)
        if scenario=='partial':
            for e in raw['events']:
                for g in e['groups']:
                    for o in g['outcomes']:o['quotes']['prophetx']['state']='unavailable';o['quotes']['prophetx']['revision']=2
        if scenario=='budget':
            for e in raw['events']:
                for g in e['groups']:
                    for o in g['outcomes']:
                        for v in ('novig','prophetx'):o['quotes'][v]['state']='budget_delayed';o['quotes'][v]['revision']=2
        if scenario=='stale':
            raw['clock_at']='2026-10-04T22:00:00+00:00'
        if scenario=='unknown':
            for e in raw['events']:
                for g in e['groups']:
                    for o in g['outcomes']:q=o['quotes']['polymarket_us'];q['times']['source_at']=None;q['times']['source_time_kind']='unknown';q['revision']=2
        if scenario=='reset':raw['runtime_id']='syn:reset-'+str(raw['state_revision'])
        store.commit(raw)
        return web.json_response(store.notice())
    app.router.add_post('/__test/commit',change)
    return app


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--synthetic-test',action='store_true',required=True);p.add_argument('--port',type=int,default=8797);a=p.parse_args()
    web.run_app(test_app(),host='127.0.0.1',port=a.port,access_log=None)


if __name__=='__main__':main()
