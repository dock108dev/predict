"""Directed transport/control fixture only; synthetic games never prove selectors."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
from aiohttp import web
from tests.test_native_redesign import Fixture as Base,configuration as prior
from tests.test_coverage import ke,pe
from app.collection.native_selectors import POLICY,SPORTS
from app.collection.transport_session import reopen
from app.dashboard.session_history import load,project_rows

def configuration(probe=False):
    s=prior();s['mode']='mock';s['mapping_revision']='sport-directed-games-v1';s['prediction']['discovery_requests']=36 if probe else 112
    if probe:
        s.pop('source_session');s['native_discovery']=dict(policy=POLICY,sports=list(SPORTS),discovery_only=True,generations=1)
    else:s['source_session']['native_discovery']=POLICY
    return s

class Fixture(Base):
    def __init__(self,probe=False):super().__init__();self.probe=probe;self.queries=[]
    async def boot(self,path):
        o=await super().boot(path);o.spec_factory=lambda:configuration(self.probe)
        if self.probe:o.endpoints.pop('aggregate')
        return o
    async def start(self,duration=10,fast=True):
        args=dict(duration=duration)
        if not self.probe:
            args['source_settings']=configuration()['source_session']
            if fast:args['source_settings']['refresh_seconds']=1
        res=await self.client.post('/api/start',json=args,headers=self.origin)
        assert res.status==200,await res.text()
        save=self.owner.session.journal.save
        def observe(row):save(row);self.books+=row['type']=='prediction_book';self.changed.set()
        self.owner.session.journal.save=observe
    async def rest(self,req):
        if req.path.startswith('/v4/'):
            assert not self.probe,'probe must never dispatch aggregate'
            return await super().rest(req)
        self.queries.append((req.path,dict(req.query)))
        if req.path=='/v2/leagues':return web.json_response(dict(leagues=[]))
        if req.path=='/v1/events':
            if req.query['tagSlug']!='nfl':return web.json_response(dict(events=[]))
            e=pe('p');e.update(gameId=1,startTime=self.schedule,active=True,closed=False,markets=[self.us_market('p0')])
            for t in e['teams']:t['league']='nfl'
            return web.json_response(dict(events=[e]))
        if req.path=='/trade-api/v2/events':
            if req.query['series_ticker']!='KXNFLGAME':return web.json_response(dict(events=[],cursor=''))
            e,m=ke('k');m['start_date']=self.schedule
            return web.json_response(dict(events=[e],milestones=[m],cursor=''))
        return await super().rest(req)

async def check(out,probe=False,fixture_class=Fixture):
    f=fixture_class(probe)
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
        o=await f.boot(out)
        try:
            await f.start()
            if probe:
                await f.wait(lambda:o.session.discovery.completed)
                assert not f.active() and not f.odds_calls and not o.session.aggregate
            else:
                await f.native_images();await f.wait(lambda:o.session.aggregate.health=='completed')
            await f.stop_route();assert o.error is None,o.error
            rows=reopen(o.session.journal.path)['rows'];saved=load(o.session.output)
            assert saved==project_rows(rows,saved['durable_cursor'])
            decisions=[r for r in rows if r['type']=='native_acquisition_selection']
            assert len(decisions)==2 and all('NFL' in r['selected'] for r in decisions),decisions
            assert o.session.cleanup_complete
            result=dict(classification=getattr(f,'classification','SYNTHETIC transport/control only'),probe=probe,queries=f.queries,
                selected={r['source']:r['selected'] for r in decisions},aggregate_requests=len(f.odds_calls),
                native_book_admissions=sum(r['type']=='prediction_book' for r in rows),exact_reopening=True,cleanup=True)
            (Path(out)/'verification.json').write_text(json.dumps(result,indent=2));print(result)
        finally:await f.close()

if __name__=='__main__':
    import sys
    p=Path(sys.argv[1]);p.mkdir(exist_ok=False);asyncio.run(check(p,'--probe' in sys.argv))
