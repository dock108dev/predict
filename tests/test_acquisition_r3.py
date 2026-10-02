"""Offline r3 regressions. Synthetic pages never establish a complete live catalog."""
import asyncio
import base64
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from contextlib import redirect_stdout, redirect_stderr
import zipfile
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.acquisition_policy import NATIVE_V2, native_caps
from app.collection.continuous import REST, Discovery
from app.collection.prediction_producer import PredictionBudget
from app.collection.odds_http import BudgetStop
from app.collection.transport_session import reopen
from app.collection.coverage import traversal
from app.dashboard.session_history import load, project_rows
from app.dashboard.session_projection import SessionProjection
from tests.test_acquisition_r2 import Fixture as R2Fixture

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'evidence/integrated-acquisition-r3-20260930'
LIVE=ROOT/'evidence/integrated-source-r2-attempt-b7fe3d0c-afee-4101-966b-7294bc9a4fb8/84986f25-77fe-4f27-b72f-9b5d7723adab'
def configuration():return json.loads((PACKAGE/'run-spec.json').read_text())
def live_rows():return reopen(next(LIVE.glob('*.jsonl')))['rows']
def page(venue, rows, position=0, cursor='', complete=True):
    body=json.dumps(dict(events=rows, cursor=cursor)).encode()
    return dict(source=venue,acquisition_discovery_policy=NATIVE_V2,status=200,complete=complete,
        path='/v1/events' if venue=='polymarket_us' else '/trade-api/v2/events',
        params=dict(limit=2,**({'offset':position} if venue=='polymarket_us' else {'cursor':position or ''})),
        body_b64=base64.b64encode(body).decode(),body_sha256=sha256(body).hexdigest())

class Fixture(R2Fixture):
    async def boot(self,path):
        owner=await super().boot(path)
        def factory():s=configuration();s['mode']='mock';return s
        owner.spec_factory=factory;self.us_calls=0
        return owner
    async def start(self,duration=30,fast=True):
        cfg=configuration()['source_session']
        if fast:cfg['refresh_seconds']=1
        res=await self.client.post('/api/start',json=dict(duration=duration,source_settings=cfg),headers=self.origin)
        assert res.status==200,await res.text()
        save=self.owner.session.journal.save
        def observed(row):save(row);self.books+=row['type']=='prediction_book';self.changed.set()
        self.owner.session.journal.save=observed
    async def rest(self,req):
        if req.path=='/v1/events' and self.fault in ('oversized','chunked'):
            self.us_calls+=1
            raw=base64.b64decode(next(r for r in live_rows() if r['type']=='prediction_discovery_http')['body_b64'])
            # Original truncation plus explicit synthetic excess: never repaired JSON.
            raw+=b'SIMULATED excess beyond retained truncation'
            if self.fault=='oversized':return web.Response(body=raw)
            response=web.StreamResponse();await response.prepare(req)
            try:
                for i in range(0,len(raw),4096):await response.write(raw[i:i+4096])
                await response.write_eof()
            except ConnectionResetError:pass
            return response
        return await super().rest(req)

class Retained(unittest.TestCase):
    def test_partial_never_admitted_and_old_reopening_unchanged(self):
        rows=live_rows();p=next(r for r in rows if r['type']=='prediction_discovery_http')
        accepted,state=traversal([p],'polymarket_us','events')
        self.assertFalse(accepted);self.assertEqual(state['state'],'failed')
        projection=SessionProjection()
        for row in rows:projection.apply(row)
        saved=load(LIVE)
        self.assertEqual(projection.snapshot(mode='saved'),project_rows(rows,saved['durable_cursor']))
        self.assertEqual(len(saved['aggregate_coverage']),63)

    def test_all_retained_bindings_and_roles(self):
        from app.reference.aggregate import bind
        from app.normalization.college_registry import aggregate_registry
        counts={}
        for row in live_rows():
            if row['type']!='aggregate_snapshot':continue
            bound=bind([r['original'] for r in row['records']]);counts[row['sport']]=len(bound)
            self.assertTrue(all(not r['reasons'] for r in bound))
            self.assertTrue(all(not r['mapping_notes'] for r in bound))
            self.assertTrue(all(r['original']['fees'] is None and r['original']['settlement'] is None for r in bound))
            if row['sport']=='NBA':self.assertTrue(all(r['role']=='bookmaker_reference' for r in bound))
        self.assertEqual(counts,dict(NFL=54,NCAAF=46,NBA=18))
        reg=aggregate_registry()
        self.assertEqual(reg.resolve('team','New Mexico State Aggies',league='NCAAF',venue='kalshi').status,'unknown')
        self.assertEqual(reg.resolve('team','New Mexico State Aggies',league='NCAAB',venue='the_odds_api').status,'unknown')
        self.assertEqual(reg.resolve('team','Aggies',league='NCAAF',venue='the_odds_api').status,'unknown')

    def test_partial_duplicate_and_cursor_traversals(self):
        first=page('polymarket_us',[dict(id='a'),dict(id='b')])
        accepted,state=traversal([first],'polymarket_us','events')
        self.assertEqual((len(accepted),state['state']),(1,'bounded/truncated'))
        for second in (page('polymarket_us',[dict(id='a'),dict(id='b')],2),first,
                       page('polymarket_us',[],2,complete=False)):
            accepted,state=traversal([first,second],'polymarket_us','events')
            self.assertEqual((len(accepted),state['state']),(1,'failed'))
        accepted,state=traversal([first,page('polymarket_us',[],2)],'polymarket_us','events')
        self.assertEqual(state['state'],'exhausted')
        pages=[page('kalshi',[dict(event_ticker='a')],cursor='next'),page('kalshi',[dict(event_ticker='b')],'next','next')]
        accepted,state=traversal(pages,'kalshi','events')
        self.assertEqual((len(accepted),state['state']),(1,'failed'))

