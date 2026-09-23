import importlib.util,json,tempfile,unittest,asyncio,time,hashlib
from pathlib import Path
from unittest.mock import patch
PACKAGE=Path('evidence/b6-public-research-20260923-v2/package')
def module():
 spec=importlib.util.spec_from_file_location('research_runner',PACKAGE/'run.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class ResearchPackageTests(unittest.TestCase):
 def test_bounded_direct_discovery_and_exclusions(self):
  m=module();r=m.Runner(json.loads((PACKAGE/'spec.json').read_text()));parent='https://docs.polymarket.us/llms.txt';url='https://docs.polymarket.us/rules.md';text='[Contract rules]('+url+')';parents={parent:('polymarket_us',text.encode())}
  d=dict(source='polymarket_us',parent_url=parent,url=url,topic='contract rules and precedence',relevance_passage=text)
  self.assertEqual(r.validate_child(d,parents)['url'],url)
  for replacement in ('https://evil.test/rules.md','https://docs.polymarket.us/rules.pdf','https://docs.polymarket.us/rules.md?proxy=yes','https://docs.polymarket.us/markets/779756'):
   text='[Rules]('+replacement+')';parents[parent]=('polymarket_us',text.encode())
   with self.assertRaises(m.GlobalStop):r.validate_child(dict(d,url=replacement,relevance_passage=text),parents)
  with self.assertRaises(m.GlobalStop):r.validate_child(d,{})
 def test_source_failure_isolation_and_cleanup(self):
  m=module();s=json.loads((PACKAGE/'spec.json').read_text());calls=[];closed=[]
  class Response:
   status=429;headers={}
   def __init__(self,url):self.url=url;self.content=self
   async def __aenter__(self):return self
   async def __aexit__(self,*a):closed.append(self.url)
   async def iter_chunked(self,n):yield b'challenge fixture'
  class Client:
   def __init__(self,**kw):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   def get(self,url,**kw):calls.append(url);assert not kw['allow_redirects'];return Response(url)
  with tempfile.TemporaryDirectory() as d,patch.object(m,'OUTPUT',Path(d)),patch.object(m.aiohttp,'ClientSession',Client):
   r=m.Runner(s);asyncio.run(r.run());self.assertEqual(len(calls),2);self.assertEqual(closed,calls);self.assertEqual(r.closed,{'kalshi','polymarket_us'})
 def test_identity_consumption_stop_and_deadline_without_network(self):
  m=module();s=json.loads((PACKAGE/'spec.json').read_text())
  with tempfile.TemporaryDirectory() as d,patch.object(m.aiohttp,'ClientSession',side_effect=AssertionError('network')):
   root=Path(d);out=root/'out';out.mkdir();pkg=root/'package';pkg.mkdir()
   for n in ('run.py','spec.json'):(pkg/n).write_bytes((PACKAGE/n).read_bytes())
   (pkg/'freeze.json').write_text(json.dumps({'files':{n:hashlib.sha256((pkg/n).read_bytes()).hexdigest() for n in ('run.py','spec.json')}}))
   approval=root/'approval.json';approval.write_text(json.dumps(dict(approved=True,package_sha256=hashlib.sha256((pkg/'freeze.json').read_bytes()).hexdigest())))
   with patch.object(m,'ROOT',pkg),patch.object(m,'OUTPUT',out):
    m.consume(approval)
    with self.assertRaisesRegex(m.GlobalStop,'consumed'):m.consume(approval)
    r=m.Runner(s)
    with self.assertRaises(m.GlobalStop):asyncio.run(r.get(dict(source='kalshi',url=s['blocked_pdf'],format='pdf')))
    (out/'STOP').touch()
    with self.assertRaises(m.GlobalStop):r.check()
    (out/'STOP').unlink();r.start=time.monotonic()-91
    with self.assertRaises(m.GlobalStop):r.check()
