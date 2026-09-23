import asyncio,hashlib,importlib.util,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
PACKAGE=Path('evidence/b6-public-prerequisites-20260923-v1/package')
def module():
 spec=importlib.util.spec_from_file_location('public_doc_runner',PACKAGE/'run.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class PackageTests(unittest.IsolatedAsyncioTestCase):
 async def test_http_error_closes_one_source_only_and_preserves_bytes(self):
  m=module();spec=json.loads((PACKAGE/'spec.json').read_text());attempts=[]
  class Response:
   status=429;headers={'Content-Type':'text/html'}
   def __init__(self,url):self.url=url;self.content=self
   async def iter_chunked(self,n):yield b'challenge fixture'
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
  class Client:
   def __init__(self,**kw):self.kw=kw
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   def get(self,url,**kw):attempts.append(url);self.assertion=kw=={'allow_redirects':False};return Response(url)
  with tempfile.TemporaryDirectory() as d,patch.object(m,'OUTPUT',Path(d)),patch.object(m.aiohttp,'ClientSession',Client):
   r=m.Runner(spec);await r.run()
   self.assertEqual(attempts,[spec['requests'][0]['url'],spec['requests'][2]['url']])
   self.assertEqual(r.closed,{'kalshi','polymarket_us'})
   self.assertEqual((Path(d)/'01-response.bin').read_bytes(),b'challenge fixture')
   self.assertEqual(len(r.log),2)
 async def test_global_stop_deadline_and_blocked_url_never_open_network(self):
  m=module();spec=json.loads((PACKAGE/'spec.json').read_text())
  with tempfile.TemporaryDirectory() as d,patch.object(m,'OUTPUT',Path(d)),patch.object(m.aiohttp,'ClientSession',side_effect=AssertionError('network')):
   r=m.Runner(spec)
   with self.assertRaises(m.GlobalStop):await r.get(dict(source='kalshi',url=spec['blocked_pdf'],format='pdf'))
   r.start=time.monotonic()-91
   with self.assertRaises(m.GlobalStop):await r.get(spec['requests'][0])
   r.start=time.monotonic();(Path(d)/'STOP').touch()
   with self.assertRaises(m.GlobalStop):await r.get(spec['requests'][0])
 async def test_fresh_approval_integrity_and_once_only(self):
  m=module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);pkg=root/'package';pkg.mkdir();out=root/'output'
   for name in ('run.py','spec.json'):(pkg/name).write_bytes((PACKAGE/name).read_bytes())
   frozen={'files':{n:hashlib.sha256((pkg/n).read_bytes()).hexdigest() for n in ('run.py','spec.json')}}
   (pkg/'freeze.json').write_text(json.dumps(frozen));approval=root/'approval.json'
   approval.write_text(json.dumps({'approved':False}))
   with patch.object(m,'ROOT',pkg),patch.object(m,'OUTPUT',out),patch.object(m.aiohttp,'ClientSession',side_effect=AssertionError('network')):
    with self.assertRaises(m.GlobalStop):m.consume(approval)
    self.assertFalse(out.exists())
    approval.write_text(json.dumps({'approved':True,'package_sha256':hashlib.sha256((pkg/'freeze.json').read_bytes()).hexdigest()}))
    m.consume(approval)
    with self.assertRaisesRegex(m.GlobalStop,'consumed'):m.consume(approval)
