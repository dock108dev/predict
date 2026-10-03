"""One attended global sport-wide scheduler under CurrentService ownership."""
import asyncio
import base64
from copy import deepcopy
from hashlib import sha256
import os
import time
from urllib.parse import quote
import aiohttp
from app.dashboard.current_contract import stamp
from app.reference.product import SPORT_KEYS
from .current_policy import ROOT
from .current_quota import QuotaLedger, QuotaStop, load_window, now

BASE='https://api.the-odds-api.com'
SPORTS=('MLB','NCAAF','NBA','NHL','NCAAB','NFL')
PARAMS=dict(bookmakers='novig,prophetx',markets='h2h,spreads,totals',oddsFormat='decimal',dateFormat='iso')


def credential():
    from .credential_handoff import existing_key
    try:
        return existing_key(ROOT,os.environ.get('ODDS_API_KEY'))
    except (OSError,ValueError):
        from app.reference.odds_credentials import SERVICE,ACCOUNT
        try:
            from keyring.backends.macOS import Keyring
            import json
            value=json.loads(Keyring().get_password(SERVICE,ACCOUNT) or '{}')
            if value.get('plan')!='free' or value.get('monthly_credits')!=500 or value.get('confirmation')!='owner-local account-plan check':raise ValueError()
            return existing_key(ROOT,value['api_key'])
        except Exception:
            raise QuotaStop('aggregate_credentials_unavailable') from None


class CurrentOddsTransport:
    def __init__(self):
        self.client=None
        self.closed=False
        self.bytes=0

    async def request(self, request, key):
        if self.closed: raise QuotaStop('aggregate_transport_closed')
        if self.client is None:
            self.client=aiohttp.ClientSession(auto_decompress=False,trust_env=False,
                connector=aiohttp.TCPConnector(limit=1),timeout=aiohttp.ClientTimeout(total=20),
                read_bufsize=4096,max_line_size=4096,max_field_size=4096)
            self.client._retry_connection=False
        async with self.client.get(BASE+request['path'],params={**request['params'],'apiKey':key},
                allow_redirects=False,headers={'Accept-Encoding':'identity'}) as response:
            headers=[(k.lower(),v) for k,v in response.headers.items() if k.lower() in ('x-requests-used','x-requests-remaining','x-requests-last')]
            body=bytearray()
            async for chunk in response.content.iter_chunked(4096):
                self.bytes+=len(chunk)
                if len(body)+len(chunk)>2*1024*1024 or self.bytes>4*1024*1024:raise QuotaStop('aggregate_response_byte_cap')
                body.extend(chunk)
            if response.headers.get('Content-Encoding','identity')!='identity':raise QuotaStop('aggregate_encoding_unsupported')
            raw=bytes(body)
            if any(secret in raw for secret in (key.encode(),base64.b64encode(key.encode()),quote(key).encode())):
                raise QuotaStop('aggregate_secret_echo_suppressed')
            # Return header values only if bounded; never provider error body text.
            safe=[(k,v if len(v)<=12 and v.isdigit() else 'invalid') for k,v in headers]
            return dict(status=response.status,headers=safe,body=raw if response.status==200 else b'',received_at=now())

    async def close(self):
        self.closed=True
        if self.client:await self.client.close()


