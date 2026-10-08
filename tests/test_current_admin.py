"""U5 operator contracts through production interfaces; isolated, zero source I/O."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from app.collection.current_service import CurrentService
from app.collection.current_policy import DEFAULT
from app.collection.local_ownership import LocalOwnership
from app.collection.current_quota import QuotaLedger
from app.collection.current_aggregate import AggregateScheduler
from app.dashboard.current_state import CurrentStore, SelectionError
from app.dashboard.multi_game_server import create_app
from tests.test_current_service import FakeWorker, native_fixture
from tests.test_current_state import owner, request
from tests.test_current_quota import WINDOW, quota

class IdleAggregate(AggregateScheduler):
    async def run(self):await asyncio.Event().wait()

class AdminTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        now=datetime.now(timezone.utc)
        self.window=dict(WINDOW,starts_at=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat(),ends_at=(now.replace(day=28)+timedelta(days=4)).replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat())
        self.q=QuotaLedger(self.root/'quota')
        self.service=CurrentService(directory=self.root/'authority',ownership=LocalOwnership(self.root/'owner'),worker_factory=FakeWorker,
            aggregate_factory=lambda svc:IdleAggregate(svc,ledger=self.q,window_loader=lambda:self.window))
        self.store=CurrentStore(self.service)
        await self.service.start(self.store);await asyncio.sleep(0)
        self.queue=asyncio.Queue(maxsize=1);self.store.subscribers.add(self.queue)
        self.q.bind_window(self.window)
        aid=self.q.reserve(self.service.ownership,self.service.digest,dict(path='/v4/sports',params={}),0,bootstrap=True)
        self.q.dispatched(aid,self.service.ownership);self.q.reconcile(aid,quota(248))
    async def asyncTearDown(self):
        await self.store.close();self.service.ownership.release();self.temp.cleanup()
    async def test_read_only_metrics_age_and_unknowns(self):
        before=(self.root/'quota/quota.json').read_bytes()
        s=self.service.status()
        self.assertEqual(s['quota']['used'],248);self.assertEqual(s['quota']['available'],202)
        self.assertGreaterEqual(s['quota']['observation_age_seconds'],0)
        self.assertIsNone(s['sources'][0]['source_age_seconds']);self.assertGreater(s['resources']['sampled_rss_bytes'],0)
        self.assertEqual((self.root/'quota/quota.json').read_bytes(),before)
        self.assertEqual(self.service.workers['the_odds_api'].metrics['requests'],0)
    async def test_issue_dedup_secret_bounds_and_distinct_scope(self):
        for _ in range(10):self.service.issue('kalshi','authentication','http_401')
        self.assertEqual(len(self.service.issues),1);self.assertEqual(self.service.issues[0]['occurrences'],10)
        self.service.issue('secret-provider','secret-category','ALPHANUMERICSECRET123')
        self.assertNotIn('SECRET',json.dumps(self.service.issues));self.assertNotIn('secret-provider',json.dumps(self.service.issues))
        self.service.config['issue_records']=2
        self.service.issue('kalshi','entitlement','http_403');self.service.issue('polymarket_us','authentication','http_401')
        self.assertEqual(len(self.service.issues),2)
        self.service.config['issue_bytes']=10
        self.service.issue('kalshi','local_defect','ValueError');self.assertEqual(self.service.issues,[])
        self.assertLessEqual((self.root/'authority/issues.json').stat().st_size,10)
    async def test_fresh_recovery_preserves_due_authority_and_expires_review(self):
        cat,book=native_fixture();self.service.catalog('kalshi',cat);self.service.book('kalshi',book)
        held=self.store.create(request(self.store));runtime=self.service.runtime_id
        q=self.q.snapshot();before=deepcopy(q)
        await self.service.recover(runtime,self.service.digest)
        self.assertNotEqual(self.service.runtime_id,runtime)
        self.assertEqual(len(list((self.root/'authority').glob('attempt-*.json'))),2)
        for key in ('used','remaining','reserved','next_due_at','bootstrap_due_at','rotation','attempts'):self.assertEqual(self.q.snapshot()[key],before[key])
        with self.assertRaises(SelectionError):self.store.get(held['selection_id'])
        with self.assertRaisesRegex(SelectionError,''):await self.service.recover(runtime,self.service.digest)
    async def test_competing_clicks_only_one_new_runtime(self):
        runtime=self.service.runtime_id;digest=self.service.digest
        results=await asyncio.gather(self.service.recover(runtime,digest),self.service.recover(runtime,digest),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,SelectionError) for r in results),1)
        self.assertEqual(len(list((self.root/'authority').glob('attempt-*.json'))),2)
    async def test_cleanup_blocks_recovery_retains_ownership(self):
        async def fail():raise OSError('SECRET unsafe provider text')
        self.service.workers['kalshi'].close=fail
        with self.assertRaises(SelectionError):await self.service.recover(self.service.runtime_id,self.service.digest)
        self.assertTrue(self.service.ownership.file);self.assertFalse(self.service.cleanup_complete)
        self.assertEqual(self.service.status()['recovery']['reason'],'cleanup_safety_unresolved')
        self.assertNotIn('SECRET',json.dumps(self.service.status()))
        self.service.workers['kalshi'].close=FakeWorker.close.__get__(self.service.workers['kalshi'])
    async def test_admission_metrics_and_clock_meaning_separate(self):
        cat,book=native_fixture();self.service.catalog('kalshi',cat);self.service.book('kalshi',book)
        p=self.service.status()['sources'][0]
        self.assertEqual(p['quotes'],2);self.assertIsNotNone(p['source_at']);self.assertEqual(p['identity_verified'],2)
        with self.assertRaises(ValueError):self.service.sink.commit(self.service.row('coverage_inventory','kalshi',inventory={},generation=2,previous_generation=-1),self.service.states)
        self.assertEqual(self.service.sink.metrics['rejected_observations'],1)
    async def test_attendance_config_candidate_quota_clock_gates(self):
        runtime=self.service.runtime_id;digest=self.service.digest
        self.store.subscribers.clear();self.assertIsNone(self.service.recovery_reason())
        self.store.subscribers.add(self.queue)
        self.service.config_loader=lambda:dict(DEFAULT,sports=['MLB'])
        self.assertEqual(self.service.recovery_reason(),'configuration_changed');self.service.config_loader=None
        with patch('app.collection.current_service.candidate',return_value=('new',{})):
            with self.assertRaises(SelectionError):await self.service.recover(runtime,digest)
        self.service.clock_wall-=180;self.assertEqual(self.service.recovery_reason(),'clock_continuity_unknown');self.service.clock_wall+=180
        aid=self.q.reserve(self.service.ownership,digest,{},3)
        self.q.dispatched(aid,self.service.ownership)
        self.assertEqual(self.service.recovery_reason(),'ambiguous_dispatch_unresolved')
        self.assertEqual(self.q.snapshot()['reserved'],3)
    async def test_shared_pause_independent_native_and_idempotent_stop(self):
        await self.service.pause('the_odds_api');await self.service.pause('the_odds_api')
        self.assertEqual(self.service.states['novig']['state'],'stopped');self.assertEqual(self.service.states['prophetx']['state'],'stopped')
        self.assertFalse(self.service.workers['kalshi'].closed)
        await self.service.close();await self.service.close();self.assertTrue(self.service.cleanup_complete)
    async def test_cancellation_resistant_cleanup_returns_bounded_conflict(self):
        release=asyncio.Event()
        async def resistant():
            try:await release.wait()
            except asyncio.CancelledError:await release.wait()
        self.service.config['cleanup_seconds']=1
        self.service.workers['kalshi'].close=resistant
        started=time.monotonic()
        with self.assertRaises(SelectionError):await self.service.recover(self.service.runtime_id,self.service.digest)
        self.assertLess(time.monotonic()-started,3)
        self.assertTrue(self.service.ownership.file);self.assertFalse(self.service.dispatch)
        self.assertEqual(self.service.recovery_reason(),'cleanup_safety_unresolved')
        release.set();await asyncio.gather(*self.service.client_cleanup_tasks.values(),return_exceptions=True)
        self.assertEqual(self.service.recovery_reason(),'cleanup_safety_unresolved')

    async def test_retained_issue_reopen_suppresses_disk_prose(self):
        self.service.issue('kalshi','authentication','http_401')
        path=self.root/'authority/issues.json'
        rows=json.loads(path.read_text());rows[0]['impact']='SECRET disk text';rows[0]['site']='https://evil.example/SECRET'
        path.write_text(json.dumps(rows))
        from app.collection.current_admin import retained_issues
        sanitized=retained_issues(self.service)
        self.assertEqual(len(sanitized),1);self.assertNotIn('SECRET',json.dumps(sanitized))
        self.assertEqual(sanitized[0]['first_at'],rows[0]['first_at'])
        self.assertEqual(sanitized[0]['runtime_id'],rows[0]['runtime_id'])
    async def test_corrupt_unknown_expired_window_block_without_mutation(self):
        old=self.window;self.window=None
        self.assertEqual(self.service.recovery_reason(),'reset_window_evidence_unverified');self.window=old
        self.q.failed='quota_missing_duplicate_or_malformed'
        self.assertEqual(self.service.recovery_reason(),'quota_missing_duplicate_or_malformed');self.q.failed=None
        path=self.root/'quota/quota.json';path.write_text('corrupt')
        status=self.service.status()
        self.assertIsNone(status['quota']['used']);self.assertEqual(status['quota']['ceiling'],500)
        self.assertEqual(self.service.recovery_reason(),'quota_ledger_unavailable');self.assertEqual(path.read_text(),'corrupt')

    async def test_routes_assets_security_status_and_conflict(self):
        # App starts the already-started service without a duplicate worker.
        async with TestClient(TestServer(create_app(owner=owner(),sessions={},current_provider=self.service))) as c:
            origin=str(c.make_url('/')).rstrip('/')
            for path in ('/admin','/api/admin/status','/current/assets/admin.js','/current/assets/admin.css','/api/admin/u4-issue'):
                r=await c.get(path);self.assertEqual(r.status,200);self.assertIn('Content-Security-Policy',r.headers)
            self.assertEqual((await c.post('/api/admin/current',json={'action':'recover'})).status,403)
            r=await c.post('/api/admin/current',headers={'Origin':origin},json=dict(action='recover',runtime_id='old',candidate_digest=self.service.digest))
            self.assertEqual(r.status,409)
            self.assertEqual((await c.get('/api/admin/status',headers={'Host':'evil.example'})).status,403)
