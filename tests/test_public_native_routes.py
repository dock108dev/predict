"""Retained real native capture through public opt-in ordinary Details/download."""
import unittest,tempfile,shutil,json,sys,asyncio
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from copy import deepcopy
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from tests.test_native_book_capture import FOLDER,SID
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_history import load
from app.dashboard.session_projection import stable
from app.collection.public_contracts import VERSION

class RetainedPublicDetails(unittest.IsolatedAsyncioTestCase):
 async def test_public_native_details_preserve_original_and_reopen_exactly(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/SID;shutil.copytree(FOLDER,folder)
   snapshot=load(folder);g=snapshot['games'][0]
   async def close():pass
   owner=SimpleNamespace(output=root,session=None,start_controls=frozenset(),close=close,status=lambda:dict(active=False),saved=lambda:[],active=lambda:False,history_paths=lambda:{SID:folder})
   client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=root/'watches.json')));await client.start_server()
   async def get(q):
    r=await client.get('/api/calculate?'+urlencode(q));self.assertEqual(r.status,200,await r.text());return await r.json()
   try:
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No account access')):
     q=dict(session=SID+'~'+g['id'],hash=SID,cutoff=snapshot['durable_cursor'],quantity='100')
     original=await get(q);public=await get(dict(q,public_binding_version=VERSION));self.assertTrue(public['native_raw']);self.assertTrue(public['public_contracts'])
     stripped=deepcopy(public);stripped.pop('public_contracts');stripped.pop('sha256')
     for row,old in zip(stripped['comparisons'],original['comparisons']):
      row.pop('public_contracts',None)
      for key in ('settlement','costs'):
       self.assertEqual(row['decision'][key][:len(old['decision'][key])],old['decision'][key])
      for key in ('version','freshness','quantity','net_reason','conclusion'):
       self.assertEqual(row['decision'][key],old['decision'][key])
      row['decision']=old['decision']
     expected=deepcopy(original);expected.pop('sha256');self.assertEqual(stripped,expected)
     self.assertTrue(all(row['net'] is None for row in public['comparisons']));self.assertTrue(all(row['raw_difference'] is not None for row in public['comparisons']))
     self.assertEqual(await get(dict(q,public_binding_version=VERSION,download='true')),public)
     self.assertEqual(public['sha256'],stable({k:v for k,v in public.items() if k!='sha256'}))
     self.assertEqual(await get(q),original)
     request=dict(sid=SID,cutoff=snapshot['durable_cursor'],get=['/api/calculate?'+urlencode(dict(q,public_binding_version=VERSION))],bundles=[])
     req=root/'request.json';req.write_text(json.dumps(request));result=root/'result.json'
     proc=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.public_contract_reopen',str(root),str(req),str(result),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
     out,err=await asyncio.wait_for(proc.communicate(),25);self.assertEqual(proc.returncode,0,err.decode());self.assertEqual(json.loads(result.read_text())['responses'],[public])
     evidence=Path('evidence/public-contract-integration-20261001-v1/verification');(evidence/'retained-public-native-details.json').write_text(json.dumps(public,indent=2)+'\n')
   finally:await client.close()
