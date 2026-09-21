"""Local servers only. No credential lookup or provider sockets."""
import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from websockets.asyncio.server import serve
from app.collection.odds_http import HTTPPolicy,OddsHTTP,BudgetStop,Budget
from app.collection.run_spec import preflight
from app.collection.transport_session import TransportSession,reopen,reference_identity
from tests.test_kalshi import ack,frame
from tests.test_polymarket_us_stream import message


def policy(**kw):
    return HTTPPolicy(**dict(dict(requests=8,credits=8,dollars=Decimal('1'),dollars_per_credit=Decimal('.01'),
        reserve_per_request=1,initial_used=0,initial_remaining=100,plan_evidence='fabricated mock plan',
        response_bytes=65536,session_bytes=1048576,timeout=1,retries=2,backoff=.01),**kw))


def spec():
    now=datetime.now(timezone.utc)
    p=policy().__dict__.copy()
    p['dollars']=str(p['dollars']);p['dollars_per_credit']=str(p['dollars_per_credit'])
    return dict(reference_enabled=True,mode='mock',event='mock-game',participants=['tb','cin'],scheduled_start=(now+timedelta(hours=1)).isoformat(),
        start_after=(now-timedelta(seconds=1)).isoformat(),start_before=(now+timedelta(minutes=1)).isoformat(),
        duration=2,reference_cadence=.05,discovery_cadence=1,stale_seconds=.2,
        sources={s:dict(event_id=e,market_id=m,participant_mapping={'Tampa Bay':'tb','Cincinnati':'cin'},
                       credential_reference='unread-mock-reference',entitlement_reference='fabricated mock entitlement')
                 for s,e,m in [('the_odds_api','mock-event','h2h'),('kalshi','E','M'),('polymarket_us','74905','381958')]},
        mapping_revision='mock-mapping-v1',assessment_revisions=dict.fromkeys(['pairing','lineage','fees','settlement']),
        http=p,prediction=dict(messages=100,connections=2,frame_bytes=65536,session_bytes=1048576,discovery_requests=20,dollar_cap_per_source='0',dollars_per_discovery_request='0',dollars_per_connection='0',plan_evidence='fabricated zero-cost local servers'),
        cleanup='retain journal; close local servers',capture_authorization='local mock test only')


