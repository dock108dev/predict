"""OFFLINE real-mode startup; unchanged retained listings, synthetic protocol only."""
import asyncio, base64, io, json, socket, subprocess, sys
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import urlsplit
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from app.collection.native_approval import digest, implementation
from app.collection.transport_session import reopen
from app.collection.venue_access import ENDPOINTS
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_history import load, project_rows
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/native-books-preparation-20260930'
PAGES=json.loads((ROOT/'evidence/native-gap-derived-20260930-v1/captured-pages.json').read_text())
class Response:
 headers={}
 def __init__(self,p):self.status=p['status'];self.buffer=io.BytesIO(base64.b64decode(p['body_b64']));self.content=self
 async def read(self,size):return self.buffer.read(size)
 async def __aenter__(self):return self
 async def __aexit__(self,*a):pass
class HTTP:
 calls=[];clients=[]
 def __init__(self,*a,**kw):self.connector=kw.get('connector');self.closed=False;self.clients.append(self)
 def get(self,url,*,params,**kw):
  host=urlsplit(url).hostname;assert host in ('external-api.kalshi.com','gateway.polymarket.us')
  source='kalshi' if host=='external-api.kalshi.com' else 'polymarket_us';path=urlsplit(url).path
  assert kw['headers']=={'Accept-Encoding':'identity'} and kw['allow_redirects'] is False
  q={k:str(v) for k,v in params.items() if k not in ('startTimeMin','startTimeMax')}
  self.calls.append(dict(source=source,path=path,params=params))
  matches=[p for p in PAGES if p['source']==source and p['path']==path and {k:str(v) for k,v in p['params'].items() if k not in ('startTimeMin','startTimeMax')}==q]
  assert len(matches)==1,('OFFLINE missing response',source,path,q)
  return Response(matches[0])
 async def close(self):
  self.closed=True
  if self.connector:await self.connector.close()
class Credential:
 def headers(self,*a):return {'OFFLINE-Protocol-Fixture':'not-a-credential'}
 def check(self,*a):pass
