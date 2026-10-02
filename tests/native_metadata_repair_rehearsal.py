"""Exact launcher offline; retained metadata in labeled reconstructed HTTP envelopes,
synthetic WS books. Deny external sockets and real credential resolution."""
import asyncio,base64,io,json,sys,socket,subprocess,shutil,importlib.util
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from app.collection.native_approval import digest,implementation
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_history import load,verified
from app.dashboard.price_comparison import comparisons
from app.dashboard.session_projection import stable
from tests.native_books_rehearsal import Credential,Response
ROOT=Path(__file__).resolve().parents[1];PACKAGE=ROOT/'evidence/native-nyi-tor-20260930-v1'
OUT=ROOT/'evidence/native-metadata-repair-20260930-v1'
SPEC=json.loads((PACKAGE/'run-spec.json').read_text());RECORDS=SPEC['native_review_records']
from app.collection.native_review_contract import contract
SPEC['native_discovery']['slice']='native-reviewed-target-v2'
for r in RECORDS:
 for v,b in r['sources'].items():b['semantic_review_contract']=contract(v,b['catalog_evidence']['event']['native_metadata'],b['metadata'])
 r.pop('sha256');r['sha256']=stable(r)
class HTTP:
 calls=[];clients=[];scenario='normal'
 def __init__(self,*a,**kw):self.closed=False;self.connector=kw.get('connector');self.clients.append(self)
 def get(self,url,*,params,**kw):
  from urllib.parse import urlsplit
  v='kalshi' if urlsplit(url).hostname=='external-api.kalshi.com' else 'polymarket_us'
  expected=next(x for x in json.loads((PACKAGE/'request-plan.json').read_text())['operations'] if x['source']==v)
  if v=='polymarket_us':expected.update(path='/v1/events/127804',params={})
  assert urlsplit(url).path==expected['path'] and params==expected['params'],(url,params)
  self.calls.append(v);assert self.calls.count(v)==1
  r=RECORDS[0]['sources'][v];e=deepcopy(r['catalog_evidence']['event']['native_metadata'])
  data=dict(events=[e])
  if v=='kalshi':
   data['cursor']='';e['markets']=[deepcopy(t['sources'][v]['metadata']) for t in RECORDS]
   # Untouched real milestone evidence, retained from its original journal receipt.
   proof=r['catalog_evidence']['event']['provenance'][0]
   folder=ROOT/r['provenance'][-1]['session_folder']
   rows=verified(folder)['rows'];page=next(x for x in rows if x.get('body_sha256')==proof['body_sha256'])
   data['milestones']=json.loads(base64.b64decode(page['body_b64'])).get('milestones',[])
  if v=='kalshi' and self.scenario in ('normal','complete_boundary','both_terminal'):
   original=ROOT/'evidence/native-nyi-tor-attempt-5c26ecaf-d41b-4589-a590-d2423e2aa62d/5da7cfc8-926c-4591-a6e9-e3354942d45b'
   page=next(x for x in verified(original)['rows'] if x['type']=='prediction_discovery_http' and x['source']=='kalshi')
   data=json.loads(base64.b64decode(page['body_b64']));e=data['events'][0]
  if self.scenario=='both_terminal' and v=='kalshi':e['title']='CONSTRUCTED material identity change'
  if self.scenario=='missing_target' and v=='polymarket_us':data['events']=[]
  if self.scenario=='missing_market' and v=='polymarket_us':e['markets']=[]
  if self.scenario=='unsupported' and v=='polymarket_us':e['teams']=[]
  if self.scenario=='unavailable' and v=='kalshi':data['events']=[]
  if self.scenario=='changed' and v=='kalshi':e['title']='OFFLINE changed identity control'
  if self.scenario=='closed' and v=='kalshi':
   for m in e['markets']:m['status']='closed'
  status=503 if self.scenario=='source_failure' and v=='polymarket_us' else 200
  if v=='polymarket_us':data={'event':data['events'][0] if data['events'] else {'id':'CONSTRUCTED-absent'}}
  if v=='polymarket_us' and self.scenario=='complete_boundary':
   data['constructed_envelope_padding']=''
   size=len(json.dumps(data).encode());data['constructed_envelope_padding']='x'*(524288-size)
  raw=json.dumps(data).encode()
  if v=='polymarket_us':
   if self.scenario in ('oversized','both_terminal'):raw=b'{"padding":"'+b'x'*524288+b'"}'
   if self.scenario=='incomplete':raw=b'{"events":['
   if self.scenario=='malformed':raw=b'{"events":INVALID}'
  return Response(dict(status=status,body_b64=base64.b64encode(raw).decode()))
 async def close(self):
  self.closed=True
  if self.connector:await self.connector.close()
