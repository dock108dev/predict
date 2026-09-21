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


class Inventory(unittest.TestCase):
    def test_independent_market_pages_and_missing_gameid(self):
        pages=fixture();e=pe();e['gameId']=71
        pages[-1]=page('polymarket_us',dict(events=[e]))
        market=pm('independent');market['slug']='independent'
        p=page('polymarket_us',dict(markets=[market]),field='markets');p['params']['gameId']='71'
        cats=coverage.build(pages+[p],SOURCE,AS_OF)['venues']
        us=cats['polymarket_us']
        self.assertEqual(us['market_completeness'],'unestablished')
        self.assertEqual([m['id'] for m in us['markets']],['independent','pm'])
        self.assertEqual(us['markets'][0]['event_id'],'p')
        self.assertEqual(coverage.build(pages,SOURCE,AS_OF)['venues']['polymarket_us']['market_completeness'],'unestablished')

    def test_unmatched_priority_cap_and_exact_margin(self):
        cat=coverage.build(fixture()[:2],SOURCE,AS_OF)['venues']['kalshi']
        self.assertEqual(cat['markets'][0]['matching_status'],'unmatched')
        self.assertEqual(select_inventory(cat,AS_OF)[0],['km'])
        start=coverage.stamp(cat['events'][0]['scheduled_start'])
        self.assertEqual(select_inventory(cat,start-timedelta(seconds=301))[0],['km'])
        self.assertEqual(select_inventory(cat,start-timedelta(seconds=300))[0],[])
        self.assertEqual(cat['markets'][0]['subscription_exclusion'],'kickoff_margin')
        cat['markets'] += [dict(deepcopy(cat['markets'][0]),id='other')]
        self.assertEqual(select_inventory(cat,AS_OF,1),(['km'],2))
        self.assertEqual(cat['markets'][1]['subscription_exclusion'],'subscription_limit')

    def test_acknowledgement_and_disconnect_are_distinct(self):
        events=[]
        s=SimpleNamespace(spec=spec(),emit=lambda v,r:events.append(r),health={},connection_attempts=0)
        v=Venue(s,'kalshi');v.groups['g']=dict(ids=('m',),health='idle',**{k:set() for k in v.ever})
        v.emit('g','kalshi',dict(type='prediction_command',body=json.dumps(dict(id=1))))
        def ack(i):return dict(type='prediction_frame',body_b64=base64.b64encode(json.dumps(dict(type='subscribed',id=i,msg=dict(channel='orderbook_delta',sid=1))).encode()).decode())
        v.emit('g','kalshi',ack(2));self.assertEqual(v.snapshot()['acknowledged'],0)
        v.emit('g','kalshi',ack(1));self.assertEqual(v.snapshot()['acknowledged'],1)
        self.assertEqual(v.snapshot()['receiving'],0)
        book=dict(sync='synchronized',receipt_freshness='recent',source_time_progress='missing',raw=dict(ref=dict(market_id='m'),received_at=AS_OF.isoformat()))
        v.emit('g','kalshi',dict(type='prediction_book',book=book));self.assertEqual(v.snapshot()['usable'],1)
        v.health('g','disconnected');self.assertEqual(v.snapshot()['usable'],0)
        v.health('g','connected');self.assertEqual(v.snapshot()['usable'],0)
        book['sync']='unsynchronized';v.emit('g','kalshi',dict(type='prediction_book',book=book));self.assertEqual(v.snapshot()['usable'],0)
        book['sync']='synchronized';v.emit('g','kalshi',dict(type='prediction_book',book=book));self.assertEqual(v.snapshot()['usable'],1)

    def test_retry_preserves_failed_attempt_and_completes_position(self):
        good=fixture()[0];failed=deepcopy(good);failed['status']=429
        rows,state=coverage.traversal([failed,good],'kalshi','events')
        self.assertEqual(state['state'],'exhausted');self.assertEqual(state['unused_pages'],1)

    def test_grouped_saved_native_replay_preserves_exact_packets(self):
        path=Path('evidence/multi-game/sessions/5accf9ee-94b9-4b09-8130-6849f842155e/saved-observations.json')
        saved=json.loads(path.read_text())
        for row in saved['rows']:
            if row.get('source') in ('kalshi','polymarket_us'):
                row['stream_group']=row['source']+'-1'
        result=replay_groups(saved)
        self.assertEqual(len(result),2)
        self.assertTrue(all(r['exact_packets'] for r in result.values()))
        self.assertGreater(sum(sum(r['exact_native_books'].values()) for r in result.values()),0)

    def test_connection_and_ingress_resource_stop(self):
        reasons=[]
        s=SimpleNamespace(spec=spec(),profile=None,connection_attempts=12,request_stop=reasons.append)
        v=Venue(s,'kalshi');budget=GroupBudget(v)
        with self.assertRaises(BudgetStop):budget.reserve('connection')
        self.assertEqual(reasons,['connection_attempt_cap'])
        with self.assertRaises(BudgetStop):budget.charge_bytes(17*MIB)
        self.assertEqual(reasons[-1],'prediction_session_byte_cap')


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_single_refresh_and_complete_market_queries_before_selection(self):
        emitted=[]
        s=SimpleNamespace(spec=spec(),credentials={},emit=lambda v,r:emitted.append(r),producers={})
        d=Discovery(s)
        concurrent=0;peak=0;calls=[]
        async def venue(v):
            nonlocal concurrent,peak
            concurrent+=1;peak=max(peak,concurrent);calls.append((d.generation,v))
            await asyncio.sleep(.01)
            d.pages.extend(p for p in fixture() if p['source']==v)
            concurrent-=1
        d.venue=venue
        await asyncio.gather(d.discover(),d.discover())
        self.assertEqual(len(calls),2);self.assertEqual(d.generation,1)
        await d.discover(force=True);self.assertEqual(d.generation,2)
        self.assertEqual(len(d.inventory['kalshi']['markets']),1)
        self.assertFalse(any(r['type']=='prediction_command' for r in emitted))

    async def test_refresh_new_departed_closed_rescheduled_and_cutoff(self):
        cats=coverage.build(fixture()[:2],SOURCE,AS_OF)['venues']
        stop=asyncio.Event();emitted=[]
        s=SimpleNamespace(spec=spec(),profile=None,credentials={},health={},stop_event=stop,connection_attempts=0,
            emit=lambda v,r:emitted.append(r),discovery=SimpleNamespace(inventory=cats,markets={'kalshi':{'km':SimpleNamespace()}}))
        from app.adapters.kalshi import parse_market
        p=fixture()[1];body,_=coverage.decode_page(p)
        market=parse_market(coverage.response('kalshi',p,body),json.loads(body)['markets'][0],'k','KXNFLGAME')
        s.discovery.markets['kalshi']['km']=market
        class Producer:
            def __init__(self,*a,**kw):pass
            async def run(self,ms):await stop.wait()
            async def aclose(self):pass
        v=Venue(s,'kalshi')
        with patch('app.collection.continuous.PredictionProducer',Producer),patch('app.collection.continuous.now',return_value=AS_OF):
            await v.reconcile();first=next(iter(v.groups))
            await v.reconcile();self.assertEqual(next(iter(v.groups)),first)
            cats['kalshi']['events'][0]['scheduled_start']='2026-09-21T17:00:00Z'
            await v.reconcile();self.assertNotIn(first,v.groups)
            cats['kalshi']['markets'][0]['exclusion']='inactive_or_unknown_market_state'
            await v.reconcile();self.assertFalse(v.groups)
            cats['kalshi']['markets'][0]['exclusion']=None
            await v.reconcile();self.assertTrue(v.groups)
            cats['kalshi']['events'][0]['scheduled_start']=(AS_OF+timedelta(seconds=299)).isoformat()
            await v.reconcile();self.assertFalse(v.groups)
            cats['kalshi']['markets']=[]
            await v.reconcile();self.assertEqual(v.selected,[])

    async def test_retry_rate_and_request_ceiling(self):
        limits=spec()['prediction'];budget=PredictionBudget(limits);seen=[]
        c=REST('https://external-api.kalshi.com',limits,lambda r:None,5,budget,venue='kalshi')
        c.account_limits(dict(read=dict(refill_rate=4,bucket_capacity=20)),dict(default_cost=10,endpoint_costs=[]))
        async def fake(client,url,params=None,**kw):
            client.budget.reserve('discovery_request');seen.append(client.request_interval)
            return httpx.Response(429 if len(seen)==1 else 200,headers={'Retry-After':'2'})
        with patch('app.collection.prediction_producer.MockREST.get',fake),patch('app.collection.continuous.asyncio.sleep',new_callable=AsyncMock) as sleep:
            await c.get('https://external-api.kalshi.com/trade-api/v2/events')
            self.assertEqual(budget.requests,2);self.assertEqual(seen,[2.5,2.5]);sleep.assert_awaited_with(2.0)

    async def test_journal_reserved_stop_preserves_terminal(self):
        from app.collection.transport_session import ObservationJournal,reopen
        with tempfile.TemporaryDirectory() as tmp:
            s=ContinuousSession(spec(),Path(tmp),{})
            s.journal=ObservationJournal(Path(tmp)/'j.jsonl')
            s.journal.count=4032
            with self.assertRaises(BudgetStop):s.emit('session',dict(type='test'))
            self.assertEqual(s.reason,'journal_reserved_stop')
            s.journal.save(dict(type='session_finished'));s.journal.close()
            self.assertEqual(reopen(Path(tmp)/'j.jsonl')['state'],'complete')

    async def test_browser_client_close_manual_stop_idle_restart_and_single_owner(self):
        class LocalSession(ContinuousSession):
            async def start(self):
                # Use real journal/lifecycle; replace only fresh venue requests.
                self.credentials={};self.spec['mode']='mock'
                await super().start()
                async def venue(v):
                    self.discovery.pages.extend(p for p in fixture() if p['source']==v)
                self.discovery.venue=venue
                for producer in self.producers.values():
                    async def run(markets):await self.stop_event.wait()
                    producer.run=run
                return self.sid
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('no credentials')):
            out=Path(tmp)
            o=CoverageOwner(out/'old',pilot_output=out/'pilot',session_factory=LocalSession)
            # Mock mode still validates local destinations during original start.
            o.endpoints={v:dict(rest='http://127.0.0.1:1',ws='ws://127.0.0.1:1') for v in ('kalshi','polymarket_us')}
            server=TestServer(create_app(owner=o,sessions={}));await server.start_server()
            url=str(server.make_url('/')).rstrip('/')
            browser=ClientSession()
            try:
                self.assertFalse(o.active());self.assertIsNone(o.session)
                r=await browser.post(url+'/api/start',json={'duration':5},headers={'Origin':url})
                self.assertEqual(r.status,200,await r.text())
                await browser.close()  # server and collector remain alive
                await asyncio.sleep(.05);self.assertTrue(o.active())
                with self.assertRaises(ValueError):await o.start()
                async with ClientSession() as other:
                    r=await other.post(url+'/api/stop',json={},headers={'Origin':url});self.assertEqual(r.status,200)
                await o.finalizer
                self.assertEqual(o.session.reason,'manual_stop');self.assertTrue(o.session.cleanup_complete);self.assertIsNone(o.error)
                restarted=CoverageOwner(out/'old',pilot_output=out/'pilot')
                self.assertFalse(restarted.status()['start_available']);self.assertIsNone(restarted.session)
                with self.assertRaises(ValueError):await restarted.start()
            finally:
                await browser.close();await server.close()

class FullLocalTransport(unittest.IsolatedAsyncioTestCase):
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
        try:
            with tempfile.TemporaryDirectory() as tmp,patch('app.collection.continuous.ENDPOINTS',ep),patch('app.collection.continuous.now',return_value=AS_OF):
                value=spec();value['mode']='mock';value['duration']=10
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
                    # Real refreshed receipts must not churn unchanged subscriptions.
                    await s.discovery.discover(force=True)
                    await s.producers['kalshi'].reconcile();await s.producers['polymarket_us'].reconcile()
                    self.assertEqual(len(connections),3)
                finally:
                    await s.stop()
                self.assertEqual(s.reason,'manual_stop');self.assertTrue(s.cleanup_complete)
                self.assertTrue(all(x['usable']==0 for x in s.status_coverage().values()))
                replay=replay_groups(reopen(s.journal.path))
                self.assertEqual(sum(sum(r['exact_native_books'].values()) for r in replay.values()),32)
        finally:await server.close()
