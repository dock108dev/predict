"""Frozen public-document runner. Requires a fresh approval; never uses credentials."""
import asyncio,hashlib,json,os,resource,select,sys,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
import aiohttp
ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT.parent/'acquisition'
class GlobalStop(Exception):pass
class SourceStop(Exception):pass
def sha(b):return hashlib.sha256(b).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def save(name,obj):
 p=OUTPUT/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(obj,indent=2)+'\n');t.replace(p)
def consume(approval):
 if (OUTPUT/'consumed.json').exists():raise GlobalStop('Attempt already consumed')
 frozen=json.loads((ROOT/'freeze.json').read_text())
 for name,value in frozen['files'].items():
  if sha((ROOT/name).read_bytes())!=value:raise GlobalStop('Frozen package mismatch')
 value=json.loads(Path(approval).read_text())
 if value.get('approved') is not True or value.get('package_sha256')!=sha((ROOT/'freeze.json').read_bytes()):raise GlobalStop('Fresh exact-package approval required')
 OUTPUT.mkdir(exist_ok=True)
 with (OUTPUT/'consumed.json').open('x') as f:
  json.dump(dict(start=now(),approval_sha256=sha(Path(approval).read_bytes()),package_sha256=sha((ROOT/'freeze.json').read_bytes())),f);f.flush();os.fsync(f.fileno())
 return json.loads((ROOT/'spec.json').read_text())
