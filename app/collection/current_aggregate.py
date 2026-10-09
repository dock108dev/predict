"""One running-app aggregate scheduler under CurrentService ownership."""
import asyncio
import base64
import json
from copy import deepcopy
from hashlib import sha256
import os
import time
from urllib.parse import quote
import aiohttp
from app.dashboard.current_contract import stamp
from app.reference.product import SPORT_KEYS
from .current_policy import ROOT, aggregate_scope
from .current_aggregate_policy import POLICY
from .current_quota import QuotaLedger, QuotaStop, load_window, now

BASE=POLICY.endpoint
SPORTS=('MLB','NCAAF','NBA','NHL','NCAAB','NFL')
PARAMS=dict(bookmakers=','.join(POLICY.bookmakers),markets=','.join(POLICY.markets),oddsFormat='decimal',dateFormat='iso')


def credential():
    from .credential_handoff import existing_key
    try:
        metadata=ROOT/'.local/predict-odds-account.json'
        if metadata.exists():
            # Paid selection is .env only; never downgrade to a legacy Keychain account.
            return existing_key(ROOT)
        return existing_key(ROOT,os.environ.get('ODDS_API_KEY'))
    except (OSError,ValueError):
        if (ROOT/'.local/predict-odds-account.json').exists():raise QuotaStop('aggregate_paid_credential_selection_failed') from None
        from app.reference.odds_credentials import SERVICE,ACCOUNT
        try:
            from keyring.backends.macOS import Keyring
            import json
            value=json.loads(Keyring().get_password(SERVICE,ACCOUNT) or '{}')
            if (value.get('plan'),value.get('monthly_credits')) not in (('free',500),('paid',POLICY.monthly_ceiling)) or value.get('confirmation')!='owner-local account-plan check':raise ValueError()
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
                connector=aiohttp.TCPConnector(limit=1),timeout=aiohttp.ClientTimeout(total=POLICY.timeout_seconds),
                read_bufsize=4096,max_line_size=4096,max_field_size=4096)
            self.client._retry_connection=False
        async with self.client.get(BASE+request['path'],params={**request['params'],'apiKey':key},
                allow_redirects=False,headers={'Accept-Encoding':'identity'}) as response:
            headers=[(k.lower(),v) for k,v in response.headers.items() if k.lower() in ('x-requests-used','x-requests-remaining','x-requests-last')]
            body=bytearray()
            async for chunk in response.content.iter_chunked(4096):
                self.bytes+=len(chunk)
                if len(body)+len(chunk)>POLICY.response_bytes or self.bytes>POLICY.cycle_bytes:raise QuotaStop('aggregate_response_byte_cap')
                body.extend(chunk)
            if response.headers.get('Content-Encoding','identity')!='identity':raise QuotaStop('aggregate_encoding_unsupported')
            raw=bytes(body)
            import json
            from urllib.parse import unquote
            try:decoded=json.dumps(json.loads(raw),ensure_ascii=False)
            except (ValueError,UnicodeError,RecursionError):decoded=raw.decode('utf-8',errors='replace')
            for _ in range(3):decoded=unquote(decoded)
            if key in decoded or 'apikey' in decoded.lower() or 'api_key' in decoded.lower():raise QuotaStop('aggregate_secret_echo_suppressed')
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
        self.cycle_id=None;self.cycle_requests=0;self.cycle_credits=0;self.sport_states={};self.prepared=False;self.manual=False;self.acquisition_lock=asyncio.Lock()
        self.wall=time.time();self.monotonic=__import__('app.collection.current_clock',fromlist=['continuous']).continuous()

    def attended(self):
        return self.service.store is not None and not self.service.store.closed

    def permitted(self):
        if self.closed or not self.service.dispatch or self.service.ownership.file is None or time.monotonic()>=self.service.deadline:
            raise QuotaStop('aggregate_dispatch_revoked')
        elapsed=__import__('app.collection.current_clock',fromlist=['continuous']).continuous()-self.monotonic
        if abs((time.time()-self.wall)-elapsed)>120:
            self.ledger.pause('clock_jump');raise QuotaStop('clock_jump')

    def state(self, state, code, reason):
        svc=self.service
        if svc.store is None or svc.store.closed:return
        states=deepcopy(svc.states)
        from .current_schedule import schedule
        plan=schedule(now())
        due=plan['next_due_at'] if not plan['open'] else self.ledger.snapshot().get('next_due_at')
        if due and not schedule(due)['open']:due=schedule(due)['next_due_at']
        for venue in ('novig','prophetx'):
            if code=='aggregate_budget_delayed' and states[venue]['state'] in ('not_offered','unavailable'):
                states[venue]['next_due_at']=due
                continue
            scoped='; '.join(scope+': '+values[venue]['reason'] for scope,values in self.sport_states.items())
            states[venue]=dict(state=state,reason_code=code,reason=reason+(' '+scoped if scoped else ''),next_due_at=due)
        if states==svc.states:return
        svc.sink.commit(svc.row('source_health','the_odds_api',state=state),states)
        svc.states=states

    async def dispatch(self, request, cost, *, bootstrap=False):
        self.permitted()
        from .current_schedule import schedule
        if not self.manual and not schedule(now())['open']:raise QuotaStop('aggregate_outside_window')
        if self.cycle_requests>=POLICY.requests_per_cycle or self.cycle_credits+cost>POLICY.worst_case_credits_per_cycle:
            raise QuotaStop('aggregate_runtime_envelope_consumed')
        # Seal exact request/candidate/cost durably before loading secrets.
        aid=self.ledger.reserve(self.service.ownership,self.service.digest,request,cost,bootstrap=bootstrap,qualification=self.qualification,cycle_id=self.cycle_id)
        self.issue_context=dict(attempt_id=aid,charged_credits=None,endpoint_class='sports_bootstrap' if bootstrap else 'sport_odds')
        sport=next((s for s,k in SPORT_KEYS.items() if request['path']=='/v4/sports/'+k+'/odds'),None)
        if sport:self.issue_context['sport']=sport
        self.service.observation('the_odds_api','reservation',dict(attempt_id=aid,request=request,worst_case_credits=cost))
        if self.key is None:self.key=self.key_loader()
        # Last synchronous boundary: no await between gates, durable uncertainty
        # marker and entering the single-request transport.
        self.permitted()
        self.ledger.dispatched(aid,self.service.ownership)
        self.cycle_requests+=1;self.cycle_credits+=cost
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
        self.metrics['last_quota_headers']=deepcopy(response['headers'])
        self.ledger.reconcile(aid,response['headers'])
        quota=self.ledger.snapshot()
        self.issue_context['charged_credits']=None if quota['observation'] is None else quota['observation']['last']
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
        async with self.acquisition_lock:await self.scheduled_step()

    async def refresh(self,sports,identity,reference=False):
        if self.acquisition_lock.locked():raise QuotaStop('aggregate_refresh_in_progress')
        async with self.acquisition_lock:
            self.permitted()
            quota=self.ledger.snapshot()
            if quota['pause']:raise QuotaStop(quota['pause'])
            self.ledger.bind_window(self.window_loader())
            params=deepcopy(PARAMS)
            if reference and 'pinnacle' not in params['bookmakers'].split(','):params['bookmakers']+=',pinnacle'
            requests=[dict(path='/v4/sports/'+SPORT_KEYS[s]+'/odds',params=deepcopy(params)) for s in sports]
            self.cycle_requests=0;self.cycle_credits=0;self.transport.bytes=0
            self.cycle_id=self.ledger.begin_manual_cycle(self.service.ownership,requests,identity)
            self.manual=True
            self.metrics['manual_scope']=list(sports)
            self.metrics['manual_refresh_id']=identity
            try:
                responses=[]
                for sport,request in zip(sports,requests):
                    response=await self.dispatch(request,POLICY.credits_per_batch)
                    self.retain_diagnostic(response,sport)
                    if reference:
                        from .current_aggregate_admission import diagnostic
                        from hashlib import sha256
                        root=ROOT/'.local/predict-odds/baselines'/sha256(identity.encode()).hexdigest()[:24]
                        root.mkdir(parents=True,exist_ok=True)
                        record=diagnostic(response['body'],sport,response['received_at'],{})
                        record['authority']='Owner authorized one full Novig, ProphetX and Pinnacle baseline pull'
                        record['request_id']=identity
                        (root/(sport+'.json')).write_text(json.dumps(record,sort_keys=True))
                    responses.append((sport,response))
                errors=[]
                for sport,response in responses:
                    try:self.admit_response(response,sport)
                    except QuotaStop as exc:errors.append(exc)
                if errors:raise errors[0]
            except QuotaStop as exc:
                self.state('unavailable',str(exc),'On-demand aggregate refresh stopped: '+str(exc).replace('_',' ')+'. Native sources continue.')
                self.service.issue('the_odds_api','quota_or_source',str(exc))
                raise
            finally:self.manual=False;self.cycle_id=None

    async def scheduled_step(self):
        self.permitted()
        from .current_schedule import schedule
        plan=schedule(now())
        if not plan['open']:
            self.state('budget_delayed','aggregate_outside_window','Aggregate paused outside 09:00–23:00 Eastern; next cycle '+plan['next_due_at']+'. Scope: '+', '.join(aggregate_scope(self.service.config))+'.')
            return
        self.cycle_requests=0;self.cycle_credits=0;self.transport.bytes=0
        if not self.prepared:
            evidence=self.window_loader()
            self.ledger.prepare_clock(self.service.ownership,self.service.digest,evidence,
                cleanup_safe=not self.service.closing and not self.service.closed and not self.service.cleanup_errors)
            self.ledger.bind_window(evidence)
            self.prepared=True
            quota=self.ledger.snapshot();inventory=quota.get('sports_inventory')
            if (inventory and inventory['account_id']==quota.get('account_id') and quota['observation'] is not None
                and 0<=(stamp(now())-stamp(inventory['at'])).total_seconds()<POLICY.inventory_seconds
                and (quota['accounting_epoch'] is None or quota['accounting_epoch']['state']=='current')):
                self.active_sports=[s for s in aggregate_scope(self.service.config) if SPORT_KEYS[s] in inventory['active']]
                self.bootstrapped=True
        inventory=self.ledger.snapshot().get('sports_inventory')
        if self.bootstrapped and inventory and (stamp(now())-stamp(inventory['at'])).total_seconds()>=POLICY.inventory_seconds:self.bootstrapped=False
        if not self.bootstrapped:
            response=await self.dispatch(dict(path='/v4/sports',params={}),0,bootstrap=True)
            from app.reference.odds_acquire import strict_json
            sports=strict_json(response['body'])
            if not isinstance(sports,list) or len(sports)>512 or any(not isinstance(x,dict) or not isinstance(x.get('key'),str) or type(x.get('active')) is not bool for x in sports):
                raise QuotaStop('aggregate_bootstrap_schema')
            available={x['key'] for x in sports if x['active'] and x.get('has_outrights') is False}
            self.ledger.record_sports([k for k in available if k in SPORT_KEYS.values()])
            self.active_sports=[s for s in aggregate_scope(self.service.config) if SPORT_KEYS[s] in available]
            self.bootstrapped=True
        quota=self.ledger.snapshot()
        if quota['pause']:raise QuotaStop(quota['pause'])
        if quota['reset'] is None:raise QuotaStop('reset_window_unknown')
        if quota['next_due_at'] and stamp(now())<stamp(quota['next_due_at']) and (self.qualification is None or self.metrics['batches']>0):
            self.state('budget_delayed','aggregate_budget_delayed','Shared aggregate cycle every 15 minutes, 09:00–23:00 Eastern. Selected scope: '+', '.join(aggregate_scope(self.service.config))+'. Inspect original source ages.')
            return
        # Inventory activity is advisory: an empty odds response costs no credits
        # and explicitly retires old quotes for a sport between seasons/rounds.
        sports=list(aggregate_scope(self.service.config))
        requests=[dict(path='/v4/sports/'+SPORT_KEYS[sport]+'/odds',params=deepcopy(PARAMS)) for sport in sports]
        self.cycle_id=self.ledger.begin_cycle(self.service.ownership,requests)
        if self.cycle_id is None:return
        self.metrics['selected_scope']=list(aggregate_scope(self.service.config))
        self.metrics['active_scope']=list(self.active_sports)
        self.metrics['cycle_id']=self.cycle_id
        for sport,request in zip(sports,requests):
            self.permitted()
            response=await self.dispatch(request,POLICY.credits_per_batch)
            self.admit_response(response,sport)
        self.cycle_id=None

    def retain_diagnostic(self,response,sport,rejected=None):
        from .current_aggregate_admission import diagnostic
        value=diagnostic(response['body'],sport,response['received_at'],rejected or {})
        directory=self.ledger.directory/'diagnostics'
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        import json,tempfile
        data=json.dumps(value,sort_keys=True).encode()
        if len(data)>POLICY.response_bytes:raise QuotaStop('aggregate_diagnostic_bound')
        fd,name=tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(name,directory/(sport+'.json'))
        finally:
            from pathlib import Path
            Path(name).unlink(missing_ok=True)

    def admit_response(self,response,sport):
        # Retain safe replay context before attempting admission or committing.
        if not response.get('retained'):self.retain_diagnostic(response,sport)
        self.permitted() # Revocation forbids admission, independently of charge reconciliation.
        self.issue_context['sport']=sport
        states=deepcopy(self.service.states)
        due=self.ledger.snapshot()['next_due_at']
        from .current_aggregate_admission import admit_venues,market_exclusions
        exclusions=market_exclusions(response['body'])
        self.metrics.setdefault('unsupported_market_exclusions',{})[sport]=exclusions
        batches,rejected=admit_venues(response['body'],sport,response['received_at'])
        records=[r for batch in batches.values() for r in batch]
        if not response.get('retained'):self.retain_diagnostic(response,sport,rejected)
        if len(rejected)==2:
            self.ledger.pause('aggregate_admission_failed')
            raise QuotaStop('aggregate_admission_failed')
        for venue in ('novig','prophetx'):
            exists=any(r['quote']['venue']==venue for r in records)
            states[venue]=dict(state='unavailable' if venue in rejected else 'budget_delayed' if exists else 'not_offered',reason_code=rejected[venue] if venue in rejected else 'aggregate_observed' if exists else 'aggregate_offering_unobserved',
                reason='Response rejected: '+rejected[venue]+'. Previous valid inputs remain inspectable.' if venue in rejected else 'Shared aggregate batch received; source age and freshness eligibility remain separate.' if exists else 'No venue records observed in this sport batch.',
                received_at=response['received_at'],next_due_at=due)
        venue_states=deepcopy(states)
        self.sport_states[sport]={venue:deepcopy(states[venue]) for venue in ('novig','prophetx')}
        for venue in ('novig','prophetx'):
            observations=[(scope,values[venue]) for scope,values in self.sport_states.items()]
            healthy=any(value['reason_code']=='aggregate_observed' for _,value in observations)
            states[venue]=dict(state='budget_delayed' if healthy else states[venue]['state'],
                reason_code='aggregate_scope_observed' if healthy else states[venue]['reason_code'],
                reason='Selected scope: '+', '.join(aggregate_scope(self.service.config))+'. '+ '; '.join(scope+': '+value['reason'] for scope,value in observations),
                received_at=response['received_at'],next_due_at=due)
        self.service.sink.commit(dict(type='current_aggregate',source='the_odds_api',sport=sport,body=response['body'],received_at=response['received_at'],venue_states=venue_states),states)
        self.service.states=states
        self.service.observation('the_odds_api','admission',dict(sport=sport,quotes=len(records),venues=sorted({r['quote']['venue'] for r in records})))
        self.metrics.update(admitted_records=len(records),rejected_venues=len(rejected))
        for venue in ('novig','prophetx'):
            if venue in rejected:self.service.issue(venue,'malformed_source','aggregate_admission_failed')
            elif not any(r['quote']['venue']==venue for r in records):self.service.issue(venue,'offering_unobserved','aggregate_offering_unobserved')

    def restore_retained(self):
        # Reopening reuses recorded observations with their original clocks;
        # it neither dispatches nor renews freshness or quota observations.
        for sport in SPORTS:
            path=self.ledger.directory/'diagnostics'/(sport+'.json')
            if not path.exists():continue
            try:
                if path.stat().st_size>POLICY.response_bytes:raise ValueError('Retained response bound')
                value=json.loads(path.read_text())
                if value.get('schema')!='predict-redacted-aggregate-diagnostic-1' or value.get('sport')!=sport:raise ValueError('Retained response identity')
                response=dict(body=json.dumps(value['replay']).encode(),received_at=value['received_at'],retained=True)
                self.admit_response(response,sport)
            except (ValueError,KeyError,TypeError,QuotaStop):
                self.service.issue('the_odds_api','malformed_source','aggregate_retained_admission_failed')

    async def run(self):
        self.restore_retained()
        while not self.closed and self.service.dispatch:
            if not self.attended():return
            try:
                await self.step()
            except asyncio.CancelledError:raise
            except Exception as exc:
                code=str(exc) if isinstance(exc,QuotaStop) else 'aggregate_admission_failed'
                if code in ('bootstrap_budget_delayed','aggregate_budget_delayed','aggregate_outside_window'):
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
