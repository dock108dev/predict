"""Bounded temporary-output fixtures; no historical generators or external access."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.adapters.kalshi_stream import BookReconstructor
from app.collection.delivery_analysis import analyze, analyze_rows
from app.collection.delivery_budget import Bodies, CAP, Clock, MIB, Records, Requests, raw_fields
from app.collection.delivery_capture import BASE, DiagnosticOwner, LoopbackTransport, Session, canonical, choose
from app.collection.odds_http import BudgetStop
from app.collection.segmented import SegmentedReader
from app.collection.supervised import bound_native
from tests.delivery_fixture import MID,EID,acknowledgement,inventory,rest_book,snapshot,NetworkGuard,Server


class FakeClock(Clock):
    def __init__(self):self.now=0.;self.offset=0.
    def monotonic(self):return self.now
    def utc(self):return datetime(2026,9,19,tzinfo=timezone.utc)+timedelta(seconds=self.now+self.offset)


def pages(start=None):
    e,m=inventory(start or '2026-09-20T17:00:00+00:00')
    return [dict(source='kalshi',path=BASE+'/events',params={'limit':200,'cursor':'','series_ticker':'KXNFLGAME'},
        status=200,complete=True,received_at='2026-09-19T00:00:00+00:00',**raw_fields(json.dumps(e).encode())),
        dict(source='kalshi',path=BASE+'/markets',params={'limit':200,'cursor':'','event_ticker':EID},
        status=200,complete=True,received_at='2026-09-19T00:00:00+00:00',**raw_fields(json.dumps(m).encode()))]


class StubTransport:
    def __init__(self,clock):self.clock=clock;self.calls=[];self.value=rest_book();self.delay=0.;self.error=None;self.status=200;self.headers={};self.hook=None
    async def http(self,path,params,consume):
        self.calls.append((path,params,self.clock.now))
        if self.hook:await self.hook()
        self.clock.now+=self.delay
        consume(json.dumps(self.value).encode())
        if self.error:raise self.error
        return self.status,self.headers
    async def close(self):pass


class Native(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.out=Path(self.temp.name);self.clock=FakeClock()
        self.transport=StubTransport(self.clock);self.s=Session(self.out,self.transport,clock=self.clock)
        self.s.start_mono=0.;self.s.started=self.clock.utc();self.s.records=Records(self.out,self.clock)
        self.s.market,audit=choose(pages(),self.s.started);self.s.mid=MID;self.s.kickoff=audit['kickoff']
        self.s.records.save('start',mode='synthetic')
        from dataclasses import asdict
        self.s.records.save('selection',kind='initial',market=json.loads(json.dumps(asdict(self.s.market),default=str)),audit=audit)
        self.s.engine=BookReconstructor([self.s.market]);bound_native(self.s.engine)
        cmd=self.s.engine.begin(1);self.s.records.save('subscription',command=cmd)
        self.s.receive(json.dumps(acknowledgement()));self.s.receive(json.dumps(snapshot()))
    async def asyncTearDown(self):
        if not self.s.records.history.closed:self.s.records.history.abort()
        self.temp.cleanup()
    def finish(self):
        h=self.s.records.history;h.finalizing=True
        h.save(dict(type='session_finished'));h.finish(cleanup_complete=True)
        return analyze(self.out/'history')
    async def sample(self,qty='10',slot=60):
        self.clock.now=slot;self.transport.value=rest_book(qty);await self.s.reference(slot)

    async def test_quiet_unchanged_does_not_refresh(self):
        before=(self.s.primary_state,self.s.primary_id,self.s.last_receipt)
        await self.sample();await self.sample(slot=75)
        self.assertEqual(before,(self.s.primary_state,self.s.primary_id,self.s.last_receipt))
        result=self.finish();self.assertTrue(result['complete'])
        self.assertEqual([r['classification'] for r in result['comparisons']],['sampled_consistency']*2)
        self.assertTrue(all(r['stale_at_send'] for r in result['comparisons']))

    async def test_unchanged_primary_and_zero_delta_refresh_only_primary(self):
        self.clock.now=20;self.s.receive(json.dumps(snapshot(2)));self.assertEqual(self.s.last_receipt,20)
        self.clock.now=25;self.s.receive(json.dumps(dict(type='orderbook_delta',sid=1,seq=3,
            msg=dict(market_ticker=MID,market_id='native-fixture-id',side='yes',price_dollars='0.4',delta_fp='0'))))
        self.assertEqual(self.s.last_receipt,25)
        await self.sample();self.assertEqual(self.s.last_receipt,25)

    async def test_authoritative_synthetic_missing_change(self):
        self.clock.now=40;state=deepcopy(self.s.primary_state);state['yes'][0][1]='11'
        self.s.records.save('fixture_truth',authority='controlled-native-fixture-v1',ordered=True,
            state=state,change_mono=40,market=MID)
        await self.sample('11');r=self.finish()
        self.assertEqual([v['classification'] for v in r['comparisons']],['cross_path_disagreement','synthetic_missing_change'])

    async def test_without_authority_only_disagreement(self):
        await self.sample('11');self.assertEqual(self.finish()['comparisons'][0]['classification'],'cross_path_disagreement')

    async def test_removed_ordering_cannot_promote_fixture_change(self):
        self.clock.now=40;state=deepcopy(self.s.primary_state);state['yes'][0][1]='11'
        self.s.records.save('fixture_truth',authority='controlled-native-fixture-v1',ordered=False,
            state=state,change_mono=40,market=MID)
        await self.sample('11');r=self.finish()
        self.assertEqual([v['classification'] for v in r['comparisons']],['cross_path_disagreement'])

    async def test_unobserved_future_truth_is_not_missing_change(self):
        self.clock.now=40;state=deepcopy(self.s.primary_state);state['yes'][0][1]='11'
        self.s.records.save('fixture_truth',authority='controlled-native-fixture-v1',ordered=True,
            state=state,change_mono=1000,market=MID)
        await self.sample('11');self.assertEqual(len(self.finish()['comparisons']),1)

    async def test_change_revert_between_samples_is_not_observed(self):
        await self.sample();self.transport.value=rest_book('12');self.transport.value=rest_book()
        await self.sample(slot=75)
        self.assertEqual({r['classification'] for r in self.finish()['comparisons']},{'sampled_consistency'})

    async def test_local_failures_replayed_exact_boundary(self):
        self.s.fault=lambda stage: (_ for _ in ()).throw(RuntimeError('fixture')) if stage=='parser' else None
        with self.assertRaises(RuntimeError):self.s.receive(json.dumps(snapshot(2,'11')))
        r=self.finish();self.assertEqual(r['local'][0]['boundary'],'parser');self.assertEqual(r['local'][0]['classification'],'local_processing_loss')

    async def test_emission_loss(self):await self.loss('emission')
    async def test_admission_loss(self):await self.loss('admission')
    async def test_queue_loss(self):await self.loss('queue')
    async def loss(self,stage):
        self.s.fault=lambda actual: (_ for _ in ()).throw(RuntimeError('fixture')) if actual==stage else None
        with self.assertRaises(RuntimeError):self.s.receive(json.dumps(snapshot(2,'11')))
        r=self.finish();self.assertEqual(r['local'][0]['boundary'],stage)
        self.assertTrue(r['local'][0]['receive_id']);self.assertTrue(r['local'][0]['body_sha256'])

    async def test_invalid_native_is_not_local_qualifying_loss(self):
        with self.assertRaises(ValueError):self.s.receive('{')
        self.assertEqual(self.finish()['local'],[])

    async def test_sequence_gap_stops_without_reconnect(self):
        with self.assertRaises(ValueError):self.s.receive(json.dumps(snapshot(3)))
        self.assertEqual(self.finish()['local'],[])

    async def test_slow_reference_inconclusive(self):
        self.transport.delay=3;await self.sample()
        self.assertEqual(self.finish()['comparisons'][0]['classification'],'insufficient_evidence')

    async def test_failed_partial_reference_retained_and_counted(self):
        self.transport.error=OSError('fixture partial')
        with self.assertRaises(OSError):await self.sample()
        self.assertGreater(self.s.bodies.used['http'],0);self.assertEqual(self.s.http.requests.counts['reference'],1)
        self.assertFalse(self.s.bodies.pending)
        self.assertEqual(self.finish()['comparisons'][0]['classification'],'insufficient_evidence')

    async def test_skipped_reference_no_catchup(self):
        self.clock.now=60;await self.s.http.lock.acquire()
        try:await self.s.reference(60)
        finally:self.s.http.lock.release()
        self.assertEqual(self.transport.calls,[]);self.assertEqual(self.s.http.requests.counts['reference'],0)
        await self.sample(slot=75);self.assertEqual(len(self.transport.calls),1)

    async def test_cached_reference_never_becomes_authoritative(self):
        self.transport.headers={'Age':'120','Date':'Sat, 19 Sep 2026 00:00:00 GMT'}
        await self.sample('11');r=self.finish()['comparisons'][0]
        self.assertEqual(r['classification'],'cross_path_disagreement');self.assertIsNone(r['server_state_age'])

    async def test_overlapping_native_change_is_inconclusive(self):
        async def update():self.s.receive(json.dumps(snapshot(2,'11')))
        self.transport.hook=update;await self.sample('11')
        self.assertEqual(self.finish()['comparisons'][0]['classification'],'insufficient_evidence')

    async def test_malformed_reference(self):
        self.clock.now=60;self.transport.value={'unexpected':1}
        with self.assertRaises(ValueError):await self.s.reference(60)
        self.assertEqual(self.finish()['comparisons'][0]['classification'],'insufficient_evidence')

    async def test_missing_side_incomparable(self):
        self.clock.now=60;self.transport.value={'orderbook_fp':{'yes_dollars':[]}}
        with self.assertRaises(ValueError):await self.s.reference(60)
        self.assertEqual(self.finish()['comparisons'][0]['classification'],'insufficient_evidence')

    async def test_empty_side_distinct_from_absent(self):
        self.clock.now=60;self.transport.value={'orderbook_fp':{'yes_dollars':[],'no_dollars':[]}}
        await self.s.reference(60);self.assertEqual(self.finish()['comparisons'][0]['classification'],'cross_path_disagreement')

    async def test_clock_jump_disqualifies_temporal_evidence(self):
        self.clock.offset=10;await self.sample()
        self.assertEqual(self.finish()['comparisons'][0]['classification'],'insufficient_evidence')

    async def test_stop_cancels_pending_reference_and_counts(self):
        entered=asyncio.Event()
        async def pending():entered.set();await asyncio.Event().wait()
        self.transport.hook=pending;self.clock.now=60
        task=asyncio.create_task(self.s.reference(60));await entered.wait();self.s.stop();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(self.s.bodies.pending);self.assertEqual(self.s.http.results['cancelled'],1)
        with self.assertRaises(asyncio.CancelledError):await self.s.reference(75)

    async def test_already_ready_receive_after_stop_cannot_admit(self):
        original=(self.s.primary_id,self.s.last_receipt,deepcopy(self.s.primary_state),dict(self.s.book_counts))
        self.s.stop();self.clock.now=1;self.s.receive(json.dumps(snapshot(2,'11')))
        self.assertEqual(original,(self.s.primary_id,self.s.last_receipt,self.s.primary_state,self.s.book_counts))
        self.assertEqual(self.finish()['local'],[])

    async def test_no_reference_retry_429(self):
        self.transport.status=429
        with self.assertRaisesRegex(ValueError,'429'):await self.sample()
        self.assertEqual(len(self.transport.calls),1)

    async def test_authoritative_retention_failure_leaves_incomplete(self):
        with patch.object(self.s.records.history,'save',side_effect=OSError('fsync')):
            with self.assertRaises(OSError):self.s.receive(json.dumps(snapshot(2)))
        self.assertTrue(self.s.records.failed);self.s.records.history.abort()
        self.assertFalse(analyze(self.out/'history')['complete'])

    async def test_expiry_independent_of_pending_receive(self):
        self.clock.now=30;task=asyncio.create_task(self.s.expiry());await asyncio.sleep(.01)
        self.assertFalse(self.s.stale)
        self.clock.now=30.000001;self.s.receipt_changed.set();await asyncio.sleep(.01)
        self.assertTrue(self.s.stale);task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_ack_mismatch_rejected(self):
        bad=acknowledgement();bad['id']=99
        with self.assertRaisesRegex(ValueError,'ack_mismatch'):self.s.receive(json.dumps(bad))

    async def test_top20_boundary_and_decimal_order(self):
        self.clock.now=60
        self.transport.value={'orderbook_fp':{'yes_dollars':[[str(i/100),'1'] for i in range(1,26)],'no_dollars':[]}}
        await self.s.reference(60);r=self.finish()['comparisons'][0]
        self.assertEqual(len(r['reference_state']['yes']),20)
        self.assertEqual(r['reference_state']['yes'][0][0],'0.25')
        self.assertEqual(r['reference_state']['yes'][-1][0],'0.06')

    async def test_reference_path_binds_ticker_when_body_does_not(self):
        await self.sample();self.finish()
        rows=list(SegmentedReader(self.out/'history').rows())
        for row in rows:
            if row['type']=='http_end' and row['kind']=='reference':row['path']=BASE+'/markets/OTHER/orderbook'
        with self.assertRaisesRegex(ValueError,'reference_request_mismatch'):analyze_rows(rows)

    async def test_account_cost_and_serial_pacing(self):
        self.s.http.account_limits({'read':{'refill_rate':10,'bucket_capacity':40}},
            {'default_cost':10,'endpoint_costs':[{'method':'GET','path':BASE+'/markets/*/orderbook','cost':20}]})
        self.assertEqual(self.s.http.interval(BASE+'/markets/'+MID+'/orderbook'),2)
        await self.sample();self.assertEqual(self.s.http.next_at,62)
        self.clock.now=61;await self.s.reference(75)
        self.assertEqual(len(self.transport.calls),1)
        self.s.http.capacity=1
        with self.assertRaises(BudgetStop):self.s.http.interval(BASE+'/markets/'+MID+'/orderbook')

    async def test_startup_deadline_on_virtual_scheduler(self):
        self.s.startup=False
        async def advance(deadline):self.clock.now=deadline
        with patch.object(self.s,'wait_until',side_effect=advance):
            with self.assertRaisesRegex(ValueError,'startup_deadline'):await self.s.schedule()

    async def test_skipped_late_slot_no_catchup(self):
        self.s.reached=set()
        async def advance(deadline):
            if deadline>61:raise asyncio.CancelledError()
            self.clock.now=deadline+1
        with patch.object(self.s,'wait_until',side_effect=advance):
            with self.assertRaises(asyncio.CancelledError):await self.s.schedule()
        self.assertIn(60,self.s.reached);self.assertEqual(self.transport.calls,[])


class Bounds(unittest.TestCase):
    def test_request_exact_partition_and_cap(self):
        r=Requests()
        for _ in range(40):r.charge('initial')
        for _ in range(40):r.charge('refresh')
        for s in range(60,300,15):r.charge('reference',s)
        self.assertEqual(r.generations,[44,52]);self.assertEqual(sum(r.counts.values()),96)
        for k,s in [('initial',None),('refresh',None),('reference',285)]:
            with self.assertRaises(BudgetStop):r.charge(k,s)
    def test_body_joint_pending_partial_and_oversize(self):
        b=Bodies();b.reserve('primary');b.reserve('http')
        self.assertEqual(b.peak,2*CAP['body'])
        with self.assertRaises(BudgetStop):b.reserve('http')
        b.finish('http',11);b.finish('primary',0)
        self.assertEqual(b.used['http'],11);self.assertFalse(b.pending)
        b.used['primary']=CAP['primary_bytes']
        with self.assertRaises(BudgetStop):b.reserve('primary')
    def test_selection_repeatable_and_kickoff(self):
        at=FakeClock().utc();a,audit=choose(pages(),at);self.assertEqual(a.raw.ref.market_id,MID)
        self.assertEqual(choose(list(reversed(pages())),at)[1],audit)
        with self.assertRaises(ValueError):choose(pages((at+timedelta(seconds=600)).isoformat()),at)
    def test_incomplete_discovery_and_unknown_start(self):
        with self.assertRaises(ValueError):choose(pages()[:1],FakeClock().utc())
        p=pages();data=json.loads(__import__('base64').b64decode(p[0]['body_b64']));data['milestones']=[]
        p[0].update(raw_fields(json.dumps(data).encode()))
        with self.assertRaises(ValueError):choose(p,FakeClock().utc())
    def test_no_eligible_and_many_sorted(self):
        p=pages();d=json.loads(__import__('base64').b64decode(p[1]['body_b64']))
        d['markets'][0]['status']='closed';p[1].update(raw_fields(json.dumps(d).encode()))
        with self.assertRaises(ValueError):choose(p,FakeClock().utc())
        d['markets'][0]['status']='active';second=deepcopy(d['markets'][0]);second['ticker']='AAA';d['markets'].append(second)
        p[1].update(raw_fields(json.dumps(d).encode()))
        self.assertEqual(choose(p,FakeClock().utc())[0].raw.ref.market_id,'AAA')
    def test_only_kalshi_loopback_no_credentials(self):
        valid={'kalshi':{'rest':'http://127.0.0.1:1','ws':'ws://127.0.0.1:1/ws'}}
        LoopbackTransport(valid)
        for endpoints,creds in [(dict(valid,polymarket_us=valid['kalshi']),None),(valid,{'kalshi':'secret'}),
                ({'kalshi':{'rest':'https://example.com','ws':'ws://127.0.0.1:1/ws'}},None)]:
            with self.assertRaises(ValueError):LoopbackTransport(endpoints,creds)
    def test_exclusive_owner_and_consumed_attempt_across_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);attempt=str(uuid4());a=DiagnosticOwner(root/'a',root/'locks',attempt);a.acquire()
            b=DiagnosticOwner(root/'b',root/'locks',str(uuid4()))
            with self.assertRaises(OSError):b.acquire()
            a.release()
            with self.assertRaises(FileExistsError):DiagnosticOwner(root/'c',root/'locks',attempt).acquire()
    def test_failed_start_consumes_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);attempt=str(uuid4());a=DiagnosticOwner(root,root/'locks',attempt)
            with self.assertRaises(FileExistsError):a.acquire()
            self.assertTrue((root/'locks'/(attempt+'.attempt.json')).exists());self.assertIsNone(a.owner_lock)
    def test_preflight_resources_consume_attempt_without_transport(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);attempt=str(uuid4());a=DiagnosticOwner(root/'out',root/'locks',attempt)
            with patch('app.collection.continuous.rss',return_value=192*MIB):
                with self.assertRaises(BudgetStop):a.acquire()
            self.assertTrue((root/'locks'/(attempt+'.attempt.json')).exists());self.assertFalse((root/'out').exists())
    def test_external_and_keyring_guard(self):
        import keyring
        with NetworkGuard():
            with self.assertRaises(AssertionError):socket.getaddrinfo('example.com',443)
            with self.assertRaises(AssertionError):keyring.get_password('x','y')
    def test_resource_subcaps_fail_before_write(self):
        cases=[('logical',CAP['logical']),('encoded',CAP['encoded_ingress']),('expanded',CAP['expanded_ingress'])]
        for attr,value in cases:
            with self.subTest(attr=attr),tempfile.TemporaryDirectory() as d:
                r=Records(Path(d));setattr(r.history,attr,value)
                with self.assertRaises(BudgetStop):r.save('fixture')
                r.history.abort()
    def test_rows_and_frames(self):
        with tempfile.TemporaryDirectory() as d:
            r=Records(Path(d));r.frames=CAP['frames']
            with self.assertRaises(BudgetStop):r.save('native_receive',frame=True)
            r.history.abort()

    def test_resource_guards_memory_disk_output_writes_state(self):
        from app.collection.supervised import PROFILE
        with tempfile.TemporaryDirectory() as d:
            r=Records(Path(d))
            with patch('app.collection.delivery_budget.rss',return_value=PROFILE['soft_rss']):
                with self.assertRaises(BudgetStop):r.guard()
            with patch('app.collection.delivery_budget.shutil.disk_usage',return_value=type('Disk',(),{'free':0})()):
                with self.assertRaises(BudgetStop):r.guard()
            with patch.object(r.history,'disk_bytes',return_value=CAP['output']):
                with self.assertRaises(BudgetStop):r.guard()
            r.history.manifest_write_bytes=CAP['write_bytes']
            with self.assertRaises(BudgetStop):r.guard()
            r.history.manifest_write_bytes=0
            with patch('app.collection.delivery_budget.retained_bytes',return_value=65*MIB):
                with self.assertRaises(BudgetStop):r.guard(state={})
            r.history.abort()
        with tempfile.TemporaryDirectory() as d:
            r=Records(Path(d))
            with self.assertRaises(BudgetStop):r.save('large',body='x'*MIB)
            r.history.abort()


class Integration(unittest.IsolatedAsyncioTestCase):
    async def test_http_disconnect_is_one_network_attempt(self):
        from aiohttp import web,ClientError
        calls=[]
        async def disconnected(request):
            calls.append(request.path);request.transport.close();return web.Response()
        app=web.Application();app.router.add_get('/book',disconnected)
        runner=web.AppRunner(app,access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        t=LoopbackTransport({'kalshi':{'rest':f'http://127.0.0.1:{port}','ws':f'ws://127.0.0.1:{port}/ws'}})
        try:
            with self.assertRaises(ClientError):await t.http('/book',{},lambda b:None)
            self.assertEqual(calls,['/book'])
        finally:await t.close();await runner.cleanup()

    async def test_native_http_ws_pending_stop_and_refresh(self):
        # Focused shortened operator Stop, not a major timed lifecycle experiment.
        from tests.test_finalization_resources import Writes
        writes=Writes()
        with tempfile.TemporaryDirectory() as d, patch.object(Path,'open',lambda p,*a,**kw:writes(p,*a,**kw)):
            out=Path(d)/'attempt';owner=DiagnosticOwner(out,Path(d)/'locks',str(uuid4()));owner.acquire()
            server=Server();transport=await server.start();s=Session(out,transport)
            task=asyncio.create_task(s.run())
            try:
                async with asyncio.timeout(15):
                    while not s.startup:
                        if s.intake_closed:raise AssertionError(s.reason)
                        await asyncio.sleep(.02)
                    await s.discover('refresh')
                    self.assertEqual(s.mid,MID);s.stop();await task
                await server.close();summary,receipt=s.finalize()
                self.assertEqual(transport.connections,1);self.assertFalse(s.bodies.pending)
                self.assertEqual(receipt['status'],'complete');self.assertTrue(summary['cleanup_complete'])
                self.assertEqual(summary['accounting']['accepted'],summary['accounting']['drained'])
                self.assertEqual(receipt['final_retained_output_bytes'],sum(p.stat().st_size for p in out.rglob('*') if p.is_file()))
                self.assertEqual(receipt['cumulative_application_file_write_bytes'],sum(n for path,n in writes.by_path.items() if Path(path).is_relative_to(out)))
            finally:
                s.stop();task.cancel();await asyncio.gather(task,return_exceptions=True)
                await server.close();owner.release()

    async def test_failed_eligibility_refresh_preserves_market(self):
        with tempfile.TemporaryDirectory() as d:
            server=Server();transport=await server.start();s=Session(Path(d),transport)
            s.records=Records(Path(d));s.started=datetime.now(timezone.utc);s.start_mono=__import__('time').monotonic()
            try:
                await s.discover('initial');server.markets['markets'][0]['status']='closed'
                with self.assertRaises(ValueError):await s.discover('refresh')
                self.assertEqual(s.mid,MID)
            finally:s.records.history.abort();await server.close();await transport.close()


if __name__=='__main__':
    with NetworkGuard():unittest.main(failfast=True)
