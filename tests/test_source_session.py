"""Ordinary owner/routes against isolated transports; never credential or provider access."""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from tests.segmented_collector_fixture import Fixture
from app.dashboard.coverage_owner import CoverageOwner,spec
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_history import load,project_rows
from app.collection.transport_session import reopen
from app.collection.source_session import VERSION,ROLES,validate,configure
from app.dashboard.price_comparison import comparisons


def settings(**kw):
    value=dict(version=VERSION,roles=ROLES,scopes=[dict(sport='NFL',markets=['h2h','spreads','totals'],event_ids=[])],
        refresh_seconds=1,stale_seconds=2,event_limit=2,quota_observed_at=datetime.now(timezone.utc).isoformat(),
        http=dict(requests=20,credits=60,dollars='0',dollars_per_credit='0',reserve_per_request=3,
            initial_used=0,initial_remaining=100,plan_evidence='SIMULATED quota; zero actual requests or credits',
            response_bytes=1048576,session_bytes=8388608,timeout=2,retries=0,backoff=1))
    value.update(kw);return deepcopy(value)


class UnifiedFixture(Fixture):
    def __init__(self):
        super().__init__();self.odds_calls=[];self.used=0;self.quote='2.1';self.missing=False;self.empty=False;self.error=False;self.block=None;self.entered=asyncio.Event();self.release=asyncio.Event()
    def event(self):
        return dict(id='mock-event',sport_key='americanfootball_nfl',home_team='Buffalo Bills',away_team='Detroit Lions',commence_time=self.schedule)
    def body(self):
        event=self.event();event['bookmakers']=[]
        if self.empty:return event
        for book in ('novig','prophetx','pinnacle','draftkings','betmgm'):
            if self.missing and book=='prophetx':continue
            markets=[dict(key='h2h',last_update=datetime.now(timezone.utc).isoformat(),outcomes=[dict(name='Buffalo Bills',price=self.quote if book=='novig' else '1.9'),dict(name='Detroit Lions',price='2.0')])]
            event['bookmakers'].append(dict(key=book,markets=markets))
        return event
    async def rest(self,req):
        if not req.path.startswith('/v4/'):
            return await super().rest(req)
        self.odds_calls.append((req.path,dict(req.query)));self.changed.set()
        phase='response' if req.path.endswith('/odds') else 'discovery'
        if self.block==phase:
            self.entered.set();await self.release.wait()
        cost=3 if phase=='response' else 0;self.used+=cost
        headers={'x-requests-used':str(self.used),'x-requests-remaining':str(100-self.used),'x-requests-last':str(cost)}
        if getattr(self,'malformed',False) and phase=='response':return web.Response(body=b'{',headers=headers)
        if getattr(self,'extra_bad_event',False):
            if phase=='discovery':return web.json_response([dict(self.event(),id='bad-event'),self.event()],headers=headers)
            if '/bad-event/' in req.path:return web.json_response({},headers=headers)
        if self.error and phase=='response':return web.json_response({'error':'SIMULATED failure'},status=503,headers=headers)
        return web.json_response(self.body() if phase=='response' else [self.event()],headers=headers)
    async def boot(self,path):
        app=web.Application();app.router.add_get('/ws',self.ws);app.router.add_get('/{path:.*}',self.rest)
        self.server=TestServer(app);await self.server.start_server();url=str(self.server.make_url('/')).rstrip('/')
        self.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')};self.endpoints['aggregate']=url
        def config():
            value=spec();value.update(mode='mock',reference_enabled=False)
            value['v1_comparison_policy']=None  # Original winner-wire control.
            return value
        self.owner=CoverageOwner(Path(path)/'unused',pilot_output=Path(path)/'sessions',endpoints=self.endpoints,product_mode=True,spec_factory=config)
        self.client=TestClient(TestServer(create_app(owner=self.owner,sessions={},watch_path=Path(path)/'watches.json')));await self.client.start_server()
        self.origin={'Origin':str(self.client.make_url('/')).rstrip('/')}
        return self.owner
    async def start_route(self,config=None):
        resp=await self.client.post('/api/start',json=dict(duration=30,source_settings=config or settings()),headers=self.origin)
        data=await resp.json()
        if resp.status!=200:raise AssertionError(data)
        original=self.owner.session.journal.save
        def saved(row):
            original(row);self.books+=row['type']=='prediction_book';self.changed.set()
        self.owner.session.journal.save=saved
        return data
    async def native_images(self):
        await self.wait(lambda:len(self.active())==2);await self.images()
    async def stop_route(self):
        response=await self.client.post('/api/stop',json={},headers=self.origin)
        if response.status!=200:raise AssertionError(await response.text())
        await self.owner.finalizer
    async def close(self):
        self.release.set()
        if hasattr(self,'client'):await self.client.close()
        await super().close()


