"""Disposable restart recovery, fictional OS facts and no credential/network I/O."""
from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch
from app.collection.current_quota import QuotaLedger, QuotaStop
from app.collection.local_ownership import LocalOwnership
from app.dashboard.current_contract import stamp
from tests import test_current_quota as fixtures
from tests.test_current_quota import WINDOW, quota

class RestartRecovery(unittest.TestCase):
    bootstrap=fixtures.DurableQuota.bootstrap
    paid=fixtures.DurableQuota.paid
    tearDown=fixtures.DurableQuota.tearDown
    def setUp(self):
        fixtures.DurableQuota.setUp(self)
        self.mono=100.0
        self.boot=dict(id='CONTROLLED-boot-a',started_at='2026-10-03T11:58:20+00:00',uptime=self.mono,source='CONTROLLED')
        self.q=QuotaLedger(self.root/'quota',clock=lambda:self.at,monotonic=lambda:self.mono,boot_loader=lambda:deepcopy(self.boot))
    def restart(self):
        self.at='2026-10-04T12:00:00+00:00';self.mono=60.0
        self.boot=dict(id='CONTROLLED-boot-b',started_at='2026-10-04T11:59:00+00:00',uptime=self.mono,source='CONTROLLED')
    def advance(self,seconds):
        self.at=(stamp(self.at)+timedelta(seconds=seconds)).isoformat();self.mono+=seconds;self.boot['uptime']=self.mono
    def prepare(self,**kw):
        self.q.prepare_clock(self.owner,'CONTROLLED-candidate',WINDOW,cleanup_safe=kw.get('safe',True))
    def seed(self):
        self.q.bind_window(WINDOW);self.bootstrap(248)
        self.q.transact(lambda v,at:v.update(rotation=2,next_due_at='2026-10-03T18:00:00+00:00'))
        return self.q._read()
    def test_same_boot_preserves_epoch_and_ordinary_schedule(self):
        self.seed();self.advance(3600);self.prepare()
        self.assertEqual(self.q.snapshot()['clock_recoveries'],[])
        with self.assertRaisesRegex(QuotaStop,'budget_delayed'):self.paid()
    def test_legacy_anchor_requires_boot_after_anchor_and_retains_failed_anchor(self):
        before=self.seed()
        legacy=dict(before,clock_anchor={k:before['clock_anchor'][k] for k in ('at','monotonic')})
        self.q._write(legacy)
        with self.assertRaisesRegex(QuotaStop,'restart_not_established'):self.prepare()
        self.restart()
        with self.assertRaisesRegex(QuotaStop,'continuity'):self.paid()
        self.assertEqual(self.q._read()['clock_anchor'],legacy['clock_anchor'])
        self.prepare()
        self.assertEqual(self.q.snapshot()['clock_recoveries'][0]['old_anchor'],legacy['clock_anchor'])
        self.assertEqual(self.q.snapshot()['pause'],None)
        with self.assertRaisesRegex(QuotaStop,'refresh_required'):self.paid()
    def test_dispatch_requires_the_reservation_runtime_owner(self):
        self.seed();self.advance(21600);aid=self.paid()
        other=LocalOwnership(self.root/'other-owner');other.acquire('CONTROLLED-other-runtime')
        try:
            with self.assertRaisesRegex(QuotaStop,'owner_conflict'):self.q.dispatched(aid,other)
        finally:other.release()
        self.assertEqual(self.q._read()['attempts'][aid]['state'],'reserved')
    def test_restart_preserves_every_record_and_needs_fresh_bootstrap(self):
        before=self.seed();self.restart();self.prepare();after=self.q._read()
        for k in ('attempts','observation','windows','window','rotation','next_due_at','bootstrap_due_at'):
            self.assertEqual(before[k],after[k],k)
        r=after['clock_recoveries'][0]
        self.assertEqual(r['old_anchor'],before['clock_anchor']);self.assertEqual(r['old_last_clock'],before['last_clock'])
        self.assertEqual(r['authority'],'free_accounting_bootstrap_only')
        with self.assertRaisesRegex(QuotaStop,'refresh_required'):self.paid()
        self.bootstrap(250);self.assertEqual(self.q.snapshot()['accounting_epoch']['state'],'current')
        aid=self.paid();self.q.dispatched(aid,self.owner);self.q.reconcile(aid,quota(253,3))
        self.assertEqual(self.q.snapshot()['used'],253)
    def test_unknown_boot_rollback_forward_jump_keep_old_anchor(self):
        for fault,expected in [('unknown','identity_unknown'),('rollback','clock_regression'),('forward','evidence_contradictory'),('contradictory','evidence_contradictory')]:
            with self.subTest(fault=fault):
                self.q=QuotaLedger(self.root/fault,clock=lambda:self.at,monotonic=lambda:self.mono,boot_loader=lambda:deepcopy(self.boot))
                self.at='2026-10-03T12:00:00+00:00';self.mono=100;self.boot=dict(id='a',started_at='2026-10-03T11:58:20+00:00',uptime=100)
                before=self.seed();self.restart()
                if fault=='unknown':self.boot=None
                if fault=='rollback':self.at='2026-10-02T12:00:00+00:00'
                if fault=='forward':self.boot=dict(id='a',started_at='2026-10-03T11:58:20+00:00',uptime=100);self.mono=100
                if fault=='contradictory':self.boot['uptime']=1
                with self.assertRaisesRegex(QuotaStop,expected):self.prepare()
                self.assertEqual(self.q._read()['clock_anchor'],before['clock_anchor'])
    def test_stale_and_contradictory_window_do_not_grant_epoch(self):
        self.seed();self.restart()
        for w in (None,dict(WINDOW,id='wrong'),dict(WINDOW,starts_at='2026-09-01T00:00:00+00:00',ends_at='2026-10-01T00:00:00+00:00')):
            with self.assertRaises(QuotaStop):self.q.prepare_clock(self.owner,'c',w,cleanup_safe=True)
        self.assertEqual(self.q.snapshot()['clock_recoveries'],[])
    def test_reserved_and_uncertain_charge_cannot_recover(self):
        self.seed();self.advance(21600);aid=self.paid();before=self.q._read();self.restart()
        with self.assertRaisesRegex(QuotaStop,'unresolved'):self.prepare()
        self.assertEqual(self.q._read()['attempts'],before['attempts'])
        self.assertEqual(self.q.snapshot()['reserved'],3)
    def test_cleanup_and_competing_ownership_block_without_mutation(self):
        before=self.seed();self.restart()
        with self.assertRaisesRegex(QuotaStop,'cleanup'):self.prepare(safe=False)
        with self.assertRaises(ValueError):LocalOwnership(self.root/'owner').acquire('competitor')
        self.owner.release()
        with self.assertRaisesRegex(QuotaStop,'ownership'):self.prepare()
        self.assertEqual(self.q._read(),before)
    def test_repeated_and_interrupted_recovery_reopens_without_duplicate_authority(self):
        self.seed();self.restart();self.prepare();first=self.q._read();self.prepare()
        self.assertEqual(self.q._read(),first)
        reopened=QuotaLedger(self.root/'quota',clock=lambda:self.at,monotonic=lambda:self.mono,boot_loader=lambda:deepcopy(self.boot))
        reopened.prepare_clock(self.owner,'c',WINDOW,cleanup_safe=True)
        self.assertEqual(len(reopened.snapshot()['clock_recoveries']),1)
        with self.assertRaisesRegex(QuotaStop,'refresh_required'):reopened.reserve(self.owner,'c',{},3)
        aid=reopened.reserve(self.owner,'c',{},0,bootstrap=True)
        with self.assertRaisesRegex(QuotaStop,'unresolved'):reopened.prepare_clock(self.owner,'c',WINDOW,cleanup_safe=True)
        with self.assertRaisesRegex(QuotaStop,'budget_delayed'):reopened.reserve(self.owner,'c',{},0,bootstrap=True)
        self.assertEqual(reopened.snapshot()['attempts'],2)
        # Simulate interruption after reservation: recovery cannot erase it.
        self.advance(1);reopened.dispatched(aid,self.owner);self.advance(1)
        self.restart()
        with self.assertRaisesRegex(QuotaStop,'unresolved'):reopened.prepare_clock(self.owner,'c',WINDOW,cleanup_safe=True)
    def test_failed_persistence_keeps_old_epoch(self):
        before=self.seed();self.restart()
        with patch('app.collection.current_quota.os.replace',side_effect=OSError('CONTROLLED')):
            with self.assertRaisesRegex(QuotaStop,'persistence_failed'):self.prepare()
        self.assertEqual(self.q._read(),before)
    def test_counter_contradiction_never_unlocks_paid(self):
        self.seed();self.restart();self.prepare()
        aid=self.q.reserve(self.owner,'c',{},0,bootstrap=True);self.q.dispatched(aid,self.owner);self.q.reconcile(aid,quota(247))
        self.assertEqual(self.q.snapshot()['accounting_epoch']['state'],'awaiting_bootstrap')
        with self.assertRaises(QuotaStop):self.paid()
    def test_window_transition_keeps_history_and_requires_fresh_accounting(self):
        before=self.seed();self.at='2026-11-02T12:00:00+00:00';self.mono=60
        self.boot=dict(id='c',started_at='2026-11-02T11:59:00+00:00',uptime=60)
        w=dict(WINDOW,id='November',starts_at='2026-11-01T00:00:00+00:00',ends_at='2026-12-01T00:00:00+00:00')
        self.q.prepare_clock(self.owner,'c',w,cleanup_safe=True);self.q.bind_window(w)
        self.assertEqual(self.q._read()['windows'][0]['observation'],before['observation'])
        self.assertEqual(self.q._read()['attempts'],before['attempts'])
        with self.assertRaises(QuotaStop):self.paid()
        self.bootstrap(0);self.assertEqual(self.q.snapshot()['used'],0)

