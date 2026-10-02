"""Offline package binding, finite-control and inert-preparation checks."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
from scripts.us_metadata_package.build import build, authorization
from app.collection.native_approval import digest
from app.collection.run_spec import preflight


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.folder = ROOT/'evidence'/('OFFLINE-package-unit-'+str(uuid.uuid4()))
        self.identity = build(self.folder)

    def tearDown(self):
        # Only the folder freshly created by this test; no attempt destination exists.
        shutil.rmtree(self.folder)

    def test_exact_inert_scope_window_and_authorization(self):
        spec = json.loads((self.folder/'run-spec.json').read_text())
        window = json.loads((self.folder/'window.json').read_text())
        self.assertTrue(preflight(spec)['valid'])
        self.assertEqual(digest(spec),self.identity['spec_sha256'])
        self.assertEqual(spec['start_before'],window['latest_activation_and_dispatch'])
        start = datetime.fromisoformat(spec['start_after'])
        expires = datetime.fromisoformat(window['expires_at'])
        self.assertEqual(expires-start,timedelta(seconds=7200))
        self.assertEqual(expires-datetime.fromisoformat(spec['start_before']),timedelta(seconds=32))
        self.assertEqual((self.folder/'AUTHORIZATION.txt').read_bytes(),authorization(self.identity,window['expires_at']))
        self.assertEqual(spec['us_metadata_diagnostic']['request'],
            dict(method='GET',host='https://gateway.polymarket.us',path='/v1/events/127804',params={}))
        self.assertEqual(spec['prediction']['connections'],0)
        self.assertEqual(spec['prediction']['messages'],0)
        self.assertEqual(set(spec['sources']),{'polymarket_us'})
        self.assertFalse(Path(self.identity['output']).exists())
        self.assertFalse((self.folder/'approval.json').exists())
        self.assertFalse((self.folder/'activation.json').exists())
        self.assertFalse((self.folder/'start-dispatch.json').exists())
        self.assertFalse(json.loads((self.folder/'approval-template.json').read_text())['approved'])
        self.assertEqual(json.loads((self.folder/'package-seal.json').read_text())['package_sha256'],digest(self.identity))

    def test_refuse_scope_mutations_and_reuse(self):
        spec = json.loads((self.folder/'run-spec.json').read_text())
        for mutation in ('parameters','sockets','response-cap','expiry'):
            changed = deepcopy(spec)
            if mutation=='parameters':
                changed['us_metadata_diagnostic']['request']['params']={'active':True}
            elif mutation=='sockets':
                changed['prediction']['connections']=1
            elif mutation=='response-cap':
                changed['native_transport']['response_entity_bytes']+=1
            else:
                changed['start_before']=changed['us_metadata_diagnostic']['validity_window']['expires']
            self.assertFalse(preflight(changed)['valid'],mutation)
        with self.assertRaises(ValueError):
            build(self.folder)

    def test_launch_check_has_no_activation_and_detects_package_change(self):
        # This is the actual copied launcher, rather than an independently recreated check.
        source = importlib.util.spec_from_file_location('offline_us_launch',self.folder/'launch.py')
        launcher = importlib.util.module_from_spec(source)
        source.loader.exec_module(launcher)
        launcher.prepared(False)
        with self.assertRaises(FileNotFoundError):
            launcher.prepared(True)
        self.assertFalse(Path(self.identity['output']).exists())
        with (self.folder/'AUTHORIZATION.txt').open('ab') as stream:
            stream.write(b'changed\n')
        with self.assertRaisesRegex(ValueError,'Sealed package changed'):
            launcher.prepared(False)


class ControlDeadlineTests(unittest.TestCase):
    def test_whole_request_alarm_and_exact_binding(self):
        path = ROOT/'scripts/us_metadata_package'
        previous = sys.modules.pop('launch',None)
        sys.path.insert(0,str(path))
        try:
            source = importlib.util.spec_from_file_location('offline_us_control',path/'control.py')
            control = importlib.util.module_from_spec(source)
            source.loader.exec_module(control)
            began = time.monotonic()
            with self.assertRaisesRegex(TimeoutError,'whole-request deadline'):
                with control.whole_request_deadline(.03):
                    time.sleep(.3)
            self.assertLess(time.monotonic()-began,.2)
            import io
            identity = dict(implementation_sha256='a'*64,spec_sha256='b'*64,
                attempt_id=str(uuid.uuid4()),output=str(ROOT/'evidence'/'UNUSED-binding-test'),
                file_hashes={'AUTHORIZATION.txt':'c'*64})
            self.assertEqual(control.body(io.BytesIO(json.dumps(identity).encode()),binding=True)['body'],identity)
            self.assertIsNone(control.body(io.BytesIO(b'x'*65537),binding=True)['body'])
            self.assertEqual(control.sanitize({'authorization':'Bearer secret'}),{'authorization':'[REDACTED]'})
            with tempfile.TemporaryDirectory() as folder:
                control.PACKAGE = Path(folder)
                value = dict(status=200,binding_schema=control.SCHEMA_VERSION,body=identity,
                             headers={'authorization':'secret'})
                control.save('verified-server-identity.json',value)
                retained = json.loads((Path(folder)/'verified-server-identity.json').read_text())
                self.assertEqual(retained['body'],identity)
                self.assertEqual(retained['headers']['authorization'],'[REDACTED]')
        finally:
            sys.path.remove(str(path))
            sys.modules.pop('launch',None)
            if previous is not None:
                sys.modules['launch']=previous


if __name__=='__main__':
    unittest.main()
