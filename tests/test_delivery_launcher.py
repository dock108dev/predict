"""Bounded launcher mocks. Temporary outputs only; no retained evidence writers."""
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import signal
import tempfile
import time
import unittest
from unittest.mock import patch

from app.collection.delivery_manifest import (SCHEMA, PRODUCTION_ROOT, digest, specification,
    executable_manifest, verify, validate_spec, validate_approval, read_json, validate_session_spec)
from app.collection.delivery_live import Launcher, Attempt, WorkerControl, load_kalshi, serve, socket_path, write_once
from app.collection.delivery_watchdog import Deadlines, watch, terminate
from app.collection.delivery_capture import (Session, KalshiTransport, HTTP, BASE, canonical, choose)
from app.collection.delivery_analysis import analyze_rows, restored
from app.collection.delivery_budget import CAP, Clock, Records
from app.collection.segmented import SegmentedReader
from app.collection.venue_access import Credential, ENDPOINTS
from app.models.core import EvidenceKind
from tests.delivery_launcher_fixture import fake_data, FixtureTransport, JumpClock, blocked_worker, orphan_supervisor
from tests.delivery_launcher_audit import audit, qualification, fixture_audit
from tests import test_delivery_capture as native
from tests.delivery_fixture import MID, acknowledgement, snapshot
from uuid import uuid4


def inputs(root,**changes):
    spec=specification(root/'attempt',str(uuid4()),ownership=root/'locks',**changes)
    manifest=executable_manifest(spec)
    approval=dict(schema=SCHEMA,approved=True,scope=spec['mode'],candidate=manifest['sha256'],
                  spec=digest(spec),attempt=spec['attempt'],authorization='Synthetic bounded test only')
    return spec,manifest,approval


async def until(predicate,seconds=15):
    async with asyncio.timeout(seconds):
        while not predicate():await asyncio.sleep(.02)


