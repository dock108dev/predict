"""Explicit one-market diagnostic collector; never selected by production factories.

Transport is injected. The included transport is loopback-only and credential-free.
No live entry point or credential loader is provided by this offline qualification.
"""
import asyncio
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
import fcntl
import fnmatch
import json
import os
from pathlib import Path
import shutil
import time
from urllib.parse import quote, urlsplit
from uuid import uuid4

from app.adapters.kalshi import Response, decode, parse_event, parse_market, parse_book
from app.adapters.kalshi_stream import BookReconstructor, RecoveryRequired
from app.dashboard.bounds import CaptureQueue, retained_bytes
from app.dashboard.coverage_owner import CoverageOwner
from app.models.core import EvidenceKind
from . import coverage
from .continuous import select_inventory
from .delivery_budget import CAP, MIB, Bodies, Clock, Records, Requests, raw_fields
from .finalization import write_supplement
from .odds_http import BudgetStop, mock_endpoint
from .segmented import fsync_dir
from .supervised import PROFILE, bound_native, native_state

SLOTS = tuple(range(60,300,15))
BASE = '/trade-api/v2'


def canonical(book):
    return {o.outcome_id:[[str(v.price.value.normalize()),str(v.quantity.value.normalize())]
        for v in o.bids.levels[:20]] if o.bids is not None else None for o in book.outcomes}


def choose(pages, started, *, kind=EvidenceKind.SYNTHETIC):
    """Reuse native catalog exclusions; stricter ten-minute Start margin."""
    cat = coverage.catalog(pages,'kalshi',started)
    if coverage.traversal([p for p in pages if p['path'].endswith('/events')], 'kalshi','events')[1]['state'] != 'exhausted':
        raise ValueError('incomplete_events')
    if len(cat['events'])>128 or len(cat['markets'])>256: raise BudgetStop('catalog_size')
    for event in cat['events']:
        if event['exclusion'] is None and event['market_discovery'] != 'exhausted':
            raise ValueError('incomplete_markets')
        if event['identity']!='resolved':
            for m in cat['markets']:
                if m['event_id']==event['id']:m['exclusion']='unresolved_identity'
    # select_inventory applies +300; adding 300 implements Start+600.
    ids, count = select_inventory(cat,started+timedelta(seconds=300),cap=1)
    if not ids: raise ValueError('no_eligible_market')
    selected = next(m for m in cat['markets'] if m['id']==ids[0])
    event = next(e for e in cat['events'] if e['id']==selected['event_id'])
    page = next(p for p in pages if p['body_sha256']==selected['provenance'][0]['body_sha256'])
    response = Response(coverage.decode_page(page)[0],page['path'],coverage.stamp(page['received_at']),kind)
    market = parse_market(response,selected['_native'],event['id'],'KXNFLGAME')
    audit = dict(selected=ids[0],kickoff=event['scheduled_start'],eligible=count,
        markets=[dict(id=m['id'],exclusion=m.get('subscription_exclusion')) for m in cat['markets']])
    return market,audit


