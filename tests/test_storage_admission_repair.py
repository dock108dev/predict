"""Rollover admission controls; disposable ledgers and journals, no acquisition."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from app.collection.current_conservative import digest
from app.collection.current_journal import CurrentJournal
from app.collection.current_quota import QuotaStop
from app.collection.current_storage_policy import (
    VERSION, JOURNAL_SEGMENT_BYTE_CAP, JOURNAL_BYTE_CAP, JOURNAL_RECORD_BYTE_CAP,
    SQL_BYTE_CAP, FREE_DISK_BYTE_FLOOR,
)
from tests.test_current_conservative_recovery import ConservativeRecovery, CANDIDATE, counters
from tests.test_current_quota import WINDOW


class StorageAdmissionRepair(unittest.TestCase):
    evidence=ConservativeRecovery.evidence
    activate=ConservativeRecovery.activate
    due=ConservativeRecovery.due
    reserve_cycle=ConservativeRecovery.reserve_cycle
    tearDown=ConservativeRecovery.tearDown

    def setUp(self):
        ConservativeRecovery.setUp(self)
        self.activate();self.due()
        self.response_id,_=self.reserve_cycle();self.q.dispatched(self.response_id,self.owner)
        self.receipt=dict(status=200,headers=counters(653,3),received_at=self.at)
        self.q.reconcile(self.response_id,self.receipt['headers'])
        self.q.record_response(self.response_id,self.receipt)
        self.q.pause('aggregate_admission_failed')
        self.journal=self.root/'observations';self.journal.mkdir()
        self.original=self.journal/'observations.jsonl'
        self.original.write_bytes(b'{"kind":"retained","source_at":"2026-10-03T14:00:00Z"}\n')
        self.original_bytes=self.original.read_bytes()
        writer=CurrentJournal(self.journal)
        writer.append(dict(kind='replayed_response',received_at=self.at))
        self.manifest=writer.manifest_path
        self.proof=dict(candidate_digest=CANDIDATE,attempt_id=self.response_id,
            repair='observation_storage_rollover',replay_verified=True,
            ingress_admitted=1,provider_requests=0,received_at=self.at,
            response_receipt_sha256=digest(self.receipt),
            storage_policy=dict(version=VERSION,journal_segment_byte_cap=JOURNAL_SEGMENT_BYTE_CAP,
                journal_total_byte_cap=JOURNAL_BYTE_CAP,journal_record_byte_cap=JOURNAL_RECORD_BYTE_CAP,
                sql_byte_cap=SQL_BYTE_CAP,free_disk_byte_floor=FREE_DISK_BYTE_FLOOR),
            original_journal=dict(path=str(self.original),bytes=len(self.original_bytes),sha256=sha256(self.original_bytes).hexdigest()),
            segmented_manifest=dict(path=str(self.manifest),sha256=sha256(self.manifest.read_bytes()).hexdigest()))
        self.proof_path=self.root/'replay.json'

    def retained_evidence(self,proof=None):
        self.proof_path.write_text(json.dumps(self.proof if proof is None else proof))
        return dict(replay_verified=True,path=str(self.proof_path),sha256=sha256(self.proof_path.read_bytes()).hexdigest(),
            attempt_id=self.response_id,repair='observation_storage_rollover')

    @contextmanager
    def owned_context(self):
        with patch('app.collection.current_policy.candidate',return_value=(CANDIDATE,{})), \
                patch('app.collection.current_account_recovery.credential_binding',return_value=self.binding), \
                patch('app.collection.current_quota.load_window',return_value=WINDOW):
            yield

    def repair(self,proof=None):
        with self.owned_context():
            self.q.repair_admission(self.retained_evidence(proof),owner=self.owner,candidate=CANDIDATE)

    def test_exact_rollover_proof_clears_only_pause_and_appends_audit(self):
        before=self.q._read();self.repair();after=self.q._read()
        for key in ('attempts','conservative_recoveries','account_transitions','observation','next_due_at','cycle','bootstrap_due_at'):
            self.assertEqual(before.get(key),after.get(key))
        self.assertIsNone(after['pause']);self.assertEqual(self.q.snapshot()['reserved'],3)
        self.assertEqual(after['admission_repairs'][-1]['repair'],'observation_storage_rollover')
        self.assertEqual(after['admission_repairs'][-1]['candidate_digest'],CANDIDATE)
        self.assertEqual(self.original.read_bytes(),self.original_bytes)

    def test_direct_storage_cap_pause_can_be_repaired(self):
        self.q.pause('current_observation_storage_cap');self.repair()
        self.assertIsNone(self.q.snapshot()['pause'])

    def test_unrelated_pause_refuses_without_changing_history(self):
        for reason in ('aggregate_authentication','current_observation_integrity_failed','current_observation_incomplete_tail'):
            self.q.pause(reason);before=(self.q.directory/'quota.json').read_bytes()
            with self.subTest(reason=reason),self.assertRaisesRegex(QuotaStop,'pause_mismatch'):
                self.repair()
            self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)

    def test_exact_candidate_replay_and_receipt_are_required_atomically(self):
        for changes in (dict(candidate_digest='c'*64),dict(attempt_id=self.aid),
                dict(received_at='2026-10-03T20:00:01+00:00'),dict(response_receipt_sha256='0'*64),
                dict(replay_verified=False),dict(provider_requests=1),dict(provider_requests=False),
                dict(ingress_admitted=0),dict(ingress_admitted=True)):
            before=(self.q.directory/'quota.json').read_bytes()
            with self.subTest(changes=changes),self.assertRaisesRegex(QuotaStop,'evidence'):
                self.repair(dict(self.proof,**changes))
            self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)

    def test_policy_version_and_each_current_cap_are_bound(self):
        for key,value in self.proof['storage_policy'].items():
            policy=dict(self.proof['storage_policy']);policy[key]='wrong' if isinstance(value,str) else value+1
            with self.subTest(key=key),self.assertRaisesRegex(QuotaStop,'evidence'):
                self.repair(dict(self.proof,storage_policy=policy))

    def test_original_preservation_and_manifest_hash_are_required(self):
        for key,value in (('sha256','0'*64),('bytes',len(self.original_bytes)+1)):
            original=dict(self.proof['original_journal']);original[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(QuotaStop,'evidence'):
                self.repair(dict(self.proof,original_journal=original))
        manifest=dict(self.proof['segmented_manifest'],sha256='0'*64)
        with self.assertRaisesRegex(QuotaStop,'evidence'):
            self.repair(dict(self.proof,segmented_manifest=manifest))
        self.original.write_bytes(self.original_bytes+b'{}\n')
        with self.assertRaisesRegex(QuotaStop,'evidence'):self.repair()

    def test_missing_or_corrupt_manifest_does_not_poison_ledger(self):
        self.manifest.unlink()
        before=(self.q.directory/'quota.json').read_bytes()
        with self.assertRaisesRegex(QuotaStop,'evidence'):self.repair()
        self.assertIsNone(self.q.failed)
        self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)

    def test_malformed_proof_refuses_without_accounting_mutation(self):
        evidence=self.retained_evidence()
        self.proof_path.write_bytes(b'{not-json')
        evidence['sha256']=sha256(self.proof_path.read_bytes()).hexdigest()
        before=(self.q.directory/'quota.json').read_bytes()
        with self.owned_context(),self.assertRaisesRegex(QuotaStop,'evidence'):
            self.q.repair_admission(evidence,owner=self.owner,candidate=CANDIDATE)
        self.assertIsNone(self.q.failed)
        self.assertEqual((self.q.directory/'quota.json').read_bytes(),before)

    def test_new_uncovered_uncertainty_and_active_holds_still_refuse(self):
        self.q.transact(lambda v,at:v['attempts'][self.aid].update(runtime_id='CONTROLLED-recovery'))
        with self.assertRaisesRegex(QuotaStop,'unresolved|active_transport'):self.repair()

    def test_owner_candidate_and_account_context_remain_required(self):
        evidence=self.retained_evidence()
        with self.owned_context():
            with self.assertRaisesRegex(QuotaStop,'ownership'):
                self.q.repair_admission(evidence,candidate=CANDIDATE)
            with self.assertRaisesRegex(QuotaStop,'candidate_changed'):
                self.q.repair_admission(evidence,owner=self.owner,candidate='c'*64)
        with self.owned_context(),patch('app.collection.current_account_recovery.credential_binding',return_value={}):
            with self.assertRaisesRegex(QuotaStop,'context'):self.q.repair_admission(evidence,owner=self.owner,candidate=CANDIDATE)


if __name__=='__main__':unittest.main()
