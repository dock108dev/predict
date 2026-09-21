"""D2 offline boundary checks; no venue access or retained evidence writes."""
import asyncio
import base64
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock
import httpx
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from app.collection import coverage
from app.collection.continuous import (Discovery, Venue, ContinuousSession, REST,
    GroupBudget, select_inventory, LIMITS, MIB)
from app.collection.prediction_producer import PredictionBudget
from app.collection.odds_http import BudgetStop
from app.dashboard.coverage_owner import CoverageOwner, spec, replay_groups
from app.dashboard.multi_game_server import create_app
from tests.test_coverage import fixture, page, pe, pm, AS_OF, SOURCE


OUT=Path(__file__).resolve().parent
class QuietLocal90SecondFixture(unittest.IsolatedAsyncioTestCase):
    async def test_unmocked_discovery_to_grouped_sockets_and_manual_stop(self):
        """Only endpoints/credentials are substituted; real D2 request path executes."""
        from tests.test_coverage import ke, km
        from app.collection.transport_session import reopen
        calls=[];connections=[]
        def eligible_market(mid):
            m=pm(mid);m.update(slug=mid,description='Fixture full-game winner terms')
            for side,team in zip(m['marketSides'],('Detroit Lions','Buffalo Bills')):
                side.update(marketId=mid,team=dict(name=team))
            return m
        async def rest(req):
            calls.append((req.path,dict(req.query)))
            if req.path.endswith('/account/limits'):
                return web.json_response(dict(read=dict(refill_rate=200,bucket_capacity=600)))
            if req.path.endswith('/account/endpoint_costs'):
                return web.json_response(dict(default_cost=10,endpoint_costs=[]))
            if req.path=='/trade-api/v2/events':
                es,ms=zip(*(ke('k'+str(i)) for i in range(24)))
                return web.json_response(dict(events=es,milestones=ms,cursor=''))
            if req.path=='/trade-api/v2/markets':
                eid=req.query['event_ticker'];return web.json_response(dict(markets=[km(eid+'m',eid)],cursor=''))
            if req.path=='/v1/events':
                offset=int(req.query['offset']);es=[]
                for i in range(offset,min(offset+5,8)):
                    e=pe('p'+str(i));e['gameId']=i+1;e['markets']=[eligible_market('p'+str(i)+'m')];es.append(e)
                return web.json_response(dict(events=es))
            if req.path=='/v1/markets':
                mid='p'+str(int(req.query['gameId'])-1)+'m';m=eligible_market(mid)
                return web.json_response(dict(markets=[m]))
            raise AssertionError(req.path)
        async def ws(req):
            socket=web.WebSocketResponse();await socket.prepare(req)
            cmd=await socket.receive_json();connections.append(cmd)
            if 'params' in cmd:
                await socket.send_json(dict(type='subscribed',id=cmd['id'],msg=dict(channel='orderbook_delta',sid=1)))
                for i,mid in enumerate(cmd['params']['market_tickers']):
                    await socket.send_json(dict(type='orderbook_snapshot',sid=1,seq=i+1,msg=dict(market_ticker=mid,market_id='native-'+mid,yes_dollars_fp=[['0.4','10']],no_dollars_fp=[['0.5','20']])))
            else:
                for slug in cmd['subscribe']['marketSlugs']:
                    await socket.send_json(dict(requestId=cmd['subscribe']['requestId'],subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',marketData=dict(marketSlug=slug,bids=[],offers=[dict(px=dict(value='0.5',currency='USD'),qty='10')],state='OPEN')))
            async for _ in socket:pass
            return socket
        app=web.Application();app.router.add_get('/ws',ws);app.router.add_get('/{path:.*}',rest)
        server=TestServer(app);await server.start_server()
        url=str(server.make_url('/')).rstrip('/');ep={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
        tmp=str(OUT/'fixture90')
        try:
            with patch('app.collection.continuous.ENDPOINTS',ep),patch('app.collection.continuous.now',return_value=AS_OF):
                value=spec();value['mode']='mock';value['duration']=100
                s=ContinuousSession(value,Path(tmp),ep,credentials={})
                await s.start()
                try:
                    for _ in range(200):
                        await asyncio.sleep(.01)
                        c=s.status_coverage()
                        if c['kalshi']['usable']==24 and c['polymarket_us']['usable']==8:break
                        if s.task.done():break
                    self.assertEqual(c['kalshi']['discovered_markets'],24)
                    self.assertEqual(c['polymarket_us']['discovered_markets'],8)
                    self.assertEqual(c['kalshi']['usable'],24,s.reason)
                    self.assertEqual(c['polymarket_us']['usable'],8,s.reason)
                    self.assertEqual(len(connections),3)
                    self.assertEqual(s.producers['kalshi'].budget.requests,27)
                    self.assertEqual(s.producers['polymarket_us'].budget.requests,10)
                    await asyncio.sleep(max(0,65-(__import__('time').monotonic()-s.started_monotonic)))
                    self.assertEqual(s.discovery.published_generation,2)
                    OUT.joinpath('fixture90-refresh.json').write_text(json.dumps(s.discovery.status(),indent=2))
                    await asyncio.sleep(max(0,90-(__import__('time').monotonic()-s.started_monotonic)))
                    requested=__import__('time').monotonic()-s.started_monotonic
                finally:
                    await s.stop()
                OUT.joinpath('fixture90-result.json').write_text(json.dumps(dict(classification='quiet synthetic local fixture, not future live throughput',stop_requested_seconds=requested,duration=s.collection_seconds,reason=s.reason,resources=s.resources(),accounting=s.accounting(),generation=s.discovery.published_generation),indent=2))
                self.assertEqual(s.reason,'manual_stop');self.assertTrue(s.cleanup_complete)
                self.assertTrue(all(x['usable']==0 for x in s.status_coverage().values()))
                replay=replay_groups(reopen(s.journal.path))
                self.assertEqual(sum(sum(r['exact_native_books'].values()) for r in replay.values()),32)
        finally:await server.close()

if __name__=='__main__':unittest.main()