class Credential(unittest.TestCase):
    def test_dummy_save_reuse_permissions_preservation_archive_and_no_logging(self):
        from app.collection.credential_handoff import handoff,candidate_files
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);subprocess.run(['git','init','-q',tmp],check=True)
            (root/'.gitignore').write_text('.env\n.env.*\n')
            (root/'.env').write_text('OTHER=value\n# keep comment\n')
            (root/'.env').chmod(0o644)
            log=io.StringIO()
            with redirect_stdout(log),redirect_stderr(log):
                self.assertEqual(handoff(root,'DUMMY_ONLY_123'),'DUMMY_ONLY_123')
                self.assertEqual(handoff(root),'DUMMY_ONLY_123')
            self.assertNotIn('DUMMY',log.getvalue())
            self.assertEqual((root/'.env').stat().st_mode&0o777,0o600)
            self.assertEqual((root/'.env').read_text(),'OTHER=value\n# keep comment\nODDS_API_KEY=DUMMY_ONLY_123\n')
            (root/'app').mkdir();(root/'app'/'ok.py').write_text('# public\n')
            (root/'app'/'.env.json').write_text('DUMMY_ONLY_123')
            files=list(candidate_files(root));self.assertEqual(files,[root/'app'/'ok.py'])
            with zipfile.ZipFile(root/'source.zip','w') as archive:
                for f in files:archive.write(f,f.relative_to(root))
            with zipfile.ZipFile(root/'source.zip') as archive:
                self.assertEqual(archive.namelist(),['app/ok.py'])
            self.assertFalse(list(root.glob('.env.*')))
            original=(root/'.env').read_bytes()
            with self.assertRaises(ValueError):handoff(root,'bad\nINJECTION=value')
            self.assertEqual((root/'.env').read_bytes(),original)
            (root/'.env').write_text('ODDS_API_KEY=DUMMY_A\nODDS_API_KEY=DUMMY_B\n')
            with self.assertRaises(ValueError):handoff(root)

