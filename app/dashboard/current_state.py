"""U2 bounded provider/commit/update and immutable lease interfaces for U3.

No source workers, durable cursor, history load, credential access or archive.
All state transitions occur synchronously on the server event loop, including
lease validation/admission; a notification follows the committed state swap.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import time
from uuid import uuid4
from aiohttp import web
from .current_contract import VERSION, VENUES, serialize, packed, quotes_of, manual_scenario, stamp, snapshot_inputs
from .local_security import HEADERS, read_json

CURRENT_KEY=web.AppKey('current',object)
MAX_STREAMS=8
STREAM_WRITE_SECONDS=2


def unavailable():
    now=datetime.now(timezone.utc).isoformat()
    return dict(schema=VERSION,mode='current',runtime_id=str(uuid4()),state_revision=1,projected_at=now,clock_at=now,
                state='unavailable',events=[],source_status={v:dict(state='unavailable',reason_code='current_provider_pending',
                reason='Automatic current prices are not connected yet.',next_due_at=None) for v in VENUES})


class CurrentStateProvider:
    """Explicit current-state absence until U3 injects its normalized service."""
    allow_synthetic=False

    def initial_state(self):
        return unavailable()

    async def close(self):
        pass


class SelectionError(Exception):
    def __init__(self,status,code,reason,**extra):
        self.status=status; self.body=dict(error=code,reason=reason,**extra)


class CurrentStore:
    def __init__(self,provider=None,*,monotonic=time.monotonic,lease_ttl=300):
        self.provider=provider or CurrentStateProvider()
        self.monotonic=monotonic
        if not 0<lease_ttl<=300:raise ValueError('Lease TTL must be at most 300 seconds')
        self.ttl=lease_ttl;self.leases={};self.clients={};self.subscribers=set();self.closed=False
        self._state=serialize(self.provider.initial_state(),allow_synthetic=self.provider.allow_synthetic)
        self._age_origin=self.monotonic();self._clock_origin=stamp(self._state['clock_at'])

    def snapshot(self):
        self.refresh_age()
        return deepcopy(self._state)

    def refresh_age(self):
        elapsed=max(0,int(self.monotonic()-self._age_origin))
        clock=self._clock_origin+timedelta(seconds=elapsed)
        if clock<=stamp(self._state['clock_at']):return
        state=deepcopy(self._state);state['clock_at']=clock.isoformat();changed=False
        for e in state['events']:
            for g in e['groups']:
                for o in g['outcomes']:
                    for q in quotes_of(o):
                        source=stamp(q['times']['source_at'],True)
                        if source is None:continue
                        age=(clock-source).total_seconds();q['age_seconds']=None if age<0 else age
                        policy=q.get('freshness_policy')
                        stale=age<0 or policy is None or age>policy['maximum_age_seconds']
                        if stale!=q['stale']:
                            changed=True
        if changed:
            state['state_revision']+=1
            # Every dependent result is rebuilt from its original bound inputs,
            # including engine legs whose other quote became stale. Leases stay frozen.
            state=serialize(snapshot_inputs(state),allow_synthetic=self.provider.allow_synthetic)
        self._state=state
        if changed:self.publish()

    def publish(self):
        for queue in self.subscribers:
            if queue.full():queue.get_nowait()
            queue.put_nowait(self.notice())

    def notice(self):
        return {k:self._state[k] for k in ('schema','runtime_id','state_revision')}

    def commit(self,raw):
        if self.closed:raise ValueError('Current store is closed')
        raw=deepcopy(raw)
        evaluated=self._clock_origin+timedelta(seconds=max(0,int(self.monotonic()-self._age_origin)))
        if raw.get('runtime_id')==self._state['runtime_id'] and stamp(raw['clock_at'])<evaluated:raw['clock_at']=evaluated.isoformat()
        candidate=serialize(raw,allow_synthetic=self.provider.allow_synthetic)
        old=self._state
        if candidate['runtime_id']==old['runtime_id']:
            if candidate['state_revision']<=old['state_revision']:
                return False  # Duplicate/regressing notices never replace a commit.
            previous={x['quote']['id']:x['quote'] for x in self.index(old).values()}
            for x in self.index(candidate).values():
                q=x['quote'];prev=previous.get(q['id'])
                if prev:
                    if q['revision']<prev['revision']:raise ValueError('Quote revision regressed')
                    # Receipt/projection clocks alone do not reprice a quote.
                    content=lambda v:dict({k:v.get(k) for k in ('original','source','state','rule_note','binding','calculation_inputs','depth','freshness_policy','rules_differ','cost_note')},source_time_kind=v['times']['source_time_kind'])
                    if q['revision']==prev['revision'] and content(q)!=content(prev):raise ValueError('Quote changed without a coherent revision')
                    if q['revision']>prev['revision'] and content(q)==content(prev):raise ValueError('Heartbeat cannot reprice a quote')
                    if q['times']['source_at'] is not None and q['times']['source_at']!=prev['times']['source_at'] and q['original']==prev['original'] and q.get('observation_time_evidence') is None:
                        raise ValueError('Identical repeat cannot reset source age without explicit observation-time evidence')
        else:
            self.leases.clear();self.clients.clear()
        self._state=candidate
        self._age_origin=self.monotonic();self._clock_origin=stamp(candidate['clock_at'])
        self.publish()
        return True

    @staticmethod
    def index(state):
        result={}
        for e in state['events']:
            for g in e['groups']:
                for o in g['outcomes']:
                    for q in quotes_of(o):
                        if q['id'] in result:raise ValueError('Instrument identity occurs twice')
                        # Hold just this event/group/outcome context, not the catalog.
                        result[q['id']]=dict(event={k:v for k,v in e.items() if k!='groups'},
                            group={k:v for k,v in g.items() if k!='outcomes'},
                            outcome={k:v for k,v in o.items() if k not in ('quotes','alternatives')},
                            quote=q,comparisonQuotes=o['quotes'],alternatives=o.get('alternatives',{}))
        return result

    def prune(self):
        now=self.monotonic()
        for token,lease in list(self.leases.items()):
            if now>=lease['deadline']:
                self.leases.pop(token)
                if self.clients.get(lease['client'])==token:self.clients.pop(lease['client'])

    def create(self,request):
        expected={'schema','runtime_id','state_revision','quote_id','quote_revision','client_id'}
        if not isinstance(request,dict) or set(request)!=expected or request['schema']!=VERSION:raise ValueError('Exact selection request required')
        for k in ('runtime_id','quote_id','client_id'):
            if not isinstance(request[k],str) or not 1<=len(request[k])<=160:raise ValueError('Bounded selection identity required')
        for k in ('state_revision','quote_revision'):
            if type(request[k]) is not int or request[k]<1:raise ValueError('Positive selection revision required')
        self.prune();self.refresh_age()
        state=self._state
        if self.closed or request['runtime_id']!=state['runtime_id']:
            raise SelectionError(410,'selection_expired','Current runtime changed; reselect a current price')
        selected=self.index(state).get(request['quote_id'])
        if selected is None or state['state_revision']!=request['state_revision'] or selected['quote']['revision']!=request['quote_revision']:
            latest=None if selected is None else dict(quote_id=selected['quote']['id'],quote_revision=selected['quote']['revision'])
            raise SelectionError(409,'selection_changed','Prices changed before selection; reselect deliberately',latest=latest,**self.notice())
        if selected['quote']['state'] in ('error','unavailable','not_offered','stopped','connecting','resyncing'):
            raise SelectionError(409,'selection_changed','Selected price is no longer available for review',latest=None)
        selected.update(runtime_id=state['runtime_id'],state_revision=state['state_revision'],clock_at=state['clock_at'],mode=state['mode'])
        size=len(packed(selected));previous=self.clients.get(request['client_id'])
        retained=[l for token,l in self.leases.items() if token!=previous]
        if len(retained)>=8 or sum(l['bytes'] for l in retained)+size>2*1024*1024:
            raise SelectionError(429,'selection_capacity','Reviews are full; close a review or wait for expiry')
        # Capacity and revision validation precede replacement. Failed adoption
        # leaves the previous review untouched.
        token=str(uuid4())
        lease=dict(client=request['client_id'],review=deepcopy(selected),deadline=self.monotonic()+self.ttl,bytes=size)
        if previous:self.leases.pop(previous,None)
        self.leases[token]=lease;self.clients[request['client_id']]=token
        return self.get(token)

    def get(self,token):
        self.prune();lease=self.leases.get(token)
        if self.closed or not lease:
            raise SelectionError(410,'selection_expired','Selection expired, released or runtime restarted')
        review=lease['review'];q=review['quote'];latest=self.index(self._state).get(q['id'])
        newer=latest is None or latest['quote']['revision']!=q['revision']
        return dict(schema=VERSION,selection_id=token,runtime_id=self._state['runtime_id'],status='newer_available' if newer else 'held',
            ttl_remaining=max(0,lease['deadline']-self.monotonic()),review=deepcopy(review),
            latest=None if latest is None else dict(quote_id=q['id'],quote_revision=latest['quote']['revision'],state_revision=self._state['state_revision'],state=latest['quote']['state'],display=deepcopy(latest['quote']['display'])))

    def release(self,token):
        self.get(token)
        lease=self.leases.pop(token)
        if self.clients.get(lease['client'])==token:self.clients.pop(lease['client'])
        return dict(released=True)

    async def close(self):
        if self.closed:return
        # Provider revokes dispatch and establishes source safety before the
        # store expires leases and closes subscriber delivery.
        await self.provider.close()
        self.closed=True;self.leases.clear();self.clients.clear()
        for queue in self.subscribers:
            if queue.full():queue.get_nowait()
            queue.put_nowait(None)


def mount(app,provider=None):
    store=CurrentStore(provider);app[CURRENT_KEY]=store

    def strict_query(req):
        if req.query:raise ValueError('Current endpoints do not accept filters or acquisition controls')

    async def current(req):
        strict_query(req)
        return web.json_response(store.snapshot())

    async def updates(req):
        strict_query(req)
        if req.method=='HEAD':return web.Response(headers={'Content-Type':'text/event-stream',**HEADERS})
        if len(store.subscribers)>=MAX_STREAMS:return web.json_response({'error':'update_capacity','reason':'Too many connected boards'},status=429,headers={'Retry-After':'2',**HEADERS})
        queue=asyncio.Queue(maxsize=1);store.subscribers.add(queue);queue.put_nowait(store.notice())
        response=web.StreamResponse(headers={'Content-Type':'text/event-stream',**HEADERS})
        try:
            await response.prepare(req)
            while not store.closed and req.transport is not None and not req.transport.is_closing():
                try:
                    notice=await asyncio.wait_for(queue.get(),10)
                    if notice is None:break
                    data=b'data: '+packed(notice)+b'\n\n'
                except TimeoutError:data=b': connection heartbeat\n\n'
                # One tiny latest notice (<1KiB) pending, no journal backlog.
                async with asyncio.timeout(STREAM_WRITE_SECONDS):await response.write(data)
        except (ConnectionError,TimeoutError,asyncio.CancelledError):
            pass
        finally:store.subscribers.discard(queue)
        return response

    async def selection(req):
        strict_query(req)
        try:
            if req.path=='/api/selections':return web.json_response(store.create(await read_json(req)),status=201)
            token=req.match_info['token']
            if req.method=='GET':return web.json_response(store.get(token))
            body=await read_json(req)
            if req.path.endswith('/release'):
                if body!={}:raise ValueError('Release accepts an empty object')
                return web.json_response(store.release(token))
            review=store.get(token)['review']
            return web.json_response(manual_scenario(review,body))
        except SelectionError as exc:return web.json_response(exc.body,status=exc.status)

    app.router.add_get('/api/current',current)
    app.router.add_get('/api/current/updates',updates)
    app.router.add_post('/api/selections',selection)
    app.router.add_get('/api/selections/{token}',selection)
    app.router.add_post('/api/selections/{token}/release',selection)
    app.router.add_post('/api/selections/{token}/what-if',selection)
    async def aging():
        while not store.closed:
            await asyncio.sleep(1)
            store.refresh_age();store.prune()
    async def startup(app):
        start=getattr(store.provider,'start',None)
        if start:await start(store)
        app[age_key]=asyncio.create_task(aging())
    async def shutdown(app):
        await store.close()
        task=app.get(age_key)
        if task:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
    age_key=web.AppKey('current_age_task',object)
    app.on_startup.append(startup)
    app.on_shutdown.append(shutdown)
    app.on_cleanup.append(shutdown)
    return store
