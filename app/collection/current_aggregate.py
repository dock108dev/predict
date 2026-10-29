"""One running-app aggregate scheduler under CurrentService ownership."""
import asyncio
from .current_ingress import operation, call
from .bulk_checkpoint import owned_thread
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
from .current_policy import ROOT, aggregate_scope, aggregate_requests
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
        self.response_receipt=None
        self.phase="idle"

    async def request(self, request, key):
        if self.closed: raise QuotaStop('aggregate_transport_closed')
        self.response_receipt=None
        self.phase='request_start'
        if self.client is None:
            trace=aiohttp.TraceConfig()
            def phase(name):
                async def record(*args):self.phase=name
                return record
            trace.on_connection_create_start.append(phase('connection'))
            trace.on_dns_resolvehost_start.append(phase('dns'))
            trace.on_dns_resolvehost_end.append(phase('connection'))
            trace.on_connection_create_end.append(phase('awaiting_headers'))
            self.client=aiohttp.ClientSession(auto_decompress=False,trust_env=False,
                trace_configs=[trace],connector=aiohttp.TCPConnector(limit=1,force_close=True),timeout=aiohttp.ClientTimeout(total=POLICY.timeout_seconds),
                read_bufsize=4096,max_line_size=4096,max_field_size=4096)
            self.client._retry_connection=False
        async with self.client.get(BASE+request['path'],params={**request['params'],'apiKey':key},
                allow_redirects=False,headers={'Accept-Encoding':'identity'}) as response:
            headers=[(k.lower(),v) for k,v in response.headers.items() if k.lower() in ('x-requests-used','x-requests-remaining','x-requests-last')]
            # Headers arrive before the body. Keep only bounded quota metadata
            # so cancellation/body failure cannot lose received charge evidence.
            safe=[(k,v if len(v)<=12 and v.isascii() and v.isdigit() else 'invalid') for k,v in headers]
            self.response_receipt=dict(status=response.status,headers=safe,received_at=now())
            self.phase="body"
            body=bytearray()
            async for chunk in response.content.iter_chunked(4096):
                self.bytes+=len(chunk)
                if len(body)+len(chunk)>POLICY.response_bytes or self.bytes>POLICY.cycle_bytes:raise QuotaStop('aggregate_response_byte_cap')
                body.extend(chunk)
            if response.headers.get('Content-Encoding','identity')!='identity':raise QuotaStop('aggregate_encoding_unsupported')
            raw=bytes(body)
            import json
            from urllib.parse import unquote
            from .current_aggregate_admission import parse_frame
            parsed_frame=None;parse_error=False
            try:
                parsed_frame=parse_frame(raw)
                decoded=json.dumps(parsed_frame.payload,ensure_ascii=False)
            except (ValueError,UnicodeError,RecursionError):
                parse_error=True;decoded=raw.decode('utf-8',errors='replace')
            for _ in range(3):decoded=unquote(decoded)
            if key in decoded or 'apikey' in decoded.lower() or 'api_key' in decoded.lower():raise QuotaStop('aggregate_secret_echo_suppressed')
            if any(secret in raw for secret in (key.encode(),base64.b64encode(key.encode()),quote(key).encode())):
                raise QuotaStop('aggregate_secret_echo_suppressed')
            self.phase="complete"
            # Return header values only if bounded; never provider error body text.
            return dict(status=response.status,headers=safe,body=raw if response.status==200 else b'',received_at=now(),parsed_frame=parsed_frame,parse_error=parse_error)

    async def close(self):
        self.closed=True
        if self.client:await self.client.close()


def check_account_binding(ledger, window_loader):
    audits=ledger._read().get('conservative_recoveries',[])
    if not audits:return
    from .current_account_recovery import credential_binding
    actual=credential_binding()
    if actual!=audits[-1]['evidence']['credential_binding']:
        ledger.pause('recovery_credential_changed');raise QuotaStop('recovery_credential_changed')
    metadata=json.loads((ROOT/'.local/predict-odds-account.json').read_text())
    if metadata['account_id']!=audits[-1]['account_id'] or window_loader()!=audits[-1]['window']:
        ledger.pause('recovery_context_mismatch');raise QuotaStop('recovery_context_mismatch')


