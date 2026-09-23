import asyncio,importlib.util,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
class DeadlineTests(unittest.IsolatedAsyncioTestCase):
 async def test_timeout_does_not_round_and_closes_socket(self):
  path=Path('evidence/b6-native-review-20260923-v5/repaired-runner-template.py');s=importlib.util.spec_from_file_location('unrounded_runner',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
  async def handler(reader,writer):
   try:await reader.read()
   finally:writer.close();await writer.wait_closed()
  server=await asyncio.start_server(handler,'127.0.0.1',0)
  url='http://127.0.0.1:'+str(server.sockets[0].getsockname()[1])+'/offline-blackhole'
  spec=json.loads(Path('evidence/b6-public-research-repair-20260923/package/spec.json').read_text());spec['requests']=[dict(source='polymarket_us',url=url,format='text')];spec['limits']['request_seconds']=.05
  factory=m.aiohttp.ClientSession;timeouts=[]
  def client(**kw):timeouts.append(kw['timeout']);return factory(**kw)
  try:
   with tempfile.TemporaryDirectory() as d,patch.object(m,'OUTPUT',Path(d)),patch.object(m.aiohttp,'ClientSession',client):
    r=m.Runner(spec);started=time.monotonic();await r.run()
    self.assertLess(time.monotonic()-started,.5);self.assertEqual(timeouts[0].ceil_threshold,float('inf'));self.assertEqual(timeouts[0].total,.05)
    self.assertEqual(r.closed,{'polymarket_us'});self.assertIn('TimeoutError',r.log[0]['error']);self.assertEqual(len(r.log),1)
  finally:server.close();await server.wait_closed()
