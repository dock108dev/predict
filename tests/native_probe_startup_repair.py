"""OFFLINE real-mode branch test. All provider HTTP is intercepted in memory.

Existing captured NFL response bytes; synthetic empty responses for other scopes.
Mode=real exercises the exact credential/approval initialization branch only.
No source response here is fresh provider evidence or current availability.
"""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import urlsplit
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from app.collection.native_approval import implementation,digest
from app.collection.venue_access import ENDPOINTS
from app.collection.transport_session import reopen
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_history import load,project_rows
from tests.test_native_selectors import supported

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/native-probe-derived-20260930-v1'
CLASSIFICATION='OFFLINE REAL-MODE INITIALIZATION TEST: in-memory intercepted HTTP, retained NFL bodies; synthetic empty other scopes; no provider/credential access or live qualification'

class Response:
    status=200
    headers={}
    def __init__(self,raw):self.content=self;self.buffer=io.BytesIO(raw)
    async def read(self,size):return self.buffer.read(size)
    def at_eof(self):return self.buffer.tell()==len(self.buffer.getvalue())
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass

class InterceptedHTTP:
    calls=[];clients=[]
    def __init__(self,*args,**kwargs):self.connector=kwargs.get('connector');self.closed=False;self.clients.append(self)
    def get(self,url,*,params,**kw):
        path=urlsplit(url).path;q={k:str(v) for k,v in (params or {}).items()}
        assert urlsplit(url).hostname in ('external-api.kalshi.com','gateway.polymarket.us')
        assert kw['allow_redirects'] is False and kw['headers']=={'Accept-Encoding':'identity'}
        self.calls.append(dict(path=path,params=q,transport='IN_MEMORY_ONLY'))
        if path=='/v2/leagues':return Response(b'{"leagues":[]}')
        if path.endswith('/events'):
            nfl=q.get('series_ticker')=='KXNFLGAME' or q.get('tagSlug')=='nfl'
            if not nfl:return Response(b'{"events":[],"cursor":""}')
            row=next(r for r in supported() if r['path']==path and str(r['params'].get('offset',r['params'].get('cursor','')))==q.get('offset',q.get('cursor','')))
        elif path.endswith('/markets'):
            row=next(r for r in supported() if r['path']==path and all(str(r['params'].get(k))==v for k,v in q.items() if k in ('gameId','event_ticker')))
        else:raise AssertionError('Unexpected endpoint '+path)
        return Response(base64.b64decode(row['body_b64']))
    async def close(self):
        self.closed=True
        if self.connector:await self.connector.close()

async def main(duration=90):
    out=OUT/('OFFLINE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'));out.mkdir()
    (out/'CLASSIFICATION.txt').write_text(CLASSIFICATION)
    spec=json.loads((ROOT/'evidence/native-discovery-probe-20260930/run-spec.json').read_text());spec['duration']=duration
    spec['capture_authorization']=CLASSIFICATION
    ident=digest(implementation());destination=out/'session';approval=out/'OFFLINE-approval.json'
    approval.write_text(json.dumps(dict(approved=True,output=str(destination),implementation_sha256=ident,spec_sha256=digest(spec))))
    owner=CoverageOwner(out/'saved',pilot_output=destination,endpoints=ENDPOINTS,spec_factory=lambda:deepcopy(spec),product_mode=True,native_approval_path=approval)
    client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=out/'watches.json')));await client.start_server()
    origin={'Origin':str(client.make_url('/')).rstrip('/')}
    original_connect=socket.socket.connect;original_open=Path.open
    def connect(sock,address):
        assert isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'),'External socket prohibited'
        return original_connect(sock,address)
    def safe_open(path,*args,**kwargs):
        assert path.name!='.env','Credential file access prohibited'
        return original_open(path,*args,**kwargs)
    InterceptedHTTP.calls=[];InterceptedHTTP.clients=[]
    try:
        with patch('socket.socket.connect',connect),patch.object(Path,'open',safe_open),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('Credentials prohibited')),patch('aiohttp.ClientSession',InterceptedHTTP),patch('app.collection.transport_session.PredictionProducer',side_effect=AssertionError('No stream constructor in probe')),patch('app.collection.continuous.PredictionProducer',side_effect=AssertionError('No stream constructor in reconcile')):
            res=await client.post('/api/start',json={'duration':duration},headers=origin);assert res.status==200,await res.text()
            await owner.finalizer
            res=await client.post('/api/stop',json={},headers=origin);assert res.status==200
            assert owner.error is None,owner.error
            session=owner.session;rows=reopen(session.journal.path)['rows'];saved=load(session.output)
            assert saved==project_rows(rows,saved['durable_cursor'])
            assert not session.aggregate and session.connection_attempts==0 and session.cleanup_complete
            assert not session.discovery.source_stops and session.discovery.published_generation==1
            assert all(c.closed for c in InterceptedHTTP.clients)
            assert all(not p.groups and p.applied_generation==1 for v,p in session.producers.items() if v in ('kalshi','polymarket_us'))
            assert not any(r['type'].startswith('aggregate_') or r['type'] in ('prediction_command','prediction_frame','prediction_book','market_selected') for r in rows)
            decisions=[r for r in rows if r['type']=='native_acquisition_selection'];assert len(decisions)==2 and all(r['selected'].get('NFL') for r in decisions)
            code='from pathlib import Path; import sys; from app.dashboard.session_history import load; from app.collection.native_approval import digest; print(digest(load(Path(sys.argv[1]))))'
            fresh=subprocess.check_output([sys.executable,'-c',code,str(session.output)],text=True).strip();assert fresh==digest(saved)
            feed=await (await client.get('/api/dashboard?view=feed&capture='+session.sid)).json();assert not feed.get('error')
            report=json.loads((session.output/'report.json').read_text());assert report['collection_seconds']>=duration-.2
            assert ident==digest(implementation())
            result=dict(classification=CLASSIFICATION,implementation_sha256=ident,duration=duration,collection_seconds=report['collection_seconds'],ordinary_start_stop=True,real_mode_initialization=True,intercepted_requests=len(InterceptedHTTP.calls),queries=InterceptedHTTP.calls,selected={r['source']:r['selected'] for r in decisions},native_generations=1,websocket_attempts=0,aggregate_requests=0,actual_provider_requests=0,credential_access=0,actual_credits=0,cleanup=True,exact_reopening=True,fresh_process_reopening=True,saved_dashboard_route=True,saved_snapshot_sha256=digest(saved),resources=session.resources())
            (out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(path=str(out),**{k:v for k,v in result.items() if k!='queries'})),flush=True)
    finally:await client.close()

if __name__=='__main__':asyncio.run(main(int(sys.argv[1]) if len(sys.argv)>1 else 90))
