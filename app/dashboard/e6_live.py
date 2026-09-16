"""Bounded file-journal live owner. No database; idle until explicit local Start."""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
from aiohttp import web
from app.collection.transport_session import TransportSession,reopen
from app.collection.native_replay import verify_native
from app.collection.venue_access import ENDPOINTS
from app.dashboard import e6_real as historical

ROOT=historical.ROOT
OUTPUT=ROOT/'evidence/e6/live-watch/sessions'

def configuration():
    s=json.loads((ROOT/(historical.RUN+'run-spec.json')).read_text())
    now=datetime.now(timezone.utc)
    s.update(start_after=(now-timedelta(seconds=1)).isoformat(),start_before=(now+timedelta(minutes=10)).isoformat(),duration=180,
             capture_authorization='owner live-loop prompt: one supervised run <=300 seconds, zero additional spending',
             mapping_revision='prior Detroit-Buffalo identity; current bounded discovery required before subscription')
    return s

def digest(path):return sha256(path.read_bytes()).hexdigest()

def save_json(path,value):
    body=json.dumps(value,indent=2).encode()
    with path.open('xb',buffering=0) as f:
        if f.write(body)!=len(body):raise OSError('short JSON write')
        f.flush()
        import os
        os.fsync(f.fileno())

def validate_saved(folder, expected=None):
    manifest=json.loads((folder/'manifest.json').read_text())
    if expected is not None and manifest['journal_chain']!=expected:raise ValueError('saved identity mismatch')
    if set(manifest['files'])!={'run-spec.json','observations.jsonl','saved-observations.json','replay.json'}:raise ValueError('incomplete manifest')
    for name,h in manifest['files'].items():
        if name not in ('run-spec.json','observations.jsonl','saved-observations.json','replay.json'):raise ValueError('invalid saved filename')
        if digest(folder/name)!=h:raise ValueError('saved evidence altered')
    saved=reopen(folder/'observations.jsonl');rows=saved['rows']
    spec=json.loads((folder/'run-spec.json').read_text())
    if saved['sha256']!=manifest['journal_chain'] or saved['state']!='complete':raise ValueError('saved chain incomplete')
    if rows[0]['spec']!=spec or rows[0]['session_id']!=folder.name or any(r['session_id']!=folder.name for r in rows):raise ValueError('saved configuration mismatch')
    if saved!=json.loads((folder/'saved-observations.json').read_text()):raise ValueError('saved export mismatch')
    replay=verify_all(folder/'observations.jsonl')
    if replay!=json.loads((folder/'replay.json').read_text()):raise ValueError('native replay mismatch')
    historical.validate_mapping(rows,spec)
    return package(rows,spec,saved['sha256'],live=False,replay=replay)

def verify_all(path):
    """Native frames verify synchronized images; derived health books retain that image."""
    return verify_all_saved(reopen(path))

def verify_all_saved(saved):
    from app.collection.native_replay import verify_native_saved
    result=verify_native_saved(saved);rows=saved['rows'];previous={};derived=0;packets=0
    for r in rows:
        if r['type']!='prediction_book':continue
        b=r['book'];v=(r['source'],b['raw']['ref']['event_id'],b['raw']['ref']['market_id']);packets+=len(r['packets'])
        if b['sync']=='synchronized' and b['receipt_freshness']=='recent':previous[v]=r;continue
        old=deepcopy(previous[v]);expected=deepcopy(old['book'])
        if b['sync'] not in ('synchronized','unsynchronized') or b['receipt_freshness'] not in ('recent','stale'):raise ValueError('unsupported health derivation')
        expected['sync']=b['sync'];expected['receipt_freshness']=b['receipt_freshness']
        if expected!=b:raise ValueError('derived health book changed native image')
        # Converter retains quotes and raw bytes, changing recorded sync/freshness only.
        expected_packets=deepcopy(old['packets'])
        for p in expected_packets:
            p['normalized']['sync']=b['sync']
        if expected_packets!=r['packets']:raise ValueError('derived quote changed')
        derived+=1
    return dict(**result,derived_health_books=derived,total_books=sum(r['type']=='prediction_book' for r in rows),total_packets=packets)

