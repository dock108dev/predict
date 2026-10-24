"""Conservative recovery controls on disposable ledgers; fictional provider I/O."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.collection.current_quota import QuotaLedger, QuotaStop
from app.collection.current_conservative import digest, pending_reason, POLICY
from app.collection.local_ownership import LocalOwnership
from app.collection.current_account_recovery import credential_binding, observe_and_activate
from app.dashboard.current_contract import stamp
from tests.test_current_quota import WINDOW

CANDIDATE='b'*64
REQUEST=dict(path='/v4/sports/icehockey_nhl/odds',params={})
def counters(used,last=0):return [['x-requests-used',str(used)],['x-requests-remaining',str(100000-used)],['x-requests-last',str(last)]]

class ConservativeRecovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.at='2026-10-03T14:00:00+00:00'
        self.owner=LocalOwnership(self.root/'owner');self.owner.acquire('CONTROLLED-old')
        self.q=QuotaLedger(self.root/'quota',clock=lambda:self.at)
        self.q.transact(lambda v,at:v.update(account_id='CONTROLLED-account',ceiling=100000))
        self.q.bind_window(WINDOW)
        bid=self.q.reserve(self.owner,CANDIDATE,dict(path='/v4/sports',params={}),0,bootstrap=True)
        self.q.dispatched(bid,self.owner);self.q.reconcile(bid,counters(622))
        self.aid=self.q.reserve(self.owner,CANDIDATE,REQUEST,3);self.q.dispatched(self.aid,self.owner)
        self.q.record_response(self.aid,None,interruption='aggregate_cancelled_after_dispatch')
        self.old=deepcopy(self.q._read()['attempts'][self.aid]);self.covered={self.aid:digest(self.old)}
        self.owner.release();self.owner.acquire('CONTROLLED-recovery')
        self.at='2026-10-03T14:03:00+00:00'
        (self.root/'.env').write_text('CONTROLLED secret never copied to evidence')
        os.utime(self.root/'.env',(stamp(WINDOW['starts_at']).timestamp(),)*2)
        self.binding=credential_binding(self.root)
        (self.root/'.local').mkdir();(self.root/'.local/predict-odds-account.json').write_text(json.dumps({'account_id':'CONTROLLED-account'}))
    def tearDown(self):self.owner.release();self.temp.cleanup()
    def evidence(self,used=650,**changes):
        e=dict(schema='predict-independent-balance-1',id='CONTROLLED-evidence',purpose=POLICY,recovery_id='CONTROLLED-recovery',
            runtime_id='CONTROLLED-recovery',candidate_digest=CANDIDATE,endpoint='https://api.the-odds-api.com/v4/sports',method='GET',params={},
            account_id='CONTROLLED-account',window=WINDOW,status=200,headers=counters(used),received_at=self.at,
            retries=0,documented_cost=0,credential_reference='.env',credential_binding=self.binding,credential_unchanged_since_snapshot=True)
        e.update(changes);return e
    def activate(self,e=None,covered=None,identity='CONTROLLED-recovery'):
        return self.q.activate_conservative(self.owner,CANDIDATE,self.covered if covered is None else covered,
            e or self.evidence(),identity,self.binding)
    def due(self):self.at='2026-10-03T20:00:00+00:00'
    def reserve_cycle(self,requests=None):
        requests=requests or [REQUEST]
        cid=self.q.begin_cycle(self.owner,requests)
        aid=self.q.reserve(self.owner,CANDIDATE,requests[0],3,cycle_id=cid)
        return aid,cid
    def test_legacy_refuses_and_exact_coverage_preserves_lost_fields(self):
        with self.assertRaisesRegex(QuotaStop,'unresolved'):self.q.prepare_clock(self.owner,CANDIDATE,WINDOW,cleanup_safe=True)
        self.activate();v=self.q._read();s=self.q.snapshot()
        self.assertEqual(v['attempts'][self.aid],self.old);self.assertEqual(s['held_uncertain_credits'],3)
        self.assertEqual(s['available'],99297);self.assertEqual(s['covered_uncertain_attempts'],1)
        self.assertIsNone(s['blocking_reason']);self.assertIsNone(self.q.recovery_reason(WINDOW))
        self.assertEqual(v['conservative_recoveries'][0]['covered'][self.aid]['original'],self.old)
        self.assertEqual(v['conservative_recoveries'][0]['prior']['next_due_at'],'2026-10-03T20:00:00+00:00')
    def test_import_rejects_context_headers_and_bad_authentication_atomically(self):
        before=(self.q.directory/'quota.json').read_bytes()
        changes=[dict(status=401),dict(account_id='other'),dict(window=dict(WINDOW,id='other')),dict(candidate_digest='c'*64),
            dict(runtime_id='other'),dict(credential_unchanged_since_snapshot=False),dict(documented_cost=3),dict(retries=1),dict(method='POST'),
            dict(headers=counters(650)+[['x-requests-used','650']]),dict(headers=[['x-requests-used','bad']]),dict(headers=counters(651,3)),
            dict(headers=counters(600)),dict(received_at='2026-10-03T14:03:01+00:00'),dict(received_at='2026-10-03T13:57:59+00:00')]
        for c in changes:
            with self.subTest(c=c),self.assertRaises(QuotaStop):self.activate(self.evidence(**c))
            self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)
        with self.assertRaisesRegex(QuotaStop,'credential_changed'):self.activate(self.evidence(credential_binding={}))
    def test_active_reserved_hash_and_exact_set_refusals(self):
        for coverage in ({},{self.aid:'a'*64},{self.aid:digest(self.old),'extra':'a'*64}):
            with self.assertRaisesRegex(QuotaStop,'coverage'):self.activate(covered=coverage)
        self.q.transact(lambda v,at:v['attempts'][self.aid].update(state='reserved'))
        with self.assertRaisesRegex(QuotaStop,'active_transport'):self.activate(covered={self.aid:digest(self.q._read()['attempts'][self.aid])})
    def test_live_uncertain_request_cannot_be_covered(self):
        self.q.transact(lambda v,at:v['attempts'][self.aid].update(runtime_id='CONTROLLED-recovery',interruption=None))
        with self.assertRaisesRegex(QuotaStop,'active_transport'):self.activate(covered={self.aid:digest(self.q._read()['attempts'][self.aid])})
    def test_unrelated_pause_and_changed_account_history_refuse(self):
        self.q.pause('aggregate_authentication')
        with self.assertRaisesRegex(QuotaStop,'authentication'):self.activate()
        self.q.pause(None);self.q.transact(lambda v,at:v.update(account_transitions=[dict(at=at)]))
        with self.assertRaisesRegex(QuotaStop,'context'):self.activate()
    def test_server_error_without_quota_headers_preserves_exact_unknown_charge(self):
        receipt=dict(status=502,headers=[],received_at='2026-10-03T14:00:01+00:00')
        self.q.reconcile(self.aid,[],received_at=receipt['received_at'])
        self.q.record_response(self.aid,receipt)
        old=deepcopy(self.q._read()['attempts'][self.aid]);self.covered={self.aid:digest(old)}
        self.activate()
        self.assertEqual(self.q._read()['attempts'][self.aid],old)
        self.assertEqual(self.q.snapshot()['held_uncertain_credits'],3)
        self.assertIsNone(self.q.snapshot()['blocking_reason'])
    def test_missing_headers_on_success_authentication_or_partial_headers_stay_blocked(self):
        for status,items in ((200,[]),(401,[]),(429,[]),(502,[['x-requests-used','622']])):
            with self.subTest(status=status,items=items):
                self.q.reconcile(self.aid,items,received_at='2026-10-03T14:00:01+00:00')
                self.q.transact(lambda v,at:v['attempts'][self.aid].update(
                    response_receipt=dict(status=status,headers=items,received_at='2026-10-03T14:00:01+00:00')))
                covered={self.aid:digest(self.q._read()['attempts'][self.aid])}
                before=(self.q.directory/'quota.json').read_bytes()
                with self.assertRaisesRegex(QuotaStop,'quota_missing_duplicate_or_malformed'):
                    self.activate(covered=covered)
                self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)
    def test_duplicate_activation_and_atomic_persistence_failure(self):
        before=(self.q.directory/'quota.json').read_bytes()
        with patch('app.collection.current_quota.os.replace',side_effect=OSError('CONTROLLED')):
            with self.assertRaisesRegex(QuotaStop,'persistence'):self.activate()
        self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)
        self.q.failed=None;self.activate();before=(self.q.directory/'quota.json').read_bytes()
        with self.assertRaisesRegex(QuotaStop,'already_activated'):self.activate()
        self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)
    def test_allowance_cycle_preflight_owned_reservation_and_no_double_subtraction(self):
        self.activate();self.due();aid,cid=self.reserve_cycle()
        self.assertEqual(self.q.snapshot()['available'],99294)
        with self.assertRaisesRegex(QuotaStop,'unresolved'):self.q.reserve(self.owner,CANDIDATE,REQUEST,3,cycle_id=cid)
        self.q.dispatched(aid,self.owner);self.assertEqual(self.q.snapshot()['available'],99294)
        self.q.reconcile(aid,counters(653,3))
        self.assertEqual(self.q.snapshot()['available'],99294);self.assertEqual(self.q.snapshot()['reserved'],3)
        self.assertEqual(self.q._read()['attempts'][self.aid],self.old)
    def test_cycle_boundary_and_external_usage(self):
        self.activate(self.evidence(99944));self.due()
        with self.assertRaisesRegex(QuotaStop,'exhausted'):self.q.begin_cycle(self.owner,[REQUEST,dict(REQUEST,path='/second')])
        aid,_=self.reserve_cycle();self.q.dispatched(aid,self.owner);self.q.reconcile(aid,counters(99948,3))
        self.assertEqual(self.q.snapshot()['available'],0);self.assertEqual(self.q.snapshot()['reserved'],3)
    def test_new_uncertainty_blocks_without_extending_old_authority(self):
        self.activate();self.due();aid,_=self.reserve_cycle();self.q.dispatched(aid,self.owner)
        self.q.record_response(aid,None,interruption='aggregate_transport_uncertain')
        self.assertEqual(self.q.snapshot()['covered_uncertain_attempts'],1);self.assertEqual(self.q.snapshot()['reserved'],6)
        self.assertEqual(self.q.recovery_reason(WINDOW),'ambiguous_dispatch_unresolved')
        self.at='2026-10-03T20:15:00+00:00'
        with self.assertRaisesRegex(QuotaStop,'unresolved'):self.q.begin_cycle(self.owner,[REQUEST])
        with self.assertRaisesRegex(QuotaStop,'coverage'):self.activate(self.evidence(recovery_id='new'),identity='new')
    def test_reopen_stop_and_changed_context_cannot_inherit_coverage(self):
        self.activate();q=QuotaLedger(self.q.directory,clock=lambda:self.at)
        self.assertIsNone(q.recovery_reason(WINDOW));self.assertEqual(q.snapshot()['reserved'],3)
        self.owner.release()
        with self.assertRaisesRegex(QuotaStop,'ownership'):q.reserve(self.owner,CANDIDATE,REQUEST,3)
        self.owner.acquire('CONTROLLED-recovery')
        self.q.transact(lambda v,at:v.update(account_id='other'))
        self.assertEqual(q.recovery_reason(WINDOW),'ambiguous_dispatch_unresolved')
    def test_audit_tamper_fails_closed_even_if_outer_envelope_resealed(self):
        self.activate();v=self.q._read();v['conservative_recoveries'][0]['covered'][self.aid]['original']['cost']=0
        self.q._write(v);self.assertEqual(self.q.snapshot()['pause'],'quota_ledger_unavailable')
    def test_late_receipt_separate_from_original_and_duplicate_release_once(self):
        self.activate();self.due();before=self.q.snapshot()
        receipt=dict(status=200,received_at='2026-10-03T14:00:01+00:00',headers=counters(625,3))
        self.q.record_response(self.aid,receipt);self.q.reconcile(self.aid,receipt['headers'])
        after=self.q.snapshot();a=self.q._read()['attempts'][self.aid]
        self.assertEqual(after['used'],before['used']);self.assertEqual(after['available'],before['available']+3)
        self.assertIsNone(a['response_receipt']);self.assertEqual(a['charged'],3);self.assertTrue(a['balance_inclusion']['established'])
        self.q.reconcile(self.aid,receipt['headers']);self.q.record_response(self.aid,receipt)
        self.assertEqual(self.q.snapshot()['available'],after['available'])
        self.assertEqual(self.q._read()['conservative_recoveries'][0]['covered'][self.aid]['original'],self.old)
    def test_late_receipt_needs_identity_and_retains_exposure_until_balance_covers(self):
        self.activate();self.due()
        with self.assertRaisesRegex(QuotaStop,'identity_required'):self.q.reconcile(self.aid,counters(625,3))
        receipt=dict(status=200,received_at='2026-10-03T14:00:01+00:00',headers=counters(660,3))
        self.q.record_response(self.aid,receipt);self.q.reconcile(self.aid,receipt['headers'])
        self.assertEqual(self.q.snapshot()['reserved'],3);self.assertEqual(self.q.snapshot()['used'],650)
        aid,_=self.reserve_cycle();self.q.dispatched(aid,self.owner);self.q.reconcile(aid,counters(663,3))
        self.assertEqual(self.q.snapshot()['reserved'],0);self.assertEqual(self.q.snapshot()['used'],663)
    def test_changed_reset_stays_blocked_and_schedule_never_catches_up(self):
        self.activate();self.assertEqual(self.q.snapshot()['next_due_at'],'2026-10-03T20:00:00+00:00')
        self.at='2026-11-02T14:00:00+00:00'
        with self.assertRaisesRegex(QuotaStop,'unresolved'):self.q.bind_window(dict(WINDOW,id='next',starts_at='2026-11-01T00:00:00+00:00',ends_at='2026-12-01T00:00:00+00:00'))
        with self.assertRaises(QuotaStop):self.q.reserve(self.owner,CANDIDATE,REQUEST,3)
    def test_competing_owner_and_clock_refusals(self):
        self.activate();self.due();aid,_=self.reserve_cycle()
        other=LocalOwnership(self.root/'other');other.acquire('CONTROLLED-other')
        try:
            with self.assertRaisesRegex(QuotaStop,'owner_conflict'):self.q.dispatched(aid,other)
        finally:other.release()
        self.at='2026-10-03T13:00:00+00:00'
        with self.assertRaisesRegex(QuotaStop,'regression'):self.q.dispatched(aid,self.owner)
    def test_additional_lost_request_requires_new_exact_recovery_transaction(self):
        self.activate();self.due();aid,_=self.reserve_cycle();self.q.dispatched(aid,self.owner)
        self.q.record_response(aid,None,interruption='aggregate_transport_uncertain');self.q.pause('aggregate_transport_uncertain')
        self.at='2026-10-03T20:03:00+00:00'
        covered={k:digest(a) for k,a in self.q._read()['attempts'].items() if a['state']=='uncertain'}
        self.activate(self.evidence(653,recovery_id='new-reviewed'),covered=covered,identity='new-reviewed')
        self.assertEqual(self.q.snapshot()['covered_uncertain_attempts'],2);self.assertEqual(self.q.snapshot()['reserved'],6)
        self.assertEqual(len(self.q.snapshot()['recovery_authority']),2)

    def test_covered_uncertainty_survives_evidenced_os_restart(self):
        self.activate()
        mono=[100.0];boot=[dict(id='CONTROLLED-boot-a',started_at='2026-10-03T14:01:20+00:00',uptime=100)]
        self.q.monotonic=lambda:mono[0];self.q.boot_loader=lambda:deepcopy(boot[0])
        self.q.transact(lambda v,at:None)
        self.at='2026-10-04T14:00:00+00:00';mono[0]=60
        boot[0]=dict(id='CONTROLLED-boot-b',started_at='2026-10-04T13:59:00+00:00',uptime=60)
        self.q.prepare_clock(self.owner,CANDIDATE,WINDOW,cleanup_safe=True)
        with self.assertRaisesRegex(QuotaStop,'refresh_required'):self.q.reserve(self.owner,CANDIDATE,REQUEST,3)
        aid=self.q.reserve(self.owner,CANDIDATE,dict(path='/v4/sports',params={}),0,bootstrap=True)
        self.q.dispatched(aid,self.owner);self.q.reconcile(aid,counters(660))
        self.assertEqual(self.q.snapshot()['accounting_epoch']['state'],'current')
        self.assertEqual(self.q.snapshot()['reserved'],3);self.assertEqual(self.q.snapshot()['covered_uncertain_attempts'],1)
    def test_related_lost_transport_can_receive_fresh_exact_audit(self):
        self.q.transact(lambda v,at:v['attempts'][self.aid].update(interruption='aggregate_transport_uncertain'))
        self.covered={self.aid:digest(self.q._read()['attempts'][self.aid])}
        self.q.pause('aggregate_transport_uncertain');self.activate()
        self.assertIsNone(self.q.snapshot()['pause']);self.assertEqual(self.q.snapshot()['reserved'],3)
    def test_confirmed_charge_without_balance_inclusion_blocks_reset_transition(self):
        self.activate();self.due()
        receipt=dict(status=200,received_at='2026-10-03T14:00:01+00:00',headers=counters(660,3))
        self.q.record_response(self.aid,receipt);self.q.reconcile(self.aid,receipt['headers'])
        self.at='2026-11-02T14:00:00+00:00'
        with self.assertRaisesRegex(QuotaStop,'unresolved'):self.q.bind_window(dict(WINDOW,id='next',starts_at='2026-11-01T00:00:00+00:00',ends_at='2026-12-01T00:00:00+00:00'))

    def test_skip_missed_slots_records_original_due_in_audit(self):
        self.at='2026-10-03T20:02:00+00:00';self.activate()
        self.assertEqual(self.q.snapshot()['next_due_at'],'2026-10-03T20:15:00+00:00')
        self.assertEqual(self.q._read()['conservative_recoveries'][0]['prior']['next_due_at'],'2026-10-03T20:00:00+00:00')

    def test_proven_owned_ingress_repair_preserves_existing_coverage_only(self):
        from hashlib import sha256
        self.activate();self.due();aid,_=self.reserve_cycle();self.q.dispatched(aid,self.owner)
        receipt=dict(status=200,headers=counters(653,3),received_at=self.at)
        self.q.reconcile(aid,receipt['headers']);self.q.record_response(aid,receipt)
        self.q.pause('aggregate_admission_failed')
        path=self.root/'replay.json';path.write_text(json.dumps(dict(candidate_digest=CANDIDATE,attempt_id=aid,repair='database_ingress_wire_bytes',replay_verified=True,ingress_admitted=1,provider_requests=0,received_at=self.at)))
        evidence=dict(replay_verified=True,path=str(path),sha256=sha256(path.read_bytes()).hexdigest(),
            attempt_id=aid,repair='database_ingress_wire_bytes')
        before=self.q._read()
        with patch('app.collection.current_policy.candidate',return_value=(CANDIDATE,{})),patch('app.collection.current_account_recovery.credential_binding',return_value=self.binding),patch('app.collection.current_quota.load_window',return_value=WINDOW):
            with self.assertRaisesRegex(QuotaStop,'ownership'):self.q.repair_admission(evidence,candidate=CANDIDATE)
            with self.assertRaisesRegex(QuotaStop,'evidence'):self.q.repair_admission(dict(evidence,sha256='0'*64),owner=self.owner,candidate=CANDIDATE)
            self.q.repair_admission(evidence,owner=self.owner,candidate=CANDIDATE)
        after=self.q._read()
        for key in ('attempts','conservative_recoveries','account_transitions','observation','next_due_at'):
            self.assertEqual(before.get(key),after.get(key))
        self.assertEqual(self.q.snapshot()['reserved'],3);self.assertIsNone(self.q.snapshot()['blocking_reason'])
        self.assertEqual(len(after['admission_repairs']),1)
        self.q.pause('aggregate_authentication')
        with self.assertRaisesRegex(QuotaStop,'pause_mismatch'):self.q.repair_admission(evidence,owner=self.owner,candidate=CANDIDATE)

class RecoveryTransport(unittest.IsolatedAsyncioTestCase):
    setUp=ConservativeRecovery.setUp
    tearDown=ConservativeRecovery.tearDown
    async def observe(self,wire,identity='CONTROLLED-recovery'):
        return await observe_and_activate(self.q,self.owner,CANDIDATE,self.covered,identity,root=self.root,transport=wire,
            key_loader=lambda:'CONTROLLED-key',window_loader=lambda:WINDOW)
    def wire(self,fail=False):
        fixture=self
        class Wire:
            calls=0;closed=False;response_receipt=None
            async def request(self,req,key):
                self.calls+=1
                assert req==dict(path='/v4/sports',params={})
                if fail:raise TimeoutError('CONTROLLED-secret')
                self.response_receipt=dict(status=200,headers=counters(650),received_at=fixture.at)
                return dict(self.response_receipt,body=b'[{"key":"americanfootball_nfl","active":true,"has_outrights":false}]')
            async def close(self):self.closed=True
        return Wire()
    async def test_single_free_observation_activation_and_no_duplicate_probe(self):
        wire=self.wire();q=await self.observe(wire)
        self.assertEqual(wire.calls,1);self.assertTrue(wire.closed);self.assertEqual(q['reserved'],3)
        self.assertEqual(q['recovery_probes'][0]['state'],'activated')
        self.assertEqual(self.q._read()['attempts'][self.aid],self.old)
        with self.assertRaisesRegex(QuotaStop,'already_activated'):await self.observe(self.wire())
        self.assertEqual(len(list((self.q.directory/'independent-balances').glob('*.json'))),1)
    async def test_failed_observation_retains_pause_and_original_history_without_retry(self):
        wire=self.wire(True)
        with self.assertRaisesRegex(QuotaStop,'observation_failed'):await self.observe(wire)
        self.assertEqual(wire.calls,1);self.assertTrue(wire.closed)
        self.assertEqual(self.q.snapshot()['pause'],'recovery_observation_failed');self.assertEqual(self.q.snapshot()['reserved'],3)
        self.assertEqual(self.q._read()['attempts'][self.aid],self.old)
        self.assertNotIn('CONTROLLED-secret',json.dumps(self.q._read()))
    async def test_changed_credential_and_unrelated_failure_prevent_probe(self):
        (self.root/'.env').write_text('CONTROLLED-changed')
        wire=self.wire()
        with self.assertRaisesRegex(QuotaStop,'credential_changed'):await self.observe(wire)
        self.assertEqual(wire.calls,0)
    async def test_unsafe_observation_cleanup_preserves_failure_and_blocks_dispatch(self):
        wire=self.wire()
        async def fail_close():raise OSError('CONTROLLED secret cleanup')
        wire.close=fail_close
        with self.assertRaisesRegex(QuotaStop,'cleanup_safety_unresolved'):await self.observe(wire)
        self.assertEqual(self.q.snapshot()['pause'],'cleanup_safety_unresolved')
        self.assertEqual(self.q.snapshot()['reserved'],3);self.assertIsNotNone(self.owner.file)

    async def test_ordinary_owned_scheduler_finishes_with_covered_hold(self):
        await self.observe(self.wire());self.at='2026-10-03T20:00:00+00:00'
        from app.collection.current_aggregate import AggregateScheduler
        from types import SimpleNamespace
        import time
        svc=SimpleNamespace(dispatch=True,ownership=self.owner,digest=CANDIDATE,deadline=time.monotonic()+100,store=SimpleNamespace(closed=False),
            observation=lambda *a:None,config={'cleanup_seconds':5})
        worker=AggregateScheduler(svc,ledger=self.q,key_loader=lambda:'CONTROLLED-key')
        request=deepcopy(REQUEST);cid=self.q.begin_cycle(self.owner,[request]);worker.cycle_id=cid
        wire=self.wire()
        async def paid(req,key):return dict(status=200,headers=counters(653,3),received_at=self.at,body=b'[]')
        wire.request=paid;worker.transport=wire
        with patch.object(worker,'check_account_binding'),patch('app.collection.current_aggregate.now',side_effect=lambda:self.at):
            response=await worker.dispatch(request,3)
        self.assertEqual(response['status'],200);self.assertEqual(self.q.snapshot()['reserved'],3)
        self.assertEqual(self.q.snapshot()['available'],99294)
        self.assertEqual(self.q._read()['attempts'][self.aid],self.old)
        await worker.close()

if __name__=='__main__':unittest.main()