class LoopbackTransport:
    """Native HTTP/WS shapes, literal loopback destinations, no secrets or redirects."""
    def __init__(self, endpoints, credentials=None):
        if credentials or set(endpoints)!={'kalshi'}: raise ValueError('Kalshi-only fixture; credentials forbidden')
        values=endpoints['kalshi']
        if set(values)!={'rest','ws'}: raise ValueError('endpoint fields')
        for name,scheme in (('rest','http'),('ws','ws')):
            p=urlsplit(mock_endpoint(values[name]))
            if p.scheme!=scheme or not p.port: raise ValueError('literal loopback endpoint required')
        self.endpoints=values;self.client=None;self.socket=None;self.connections=0;self.credential=None;self.mode='synthetic'

    def http_url(self,path,params):
        return self.endpoints['rest']+path

    def ws_url(self):
        return self.endpoints['ws']

    async def http(self,path,params,consume):
        import aiohttp
        url=self.http_url(path,params)
        if self.client is None:
            self.client=aiohttp.ClientSession(auto_decompress=False,trust_env=False,
                timeout=aiohttp.ClientTimeout(total=5),connector=aiohttp.TCPConnector(limit=1))
            # aiohttp otherwise retries idempotent GET on a disconnected socket
            # inside one request call, bypassing our explicit attempt accounting.
            # Pin/verify this library seam in the disconnect regression.
            self.client._retry_connection=False
        headers={'Accept-Encoding':'identity'}
        if self.credential:headers.update(self.credential.headers(path))
        async with self.client.get(url,params=params,
                allow_redirects=False,headers=headers) as response:
            if self.credential:self.credential.check(json.dumps(dict(response.headers)).encode(),headers=headers)
            headers={k:v for k,v in response.headers.items() if k.lower() in ('date','age','cache-control','etag')}
            if response.headers.get('Content-Encoding','identity')!='identity': raise ValueError('compressed_body')
            received=0
            while received<CAP['body']:
                block=await response.content.read(min(4096,CAP['body']-received))
                if not block:break
                received+=len(block);consume(block)
            if received==CAP['body'] and not response.content.at_eof():raise BudgetStop('http_oversize')
            return response.status,headers

    async def connect(self):
        from websockets.asyncio.client import connect
        if self.connections: raise BudgetStop('one_connection_attempt')
        self.connections+=1
        class NoRedirect(connect):
            def process_redirect(self,exc): return exc
        self.socket=await NoRedirect(self.ws_url(),max_size=CAP['body'],max_queue=1,
            compression=None,open_timeout=3,close_timeout=1,proxy=None,
            additional_headers=self.credential.headers() if self.credential else None)
        return self.socket

    async def close(self):
        if self.socket: await self.socket.close()
        if self.client: await self.client.close()


class KalshiTransport(LoopbackTransport):
    """Future authorized use via injected existing Kalshi credential, never keyring.

    Construction has no traffic. Caller must acquire the shared production owner
    and verify candidate/one-shot authorization before constructing a Session.
    """
    def __init__(self,credential):
        from .venue_access import Credential,ENDPOINTS
        if type(credential) is not Credential or credential.venue!='kalshi':
            raise ValueError('only existing Kalshi project credential supported')
        self.endpoints=dict(ENDPOINTS['kalshi']);self.credential=credential;self.mode='real'
        self.client=None;self.socket=None;self.connections=0

    def http_url(self,path,params):
        from .venue_access import ENDPOINTS
        if self.endpoints!=ENDPOINTS['kalshi'] or not native_request(path,params):
            raise ValueError('native_request_surface')
        return super().http_url(path,params)

    def ws_url(self):
        from .venue_access import ENDPOINTS
        if self.endpoints!=ENDPOINTS['kalshi']:raise ValueError('native_destination')
        return super().ws_url()


def native_request(path,params):
    """Exact GET surface; selected ticker/event binding is additionally checked by HTTP."""
    if not isinstance(params,dict):return False
    if path in (BASE+'/account/limits',BASE+'/account/endpoint_costs'):return params=={}
    cursor=params.get('cursor')
    pagination=type(params.get('limit')) is int and params['limit']==200 and isinstance(cursor,str) and len(cursor)<=4096
    if path==BASE+'/events':
        return pagination and params==dict(series_ticker='KXNFLGAME',status='open',with_milestones='true',limit=200,cursor=cursor)
    if path==BASE+'/markets':
        event=params.get('event_ticker')
        return pagination and isinstance(event,str) and bool(event) and set(params)=={'event_ticker','limit','cursor'}
    if path.startswith(BASE+'/markets/') and path.endswith('/orderbook'):
        from urllib.parse import unquote
        ticker=path[len(BASE+'/markets/'):-len('/orderbook')]
        return bool(ticker) and quote(unquote(ticker),safe='')==ticker and params=={'depth':20} and type(params['depth']) is int
    return False


