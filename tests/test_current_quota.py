"""Controlled durable accounting; fictional clocks/headers, no provider I/O."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.collection.current_quota import QuotaLedger,QuotaStop,headers
from app.collection.local_ownership import LocalOwnership

AT='2026-10-03T12:00:00+00:00'
WINDOW=dict(id='CONTROLLED-October',starts_at='2026-10-01T00:00:00+00:00',ends_at='2026-11-01T00:00:00+00:00',evidence='CONTROLLED account evidence',evidence_sha256='a'*64)

def quota(used,last=0):return [('x-requests-used',str(used)),('x-requests-remaining',str(500-used)),('x-requests-last',str(last))]

class DurableQuota(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.at=AT
        self.owner=LocalOwnership(self.root/'owner');self.owner.acquire('CONTROLLED-runtime')
        self.q=QuotaLedger(self.root/'quota',clock=lambda:self.at)
    def tearDown(self):self.owner.release();self.temp.cleanup()
    def bootstrap(self,used=20):
        aid=self.q.reserve(self.owner,'candidate',dict(path='/v4/sports',params={}),0,bootstrap=True)
        self.q.dispatched(aid,self.owner);self.q.reconcile(aid,quota(used));return aid
    def paid(self,cost=3):return self.q.reserve(self.owner,'candidate',dict(path='/v4/sports/baseball_mlb/odds',params={}),cost)
    def test_expired_uncertain_zero_charge_requires_exact_usage_evidence(self):
        self.q.bind_window(WINDOW);self.bootstrap();aid=self.paid();self.q.dispatched(aid,self.owner)
        before=self.q.snapshot();self.at='2026-10-03T12:03:00+00:00'
        path=self.root/'usage.json'
        def evidence(used):
            path.write_text(json.dumps(dict(schema='predict-usage-observation-1',status=200,endpoint_class='sports_bootstrap',purpose='read_only_usage_recovery',received_at=self.at,headers=quota(used))))
        evidence(23)
        with self.assertRaisesRegex(QuotaStop,'not_uncharged'):self.q.reconcile_uncharged(self.owner,aid,path)
        self.assertEqual(self.q.snapshot()['reserved'],3)
        evidence(20);self.q.reconcile_uncharged(self.owner,aid,path)
        after=self.q.snapshot();self.assertEqual(after['used'],20);self.assertEqual(after['reserved'],0)
        for k in ('next_due_at','rotation','bootstrap_due_at','attempts'):self.assertEqual(after[k],before[k])
        attempt=self.q._read()['attempts'][aid];self.assertTrue(attempt['consumed']);self.assertEqual(attempt['charged'],0);self.assertIn('recovery',attempt)

    def test_bootstrap_without_paid_or_window(self):
        self.bootstrap();self.assertEqual(self.q.snapshot()['remaining'],480)
        with self.assertRaisesRegex(QuotaStop,'reset_window_unknown'):self.paid()
        with self.assertRaisesRegex(QuotaStop,'bootstrap_budget_delayed'):self.bootstrap()

    def usage_evidence(self,used=20,**changes):
        e=dict(schema='predict-usage-observation-2',id='CONTROLLED-observation',status=200,endpoint_class='sports_bootstrap',
            purpose='read_only_usage_recovery',received_at=self.at,headers=quota(used),account_id='CONTROLLED-paid',
            window_id=WINDOW['id'],window_evidence_sha256=WINDOW['evidence_sha256'],
            endpoint='https://api.the-odds-api.com/v4/sports',method='GET',params={},credential_reference='.env',
            credential_unchanged_since_snapshot=True,retries=0,documented_cost=0)
        e.update(changes);path=self.root/'usage.json';path.write_text(json.dumps(e));return path

    def paused_paid(self):
        self.q.bind_window(WINDOW);self.q.transact(lambda v,at:v.update(account_id='CONTROLLED-paid'))
        self.bootstrap();aid=self.paid();self.q.dispatched(aid,self.owner);self.q.reconcile(aid,[])
        self.at='2026-10-03T15:00:00+00:00';return aid

    def test_same_account_paused_receipt_zero_resolution_preserves_history_and_due(self):
        aid=self.paused_paid();before=self.q._read();self.q.reconcile_uncharged(self.owner,aid,self.usage_evidence())
        after=self.q._read();a=after['attempts'][aid]
        self.assertEqual(a['charged'],0);self.assertEqual(a['quota_headers'],[])
        self.assertEqual(a['quota_failure'],'quota_missing_duplicate_or_malformed');self.assertTrue(a['consumed'])
        self.assertEqual(a['recovery']['account_id'],'CONTROLLED-paid');self.assertEqual(a['recovery']['old_pause'],before['pause'])
        for k in ('next_due_at','bootstrap_due_at','rotation','window','account_id','account_transitions','cycle'):
            self.assertEqual(after.get(k),before.get(k))
        self.assertEqual(len(after['attempts']),len(before['attempts']));self.assertIsNone(after['pause'])
        self.assertEqual(QuotaLedger(self.root/'quota',clock=lambda:self.at).snapshot()['reserved'],0)
        with self.assertRaisesRegex(QuotaStop,'ambiguous'):self.q.reconcile_uncharged(self.owner,aid,self.usage_evidence())

    def test_positive_delta_intervening_spend_and_delayed_counters_do_not_resolve(self):
        aid=self.paused_paid();before=(self.root/'quota/quota.json').read_bytes()
        for used in (21,23,100):
            with self.assertRaisesRegex(QuotaStop,'not_uncharged'):self.q.reconcile_uncharged(self.owner,aid,self.usage_evidence(used))
            self.assertEqual((self.root/'quota/quota.json').read_bytes(),before)
        for changes in (dict(received_at=AT),dict(received_at='2026-10-03T15:06:00+00:00'),dict(received_at='2026-10-03T14:54:00+00:00')):
            with self.assertRaises(QuotaStop):self.q.reconcile_uncharged(self.owner,aid,self.usage_evidence(**changes))
        self.assertEqual(self.q.snapshot()['reserved'],3)

    def test_account_reset_credential_and_endpoint_mismatch_preserve_reservation(self):
        aid=self.paused_paid()
        for changes in (dict(account_id='other'),dict(window_id='other'),dict(window_evidence_sha256='b'*64),
            dict(schema='predict-usage-observation-1'),dict(credential_unchanged_since_snapshot=False),
            dict(endpoint='https://api.the-odds-api.com/v4/sports/baseball_mlb/odds'),dict(documented_cost=3)):
            with self.assertRaisesRegex(QuotaStop,'account_or_window'):self.q.reconcile_uncharged(self.owner,aid,self.usage_evidence(**changes))
        self.q.transact(lambda v,at:v.update(account_transitions=[dict(at=self.at,reason='CONTROLLED-account-change')]))
        with self.assertRaisesRegex(QuotaStop,'account_or_window'):self.q.reconcile_uncharged(self.owner,aid,self.usage_evidence())
        self.assertEqual(self.q.snapshot()['reserved'],3)

    def test_unrelated_pause_and_extra_uncertain_attempt_remain_blocked(self):
        aid=self.paused_paid();self.q.pause('aggregate_authentication')
        with self.assertRaisesRegex(QuotaStop,'not_uncharged'):self.q.reconcile_uncharged(self.owner,aid,self.usage_evidence())
        self.q.pause('quota_missing_duplicate_or_malformed')
        def extra(v,at):
            a=deepcopy(v['attempts'][aid]);a['id']='CONTROLLED-other';v['attempts'][a['id']]=a
        self.q.transact(extra)
        with self.assertRaisesRegex(QuotaStop,'ambiguous'):self.q.reconcile_uncharged(self.owner,aid,self.usage_evidence())
        self.assertEqual(self.q.snapshot()['reserved'],6)

    def test_header_case_duplicate_and_malformed_provenance(self):
        self.q.bind_window(WINDOW);self.bootstrap();aid=self.paid();self.q.dispatched(aid,self.owner)
        self.q.reconcile(aid,[('X-Requests-Used','23'),('X-Requests-Remaining','477'),('X-Requests-Last','secret'),('x-requests-last','3')])
        a=self.q._read()['attempts'][aid]
        self.assertEqual(a['quota_headers'],[['x-requests-used','23'],['x-requests-remaining','477'],['x-requests-last','invalid'],['x-requests-last','3']])
        self.assertEqual(self.q.snapshot()['reserved'],3);self.assertNotIn('secret',json.dumps(a))
    def test_atomic_reservation_restart_schedule_and_duplicate(self):
        self.q.bind_window(WINDOW);self.bootstrap();aid=self.paid()
        other=QuotaLedger(self.root/'quota',clock=lambda:self.at)
        self.assertEqual(other.snapshot()['reserved'],3)
        with self.assertRaises(QuotaStop):other.reserve(self.owner,'candidate',{},3)
        self.q.dispatched(aid,self.owner);self.q.reconcile(aid,quota(23,3))
        before=self.q.snapshot();self.q.reconcile(aid,quota(26,3));self.assertEqual(self.q.snapshot(),before)
        self.assertEqual(before['reserved'],0);self.assertEqual(before['available'],427)
        with self.assertRaisesRegex(QuotaStop,'budget_delayed'):self.paid()
    def test_out_of_band_spend_reduces_allowance(self):
        self.q.bind_window(WINDOW);self.bootstrap();aid=self.paid();self.q.dispatched(aid,self.owner)
        self.q.reconcile(aid,quota(100,3));self.assertEqual(self.q.snapshot()['available'],350)
        self.assertIsNone(self.q.snapshot()['pause']);self.assertEqual(self.q.snapshot()['reserved'],0)
    def test_missing_duplicate_counter_regression_and_unexpected_charge(self):
        for values in ([],quota(23)+[('x-requests-last','0')],quota(19,3),quota(24,4),[('x-requests-used','23'),('x-requests-remaining','480'),('x-requests-last','3')]):
            with self.subTest(values=values):
                root=self.root/str(len(list(self.root.iterdir())))
                q=QuotaLedger(root,clock=lambda:AT);q.bind_window(WINDOW)
                aid=q.reserve(self.owner,'candidate',{},0,bootstrap=True);q.dispatched(aid,self.owner);q.reconcile(aid,quota(20))
                paid=q.reserve(self.owner,'candidate',{},3);q.dispatched(paid,self.owner);q.reconcile(paid,values)
                self.assertIsNotNone(q.snapshot()['pause']);self.assertEqual(q.snapshot()['reserved'],3)
                with self.assertRaises(QuotaStop):q.reserve(self.owner,'candidate',{},3)
    def test_write_failure_prevents_dispatch_and_latches(self):
        self.q.bind_window(WINDOW);self.bootstrap()
        with patch('app.collection.current_quota.os.replace',side_effect=OSError('CONTROLLED')):
            with self.assertRaisesRegex(QuotaStop,'persistence_failed'):self.paid()
        self.assertEqual(self.q.snapshot()['attempts'],1)
        with self.assertRaises(QuotaStop):self.paid()
    def test_ambiguity_blocks_restart_and_reset_preserves_records(self):
        self.q.bind_window(WINDOW);self.bootstrap();aid=self.paid();self.q.dispatched(aid,self.owner)
        self.at='2026-10-04T12:00:00+00:00';self.bootstrap(23)
        self.assertEqual(self.q.snapshot()['reserved'],3)
        with self.assertRaisesRegex(QuotaStop,'ambiguous'):self.paid()
        next_window=dict(WINDOW,id='CONTROLLED-November',starts_at='2026-11-01T00:00:00+00:00',ends_at='2026-12-01T00:00:00+00:00')
        self.at='2026-11-02T12:00:00+00:00'
        with self.assertRaisesRegex(QuotaStop,'unresolved'):self.q.bind_window(next_window)
        self.q.reconcile(aid,quota(23,3))
        # Confirmed exact receipt can release once; bootstrap spend isn't added twice.
        self.q.bind_window(next_window);self.assertIsNone(self.q.snapshot()['remaining'])
        self.assertEqual(self.q.snapshot()['attempts'],3)
    def test_reset_requires_new_evidence_and_fresh_observation(self):
        self.q.bind_window(WINDOW);self.bootstrap();aid=self.paid();self.q.dispatched(aid,self.owner);self.q.reconcile(aid,quota(23,3))
        self.at='2026-11-02T12:00:00+00:00'
        with self.assertRaisesRegex(QuotaStop,'expired'):self.paid()
        next_window=dict(WINDOW,id='CONTROLLED-November',starts_at='2026-11-01T00:00:00+00:00',ends_at='2026-12-01T00:00:00+00:00')
        self.q.bind_window(next_window);self.bootstrap(0)
        self.assertEqual(self.q.snapshot()['used'],0);self.assertEqual(self.q.snapshot()['attempts'],3)
    def test_corrupt_ledger_clock_regression_and_record_capacity(self):
        self.q.bind_window(WINDOW);self.bootstrap()
        self.at='2026-10-02T00:00:00+00:00'
        with self.assertRaisesRegex(QuotaStop,'clock_regression'):self.paid()
        self.assertEqual(self.q.snapshot()['pause'],'clock_regression')
        (self.root/'quota/quota.json').write_text('{}')
        with self.assertRaisesRegex(QuotaStop,'corrupt'):self.paid()
        self.assertIsNone(self.q.snapshot()['remaining'])
    def test_exhaustion_ownership_and_free_missing_headers(self):
        self.q.bind_window(WINDOW);self.bootstrap(448)
        with self.assertRaisesRegex(QuotaStop,'exhausted'):self.paid()
        self.owner.release()
        with self.assertRaisesRegex(QuotaStop,'ownership'):self.paid()
    def test_pacing_is_one_global_six_hour_upper_bound(self):
        self.q.bind_window(WINDOW);self.bootstrap(20);aid=self.paid();self.q.dispatched(aid,self.owner);self.q.reconcile(aid,quota(23,3))
        first=self.q.snapshot()['next_due_at'];self.assertEqual(first,'2026-10-03T18:00:00+00:00')
        self.at=first;self.paid();self.assertEqual(self.q.snapshot()['rotation'],2)

    def test_competing_process_cannot_reserve_without_owner(self):
        import subprocess,sys
        code="from app.collection.local_ownership import LocalOwnership; from app.collection.current_quota import QuotaLedger; import sys; o=LocalOwnership(sys.argv[1]); o.acquire('competitor'); QuotaLedger(sys.argv[2]).reserve(o,'c',{},3)"
        result=subprocess.run([sys.executable,'-c',code,str(self.root/'owner'),str(self.root/'quota')],capture_output=True)
        self.assertNotEqual(result.returncode,0);self.assertEqual(self.q.snapshot()['attempts'],0)
    def test_restart_clock_jump_missing_file_and_capacity(self):
        mono=[100.0];q=QuotaLedger(self.root/'anchor',clock=lambda:self.at,monotonic=lambda:mono[0])
        q.bind_window(WINDOW)
        self.at='2026-10-03T15:00:00+00:00';mono[0]=101
        restarted=QuotaLedger(self.root/'anchor',clock=lambda:self.at,monotonic=lambda:mono[0])
        with self.assertRaisesRegex(QuotaStop,'continuity'):restarted.reserve(self.owner,'c',{},0,bootstrap=True)
        self.assertEqual(restarted.snapshot()['pause'],'clock_continuity_unknown')
        (self.root/'anchor/quota.json').unlink()
        with self.assertRaisesRegex(QuotaStop,'missing'):restarted.reserve(self.owner,'c',{},0,bootstrap=True)
    def test_capacity_never_drops_unresolved(self):
        self.q.bind_window(WINDOW);self.bootstrap();aid=self.paid();self.q.dispatched(aid,self.owner)
        def fill(v,at):
            for i in range(510):v['attempts'][str(i)]=dict(id=str(i),cost=0,state='confirmed',consumed=True)
        self.q.transact(fill)
        with __import__('unittest.mock',fromlist=['patch']).patch('app.collection.current_quota.ATTEMPT_CAP',512), self.assertRaisesRegex(QuotaStop,'capacity'):self.q.reserve(self.owner,'c',{},0,bootstrap=True)
        self.assertEqual(self.q.snapshot()['reserved'],3)
    def test_unexpected_charge_reduces_observed_allowance(self):
        self.q.bind_window(WINDOW);self.bootstrap();aid=self.paid();self.q.dispatched(aid,self.owner)
        self.q.reconcile(aid,quota(120,100))
        self.assertEqual(self.q.snapshot()['remaining'],380);self.assertIsNotNone(self.q.snapshot()['pause'])

    def test_sealed_diagnostic_is_once_only_and_does_not_reset_due(self):
        self.q.bind_window(WINDOW);self.bootstrap();aid=self.paid();self.q.dispatched(aid,self.owner);self.q.reconcile(aid,quota(23,3))
        due=self.q.snapshot()['next_due_at']
        envelope=dict(schema='predict-u4-qualification-1',id='CONTROLLED-diagnostic',candidate_digest='candidate',expires_at='2026-10-03T12:04:00+00:00',window_id=WINDOW['id'],maximum_credits=3,maximum_requests=2,authority='predict-standing-source-u4-20261003')
        request=dict(path='/v4/sports/baseball_mlb/odds',params=dict(bookmakers='novig,prophetx',markets='h2h,spreads,totals'))
        aid=self.q.reserve(self.owner,'candidate',request,3,qualification=envelope);self.q.dispatched(aid,self.owner);self.q.reconcile(aid,quota(26,3))
        self.assertGreaterEqual(self.q.snapshot()['next_due_at'],due)
        with self.assertRaisesRegex(QuotaStop,'consumed'):self.q.reserve(self.owner,'candidate',request,3,qualification=envelope)
        with self.assertRaisesRegex(QuotaStop,'invalid'):self.q.reserve(self.owner,'wrong-candidate',request,3,qualification=envelope)
        with self.assertRaisesRegex(QuotaStop,'budget_delayed'):self.paid()
