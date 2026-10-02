"""Exact new inert package; offline seals and early-terminal controller controls."""
import shutil
from unittest.mock import patch
from tests import test_native_gap_package as prior
PACKAGE=prior.ROOT/'evidence/native-nyi-tor-20260930-v2'
class SemanticPackage(prior.PackageTests):
 def setUp(self):
  self.previous=prior.PACKAGE;prior.PACKAGE=PACKAGE
  super().setUp()
  for name in self.read('identity.json')['file_hashes']:
   if not (self.path/name).exists():shutil.copyfile(PACKAGE/name,self.path/name)
 def tearDown(self):
  try:super().tearDown()
  finally:prior.PACKAGE=self.previous
 def test_early_terminal_still_retains_stop_cleanup_and_consumption(self):
  self.activated();calls=[]
  def request(path,*args):
   calls.append(path)
   if path=='/probe-binding':return dict(status=200,body=self.read('identity.json'))
   if path=='/api/start':return dict(status=200,body=dict(started=True))
   return dict(status=200,body=dict(state='idle' if len(calls)==2 else 'completed',active=False,start_available=len(calls)==2))
  with patch.object(self.control,'request',side_effect=request),patch.object(self.control.time,'sleep'),patch.object(self.control.time,'monotonic',side_effect=[0,0,1,1]):self.control.run()
  self.assertEqual(calls,['/probe-binding','/api/status','/api/start','/api/status','/api/stop','/api/status'])
  self.assertFalse(self.read('terminal-status.json')['body']['active']);self.assertTrue(self.read('start-dispatch.json')['consumed'])
  with self.assertRaisesRegex(ValueError,'consumed'):self.control.run()