class Contracts(unittest.TestCase):
    def test_fixture_observations_bounded(self):
        from tests.delivery_launcher_fixture import Runtime
        runtime=Runtime({}, {})
        for _ in range(98):runtime.observe(dict(event='http'))
        with self.assertRaises(ValueError):runtime.observe(dict(event='http'))
        runtime.observations=[]
        with self.assertRaises(ValueError):runtime.observe(dict(path='x'*32768))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.spec,self.manifest,self.approval=inputs(self.root)

    def test_manifest_roundtrip_and_source_runtime_execution_binding(self):
        path=self.root/'candidate.json';write_once(path,self.manifest)
        self.assertEqual(verify(read_json(path),self.spec),self.manifest['sha256'])
        for field in ('runtime','files','head','tracked_diff_sha256','untracked','profiles','execution','roles'):
            bad=deepcopy(self.manifest);bad['payload'][field]=None
            with self.subTest(field=field),self.assertRaises(ValueError):Launcher(bad,self.spec)

    def test_invalid_spec_has_no_files_or_credential_calls(self):
        from keyring.backends.macOS import Keyring
        with patch.object(Keyring,'get_password',side_effect=AssertionError('secret')) as loader:
            for field,value in [('duration',301),('direct_stop',1),('endpoints',{}),('credential_reference','US'),('subcaps',{})]:
                bad=deepcopy(self.spec);bad[field]=value
                with self.subTest(field=field),self.assertRaises(ValueError):Launcher(self.manifest,bad)
            self.assertFalse(list(self.root.iterdir()));loader.assert_not_called()

    def test_production_root_and_injection_guards(self):
        real=specification(self.root/'real',str(uuid4()),mode='real')
        validate_spec(real)
        wrong=deepcopy(real);wrong['ownership']=str(self.root/'other')
        with self.assertRaises(ValueError):validate_spec(wrong)
        with self.assertRaises(ValueError):Launcher(executable_manifest(real),real,fixture_options={})
        offline=specification(self.root/'x',str(uuid4()),ownership=PRODUCTION_ROOT)
        with self.assertRaises(ValueError):validate_spec(offline)

    def test_explicit_approval_binding(self):
        for field,value in [('approved',False),('candidate','x'),('spec','x'),('attempt',str(uuid4())),('scope','real')]:
            bad=dict(self.approval,**{field:value})
            with self.subTest(field=field),self.assertRaises(ValueError):validate_approval(bad,self.manifest,self.spec)

    def test_generated_session_spec_is_explicitly_bound(self):
        actual=dict(schema='kalshi-delivery-diagnostic-v1',mode='synthetic',duration=300,direct_stop=240,
                    slots=self.spec['slots'],frozen=self.spec['frozen'],subcaps=self.spec['subcaps'])
        validate_session_spec(actual,self.spec)
        for field,value in [('mode','real'),('slots',[]),('duration',301),('direct_stop',239),('subcaps',{})]:
            with self.subTest(field=field),self.assertRaises(ValueError):validate_session_spec(dict(actual,**{field:value}),self.spec)

    def test_worker_rechecks_before_secret(self):
        from app.collection.delivery_live import worker
        a=Attempt(self.spec,self.manifest,self.approval,Clock().anchor());a.acquire();self.addCleanup(a.release)
        messages=[]
        class FD:
            def detach(self):return os.dup(a.lock.fileno())
        class Pipe:
            def poll(self,*args):return True
            def recv(self):return {'action':'armed'}
            def send(self,value):messages.append(value)
            def close(self):pass
        with (patch('app.collection.delivery_live.verify',side_effect=ValueError('candidate_changed')),
              patch('app.collection.delivery_live.load_kalshi',side_effect=AssertionError('credentials')) as loader):
            with self.assertRaises(SystemExit):worker(self.spec,self.manifest,self.approval,Pipe(),Clock().anchor(),FD())
            loader.assert_not_called()
        self.assertEqual([r['event'] for r in messages],['worker_failed']);self.assertTrue(a.marker.exists())

    def test_lock_consumed_marker_changed_output_and_failure(self):
        a=Attempt(self.spec,self.manifest,self.approval,Clock().anchor());a.acquire();self.addCleanup(a.release)
        bound=read_json(a.marker)
        self.assertEqual((bound['candidate'],bound['spec'],bound['output']),
                         (self.manifest['sha256'],digest(self.spec),self.spec['output']))
        other=deepcopy(self.spec);other.update(attempt=str(uuid4()),output=str(self.root/'other'))
        b=Attempt(other,self.manifest,self.approval,Clock().anchor())
        with self.assertRaises(BlockingIOError):b.acquire()
        a.release()
        changed=dict(self.spec,output=str(self.root/'changed'))
        with self.assertRaises(FileExistsError):Attempt(changed,self.manifest,self.approval,Clock().anchor()).acquire()
        self.assertEqual(read_json(a.marker),bound)

    def test_resource_failed_start_consumed_and_sanitized(self):
        a=Attempt(self.spec,self.manifest,self.approval,Clock().anchor())
        with patch('app.collection.delivery_live.rss',return_value=192*1024**2),self.assertRaises(ValueError):a.acquire()
        a.failed_start();self.assertTrue(a.marker.exists());self.assertIsNone(a.lock)
        self.assertEqual(read_json(a.root/(self.spec['attempt']+'.failure.json'))['phase'],'start_failed')

    def test_existing_output_is_not_modified_on_failed_start(self):
        output=Path(self.spec['output']);output.mkdir();(output/'keep').write_bytes(b'preserve')
        a=Attempt(self.spec,self.manifest,self.approval,Clock().anchor())
        with self.assertRaises(FileExistsError):a.acquire()
        a.failed_start();self.assertEqual(list(output.iterdir()),[output/'keep'])
        self.assertEqual((output/'keep').read_bytes(),b'preserve');self.assertTrue(a.marker.exists())

    def test_helper_and_failed_start_writes_independently_counted(self):
        from tests.test_finalization_resources import Writes
        writes=Writes();a=Attempt(self.spec,self.manifest,self.approval,Clock().anchor())
        with patch.object(Path,'open',lambda p,*args,**kw:writes(p,*args,**kw)):
            a.acquire();a.helper('candidate.json',self.manifest);a.failed_start();a.release()
        report=read_json(a.root/(self.spec['attempt']+'.failure.json'))
        self.assertEqual(report['helper_write_bytes'],writes.bytes)
        with self.assertRaises(ValueError):a.helper('oversize.json',{},size=CAP['helper_bytes'])

    def test_kalshi_loader_exact_lookup_and_sanitized_failure(self):
        from keyring.backends.macOS import Keyring
        data=fake_data()
        with patch.object(Keyring,'get_password',return_value=json.dumps(data)) as mock:
            credential=load_kalshi();self.assertEqual(credential.venue,'kalshi')
            mock.assert_called_once_with('prediction-arb.kalshi.production','market-data')
        for value in (None,'{}','{"key_id":"US","secret_key":"SECRET"}'):
            with patch.object(Keyring,'get_password',return_value=value),self.assertRaisesRegex(ValueError,'^kalshi_credential_unavailable$'):load_kalshi()

    def test_native_signing_exact_path_without_query(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        import base64
        credential=Credential('kalshi',fake_data());path=BASE+'/markets/A%2FB/orderbook'
        headers=credential.headers(path)
        message=(headers['KALSHI-ACCESS-TIMESTAMP']+'GET'+path).encode()
        credential.signer._key.public_key().verify(base64.b64decode(headers['KALSHI-ACCESS-SIGNATURE']),message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())
        t=KalshiTransport(credential)
        self.assertEqual(t.http_url(path,{'depth':20}),ENDPOINTS['kalshi']['rest']+path)
        for wrong,params in [(BASE+'/trades',{}),(path,{'depth':0}),(BASE+'/markets/A/B/orderbook',{'depth':20}),
                (BASE+'/events',{'series_ticker':'KXNFLGAME','status':'closed','with_milestones':'true','limit':200,'cursor':''})]:
            with self.subTest(path=wrong,params=params),self.assertRaises(ValueError):t.http_url(wrong,params)
        t.endpoints={'rest':'https://wrong.invalid','ws':ENDPOINTS['kalshi']['ws']}
        with self.assertRaises(ValueError):t.ws_url()

    def test_deadline_boundaries_unchanged(self):
        d=Deadlines(100)
        self.assertIsNone(d.action(339.999));self.assertEqual(d.action(340),'direct_stop')
        d.stop_sent=True;self.assertIsNone(d.action(399.999));self.assertEqual(d.action(400),'independent_cutoff')
        d.closed=341;self.assertIsNone(d.action(640.999));self.assertEqual(d.action(641),'finalization_cutoff')
        self.assertEqual(d.action(760),'outer_cutoff')


class IdentityAndProvenance(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.case=native.Native(methodName='runTest');await self.case.asyncSetUp()
    async def asyncTearDown(self):await self.case.asyncTearDown()

    async def test_reference_begin_end_identity_matrix(self):
        c=self.case;await c.sample();c.finish()
        original=list(SegmentedReader(c.out/'history').rows())
        changes=[('http_begin','path',BASE+'/markets/OTHER/orderbook'),('http_begin','params',{'depth':19}),
            ('http_begin','params',{'depth':20,'extra':1}),('http_begin','primary_id','wrong'),
            ('http_begin','primary_state',{}),('http_end','path',BASE+'/markets/OTHER/orderbook'),
            ('http_end','params',{'depth':0}),('http_end','request_id','wrong')]
        for kind,field,value in changes:
            rows=deepcopy(original)
            row=next(x for x in rows if x['type']==kind and x.get('kind')=='reference');row[field]=value
            with self.subTest(kind=kind,field=field),self.assertRaises(ValueError):analyze_rows(rows)

    async def test_url_quoted_ticker_guard(self):
        c=self.case;c.s.mid='A/B ?#'
        from urllib.parse import quote
        path=BASE+'/markets/'+quote(c.s.mid,safe='')+'/orderbook'
        self.assertTrue(c.s.http.allowed(path,{'depth':20},'reference'))
        self.assertFalse(c.s.http.allowed(BASE+'/markets/'+c.s.mid+'/orderbook',{'depth':20},'reference'))
        # Analyzer accepts the exact encoded request binding independently of body ticker.
        await c.sample();c.finish()
        rows=list(SegmentedReader(c.out/'history').rows())
        selection=next(r for r in rows if r['type']=='selection')
        market=restored(selection['market']);raw=market.raw
        data=json.loads(raw.json_text);data['markets'][0]['ticker']=c.s.mid
        market=replace(market,raw=replace(raw,ref=replace(raw.ref,market_id=c.s.mid),json_text=json.dumps(data)))
        selection['market']=json.loads(json.dumps(asdict(market),default=str))
        # Keep only selection and reference with no baseline: identity validates; result is insufficient.
        subset=[r for r in rows if r['type'] in ('start','selection','http_begin','http_end','session_finished')]
        for r in subset:
            if r['type']=='http_begin':r.update(primary_id=None,primary_state=None)
        result=analyze_rows(subset)
        self.assertEqual(result['comparisons'][0]['classification'],'insufficient_evidence')

    async def test_observation_and_synthetic_selection_and_reference(self):
        for kind in (EvidenceKind.OBSERVATION,EvidenceKind.SYNTHETIC):
            market,_=choose(native.pages(),self.case.clock.utc(),kind=kind)
            self.assertEqual(market.raw.kind,kind)
            self.assertEqual(restored(json.loads(json.dumps(asdict(market),default=str))).raw.kind,kind)
        c=self.case;c.s.kind=EvidenceKind.OBSERVATION
        import app.collection.delivery_capture as module
        original=module.parse_book;seen=[]
        def parse(response,*args,**kw):seen.append(response.kind);return original(response,*args,**kw)
        with patch.object(module,'parse_book',parse):await c.sample()
        self.assertEqual(seen,[EvidenceKind.OBSERVATION])

    async def test_real_never_accepts_fixture_authority(self):
        c=self.case;c.finish();rows=list(SegmentedReader(c.out/'history').rows())
        next(r for r in rows if r['type']=='start')['mode']='real'
        with self.assertRaisesRegex(ValueError,'selection_provenance'):analyze_rows(rows)
        next(r for r in rows if r['type']=='selection')['market']['raw']['kind']='observation'
        rows.insert(-1,dict(type='fixture_truth',authority='controlled-native-fixture-v1'))
        with self.assertRaisesRegex(ValueError,'untrusted_change_authority'):analyze_rows(rows)

    async def test_ready_receive_does_not_parse_or_change_reconstruction(self):
        c=self.case;s=c.s
        before=(s.engine.seq,deepcopy(s.primary_state),s.last_receipt,dict(s.book_counts))
        s.stop()
        with patch.object(s.engine,'feed',side_effect=AssertionError('parsed_after_stop')):
            s.receive(json.dumps(snapshot(3)))
        self.assertEqual(before,(s.engine.seq,s.primary_state,s.last_receipt,s.book_counts))
        result=c.finish();self.assertEqual(result['local'],[])
        rows=list(SegmentedReader(c.out/'history').rows())
        self.assertTrue(any(r.get('reason')=='intake_closed' and r.get('intentional') for r in rows))
        with self.assertRaises(asyncio.CancelledError):await s.reference(75)

    async def test_worker_control_pending_http_and_ready_receive(self):
        c=self.case;s=c.s;messages=[]
        class Pipe:
            def send(self,value):messages.append(value)
        started=asyncio.Event()
        async def block():started.set();await asyncio.Event().wait()
        s.transport.hook=block;c.clock.now=60
        task=asyncio.create_task(s.reference(60));await started.wait()
        control=WorkerControl(s,Pipe());before=(s.engine.seq,s.last_receipt,deepcopy(s.primary_state))
        control.stop(dict(source='scheduled'));control.stop(dict(source='owner'))
        with patch.object(s.engine,'feed',side_effect=AssertionError('post_stop_parse')):s.receive(json.dumps(snapshot(3)))
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(before,(s.engine.seq,s.last_receipt,s.primary_state))
        self.assertFalse(s.bodies.pending);self.assertEqual(s.http.results['cancelled'],1)
        self.assertEqual(len(messages),1);self.assertEqual(c.finish()['local'],[])


class Transport(unittest.IsolatedAsyncioTestCase):
    async def test_ws_exact_destination_no_proxy_redirect_or_replacement(self):
        import websockets.asyncio.client as module
        seen=[]
        class Connect:
            def __init__(self,url,**kw):seen.append((self,url,kw))
            def __await__(self):
                async def value():return self
                return value().__await__()
            async def close(self):pass
        credential=Credential('kalshi',fake_data());t=KalshiTransport(credential)
        with patch.object(module,'connect',Connect):
            await t.connect()
            with self.assertRaises(Exception):await t.connect()
        obj,url,kw=seen[0]
        self.assertEqual(url,ENDPOINTS['kalshi']['ws']);self.assertIsNone(kw['proxy'])
        self.assertIsNone(kw['compression']);self.assertEqual(kw['max_queue'],1)
        self.assertIn('KALSHI-ACCESS-SIGNATURE',kw['additional_headers'])
        failure=ValueError('redirect');self.assertIs(obj.process_redirect(failure),failure)
        self.assertEqual(len(seen),1);await t.close()
    async def test_fresh_reused_disconnect_redirect_and_header_secret(self):
        from aiohttp import web,ClientError
        calls=[];behavior=['ok'];credential=Credential('kalshi',fake_data())
        path=BASE+'/markets/TEST/orderbook'
        async def handler(request):
            calls.append((request.method,request.path,dict(request.query)))
            if behavior[0]=='disconnect':request.transport.close();return web.Response()
            if behavior[0]=='redirect':raise web.HTTPFound('/forbidden')
            if behavior[0]=='echo':return web.json_response({},headers={'Cache-Control':'diagnostic-fixture-key-only'})
            return web.json_response({})
        app=web.Application();app.router.add_get('/{tail:.*}',handler)
        runner=web.AppRunner(app,access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
        endpoints=dict(rest=f'http://127.0.0.1:{port}',ws=f'ws://127.0.0.1:{port}/ws')
        t=FixtureTransport(credential,endpoints)
        try:
            behavior[0]='disconnect'
            with self.assertRaises(ClientError):await t.http(path,{'depth':20},lambda b:None)
            self.assertEqual(len(calls),1)
            behavior[0]='ok';await t.http(path,{'depth':20},lambda b:None)
            behavior[0]='disconnect'
            with self.assertRaises(ClientError):await t.http(path,{'depth':20},lambda b:None)
            self.assertEqual(len(calls),3)
            behavior[0]='redirect';status,_=await t.http(path,{'depth':20},lambda b:None)
            self.assertEqual(status,302);self.assertEqual(len(calls),4)
            self.assertTrue(all(v==('GET',path,{'depth':'20'}) for v in calls))
            self.assertFalse(t.client.trust_env);self.assertFalse(t.client._retry_connection)
            behavior[0]='echo'
            with self.assertRaisesRegex(ValueError,'credential echo'):await t.http(path,{'depth':20},lambda b:None)
        finally:await t.close();await runner.cleanup()

    async def test_charged_discovery_retry_and_fatal_reference(self):
        c=native.Native(methodName='runTest');await c.asyncSetUp()
        try:
            s=c.s;pages=native.pages();calls=[]
            async def http(path,params,consume):
                calls.append(path)
                if len(calls)==1:raise OSError('disconnect')
                if path.endswith('/limits'):body={'read':{'refill_rate':200,'bucket_capacity':400}}
                elif path.endswith('/endpoint_costs'):body={'default_cost':10,'endpoint_costs':[]}
                elif path.endswith('/events'):body=json.loads(__import__('base64').b64decode(pages[0]['body_b64']))
                elif path.endswith('/markets'):body=json.loads(__import__('base64').b64decode(pages[1]['body_b64']))
                else:raise OSError('fatal_reference')
                consume(json.dumps(body).encode());return 200,{}
            async def advance(deadline):c.clock.now=max(c.clock.now,deadline)
            s.transport.http=http;s.wait_until=advance
            await s.discover('initial')
            self.assertEqual(s.http.requests.counts['initial'],5);self.assertEqual(len(calls),5)
            c.clock.now=60
            with self.assertRaises(OSError):await s.reference(60)
            self.assertEqual(s.http.requests.counts['reference'],1);self.assertEqual(len(calls),6)
        finally:await c.asyncTearDown()


class Processes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.launchers=[]
    async def asyncTearDown(self):
        for launcher in self.launchers:await launcher.close()
        self.temp.cleanup()

    def launcher(self,root=None,**kwargs):
        root=root or self.root;spec,manifest,approval=inputs(root)
        launcher=Launcher(manifest,spec,**kwargs);self.launchers.append(launcher)
        return launcher,approval

    async def test_idle_invalid_start_concurrent_duplicate_and_direct_stop(self):
        launcher,approval=self.launcher()
        self.assertEqual(launcher.status()['state'],'idle');self.assertFalse(list(self.root.iterdir()))
        self.assertEqual(launcher.stop()['reason'],'not_started')
        with self.assertRaises(ValueError):await launcher.start(dict(approval,approved=False))
        self.assertFalse(list(self.root.iterdir()))
        task=asyncio.create_task(launcher.start(approval))
        await asyncio.sleep(0)
        with self.assertRaises(ValueError):await launcher.start(approval)
        await task
        await until(lambda:any(x.get('value',{}).get('event')=='collecting' for x in launcher.events))
        await asyncio.sleep(3.5)  # Real paced discovery; receive remains pending.
        launcher.stop();launcher.stop()
        await asyncio.wait_for(launcher.done.wait(),15)
        self.assertEqual(launcher.state,'finished',launcher.result)
        self.assertEqual(audit(launcher.spec['output'])['status'],'complete')
        closed=next(x['value']['mono'] for x in launcher.events if x.get('value',{}).get('event')=='intake_closed')
        observed=fixture_audit(launcher.spec['output'],launcher.anchor['mono'],closed)
        self.assertGreater(observed['server_http_requests'],0)
        telemetry=read_json(Path(launcher.spec['output'])/'fixture-observations.json')
        for change in ('origin','path','count','post_stop'):
            bad=deepcopy(telemetry)
            if change=='origin':bad['observations'][0]['mono']=launcher.anchor['mono']-1
            elif change=='count':bad['http_calls']+=1
            else:
                row=next(r for r in bad['observations'] if r['event']=='http')
                if change=='path':row['path']='/wrong'
                else:row['mono']=closed+1
            with patch('tests.delivery_launcher_audit.read_json',return_value=bad),self.assertRaises(AssertionError):
                fixture_audit(launcher.spec['output'],launcher.anchor['mono'],closed)
        with self.assertRaises(AssertionError):qualification(launcher.spec['output'])
        self.assertIsNone(launcher.attempt.lock)
        self.assertEqual(sum(x['event']=='stop_sent' for x in launcher.events),1)
        with self.assertRaises(ValueError):await launcher.start(approval)

    async def test_failed_credential_and_crash_are_consumed(self):
        for fault in ('load_failure','worker_crash'):
            root=self.root/fault;root.mkdir();launcher,approval=self.launcher(root,fixture_options={fault:True})
            await launcher.start(approval);await asyncio.wait_for(launcher.done.wait(),15)
            self.assertEqual(launcher.state,'failed');self.assertTrue(launcher.attempt.marker.exists())
            self.assertFalse((root/'attempt/collector/finalization-resources.json').exists())
            self.assertNotIn('fixture-secret-must-not-leak',''.join(p.read_text() for p in (root/'attempt').rglob('*.json')))
            self.assertIsNone(launcher.attempt.lock)

    async def test_scheduled_stop_same_handler_short_clock(self):
        launcher,approval=self.launcher(watch_clock=JumpClock(240,after=3))
        await launcher.start(approval);await asyncio.wait_for(launcher.done.wait(),20)
        self.assertEqual(launcher.state,'finished',launcher.result)
        self.assertTrue(any(x['event']=='stop_sent' and x['source']=='scheduled' for x in launcher.events))
        self.assertTrue(any(x.get('value',{}).get('event')=='stop_received' for x in launcher.events))

    async def test_watchdog_loss_kills_blocked_worker(self):
        launcher,approval=self.launcher(fixture_options={'block_worker':True})
        await launcher.start(approval);launcher.guard.kill()
        await asyncio.wait_for(launcher.done.wait(),10)
        self.assertEqual(launcher.state,'failed');self.assertFalse(launcher.process.is_alive())
        self.assertTrue(launcher.attempt.marker.exists())

    async def test_blocked_finalizer_independent_cutoff(self):
        launcher,approval=self.launcher(fixture_options={'block_finalizer':True},watch_clock=JumpClock(301,after=4))
        await launcher.start(approval)
        await until(lambda:any(x.get('value',{}).get('event')=='collecting' for x in launcher.events))
        launcher.stop();await asyncio.wait_for(launcher.done.wait(),15)
        self.assertEqual(launcher.state,'failed');self.assertFalse(launcher.process.is_alive())
        self.assertFalse((Path(launcher.spec['output'])/'collector/finalization-resources.json').exists())

    async def test_private_unix_controls_idle_and_stop_before_start(self):
        import aiohttp
        spec,manifest,approval=inputs(self.root);approval_path=self.root/'approval.json';write_once(approval_path,approval)
        task=asyncio.create_task(serve(manifest,spec,approval_path));path=Path(socket_path(spec))
        try:
            await until(path.exists)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(path))) as client:
                async with client.get('http://localhost/status') as response:self.assertEqual((await response.json())['state'],'idle')
                async with client.post('http://localhost/stop') as response:self.assertEqual((await response.json())['reason'],'not_started')
                self.assertFalse(Path(spec['output']).exists());self.assertFalse(Path(spec['ownership']).exists())
                async with client.post('http://localhost/start') as response:self.assertEqual(response.status,200)
                async with client.post('http://localhost/stop') as response:self.assertTrue((await response.json())['stopped'])
            await asyncio.wait_for(asyncio.shield(task),15)
            self.assertTrue((Path(spec['ownership'])/(spec['attempt']+'.attempt.json')).exists())
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertFalse(path.exists())

    async def test_startup_failure_before_arm_consumes_without_credentials(self):
        launcher,approval=self.launcher()
        with patch('multiprocessing.process.BaseProcess.start',side_effect=OSError('fixture_secret')):
            with self.assertRaisesRegex(ValueError,'^start_failed_attempt_retained$'):await launcher.start(approval)
        self.assertTrue(launcher.attempt.marker.exists());self.assertIsNone(launcher.attempt.lock)
        self.assertFalse((Path(launcher.spec['output'])/'collector').exists())
        self.assertNotIn('fixture_secret',str(launcher.status()))

    async def test_start_rechecks_manifest_before_attempt(self):
        launcher,approval=self.launcher()
        with patch('app.collection.delivery_manifest.runtime_inventory',return_value={}):
            with self.assertRaises(ValueError):await launcher.start(approval)
        self.assertFalse(list(self.root.iterdir()))

    async def test_supervisor_death_releases_worker_lock(self):
        spec,manifest,approval=inputs(self.root)
        ctx=multiprocessing.get_context('spawn');parent,child=ctx.Pipe()
        process=ctx.Process(target=orphan_supervisor,args=(spec,manifest,approval,child));process.start();child.close()
        try:
            await until(parent.poll,15);pids=parent.recv();process.kill();process.join(2)
            marker=Path(spec['ownership'])/(spec['attempt']+'.attempt.json')
            self.assertTrue(marker.exists())
            def released():
                with (Path(spec['ownership'])/'collector.lock').open('a') as f:
                    try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);return True
                    except BlockingIOError:return False
            await until(released,10)
            self.assertFalse((Path(spec['output'])/'collector/finalization-resources.json').exists())
        finally:
            if process.is_alive():process.kill();process.join(2)
            parent.close()

    async def test_blocked_control_loop_cannot_keep_collector_alive(self):
        import subprocess
        spec,manifest,approval=inputs(self.root)
        ctx=multiprocessing.get_context('spawn');parent,child=ctx.Pipe()
        process=ctx.Process(target=orphan_supervisor,args=(spec,manifest,approval,child,True));process.start();child.close()
        try:
            await until(parent.poll,15);pids=parent.recv()
            def exited():
                value=subprocess.run(['ps','-p',str(pids['worker']),'-o','stat='],capture_output=True,text=True)
                return value.returncode!=0 or value.stdout.strip().startswith('Z')
            await until(exited,10)
            self.assertFalse((Path(spec['output'])/'collector/finalization-resources.json').exists())
            self.assertTrue((Path(spec['ownership'])/(spec['attempt']+'.attempt.json')).exists())
        finally:
            if process.is_alive():process.kill();process.join(2)
            parent.close()