class OSBootEvidence(unittest.TestCase):
    def test_darwin_consistent_os_facts_are_required(self):
        from types import SimpleNamespace
        from app.collection.current_clock import boot_evidence
        row=SimpleNamespace(stdout='E01AAC7F-A902-4E69-9803-EB7CE2F6F86E\n{ sec = 1791057348, usec = 119171 } Sat Oct 3\n')
        with patch('app.collection.current_clock.platform.system',return_value='Darwin'),patch('app.collection.current_clock.subprocess.run',return_value=row) as read,patch('app.collection.current_clock.continuous',return_value=60):
            proof=boot_evidence();self.assertEqual(proof['started_at'],'2026-10-03T19:55:48.119171+00:00');self.assertEqual(read.call_count,2)
            changed=SimpleNamespace(stdout=row.stdout.replace('E01AAC7F','F01AAC7F'))
            read.side_effect=[row,changed];self.assertIsNone(boot_evidence())
    def test_unsupported_or_missing_os_identity_grants_no_restart(self):
        from app.collection.current_clock import boot_evidence
        with patch('app.collection.current_clock.platform.system',return_value='unsupported'):
            self.assertIsNone(boot_evidence())
        with patch('app.collection.current_clock.platform.system',return_value='Darwin'),patch('app.collection.current_clock.subprocess.run',side_effect=OSError('CONTROLLED')):
            self.assertIsNone(boot_evidence())
    def test_linux_boot_identity_and_btime_are_independent_of_wall(self):
        from app.collection.current_clock import boot_evidence
        def read(path):
            return 'btime 1791057348\n' if str(path)=='/proc/stat' else 'e01aac7f-a902-4e69-9803-eb7ce2f6f86e\n'
        with patch('app.collection.current_clock.platform.system',return_value='Linux'),patch('app.collection.current_clock.Path.read_text',autospec=True,side_effect=read),patch('app.collection.current_clock.continuous',return_value=60):
            proof=boot_evidence();self.assertEqual(proof['started_at'],'2026-10-03T19:55:48+00:00');self.assertEqual(proof['uptime'],60)
