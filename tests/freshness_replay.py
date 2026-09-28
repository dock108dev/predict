"""Offline retained-input benchmark. Never imports a live launcher or rewrites inputs.

Usage: python tests/freshness_replay.py SOURCE_ROOT PORT OUTPUT
The replay clock measures local admission separately from original application receipt.
"""
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import asyncio,json,time
from types import SimpleNamespace
from aiohttp import web
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.session_projection import SessionProjection
from app.dashboard.session_history import verified
from app.dashboard.multi_game_server import create_app
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'evidence/live-comparison-multi-run-b9b5f3c7-514f-4ef6-b27d-ac77c5138c17/b9b5f3c7-514f-4ef6-b27d-ac77c5138c17'
rows=list(verified(folder)['rows']);out=Path(sys.argv[3]);out.mkdir(parents=True,exist_ok=True)
p=SessionProjection();index=0;receipts={};native_receipts={};events=[];running=True
# Start with all twelve initial books. The browser joins an existing replay.
while len(p.books)<12:
 p.apply(rows[index]);index+=1
def receipt_key(r):return (r['source'],r['book']['raw']['ref']['market_id'],r['book']['raw']['received_at'])
for r in p.books.values():
 native_receipts[receipt_key(r)]=time.time()*1000
 receipts[r['ingress_id']]=native_receipts[receipt_key(r)]
class Owner(CoverageOwner):
 def active(self):return running
 def status(self):return dict(state='running' if running else 'saved',active=running,start_available=False,operating_mode='product-session',session=self.session.sid)
 def saved(self):return []
 def history_paths(self):return {} if running else {self.session.sid:folder}
 async def close(self):pass
 def current_snapshot(self):
  result=super().current_snapshot();result['data_mode']='retained replay';return result
 async def stop(self):
  global running
  running=False
  return self.status()
o=Owner(out/'unused',product_mode=True);o.session=SimpleNamespace(projection=p,journal=None,persistence_error=None,projection_error=None,segmented_history=False,sid=rows[0]['session_id'],output=folder)
@web.middleware
async def measured(req,handler):
 started=time.perf_counter();resp=await handler(req)
 if req.path=='/api/dashboard' and resp.status==200:
  d=json.loads(resp.body);d['replay_receipts']=dict(receipts);d['replay_request_ms']=(time.perf_counter()-started)*1000
  resp=web.json_response(d)
 return resp
app=create_app(owner=o,sessions={});app.middlewares.insert(0,measured)
async def advance(req):
 global index
 start=time.perf_counter();n=int(req.query.get('count','1'));admitted=[]
 for _ in range(n):
  while index<len(rows)-1:
   r=rows[index];index+=1;p.apply(r)
   if r['type']=='prediction_book':
    key=receipt_key(r)
    native_receipts.setdefault(key,time.time()*1000)
    receipts[r['ingress_id']]=native_receipts[key];admitted.append(r['ingress_id']);break
 events.append(dict(index=index,books=admitted,apply_ms=(time.perf_counter()-start)*1000))
 return web.json_response(dict(index=index,books=admitted))
async def finish(req):
 (out/'replay-events.json').write_text(json.dumps(events,indent=2));return web.json_response(dict(saved=True))
app.router.add_post('/replay/advance',advance);app.router.add_post('/replay/finish',finish)
web.run_app(app,host='127.0.0.1',port=int(sys.argv[2]),print=None)