class Socket:
 instances=[];scenario="normal"
 def __init__(self,v,epoch):self.venue=v;self.epoch=epoch;self.index=0;self.closed=False;self.sent=[];self.instances.append(self)
 async def send(self,body):
  c=json.loads(body);self.sent.append(c)
  if self.venue=='kalshi':
   assert c['params']==dict(channels=['orderbook_delta'],market_tickers=['KXNCAAFGAME-26OCT01WKUNMSU-NMSU'])
  else:assert c['subscribe']['marketSlugs']==['aec-cfb-wkent-nmxst-2026-10-01']
 async def recv(self):
  await asyncio.sleep(.03);i=self.index;self.index+=1
  if self.venue=='kalshi':
   rid=self.sent[0]['id'];mid=self.sent[0]['params']['market_tickers'][0]
   if i==0:return json.dumps(dict(id=rid,type='subscribed',msg=dict(channel='orderbook_delta',sid=self.epoch)))
   if i==1:return json.dumps(dict(type='orderbook_snapshot',sid=self.epoch,seq=1,msg=dict(market_ticker=mid,market_id='OFFLINE-native-uuid',yes_dollars_fp=[['0.4000','10.00']],no_dollars_fp=[['0.5000','20.00']])))
   if self.epoch==1 and i in (2,3,4):
    # zero delta, quantity change, duplicate sequence => mandatory recovery.
    return json.dumps(dict(type='orderbook_delta',sid=1,seq=2 if i==2 else 5 if i==4 and self.scenario=='gap' else 3,msg=dict(market_ticker=mid,market_id='OFFLINE-native-uuid',side='yes',price_dollars='0.4000',delta_fp='0.00' if i==2 else '2.00',ts_ms=1790762400000)))
  else:
   if i<4:
    return json.dumps(dict(requestId=self.sent[0]['subscribe']['requestId'],subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',marketData=dict(marketSlug=self.sent[0]['subscribe']['marketSlugs'][0],bids=[dict(px=dict(value='0.4' if i<3 else '0.42',currency='USD'),qty='10.00' if i<2 else '12.00')],offers=[dict(px=dict(value='0.55',currency='USD'),qty='20.00')],transactTime='2026-09-30T10:00:00Z')))
   if self.epoch==1 and i==4:raise ConnectionError('OFFLINE controlled disconnect')
  await asyncio.sleep(120)
 async def close(self):self.closed=True
COUNTS={}
async def connect_ws(url,**kw):
 v=next(v for v,e in ENDPOINTS.items() if e['ws']==url)
 assert kw['additional_headers']=={'OFFLINE-Protocol-Fixture':'not-a-credential'}
 assert kw['proxy'] is None and kw['compression'] is None and kw['max_queue']==1
 COUNTS[v]=COUNTS.get(v,0)+1;assert COUNTS[v]<=2
 return Socket(v,COUNTS[v])
class Connector:
 def __init__(self,url,**kw):self.url=url;self.kw=kw
 def __await__(self):return connect_ws(self.url,**self.kw).__await__()

async def run(duration=16, scenario="normal"):
 HTTP.calls=[];HTTP.clients=[];Socket.instances=[];Socket.scenario=scenario;COUNTS.clear()
 out=OUT/('OFFLINE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'));out.mkdir()
 spec=json.loads((ROOT/'evidence/native-books-20260930/run-spec.json').read_text());spec['duration']=duration
 spec['capture_authorization']='OFFLINE retained listing / synthetic protocol rehearsal, external access intercepted'
 dest=out/'session';approval=out/'OFFLINE-approval.json';ident=digest(implementation())
 approval.write_text(json.dumps(dict(approved=True,output=str(dest),implementation_sha256=ident,spec_sha256=digest(spec))))
 owner=CoverageOwner(out/'saved',pilot_output=dest,endpoints=ENDPOINTS,spec_factory=lambda:deepcopy(spec),product_mode=True,native_approval_path=approval)
 client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=out/'watches.json')));await client.start_server();origin={'Origin':str(client.make_url('/')).rstrip('/')}
 orig=socket.socket.connect;opened=Path.open;credential_calls=[]
 def connect(sock,address):
  assert isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'),'External socket forbidden'
  return orig(sock,address)
 def safe_open(path,*a,**kw):
  assert path.name!='.env','Credential file forbidden'
  return opened(path,*a,**kw)
 def credentials(venues):
  credential_calls.extend(venues)
  if scenario=='missing_us_credential' and venues==['polymarket_us']:raise RuntimeError('OFFLINE missing credential control')
  return {v:Credential() for v in venues}
 try:
  with patch('socket.socket.connect',connect),patch.object(Path,'open',safe_open),patch('aiohttp.ClientSession',HTTP),patch('app.collection.venue_access.load_credentials',credentials),patch('app.collection.prediction_producer.connect',Connector):
   res=await client.post('/api/start',json={'duration':duration},headers=origin);assert res.status==200,await res.text()
   if scenario=='early_stop':
    await asyncio.sleep(4)
    assert (await client.post('/api/stop',json={},headers=origin)).status==200
   await owner.finalizer
   assert (await client.post('/api/stop',json={},headers=origin)).status==200
   assert not owner.error,owner.error
   s=owner.session;assert s.cleanup_complete and not s.aggregate
   rows=reopen(s.journal.path)['rows'];saved=load(s.output);assert saved==project_rows(rows,saved['durable_cursor'])
   assert s.discovery.published_generation==1
   assert len(HTTP.calls)==3 and COUNTS==(dict(kalshi=2) if scenario=='missing_us_credential' else dict(kalshi=2,polymarket_us=2)),(HTTP.calls,COUNTS)
   obs=[r['native_observation'] for r in rows if r.get('native_observation')]
   assert {x['classification'] for x in obs}=={'initial_snapshot','recovery_snapshot','repeated_identical_observation','price_or_quantity_change'}
   if duration>=16 and scenario!='early_stop':assert any(r['type']=='prediction_book' and r['book']['receipt_freshness']=='stale' for r in rows)
   assert any(r['type']=='source_health' and r['state']=='disconnected' for r in rows)
   assert all(x.closed for x in HTTP.clients+Socket.instances)
   code='from pathlib import Path;import sys;from app.dashboard.session_history import load;from app.collection.native_approval import digest;print(digest(load(Path(sys.argv[1]))))'
   fresh=subprocess.check_output([sys.executable,'-c',code,str(s.output)],text=True).strip();assert fresh==digest(saved)
   feed=await(await client.get('/api/dashboard?view=feed&capture='+s.sid)).json();assert not feed.get('error'),feed
   assert len([m for m in saved['market_catalog'] if m.get('book_evidence')])==(1 if scenario=='missing_us_credential' else 2)
   assert not saved['games'],'Raw acquisition cannot create qualified games/economics'
   before=(len(HTTP.calls),dict(COUNTS),len(rows));await asyncio.sleep(.1)
   assert before==(len(HTTP.calls),dict(COUNTS),len(reopen(s.journal.path)['rows']))
   if scenario=='missing_us_credential':assert s.discovery.source_stops=={'polymarket_us':'dedicated_credential_unavailable'}
   report=json.loads((s.output/'report.json').read_text())
   result=dict(scenario=scenario,source_stops=s.discovery.source_stops,classification='OFFLINE unchanged retained listing bytes plus labeled synthetic book/ack/delta/recovery fixtures through ordinary real-mode Start. No live credential/provider access.',implementation_sha256=ident,spec_sha256=digest(spec),offline_output=str(s.output),collection_seconds=report['collection_seconds'],stop_reason=report['reason'],intercepted_http=HTTP.calls,intercepted_connections=COUNTS,credential_boundary_interceptions=credential_calls,external_requests=0,credential_access=0,aggregate_requests=0,credits=0,cleanup=True,ordinary_start_stop=True,saved_dashboard=True,details=True,fresh_process_reopening=True,saved_sha256=fresh,observations=obs,resources=s.resources())
   (out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
 finally:await client.close()
if __name__=='__main__':asyncio.run(run(int(sys.argv[1]) if len(sys.argv)>1 else 16,sys.argv[2] if len(sys.argv)>2 else 'normal'))
