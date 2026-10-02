"""Exact sealed launcher/control, offline copied destination and intercepted access."""
import asyncio, importlib.util, json, shutil, socket, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
from hashlib import sha256
from unittest.mock import patch
from aiohttp.test_utils import TestServer
from app.collection.native_approval import digest, implementation
from app.collection.transport_session import reopen
from app.collection.native_book_report import summarize
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.session_history import load, project_rows
from tests.native_books_rehearsal import HTTP, Socket, Connector, COUNTS, Credential, ROOT, OUT
PACKAGE=ROOT/'evidence/native-books-20260930'
def module(name,folder):
 spec=importlib.util.spec_from_file_location(name,folder/(name+'.py'));m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
async def main():
 folder=OUT/('OFFLINE-EXACT-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'));folder.mkdir()
 ident=json.loads((PACKAGE/'identity.json').read_text())
 for name in [*ident['file_hashes'],'identity.json']:shutil.copyfile(PACKAGE/name,folder/name)
 a=json.loads((folder/'attempt.json').read_text());a['output']=str(folder/'session');(folder/'attempt.json').write_text(json.dumps(a))
 ident['output']=a['output'];ident['file_hashes']['attempt.json']=sha256((folder/'attempt.json').read_bytes()).hexdigest();(folder/'identity.json').write_text(json.dumps(ident))
 (folder/'approval.json').write_text(json.dumps(dict(approved=True,**ident,classification='OFFLINE interception only; not provider authority')))
 launch=module('launch',folder);control=module('control',folder);captured={};credential_calls=[]
 def owner(*args,**kw):captured['owner']=CoverageOwner(*args,**kw);return captured['owner']
 def run_app(app,**kw):assert kw==dict(host='127.0.0.1',port=8831);captured['app']=app
 original_connect=socket.socket.connect;opened=Path.open
 def connect(sock,address):
  assert isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'),'External sockets forbidden'
  return original_connect(sock,address)
 def safe_open(path,*args,**kw):assert path.name!='.env','Credential file forbidden';return opened(path,*args,**kw)
 def credentials(venues):credential_calls.extend(venues);return {v:Credential() for v in venues}
 HTTP.calls=[];HTTP.clients=[];Socket.instances=[];COUNTS.clear();server=None
 try:
  with patch('socket.socket.connect',connect),patch.object(Path,'open',safe_open),patch('aiohttp.ClientSession',HTTP),patch('app.collection.venue_access.load_credentials',credentials),patch('app.collection.prediction_producer.connect',Connector):
   with patch('aiohttp.web.run_app',run_app),patch('app.dashboard.coverage_owner.CoverageOwner',owner),patch.object(sys,'argv',['launch.py','--serve']):launch.main()
   server=TestServer(captured['app'],host='127.0.0.1',port=8831);await server.start_server()
   await asyncio.to_thread(control.run)
   o=captured['owner']
   if o.finalizer:await o.finalizer
   assert not o.error,o.error
   s=o.session;report=json.loads((s.output/'report.json').read_text())
   assert 89.5<=report['collection_seconds']<=91,report
   assert s.discovery.published_generation==1 and s.discovery.source_stops=={}
   assert s.cleanup_complete and s.connection_attempts==4 and not s.aggregate
   assert len(HTTP.calls)==3 and COUNTS==dict(kalshi=2,polymarket_us=2)
   assert all(c.closed for c in HTTP.clients+Socket.instances)
   rows=reopen(s.journal.path)['rows'];saved=load(s.output);assert saved==project_rows(rows,saved['durable_cursor'])
   evidence=summarize(rows);(folder/'book-evidence.json').write_text(json.dumps(evidence,indent=2))
   for v in ('kalshi','polymarket_us'):
    counts=evidence['sources'][v]['accepted'];assert counts['initial_snapshot']==counts['recovery_snapshot']==1
    assert counts['price_or_quantity_change'] and counts['repeated_identical_observation']
   assert any(r['type']=='prediction_book' and r['book']['receipt_freshness']=='stale' for r in rows)
   assert len([m for m in saved['market_catalog'] if m.get('book_evidence')])==2 and not saved['games']
   code='from pathlib import Path;import sys;from app.dashboard.session_history import load;from app.collection.native_approval import digest;print(digest(load(Path(sys.argv[1]))))'
   fresh=await asyncio.to_thread(subprocess.check_output,[sys.executable,'-c',code,str(s.output)],text=True);fresh=fresh.strip();assert fresh==digest(saved)
   def dashboard():
    from urllib.request import build_opener,ProxyHandler
    with build_opener(ProxyHandler({})).open('http://127.0.0.1:8831/api/dashboard?view=feed&capture='+s.sid,timeout=15) as r:return json.load(r)
   feed=await asyncio.to_thread(dashboard);assert not feed.get('error')
   assert len([m for m in feed['market_catalog'] if m.get('book_evidence')])==2
   for name in ('start-response.json','stop-response.json'):assert json.loads((folder/name).read_text())['status']==200
   assert not Path(json.loads((PACKAGE/'attempt.json').read_text())['output']).exists()
   for name in ('approval.json','activation.json','start-dispatch.json'):assert not (PACKAGE/name).exists()
   result=dict(classification='OFFLINE exact sealed launcher/control; unchanged retained listing bytes plus explicitly synthetic protocol fixtures. No live qualification.',implementation_sha256=digest(implementation()),spec_sha256=ident['spec_sha256'],offline_output=str(s.output),collection_seconds=report['collection_seconds'],stop_reason=report['reason'],intercepted_http=HTTP.calls,intercepted_connections=COUNTS,credential_boundary_interceptions=credential_calls,external_requests=0,credentials=0,odds_api=0,credits=0,ordinary_start_stop=True,exact_launcher=True,exact_control=True,cleanup=True,saved_dashboard=True,details=True,fresh_process_reopening=True,saved_sha256=fresh,resources=s.resources())
   (folder/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
 finally:
  if server:await server.close()
if __name__=='__main__':asyncio.run(main())
