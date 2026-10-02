"""No-I/O launch gates for the unapproved native-only package."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from hashlib import sha256
from unittest.mock import patch
from app.collection.native_approval import digest
ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'evidence/native-discovery-probe-20260930'

class Gates(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        for n in ('identity.json','attempt.json','run-spec.json','launch.py'):shutil.copyfile(PACKAGE/n,self.path/n)
        spec=importlib.util.spec_from_file_location('native_probe_launcher',PACKAGE/'launch.py');self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module);self.module.PACKAGE=self.path
    def tearDown(self):self.tmp.cleanup()
    def write(self,name,value):
        (self.path/name).write_text(json.dumps(value))
    def test_unapproved_never_reaches_activation(self):
        with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credential access')):
            self.module.prepared(False)
            with self.assertRaises(OSError):self.module.prepared(True)
    def test_changed_candidate_or_launcher_refused(self):
        identity=json.loads((self.path/'identity.json').read_text());identity['implementation_sha256']='0'*64;self.write('identity.json',identity)
        with self.assertRaisesRegex(ValueError,'Candidate changed'):self.module.prepared()
        shutil.copyfile(PACKAGE/'identity.json',self.path/'identity.json');(self.path/'launch.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'package changed'):self.module.prepared()
    def test_used_destination_and_expired_window_refused(self):
        attempt=json.loads((self.path/'attempt.json').read_text());attempt['output']=str(self.path);self.write('attempt.json',attempt)
        identity=json.loads((self.path/'identity.json').read_text());identity['file_hashes']['attempt.json']=sha256((self.path/'attempt.json').read_bytes()).hexdigest();self.write('identity.json',identity)
        with self.assertRaisesRegex(ValueError,'already exists'):self.module.prepared()
        shutil.copyfile(PACKAGE/'attempt.json',self.path/'attempt.json');identity=json.loads((PACKAGE/'identity.json').read_text())
        spec=json.loads((self.path/'run-spec.json').read_text());spec['start_before']='2020-01-01T00:00:00Z';self.write('run-spec.json',spec)
        identity['spec_sha256']=digest(spec);identity['file_hashes']['run-spec.json']=sha256((self.path/'run-spec.json').read_bytes()).hexdigest();self.write('identity.json',identity)
        with self.assertRaisesRegex(ValueError,'Invalid spec|Outside sealed window'):self.module.prepared()
