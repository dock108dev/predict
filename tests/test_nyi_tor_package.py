"""Once-only unapproved package gates, inherited adversarial launcher/control tests."""
import shutil
from tests import test_native_gap_package as prior
PACKAGE=prior.ROOT/'evidence/native-nyi-tor-20260930-v1'
class TargetPackage(prior.PackageTests):
 def setUp(self):
  self.previous=prior.PACKAGE;prior.PACKAGE=PACKAGE
  super().setUp()
  for name in self.read('identity.json')['file_hashes']:
   if not (self.path/name).exists():shutil.copyfile(PACKAGE/name,self.path/name)
 def tearDown(self):
  try:super().tearDown()
  finally:prior.PACKAGE=self.previous
