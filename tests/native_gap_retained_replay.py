"""Offline ordinary real-mode replay of r2 bytes; missing responses are explicit gaps."""
import asyncio,base64,io,json,socket,subprocess,sys
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
from urllib.parse import urlsplit
from unittest.mock import patch
import aiohttp
from aiohttp.test_utils import TestClient,TestServer
from app.collection.native_approval import digest,implementation
from app.collection.odds_http import BudgetStop
from app.collection.transport_session import reopen
from app.collection.venue_access import ENDPOINTS
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_history import load,project_rows
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/native-gap-derived-20260930-v1'
class Response:
 headers={}
 def __init__(self,p):self.status=p['status'];self.complete=p['complete'];self.buffer=io.BytesIO(base64.b64decode(p['body_b64']));self.content=self
 async def read(self,size):
  data=self.buffer.read(size)
  if not data and not self.complete:raise BudgetStop('prediction_discovery_byte_cap')
  return data
 async def __aenter__(self):return self
 async def __aexit__(self,*a):pass
class HTTP:
 calls=[];gaps=[];clients=[]
 def __init__(self,*a,**kw):self.connector=kw.get('connector');self.closed=False;self.clients.append(self)
 def get(self,url,*,params,**kw):
  path=urlsplit(url).path;source='kalshi' if urlsplit(url).hostname=='external-api.kalshi.com' else 'polymarket_us'
  assert urlsplit(url).hostname in ('external-api.kalshi.com','gateway.polymarket.us')
  assert kw['headers']=={'Accept-Encoding':'identity'} and kw['allow_redirects'] is False
  # Time filters vary by replay Start; ignore only them in matching old responses.
  q={k:str(v) for k,v in params.items() if k not in ('startTimeMin','startTimeMax')}
  self.calls.append(dict(source=source,path=path,params=params))
  matches=[p for p in PAGES if p['source']==source and p['path']==path and {k:str(v) for k,v in p['params'].items() if k not in ('startTimeMin','startTimeMax')}==q]
  if not matches:
   self.gaps.append(dict(source=source,path=path,params=params));raise ValueError('OFFLINE retained response unavailable; no substitute or provider dispatch')
  return Response(matches[0])
 async def close(self):
  self.closed=True
  if self.connector:await self.connector.close()
PAGES=json.loads((OUT/'captured-pages.json').read_text())
async def main():
 out=OUT/('OFFLINE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'));out.mkdir()
 spec=json.loads((ROOT/'evidence/native-gap-probe-20260930/run-spec.json').read_text());spec['duration']=30
 spec['capture_authorization']='OFFLINE retained gap replay only; no provider or credential access'
 dest=out/'session';approval=out/'OFFLINE-approval.json';ident=digest(implementation())
 approval.write_text(json.dumps(dict(approved=True,output=str(dest),implementation_sha256=ident,spec_sha256=digest(spec))))
 owner=CoverageOwner(out/'saved',pilot_output=dest,endpoints=ENDPOINTS,spec_factory=lambda:deepcopy(spec),product_mode=True,native_approval_path=approval)
 client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=out/'watches.json')));await client.start_server();origin={'Origin':str(client.make_url('/')).rstrip('/')}
 orig=socket.socket.connect;opened=Path.open
 def connect(sock,address):
  assert isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'),'No provider socket'
  return orig(sock,address)
 def safe_open(path,*a,**kw):
  assert path.name!='.env','No credential file'
  return opened(path,*a,**kw)
 try:
  with patch('socket.socket.connect',connect),patch.object(Path,'open',safe_open),patch('aiohttp.ClientSession',HTTP),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')),patch('app.collection.transport_session.PredictionProducer',side_effect=AssertionError('No subscriptions')),patch('app.collection.continuous.PredictionProducer',side_effect=AssertionError('No subscriptions')):
   res=await client.post('/api/start',json={'duration':30},headers=origin);assert res.status==200,await res.text()
   await owner.finalizer
   assert (await client.post('/api/stop',json={},headers=origin)).status==200
   session=owner.session;assert not owner.error,owner.error
   report=json.loads((session.output/'report.json').read_text());assert report['collection_seconds']>=29.8,report['reason']
   assert session.discovery.published_generation==1,session.discovery.refresh
   assert session.discovery.source_stops=={}
   assert session.discovery.markets['kalshi'] and session.cleanup_complete
   assert session.connection_attempts==0 and not session.aggregate
   rows=reopen(session.journal.path)['rows'];saved=load(session.output);assert saved==project_rows(rows,saved['durable_cursor'])
   decisions=[r for r in rows if r['type']=='native_acquisition_selection'];assert len(decisions)==2
   us=next(r for r in decisions if r['source']=='polymarket_us');assert set(us['selected'])=={'NCAAF','MLB','NHL'};assert us['sports']['NCAAB']['state']=='no_eligible_game_in_bounded_query'
   code='from pathlib import Path;import sys;from app.dashboard.session_history import load;from app.collection.native_approval import digest;print(digest(load(Path(sys.argv[1]))))'
   fresh=subprocess.check_output([sys.executable,'-c',code,str(session.output)],text=True).strip();assert fresh==digest(saved)
   feed=await(await client.get('/api/dashboard?view=feed&capture='+session.sid)).json();assert not feed.get('error')
   assert all(c.closed for c in HTTP.clients)
   result=dict(classification='OFFLINE 30-second repaired real-mode replay of unchanged complete gap-probe bytes. New slug metadata responses are not retained and raise explicit local gaps. No provider response or game substitution.',implementation_sha256=ident,collection_seconds=report['collection_seconds'],stop_reason=report['reason'],published_generation=1,selected={r['source']:r['selected'] for r in decisions},source_stops=session.discovery.source_stops,unretained_metadata=HTTP.gaps,intercepted_operations=len(HTTP.calls),external_requests=0,websockets=0,aggregate=0,credentials=0,cleanup=True,ordinary_start_stop=True,fresh_process_reopening=True,saved_dashboard=True,saved_sha256=fresh,resources=session.resources())
   (out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
 finally:await client.close()
if __name__=='__main__':asyncio.run(main())
