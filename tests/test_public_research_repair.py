import asyncio,hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
OLD=Path('evidence/b6-public-research-20260923-v2/package')
NEW=Path('evidence/b6-public-research-repair-20260923/package')
def module(p):
 s=importlib.util.spec_from_file_location('repair_runner',p/'run.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class RepairTests(unittest.TestCase):
 def test_consumed_original_and_retained_regression(self):
  m=module(OLD)
  with patch.object(m.aiohttp,'ClientSession',side_effect=AssertionError('network')):
   with self.assertRaisesRegex(m.GlobalStop,'consumed'):m.consume(OLD.parent/'approval.json')
  d=json.loads((OLD.parent/'acquisition/discovery-decisions.json').read_text())[1]
  parents={d['parent_url']:('polymarket_us',(OLD.parent/'acquisition/02-response.bin').read_bytes())}
  with self.assertRaisesRegex(m.GlobalStop,'Excluded child'):m.Runner(json.loads((OLD/'spec.json').read_text())).validate_child(d,parents)
 def test_exact_document_path_allowed_without_admitting_market_api_or_siblings(self):
  m=module(NEW);spec=json.loads((NEW/'spec.json').read_text());calls=[];closed=[]
  class Response:
   status=200;headers={}
   def __init__(self,url):self.url=url;self.content=self
   async def __aenter__(self):return self
   async def __aexit__(self,*args):closed.append(self.url)
   async def iter_chunked(self,n):yield b'# Offline document fixture'
  class Client:
   def __init__(self,**kw):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   def get(self,url,**kw):calls.append(url);assert not kw['allow_redirects'];return Response(url)
  with tempfile.TemporaryDirectory() as d,patch.object(m,'OUTPUT',Path(d)),patch.object(m.aiohttp,'ClientSession',Client):
   r=m.Runner(spec)
   for row in spec['requests'][-2:]:asyncio.run(r.get(row))
   self.assertEqual(len(calls),2);self.assertEqual(calls,closed)
   for url in ['https://docs.polymarket.us/api-reference/markets/get-market-settlement.md','https://api.polymarket.us/v1/markets','https://docs.polymarket.us/learn/markets/other.md','https://kalshi.com/fee-schedule',spec['blocked_pdf']]:
    with self.assertRaises(m.GlobalStop):asyncio.run(r.get(dict(source='polymarket_us',url=url,format='text')))
   self.assertEqual(len(calls),2)
 def test_source_failure_retains_independent_documents(self):
  m=module(NEW);spec=json.loads((NEW/'spec.json').read_text());calls=[]
  class Response:
   status=429;headers={}
   def __init__(self,url):self.url=url;self.content=self
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def iter_chunked(self,n):yield b'challenge fixture'
  class Client:
   def __init__(self,**kw):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   def get(self,url,**kw):calls.append(url);return Response(url)
  with tempfile.TemporaryDirectory() as d,patch.object(m,'OUTPUT',Path(d)),patch.object(m.aiohttp,'ClientSession',Client):
   r=m.Runner(spec);asyncio.run(r.run());self.assertEqual(calls,[spec['requests'][0]['url'],spec['requests'][3]['url']])
 def test_prepared_package_once_stop_deadline(self):
  m=module(NEW)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);p=root/'package';p.mkdir();out=root/'out'
   for n in ('run.py','spec.json'):(p/n).write_bytes((NEW/n).read_bytes())
   (p/'freeze.json').write_text(json.dumps(dict(files={n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in ('run.py','spec.json')})))
   a=root/'approval.json';a.write_text(json.dumps(dict(approved=True,package_sha256=hashlib.sha256((p/'freeze.json').read_bytes()).hexdigest())))
   with patch.object(m,'ROOT',p),patch.object(m,'OUTPUT',out),patch.object(m.aiohttp,'ClientSession',side_effect=AssertionError('network')):
    spec=m.consume(a)
    with self.assertRaisesRegex(m.GlobalStop,'consumed'):m.consume(a)
    r=m.Runner(spec);(out/'STOP').touch()
    with self.assertRaises(m.GlobalStop):r.check()
    (out/'STOP').unlink();r.start-=91
    with self.assertRaises(m.GlobalStop):r.check()
