"""Public binding schema and redaction boundaries, without transport."""
import io,json,unittest,sys,importlib.util
from pathlib import Path
from copy import deepcopy
from app.collection.control_binding import parse_identity,BODY_CAP
ROOT=Path(__file__).resolve().parents[1]
class BindingTests(unittest.TestCase):
 def setUp(self):self.i=json.loads((ROOT/'evidence/native-nyi-tor-20260930-v2/identity.json').read_text())
 def test_exact_public_authorization_hash(self):self.assertEqual(parse_identity(json.dumps(self.i).encode()),self.i)
 def test_missing_unknown_keys(self):
  for key in self.i:
   v=deepcopy(self.i);v.pop(key)
   with self.assertRaises(ValueError):parse_identity(json.dumps(v).encode())
  v=deepcopy(self.i);v['authorization']='constructed secret'
  with self.assertRaises(ValueError):parse_identity(json.dumps(v).encode())
 def test_bad_shapes_and_values(self):
  variants=[dict(self.i,file_hashes=[]),dict(self.i,attempt_id='bad'),dict(self.i,output='../bad'),dict(self.i,implementation_sha256='G'*64),dict(self.i,output='/'+('x'*4096))]
  for v in variants:
   with self.subTest(v=v.keys()),self.assertRaises(ValueError):parse_identity(json.dumps(v).encode())
 def test_duplicate_nonfinite_malformed_utf8_and_overflow(self):
  for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{',b'\xff',b'x'*(BODY_CAP+1),b'['*2000+b']'*2000):
   with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):parse_identity(raw)
 def test_filename_hash_schema(self):
  for name,value in (('../bad','0'*64),('AUTHORIZATION.txt','constructed secret')):
   v=deepcopy(self.i);v['file_hashes'][name]=value
   with self.assertRaises(ValueError):parse_identity(json.dumps(v).encode())
 def test_control_response_and_saved_redaction(self):
  sys.path.insert(0,str(ROOT/'scripts/native_package'))
  sp=importlib.util.spec_from_file_location('binding_test_control',ROOT/'scripts/native_package/control.py');c=importlib.util.module_from_spec(sp);sp.loader.exec_module(c)
  self.assertEqual(c.body(io.BytesIO(json.dumps(self.i).encode()),binding=True)['body'],self.i)
  secret=b'{"authorization":"constructed secret","credential":"fake"}'
  self.assertEqual(c.body(io.BytesIO(secret))['body']['authorization'],'[REDACTED]')
  self.assertIsNone(c.body(io.BytesIO(secret),binding=True)['body'])
  self.assertEqual(c.sanitize(self.i)['file_hashes']['AUTHORIZATION.txt'],'[REDACTED]')
  self.assertTrue(c.body(io.BytesIO(b'x'*(BODY_CAP+1)),binding=True)['truncated'])
if __name__=='__main__':unittest.main()