class WatchdogProcesses(unittest.TestCase):
    def test_blocked_loop_term_kill_and_control_eof(self):
        ctx=multiprocessing.get_context('spawn')
        for scenario in ('intake','finalizer','eof'):
            with self.subTest(scenario=scenario):
                parent,child=ctx.Pipe();worker=ctx.Process(target=blocked_worker,args=(child,True))
                worker.start();child.close()
                self.assertTrue(parent.poll(5));pid=parent.recv()
                control,remote=ctx.Pipe();start=time.monotonic()
                watchdog=ctx.Process(target=watch,args=(pid,os.getpid(),remote,start),kwargs={'clock':JumpClock(301,after=1)})
                watchdog.start();remote.close()
                try:
                    self.assertTrue(control.poll(5));self.assertEqual(control.recv()['event'],'armed')
                    control.send({'action':'collecting'})
                    if scenario=='finalizer':control.send(dict(action='closed',mono=start+.1))
                    if scenario=='eof':control.close()
                    worker.join(8);watchdog.join(3)
                    self.assertFalse(worker.is_alive());self.assertEqual(worker.exitcode,-signal.SIGKILL)
                    self.assertFalse(watchdog.is_alive());self.assertLess(time.monotonic()-start,15)
                finally:
                    if worker.is_alive():worker.kill();worker.join(1)
                    if watchdog.is_alive():watchdog.kill();watchdog.join(1)
                    parent.close();control.close()
