"""Fictional account evidence and disposable ledgers only."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import unittest
from app.collection.current_account_recovery import observe_and_activate
from app.collection.current_conservative import digest, exposure, pending_reason
from app.collection.current_quota import QuotaStop
from app.collection.current_rollover import import_rollover
from tests import test_current_conservative_recovery as fixture
from tests.test_current_conservative_recovery import counters, CANDIDATE


class Rollover(unittest.TestCase):
    tearDown = fixture.ConservativeRecovery.tearDown
    evidence = fixture.ConservativeRecovery.evidence
    activate = fixture.ConservativeRecovery.activate

    def setUp(self):
        fixture.ConservativeRecovery.setUp(self)
        def holds(v, at):
            for i, cost in enumerate([3,3,3,3,3,3,2]):
                a=deepcopy(v['attempts'][self.aid]);a.update(id=f'CONTROLLED-old-{i}',cost=cost)
                v['attempts'][a['id']]=a
        self.q.transact(holds)
        self.covered={k:digest(a) for k,a in self.q._read()['attempts'].items() if a['state']=='uncertain'}
        self.activate()
        self.at='2026-11-03T03:30:00+00:00'
        self.old_window=deepcopy(self.q._read()['window'])
        self.proof=dict(provider='the_odds_api',evidence_kind='provider_account',
            account_id='CONTROLLED-account',monthly_credits=100000,credential_binding=self.binding,
            same_account_confirmed=True,provenance='Fictional authenticated account fixture',
            starts_at='2026-11-01T00:00:00+00:00',ends_at='2026-12-01T00:00:00+00:00',observed_at=self.at)
        self.w=dict(id='CONTROLLED-November',starts_at=self.proof['starts_at'],ends_at=self.proof['ends_at'],
                    evidence=str(self.root/'account-proof.json'),evidence_sha256='a'*64)
        self.write_proof()
        def seed(v, at):
            v['observation'].update(used=20822,remaining=79178)
            a=deepcopy(v['attempts'][self.aid]);a.update(id='CONTROLLED-bootstrap',cost=0,bootstrap=True,
                request=dict(path='/v4/sports',params={}),runtime_id='CONTROLLED-expired',
                dispatch_at='2026-11-01T01:59:00+00:00',quota_failure='quota_counter_or_charge_contradictory',
                response_receipt=dict(status=200,headers=counters(0),received_at='2026-11-01T01:59:01+00:00'))
            v['attempts'][a['id']]=a;v['pause']='quota_counter_or_charge_contradictory'
        self.q.transact(seed)
        self.refresh()

    def write_proof(self):
        raw=json.dumps(self.proof).encode();(self.root/'account-proof.json').write_bytes(raw)
        self.w['evidence_sha256']=sha256(raw).hexdigest()

    def refresh(self):
        self.before=deepcopy(self.q._read())
        self.covered={k:digest(a) for k,a in self.before['attempts'].items() if a['state']=='uncertain'}

    def transition(self, **changes):
        e=self.evidence(window=self.w,recovery_id='CONTROLLED-rollover',headers=counters(10),**changes)
        return self.q.transact(lambda v,at:import_rollover(v,e,at,self.covered,
            owner_runtime='CONTROLLED-recovery',candidate=CANDIDATE,recovery_id='CONTROLLED-rollover',
            new_window=self.w,binding=self.binding))

    def test_rollover_preserves_history_holds_and_capacity(self):
        self.transition();v=self.q._read()
        self.assertEqual(v['attempts'],self.before['attempts'])
        self.assertEqual(v['conservative_recoveries'][:-1],self.before['conservative_recoveries'])
        self.assertEqual(v['windows'][-1]['window'],self.old_window)
        self.assertEqual(v['windows'][-1]['observation']['used'],20822)
        self.assertEqual(exposure(v),23);self.assertEqual(self.q.available(v),99917)
        self.assertIsNone(pending_reason(v));self.assertIsNone(self.q.eligibility(v,self.at))
        self.assertGreater(v['next_due_at'],self.at)
        self.assertEqual(v['bootstrap_due_at'],self.before['bootstrap_due_at'])
        prior=(self.q.directory/'quota.json').read_bytes()
        with self.assertRaisesRegex(QuotaStop,'already_activated'):self.transition()
        self.assertEqual((self.q.directory/'quota.json').read_bytes(),prior)

    def test_bad_account_credential_allowance_or_age_is_atomic(self):
        for key,val in [('account_id','other'),('credential_binding',{}),('monthly_credits',500),
                        ('observed_at','2026-11-01T00:00:00+00:00'),('same_account_confirmed',False)]:
            with self.subTest(key=key):
                saved=deepcopy(self.proof);self.proof[key]=val;self.write_proof()
                prior=(self.q.directory/'quota.json').read_bytes()
                with self.assertRaises(QuotaStop):self.transition()
                self.assertEqual((self.q.directory/'quota.json').read_bytes(),prior)
                self.proof=saved;self.write_proof()

    def test_within_window_decrease_and_overlap_refused(self):
        self.q.transact(lambda v,at:v['attempts']['CONTROLLED-bootstrap'].update(dispatch_at='2026-10-31T23:59:00+00:00'))
        self.refresh()
        with self.assertRaisesRegex(QuotaStop,'unexplained'):self.transition()
        self.w['starts_at']='2026-10-31T00:00:00+00:00'
        with self.assertRaisesRegex(QuotaStop,'unsupported'):self.transition()

    def test_active_transport_expired_balance_and_missing_coverage(self):
        with self.assertRaisesRegex(QuotaStop,'expired'):self.transition(received_at='2026-11-03T03:20:00+00:00')
        self.covered={}
        with self.assertRaisesRegex(QuotaStop,'coverage'):self.transition()
        self.q.transact(lambda v,at:v['attempts']['CONTROLLED-bootstrap'].update(state='reserved'))
        self.covered={k:digest(a) for k,a in self.q._read()['attempts'].items() if a['state'] in ('uncertain','reserved')}
        with self.assertRaisesRegex(QuotaStop,'active_transport'):self.transition()

    def test_owned_observation_no_paid_authority_until_closed(self):
        outer=self
        class Transport:
            async def request(self, request, key):
                outer.assertEqual(request,dict(path='/v4/sports',params={}))
                outer.assertEqual(outer.q.eligibility(outer.q._read(),outer.at),'quota_counter_or_charge_contradictory')
                from app.collection.local_ownership import LocalOwnership
                rival=LocalOwnership(outer.root/'owner')
                with outer.assertRaisesRegex(ValueError,'Another'):rival.acquire('rival')
                return dict(status=200,headers=counters(10),received_at=outer.at,body=b'[]')
            async def close(self):
                outer.assertEqual(outer.q._read()['window'],outer.old_window)
        result=asyncio.run(observe_and_activate(self.q,self.owner,CANDIDATE,self.covered,'CONTROLLED-rollover',
            root=self.root,transport=Transport(),key_loader=lambda:'fictional',window_loader=lambda:self.w,rollover=True))
        self.assertIsNone(result['blocking_reason']);self.assertEqual(result['reserved'],23)
        self.assertEqual(result['recovery_probes'][-1]['state'],'activated')
        self.assertTrue((self.q.directory/'independent-balances/CONTROLLED-rollover.json').exists())

    def test_later_same_window_recovery_carries_historical_coverage(self):
        self.transition()
        from app.collection.current_conservative import recovery_preflight
        recovery_preflight(self.q._read(),self.at,self.covered,owner_runtime='another',recovery_id='later')

    def test_current_window_accepted_balance_cannot_be_reset(self):
        self.q.transact(lambda v,at:v['observation'].update(at='2026-11-01T01:00:00+00:00'))
        with self.assertRaisesRegex(QuotaStop,'unexplained'):self.transition()

    def test_other_pause_and_observing_recovery_stay_blocked(self):
        self.q.pause('owner_stop')
        with self.assertRaisesRegex(QuotaStop,'owner_stop'):self.transition()
        self.q.pause('quota_counter_or_charge_contradictory')
        self.q.transact(lambda v,at:v.setdefault('recovery_probes',[]).append(dict(id='other',state='observing')))
        with self.assertRaisesRegex(QuotaStop,'active_transport'):self.transition()

    def test_persistence_failure_does_not_partially_transition(self):
        from unittest.mock import patch
        before=(self.q.directory/'quota.json').read_bytes()
        with patch('app.collection.current_quota.os.replace',side_effect=OSError('fictional failure')):
            with self.assertRaisesRegex(QuotaStop,'persistence'):self.transition()
        self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)

    def test_changed_credential_during_observation_never_activates(self):
        outer=self
        class Transport:
            async def request(self, request, key):
                (outer.root/'.env').write_text('fictional changed credential')
                return dict(status=200,headers=counters(10),received_at=outer.at,body=b'[]')
            async def close(self):pass
        with self.assertRaisesRegex(QuotaStop,'credential_changed'):
            asyncio.run(observe_and_activate(self.q,self.owner,CANDIDATE,self.covered,'CONTROLLED-rollover',
                root=self.root,transport=Transport(),key_loader=lambda:'fictional',window_loader=lambda:self.w,rollover=True))
        value=self.q._read()
        self.assertEqual(value['window'],self.old_window)
        self.assertEqual(value['attempts'],self.before['attempts'])
        self.assertEqual(value['observation'],self.before['observation'])

    def test_historical_charge_cannot_overwrite_current_capacity(self):
        self.transition()
        before=(self.q.directory/'quota.json').read_bytes()
        with self.assertRaisesRegex(QuotaStop,'historical_charge'):
            self.q.reconcile(self.aid,counters(20825,3),received_at='2026-10-31T23:00:00+00:00')
        self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)