def package(rows,spec,chain,*,live,replay=None,now=None):
    timeline=historical.project(rows,spec)
    sid=rows[0]['session_id']
    for p in timeline:
        if p['type']=='session_finished':p['id']=sid+':finished'
    if live:
        point=deepcopy(timeline[-1]);point['at']=now or datetime.now(timezone.utc).isoformat();point['id']='current'
        for c in point['cards']:
            b=c['book']
            if b:
                c['age_seconds']=historical.fixed(historical.exact_time(point['at'])-historical.exact_time(b['received_at']))
                c['receipt_stale']=Decimal(c['age_seconds'])>Decimal(str(spec['stale_seconds']))
            c['last_receipt']=None if not b else b['received_at']
            c['unavailable_reason']=None
            if c['connection']!='connected' or not b or b['sync']!='synchronized' or c['receipt_stale']:
                c['unavailable_reason']='Current book unavailable: '+('receipt stale on a quiet feed' if c['receipt_stale'] and c['connection']=='connected' else c['connection'])
                c['book']=None
        timeline=[point]
    counts=dict(frames=sum(r['type']=='prediction_frame' for r in rows),books=sum(r['type']=='prediction_book' for r in rows),packets=sum(len(r['packets']) for r in rows if r['type']=='prediction_book'),ingress=sum('ingress_id' in r for r in rows))
    validations={v:sum(r['type']=='discovery_validated' and r.get('source')==v for r in rows) for v in historical.VENUES}
    transitions=[dict(at=r['observed_at'],source=r['source'],state=r.get('state'),type=r['type']) for r in rows if r['type'] in ('source_health','controlled_interruption')]
    return dict(session=sid,hash=chain,live=live,event='Detroit Lions at Buffalo Bills',kickoff=spec['scheduled_start'],capture_start=rows[0]['observed_at'],capture_end=rows[-1]['observed_at'],timeline=timeline,counts=counts,replay=replay,transitions=transitions,
        coverage=dict(limitation='Validated metadata refreshes: '+str(validations)+'. A stop may interrupt a refresh between requests; only validated revisions count.',completeness='Bounded retained observations, not complete upstream history. Controlled client interruption is not natural-outage reliability.'),
        economics=dict(arb='Unavailable — fee, account rounding and settlement inputs are unqualified.',our_price='Unavailable — no supporting reference/model inputs.',mispricing='Unavailable — no qualified fair-price inputs. References are disabled.'))

class Owner:
    def __init__(self,output=OUTPUT,*,spec_factory=configuration,endpoints=ENDPOINTS):
        self.output=Path(output);self.output.mkdir(parents=True,exist_ok=True)
        self.spec_factory=spec_factory;self.endpoints=endpoints;self.session=None;self.finalizer=None;self.error=None;self.lock=asyncio.Lock();self.interrupted=False
    def saved(self):
        return sorted({p.parent.name for pattern in ('*/manifest.json','*/recovery.json') for p in self.output.glob(pattern)})[:8]
    def active(self):return self.session is not None and self.finalizer is not None and not self.finalizer.done()
    async def start(self):
        async with self.lock:
            if self.session is not None:raise ValueError('this owner already attempted a session; no automatic retry')
            # This environment grants exactly one real attempt, across browser and process restarts.
            if (self.output/'attempt.json').exists():raise ValueError('one authorized real run already used; no additional run in this slice')
            s=self.spec_factory();s['reference_enabled']=False
            self.session=TransportSession(s,self.output/'pending',self.endpoints)
            folder=self.output/self.session.sid;self.session.output=folder
            try:
                folder.mkdir()
                save_json(self.output/'attempt.json',dict(session=self.session.sid,at=datetime.now(timezone.utc).isoformat()))
                save_json(folder/'run-spec.json',s)
                await self.session.start()
            except Exception as exc:
                if isinstance(exc,OSError):
                    self.session.storage_failed(getattr(exc,'stage','startup_files'))
                    self.session.state='failed';self.session.report_failure()
                self.error='Start failed: existing credentials, configuration or local storage unavailable. No automatic retry.'
                raise ValueError(self.error) from None
            self.finalizer=asyncio.create_task(self.finish(folder))
            return self.session.sid
    async def finish(self,folder):
        stage='collection'
        try:
            await self.session.task
            if self.session.persistence_error:
                self.error=self.session.persistence_error
                return
            stage='journal_rename'
            path=self.session.journal.path;path.rename(folder/'observations.jsonl');self.session.journal.path=folder/'observations.jsonl'
            stage='export'
            saved=reopen(self.session.journal.path);save_json(folder/'saved-observations.json',saved)
            stage='replay'
            replay=verify_all(self.session.journal.path);save_json(folder/'replay.json',replay)
            stage='manifest'
            save_json(folder/'manifest.pending.json',dict(session=self.session.sid,journal_chain=saved['sha256'],files={n:digest(folder/n) for n in ('run-spec.json','observations.jsonl','saved-observations.json','replay.json')}))
            # A failed manifest write/flush/fsync must not enter the completed catalog.
            (folder/'manifest.pending.json').rename(folder/'manifest.json')
        except Exception as exc:
            self.session.storage_failed(stage)
            self.session.state='failed';self.session.report_failure()
            self.error='Saved finalization failed at '+stage+'; retained files are not replaced.' 
    async def stop(self):
        if self.active():
            self.session.state='stopping';self.session.request_stop('manual_stop')
    async def interrupt(self):
        if not self.active() or self.session.state!='running' or self.interrupted:raise ValueError('controlled interruption unavailable')
        p=self.session.producers['kalshi']
        if self.session.health['kalshi']!='connected':raise ValueError('wait for a synchronized Kalshi image')
        self.interrupted=True
        await p.interrupt_connection()
    def status(self):
        s=self.session;active=self.active()
        result=dict(state=('stopping' if s and s.state=='stopped' and active else s.state) if s else 'idle',active=active,error=self.error,
                    saved=self.saved(),saved_status={s:('Interrupted' if (self.output/s/'recovery.json').exists() else 'Completed') for s in self.saved()},start_available=self.session is None and not (self.output/'attempt.json').exists(),interrupted=self.interrupted,view=None)
        if s:
            result.update(session=s.sid,delivered=s.delivered,persisted=s.persisted,
                          storage_accounting=s.accounting(),cleanup_complete=s.cleanup_complete,
                          failure_report=s.failure_report,usable=active and not s.persistence_error,
                          terminal_acknowledged=bool(s.journal and s.journal.terminal_acknowledged))
            result['error']=self.error or s.persistence_error
        if active and s.journal and not s.persistence_error:
            saved=reopen(s.journal.path);result['view']=package(saved['rows'],s.spec,saved['sha256'],live=True)
            result.update(session=s.sid,delivered=s.delivered,persisted=s.persisted)
        if not active and (self.output/'attempt.json').exists() and not self.saved() and not result['error']:
            result['error']='An interrupted or incomplete attempt is retained. Startup does not resume collection.'
        return result
    async def close(self):
        await self.stop()
        if self.finalizer:await self.finalizer