class HTTP:
    def __init__(self,session):
        self.s=session;self.lock=asyncio.Lock();self.next_at=0.;self.rate=None;self.capacity=None
        self.last_begin=-1e30
        self.costs=None;self.requests=Requests();self.results=dict(success=0,failure=0,cancelled=0)

    def account_limits(self,limits,costs):
        # Same account rules as continuous.REST, with finite-value validation.
        from .continuous import REST
        REST.account_limits(self,limits,costs)
        values=[self.rate,self.capacity,float(costs['default_cost']),*[float(x['cost']) for x in costs['endpoint_costs']]]
        if any(not Decimal(str(v)).is_finite() or v<=0 for v in values): raise ValueError('account_costs')

    def interval(self,path):
        if self.rate is None:return 1.
        cost=max([float(self.costs['default_cost']),*[float(e['cost']) for e in self.costs['endpoint_costs']
            if e['method']=='GET' and fnmatch.fnmatch(path,e['path'])]])
        if cost>self.capacity: raise BudgetStop('account_capacity')
        return max(.5,cost/self.rate)

    def allowed(self,path,params,kind):
        if kind not in ('initial','refresh','reference') or not native_request(path,params):return False
        if kind=='reference':
            return self.s.market is not None and path==BASE+'/markets/'+quote(self.s.mid,safe='')+'/orderbook' and params=={'depth':20}
        return ((path in (BASE+'/account/limits',BASE+'/account/endpoint_costs') and kind=='initial' and not params) or
            (path==BASE+'/events' and params.get('series_ticker')=='KXNFLGAME' and set(params)<= {'series_ticker','status','with_milestones','limit','cursor'}) or
            (path==BASE+'/markets' and params.get('event_ticker') in self.s.event_ids and set(params)<= {'event_ticker','limit','cursor'}))

    async def get(self,path,params,kind,slot=None):
        self.s.ensure_active()
        if not self.allowed(path,params,kind):raise ValueError('request_surface')
        ready=max(self.next_at,self.last_begin+self.interval(path))
        if kind=='reference' and (self.lock.locked() or self.s.refreshing or self.s.clock.monotonic()<ready):
            self.s.records.save('reference_skipped',slot=slot,reason='http_or_pacing_busy');return None
        async with self.lock:
            if kind!='reference': await self.s.wait_until(max(self.next_at,self.last_begin+self.interval(path)))
            self.s.ensure_active()
            interval=self.interval(path)
            self.s.bodies.reserve('http')
            try:self.requests.charge(kind,slot)
            except BaseException:
                self.s.bodies.finish('http',0);raise
            rid=str(uuid4());begin=self.s.clock.anchor();self.next_at=begin['mono']+interval
            self.last_begin=begin['mono']
            body=bytearray();first=None;last=None;status=None;headers={};outcome='failure';error=None;received_bytes=0
            def consume(block):
                nonlocal first,last,received_bytes
                now=self.s.clock.anchor();first=first or now;last=now
                room=CAP['body']-len(body);body.extend(block[:room]);received_bytes+=min(room,len(block))
                if len(block)>room:raise BudgetStop('http_oversize')
            try:
                self.s.records.save('http_begin',request_id=rid,path=path,params=params,kind=kind,slot=slot,
                    primary_id=self.s.primary_id,primary_state=self.s.primary_state)
                async with asyncio.timeout(min(5,max(.001,self.s.start_mono+300-self.s.clock.monotonic()))):
                    status,headers=await self.s.transport.http(path,params,consume)
                if getattr(self.s.transport,'credential',None):self.s.transport.credential.check(bytes(body))
                if status!=200:raise ValueError('http_status_'+str(status))
                outcome='success'
            except asyncio.CancelledError:
                outcome='cancelled';error='cancelled';raise
            except Exception as exc:
                error=type(exc).__name__
                if getattr(self.s.transport,'credential',None):
                    try:self.s.transport.credential.check(bytes(body))
                    except ValueError:
                        body.clear();error='credential_echo_suppressed';self.s.records.failed=True
                raise
            finally:
                self.s.bodies.finish('http',received_bytes);end=self.s.clock.anchor()
                self.results[outcome]+=1
                if not self.s.records.failed:
                    self.s.records.save('http_end',request_id=rid,path=path,params=params,kind=kind,slot=slot,
                        started=begin,first_byte=first,last_byte=last,ended=end,status=status,headers=headers,
                        outcome=outcome,error=error,timing_uncertain=end['mono']-begin['mono']>2,
                        **raw_fields(bytes(body)))
            return dict(source='kalshi',path=path,params=params,status=status,complete=True,
                received_at=end['utc'],**raw_fields(bytes(body)))


