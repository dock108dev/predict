"""R2 preparation only: in-memory control transport; no live app Start/provider access."""
import importlib.util
import io
import json
import logging
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from hashlib import sha256
from unittest.mock import patch
from urllib.error import HTTPError
from app.collection.native_approval import digest,implementation
ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'evidence/native-discovery-probe-r2-20260930'

def load(name):
    spec=importlib.util.spec_from_file_location(name,PACKAGE/(name+'.py'));m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name).resolve();self.output=self.path/'unused'
        for n in ('identity.json','attempt.json','run-spec.json','launch.py','control.py'):shutil.copyfile(PACKAGE/n,self.path/n)
        self.launch=load('launch');self.control=load('control');self.launch.PACKAGE=self.path;self.control.PACKAGE=self.path
        a=self.read('attempt.json');a['output']=str(self.output);self.write('attempt.json',a)
        i=self.read('identity.json');i['output']=str(self.output);i['file_hashes']['attempt.json']=sha256((self.path/'attempt.json').read_bytes()).hexdigest();self.write('identity.json',i)
        self.net=patch('socket.socket.connect',side_effect=AssertionError('No sockets'));self.net.start()
        self.creds=patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials'));self.creds.start()
    def tearDown(self):self.creds.stop();self.net.stop();self.tmp.cleanup()
    def read(self,n):return json.loads((self.path/n).read_text())
    def write(self,n,v): (self.path/n).write_text(json.dumps(v))
    def approve(self):self.write('approval.json',dict(approved=True,**self.read('identity.json')))
    def activated(self):
        self.approve();self.launch.prepared(True);self.write('activation.json',self.read('attempt.json'));self.output.mkdir()
    def test_exact_static_and_approval(self):
        self.launch.prepared()
        with self.assertRaises(FileNotFoundError):self.launch.prepared(True)
        self.approve();self.launch.prepared(True)
        a=self.read('approval.json');a['file_hashes']['control.py']='0'*64;self.write('approval.json',a)
        with self.assertRaisesRegex(ValueError,'seals'):self.launch.prepared(True)
    def test_app_identity_unchanged(self):self.assertEqual(digest(implementation()),self.read('identity.json')['implementation_sha256'])
    def test_each_sealed_file_tamper(self):
        for n in self.read('identity.json')['file_hashes']:
            with self.subTest(file=n):
                b=(self.path/n).read_bytes();(self.path/n).write_bytes(b+b' ')
                with self.assertRaisesRegex(ValueError,'package changed'):self.launch.prepared()
                (self.path/n).write_bytes(b)
    def test_candidate_mismatch(self):
        with patch.object(self.launch,'implementation',return_value={}):
            with self.assertRaisesRegex(ValueError,'Candidate'):self.launch.prepared()
    def test_attempt_mismatch(self):
        i=self.read('identity.json');i['attempt_id']='wrong';self.write('identity.json',i)
        with self.assertRaisesRegex(ValueError,'identity mismatch'):self.launch.prepared()
    def test_window_bounds(self):
        s=self.read('run-spec.json')
        for when in (datetime.fromisoformat(s['start_after'].replace('Z','+00:00'))-timedelta(seconds=1),datetime.fromisoformat(s['start_before'].replace('Z','+00:00'))+timedelta(seconds=1)):
            with patch.object(self.launch,'datetime') as clock:
                clock.now.return_value=when
                with self.assertRaisesRegex(ValueError,'Outside'):self.launch.prepared()
    def test_existing_destination(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError,'already exists'):self.launch.prepared()
    def test_real_idle_owner_directory_and_dirty_refusal(self):
        from app.dashboard.coverage_owner import CoverageOwner
        from app.collection.venue_access import ENDPOINTS
        self.approve();spec,output=self.launch.prepared(True)
        self.write('activation.json',self.read('attempt.json'))
        owner=CoverageOwner(output/'unused-saved',pilot_output=output,endpoints=ENDPOINTS,spec_factory=lambda:spec,product_mode=True,native_approval_path=self.path/'approval.json')
        self.assertEqual(owner.status()['state'],'idle')
        self.launch.prepared(True,activated=True)
        (output/'unused-saved'/'unexpected').write_text('used')
        with self.assertRaisesRegex(ValueError,'unused idle'):self.launch.prepared(True,activated=True)
    def test_consumed_marker_and_dispatch(self):
        self.activated()
        for f in (self.output/'b3-attempt.json',self.path/'start-dispatch.json'):
            f.write_text('{}')
            with self.assertRaisesRegex(ValueError,'consumed'):self.launch.prepared(True,activated=True)
            f.unlink()
    def test_approval_attempt_spec_output(self):
        for key in ('attempt_id','spec_sha256','implementation_sha256','output'):
            self.approve();a=self.read('approval.json');a[key]='wrong';self.write('approval.json',a)
            with self.assertRaises(ValueError):self.launch.prepared(True)
    def test_http_error_body_sanitized(self):
        payload=json.dumps({'error':'Missing required market metadata','api_key':'FAKE_SECRET','nested':{'authorization':'Bearer FAKE_TOKEN'}}).encode()
        error=HTTPError('http://127.0.0.1:8831/api/start',422,'bad',{},io.BytesIO(payload))
        with patch.object(self.control,'build_opener') as opener:
            opener.return_value.open.side_effect=error;r=self.control.request('/api/start','POST',{'duration':90})
        self.assertEqual(r['status'],422);self.assertIn('Missing required',r['body']['error']);self.assertNotIn('FAKE',json.dumps(r))
    def test_error_body_cap_and_text_redaction(self):
        r=self.control.body(io.BytesIO(b'Bearer FAKE_TOKEN api_key=FAKE_KEY '+b'x'*70000))
        self.assertTrue(r['truncated']);self.assertEqual(r['retained_input_bytes'],65536);self.assertNotIn('FAKE',json.dumps(r))
    def test_truncated_json_secret_and_storage_bound(self):
        r=self.control.body(io.BytesIO(b'{"api_key":"FAKE_SECRET", "error":"explanation '+b'x'*70000))
        self.assertNotIn('FAKE_SECRET',json.dumps(r));self.assertTrue(r['truncated'])
        self.control.save('bounded.json',{'body':'\x00'*65536})
        self.assertLess((self.path/'bounded.json').stat().st_size,131073)
        self.assertTrue(self.read('bounded.json')['control_record_truncated'])
    def test_transport_error(self):
        with patch.object(self.control,'build_opener') as opener:
            opener.return_value.open.side_effect=OSError('offline');r=self.control.request('/api/status')
        self.assertIsNone(r['status']);self.assertEqual(r['error_class'],'OSError')
    def test_wrong_server_never_start(self):
        self.activated()
        with patch.object(self.control,'request',return_value={'status':200,'body':{}}) as req:
            with self.assertRaisesRegex(ValueError,'binding'):self.control.run()
            self.assertEqual([c.args[0] for c in req.call_args_list],['/probe-binding','/api/status'])
        self.assertFalse((self.path/'start-dispatch.json').exists())
    def test_failure_retained_stop_and_repeat_refused(self):
        self.activated();calls=[]
        def request(path,*args):
            calls.append(path)
            if path=='/probe-binding':return dict(status=200,body=self.read('identity.json'))
            if path=='/api/status' and len(calls)==2:return dict(status=200,body=dict(state='idle',active=False,start_available=True))
            if path=='/api/start':
                folder=self.output/'session';folder.mkdir();(folder/'startup-failure.json').write_text(json.dumps({'failure_class':'ValueError','stage':'before_session_task'}))
                return dict(status=422,body={'error':'required metadata missing'})
            return dict(status=None,error_class='OSError')
        with patch.object(self.control,'request',side_effect=request):
            self.control.run()
            with self.assertRaisesRegex(ValueError,'consumed'):self.control.run()
        self.assertEqual(calls.count('/api/start'),1);self.assertEqual(calls.count('/api/stop'),1)
        self.assertEqual(self.read('start-response.json')['body']['error'],'required metadata missing')
        self.assertEqual(self.read('startup-diagnostics.json')[0]['body']['failure_class'],'ValueError')
    def test_interruption_consumes_and_retains_diagnostics(self):
        self.activated()
        def request(path,*args):
            if path=='/probe-binding':return dict(status=200,body=self.read('identity.json'))
            if path=='/api/start':raise KeyboardInterrupt('interrupted')
            return dict(status=200,body=dict(state='idle',active=False,start_available=True))
        with patch.object(self.control,'request',side_effect=request):
            with self.assertRaises(KeyboardInterrupt):self.control.run()
        self.assertTrue(self.read('start-dispatch.json')['consumed'])
        self.assertEqual(self.read('control-interruption.json')['error_class'],'KeyboardInterrupt')
        self.assertTrue((self.path/'startup-diagnostics.json').exists())
    def test_safe_failure_locations_retained(self):
        handler=self.launch.install_diagnostics();logger=logging.getLogger('app.dashboard.coverage_owner')
        try:
            logger.error('%s failed (%s); frames=%s','coverage_start','ValueError','file.py:12:start')
            logger.error('arbitrary FAKE_SECRET')
            data=(self.path/'startup-locations.log').read_text();self.assertIn('file.py:12:start',data);self.assertNotIn('FAKE',data)
        finally:logger.removeHandler(handler)
    def test_success_once_control_without_elapsed_rehearsal(self):
        self.activated();calls=[]
        def request(path,*args):
            calls.append(path)
            return dict(status=200,body=self.read('identity.json') if path=='/probe-binding' else dict(state='idle',active=False,start_available=True))
        with patch.object(self.control,'request',side_effect=request),patch.object(self.control.time,'monotonic',side_effect=[0,0,91]):self.control.run()
        self.assertEqual(calls,['/probe-binding','/api/status','/api/start','/api/stop','/api/status'])

if __name__=='__main__':unittest.main()