class AggregateScheduler:
    def __init__(self, service, *, ledger=None, transport=None, key_loader=credential, window_loader=load_window, qualification=None):
        self.service=service
        self.ledger=ledger or QuotaLedger()
        self.process_accounting=bool(ledger is None and getattr(service,'database_mode',False))
        self.accounting_process=None
        self.transport=transport or CurrentOddsTransport()
        self.key_loader=key_loader;self.window_loader=window_loader
        self.qualification=deepcopy(qualification)
        self.closed=False;self.key=None;self.active_sports=[];self.bootstrapped=False
        self.metrics=dict(requests=0,bootstrap_requests=0,batches=0,worst_case_credits=0,body_bytes=0,
            accounting_isolation='process' if self.process_accounting else 'joined_thread')
        self.issue_context={}
        self.phase='idle';self.next_check_at=None;self.quota_next_due_at=...
        self.cycle_id=None;self.cycle_requests=0;self.cycle_credits=0;self.sport_states={};self.prepared=False;self.manual=False;self.acquisition_lock=asyncio.Lock()
        self.wall=time.time();self.monotonic=__import__('app.collection.current_clock',fromlist=['continuous']).continuous()

    def check_account_binding(self):
        return check_account_binding(self.ledger,self.window_loader)

    async def accounting(self,method,*args,result=None,**kwargs):
        if self.process_accounting:
            if self.accounting_process is None:
                from .accounting_process import AccountingProcess
                self.accounting_process=AccountingProcess(self.ledger,self.service.ownership)
            return await self.accounting_process.call(method,*args,result=result,**kwargs)
        if method=='snapshot':return await owned_thread(self.ledger.snapshot)
        if method=='check_binding':return await owned_thread(self.check_account_binding)
        if method=='account_response':return await owned_thread(self.account_response,*args)
        def operation():
            if method in ('reserve','prepare_clock'):value=getattr(self.ledger,method)(self.service.ownership,*args,**kwargs)
            else:value=getattr(self.ledger,method)(*args,self.service.ownership,**kwargs)
            if result is not None:result['id']=value
            return value
        return await owned_thread(operation)

    async def quota_snapshot(self):
        # Read-only scheduler projection is CPU-heavy for a full attempt ledger.
        # Keep it off the socket loop; reservation still reloads/rechecks under
        # the original owner lock immediately before every dispatch.
        value=await self.accounting('snapshot')
        if self.ledger.failed:value=dict(value,pause=self.ledger.failed)
        self.quota_next_due_at=value.get('next_due_at')
        return value

    def quota_due(self):
        # Due time is a display fact, never acquisition authority. Synchronous
        # controlled callers retain their original fallback; live dispatch has
        # already obtained this value from strict receipt accounting.
        return self.ledger.snapshot().get('next_due_at') if self.quota_next_due_at is ... else self.quota_next_due_at

    def attended(self):
        return self.service.store is not None and not self.service.store.closed

    def permitted(self):
        if self.closed or not self.service.dispatch or self.service.ownership.file is None or time.monotonic()>=self.service.deadline:
            raise QuotaStop('aggregate_dispatch_revoked')
        elapsed=__import__('app.collection.current_clock',fromlist=['continuous']).continuous()-self.monotonic
        if abs((time.time()-self.wall)-elapsed)>120:
            self.ledger.pause('clock_jump');raise QuotaStop('clock_jump')

    @operation
    def state(self, state, code, reason):
        svc=self.service
        if svc.store is None or svc.store.closed:return
        states=deepcopy(svc.states)
        from .current_schedule import schedule
        plan=schedule(now())
        due=plan['next_due_at'] if not plan['open'] else self.quota_due()
        if due and not schedule(due)['open']:due=schedule(due)['next_due_at']
        for venue in ('novig','prophetx'):
            # After exact accounting recovery, the old transport hold is no
            # longer the current cause. Preserve offering/admission failures,
            # but show the scheduled wait instead of a cleared accounting hold.
            if (code=='aggregate_budget_delayed' and states[venue]['state'] in ('not_offered','unavailable')
                    and states[venue].get('reason_code') not in
                    ('aggregate_transport_uncertain','ambiguous_dispatch_unresolved')):
                states[venue]['next_due_at']=due
                continue
            scoped='; '.join(scope+': '+values[venue]['reason'] for scope,values in self.sport_states.items())
            states[venue]=dict(state=state,reason_code=code,reason=reason+(' '+scoped if scoped else ''),next_due_at=due)
        if states==svc.states:return
        (yield (svc.row('source_health','the_odds_api',state=state), states))
        svc.states=states

    async def dispatch(self, request, cost, *, bootstrap=False):
        self.phase='scheduled_admission'
        self.permitted()
        await self.accounting('check_binding')
        self.permitted()
        if getattr(self.service,'database_mode',False):
            from .alternate_acquisition import check_expiry
            check_expiry(now())
        from .current_schedule import schedule
        if not self.manual and not schedule(now())['open']:raise QuotaStop('aggregate_outside_window')
        from .alternate_acquisition import authority
        grant=authority(now()) if self.cycle_id and not self.manual and getattr(self.service,'database_mode',False) else None
        request_limit=12+(grant['credits_per_cycle']-18)//2 if grant else POLICY.requests_per_cycle
        if self.cycle_requests>=request_limit or self.cycle_credits+cost>(grant['credits_per_cycle'] if grant else POLICY.worst_case_credits_per_cycle):
            raise QuotaStop('aggregate_runtime_envelope_consumed')
        # Seal exact request/candidate/cost durably before loading secrets.
        self.phase='reservation'
        reservation={}
        try:
            aid=await self.accounting('reserve',self.service.digest,request,cost,
                bootstrap=bootstrap,qualification=self.qualification,cycle_id=self.cycle_id,result=reservation)
            self.issue_context=dict(attempt_id=aid,charged_credits=None,endpoint_class='sports_bootstrap' if bootstrap else 'sport_odds')
            sport=next((s for s,k in SPORT_KEYS.items() if request['path']=='/v4/sports/'+k+'/odds'),None)
            if sport:self.issue_context['sport']=sport
            self.service.observation('the_odds_api','reservation',dict(attempt_id=aid,request=request,worst_case_credits=cost))
            if self.key is None:self.key=self.key_loader()
            self.permitted()
            await self.accounting('dispatched',aid)
            # Last synchronous gate remains immediately before transport entry.
            # A cancellation before here joins the marker and records positive
            # local evidence that no request task was ever created.
            self.permitted()
        except (Exception,asyncio.CancelledError):
            if reservation.get('id'):
                await self.accounting('cancel_before_transport',reservation['id'])
            raise
        self.cycle_requests+=1;self.cycle_credits+=cost
        self.metrics['requests']+=1;self.metrics['worst_case_credits']+=cost
        if bootstrap:self.metrics['bootstrap_requests']+=1
        else:self.metrics['batches']+=1
        async def send_once():
            self.permitted()
            return await self.transport.request(request,self.key)
        request_task=asyncio.create_task(send_once())
        try:
            tick=time.perf_counter()
            self.metrics['request_started_at']=now()
            self.phase='transport'
            response=await asyncio.shield(request_task)
            self.metrics['http_response_ms']=(time.perf_counter()-tick)*1000
            self.metrics['last_received_at']=response['received_at']
        except asyncio.CancelledError:
            # Stop has already revoked publication and future dispatch. Give only
            # this existing request a bounded chance to deliver charge headers.
            # No retry, new request or post-Stop price admission is permitted.
            response=None
            if getattr(self.transport,'response_receipt',None) is None:
                try:
                    response=await asyncio.wait_for(asyncio.shield(request_task),
                        timeout=min(2,self.service.config['cleanup_seconds']/2))
                except Exception:pass
            if not request_task.done():request_task.cancel()
            await asyncio.gather(request_task,return_exceptions=True)
            self.retain_interrupted_response(aid,'aggregate_cancelled_after_dispatch',receipt=response)
            # No receipt leaves the durable marker uncertain. Never refund it.
            raise
        except Exception as exc:
            from .current_transport_diagnostics import exception_kind
            phase=getattr(self.transport,'phase',None)
            diagnostic=dict(**exception_kind(exc),elapsed_seconds=round(time.perf_counter()-tick,6),
                transport_phase=phase if phase in ('idle','request_start','dns','connection',
                    'awaiting_headers','body','complete') else 'unknown')
            self.metrics['last_transport_failure']=diagnostic
            self.retain_interrupted_response(aid,'aggregate_transport_uncertain',diagnostic=diagnostic)
            self.service.observation('the_odds_api','response',dict(attempt_id=aid,status=None,reason='aggregate_transport_uncertain'))
            self.coverage_failure(sport)
            raise QuotaStop('aggregate_transport_uncertain') from None
        self.metrics['last_quota_headers']=deepcopy(response['headers'])
        self.phase='accounting'
        charged,q=await self.accounting('account_response',aid,
            {k:response[k] for k in ('status','headers','received_at')})
        self.issue_context['charged_credits']=charged
        self.quota_next_due_at=q.get('next_due_at')
        self.metrics['body_bytes']+=len(response['body'])
        self.metrics['last_body_sha256']=sha256(response['body']).hexdigest()
        self.service.observation('the_odds_api','response',dict(attempt_id=aid,status=response['status'],
            request=request,headers=response['headers'],received_at=response['received_at'],body_bytes=len(response['body']),body_sha256=sha256(response['body']).hexdigest()))
        if q['pause']:raise QuotaStop(q['pause'])
        if response['status']!=200:
            self.coverage_failure(sport,response['received_at'])
            code='aggregate_rate_limit' if response['status']==429 else 'aggregate_authentication' if response['status'] in (401,403) else 'aggregate_http_failure'
            # No blind retry; preserve next-due and pause this runtime.
            raise QuotaStop(code)
        return response

    def account_response(self,aid,response):
        """Join strict durable receipt accounting without blocking socket reads."""
        self.ledger.reconcile(aid,response['headers'],received_at=response['received_at'])
        self.ledger.record_response(aid,response)
        charged=self.ledger._read()['attempts'][aid].get('charged')
        return charged,self.ledger.snapshot()

    def retain_interrupted_response(self, aid, reason, *, receipt=None, diagnostic=None):
        receipt=receipt or getattr(self.transport,'response_receipt',None)
        if receipt is not None:
            self.ledger.reconcile(aid,receipt['headers'],received_at=receipt['received_at'])
            self.metrics['last_quota_headers']=deepcopy(receipt['headers'])
            self.issue_context['charged_credits']=self.ledger._read()['attempts'][aid].get('charged')
        self.ledger.record_response(aid,receipt,interruption=reason,diagnostic=diagnostic)
        self.service.observation('the_odds_api','interrupted_response',dict(attempt_id=aid,reason=reason,receipt=deepcopy(receipt)))

    def coverage_failure(self,sport,checked_at=None):
        if sport and hasattr(self.service,'coverage'):
            for venue in ('novig','prophetx','pinnacle'):
                self.service.coverage.observe(sport,venue,checked_at=checked_at or now(),
                    status='failed_source',reason='source_failed')

    async def step(self):
        async with self.acquisition_lock:await self.scheduled_step()

    async def refresh(self,sports,identity,reference=False):
        if self.acquisition_lock.locked():raise QuotaStop('aggregate_refresh_in_progress')
        async with self.acquisition_lock:
            self.permitted()
            try:requests=aggregate_requests(self.service.config,sports)
            except ValueError as exc:raise QuotaStop(str(exc)) from None
            quota=await self.quota_snapshot()
            if quota['pause']:raise QuotaStop(quota['pause'])
            self.ledger.bind_window(self.window_loader())
            self.cycle_requests=0;self.cycle_credits=0;self.transport.bytes=0
            self.cycle_id=self.ledger.begin_manual_cycle(self.service.ownership,requests,identity)
            self.manual=True
            self.metrics['manual_scope']=list(sports)
            self.metrics['manual_refresh_id']=identity
            try:
                responses=[]
                for sport,request in zip(sports,requests):
                    response=await self.dispatch(request,POLICY.credits_per_batch)
                    responses.append((sport,response))
                errors=[]
                for sport,response in responses:
                    try:await call(self.service, self.admit_response, response, sport)
                    except QuotaStop as exc:errors.append(exc)
                if errors:raise errors[0]
            except QuotaStop as exc:
                await call(self.service, self.state, 'unavailable', str(exc), 'On-demand aggregate refresh stopped: '+str(exc).replace('_',' ')+'. Inspect current status for each native worker.')
                self.service.issue('the_odds_api','quota_or_source',str(exc))
                raise
            finally:self.manual=False;self.cycle_id=None

    async def scheduled_step(self):
        self.next_check_at=None
        self.phase='scheduled_admission'
        self.permitted()
        await self.accounting('check_binding')
        self.permitted()
        if getattr(self.service,'database_mode',False):
            from .alternate_acquisition import check_expiry
            check_expiry(now())
        # Restore locally proved clock continuity even outside collection hours.
        # This performs no transport and never changes the persisted due times.
        restore_inventory=not self.prepared
        if restore_inventory:
            evidence=self.window_loader()
            await self.accounting('prepare_clock',self.service.digest,evidence,
                cleanup_safe=not self.service.closing and not self.service.closed and not self.service.cleanup_errors)
            await owned_thread(self.ledger.bind_window,evidence)
            self.prepared=True
        from .current_schedule import schedule
        plan=schedule(now())
        if not plan['open']:
            self.next_check_at=plan['next_due_at']
            self.phase='waiting_for_cycle'
            await call(self.service, self.state, 'budget_delayed', 'aggregate_outside_window', 'Aggregate paused outside 09:00–23:00 Eastern; next cycle '+plan['next_due_at']+'. Scope: '+', '.join(aggregate_scope(self.service.config))+'.')
            return
        self.cycle_requests=0;self.cycle_credits=0;self.transport.bytes=0
        quota=None
        if restore_inventory:
            quota=await self.quota_snapshot();inventory=quota.get('sports_inventory')
            if (inventory and inventory['account_id']==quota.get('account_id') and quota['observation'] is not None
                and 0<=(stamp(now())-stamp(inventory['at'])).total_seconds()<POLICY.inventory_seconds
                and (quota['accounting_epoch'] is None or quota['accounting_epoch']['state']=='current')):
                self.active_sports=[s for s in aggregate_scope(self.service.config) if SPORT_KEYS[s] in inventory['active']]
                self.bootstrapped=True
        if quota is None:quota=await self.quota_snapshot()
        inventory=quota.get('sports_inventory')
        if self.bootstrapped and inventory and (stamp(now())-stamp(inventory['at'])).total_seconds()>=POLICY.inventory_seconds:self.bootstrapped=False
        if not self.bootstrapped:
            response=await self.dispatch(dict(path='/v4/sports',params={}),0,bootstrap=True)
            from .current_aggregate_admission import parse_frame
            if response.get('parse_error'):raise QuotaStop('aggregate_bootstrap_schema')
            sports=(response.get('parsed_frame') or parse_frame(response['body'])).payload
            if not isinstance(sports,list) or len(sports)>512 or any(not isinstance(x,dict) or not isinstance(x.get('key'),str) or type(x.get('active')) is not bool for x in sports):
                raise QuotaStop('aggregate_bootstrap_schema')
            available={x['key'] for x in sports if x['active'] and x.get('has_outrights') is False}
            self.ledger.record_sports([k for k in available if k in SPORT_KEYS.values()])
            self.active_sports=[s for s in aggregate_scope(self.service.config) if SPORT_KEYS[s] in available]
            self.bootstrapped=True
            quota=await self.quota_snapshot()
        if quota['pause']:raise QuotaStop(quota['pause'])
        if quota['reset'] is None:raise QuotaStop('reset_window_unknown')
        if quota['next_due_at'] and stamp(now())<stamp(quota['next_due_at']) and (self.qualification is None or self.metrics['batches']>0):
            self.next_check_at=quota['next_due_at']
            self.phase='waiting_for_cycle'
            await call(self.service, self.state, 'budget_delayed', 'aggregate_budget_delayed', 'Shared aggregate cycle every 15 minutes, 09:00–23:00 Eastern. Selected scope: '+', '.join(aggregate_scope(self.service.config))+'. Inspect original source ages.')
            return
        # Inventory activity is advisory: an empty odds response costs no credits
        # and explicitly retires old quotes for a sport between seasons/rounds.
        sports=list(aggregate_scope(self.service.config))
        requests=aggregate_requests(self.service.config)
        self.cycle_id=self.ledger.begin_cycle(self.service.ownership,requests)
        if self.cycle_id is None:return
        self.metrics['selected_scope']=list(aggregate_scope(self.service.config))
        self.metrics['active_scope']=list(self.active_sports)
        self.metrics['cycle_id']=self.cycle_id
        for sport,request in zip(sports,requests):
            self.permitted()
            response=await self.dispatch(request,POLICY.credits_per_batch)
            await call(self.service, self.admit_response, response, sport)
        from .alternate_acquisition import acquire
        if getattr(self.service,'database_mode',False):await acquire(self,sports)
        self.cycle_id=None

    @operation
    def admit_response(self,response,sport):
        # One decoded exact frame supplies admission, references and coverage.
        self.permitted() # Revocation forbids admission, independently of charge reconciliation.
        self.issue_context['sport']=sport
        states=deepcopy(self.service.states)
        due=self.quota_due()
        from .current_aggregate_admission import admit_venues,market_exclusions,parse_frame
        self.phase='decoding'
        if response.get('parse_error'):raise ValueError('aggregate_json_invalid')
        frame=response.get('parsed_frame') or parse_frame(response['body'])
        self.phase='normalization'
        exclusions=market_exclusions(response['body'],frame=frame)
        self.metrics.setdefault('unsupported_market_exclusions',{})[sport]=exclusions
        batches,rejected=admit_venues(response['body'],sport,response['received_at'],frame=frame,include_reference=True)
        records=[r for venue,batch in batches.items() if venue!='pinnacle' for r in batch]
        for venue in ('novig','prophetx'):
            exists=any(r['quote']['venue']==venue for r in records)
            states[venue]=dict(state='budget_delayed' if exists else 'unavailable' if venue in rejected else 'not_offered',
                reason_code='aggregate_partial_admission' if exists and venue in rejected else rejected[venue] if venue in rejected else 'aggregate_observed' if exists else 'aggregate_offering_unobserved',
                reason='Independent valid markets admitted; rejected markets: '+rejected[venue]+'. Previous valid inputs remain inspectable.' if exists and venue in rejected else 'Response rejected: '+rejected[venue]+'. Previous valid inputs remain inspectable.' if venue in rejected else 'Shared aggregate batch received; source age and freshness eligibility remain separate.' if exists else 'No venue records observed in this sport batch.',
                received_at=response['received_at'],next_due_at=due)
        venue_states=deepcopy(states)
        self.sport_states[sport]={venue:deepcopy(states[venue]) for venue in ('novig','prophetx')}
        for venue in ('novig','prophetx'):
            observations=[(scope,values[venue]) for scope,values in self.sport_states.items()]
            healthy=any(value['reason_code'] in ('aggregate_observed','aggregate_partial_admission') for _,value in observations)
            states[venue]=dict(state='budget_delayed' if healthy else states[venue]['state'],
                reason_code='aggregate_scope_observed' if healthy else states[venue]['reason_code'],
                reason='Selected scope: '+', '.join(aggregate_scope(self.service.config))+'. '+ '; '.join(scope+': '+value['reason'] for scope,value in observations),
                received_at=response['received_at'],next_due_at=due)
        self.phase='database_ingress'
        if getattr(self.service,'database',None) is not None:
            complete=[venue for venue in batches if venue not in rejected]
            records.extend(batches.get('pinnacle',[]))
            (yield (dict(type='current_aggregate_records',source='the_odds_api',sport=sport,
                records=records,complete_venues=complete,received_at=response['received_at'],raw_payload=frame.payload), states))
        else:
            (yield (dict(type='current_aggregate',source='the_odds_api',sport=sport,body=response['body'],received_at=response['received_at'],venue_states=venue_states), states))
        self.phase='offered_inventory'
        if hasattr(self.service,'coverage'):
            from app.comparison.coverage import aggregate_observation
            aggregate_observation(self.service.coverage,response['body'],sport,response['received_at'],rejected,parsed_frame=frame,records=records,
                started_at=self.metrics.get('request_started_at'),query=aggregate_requests(self.service.config,[sport])[0],admitted_at=now())
        self.phase='admitted'
        self.service.states=states
        self.service.observation('the_odds_api','admission',dict(sport=sport,quotes=len(records),venues=sorted({r['quote']['venue'] for r in records})))
        self.metrics.update(admitted_records=len(records),rejected_venues=len(rejected))
        for venue in ('novig','prophetx'):
            if venue in rejected:self.service.issue(venue,'malformed_source','aggregate_admission_failed')
            elif not any(r['quote']['venue']==venue for r in records):self.service.issue(venue,'offering_unobserved','aggregate_offering_unobserved')

    def restore_retained(self):
        # Reopening never imports diagnostics. Original current rows remain in SQL.
        return

    async def run(self):
        self.restore_retained()
        while not self.closed and self.service.dispatch:
            if not self.attended():return
            try:
                await self.step()
            except asyncio.CancelledError:raise
            except Exception as exc:
                from app.diagnostics import failure
                failure(__name__, 'aggregate_'+self.phase, exc)
                self.metrics['last_processing_failure']=dict(phase=self.phase,
                    exception_class=type(exc).__name__,runtime_id=self.service.runtime_id,
                    attempt_id=self.issue_context.get('attempt_id'),sport=self.issue_context.get('sport'),
                    received_at=self.metrics.get('last_received_at'),receipt_sha256=self.metrics.get('last_body_sha256'))
                from .odds_http import BudgetStop
                storage_codes={'current_observation_storage_cap','current_observation_record_cap','current_observation_incomplete_tail',
                    'current_observation_manifest_corrupt','current_observation_integrity_failed',
                    'current_observation_disk_free_floor','current_observation_segment_cap'}
                code=str(exc) if isinstance(exc,QuotaStop) or isinstance(exc,BudgetStop) and str(exc) in storage_codes else 'aggregate_admission_failed'
                if code in ('bootstrap_budget_delayed','aggregate_budget_delayed','aggregate_outside_window'):
                    await call(self.service, self.state, 'budget_delayed', 'aggregate_budget_delayed', 'Shared aggregate delivery waits for its persisted due time.')
                    await asyncio.sleep(1)
                    continue
                await call(self.service, self.state, 'unavailable', code, 'Aggregate acquisition paused: '+code.replace('_',' ')+'. Inspect current status for each native worker.')
                # Preserve independent failures across recovery/reopening. An
                # unresolved request already blocks through exact eligibility.
                if code!='ambiguous_dispatch_unresolved' and not (await self.quota_snapshot()).get('pause'):
                    self.ledger.pause(code)
                self.service.issue('the_odds_api','quota_or_source',code)
                return
            # Idle scheduling need not deserialize and validate the entire
            # ledger every second. Dispatch still rechecks every guard; Stop
            # cancels this sleep and manual refresh owns its existing lock.
            await asyncio.sleep(self.idle_delay())

    def idle_delay(self):
        if self.next_check_at is None:return 1
        return max(.05,min(30,(stamp(self.next_check_at)-stamp(now())).total_seconds()))

    async def close(self):
        self.closed=True
        await self.transport.close()
        if self.accounting_process:await self.accounting_process.close()
        self.key=None