def odds(s):
    return json.dumps(dict(id='mock-event',sport_key='americanfootball_nfl',commence_time=s['scheduled_start'],
        home_team='Tampa Bay',away_team='Cincinnati',bookmakers=[dict(key='pinnacle',markets=[dict(key='h2h',
        outcomes=[dict(name='Tampa Bay',price='2.1'),dict(name='Cincinnati',price='1.9')])])])).encode()


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.records=[];self.calls=[];self.count=0;self.mode='ok';self.entered=asyncio.Event()
        async def handler(request):
            mode=self.mode
            self.calls.append(dict(path=request.path,query=dict(request.query)));self.count+=1
            self.entered.set()
            headers={'x-requests-used':str(self.count),'x-requests-remaining':str(100-self.count),'x-requests-last':'1'}
            if mode=='unknown':headers={}
            if mode=='contradictory':headers['x-requests-last']='2'
            if mode=='exhausted':headers['x-requests-remaining']='0'
            if mode=='redirect':return web.Response(status=302,headers={**headers,'Location':'http://127.0.0.1:1/never'})
            if mode=='echo':return web.Response(body=b'e6-dummy-key',headers=headers)
            if mode=='429':return web.Response(status=429,body=b'{}',headers={**headers,'Retry-After':'1'})
            if mode=='wait':await asyncio.sleep(.15)
            if mode in ('stream','truncate'):
                response=web.StreamResponse(headers={**headers,**({'Content-Length':'999'} if mode=='truncate' else {})})
                await response.prepare(request);await response.write(b'abc');await asyncio.sleep(.15)
                if mode=='truncate':
                    if request.transport:request.transport.close()
                    return response
                try:await response.write(b'def');await response.write_eof()
                except (ConnectionError,RuntimeError):pass
                return response
            return web.Response(body=b'abcdef' if mode=='large' else b'{"ok":true}',headers=headers)
        app=web.Application();app.router.add_get('/{path:.*}',handler)
        self.runner=web.AppRunner(app,access_log=None);await self.runner.setup()
        self.site=web.TCPSite(self.runner,'127.0.0.1',0);await self.site.start()
        self.url='http://127.0.0.1:'+str(self.site._server.sockets[0].getsockname()[1])
        self.transport=None
    async def asyncTearDown(self):
        if self.transport:await self.transport.aclose()
        await self.runner.cleanup()
    def make(self,**kw):
        self.transport=OddsHTTP(self.url,'mock-event',policy(**kw),self.records.append);return self.transport
    async def test_request_exact_redaction_and_pre_dispatch_budget(self):
        t=self.make(requests=1);r=await t.request()
        self.assertEqual(base64.b64decode(r['body_b64']),b'{"ok":true}')
        self.assertEqual(self.calls[0]['query'],dict(markets='h2h',bookmakers='pinnacle',oddsFormat='decimal',dateFormat='iso',includeSids='true',apiKey='e6-dummy-key'))
        self.assertNotIn('e6-dummy-key',json.dumps(self.records))
        with self.assertRaises(BudgetStop):await t.request()
        self.assertEqual(len(self.calls),1)
    async def test_stream_limit_before_retention(self):
        self.mode='large';t=self.make(response_bytes=3);r=await t.request()
        self.assertFalse(r['complete']);self.assertEqual(base64.b64decode(r['body_b64']),b'abc')
        self.assertLessEqual(t.total_bytes,4)
    async def test_unknown_contradiction_exhaustion_redirect_echo(self):
        for mode in ('unknown','contradictory','exhausted','redirect','echo'):
            with self.subTest(mode=mode):
                self.mode=mode;self.count=0;t=self.make();r=await t.request()
                self.assertIsNotNone(t.budget.reason)
                with self.assertRaises(BudgetStop):await t.request()
                self.assertNotIn('e6-dummy-key',json.dumps(r));await t.aclose()
    async def test_timeout_truncation_and_cancel_stream(self):
        for mode in ('wait','truncate','stream'):
            self.mode=mode;self.count=0;self.entered.clear();t=self.make(timeout=.3 if mode=='truncate' else .04)
            task=asyncio.create_task(t.request());await self.entered.wait()
            if mode=='stream':
                await asyncio.sleep(.01);task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            else:await task
            self.assertFalse(self.records[-1]['complete']);self.assertIsNotNone(t.budget.reason);await t.aclose()
    async def test_cancel_during_connection_and_no_refund(self):
        t=self.make()
        async def wait(*a,**k):await asyncio.sleep(5)
        with patch('aiohttp.TCPConnector.connect',wait):
            task=asyncio.create_task(t.request());await asyncio.sleep(.01);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(t.budget.credits,1);self.assertFalse(self.records[-1]['complete'])
    async def test_429_retries_charge_each_dispatch(self):
        self.mode='429';t=self.make()
        for _ in range(3):self.assertEqual((await t.request())['status'],429)
        self.assertEqual((t.budget.requests,t.budget.credits),(3,3))
    async def test_concurrency_and_total_bytes(self):
        self.mode='wait';t=self.make(session_bytes=11)
        task=asyncio.create_task(t.request());await self.entered.wait()
        with self.assertRaises(BudgetStop):await t.request()
        await task
        with self.assertRaises(BudgetStop):await t.request()
    def test_disabled_and_cost_reservation(self):
        with self.assertRaises(ValueError):OddsHTTP('https://api.the-odds-api.com','event',policy(),self.records.append)
        with self.assertRaises(ValueError):OddsHTTP(self.url,'event',policy(),self.records.append,dummy_key='other')
        b=Budget(policy(dollars=Decimal('0')))
        with self.assertRaises(BudgetStop):b.reserve()
        self.assertEqual(b.requests,0)