class DiagnosticOwner(CoverageOwner):
    """Reuse the existing flock owner release; no beta catalog/configuration startup."""
    def __init__(self,output,ownership_root,attempt_id):
        self.output=Path(output);self.ownership_root=Path(ownership_root)
        # Attempt scope is rooted at ownership, not bypassable by a new output path.
        if str(__import__('uuid').UUID(attempt_id))!=attempt_id:raise ValueError('attempt UUID')
        self.attempt_id=attempt_id;self.owner_lock=None

    def acquire(self):
        self.ownership_root.mkdir(parents=True,exist_ok=True)
        self.owner_lock=(self.ownership_root/'collector.lock').open('a')
        try:
            fcntl.flock(self.owner_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            marker=self.ownership_root/(self.attempt_id+'.attempt.json')
            with marker.open('x') as f:
                json.dump(dict(attempt=self.attempt_id,output=str(self.output)),f);f.flush();os.fsync(f.fileno())
            fsync_dir(self.ownership_root)
            from .continuous import rss
            if rss()>=192*MIB or shutil.disk_usage(self.output.parent).free<PROFILE['disk_floor']+PROFILE['output']:
                raise BudgetStop('diagnostic_start_resources')
            self.output.mkdir(exist_ok=False)
        except BaseException:
            self.release();raise


class Session:
    def __init__(self,output,transport,*,clock=None,fault=None,start_anchor=None,external_reserve=0,on_closed=None):
        self.output=Path(output);self.transport=transport;self.clock=clock or Clock()
        self.mode=getattr(transport,'mode','synthetic')
        self.kind=EvidenceKind.SYNTHETIC if self.mode=='synthetic' else EvidenceKind.OBSERVATION
        self.fault=fault or (lambda stage:None);self.records=None;self.bodies=Bodies();self.http=HTTP(self)
        self.stop_event=asyncio.Event();self.intake_closed=False;self.reason=None;self.complete=False
        self.market=None;self.mid=None;self.engine=None;self.primary_state=None;self.primary_id=None
        self.last_receipt=None;self.stale=True;self.start_mono=None;self.started=None
        self.refreshing=False;self.event_ids=set();self.ever_ids=set();self.tasks=[];self.connection=None
        self.stage_queue=CaptureQueue(48,4*MIB);self.book_counts=dict(received=0,emitted=0,admitted=0,durable=0,queued=0,drained=0)
        self.startup=False;self.close_errors=[];self.reached=set();self.last_health=None
        self.receipt_changed=asyncio.Event()
        self.start_anchor=start_anchor;self.external_reserve=external_reserve;self.on_closed=on_closed

    def ensure_active(self):
        if self.intake_closed or self.clock.monotonic()>=self.start_mono+300: raise asyncio.CancelledError()

    async def wait_until(self,deadline):
        self.ensure_active()
        delay=deadline-self.clock.monotonic()
        if delay>0:
            try:await asyncio.wait_for(self.stop_event.wait(),delay)
            except TimeoutError:pass
        self.ensure_active()

    def stop(self,reason='direct_stop'):
        if self.intake_closed:return
        self.intake_closed=True;self.reason=reason;self.closed_at=self.clock.monotonic();self.stop_event.set()
        if self.on_closed:self.on_closed(self.closed_at)
        if self.records and not self.records.failed:
            try:self.records.save('stop',reason=reason,intake_closed=True)
            except Exception:pass

    async def discover(self,kind):
        pages=[];self.event_ids=set()
        async def page(path,params):
            # At most one retry for discovery; 429 is always fatal.
            for attempt in range(2):
                try:return await self.http.get(path,params,kind)
                except (TimeoutError,OSError,ValueError) as exc:
                    if attempt or '429' in str(exc) or '401' in str(exc) or '403' in str(exc):raise
                    await self.wait_until(self.clock.monotonic()+1)
        async def traverse(path,params,field):
            cursor='';seen=set();rows=[]
            while True:
                p=await page(path,dict(params,limit=200,cursor=cursor));pages.append(p)
                self.records.guard(state=(pages,rows,self.engine))
                data=decode(__import__('base64').b64decode(p['body_b64']).decode())
                if not isinstance(data.get(field),list) or not isinstance(data.get('cursor'),str):raise ValueError('incomplete_catalog')
                rows.extend(data[field])
                if len(rows)>(128 if field=='events' else 256):raise BudgetStop('catalog_count')
                cursor=data['cursor']
                if not cursor:return rows
                if cursor in seen:raise ValueError('repeated_cursor')
                seen.add(cursor)
        if kind=='initial':
            limits=await page(BASE+'/account/limits',{})
            costs=await page(BASE+'/account/endpoint_costs',{})
            self.http.account_limits(decode(__import__('base64').b64decode(limits['body_b64']).decode()),
                                     decode(__import__('base64').b64decode(costs['body_b64']).decode()))
        events=await traverse(BASE+'/events',dict(series_ticker='KXNFLGAME',status='open',with_milestones='true'),'events')
        cat=coverage.catalog(pages,'kalshi',self.started)
        for event in cat['events']:
            if event['exclusion'] is None:
                self.event_ids.add(event['id'])
                markets=await traverse(BASE+'/markets',dict(event_ticker=event['id']),'markets')
                self.ever_ids.update(m['ticker'] for m in markets)
                if len(self.ever_ids)>256:raise BudgetStop('unique_market_cap')
        market,audit=choose(pages,self.started,kind=self.kind)
        if kind=='refresh':
            # Freeze original identity: a newly earlier eligible market is not a replacement.
            cat=coverage.catalog(pages,'kalshi',self.started)
            ids,_=select_inventory(cat,self.started+timedelta(seconds=300))
            event=next((e for e in cat['events'] if e['id']==self.market.raw.ref.event_id),None)
            if self.mid not in ids or event is None or event['scheduled_start']!=self.kickoff:raise ValueError('eligibility_refresh')
            audit['selected']=self.mid
        else:
            self.market=market;self.mid=market.raw.ref.market_id;self.kickoff=audit['kickoff']
        self.records.save('selection',kind=kind,audit=audit,market=json.loads(json.dumps(asdict(self.market),default=str)))

    def receive(self,raw):
        """Durable raw boundary, then serial parse/reconstruction/admission pipeline."""
        rid=str(uuid4());received=self.clock.anchor()
        row=self.records.save('native_receive',frame=True,receive_id=rid,received=received,
            connection=1,opcode='text' if isinstance(raw,str) else 'binary',**raw_fields(raw.encode() if isinstance(raw,str) else raw))
        if self.intake_closed:
            self.records.save('native_stage',receive_id=rid,stage='admission',status='rejected',
                intentional=True,reason='intake_closed')
            return
        stage='parser';book=None
        try:
            self.records.save('native_stage',receive_id=rid,stage='parser',status='begin',raw_record=row['ingress_id'])
            self.fault('parser')
            native=decode(raw)
            if native.get('type')=='subscribed' and native.get('id')!=self.engine.request_id:
                raise ValueError('subscription_ack_mismatch')
            book=self.engine.feed(raw,self.engine.generation,coverage.stamp(received['utc']))
            self.records.save('native_stage',receive_id=rid,stage='parser',status='complete',
                disposition='qualifying' if book else 'control',sid=self.engine.sid,seq=self.engine.seq)
            if book is None:return
            self.book_counts['received']+=1
            state=canonical(book);stage='emission';self.fault(stage)
            self.records.save('native_stage',receive_id=rid,stage=stage,status='complete',state=state,book_id=rid,
                sequence=book.sequence,source_time=str(book.raw.exchange_at) if book.raw.exchange_at else None)
            self.book_counts['emitted']+=1
            stage='admission';self.fault(stage)
            self.records.save('native_stage',receive_id=rid,stage=stage,status='accepted')
            self.book_counts['admitted']+=1
            self.records.save('native_stage',receive_id=rid,stage='durable',status='complete')
            self.book_counts['durable']+=1
            stage='queue';self.fault(stage)
            item=(rid,state);self.stage_queue.put_nowait(item);self.book_counts['queued']+=1
            self.records.save('native_stage',receive_id=rid,stage=stage,status='inserted')
            self.stage_queue.get_nowait();self.stage_queue.task_done();self.book_counts['drained']+=1
            self.records.save('native_stage',receive_id=rid,stage='drain',status='complete')
            self.primary_state=state;self.primary_id=rid;self.last_receipt=received['mono'];self.stale=False
            self.receipt_changed.set()
            self.startup=True
            self.records.save('coverage',receive_id=rid,usable=True,receipt_mono=self.last_receipt,reason='primary_receipt')
        except Exception as exc:
            if not self.records.failed:
                self.records.save('native_stage',receive_id=rid,stage=stage,status='failed',
                    error=type(exc).__name__,intentional=isinstance(exc,(RecoveryRequired,BudgetStop)))
            raise
        finally:
            self.records.guard(state=(native_state(self.engine),self.primary_state,self.stage_queue._queue,self.http.requests.counts,self.ever_ids))

    async def stream(self):
        self.records.save('connection',state='attempt',attempt=1)
        self.connection=await self.transport.connect()
        self.records.save('connection',state='open',attempt=1,ping_visibility='library-managed; not observable here')
        self.engine=BookReconstructor([self.market],kind=self.kind);bound_native(self.engine)
        command=self.engine.begin(1)
        self.records.save('subscription',command=command,sequence_scope='subscription sid',market=self.mid)
        await self.connection.send(json.dumps(command))
        while not self.intake_closed:
            self.bodies.reserve('primary');n=0
            try:
                body=await self.connection.recv();n=len(body.encode() if isinstance(body,str) else body)
                if n>CAP['body']:raise BudgetStop('primary_oversize')
                if getattr(self.transport,'credential',None):
                    try:self.transport.credential.check(body.encode() if isinstance(body,str) else body)
                    except ValueError:
                        self.records.failed=True;raise
                self.receive(body)
            finally:self.bodies.finish('primary',min(n,CAP['body']))

    async def reference(self,slot):
        p=await self.http.get(BASE+'/markets/'+quote(self.mid,safe='')+'/orderbook',{'depth':20},'reference',slot)
        if p is None:return
        body=__import__('base64').b64decode(p['body_b64']).decode()
        book=parse_book(Response(body,p['path'],coverage.stamp(p['received_at']),self.kind),self.market,depth=20)
        if any(o.bids is None for o in book.outcomes):raise ValueError('incomparable_reference')
        self.records.save('reference_parsed',slot=slot,state=canonical(book),body_sha256=p['body_sha256'],
            market=self.mid,algorithm='native-bids-top20-decimal-v1',server_state_age=None)

    async def schedule(self):
        for second in range(1,301):
            await self.wait_until(self.start_mono+second)
            actual=self.clock.monotonic()
            if second%5==0:
                self.records.guard(state=(native_state(self.engine) if self.engine else {},self.primary_state,self.stage_queue._queue,self.ever_ids))
                self.records.save('health',event_loop_lag=max(0,actual-self.start_mono-second),
                    stale=self.stale,primary_id=self.primary_id,queue_objects=self.stage_queue.qsize(),
                    queue_bytes=self.stage_queue.bytes,state_bytes=self.records.state_peak,rss=__import__('app.collection.continuous',fromlist=['rss']).rss())
            if second==60 and not self.startup:raise ValueError('startup_deadline')
            if second==120:
                self.refreshing=True
                async def refresh():
                    try:await self.discover('refresh')
                    finally:self.refreshing=False
                self.spawn(refresh())
            if second in SLOTS:
                self.reached.add(second)
                if actual-self.start_mono-second>.25:
                    self.records.save('reference_skipped',slot=second,reason='scheduler_late')
                else:self.spawn(self.reference(second))

    async def expiry(self):
        # Independent deadline, preserving strict >30, never canceling native recv.
        while not self.intake_closed:
            self.receipt_changed.clear()
            delay=max(.000001,self.last_receipt+30-self.clock.monotonic()) if self.last_receipt is not None and not self.stale else .5
            try:await asyncio.wait_for(self.receipt_changed.wait(),min(.5,delay))
            except TimeoutError:pass
            if self.last_receipt is not None and not self.stale and self.clock.monotonic()-self.last_receipt>30:
                self.stale=True;self.records.save('coverage',receive_id=self.primary_id,usable=False,
                    receipt_mono=self.last_receipt,reason='receipt_expiry')

    def spawn(self,coro):
        async def guarded():
            try:await coro
            except asyncio.CancelledError:pass
            except Exception as exc:
                self.stop(type(exc).__name__)
        task=asyncio.create_task(guarded());self.tasks.append(task)
        # At most 1 stream, scheduler, discovery, and 16 reference tasks per attempt.
        return task

    async def run(self,started_callback=None):
        self.started=coverage.stamp(self.start_anchor['utc']) if self.start_anchor else self.clock.utc()
        self.start_mono=self.start_anchor['mono'] if self.start_anchor else self.clock.monotonic()
        self.records=Records(self.output,self.clock,external_reserve=self.external_reserve)
        self.records.metadata('spec.json',dict(schema='kalshi-delivery-diagnostic-v1',mode=self.mode,
            duration=300,direct_stop=240,slots=SLOTS,frozen=dict(PROFILE),subcaps=dict(CAP)))
        self.records.save('start',started=self.started.isoformat(),start_mono=self.start_mono,
                          mode=self.mode,transport='Kalshi-only native transport')
        if started_callback:started_callback(self.start_mono)
        async def initial():
            await self.discover('initial');self.spawn(self.stream())
        if not self.intake_closed:
            self.spawn(initial());self.spawn(self.schedule());self.spawn(self.expiry())
        try:await self.stop_event.wait()
        finally:
            self.stop(self.reason or 'cancelled')
            for task in self.tasks:task.cancel()
            try:
                async with asyncio.timeout(5):
                    await asyncio.gather(*self.tasks,return_exceptions=True)
                    await self.transport.close()
            except BaseException as exc:self.close_errors.append(type(exc).__name__)
            self.complete=not self.close_errors and not self.records.failed and not self.bodies.pending
            self.cleanup_finished=self.clock.monotonic()
            self.records.history.finalizing=True
            if self.records.failed or self.close_errors:
                self.records.history.abort()
            else:
                self.records.save('slots_final',not_reached=[s for s in SLOTS if s not in self.reached],
                    requests=self.http.requests.counts,generations=self.http.requests.generations,
                    results=self.http.results,bodies=dict(used=self.bodies.used,pending=self.bodies.pending,peak=self.bodies.peak))
                self.records.history.save(dict(type='session_finished',reason=self.reason,cleanup_errors=[],
                    intake_complete=True,book_counts=self.book_counts))
                self.records.history.finish(cleanup_complete=True)
        return self.complete

    def finalize(self):
        from .delivery_analysis import analyze
        from .segmented import SegmentedReader
        from .supervised import ExactIdentities
        exact=ExactIdentities(self.output/'identities')
        for row in SegmentedReader(self.output/'history').rows():
            if row.get('ingress_id'):exact.add(row['ingress_id'])
        identities=exact.finish()
        result=analyze(self.output/'history')
        self.records.metadata('analysis.json',result,finalizing=True)
        self.records.guard(finalizing=True)
        summary=dict(reason=self.reason,cleanup_complete=self.complete,accounting=self.records.accounting(),
            books=self.book_counts,analysis=result,requests=self.http.requests.counts,bodies=self.bodies.used,
            close_seconds=self.cleanup_finished-self.closed_at,exact_identities=identities)
        proposed=len(json.dumps(summary,indent=2).encode())+16*1024+(self.output/'analysis.json').stat().st_size
        if proposed>CAP['finalization_bytes']:raise BudgetStop('finalization_reserve')
        # Sealed manifest keeps the original frozen policy. Receipt enforcement is
        # narrowed in memory only, after closing the journal, before serialization.
        h=self.records.history;old=h.policy
        h.policy=dict(old,output=CAP['output']-self.external_reserve,write_bytes=CAP['write_bytes']-self.external_reserve)
        try:receipt=write_supplement(self.output,h,summary,started=self.start_mono,closed=self.closed_at)
        finally:h.policy=old
        if receipt['final_retained_output_bytes']>CAP['output'] or receipt['cumulative_application_file_write_bytes']>CAP['write_bytes']:
            raise BudgetStop('diagnostic_finalization_cap')
        return summary,receipt
