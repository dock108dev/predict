"""Focused immutable-approval, dynamic evidence and bounded accounting checks."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from tests.integrated_acquisition_package import Fixture as PriorFixture
from app.collection.acquisition_policy import policy,StartupBudget,request_cost,totals
from app.collection.native_approval import validate_approval,digest
from app.collection.venue_access import ENDPOINTS
from app.collection.source_session import validate
from app.collection.transport_session import reopen

PACKAGE=Path(__file__).resolve().parents[1]/'evidence/integrated-acquisition-r2-20260929'

def configuration():return json.loads((PACKAGE/'run-spec.json').read_text())

def headers(used=20,remaining=1000,last=0):
    return [(k,str(v)) for k,v in zip(('x-requests-used','x-requests-remaining','x-requests-last'),(used,remaining,last))]

class Fixture(PriorFixture):
    def __init__(self,fault=None):
        super().__init__();self.fault=fault;self.used=20;self.base_quota=1020;self.entered=asyncio.Event();self.release=asyncio.Event()
    async def boot(self,path):
        o=await super().boot(path)
        def factory():s=configuration();s['mode']='mock';return s
        o.spec_factory=factory
        return o
    async def rest(self,req):
        if req.path=='/v4/sports':
            self.odds_calls.append((req.path,dict(req.query)));self.entered.set()
            if self.fault=='blocked_startup':await self.release.wait()
            h=dict(headers(remaining=10 if self.fault=='insufficient' else 1000,last=1 if self.fault=='charged_startup' else 0))
            if self.fault=='missing_quota':h={}
            return web.json_response({} if self.fault=='malformed_startup' else [],headers=h)
        if req.path.startswith('/v4/'):
            from app.reference.product import SPORT_KEYS
            self.sport=next(k for k,v in SPORT_KEYS.items() if '/'+v+'/' in req.path)
            odds=req.path.endswith('/odds');self.odds_calls.append((req.path,dict(req.query)))
            if odds:
                self.requested=req.query['markets'].split(',');self.rounds[self.sport]=self.rounds.get(self.sport,0)+1
            cost=len(self.requested) if odds else 0
            if odds and self.fault=='absent_markets':cost=0
            if odds and self.fault=='unexpected_charge':cost+=1
            self.used+=cost
            h=dict(headers(self.used,self.base_quota-self.used,cost))
            if odds and self.fault=='missing_paid_quota':h={}
            body=self.body() if odds else ([] if self.fault=='absent_events' else [self.event()])
            if odds and self.fault=='absent_markets':body['bookmakers']=[]
            if odds and self.fault=='body_charge_mismatch':body['bookmakers']=[]
            if odds and self.fault=='recovery':return web.json_response({'error':'SIMULATED 503'},status=503,headers=h)
            return web.json_response(body,headers=h)
        return await super().rest(req)
    async def start(self,duration=30,fast=True):
        cfg=configuration()['source_session']
        if fast:cfg['refresh_seconds']=1
        resp=await self.client.post('/api/start',json=dict(duration=duration,source_settings=cfg),headers=self.origin)
        assert resp.status==200,await resp.text()
        saved=self.owner.session.journal.save
        def observe(row):saved(row);self.books+=row['type']=='prediction_book';self.changed.set()
        self.owner.session.journal.save=observe
    async def close(self):self.release.set();await super().close()

class Accounting(unittest.TestCase):
    def test_catalog_metadata_scope_and_legacy_behavior(self):
        from tests.test_coverage import page,pe,AS_OF
        from app.collection.coverage import catalog
        e=pe();p=page('polymarket_us',{'events':[e]});p['params'].pop('tagSlug')
        self.assertEqual(catalog([p],'polymarket_us',AS_OF)['events'][0]['exclusion'],'event_parse_error')
        p['acquisition_discovery_policy']='bounded-open-catalog-v1'
        self.assertEqual(catalog([p],'polymarket_us',AS_OF)['events'][0]['competition'],'NFL')
        e['teams'][1]['league']='nba'
        p=page('polymarket_us',{'events':[e]});p['params'].pop('tagSlug');p['acquisition_discovery_policy']='bounded-open-catalog-v1'
        self.assertEqual(catalog([p],'polymarket_us',AS_OF)['events'][0]['exclusion'],'event_parse_error')
    def test_matrix_independent_sums_and_no_retry_refunds(self):
        s=configuration()['source_session'];rows=json.loads((PACKAGE/'request-matrix.json').read_text())
        self.assertEqual(len(rows),37);self.assertEqual(sum(r['reserve_credits'] for r in rows),135)
        self.assertEqual(totals(s),dict(startup=1,discovery=18,paid=18,requests=37,credits=135))
        b=StartupBudget(policy(s));b.reserve(0);b.reconcile(headers())
        for row in rows[1:]:
            request={'path':row['path'].replace('{selected_id}','observed-event'),'params':row['params']}
            cost=request_cost(s,request);self.assertEqual(cost,row['reserve_credits']);b.reserve(cost)
            # Zero reported charge never restores the reserved allowance.
            b.reconcile(headers())
        self.assertEqual((b.requests,b.credits,b.remaining),(37,135,865))
        from app.collection.odds_http import BudgetStop
        with self.assertRaises(BudgetStop):b.reserve(6)
    def test_scope_mismatch_and_dynamic_fields_rejected(self):
        s=configuration()['source_session'];row=json.loads((PACKAGE/'request-matrix.json').read_text())[2]
        target=dict(path=row['path'].replace('{selected_id}','E'),params=deepcopy(row['params']))
        target['params']['bookmakers']+=',another-book'
        with self.assertRaises(ValueError):request_cost(s,target)
        for key,val in [('quota_observed_at',datetime.now(timezone.utc).isoformat()),('native_selection',{})]:
            v=deepcopy(s);v[key]=val
            with self.assertRaises(ValueError):validate(v)
        v=deepcopy(s);v['http']['credits']=134
        with self.assertRaises(ValueError):validate(v)
    def test_approval_binds_static_spec_without_quota_or_event_ids(self):
        s=configuration();ep={**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'}
        with tempfile.TemporaryDirectory() as root,patch('app.collection.native_approval.implementation',return_value={'fixture':'hash'}):
            p=Path(root)/'approval.json'
            p.write_text(json.dumps(dict(approved=True,spec_sha256=digest(s),implementation_sha256=digest({'fixture':'hash'}),output=str(Path(root).resolve()))))
            validate_approval(s,ep,p,root)
            for key,val in [('duration',179),('start_before','2026-10-08T00:00:00Z')]:
                changed=deepcopy(s);changed[key]=val
                with self.assertRaises(ValueError):validate_approval(changed,ep,p,root)
            changed=deepcopy(s);changed['source_session']['scopes'][0]['markets'].pop()
            with self.assertRaises(ValueError):validate_approval(changed,ep,p,root)
            validate_approval(s,ep,p,root,consume=True)
            with self.assertRaises(ValueError):validate_approval(s,ep,p,root)
    def test_missing_baseline_and_unexpected_billing(self):
        from app.collection.odds_http import BudgetStop
        b=StartupBudget(policy(configuration()['source_session']))
        with self.assertRaises(BudgetStop):b.reserve(6)
        b.reserve(0);b.reconcile(headers());b.reserve(6)
        b.reconcile(headers(27,993,7));self.assertEqual(b.reason,'quota_contradictory')
        with self.assertRaises(BudgetStop):b.reserve(0)

class Runtime(unittest.IsolatedAsyncioTestCase):
    async def test_native_recovery_caps_reject_before_network(self):
        from app.collection.continuous import REST
        from app.collection.prediction_producer import PredictionBudget
        from app.collection.odds_http import BudgetStop
        from app.collection.acquisition_policy import NATIVE_REQUEST_CAPS
        for cap in NATIVE_REQUEST_CAPS.values():
            limits=configuration()['prediction'];budget=PredictionBudget(limits);budget.requests=cap
            client=REST('http://127.0.0.1:9',limits,lambda r:None,1,budget)
            client.request_ceiling=cap
            with patch('aiohttp.ClientSession',side_effect=AssertionError('No dispatch beyond cap')):
                with self.assertRaises(BudgetStop):await client.get('http://127.0.0.1:9/events')

    async def run_case(self,fault):
        with tempfile.TemporaryDirectory() as root,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
            f=Fixture(fault);o=await f.boot(root)
            try:
                await f.start();await f.native_images()
                await f.wait(lambda:o.session.aggregate.health in ('completed','unavailable'))
                if fault in ('missing_quota','insufficient','charged_startup','malformed_startup'):
                    self.assertEqual(len(f.odds_calls),1);self.assertFalse(o.session.projection.aggregates)
                elif fault in ('unexpected_charge','missing_paid_quota','body_charge_mismatch'):
                    self.assertEqual(len(f.odds_calls),3);self.assertFalse(o.session.projection.aggregates)
                elif fault=='absent_events':
                    await f.wait(lambda:o.session.aggregate.health=='completed');self.assertEqual(len(f.odds_calls),7)
                elif fault in ('recovery','absent_markets'):
                    await f.wait(lambda:o.session.aggregate.poll==3 and len(f.odds_calls)==37)
                    self.assertEqual(o.session.aggregate.budget.credits,135)
                    await f.wait(lambda:o.session.aggregate.health=='completed')
                else:
                    await f.wait(lambda:o.session.aggregate.health=='completed')
                    self.assertEqual(len(f.odds_calls),37);self.assertEqual(o.session.aggregate.budget.credits,135)
                self.assertEqual(o.session.state,'running')
                self.assertEqual(len(o.current_snapshot()['aggregate_coverage']),63)
                await f.stop_route();self.assertIsNone(o.error)
                before=len(f.odds_calls);await asyncio.sleep(.05);self.assertEqual(len(f.odds_calls),before)
                rows=reopen(o.session.journal.path)['rows']
                if fault not in ('missing_quota','insufficient','charged_startup','malformed_startup'):
                    self.assertEqual(sum(r['type']=='aggregate_quota_baseline' for r in rows),1)
                self.assertTrue(o.session.cleanup_complete)
            finally:await f.close()
    async def test_missing_quota(self):await self.run_case('missing_quota')
    async def test_malformed_startup(self):await self.run_case('malformed_startup')
    async def test_response_market_billing_contradiction(self):await self.run_case('body_charge_mismatch')
    async def test_insufficient(self):await self.run_case('insufficient')
    async def test_startup_charge(self):await self.run_case('charged_startup')
    async def test_unexpected_paid_charge(self):await self.run_case('unexpected_charge')
    async def test_uncertain_paid_charge(self):await self.run_case('missing_paid_quota')
    async def test_absent_events(self):await self.run_case('absent_events')
    async def test_absent_markets(self):await self.run_case('absent_markets')
    async def test_exhausted_recovery_budget(self):await self.run_case('recovery')
    async def test_success(self):await self.run_case(None)
    async def test_interrupted_startup(self):
        with tempfile.TemporaryDirectory() as root:
            f=Fixture('blocked_startup');o=await f.boot(root)
            try:
                s=configuration();p=Path(root)/'SIMULATED-approval.json'
                with patch('app.collection.native_approval.implementation',return_value={'fixture':'hash'}):
                    p.write_text(json.dumps(dict(approved=True,spec_sha256=digest(s),implementation_sha256=digest({'fixture':'hash'}),output=str(o.pilot_output.resolve()))))
                    validate_approval(s,{**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'},p,o.pilot_output,consume=True)
                await f.start();await asyncio.wait_for(f.entered.wait(),3)
                await f.stop_route();self.assertIsNone(o.error)
                rows=reopen(o.session.journal.path)['rows']
                self.assertTrue(any(r.get('reason')=='incomplete_capture_cancelled' for r in rows))
                self.assertFalse(any(r['type']=='aggregate_quota_baseline' for r in rows))
                self.assertEqual(len(f.odds_calls),1)
                self.assertTrue((o.pilot_output/'b3-attempt.json').exists())
            finally:await f.close()