class Runtime(unittest.IsolatedAsyncioTestCase):
    async def test_source_failure_peers_continue_no_retry_and_reopen(self):
        for fault in ('oversized','chunked'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
                f=Fixture(fault);o=await f.boot(tmp)
                try:
                    await f.start();await f.wait(lambda:o.session.aggregate.health=='completed')
                    await f.wait(lambda:o.session.discovery.completed)
                    self.assertEqual(f.us_calls,1);self.assertEqual(len(f.odds_calls),37)
                    self.assertFalse(o.session.stop_event.is_set())
                    self.assertEqual(len(o.session.discovery.inventory['kalshi']['acquisition_scope']['sports']),6)
                    self.assertEqual(o.session.discovery.inventory['polymarket_us']['selection']['ids'],[])
                    self.assertEqual(o.session.discovery.source_stops['polymarket_us'],'prediction_discovery_byte_cap')
                    self.assertGreater(o.session.producers['kalshi'].budget.requests,0)
                    await f.wait(lambda:len(f.active())==1)
                    await f.images()
                    self.assertTrue(any(k[0]=='kalshi' for k in o.session.projection.books))
                    await o.session.discovery.discover(force=True)
                    self.assertEqual(f.us_calls,1)
                    await f.stop_route();self.assertTrue(o.session.cleanup_complete)
                    rows=reopen(o.session.journal.path)['rows'];snapshot=load(o.session.output)
                    self.assertEqual(snapshot,project_rows(rows,snapshot['durable_cursor']))
                    self.assertEqual(len(snapshot['aggregate_coverage']),63)
                    self.assertTrue(any(r['type']=='native_source_stopped' for r in rows))
                finally:await f.close()

    async def test_pagination_bound_and_duplicate_no_fallback(self):
        s=SimpleNamespace(spec=configuration(),producers={},emit=Mock())
        discovery=Discovery(s);seen=[]
        async def get(url,params):
            seen.append(params)
            offset=params['offset']
            return SimpleNamespace(status_code=200,json=lambda:dict(events=[dict(id=str(offset)),dict(id=str(offset+1))]))
        discovery.clients['polymarket_us']=SimpleNamespace(get=get)
        rows=await discovery.pages_for('polymarket_us','/v1/events',{},'events',2)
        self.assertEqual((len(seen),len(rows),seen[-1]['offset']),(75,150,148))
        self.assertEqual(native_caps(s.spec)['polymarket_us'],486)
        async def repeated(url,params):return SimpleNamespace(status_code=200,json=lambda:dict(events=[dict(id='a'),dict(id='b')]))
        discovery.clients['polymarket_us'].get=repeated
        with self.assertRaisesRegex(ValueError,'duplicate'):await discovery.pages_for('polymarket_us','/v1/events',{},'events',2)
        self.assertIn('polymarket_us',discovery.source_stops)

    async def test_global_failure_remains_global(self):
        session=SimpleNamespace(spec=configuration(),discovery=SimpleNamespace(stop_source=Mock()),request_stop=Mock())
        client=REST('http://127.0.0.1:9',configuration()['prediction'],lambda r:None,1,PredictionBudget(configuration()['prediction']))
        client.session=session;client.source_venue='polymarket_us'
        for reason in ('journal_byte_cap','rss_cap','disk_floor','catalog_response_not_retained'):
            client.fail_budget(reason)
        self.assertEqual(session.request_stop.call_count,4);session.discovery.stop_source.assert_not_called()

    async def test_global_memory_stop_during_healthy_peer_work(self):
        from app.collection.continuous import LIMITS
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture('oversized');o=await f.boot(tmp)
            try:
                await f.start();await f.wait(lambda:bool(o.session.projection.aggregates))
                with patch('app.collection.continuous.rss',return_value=LIMITS['rss_bytes']):
                    with self.assertRaisesRegex(BudgetStop,'rss_cap'):
                        o.session.emit('session',dict(type='SIMULATED global memory pressure'))
                await o.finalizer
                self.assertEqual(o.session.reason,'rss_cap')
                self.assertTrue(o.session.cleanup_complete)
                before=len(f.odds_calls);await asyncio.sleep(.05)
                self.assertEqual(len(f.odds_calls),before)
                self.assertEqual(load(o.session.output)['state'],'saved')
            finally:await f.close()

    async def test_source_request_exhaustion_never_dispatches(self):
        limits=configuration()['prediction'];budget=PredictionBudget(limits);budget.requests=486
        client=REST('http://127.0.0.1:9',limits,lambda r:None,1,budget)
        client.source_venue='polymarket_us';client.request_ceiling=486
        client.session=SimpleNamespace(spec=configuration(),discovery=SimpleNamespace(stop_source=Mock()),request_stop=Mock())
        with patch('aiohttp.ClientSession',side_effect=AssertionError('No excess dispatch')):
            with self.assertRaises(BudgetStop):await client.get('http://127.0.0.1:9/events')
        client.session.discovery.stop_source.assert_called_once()
        client.session.request_stop.assert_not_called()

    async def test_cancelled_chunked_capture_retains_prefix(self):
        entered=asyncio.Event();release=asyncio.Event();receipts=[]
        async def serve(req):
            response=web.StreamResponse();await response.prepare(req);await response.write(b'{"events":[');entered.set()
            await release.wait();return response
        app=web.Application();app.router.add_get('/events',serve);server=TestServer(app);await server.start_server()
        limits=configuration()['prediction'];client=REST(str(server.make_url('/')).rstrip('/'),limits,receipts.append,5,PredictionBudget(limits))
        task=asyncio.create_task(client.get(str(server.make_url('/events'))))
        try:
            await entered.wait();await asyncio.sleep(.01);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertEqual(len(receipts),1);self.assertFalse(receipts[0]['complete'])
            self.assertEqual(client.budget.requests,1)
        finally:release.set();await client.aclose();await server.close()


class ExactBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_exact_chunked_limit_is_complete_and_excess_is_rejected_once(self):
        for excess in (False,True):
            receipts=[]
            async def serve(req):
                response=web.StreamResponse();await response.prepare(req)
                await response.write(b'x'*128);await asyncio.sleep(.01)
                if excess:await response.write(b'y')
                await response.write_eof();return response
            app=web.Application();app.router.add_get('/events',serve);server=TestServer(app);await server.start_server()
            limits={**configuration()['prediction'],'frame_bytes':128}
            client=REST(str(server.make_url('/')).rstrip('/'),limits,receipts.append,5,PredictionBudget(limits));client.strict_eof=True
            try:
                if excess:
                    with self.assertRaises(BudgetStop):await client.get(str(server.make_url('/events')))
                else:await client.get(str(server.make_url('/events')))
                self.assertEqual(receipts[0]['complete'],not excess)
                self.assertEqual(client.budget.requests,1)
                self.assertEqual(client.budget.bytes,129 if excess else 128)
            finally:await client.aclose();await server.close()