class PreflightTests(unittest.TestCase):
    def test_idle_preflight_and_real_start_blocked(self):
        s=spec();s['mode']='real';s['reference_enabled']=False
        with patch('aiohttp.ClientSession',side_effect=AssertionError('network')),patch('os.getenv',side_effect=AssertionError('credential')):
            self.assertTrue(preflight(s)['valid'])
            owner=TransportSession(s,'/unused',{})
            self.assertEqual(owner.state,'idle')
            with patch('app.collection.venue_access.load_credentials',side_effect=ValueError('missing credential')):
                with self.assertRaises(ValueError):asyncio.run(owner.start())
    def test_missing_conflicts_and_null_economics(self):
        self.assertTrue(preflight(spec())['valid'])
        for field in ('participants','mapping_revision','http','cleanup'):
            s=spec();del s[field];self.assertIn(field+': missing',preflight(s)['errors'])
        s=spec();s['sources']['kalshi']['participant_mapping']={};self.assertFalse(preflight(s)['valid'])
        s=spec();s['scheduled_start']=s['start_after'];self.assertFalse(preflight(s)['valid'])
        s=spec();s['duration']=float('nan');self.assertFalse(preflight(s)['valid'])
    def test_reference_identity_schedule_mapping_cutoff(self):
        s=spec();r=dict(complete=True,status=200,body_b64=base64.b64encode(odds(s)).decode())
        self.assertTrue(reference_identity(r,s)[0])
        for key,value in [('id','wrong'),('commence_time','2020-01-01T00:00:00Z'),('home_team','unknown')]:
            body=json.loads(odds(s));body[key]=value;r['body_b64']=base64.b64encode(json.dumps(body).encode()).decode()
            self.assertFalse(reference_identity(r,s)[0])


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.s=spec();self.s['duration']=2.2;self.s['http']['requests']=64;self.s['http']['credits']=64
        self.s['discovery_cadence']=10
        self.calls=0;self.ref_calls=0;self.k_connections=0;self.p_connections=0;self.ref_mode='ok'
        self.tmp=tempfile.TemporaryDirectory();self.owner=None
        # Retained PMUS market metadata is adapted into a fabricated future schedule.
        self.pmarket=json.loads(Path('evidence/phase-0/pmus-tb-market.json').read_text())['market']
        self.pmarket['gameStartTime']=self.s['scheduled_start']
        async def http(request):
            self.calls+=1;path=request.path
            if '/odds' in path:
                self.ref_calls+=1
                headers={'x-requests-used':str(self.ref_calls),'x-requests-remaining':str(100-self.ref_calls),'x-requests-last':'1'}
                if self.ref_mode=='429':return web.Response(status=429,body=b'{}',headers={**headers,'Retry-After':'1'})
                return web.Response(body=odds(self.s),headers=headers)
            if '/series/' in path:return web.json_response({'series':{'ticker':'KXNFLGAME','category':'Sports'}})
            if path.endswith('/events') and '/leagues/' not in path:
                return web.json_response(dict(cursor='',events=[dict(event_ticker='E',series_ticker='KXNFLGAME',title='Tampa Bay vs. Cincinnati')],
                    milestones=[dict(category='Sports',type='football_game',related_event_tickers=['E'],start_date=self.s['scheduled_start'])]))
            if path.endswith('/markets'):
                return web.json_response({'cursor':'','markets':[dict(ticker='M',event_ticker='E',title='Tampa Bay wins',status='active')]})
            if '/leagues/' in path:
                return web.json_response(dict(events=[dict(id='74905',title='Tampa Bay vs. Cincinnati',startTime=self.s['scheduled_start'],
                    teams=[dict(name='Tampa Bay'),dict(name='Cincinnati')],markets=[self.pmarket])]))
            return web.Response(status=404)
        app=web.Application();app.router.add_get('/{path:.*}',http)
        self.runner=web.AppRunner(app,access_log=None);await self.runner.setup()
        self.site=web.TCPSite(self.runner,'127.0.0.1',0);await self.site.start()
        self.url='http://127.0.0.1:'+str(self.site._server.sockets[0].getsockname()[1])
        async def kalshi(ws):
            self.k_connections+=1
            try:
                command=json.loads(await ws.recv());await ws.send(ack(command['id']))
                await ws.send(frame(1));await ws.send(frame(2,'orderbook_delta'))
                if self.k_connections==1:await ws.send(frame(4,'orderbook_delta'))
                await ws.wait_closed()
            except Exception:pass
        async def pmus(ws):
            self.p_connections+=1
            try:
                command=json.loads(await ws.recv());rid=command['subscribe']['requestId']
                await ws.send(message(rid,price='.4' if self.p_connections==1 else '.3'))
                if self.p_connections==1:await ws.close()
                else:await ws.wait_closed()
            except Exception:pass
        self.ks=await serve(kalshi,'127.0.0.1',0);self.ps=await serve(pmus,'127.0.0.1',0)
        self.endpoints=dict(reference=self.url,kalshi=dict(rest=self.url,ws='ws://127.0.0.1:'+str(self.ks.sockets[0].getsockname()[1])),
            polymarket_us=dict(rest=self.url,ws='ws://127.0.0.1:'+str(self.ps.sockets[0].getsockname()[1])))
    async def asyncTearDown(self):
        if self.owner and self.owner.task:await self.owner.stop()
        self.ks.close();self.ps.close();await self.ks.wait_closed();await self.ps.wait_closed()
        await self.runner.cleanup();self.tmp.cleanup()
    async def start(self):
        self.owner=TransportSession(self.s,self.tmp.name,self.endpoints)
        self.assertEqual(self.calls,0)
        await self.owner.start()
        return self.owner
    async def test_native_producers_recovery_mixed_persistence_and_exact_reopen(self):
        o=await self.start();await o.task
        saved=reopen(o.journal.path)
        self.assertEqual(saved,reopen(o.journal.path));self.assertEqual(saved['state'],'complete')
        self.assertEqual(o.delivered,o.persisted)
        books=[r for r in saved['rows'] if r['type']=='prediction_book']
        self.assertEqual({r['source'] for r in books},{'kalshi','polymarket_us'})
        self.assertGreaterEqual(self.k_connections,2);self.assertGreaterEqual(self.p_connections,2)
        for venue in ('kalshi','polymarket_us'):
            states=[r['book']['sync'] for r in books if r['source']==venue]
            self.assertIn('unsynchronized',states);self.assertIn('synchronized',states)
        self.assertTrue(any(r['type']=='reference_http' for r in saved['rows']))
        self.assertTrue(all(r.get('economics') is None for r in saved['rows']))
        output=Path(self.tmp.name)
        (output/'mixed-session.jsonl').write_bytes(o.journal.path.read_bytes())
        (output/'mixed-summary.json').write_text(json.dumps(dict(session=o.sid,delivered=o.delivered,persisted=o.persisted,
            http_requests=self.calls,reference_requests=self.ref_calls,kalshi_connections=self.k_connections,
            pmus_connections=self.p_connections,sha256=saved['sha256'],reason=o.reason,exact_replay=True,
            provenance='local mock HTTP/WS; fabricated frames; adapted retained PMUS metadata'),indent=2))
    async def test_cancel_backoff_and_start_over_60_seconds(self):
        self.s['duration']=120;self.ref_mode='429'
        o=await self.start()
        for _ in range(100):
            if self.ref_calls:break
            await asyncio.sleep(.01)
        await asyncio.sleep(.03);await o.stop()
        self.assertEqual(o.reference.budget.requests,1)
        self.assertEqual(o.state,'stopped');self.assertEqual(o.reason,'manual_stop')
    async def test_changed_schedule_stops_discovery(self):
        o=await self.start()
        self.s['scheduled_start']=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        await o.task
        self.assertTrue(o.reason.startswith('discovery_failure'))
        self.assertEqual(self.ref_calls,0)