class Runner:
 def __init__(self,spec):self.spec=spec;self.start=time.monotonic();self.log=[];self.total=0;self.closed=set();self.reason='';self.peak=0;self.children=[]
 def check(self):
  lim=self.spec['limits'];self.peak=max(self.peak,resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024))
  if (OUTPUT/'STOP').exists():raise GlobalStop('Operator Stop')
  if time.monotonic()-self.start>=lim['seconds']:raise GlobalStop('90-second deadline')
  if self.peak>lim['rss_bytes'] or sum(p.stat().st_size for p in OUTPUT.rglob('*') if p.is_file())>lim['output_bytes']:raise GlobalStop('Resource cap')
 async def monitor(self):
  while True:self.check();await asyncio.sleep(.025)
 async def get(self,row):
  self.check();lim=self.spec['limits'];url=row['url']
  if row not in self.spec['requests']+self.children:raise GlobalStop('Outside exact document allowlist')
  if len(self.log)>=lim['requests'] or any(r['url']==url for r in self.log) or url==self.spec['blocked_pdf']:raise GlobalStop('Request scope/duplicate/cap')
  request_start=time.monotonic();deadline=min(request_start+lim['request_seconds'],self.start+lim['seconds'])
  r=dict(request_budget_seconds=deadline-request_start,attempt=len(self.log)+1,source=row['source'],url=url,start=now(),elapsed_start=time.monotonic()-self.start,credentials=False);self.log.append(r);save('requests.json',self.log)
  body=OUTPUT/('%02d-response.bin'%len(self.log));size=0;digest=hashlib.sha256()
  try:
   async with asyncio.timeout(max(0,deadline-time.monotonic())):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=max(.000001,deadline-time.monotonic()),ceil_threshold=float('inf')),trust_env=False,auto_decompress=False,connector=aiohttp.TCPConnector(force_close=True),headers={'Accept-Encoding':'identity'}) as session:
     session._retry_connection=False
     async with session.get(url,allow_redirects=False) as response:
      r.update(status=response.status,headers_received=now(),headers=list(response.headers.items()),response_url=str(response.url))
      with body.open('xb') as f:
       async for chunk in response.content.iter_chunked(32768):
        self.check()
        if time.monotonic()>=deadline:raise asyncio.TimeoutError('Request body deadline')
        if size+len(chunk)>lim['body_bytes'] or self.total+len(chunk)>lim['retained_body_bytes']:raise GlobalStop('Body/storage cap')
        f.write(chunk);digest.update(chunk);size+=len(chunk);self.total+=len(chunk)
      if time.monotonic()>=deadline:raise asyncio.TimeoutError('Request completion deadline')
      r['complete_body']=True
      if response.status!=200:raise SourceStop('HTTP '+str(response.status)+'; no redirect/retry')
      if str(response.url)!=url:raise GlobalStop('Response URL mismatch')
      if response.headers.get('Content-Encoding','identity') not in ('identity',''):raise SourceStop('Unsupported encoding')
      data=body.read_bytes()
      if row['format']=='pdf' and not data.startswith(b'%PDF-'):raise SourceStop('Expected PDF')
      if row['format']=='text' and (b'<html' in data[:1024].lower() or b'<!doctype html' in data[:1024].lower()):raise SourceStop('Expected documentation, received HTML')
      if row['format']=='json':
       try:json.loads(data)
       except (ValueError,UnicodeError):raise SourceStop('Expected JSON')
      if any(x in data[:8192].lower() for x in (b'verify you are human',b'cf-chl-',b'captcha')):raise SourceStop('Challenge; no bypass')
      if time.monotonic()>=deadline:raise asyncio.TimeoutError('Validation deadline')
      return data
  except (SourceStop,asyncio.TimeoutError,aiohttp.ClientError) as exc:
   r['error']=type(exc).__name__+': '+str(exc);self.closed.add(row['source']);return None
  except asyncio.CancelledError:
   r['error']='CancelledError: global Stop or deadline';raise
  except GlobalStop as exc:
   r['error']='GlobalStop: '+str(exc);raise
  finally:
   closed_at=time.monotonic();r.update(request_elapsed_seconds=closed_at-request_start,deadline_overrun_seconds=max(0,closed_at-deadline),transport_closed=True,within_request_deadline=closed_at<=deadline)
   r.update(body=body.name if body.exists() else None,bytes=size,sha256=digest.hexdigest(),end=now(),elapsed_end=time.monotonic()-self.start);save('requests.json',self.log)
   print(json.dumps({k:r.get(k) for k in ('attempt','source','url','status','error')}),flush=True)
 def child(self,d,parents):
  from urllib.parse import urljoin,unquote
  import re
  from html.parser import HTMLParser
  source=d.get('source');parent=d.get('parent_url');url=d.get('url','');passage=d.get('relevance_passage','')
  if parent not in parents or parents[parent][0]!=source or source not in self.spec['child_hosts'] or d.get('topic') not in self.spec['topics']:raise GlobalStop('Unresolved source/parent/topic')
  text=parents[parent][1].decode('utf-8');links=[]
  class Links(HTMLParser):
   def handle_starttag(self,tag,attrs):
    if tag=='a':links.extend(v for k,v in attrs if k=='href' and v)
  Links().feed(text);links.extend(re.findall(r'\]\(([^\s)]+)\)',text))
  if url not in [urljoin(parent,x) for x in links] or not passage or passage not in text or not any(urljoin(parent,x)==url and x in passage for x in links):raise GlobalStop('Missing exact link/relevance')
  u=urlsplit(url);path=unquote(u.path).lower()
  if u.scheme!='https' or u.hostname not in self.spec['child_hosts'][source] or u.username or u.password or u.port not in (None,443) or u.query or u.fragment:raise GlobalStop('Outside document scope')
  if url in self.spec['blocked_urls'] or any(x in path for x in ('fee-schedule.pdf','/fee-schedule','proxy','mirror','/api/','/trade-api/','/v1/','/search')) or (('/markets/' in path or '/events/' in path) and not path.startswith('/learn/')):raise GlobalStop('Excluded endpoint')
  return dict(source=source,url=url,format='pdf' if path.endswith('.pdf') else 'text' if path.endswith(('.md','.txt')) else 'html')
 async def run(self):
  parents={}
  for row in self.spec['requests']:
   if row['source'] not in self.closed:
    data=await self.get(row)
    if data:parents[row['url']]=(row['source'],data)
  if not parents:self.reason='No successful parents; investigation closed';return
  print('Within remaining deadline, provide one JSON list (or []) of at most three Kalshi and one US directly linked documents with source,parent_url,url,topic,relevance_passage.',flush=True)
  buffer=b''
  while b'\n' not in buffer:
   self.check()
   if select.select([sys.stdin],[],[],0)[0]:
    chunk=os.read(sys.stdin.fileno(),4096)
    if not chunk:break
    buffer+=chunk
    if len(buffer)>65536:raise GlobalStop('Discovery input cap')
   await asyncio.sleep(.025)
  decisions=json.loads(buffer.decode() or '[]');save('discovery-decisions.json',decisions)
  if not isinstance(decisions,list) or len(decisions)>4:raise GlobalStop('Discovery cap')
  counts={}
  for d in decisions:
   row=self.child(d,parents);source=row['source'];counts[source]=counts.get(source,0)+1
   if counts[source]>(3 if source=='kalshi' else 1):raise GlobalStop('Source document cap')
   self.children.append(row)
  for row in self.children:
   if row['source'] not in self.closed:await self.get(row)
  self.reason='Final public investigation complete; unresolved questions go to drafted provider inquiry'
async def main(approval):
 spec=consume(approval);r=Runner(spec)
 try:
  async with asyncio.timeout(spec['limits']['seconds']):
   job=asyncio.create_task(r.run());watch=asyncio.create_task(r.monitor())
   try:
    done,pending=await asyncio.wait((job,watch),return_when=asyncio.FIRST_COMPLETED)
    for task in done:task.result()
   finally:
    for task in (job,watch):task.cancel()
    await asyncio.gather(job,watch,return_exceptions=True)
 except BaseException as exc:r.reason=type(exc).__name__+': '+str(exc)
 finally:
  save('result.json',dict(consumed=True,stop_reason=r.reason,requests=len(r.log),closed_sources=sorted(r.closed),elapsed=time.monotonic()-r.start,peak_rss_bytes=r.peak,body_bytes=r.total,connections_closed=True,credentials=False,retries=0,credits=0))
if __name__=='__main__':
 if len(sys.argv)!=2:raise SystemExit('Usage: python run.py /path/to/fresh-approval.json (not approved yet)')
 asyncio.run(main(sys.argv[1]))
