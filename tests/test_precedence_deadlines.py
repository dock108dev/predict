import asyncio,hashlib,importlib.util,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
PACKAGE=Path('evidence/b6-precedence-final-20260923/package')
def module():
 s=importlib.util.spec_from_file_location('final_deadline',PACKAGE/'run.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class DeadlineCoverage(unittest.IsolatedAsyncioTestCase):
 measurements=[]
 async def exercise(self,kind,budget,stop=False):
  m=module();disconnected=asyncio.Event();tasks=set()
  async def server(reader,writer):
   task=asyncio.current_task();tasks.add(task)
   try:
    await reader.readuntil(b'\r\n\r\n')
    if kind!='headers':
     writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nContent-Type: text/plain\r\n\r\nretained-prefix');await writer.drain()
    if kind=='trickle':
     while True:
      await asyncio.sleep(.01);writer.write(b'.');await writer.drain()
    else:await reader.read()
   except (ConnectionError,asyncio.IncompleteReadError):pass
   finally:
    writer.close()
    try:await writer.wait_closed()
    except ConnectionError:pass
    disconnected.set();tasks.discard(task)
  listener=await asyncio.start_server(server,'127.0.0.1',0);url='http://127.0.0.1:'+str(listener.sockets[0].getsockname()[1])+'/fixture'
  spec=json.loads((PACKAGE/'spec.json').read_text());spec['requests']=[dict(source='kalshi',url=url,format='text')];spec['limits']['request_seconds']=budget
  try:
   with tempfile.TemporaryDirectory() as directory,patch.object(m,'OUTPUT',Path(directory)):
    r=m.Runner(spec);task=asyncio.create_task(r.get(spec['requests'][0]));watch=None;start=time.monotonic()
    if stop:
     await asyncio.sleep(.04);(Path(directory)/'STOP').touch();watch=asyncio.create_task(r.monitor())
     with self.assertRaises(m.GlobalStop):await watch
     task.cancel()
     with self.assertRaises(asyncio.CancelledError):await task
    else:await task
    elapsed=time.monotonic()-start;row=r.log[0]
    await asyncio.wait_for(disconnected.wait(),.5)
    self.assertTrue(row['transport_closed']);self.assertNotIn('complete_body',row);self.assertEqual(len(r.log),1)
    if not stop:
     self.assertIn('TimeoutError',row['error']);self.assertGreaterEqual(elapsed,budget-.02);self.assertLess(elapsed-budget,.1)
    else:self.assertIn('CancelledError',row['error']);self.assertLess(elapsed,.2)
    if kind!='headers':
     body=(Path(directory)/row['body']).read_bytes();self.assertTrue(body.startswith(b'retained-prefix'));self.assertEqual(hashlib.sha256(body).hexdigest(),row['sha256'])
    self.measurements.append(dict(case=kind,stop=stop,budget=budget,elapsed=elapsed,overrun=row['deadline_overrun_seconds'],partial_bytes=row['bytes']))
  finally:
   listener.close();await listener.wait_closed()
   for t in list(tasks):t.cancel()
   await asyncio.gather(*tasks,return_exceptions=True)
 async def test_full_ten_second_headers_timeout(self):await self.exercise('headers',10)
 async def test_body_stall(self):await self.exercise('body',.12)
 async def test_trickle_cannot_reset_total_budget(self):await self.exercise('trickle',.12)
 async def test_stop_cancels_body_and_preserves_partial_bytes(self):await self.exercise('body',10,True)
 @classmethod
 def tearDownClass(cls):print('DEADLINE_MEASUREMENTS='+json.dumps(cls.measurements))
class ScopeCoverage(unittest.TestCase):
 def test_exact_link_and_excluded_sources(self):
  m=module();r=m.Runner(json.loads((PACKAGE/'spec.json').read_text()));parent='https://kalshi.com/regulatory/filings';url='https://assets.kalshi.com/regulatory/amendment.pdf';text='<a href="'+url+'">FOOTBALLGAMEWIN amendment</a>';d=dict(source='kalshi',parent_url=parent,url=url,topic='FOOTBALLGAMEWIN effective amendment',relevance_passage=text)
  self.assertEqual(r.child(d,{parent:('kalshi',text.encode())})['url'],url)
  for u in ('https://evil.test/rules.pdf','https://kalshi.com/docs/kalshi-fee-schedule.pdf','https://kalshi.com/fee-schedule','https://kalshi.com/trade-api/v2/markets','https://kalshi.com/rules?search=yes'):
   t='<a href="'+u+'">rule</a>'
   with self.assertRaises(m.GlobalStop):r.child(dict(d,url=u,relevance_passage=t),{parent:('kalshi',t.encode())})
 def test_once_only_and_identity_before_network(self):
  m=module()
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'package';p.mkdir();out=Path(d)/'out'
   for n in ('run.py','spec.json'):(p/n).write_bytes((PACKAGE/n).read_bytes())
   (p/'freeze.json').write_text(json.dumps(dict(files={n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in ('run.py','spec.json')})))
   a=Path(d)/'approval.json';a.write_text(json.dumps(dict(approved=True,package_sha256=hashlib.sha256((p/'freeze.json').read_bytes()).hexdigest())))
   with patch.object(m,'ROOT',p),patch.object(m,'OUTPUT',out),patch.object(m.aiohttp,'ClientSession',side_effect=AssertionError('network')):
    before=(p/'spec.json').read_bytes();(p/'spec.json').write_bytes(before+b' ')
    with self.assertRaisesRegex(m.GlobalStop,'mismatch'):m.consume(a)
    (p/'spec.json').write_bytes(before);m.consume(a)
    with self.assertRaisesRegex(m.GlobalStop,'consumed'):m.consume(a)
 def test_independent_source_failures_do_not_expand_scope(self):
  m=module();spec=json.loads((PACKAGE/'spec.json').read_text());calls=[]
  class Response:
   status=429;headers={}
   def __init__(self,url):self.url=url;self.content=self
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def iter_chunked(self,n):yield b'challenge'
  class Client:
   def __init__(self,**kw):assert kw['timeout'].ceil_threshold==float('inf')
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   def get(self,url,**kw):calls.append(url);return Response(url)
  with tempfile.TemporaryDirectory() as d,patch.object(m,'OUTPUT',Path(d)),patch.object(m.aiohttp,'ClientSession',Client):
   r=m.Runner(spec);asyncio.run(r.run());self.assertEqual(calls,[x['url'] for x in spec['requests']]);self.assertEqual(r.closed,{'kalshi','polymarket_us'});self.assertFalse(r.children)
