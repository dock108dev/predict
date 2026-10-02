"""Inert master, immutable revisions and conservative once-spent reservations."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.collection import engineering_authorization as auth
from app.collection.native_payload import TRANSPORT_CONTRACT
from app.collection.venue_access import ENDPOINTS
from app.collection.native_selectors import POLICY as DIRECTED, SPORTS

ROOT=Path(__file__).resolve().parents[1]
AT=datetime(2026,9,30,22,0,tzinfo=timezone.utc)


def session(kind):
    path=ROOT/('evidence/native-gap-probe-20260930/run-spec.json' if kind=='metadata'
               else 'evidence/integrated-acquisition-r3-20260930/run-spec.json')
    value=json.loads(path.read_text())
    value.update(start_after=(AT-timedelta(minutes=1)).isoformat(),
        start_before=(AT+timedelta(minutes=1)).isoformat(),duration=180,
        native_transport=deepcopy(TRANSPORT_CONTRACT))
    value['prediction'].update(discovery_requests=48,connections=2,session_bytes=8*1024*1024)
    for venue in ('novig','prophetx'):value['native_sources'][venue]=dict(state='disabled',selected=False)
    if kind=='metadata':
        value['native_discovery']=dict(policy=DIRECTED,sports=list(SPORTS),discovery_only=True,generations=1)
        value['prediction']['discovery_requests']=36
    else:value['source_session']['native_discovery']=DIRECTED
    endpoints=deepcopy(ENDPOINTS)
    if kind=='integrated':endpoints['aggregate']='https://api.the-odds-api.com'
    return value,endpoints


class Authorization(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.package=self.root/'package';self.package.mkdir()
        controller=self.root/auth.CONTROLLER;controller.parent.mkdir(parents=True)
        controller.write_text('SIMULATED protected controller')
        (controller.parent/'native_approval.py').write_text('SIMULATED protected exact child approval')
        (controller.parent/'transport.py').write_text('SIMULATED transport revision1')
        self.root_patch=patch.object(auth,'ROOT',self.root);self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.master=auth.master_document(self.root/'outputs',dict(start=(AT-timedelta(hours=1)).isoformat(),
                                                                  expires=(AT+timedelta(hours=1)).isoformat()))
        self.master_path=self.package/'master.json';self.master_path.write_text(json.dumps(self.master))
        self.approval=dict(approved=True,master_sha256=auth.digest(self.master),
            policy_sha256=self.master['policy_sha256'],output_root=self.master['output_root'],
            validity_window=self.master['validity_window'])
        self.approval_path=self.package/'owner-approval.json';self.approval_path.write_text(json.dumps(self.approval))

    def reserve(self,kind='metadata',**kwargs):
        value,endpoints=session(kind)
        return auth.reserve_session(self.master_path,self.approval_path,value,endpoints,
            kind=kind,reason='Resolve evidenced ordinary source binding and retest',
            offline_regression_evidence=['temporary offline verification.json; focused tests PASS'],now=AT,**kwargs)

    def ledger(self):
        return [json.loads(line) for line in (self.package/'reservations.jsonl').read_text().splitlines()]

    def test_master_is_inert_without_exact_owner_approval_and_window(self):
        self.approval_path.unlink()
        with self.assertRaises(OSError):self.reserve()
        self.approval_path.write_text(json.dumps(dict(self.approval,approved=False)))
        with self.assertRaisesRegex(ValueError,'Exact owner-approved'):self.reserve()
        self.approval_path.write_text(json.dumps(self.approval))
        with self.assertRaisesRegex(ValueError,'Outside master'):
            auth.validate_master(self.master_path,self.approval_path,AT+timedelta(hours=2))
        self.assertFalse((self.package/'reservations.jsonl').exists())

    def test_policy_roles_types_and_controller_drift_are_rejected(self):
        for key,value in (('max_sessions',5),('max_sessions',4.0),('roles',{'novig':'native_comparison'})):
            bad=deepcopy(self.master);bad['policy'][key]=value;bad['policy_sha256']=auth.digest(bad['policy'])
            self.master_path.write_text(json.dumps(bad))
            with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,'limits or roles drifted'):self.reserve()
        self.master_path.write_text(json.dumps(self.master))
        (self.root/auth.CONTROLLER).write_text('SIMULATED changed approval controller')
        with self.assertRaisesRegex(ValueError,'controller changed'):self.reserve()

    def test_child_exact_caps_destinations_and_direct_native_access_fail_before_reservation(self):
        for change in ('requests','source_bytes','destination','native','transport','duration'):
            value,endpoints=session('integrated')
            if change=='requests':value['prediction']['discovery_requests']=49
            elif change=='source_bytes':value['prediction']['session_bytes']=16*1024*1024
            elif change=='destination':endpoints['aggregate']='https://other.invalid'
            elif change=='native':value['native_sources']['novig']=dict(state='not_configured',selected=True)
            elif change=='transport':value.pop('native_transport')
            elif change=='duration':value['duration']=181
            with self.subTest(change=change),self.assertRaises(ValueError):
                auth.reserve_session(self.master_path,self.approval_path,value,endpoints,
                    kind='integrated',reason='test exact limits',offline_regression_evidence=['offline verification'],now=AT)
        self.assertFalse((self.package/'reservations.jsonl').exists())

    def test_two_integrated_two_metadata_reserve_exact_worst_case_totals(self):
        results=[self.reserve(kind) for kind in ('integrated','metadata','integrated','metadata')]
        self.assertEqual(results[-1]['cumulative'],dict(http_requests=458,native_http_requests=384,
            aggregate_http_requests=74,aggregate_credits=270,websocket_connections=16,
            collection_seconds=720,owned_wall_seconds=960,output_bytes=512*1024*1024))
        self.assertEqual(len({r['attempt_id'] for r in results}),4)
        self.assertTrue(all(not Path(r['output']).exists() for r in results))
        for result,row in zip(results,self.ledger()):
            approval=json.loads(Path(result['approval_path']).read_text());spec,endpoints=session(row['kind'])
            auth.validate_child_approval(approval,spec,endpoints,result['output'],AT)
            self.assertEqual(row['spec'],spec)
            self.assertTrue(row['offline_regression_evidence'])
        with self.assertRaisesRegex(ValueError,'allowance consumed'):self.reserve()

    def test_third_integrated_session_rejected_without_spending_metadata_allowance(self):
        self.reserve('integrated');self.reserve('integrated')
        with self.assertRaisesRegex(ValueError,'allowance consumed'):self.reserve('integrated')
        self.assertEqual(len(self.ledger()),2)
        self.reserve('metadata');self.assertEqual(len(self.ledger()),3)

    def test_repair_revision_is_logged_before_new_child_approval_and_old_candidate_stays_exact(self):
        first=self.reserve();first_row=self.ledger()[0]
        (self.root/'app/collection/transport.py').write_text('SIMULATED bounded repair revision2')
        second=self.reserve();second_row=self.ledger()[1]
        self.assertNotEqual(first_row['implementation_sha256'],second_row['implementation_sha256'])
        self.assertEqual(second_row['previous_sha256'],first_row['sha256'])
        self.assertEqual(first_row['source_manifest'],json.loads((Path(first['approval_path']).parent/'source-manifest.json').read_text()))
        value,endpoints=session('metadata')
        with self.assertRaisesRegex(ValueError,'changed after reservation'):
            auth.validate_child_approval(json.loads(Path(first['approval_path']).read_text()),value,endpoints,first['output'],AT)
        auth.validate_child_approval(json.loads(Path(second['approval_path']).read_text()),value,endpoints,second['output'],AT)

    def test_failure_after_reservation_is_spent_and_unique_attempt_cannot_restart(self):
        identity=str(uuid4());write=auth._write_new
        def crash(path,value):
            if Path(path).name=='approval.json':raise OSError('SIMULATED interruption before child approval')
            return write(path,value)
        with patch.object(auth,'_write_new',side_effect=crash),self.assertRaises(OSError):self.reserve(attempt_id=identity)
        self.assertEqual(len(self.ledger()),1)
        self.assertFalse((self.package/'children'/identity/'approval.json').exists())
        with self.assertRaisesRegex(ValueError,'already reserved'):self.reserve(attempt_id=identity)
        self.reserve();self.assertEqual(len(self.ledger()),2)

    def test_deleted_or_incomplete_spent_ledger_cannot_reset_allowance(self):
        self.reserve();ledger=self.package/'reservations.jsonl';original=ledger.read_bytes()
        ledger.write_bytes(original[:-1])
        with self.assertRaisesRegex(ValueError,'Uncertain'):self.reserve()
        ledger.unlink()
        with self.assertRaisesRegex(ValueError,'Missing spent'):self.reserve()

    def test_metadata_cannot_gain_aggregate_book_reviews_or_socket_policy(self):
        value,endpoints=session('metadata');value['native_discovery']['discovery_only']=False
        with self.assertRaises(ValueError):
            auth.reserve_session(self.master_path,self.approval_path,value,endpoints,kind='metadata',
                reason='invalid socket policy',offline_regression_evidence=['offline regression'],now=AT)
        self.assertFalse((self.package/'reservations.jsonl').exists())

    def test_shared_resource_gate_drift_fails_before_reservation(self):
        from app.collection.continuous import LIMITS
        with patch.dict(LIMITS,output_bytes=256*1024*1024),self.assertRaisesRegex(ValueError,'runtime resource gates changed'):
            self.reserve()
        self.assertFalse((self.package/'reservations.jsonl').exists())


if __name__=='__main__':unittest.main()
