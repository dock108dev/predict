import json,time,threading,urllib.request,datetime
from pathlib import Path
out=Path(Path('.local/d2-validation-path.txt').read_text())
base='http://127.0.0.1:8783';done=threading.Event();start=time.monotonic()
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def record(name,x):
 with open(out/name,'a') as f:f.write(json.dumps(x)+'\n');f.flush()
def request(route,data=None,timeout=8):
 req=urllib.request.Request(base+route,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(req,timeout=timeout) as r:return dict(http=r.status,body=json.load(r))
def stop():
 if done.wait(max(0,start+90-time.monotonic())):return
 record('control.jsonl',dict(action='stop_requested',at=stamp(),elapsed=time.monotonic()-start))
 try:result=request('/api/stop',{},timeout=70)
 except Exception as e:result={'error':repr(e)}
 record('control.jsonl',dict(action='stop_response',at=stamp(),elapsed=time.monotonic()-start,result=result))
t=threading.Thread(target=stop);t.start()
record('control.jsonl',dict(action='start_requested',at=stamp(),monotonic=start))
try:
 result=request('/api/start',{'duration':180},timeout=20);record('control.jsonl',dict(action='start_response',at=stamp(),elapsed=time.monotonic()-start,result=result));print('START',result,flush=True)
 while time.monotonic()-start<180:
  s=request('/api/status')['body'];elapsed=time.monotonic()-start
  record('independent-status.jsonl',dict(at=stamp(),elapsed=elapsed,status=s))
  if int(elapsed)%10<2:print(round(elapsed,1),s['state'],s.get('stop_reason'),{v:{k:c.get(k) for k in ('generation','discovered_markets','requested','acknowledged','receiving','usable')} for v,c in (s.get('coverage') or {}).items()},flush=True)
  if not s['active']:
   record('control.jsonl',dict(action='inactive_observed',at=stamp(),elapsed=elapsed,reason=s.get('stop_reason')));done.set();break
  done.wait(2)
finally:
 t.join();print('CONTROL FINISHED',flush=True)