class Policy(unittest.TestCase):
    def test_real_binding_uses_existing_exact_consumed_approval_without_network(self):
        from tests.test_native_integration import configuration
        from app.collection.native_approval import validate_approval,digest
        from app.collection.venue_access import ENDPOINTS
        s=configuration();s['mode']='real'
        endpoints={**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'}
        s=configure(s,settings(),endpoints,prepare_approved=True)
        with tempfile.TemporaryDirectory() as root,patch('app.collection.native_approval.implementation',return_value={'mock-candidate':'digest'}):
            p=Path(root)/'approval.json'
            with self.assertRaises(ValueError):validate_approval(s,endpoints,None,root)
            p.write_text(json.dumps(dict(approved=True,spec_sha256=digest(s),implementation_sha256=digest({'mock-candidate':'digest'}),output=str(Path(root).resolve()))))
            validate_approval(s,endpoints,p,root)
            altered=deepcopy(s);altered['source_session']['http']['credits']+=1
            with self.assertRaises(ValueError):validate_approval(altered,endpoints,p,root)
            validate_approval(s,endpoints,p,root,consume=True)
            with self.assertRaises(ValueError):validate_approval(s,endpoints,p,root)

    def test_roles_bounds_unknown_semantics_and_saved_authority(self):
        for change in [dict(auto_start=True),dict(roles=dict(ROLES,pinnacle='aggregate_comparison')),dict(scopes=[dict(sport='MLB',markets=['h2h_1st_6_innings'],event_ids=[])]),dict(event_limit=13)]:
            with self.subTest(change=change),self.assertRaises((ValueError,TypeError)):validate(settings(**change))
        v=spec();v.update(mode='real',reference_enabled=False)
        with self.assertRaisesRegex(ValueError,'activation unavailable'):configure(v,settings(),{'aggregate':'http://127.0.0.1:1'})
        v['mode']='mock'
        with self.assertRaisesRegex(ValueError,'Fresh quota'):configure(v,settings(quota_observed_at='2020-01-01T00:00:00Z'),{'aggregate':'http://127.0.0.1:1'})
        with self.assertRaises(ValueError):configure(v,settings(),{'aggregate':'https://api.the-odds-api.com'})


class Integrated(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.f=UnifiedFixture();self.o=await self.f.boot(self.temp.name)
        self.no_credentials=patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credential access forbidden'));self.no_credentials.start()
    async def asyncTearDown(self):
        await self.f.close();self.no_credentials.stop();self.temp.cleanup()
    async def wait_aggregate(self,predicate=lambda s:bool(s.aggregates)):
        await self.f.wait(lambda:predicate(self.o.session.projection))
    async def test_start_mixed_independent_updates_details_watch_stop_exact_download_restart(self):
        from urllib.parse import urlencode
        await self.f.start_route();await self.f.native_images();await self.wait_aggregate()
        c=self.f.client
        d=await (await c.get('/api/dashboard?view=feed')).json()
        rows=d['comparisons'];self.assertTrue(any(not r.get('aggregated') for r in rows));a=next(r for r in rows if r.get('aggregated'))
        self.assertEqual({l['venue'] for r in rows for l in r['legs']} , {'novig','prophetx','kalshi','polymarket_us'})
        self.assertEqual(len(self.o.current_snapshot()['aggregate_coverage']),63)
        query=urlencode(dict(session=a['session'],hash=a['hash'],cutoff=a['cutoff']))
        response=await c.get('/api/calculate?'+query);detail=await response.json();self.assertEqual(response.status,200,detail)
        watch=dict(name='Aggregate raw',metric='raw_gap',threshold='0',quantity='100',filters={'venue':'novig+prophetx'})
        self.assertEqual((await c.post('/api/watchlists',json=[watch],headers=self.f.origin)).status,200)
        signal=await (await c.get('/api/signals')).json();self.assertFalse(any(i['active'] for i in signal['items']))
        old_native=self.o.session.projection.cursor
        await self.f.send(self.f.active()[0]);self.assertGreater(self.o.session.projection.cursor,old_native)
        before=self.o.current_snapshot()['aggregate_comparisons'][0]['raw_difference'];self.f.quote='2.5'
        await self.f.wait(lambda:self.o.current_snapshot()['aggregate_comparisons'][0]['raw_difference']!=before)
        self.assertEqual(next(r for r in comparisons(self.o.current_snapshot(),{}) if r.get('aggregated') and r['outcome']==a['outcome'])['id'],a['id'])
        await self.f.stop_route();self.assertIsNone(self.o.error)
        reopened=await (await c.get('/api/calculate?'+query)).json();self.assertEqual(detail,reopened)
        sid=self.o.session.sid
        report=await (await c.get('/api/opportunity-history?capture='+sid)).json()
        download=await (await c.get('/api/opportunity-history?capture='+sid+'&download=true')).json();self.assertEqual(report,download)
        saved=load(self.o.session.output);self.assertEqual(len(saved['aggregate_coverage']),63)
        for ref in saved['references']:self.assertIn(ref['origin_id'],('pinnacle','draftkings','betmgm'))
        calls=len(self.f.odds_calls);await asyncio.sleep(.05);self.assertEqual(calls,len(self.f.odds_calls))
        restart=CoverageOwner(Path(self.temp.name)/'unused',pilot_output=Path(self.temp.name)/'sessions',endpoints=self.f.endpoints,product_mode=True,spec_factory=self.o.spec_factory)
        self.assertFalse(restart.active());self.assertIsNone(restart.session);self.assertEqual(saved,load(self.o.session.output))
        self.assertEqual(sum(path.endswith('/odds') for path,q in self.f.odds_calls)*3,self.f.used)
        self.assertTrue(all('bookmakers' not in q or q['bookmakers']=='novig,prophetx,pinnacle,draftkings,betmgm' for _,q in self.f.odds_calls))
    async def test_missing_removed_failure_recovery_and_stale(self):
        await self.f.start_route();await self.f.native_images();await self.wait_aggregate()
        self.f.missing=True
        await self.f.wait(lambda:not self.o.current_snapshot()['aggregate_comparisons'])
        self.assertTrue(self.o.current_snapshot()['references'])
        self.f.missing=False
        await self.f.wait(lambda:bool(self.o.current_snapshot()['aggregate_comparisons']))
        self.f.error=True
        await self.f.wait(lambda:self.o.session.aggregate.health=='unavailable')
        self.assertEqual(self.o.session.state,'running');self.assertTrue(self.o.current_snapshot()['games'])
        self.f.error=False
        await self.f.wait(lambda:self.o.session.aggregate.health=='waiting')
        self.f.empty=True
        await self.f.wait(lambda:not self.o.session.projection.aggregates)
        self.assertTrue(any(not g.get('aggregated') for g in self.o.current_snapshot()['games']))
        self.assertEqual(len(self.o.current_snapshot()['aggregate_coverage']),63)
        await self.f.stop_route();self.assertIsNone(self.o.error)
    async def test_quota_exhaustion_does_not_stop_native(self):
        cfg=settings();cfg['http']['requests']=2
        await self.f.start_route(cfg);await self.f.native_images();await self.wait_aggregate()
        await self.f.wait(lambda:self.o.session.aggregate.health=='unavailable')
        self.assertEqual(self.o.session.state,'running');self.assertEqual(len(self.f.odds_calls),2)
        await self.f.send(self.f.active()[0]);await self.f.stop_route();self.assertIsNone(self.o.error)
    async def test_stop_during_discovery(self):await self.stop_block('discovery')
    async def test_stop_during_response(self):await self.stop_block('response')
    async def stop_block(self,phase):
        self.f.block=phase;await self.f.start_route();await asyncio.wait_for(self.f.entered.wait(),5)
        await asyncio.wait_for(self.f.stop_route(),3)
        self.assertIsNone(self.o.error);self.assertFalse(self.o.session.projection.aggregates)
        rows=reopen(self.o.session.journal.path)['rows']
        self.assertTrue(any(r.get('reason')=='incomplete_capture_cancelled' for r in rows))
        self.assertTrue(self.o.session.cleanup_complete)
    async def test_interrupted_persistence_preserves_prior_and_fails_closed(self):
        await self.f.start_route();await self.f.native_images();await self.wait_aggregate()
        original=self.o.session.journal.save
        def fail(row):
            if row['type']=='aggregate_snapshot':raise OSError('SIMULATED persistence interruption')
            original(row)
        self.o.session.journal.save=fail
        await self.f.wait(lambda:self.o.session.stop_event.is_set())
        await self.o.finalizer
        self.assertIsNotNone(self.o.error);self.assertTrue(self.o.session.journal.path.exists())
        with self.assertRaises(ValueError):load(self.o.session.output)
        from app.collection.recovery import index,reopen_index
        before=self.o.session.journal.path.read_bytes()
        destination=self.o.session.output/'recovery-index.json'
        report=index(self.o.session.journal.path,destination)
        _,saved=reopen_index(destination)
        self.assertEqual(before,self.o.session.journal.path.read_bytes())
        self.assertTrue(project_rows(saved['rows'])['aggregate_comparisons'])
        self.assertEqual(report['status'],'interrupted')
        response=await self.f.client.get('/api/recovery?capture='+self.o.session.sid+'&download=true')
        downloaded=await response.json();self.assertEqual(response.status,200,downloaded)
        self.assertFalse(downloaded['collection_authorized']);self.assertEqual(downloaded['snapshot']['state'],'incomplete')
        self.assertEqual(downloaded['snapshot']['durable_cursor'],project_rows(saved['rows'])['durable_cursor'])

    async def test_bad_event_does_not_block_other_event_or_native_finalization(self):
        self.f.extra_bad_event=True
        await self.f.start_route();await self.f.native_images();await self.wait_aggregate()
        self.assertTrue(self.o.current_snapshot()['aggregate_comparisons'])
        self.assertTrue(self.o.session.aggregate.failures)
        self.f.malformed=True
        await self.f.wait(lambda:len(self.f.odds_calls)>=6)
        await self.f.stop_route();self.assertIsNone(self.o.error)
        self.assertTrue(load(self.o.session.output)['aggregate_comparisons'])

    async def test_native_selection_never_blocks_provider_scoped_comparisons(self):
        cfg=settings(native_selection={v:dict(event_ids=['not-selected'],market_ids=[]) for v in ('kalshi','polymarket_us')})
        await self.f.start_route(cfg);await self.wait_aggregate()
        await self.f.wait(lambda:self.o.session.discovery.completed)
        self.assertFalse(self.f.active());self.assertTrue(self.o.current_snapshot()['aggregate_comparisons'])
        self.assertTrue(any(m.get('reason')=='Outside explicit source-session selection' for m in self.o.current_snapshot()['market_catalog']))
        await self.f.stop_route();self.assertIsNone(self.o.error)

    async def test_stop_at_processing_boundary(self):
        from app.collection.source_session import bind as original
        def stop_after_normalization(rows):
            result=original(rows);self.o.session.request_stop('SIMULATED stop during processing');return result
        with patch('app.collection.source_session.bind',side_effect=stop_after_normalization):
            await self.f.start_route();await self.o.session.task;await self.o.finalizer
        self.assertFalse(self.o.session.projection.aggregates);self.assertIsNone(self.o.error)
        self.assertTrue(any(r['type']=='aggregate_http' and r['complete'] for r in reopen(self.o.session.journal.path)['rows']))
    async def test_stop_during_refresh_keeps_previous_snapshot(self):
        await self.f.start_route();await self.wait_aggregate()
        originals=deepcopy(self.o.session.projection.aggregates)
        self.f.block='discovery';await asyncio.wait_for(self.f.entered.wait(),5)
        await asyncio.wait_for(self.f.stop_route(),3)
        self.assertEqual(self.o.session.projection.aggregates,originals);self.assertIsNone(self.o.error)
    async def test_native_disconnect_does_not_block_aggregate(self):
        await self.f.start_route();await self.f.native_images();await self.wait_aggregate()
        connection=self.f.active()[0];await connection['socket'].close()
        self.f.quote='2.6'
        await self.f.wait(lambda:any(r['original']['decimal_odds']=='2.6' for r in self.o.session.projection.aggregates.values()))
        self.assertEqual(self.o.session.state,'running')
        await self.f.wait(lambda:len(self.f.connections)>2)
        new=next(c for c in self.f.active() if c['venue']==connection['venue'])
        await self.f.send(new)
        self.assertTrue(self.o.session.projection.books)
        await self.f.stop_route();self.assertIsNone(self.o.error)


class Projection(unittest.TestCase):
    def test_unknown_timestamp_is_unavailable_without_blocking_other_prices(self):
        p=self.projection();body=self.body();body['bookmakers'][0]['markets'][0]['last_update']=None
        self.apply(p,body)
        view=p.snapshot(mode='current',now='2026-09-29T12:00:01Z')
        self.assertTrue(view['aggregate_comparisons'])
        self.assertTrue(any(l['source_age_seconds'] is None for r in view['aggregate_comparisons'] for l in r['legs']))


    def projection(self):
        from app.dashboard.session_projection import SessionProjection
        p=SessionProjection();p.apply(dict(type='session_started',session_id='SIMULATED',observed_at='2026-09-29T12:00:00+00:00',spec=dict(mode='mock',source_session=settings())))
        return p
    def apply(self,p,body,at='2026-09-29T12:00:00+00:00'):
        from app.reference.aggregate import bind,VERSION as MAPPING
        from app.reference.odds_bindings import normalize_event
        raw=json.dumps(body).encode();records=bind(normalize_event(raw,'NFL',at))
        row=dict(type='aggregate_snapshot',session_id=p.sid,observed_at=at,version=MAPPING,sport='NFL',event_id=body['id'],records=records,response_sha256=sha256(raw).hexdigest(),received_at=at,processing_at=at)
        p.apply(row);return row
    def body(self):
        f=UnifiedFixture();f.schedule='2026-10-01T12:00:00Z';body=f.body()
        for b in body['bookmakers']:
            for m in b['markets']:m['last_update']='2026-09-29T12:00:00Z'
        return body
    def test_duplicate_changed_line_removed_event_stale_and_prefix(self):
        p=self.projection();body=self.body();row=self.apply(p,body)
        first=p.snapshot(mode='saved');count=len(p.aggregates)
        p.apply(row);self.assertEqual(len(p.aggregates),count)
        self.assertEqual([r['id'] for r in comparisons(first,{})],[r['id'] for r in comparisons(p.snapshot(),{})])
        live=p.snapshot(mode='current',now='2026-09-29T12:00:05Z')
        self.assertTrue(all(l['status']=='stale or source time unknown' for r in live['aggregate_comparisons'] for l in r['legs']))
        for b in body['bookmakers']:
            b['markets'][0]['key']='spreads'
            for o in b['markets'][0]['outcomes']:o['point']=3.5
        self.apply(p,body);self.assertTrue(all(r['identity']['line']=='3.5' for r in p.snapshot()['aggregate_comparisons']))
        for b in body['bookmakers']:
            for o in b['markets'][0]['outcomes']:o['point']=4.5
        self.apply(p,body);self.assertTrue(all(r['identity']['line']=='4.5' for r in p.snapshot()['aggregate_comparisons']))
        self.assertEqual(len(p.aggregates),count)
        p.apply(dict(type='aggregate_inventory',session_id=p.sid,observed_at='2026-09-29T12:00:05Z',sport='NFL',event_ids=[]))
        self.assertFalse(p.aggregates);self.assertFalse(p.snapshot()['aggregate_comparisons']);self.assertEqual(len(p.snapshot()['aggregate_coverage']),63)
    def test_retained_actual_timestamps_never_rebased(self):
        from app.dashboard.session_history import verified
        from tests.test_aggregate_ingestion import FOLDER
        original=next(r for r in verified(FOLDER)['rows'] if r['type']=='product_aggregate' and r['sport']=='NFL')
        p=self.projection()
        events={r['original']['source_event_id'] for r in original['records']}
        for event in events:
            records=[r for r in original['records'] if r['original']['source_event_id']==event]
            p.apply(dict(type='aggregate_snapshot',session_id=p.sid,observed_at='2026-09-29T12:00:00Z',version=original['version'],sport='NFL',event_id=event,records=records,response_sha256=original['response_sha256']))
        actual={r['id']:r for r in original['records']}
        self.assertEqual(p.aggregates,actual)
        self.assertTrue(all(c['raw_difference'] is not None for c in p.snapshot()['aggregate_comparisons']))
        self.assertEqual(len(p.snapshot()['aggregate_coverage']),63)

if __name__=='__main__':unittest.main()