def create_app(output=OUTPUT,owner=None,*,saved_loader=None,assets=None,card_source=None):
    owner=owner or Owner(output)
    if assets is None and any(owner.output.glob('*/recovery.json')):
        from app.dashboard.e6_recovery import card_source as recovery_cards
        assets=ROOT/'app/dashboard/e6_recovery_static';card_source=card_source or recovery_cards()
    requests_in_progress=0
    @web.middleware
    async def guard(request,handler):
        if request.host not in ('127.0.0.1:'+str(request.url.port),'localhost:'+str(request.url.port)):raise web.HTTPForbidden()
        if request.method=='POST' and request.headers.get('Origin')!='http://'+request.host:raise web.HTTPForbidden()
        if request.method=='POST' and request.headers.get('Content-Type')!='application/json':raise web.HTTPForbidden()
        nonlocal requests_in_progress
        if requests_in_progress>=8:raise web.HTTPServiceUnavailable()
        requests_in_progress+=1
        try:
            try:response=await handler(request)
            except (ValueError,OSError,KeyError):response=web.json_response({'error':'Operation unavailable or saved identity invalid. No replacement data loaded.'},status=422)
        finally:requests_in_progress-=1
        response.headers.update({'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response
    app=web.Application(middlewares=[guard],client_max_size=2048);app['owner']=owner
    async def status(r):return web.json_response(owner.status())
    async def start(r):return web.json_response(dict(session=await owner.start()))
    async def stop(r):await owner.stop();return web.json_response(owner.status())
    async def interrupt(r):await owner.interrupt();return web.json_response(owner.status())
    async def saved(r):
        sid=r.match_info['sid'];h=r.query.get('hash')
        if not re.fullmatch('[a-f0-9-]{36}',sid):raise ValueError('invalid session')
        loader=saved_loader or validate_saved
        if saved_loader is None and (owner.output/sid/'recovery.json').exists():
            from app.dashboard.e6_recovery import load_saved
            loader=load_saved
        return web.json_response(loader(owner.output/sid,h))
    async def page(r):return web.FileResponse((assets or ROOT/'app/dashboard/e6_live_static')/'index.html')
    async def shared(r):
        s=card_source or (ROOT/'app/dashboard/e6_real_static/watch.js').read_text();return web.Response(text=s[:s.index('function render()')],content_type='text/javascript')
    async def css(r):return web.FileResponse(ROOT/'app/dashboard/static/style.css')
    async def state(r):return web.FileResponse(ROOT/'app/dashboard/e5_static/state.js')
    app.add_routes([web.get('/',page),web.get('/api/status',status),web.post('/api/start',start),web.post('/api/stop',stop),web.post('/api/interrupt',interrupt),web.get('/api/saved/{sid}',saved),web.get('/shared-card.js',shared),web.get('/style.css',css),web.get('/shared-state.js',state)])
    app.router.add_static('/view/',ROOT/'app/dashboard/e6_real_static',show_index=False)
    app.router.add_static('/live/',assets or ROOT/'app/dashboard/e6_live_static',show_index=False)
    async def cleanup(app):await owner.close()
    app.on_cleanup.append(cleanup)
    return app

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8779);p.add_argument('--output',type=Path,default=OUTPUT);a=p.parse_args()
    import psycopg
    def deny(*args,**kw):raise PermissionError('file journal application forbids databases')
    psycopg.connect=psycopg.Connection.connect=psycopg.AsyncConnection.connect=deny
    # Lock only this isolated environment. No auto-resume on restart.
    import fcntl
    a.output.mkdir(parents=True,exist_ok=True)
    with (a.output/'owner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        web.run_app(create_app(a.output),host='127.0.0.1',port=a.port,access_log=None)
if __name__=='__main__':main()
