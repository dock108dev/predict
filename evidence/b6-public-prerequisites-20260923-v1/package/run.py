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
 def __init__(self,spec):self.spec=spec;self.start=time.monotonic();self.log=[];self.total=0;self.closed=set();self.reason='';self.peak=0
 def check(self):
  lim=self.spec['limits'];self.peak=max(self.peak,resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024))
  if (OUTPUT/'STOP').exists():raise GlobalStop('Operator Stop')
  if time.monotonic()-self.start>=lim['seconds']:raise GlobalStop('90-second deadline')
  if self.peak>lim['rss_bytes'] or sum(p.stat().st_size for p in OUTPUT.rglob('*') if p.is_file())>lim['output_bytes']:raise GlobalStop('Resource cap')
 async def monitor(self):
  while True:self.check();await asyncio.sleep(.025)
 async def get(self,row):
  self.check();lim=self.spec['limits'];url=row['url']
  if len(self.log)>=lim['requests'] or any(r['url']==url for r in self.log) or url==self.spec['blocked_pdf']:raise GlobalStop('Request scope/duplicate/cap')
  r=dict(attempt=len(self.log)+1,source=row['source'],url=url,start=now(),elapsed_start=time.monotonic()-self.start,credentials=False);self.log.append(r);save('requests.json',self.log)
  body=OUTPUT/('%02d-response.bin'%len(self.log));size=0;digest=hashlib.sha256()
  try:
   async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=min(10,90-(time.monotonic()-self.start))),trust_env=False,auto_decompress=False,connector=aiohttp.TCPConnector(force_close=True),headers={'Accept-Encoding':'identity'}) as session:
    session._retry_connection=False
    async with session.get(url,allow_redirects=False) as response:
     r.update(status=response.status,headers_received=now(),headers=list(response.headers.items()),response_url=str(response.url))
     with body.open('xb') as f:
      async for chunk in response.content.iter_chunked(32768):
       self.check()
       if size+len(chunk)>lim['body_bytes'] or self.total+len(chunk)>lim['retained_body_bytes']:raise GlobalStop('Body/storage cap')
       f.write(chunk);digest.update(chunk);size+=len(chunk);self.total+=len(chunk)
     r['complete_body']=True
     if response.status!=200:raise SourceStop('HTTP '+str(response.status)+'; no redirect/retry')
     if str(response.url)!=url:raise GlobalStop('Response URL mismatch')
     if response.headers.get('Content-Encoding','identity') not in ('identity',''):raise SourceStop('Unsupported encoding')
     data=body.read_bytes()
     if row['format']=='pdf' and not data.startswith(b'%PDF-'):raise SourceStop('Expected PDF')
     if row['format']=='text' and (b'<html' in data[:1024].lower() or b'<!doctype html' in data[:1024].lower()):raise SourceStop('Expected documentation, received HTML')
     return data
  except (SourceStop,asyncio.TimeoutError,aiohttp.ClientError) as exc:
   r['error']=type(exc).__name__+': '+str(exc);self.closed.add(row['source']);return None
  finally:
   r.update(body=body.name if body.exists() else None,bytes=size,sha256=digest.hexdigest(),end=now(),elapsed_end=time.monotonic()-self.start);save('requests.json',self.log)
   print(json.dumps({k:r.get(k) for k in ('attempt','source','url','status','error')}),flush=True)
 async def run(self):
  us=None
  for row in self.spec['requests']:
   if row['source'] not in self.closed:
    data=await self.get(row)
    if row['url']=='https://docs.polymarket.us/fees.md':us=data
  if us:
   print('Optional US document: send {"url":null} if no authoritative exact-market link exists, otherwise {"url":"exact directly linked HTTPS URL","market":"779756","applicability_passage":"exact passage from fee page"}. Deadline continues.',flush=True)
   while not select.select([sys.stdin],[],[],0)[0]:self.check();await asyncio.sleep(.05)
   decision=json.loads(sys.stdin.readline());save('us-link-review.json',decision)
   if decision.get('url'):
    text=us.decode('utf-8');url=decision['url'];p=urlsplit(url);passage=decision.get('applicability_passage','')
    if p.scheme!='https' or p.hostname not in ('docs.polymarket.us','polymarket.us','www.polymarket.us') or p.username or p.password or p.port not in (None,443) or p.fragment or decision.get('market')!='779756' or not passage or passage not in text or '779756' not in passage or url not in passage or not ('('+url+')' in text or 'href="'+url+'"' in text):raise GlobalStop('Unresolved exact US contract linkage')
    await self.get(dict(source='polymarket_us',url=url,format='pdf' if p.path.lower().endswith('.pdf') else 'text'))
  self.reason='Complete; unresolved/skipped slots unused'
async def main(approval):
 spec=consume(approval);r=Runner(spec)
 try:
  async with asyncio.timeout(90):
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
