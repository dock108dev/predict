"""Exact sealed launcher and control client, offline copy only; no provider sockets.

Retained Kalshi bytes are unchanged. US successes/missing metadata/duplicate IDs
are labeled synthetic controls; original truncated CFB bytes test rejection only.
The actual unapproved package, unused destination and attempt remain untouched.
"""
import asyncio,importlib.util,json,shutil,socket,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
from hashlib import sha256
from unittest.mock import patch
from aiohttp.test_utils import TestServer
from app.collection.native_approval import digest,implementation
from app.collection.transport_session import reopen
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.session_history import load,project_rows
from tests.native_gap_fixture import HTTP,ROOT
PACKAGE=ROOT/'evidence/native-gap-probe-20260930'
OUT=ROOT/'evidence/native-gap-preparation-20260930'

def module(name,folder):
 spec=importlib.util.spec_from_file_location(name,folder/(name+'.py'));m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

async def main():
 folder=OUT/('OFFLINE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'));folder.mkdir()
 for name in ('launch.py','control.py','run-spec.json','attempt.json','identity.json'):shutil.copyfile(PACKAGE/name,folder/name)
 # Only destination differs. Attempt UUID/spec/app/exact launcher and client stay identical.
 a=json.loads((folder/'attempt.json').read_text());a['output']=str(folder/'session');(folder/'attempt.json').write_text(json.dumps(a))
 i=json.loads((folder/'identity.json').read_text());i['output']=a['output'];i['file_hashes']['attempt.json']=sha256((folder/'attempt.json').read_bytes()).hexdigest();(folder/'identity.json').write_text(json.dumps(i))
 (folder/'approval.json').write_text(json.dumps(dict(approved=True,**i,classification='OFFLINE control verification only; external transport intercepted')))
 launch=module('launch',folder);control=module('control',folder);captured={}
 def owner(*args,**kw):captured['owner']=CoverageOwner(*args,**kw);return captured['owner']
 def run_app(app,**kw):assert kw==dict(host='127.0.0.1',port=8831);captured['app']=app
 original_connect=socket.socket.connect;opened=Path.open
 def connect(sock,address):
  assert isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'),'External sockets forbidden'
  return original_connect(sock,address)
 def safe_open(path,*args,**kw):assert path.name!='.env','Credential file forbidden';return opened(path,*args,**kw)
 HTTP.reset('oversized_source_stop',retry=True)
 server=None
 try:
  with patch('socket.socket.connect',connect),patch.object(Path,'open',safe_open),patch('aiohttp.ClientSession',HTTP),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('Credentials forbidden')),patch('app.collection.transport_session.PredictionProducer',side_effect=AssertionError('Subscriptions forbidden')),patch('app.collection.continuous.PredictionProducer',side_effect=AssertionError('Subscriptions forbidden')):
   with patch('aiohttp.web.run_app',run_app),patch('app.dashboard.coverage_owner.CoverageOwner',owner),patch.object(sys,'argv',['launch.py','--serve']):launch.main()
   server=TestServer(captured['app'],host='127.0.0.1',port=8831);await server.start_server()
   await asyncio.to_thread(control.run)
   o=captured['owner']
   if o.finalizer:await o.finalizer
   assert not o.error,o.error
   session=o.session;report=json.loads((session.output/'report.json').read_text())
   assert report['collection_seconds']>=89.6,report
   assert session.discovery.published_generation==1,session.discovery.refresh
   assert session.discovery.source_stops=={'polymarket_us':'invalid_gap_traversal'},session.discovery.source_stops
   assert session.discovery.markets['kalshi'] is not None
   assert session.cleanup_complete and session.connection_attempts==0 and not session.aggregate
   rows=reopen(session.journal.path)['rows'];saved=load(session.output);assert saved==project_rows(rows,saved['durable_cursor'])
   decisions=[r for r in rows if r['type']=='native_acquisition_selection'];assert len(decisions)==2
   us=next(r for r in decisions if r['source']=='polymarket_us')
   assert us['sports']['NCAAF']['response_envelope_exceeded'] and us['sports']['NCAAB']['metadata']=='complete_bounded_page'
   ops=[r for r in rows if r['type']=='native_gap_operation' and r['source']=='polymarket_us']
   assert [r['sport'] for r in ops[:5]]==['NCAAF','NBA','MLB','NHL','NCAAB']
   assert all(r['phase']=='first_opportunities' for r in ops[:5])
   assert all(c.closed for c in HTTP.clients)
   code='from pathlib import Path;import sys;from app.dashboard.session_history import load;from app.collection.native_approval import digest;print(digest(load(Path(sys.argv[1]))))'
   fresh=await asyncio.to_thread(subprocess.check_output,[sys.executable,'-c',code,str(session.output)],text=True);fresh=fresh.strip();assert fresh==digest(saved)
   def dashboard():
    from urllib.request import build_opener,ProxyHandler
    with build_opener(ProxyHandler({})).open('http://127.0.0.1:8831/api/dashboard?view=feed&capture='+session.sid,timeout=15) as r:return json.load(r)
   feed=await asyncio.to_thread(dashboard);assert not feed.get('error')
   for name in ('start-response.json','stop-response.json'):assert json.loads((folder/name).read_text())['status']==200
   assert not Path(json.loads((PACKAGE/'attempt.json').read_text())['output']).exists()
   for n in ('approval.json','activation.json','start-dispatch.json'):assert not (PACKAGE/n).exists()
   result=dict(classification='OFFLINE exact launcher/control 90-second real-mode run; mixed retained Kalshi bytes and labeled US transport controls. No fresh source qualification.',implementation_sha256=digest(implementation()),spec_sha256=i['spec_sha256'],offline_output=str(session.output),collection_seconds=report['collection_seconds'],stop_reason=report['reason'],published_generation=session.discovery.published_generation,selected={r['source']:r['selected'] for r in decisions},source_stops=session.discovery.source_stops,intercepted_operations=len(HTTP.calls),operations=HTTP.calls,external_requests=0,websockets=0,aggregate=0,credits=0,credentials=0,ordinary_start_stop=True,exact_launcher=True,exact_control=True,fresh_process_reopening=True,saved_dashboard=True,cleanup=True,saved_sha256=fresh,resources=session.resources(),source_budgets={v:p.budget.summary() if hasattr(p.budget,'summary') else vars(p.budget) for v,p in session.producers.items()})
   (folder/'verification.json').write_text(json.dumps(result,indent=2,default=str));print(json.dumps(result,default=str),flush=True)
 finally:
  if server:await server.close()
if __name__=='__main__':asyncio.run(main())
