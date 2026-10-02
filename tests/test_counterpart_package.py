"""Offline seals, spent reservations and optional repair/retest; no transports."""
import importlib.util,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];PACKAGE=ROOT/'scripts/v1_counterpart_package'
class Package(unittest.TestCase):
 def module(self):
  s=importlib.util.spec_from_file_location('counterpart_master_control',PACKAGE/'master.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_actual_package_is_unapproved_unused_and_exact(self):
  m=self.module();master,spec=m.checked(False);self.assertEqual(m.ledger(master),[]);self.assertFalse(Path(master['output_root']).exists());self.assertFalse((PACKAGE/'owner-approval.json').exists())
  with self.assertRaises(FileNotFoundError):m.checked(True)
  from app.collection.native_approval import implementation,digest
  self.assertEqual(master['initial_implementation_sha256'],digest(implementation()))
 def test_two_irreversible_reservations_require_cleanup_and_repair_reason(self):
  m=self.module();proof=['evidence/v1-counterpart-completion-20261001-v1/runtime-verification.json']
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'OFFLINE';shutil.copytree(PACKAGE,p,ignore=shutil.ignore_patterns('__pycache__'));master=json.loads((p/'master.json').read_text());master['output_root']=str(Path(tmp)/'OFFLINE-outputs');(p/'master.json').write_text(json.dumps(master));(p/'owner-approval.json').write_text(json.dumps(dict(approved=True,master_sha256=m.digest(master))))
   with patch.object(m,'PACKAGE',p):
    child=m.reserve('OFFLINE synthetic reservation only',proof);rows=m.ledger(master);self.assertEqual(len(rows),1);self.assertTrue((child/'approval.json').exists());self.assertFalse(Path(rows[0]['output']).exists())
    with self.assertRaisesRegex(ValueError,'cleanup'):m.reserve('repair/retest: SYNTHETIC narrow fix',proof)
    self.assertEqual(len(m.ledger(master)),1)
    report=Path(rows[0]['output'])/'OFFLINE-session';report.mkdir(parents=True);(report/'report.json').write_text(json.dumps(dict(cleanup_complete=True)))
    with self.assertRaisesRegex(ValueError,'repair/retest'):m.reserve('another general collection',proof)
    m.reserve('repair/retest: SYNTHETIC exact failed counterpart',proof);self.assertEqual(len(m.ledger(master)),2)
    with self.assertRaisesRegex(ValueError,'exhausted'):m.reserve('repair/retest: third forbidden',proof)
    ledger=p/'reservations.jsonl';ledger.write_bytes(ledger.read_bytes()[:-1])
    with self.assertRaisesRegex(ValueError,'Uncertain'):m.ledger(master)