class AdditionalBounds(unittest.IsolatedAsyncioTestCase):
    def test_conservative_overreservation_no_false_refund(self):
        b=Budget(policy(reserve_per_request=2,credits=8))
        for i in range(1,4):
            b.reserve();b.reconcile([('x-requests-used',str(i)),('x-requests-remaining',str(100-i)),('x-requests-last','1')])
            self.assertIsNone(b.reason)
        self.assertEqual(b.credits,6);self.assertEqual(b.remaining,94)
        b.reserve()
        with self.assertRaises(BudgetStop):b.reserve()
    def test_quota_duplicate_and_reset_stop(self):
        for headers in ([('x-requests-used','1'),('x-requests-last','1'),('x-requests-remaining','99'),('x-requests-remaining','99')],
                        [('x-requests-used','0'),('x-requests-last','0'),('x-requests-remaining','200')]):
            b=Budget(policy());b.reserve();b.reconcile(headers);self.assertIsNotNone(b.reason)
    def test_prediction_cost_reserved_before_dispatch(self):
        from app.collection.prediction_producer import PredictionBudget
        limits=spec()['prediction'];limits['dollars_per_discovery_request']='.1'
        b=PredictionBudget(limits)
        with self.assertRaises(BudgetStop):b.reserve('discovery_request')
        self.assertEqual(b.requests,0)
    def test_replay_tamper_torn_and_interrupted(self):
        from app.collection.transport_session import ObservationJournal
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'journal';journal=ObservationJournal(path);journal.save(dict(type='observation'));journal.close()
            self.assertEqual(reopen(path)['state'],'interrupted')
            original=path.read_bytes();path.write_bytes(original[:-1])
            with self.assertRaises(ValueError):reopen(path)
            path.write_bytes(original.replace(b'observation',b'xxxxxxxxxxx'))
            with self.assertRaises(ValueError):reopen(path)
    def test_precise_nested_preflight_and_secret_field(self):
        s=spec();del s['http']['plan_evidence']
        self.assertIn('http.plan_evidence: missing',preflight(s)['errors'])
        s=spec();s['sources']['kalshi']['apiKey']='prohibited'
        self.assertFalse(preflight(s)['valid'])
    def test_preflight_malformed_source_and_overflow_duration(self):
        s=spec();s['sources']['the_odds_api']=None
        self.assertFalse(preflight(s)['valid'])
        s=spec();s['duration']=1e300
        self.assertFalse(preflight(s)['valid'])

    async def test_manual_stop_during_discovery_closes_siblings(self):
        from app.collection.prediction_producer import PredictionProducer
        s=spec();s['duration']=120
        with tempfile.TemporaryDirectory() as tmp:
            endpoint=dict(rest='http://127.0.0.1:1',ws='ws://127.0.0.1:1')
            owner=TransportSession(s,tmp,dict(reference='http://127.0.0.1:1',kalshi=endpoint,polymarket_us=endpoint))
            cancelled=[]
            async def slow(producer):
                try:await asyncio.sleep(20)
                finally:cancelled.append(producer.venue)
            with patch.object(PredictionProducer,'discover',slow):
                await owner.start();await asyncio.sleep(.01)
                await asyncio.wait_for(owner.stop(),1)
            self.assertEqual(set(cancelled),{'kalshi','polymarket_us'})
            self.assertEqual(owner.state,'stopped')
