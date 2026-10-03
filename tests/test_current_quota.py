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
    def test_bootstrap_without_paid_or_window(self):
        self.bootstrap();self.assertEqual(self.q.snapshot()['remaining'],480)
        with self.assertRaisesRegex(QuotaStop,'reset_window_unknown'):self.paid()
        with self.assertRaisesRegex(QuotaStop,'bootstrap_budget_delayed'):self.bootstrap()
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
        with self.assertRaisesRegex(QuotaStop,'capacity'):self.q.reserve(self.owner,'c',{},0,bootstrap=True)
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
