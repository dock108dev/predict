"""Fresh offline process: ordinary routes from immutable selected journal bytes."""
import asyncio,json,sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from aiohttp.test_utils import TestClient,TestServer
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_history import load

async def run(root,request_path,output):
 root=Path(root);request=json.loads(Path(request_path).read_text());sid=request['sid'];folder=root/sid
 async def close():pass
 owner=SimpleNamespace(output=root,session=None,start_controls=frozenset(),close=close,status=lambda:dict(active=False),saved=lambda:[],active=lambda:False,history_paths=lambda:{sid:folder})
 client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=root/'fresh-watchlists.json')));await client.start_server()
 try:
  origin=str(client.make_url('')).rstrip('/')
  watches=[{k:v for k,v in w.items() if k!='id'} for w in request.get('watchlists',[])]
  response=await client.post('/api/watchlists',json=watches,headers={'Origin':origin});assert response.status==200,await response.text()
  result={'snapshot':load(folder,request['cutoff']),'responses':[]}
  for path in request['get']:
   r=await client.get(path);assert r.status==200,(path,await r.text());result['responses'].append(await r.json())
  origin=str(client.make_url('')).rstrip('/')
  result['replays']=[]
  for bundle in request['bundles']:
   r=await client.post('/api/math-scenario',json={'replay':bundle},headers={'Origin':origin});assert r.status==200,await r.text();result['replays'].append(await r.json())
  Path(output).write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
 finally:await client.close()

if __name__=='__main__':asyncio.run(run(*sys.argv[1:]))