class WS:
 clients=[];subscriptions=[]
 def __init__(self,v):self.v=v;self.sent=[];self.i=0;self.closed=False;self.clients.append(self)
 async def send(self,body):
  b=json.loads(body);self.sent.append(b);self.subscriptions.append((self.v,b))
  if self.v=='kalshi':assert b['params']['market_tickers']==['KXNHLGAME-26SEP30NYITOR-NYI','KXNHLGAME-26SEP30NYITOR-TOR']
  else:assert b['subscribe']['marketSlugs']==[RECORDS[0]['sources'][self.v]['metadata']['slug']]
 async def recv(self):
  await asyncio.sleep(.03);i=self.i;self.i+=1
  if HTTP.scenario=='stream_terminal':raise ConnectionError('CONSTRUCTED terminal stream failure')
  if self.v=='kalshi':
   if i==0:return json.dumps(dict(id=self.sent[0]['id'],type='subscribed',msg=dict(channel='orderbook_delta',sid=1)))
   if i in (1,2):return json.dumps(dict(type='orderbook_snapshot',sid=1,seq=i,msg=dict(market_ticker=self.sent[0]['params']['market_tickers'][i-1],market_id='OFFLINE-'+str(i),yes_dollars_fp=[['0.4000','10.00']],no_dollars_fp=[['0.5000','20.00']])))
   if i in (3,4,5):return json.dumps(dict(type='orderbook_delta',sid=1,seq=i,msg=dict(market_ticker=self.sent[0]['params']['market_tickers'][0],market_id='OFFLINE-1',side='yes',price_dollars='0.4200' if i==5 else '0.4000',delta_fp='0.00' if i==3 else '2.00')))
  elif i<4:
   return json.dumps(dict(requestId=self.sent[0]['subscribe']['requestId'],subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',marketData=dict(marketSlug=self.sent[0]['subscribe']['marketSlugs'][0],bids=[dict(px=dict(value='0.4' if i<3 else '0.42',currency='USD'),qty='10.00' if i<2 else '12.00')],offers=[dict(px=dict(value='0.55',currency='USD'),qty='20.00')],transactTime=datetime.now(timezone.utc).isoformat())))
  await asyncio.sleep(120)
 async def close(self):self.closed=True
async def connector(url,**kw):
 assert kw['additional_headers']=={'OFFLINE-Protocol-Fixture':'not-a-credential'}
 return WS('kalshi' if 'kalshi' in url else 'polymarket_us')
class Connector:
 def __init__(self,url,**kw):self.url=url;self.kw=kw
 def __await__(self):return connector(self.url,**self.kw).__await__()
def module(folder):
 name='nyi_launcher';sp=importlib.util.spec_from_file_location(name,folder/'launch.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m
async def run(scenario='normal'):
 from tempfile import TemporaryDirectory
 HTTP.calls=[];HTTP.clients=[];HTTP.scenario=scenario;WS.clients=[];WS.subscriptions=[]
 out=OUT/'launcher-controls'/ (scenario+'-'+datetime.now(timezone.utc).strftime('%H%M%S%f'));out.mkdir(parents=True)
 folder=out/'package';folder.mkdir()
 ident=json.loads((PACKAGE/'identity.json').read_text())
 for n in [*ident['file_hashes'],'identity.json']:shutil.copyfile(PACKAGE/n,folder/n)
 (folder/'run-spec.json').write_text(json.dumps(SPEC))
 ident['implementation_sha256']=digest(implementation());ident['spec_sha256']=digest(SPEC)
 ident['file_hashes']['run-spec.json']=sha256((folder/'run-spec.json').read_bytes()).hexdigest()
 a=json.loads((folder/'attempt.json').read_text());a['output']=str(out/'session');(folder/'attempt.json').write_text(json.dumps(a));ident['output']=a['output'];ident['file_hashes']['attempt.json']=sha256((folder/'attempt.json').read_bytes()).hexdigest();(folder/'identity.json').write_text(json.dumps(ident));(folder/'approval.json').write_text(json.dumps(dict(approved=True,**ident,classification='OFFLINE CONTROL ONLY')))
 captured={}
 def owner(*a,**kw):captured['owner']=CoverageOwner(*a,**kw);return captured['owner']
 def run_app(app,**kw):captured['app']=app
 orig=socket.socket.connect
 def local(sock,address):
  assert address[0] in ('127.0.0.1','::1'),'external network denied'
  return orig(sock,address)
 def creds(venues):return {v:Credential() for v in venues}
 with patch('socket.socket.connect',local),patch('aiohttp.ClientSession',HTTP),patch('app.collection.venue_access.load_credentials',creds),patch('app.collection.prediction_producer.connect',Connector):
  with patch('app.dashboard.coverage_owner.CoverageOwner',owner),patch('aiohttp.web.run_app',run_app),patch.object(sys,'argv',['launch.py','--serve']):module(folder).main()
  from app.dashboard.opportunity_history import WatchStore
  WatchStore(out/'session'/'watches.json').save([dict(name='NHL raw prices',metric='raw_gap',threshold='0',quantity='1',filters={'competition':'NHL'})])
  async with TestClient(TestServer(captured['app'])) as client:
   origin={'Origin':str(client.make_url('')).rstrip('/')}
   response=await client.post('/api/start',headers=origin,json={'duration':90});assert response.status==200,await response.text()
   o=captured['owner']
   o.session.emit('session',dict(type='offline_control_classification',classification='SYNTHETIC OFFLINE ONLY: reconstructed HTTP envelopes with unchanged retained metadata; synthetic WS books; fake credentials; no provider authority'))
   import time
   started=time.monotonic()
   for _ in range(30):
    await asyncio.sleep(.5)
    live=await(await client.get('/api/dashboard?view=feed')).json()
    if scenario in ('both_terminal','stream_terminal') and o.session.cleanup_complete:break
    if (scenario in ('normal','complete_boundary') and len(live['comparisons'])==2) or (scenario not in ('normal','complete_boundary','both_terminal','stream_terminal') and WS.subscriptions):break
   assert not o.error,o.error
   if scenario in ('normal','complete_boundary'):
    assert len(live['comparisons'])==2,dict(subscriptions=WS.subscriptions,selection=o.session.discovery.book_market_ids,errors=live.get('native_comparison_review',{}).get('errors'))
    from app.dashboard.opportunity_history import WatchStore
    WatchStore(out/'session'/'watches.json').save([dict(name='NHL raw prices',metric='raw_gap',threshold='0',quantity='1',filters={'competition':'NHL'})])
    uslegs=[l for r in live['comparisons'] for l in r['legs'] if l['venue']=='polymarket_us']
    assert {l['native_identity']['market_id'] for l in uslegs}=={'1061481'}
    assert len(HTTP.calls)==2 and len(WS.subscriptions)==2
    assert live['coverage']['sources']
    assert all(r['net'] is None for r in live['comparisons'])
    variants={r['game_id']:r for p in live['comparisons'] for r in [p,*p['alternatives']]}
    for r in variants.values():
     q={k:r[k] for k in ('session','hash','cutoff')}
     detail=await client.get('/api/calculate',params=q);assert detail.status==200;d=await detail.json();assert len(d['comparisons'])==2
     assert await(await client.get('/api/calculate',params=dict(q,download='true'))).json()==d
     sizes=await client.post('/api/decision-sizes',headers=origin,json=dict(q,sizes=['1','100']));assert sizes.status==200 and (await sizes.json())['best'] is None
    watch_response=await client.get('/api/watchlists');assert watch_response.status==200 and len((await watch_response.json())['watchlists'])==1
    export=await client.get('/api/native-reviews',params=dict(capture=o.session.sid,cutoff=live['durable_cursor'],download='true'));assert export.status==200
    (out/'paired-live-control.json').write_text(json.dumps(live))
    for _ in range(30):
     if all(c.i>=(6 if c.v=='kalshi' else 5) for c in WS.clients):break
     await asyncio.sleep(.2)
    await asyncio.sleep(12)
   else:
    if scenario in ('both_terminal','stream_terminal'):live=await(await client.get('/api/dashboard',params=dict(view='feed',capture=o.session.sid))).json()
    assert not live['comparisons'],(scenario,live['comparisons'])
    assert o.session.discovery.source_stops
    if scenario!='stream_terminal':assert all(o.session.discovery.inventory[v].get('source_error')==reason for v,reason in o.session.discovery.source_stops.items())
   if scenario in ('both_terminal','stream_terminal'):
    assert o.session.cleanup_complete and time.monotonic()-started<8
    assert o.session.reason=='all_selected_sources_terminal_no_permitted_work'
   else:
    assert not o.session.stop_event.is_set(),'healthy source stopped early'
    assert (await client.post('/api/stop',headers=origin,json={})).status==200
   if o.finalizer:await o.finalizer
   assert not o.error,o.error
   s=o.session;v=load(s.output);rows=list(verified(s.output)['rows']);assert s.cleanup_complete
   signals=await client.get('/api/signals');assert signals.status==200
   history=await client.get('/api/opportunity-history',params=dict(capture=s.sid,download='true'));assert history.status==200
   h=await history.json();(out/'history-control.json').write_text(json.dumps(h))
   if scenario in ('normal','complete_boundary'):assert h['items']
   from app.collection.native_book_report import summarize
   (out/'observation-control.json').write_text(json.dumps(summarize(rows),indent=2))
   assert all(c.closed for c in HTTP.clients+WS.clients)
   assert len(WS.subscriptions)==(2 if scenario in ('normal','complete_boundary') else 0 if scenario=='both_terminal' else 4 if scenario=='stream_terminal' else 1),WS.subscriptions
   if scenario in ('normal','complete_boundary'):assert any(x['type']=='prediction_book' and x['book']['receipt_freshness']=='stale' for x in rows)
   code='import sys;from pathlib import Path;from app.dashboard.session_history import load;from app.collection.native_approval import digest;print(digest(load(Path(sys.argv[1]))))'
   fresh=subprocess.check_output([sys.executable,'-c',code,str(s.output)],text=True).strip();assert fresh==digest(v)
   result=dict(scenario=scenario,external_requests=0,credentials_accessed=0,retained_metadata='unchanged exact source objects in labeled reconstructed HTTP envelopes',book_controls='synthetic protocol only',exact_launcher=True,ordinary_start_stop=scenario not in ('both_terminal','stream_terminal'),terminal_reason=s.reason,collection_seconds=s.collection_seconds,resources=s.resources(),source_stops=s.discovery.source_stops,cleanup=True,fresh_process_reopening=True,output=str(s.output),saved_sha256=fresh,subscriptions=len(WS.subscriptions),http_controls=HTTP.calls,live_comparisons=len(live['comparisons']))
   (out/'verification.json').write_text(json.dumps(result,indent=2));return result
async def main():
 results=[]
 for s in ['normal','complete_boundary','changed','oversized','incomplete','malformed','missing_target','missing_market','unsupported','both_terminal','stream_terminal']:
  results.append(await run(s));print(s+' PASS',flush=True)
 (OUT/'launcher-verification.json').write_text(json.dumps(results,indent=2))
if __name__=='__main__':asyncio.run(main())