class AggregateScheduler:
    def __init__(self, service, *, ledger=None, transport=None, key_loader=credential, window_loader=load_window, qualification=None):
        self.service=service
        self.ledger=ledger or QuotaLedger()
        self.transport=transport or CurrentOddsTransport()
        self.key_loader=key_loader;self.window_loader=window_loader
        self.qualification=deepcopy(qualification)
        self.closed=False;self.key=None;self.active_sports=[];self.bootstrapped=False
        self.metrics=dict(requests=0,bootstrap_requests=0,batches=0,worst_case_credits=0,body_bytes=0)
        self.issue_context={}
        self.wall=time.time();self.monotonic=time.monotonic()

    def attended(self):
        return self.service.store is not None and bool(self.service.store.subscribers)

    def permitted(self):
        if self.closed or not self.service.dispatch or self.service.ownership.file is None or time.monotonic()>=self.service.deadline:
            raise QuotaStop('aggregate_dispatch_revoked')
        if not self.attended(): raise QuotaStop('aggregate_idle')
        elapsed=time.monotonic()-self.monotonic
        if abs((time.time()-self.wall)-elapsed)>120:
            self.ledger.pause('clock_jump');raise QuotaStop('clock_jump')

    def state(self, state, code, reason):
        svc=self.service
        if svc.store is None or svc.store.closed:return
        states=deepcopy(svc.states)
        due=self.ledger.snapshot().get('next_due_at')
        for venue in ('novig','prophetx'):
            if code=='aggregate_budget_delayed' and states[venue]['state'] in ('not_offered','unavailable'):
                states[venue]['next_due_at']=due
                continue
            states[venue]=dict(state=state,reason_code=code,reason=reason,next_due_at=due)
        if states==svc.states:return
        svc.sink.commit(svc.row('source_health','the_odds_api',state=state),states)
        svc.states=states

    async def dispatch(self, request, cost, *, bootstrap=False):
        self.permitted()
        if self.metrics['requests']>=3 or self.metrics['worst_case_credits']+cost>6:
            raise QuotaStop('aggregate_runtime_envelope_consumed')
        # Seal exact request/candidate/cost durably before loading secrets.
        aid=self.ledger.reserve(self.service.ownership,self.service.digest,request,cost,bootstrap=bootstrap,qualification=self.qualification)
        self.issue_context=dict(attempt_id=aid,charged_credits=None,endpoint_class='sports_bootstrap' if bootstrap else 'sport_odds')
        sport=next((s for s,k in SPORT_KEYS.items() if request['path']=='/v4/sports/'+k+'/odds'),None)
        if sport:self.issue_context['sport']=sport
        self.service.observation('the_odds_api','reservation',dict(attempt_id=aid,request=request,worst_case_credits=cost))
        if self.key is None:self.key=self.key_loader()
        # Last synchronous boundary: no await between gates, durable uncertainty
        # marker and entering the single-request transport.
        self.permitted()
        self.ledger.dispatched(aid,self.service.ownership)
        self.metrics['requests']+=1;self.metrics['worst_case_credits']+=cost
        if bootstrap:self.metrics['bootstrap_requests']+=1
        else:self.metrics['batches']+=1
        try:
            tick=time.perf_counter()
            response=await self.transport.request(request,self.key)
            self.metrics['http_response_ms']=(time.perf_counter()-tick)*1000
            self.metrics['last_received_at']=response['received_at']
        except asyncio.CancelledError:
            # Marker already uncertain. Cancellation never refunds it.
            raise
        except Exception:
            self.service.observation('the_odds_api','response',dict(attempt_id=aid,status=None,reason='aggregate_transport_uncertain'))
            raise QuotaStop('aggregate_transport_uncertain') from None
        self.ledger.reconcile(aid,response['headers'])
        self.issue_context['charged_credits']=self.ledger.snapshot()['observation']['last']
        self.metrics['body_bytes']+=len(response['body'])
        self.service.observation('the_odds_api','response',dict(attempt_id=aid,status=response['status'],
            request=request,headers=response['headers'],received_at=response['received_at'],body_bytes=len(response['body']),body_sha256=sha256(response['body']).hexdigest()))
        q=self.ledger.snapshot()
        if q['pause']:raise QuotaStop(q['pause'])
        if response['status']!=200:
            code='aggregate_rate_limit' if response['status']==429 else 'aggregate_authentication' if response['status'] in (401,403) else 'aggregate_http_failure'
            # No blind retry; preserve next-due and pause this runtime.
            raise QuotaStop(code)
        return response

    async def step(self):
        self.permitted()
        if not self.bootstrapped:
            self.ledger.bind_window(self.window_loader())
            response=await self.dispatch(dict(path='/v4/sports',params={}),0,bootstrap=True)
            from app.reference.odds_acquire import strict_json
            sports=strict_json(response['body'])
            if not isinstance(sports,list) or len(sports)>512 or any(not isinstance(x,dict) or not isinstance(x.get('key'),str) or type(x.get('active')) is not bool for x in sports):
                raise QuotaStop('aggregate_bootstrap_schema')
            available={x['key'] for x in sports if x['active'] and x.get('has_outrights') is False}
            self.active_sports=[s for s in SPORTS if SPORT_KEYS[s] in available]
            self.bootstrapped=True
        quota=self.ledger.snapshot()
        if quota['pause']:raise QuotaStop(quota['pause'])
        if quota['reset'] is None:raise QuotaStop('reset_window_unknown')
        if quota['next_due_at'] and stamp(now())<stamp(quota['next_due_at']) and (self.qualification is None or self.metrics['batches']>0):
            self.state('budget_delayed','aggregate_budget_delayed','Shared aggregate delivery is budget-paced; inspect each price age.')
            return
        if not self.active_sports:raise QuotaStop('aggregate_common_sport_unobserved')
        sport=self.active_sports[quota['rotation']%len(self.active_sports)]
        request=dict(path='/v4/sports/'+SPORT_KEYS[sport]+'/odds',params=deepcopy(PARAMS))
        response=await self.dispatch(request,3)
        self.permitted() # Revocation forbids admission, independently of charge reconciliation.
        self.issue_context['sport']=sport
        states=deepcopy(self.service.states)
        due=self.ledger.snapshot()['next_due_at']
        from .current_aggregate_admission import admit_venues
        batches,rejected=admit_venues(response['body'],sport,response['received_at'])
        records=[r for batch in batches.values() for r in batch]
        if len(rejected)==2:raise QuotaStop('aggregate_admission_failed')
        for venue in ('novig','prophetx'):
            exists=any(r['quote']['venue']==venue for r in records)
            states[venue]=dict(state='unavailable' if venue in rejected else 'budget_delayed' if exists else 'not_offered',reason_code=rejected[venue] if venue in rejected else 'aggregate_observed' if exists else 'aggregate_offering_unobserved',
                reason='Malformed venue inputs withheld; previous valid inputs remain inspectable.' if venue in rejected else 'Shared aggregate batch received; source age and freshness eligibility remain separate.' if exists else 'No venue records observed in this sport batch.',
                received_at=response['received_at'],next_due_at=due)
        self.service.sink.commit(dict(type='current_aggregate',source='the_odds_api',sport=sport,body=response['body'],received_at=response['received_at']),states)
        self.service.states=states
        self.service.observation('the_odds_api','admission',dict(sport=sport,quotes=len(records),venues=sorted({r['quote']['venue'] for r in records})))
        self.metrics.update(admitted_records=len(records),rejected_venues=len(rejected))
        for venue in ('novig','prophetx'):
            if venue in rejected:self.service.issue(venue,'malformed_source','aggregate_admission_failed')
            elif not any(r['quote']['venue']==venue for r in records):self.service.issue(venue,'offering_unobserved','aggregate_offering_unobserved')

    async def run(self):
        while not self.closed and self.service.dispatch:
            if not self.attended():
                self.state('budget_delayed','aggregate_idle','Aggregate delivery waits for an open board; native feeds continue.')
                await asyncio.sleep(1);continue
            try:
                await self.step()
            except asyncio.CancelledError:raise
            except Exception as exc:
                code=str(exc) if isinstance(exc,QuotaStop) else 'aggregate_admission_failed'
                if code in ('bootstrap_budget_delayed','aggregate_budget_delayed'):
                    self.state('budget_delayed','aggregate_budget_delayed','Shared aggregate delivery waits for its persisted due time.')
                    await asyncio.sleep(1)
                    continue
                self.state('unavailable',code,'Aggregate acquisition paused: '+code.replace('_',' ')+'. Native sources continue.')
                self.service.issue('the_odds_api','quota_or_source',code)
                return
            await asyncio.sleep(1)

    async def close(self):
        self.closed=True
        await self.transport.close()
        self.key=None
