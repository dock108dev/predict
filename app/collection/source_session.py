"""Unified source policy and aggregate worker for the shared session owner.

Inert settings never authorize networking. This version admits isolated loopback
transports or an exact separately approved native/aggregate source binding.
"""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import re
from app.collection.odds_http import OddsHTTP, HTTPPolicy, Budget, BudgetStop, utc, mock_endpoint
from app.reference.odds_bindings import BOOKS, period_binding, normalize_event
from app.reference.product import SPORT_KEYS, time
from app.reference.aggregate import bind, VERSION as MAPPING

VERSION = 'unified-source-session-1'
ROLES = dict(kalshi='native_comparison', polymarket_us='native_comparison',
             novig='aggregate_comparison', prophetx='aggregate_comparison',
             pinnacle='reference', draftkings='reference', betmgm='reference')


def normalize_native_scopes(value):
    """Canonical scope validation shared by aggregate and metadata-only specs."""
    native_scopes=deepcopy(value)
    if not isinstance(native_scopes,dict) or not native_scopes or set(native_scopes)-{'kalshi','polymarket_us'}:
        raise ValueError('Explicit native source scopes required')
    from .source_bindings import required_cells
    allowed_cells={(c['sport'],c['period'],c['family'],c['category']) for c in required_cells()}
    for source,scopes_for_source in native_scopes.items():
        if scopes_for_source=='required-63-v1':
            scopes_for_source=[{k:v for k,v in c.items() if k!='cell_id'} for c in required_cells()]
            native_scopes[source]=scopes_for_source
        if not isinstance(scopes_for_source,list) or not 1<=len(scopes_for_source)<=63:
            raise ValueError('Choose one to 63 canonical native cells per source')
        native_seen=set()
        for cell in scopes_for_source:
            if not isinstance(cell,dict) or set(cell)!={'sport','period','family','category'}:
                raise ValueError('Complete canonical native cell required')
            sport,period,family,category=(cell[k] for k in ('sport','period','family','category'))
            if any(type(v) is not str for v in (sport,period,family)) or sport not in SPORT_KEYS:
                raise ValueError('Unknown canonical native cell')
            if category is not None and type(category) is not str:raise ValueError('Unknown canonical native cell')
            key=(sport,period,family,category)
            if key not in allowed_cells:raise ValueError('Unknown canonical native cell')
            if key in native_seen:raise ValueError('Duplicate canonical native cell')
            native_seen.add(key)
    return native_scopes


def validate(value):
    from .acquisition_policy import STARTUP, policy as http_policy, validate_static
    startup=isinstance(value,dict) and value.get('quota_startup')==STARTUP
    required={'version','roles','scopes','refresh_seconds','stale_seconds','event_limit','http'} | ({'quota_startup','native_discovery'} if startup else {'quota_observed_at'})
    if not isinstance(value, dict) or set(value)-{'native_selection','native_scopes','correspondence_policy','max_cycles','coverage_policy'} != required:
        raise ValueError('Complete versioned source settings required; authority fields prohibited')
    value=deepcopy(value)
    if 'coverage_policy' in value and value['coverage_policy'] not in ('v1-missing-pairs-1','v1-counterpart-completion-1'):raise ValueError('Unknown coverage policy')
    if value['version'] != VERSION or value['roles'] != ROLES:
        raise ValueError('Source roles must preserve native, aggregate comparison and reference boundaries')
    if 'correspondence_policy' in value and value['correspondence_policy']!='source-correspondence-1':
        raise ValueError('Unknown source correspondence policy')
    if 'max_cycles' in value and (type(value['max_cycles']) is not int or not 1 <= value['max_cycles'] <= 3):
        raise ValueError('Acquisition cycles must be one to three')
    for k,lo,hi in (('refresh_seconds',1,300),('stale_seconds',1,3600),('event_limit',1,12)):
        if type(value[k]) is not int or not lo <= value[k] <= hi:raise ValueError('Invalid '+k)
    scopes=value['scopes']
    if not isinstance(scopes,list) or not 1<=len(scopes)<=6:raise ValueError('Choose one to six sports')
    seen=set()
    for scope in scopes:
        if not isinstance(scope,dict) or set(scope)!= {'sport','markets','event_ids'}:raise ValueError('Invalid source scope')
        sport=scope['sport']
        if sport not in SPORT_KEYS or sport in seen:raise ValueError('Unknown or duplicate sport')
        seen.add(sport)
        markets=scope['markets']
        if not isinstance(markets,list) or not 1<=len(markets)<=12 or len(set(markets))!=len(markets):raise ValueError('Invalid markets')
        if any(m not in ('h2h','spreads','totals') and not period_binding(sport,m) for m in markets):
            raise ValueError('Market mapping unavailable; unsupported cells remain in coverage')
        ids=scope['event_ids']
        if not isinstance(ids,list) or len(ids)>value['event_limit'] or len(set(ids))!=len(ids) or any(not isinstance(x,str) or not re.fullmatch('[A-Za-z0-9_-]{1,160}',x) for x in ids):raise ValueError('Invalid event selection')
    native=value.get('native_selection',{})
    if not isinstance(native,dict) or set(native)-{'kalshi','polymarket_us'}:raise ValueError('Invalid native selection')
    for selection in native.values():
        if not isinstance(selection,dict) or set(selection)!={'event_ids','market_ids'}:raise ValueError('Explicit native event and market selection required')
        for ids in selection.values():
            if not isinstance(ids,list) or len(ids)>100 or any(not isinstance(x,str) or not re.fullmatch('[A-Za-z0-9_.:-]{1,160}',x) for x in ids):raise ValueError('Invalid native identity selection')
    if 'native_scopes' in value:
        value['native_scopes']=normalize_native_scopes(value['native_scopes'])
    policy=http_policy(value)
    if policy.reserve_per_request < max(len(s['markets']) for s in scopes):raise ValueError('Credit reservation must cover all requested markets')
    if startup:validate_static(value)
    else:time(value['quota_observed_at'])
    return deepcopy(value)


def configure(spec, settings, endpoints, *, prepare_approved=False):
    settings=validate(settings)
    if spec.get('mode')!='mock' and not prepare_approved:raise ValueError('Unified real-source activation unavailable: fresh explicit source approval required')
    if spec.get('mode')=='real':
        from .venue_access import ENDPOINTS
        if not spec.get('native_sources') or endpoints!={**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'}:raise ValueError('Approved source endpoints and native configuration required')
    elif spec.get('mode')!='mock':raise ValueError('Unsupported source-session mode')
    if spec.get('two_source_qualification') or spec.get('supervised_profile'):raise ValueError('Consumed qualification policies cannot be extended')
    if spec.get('mode')=='mock':mock_endpoint(endpoints.get('aggregate',''))
    if not settings.get('quota_startup') and not 0 <= (datetime.now(timezone.utc)-time(settings['quota_observed_at'])).total_seconds() <= 60:
        raise ValueError('Fresh quota baseline required at explicit Start; saved settings are not quota authority')
    value=deepcopy(spec);value['source_session']=settings;value['reference_enabled']=False
    # New ordinary sessions use manual admission. Existing journals and sealed
    # approval specs are never retroactively rewritten.
    from .v1_comparison import REPAIR_POLICY as POLICY
    value.setdefault('v1_comparison_policy',POLICY)
    if value.get('native_sources'):
        for v in ('novig','prophetx'):
            value['native_sources'][v]=dict(state='disabled',selected=False)
    return value


def decode(receipt):
    from app.reference.odds_acquire import strict_json
    raw=base64.b64decode(receipt['body_b64'],validate=True)
    from hashlib import sha256
    if sha256(raw).hexdigest()!=receipt['body_sha256']:raise ValueError('Response digest mismatch')
    return raw,strict_json(raw)


class AggregateHTTP(OddsHTTP):
    """Reuse bounded capture, quota reconciliation and cancellation; no key loader."""
    def __init__(self, endpoint, policy, sink, *, real_key=None):
        super().__init__(endpoint,'pending',policy,sink,real_key=real_key,aggregate_authorized=real_key is not None)
        self.target=None
    def metadata(self):
        return deepcopy(self.target)
    def reservation_cost(self):
        if not getattr(self,'acquisition_settings',None):return self.policy.reserve_per_request
        from .acquisition_policy import request_cost
        return request_cost(self.acquisition_settings,self.target)


class AggregateWorker:
    def __init__(self, session):
        self.session=session;self.settings=validate(session.spec['source_session'])
        from .acquisition_policy import policy as http_policy, StartupBudget
        key=None;self.startup_error=None
        if session.spec['mode']=='real':
            if not getattr(session,'native_authorized',False):raise ValueError('Exact source approval required before credential resolution')
            # Reuse the existing optional Odds API environment handoff, at Start only.
            import os
            key=os.environ.get('ODDS_API_KEY')
            if not key:
                from .credential_handoff import existing_key
                from pathlib import Path
                try:key=existing_key(Path(__file__).resolve().parents[2])
                except (ValueError,OSError):key=None
            if not key:self.startup_error='Approved aggregate source credential unavailable'
        policy=http_policy(self.settings);self._budget=Budget(policy)
        self.http=None if self.startup_error else AggregateHTTP(session.endpoints['aggregate'],policy,self.capture,real_key=key)
        if self.http and self.settings.get('quota_startup'):
            self.http.budget=StartupBudget(policy)
            self.http.acquisition_settings=self.settings
        if self.http:self.http.before_dispatch=lambda request,accounting:self.emit('aggregate_dispatch',request=request,decision='reserved_dispatch_uncertain',attempt_consumed=True,accounting=accounting)
        self.health='idle';self.poll=0;self.failures={};self.unavailable_scopes=set();self.selected_events={};self.last_dispatch=None;self.counterpart_empty=set();self.counterpart_markets={}
    @property
    def budget(self):return self.http.budget if self.http else self._budget
    def emit(self,typ,**data):return self.session.emit('the_odds_api',dict(type=typ,**data))
    def capture(self,row):
        # Capture cancellation even after Stop; it is an audit receipt, never a price.
        if self.session.stop_event.is_set() and not self.session.persistence_error:
            self.session.save_observed(dict(row,source='the_odds_api',session_id=self.session.sid,observed_at=utc()))
        else:self.emit('aggregate_http',**{k:v for k,v in row.items() if k!='type'})
    def status(self,state,reason=None):
        self.health=state
        self.emit('aggregate_status',state=state,reason=reason,accounting=self.budget.snapshot(),poll=self.poll,event_failures=deepcopy(self.failures))
    async def request(self,path,params):
        if self.session.stop_event.is_set():raise asyncio.CancelledError()
        if self.settings.get('coverage_policy') in ('v1-missing-pairs-1','v1-counterpart-completion-1'):
            import time as wall
            if self.last_dispatch is not None:await self.session.pause(max(0,.5-(wall.monotonic()-self.last_dispatch)))
            if self.session.stop_event.is_set():raise asyncio.CancelledError()
            self.last_dispatch=wall.monotonic()
        self.http.target=dict(path=path,params=params)
        result=await self.http.request()
        if self.session.stop_event.is_set():raise asyncio.CancelledError()
        if self.budget.reason:raise BudgetStop(self.budget.reason)
        if not result['complete'] or result['status']!=200:
            raise ValueError('Incomplete or failed aggregate response')
        return result
    async def cycle(self,scope):
        sport=scope['sport'];key=SPORT_KEYS[sport]
        if self.settings.get('coverage_policy') in ('v1-missing-pairs-1','v1-counterpart-completion-1') and sport in self.selected_events:
            for event in self.selected_events[sport]:await self.event(scope,event)
            return
        self.status('discovering')
        receipt=await self.request('/v4/sports/'+key+'/events',dict(dateFormat='iso'))
        _,events=decode(receipt)
        if not isinstance(events,list) or len(events)>512:raise ValueError('Discovery bound or shape')
        ids=set();eligible=[]
        for event in events:
            if event.get('sport_key')!=key or not isinstance(event.get('id'),str) or not re.fullmatch('[A-Za-z0-9_-]{1,160}',event['id']) or event['id'] in ids:raise ValueError('Ambiguous discovery identity')
            ids.add(event['id'])
            if not all(isinstance(event.get(k),str) and event[k] for k in ('home_team','away_team')) or event['home_team']==event['away_team']:raise ValueError('Discovery participants missing')
            if time(event['commence_time'])>time(receipt['received_at']) and (not scope['event_ids'] or event['id'] in scope['event_ids']):eligible.append(event)
        from .v1_coverage import counterpart_rank
        eligible=sorted(eligible,key=lambda e:((counterpart_rank(e,getattr(self.session,'projection',None)) if self.settings.get('coverage_policy') else 1),time(e['commence_time']),e['id']))[:self.settings['event_limit']]
        if self.settings.get('coverage_policy') in ('v1-missing-pairs-1','v1-counterpart-completion-1'):self.selected_events[sport]=eligible
        self.emit('aggregate_inventory',sport=sport,event_ids=[e['id'] for e in eligible],discovery_sha256=receipt['body_sha256'],
                  missing_requested=sorted(set(scope['event_ids'])-ids),truncated=len(events)>len(eligible))
        if not eligible and 'max_cycles' in self.settings:
            self.unavailable_scopes.add(sport)
            self.emit('aggregate_scope_unavailable',sport=sport,reason='No eligible event; no repeat discovery in this bounded attempt')
        active={sport+':'+e['id'] for e in eligible}
        self.failures={k:v for k,v in self.failures.items() if not k.startswith(sport+':') or k in active}
        for event in eligible:
            event_key=sport+':'+event['id']
            try:
                await self.event(scope,event)
                self.failures.pop(event_key,None)
            except asyncio.CancelledError:raise
            except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                self.failures[event_key]='Incomplete, malformed or unsupported event response ('+type(exc).__name__+')'
                self.status('unavailable',self.failures[event_key])
            if self.budget.reason:raise BudgetStop(self.budget.reason)
        if self.failures:self.status('unavailable','Some event responses unavailable; valid independent observations retained')
    async def event(self,scope,event):
        sport=scope['sport'];key=SPORT_KEYS[sport]
        if self.session.spec.get('v1_comparison_policy')=='manual-comparison-2' and (sport,event['id']) in self.counterpart_markets:
            allowed=self.counterpart_markets[(sport,event['id'])]
            scope=dict(scope,markets=[m for m in scope['markets'] if m in allowed])
            if not scope['markets']:return
        self.status('receiving')
        response=await self.request('/v4/sports/'+key+'/events/'+event['id']+'/odds',
            dict(bookmakers=','.join(BOOKS),markets=','.join(scope['markets']),oddsFormat='decimal',dateFormat='iso',includeSids='true'))
        raw,body=decode(response)
        if not isinstance(body,dict) or any(body.get(k)!=event.get(k) for k in ('id','sport_key','home_team','away_team','commence_time')):raise ValueError('Odds/discovery identity changed')
        for book in body['bookmakers']:
            if any(m['key'] not in scope['markets'] for m in book['markets']):raise ValueError('Unrequested market')
        if self.settings.get('quota_startup'):
            returned={m['key'] for book in body['bookmakers'] for m in book['markets']}
            charged=int(dict(response['headers'])['x-requests-last'])
            if charged!=len(returned):
                self.budget.reason='quota_response_market_count_contradiction'
                raise BudgetStop(self.budget.reason)
        records=bind(normalize_event(raw,sport,response['received_at']))
        if len(records)>5000 or len(json.dumps(records).encode())>16*1024*1024:raise ValueError('Aggregate projection bound')
        projection=getattr(self.session,'projection',None)
        if projection:
            other=[r for r in projection.aggregates.values() if (r['original']['sport'],r['original']['source_event_id'])!=(sport,event['id'])]
            if len(other)+len(records)>5000 or len(json.dumps(other+records).encode())>16*1024*1024:raise ValueError('Aggregate resident bound')
        if self.session.stop_event.is_set():raise asyncio.CancelledError()
        if self.session.spec.get('v1_comparison_policy')=='manual-comparison-2':
            eligible={r['original']['market'] for r in records if r['role']=='aggregated_venue_observation' and not r['reasons'] and r.get('implied') is not None}
            self.counterpart_markets[(sport,event['id'])]=eligible
            omitted=sorted(set(scope['markets'])-eligible)
            if omitted:self.emit('aggregate_counterpart_unavailable',kind='game_markets',sport=sport,event_id=event['id'],markets=omitted,disposition='no_eligible_comparison_prices',next_poll='omitted; no documented update objective')
        self.emit('aggregate_snapshot',version=MAPPING,sport=sport,event_id=event['id'],records=records,
                  response_sha256=response['body_sha256'],received_at=response['received_at'],processing_at=utc(),poll=self.poll)
        self.status('connected')
    def counterpart_interest(self,kind,sport,records):
        if self.session.spec.get('v1_comparison_policy')!='manual-comparison-2':return
        if not any(r['role']=='aggregated_venue_observation' and not r['reasons'] and r.get('implied') is not None for r in records):
            self.counterpart_empty.add((kind,sport))
            self.emit('aggregate_counterpart_unavailable',kind=kind,sport=sport,disposition='no_eligible_comparison_prices',reference_only_retained=True,next_poll='omitted; no documented update objective')

    async def award(self,scope):
        from app.reference.odds_bindings import CHAMPIONSHIPS
        from app.reference.outrights import normalize
        sport=scope['sport']
        response=await self.request('/v4/sports/'+CHAMPIONSHIPS[sport]+'/odds',dict(bookmakers=','.join(BOOKS),markets='outrights',oddsFormat='decimal',dateFormat='iso'))
        raw,body=decode(response);records=bind(normalize(raw,sport,response['received_at']))
        expected=1 if body else 0
        if int(dict(response['headers'])['x-requests-last'])!=expected:
            self.budget.reason='award_quota_contradiction';raise BudgetStop(self.budget.reason)
        self.counterpart_interest('award',sport,records)
        self.emit('aggregate_award_snapshot',version=MAPPING,sport=sport,records=records,response_sha256=response['body_sha256'],received_at=response['received_at'],processing_at=utc(),poll=self.poll)
        self.status('connected')

    async def run(self):
        if self.startup_error:
            self.status('unavailable',self.startup_error)
            await self.session.stop_event.wait()
            return
        try:
            if self.settings.get('quota_startup'):
                self.status('quota_preflight')
                receipt=await self.request('/v4/sports',dict(all='true'))
                if self.budget.reason or self.budget.baseline_pending:
                    raise BudgetStop(self.budget.reason or 'fresh_quota_required')
                _,body=decode(receipt)
                if not isinstance(body,list):raise BudgetStop('malformed_quota_startup_response')
                self.emit('aggregate_quota_baseline',received_at=receipt['received_at'],response_sha256=receipt['body_sha256'],accounting=self.budget.snapshot())
            while not self.session.stop_event.is_set():
                if self.poll >= self.settings.get('max_cycles', 256):
                    self.status('completed','Explicit acquisition cycle cap reached')
                    return
                self.poll+=1
                for scope in self.settings['scopes']:
                    if self.settings.get('coverage_policy')=='v1-missing-pairs-1' and ('award',scope['sport']) not in self.counterpart_empty:
                        try:await self.award(scope)
                        except asyncio.CancelledError:raise
                        except (ValueError,KeyError,TypeError,ArithmeticError):self.status('unavailable','Award response unavailable; independent game work continues')
                    if scope['sport'] in self.unavailable_scopes:continue
                    try:await self.cycle(scope)
                    except asyncio.CancelledError:raise
                    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                        self.status('unavailable','Incomplete, malformed or unsupported aggregate response; inputs not refreshed ('+type(exc).__name__+')')
                    if self.budget.reason:raise BudgetStop(self.budget.reason)
                self.status('waiting' if self.health=='connected' else self.health)
                await self.session.pause(self.settings['refresh_seconds'])
        except BudgetStop as exc:self.status('unavailable',str(exc))
        except (ValueError,KeyError,TypeError,ArithmeticError):
            self.status('unavailable','Invalid startup quota response; no paid dispatch')
        except asyncio.CancelledError:raise
    async def aclose(self):
        if self.http:await self.http.aclose()


def verify_rows(rows):
    """Recompute admitted mappings from the same durable raw response, offline."""
    receipts={};snapshots=0;dispatches=0
    for row in rows:
        if row['type']=='aggregate_dispatch':dispatches+=1
        if row['type']=='aggregate_http':
            from hashlib import sha256
            raw=base64.b64decode(row['body_b64'],validate=True)
            if sha256(raw).hexdigest()!=row['body_sha256']:raise ValueError('Aggregate capture digest mismatch')
            if row.get('complete') and row.get('status')==200:receipts[(row['body_sha256'],row['received_at'])]=row
        if row['type']=='aggregate_award_snapshot':
            from app.reference.outrights import normalize
            receipt=receipts.get((row['response_sha256'],row['received_at']))
            if receipt is None:raise ValueError('Award lacks durable response')
            raw,_=decode(receipt)
            if bind(normalize(raw,row['sport'],row['received_at']))!=row['records']:raise ValueError('Award replay mismatch')
            snapshots+=1
        if row['type']=='aggregate_snapshot':
            receipt=receipts.get((row['response_sha256'],row['received_at']))
            if receipt is None:raise ValueError('Aggregate snapshot lacks durable response')
            raw,body=decode(receipt)
            if body['id']!=row['event_id'] or bind(normalize_event(raw,row['sport'],row['received_at']))!=row['records']:
                raise ValueError('Aggregate projection does not reproduce response')
            snapshots+=1
    return dict(version=VERSION,verified=True,snapshots=snapshots,dispatch_reservations=dispatches,
                qualification='Offline raw response and mapping replay; no source semantics inferred')


def filter_native_catalog(catalog, source, settings):
    """Selection uses existing normalized identities; it never adds discovery keys."""
    from app.dashboard.session_projection import identity
    selection=settings.get('native_selection',{}).get(source,{})
    if 'native_scopes' in settings:
        wanted={(c['sport'],c['family'],c['period'],c['category'])
                for c in normalize_native_scopes(settings['native_scopes']).get(source,[])}
        events={e['id']:e for e in catalog['events']}
        for market in catalog['markets']:
            event=events.get(market['event_id'])
            if not event:continue
            if event.get('exclusion') or event.get('identity')!='resolved':
                market['exclusion']=market.get('exclusion') or 'Unresolved native event identity'
                continue
            ident=identity(event,market)
            key=(ident['competition'],ident['family'],ident['period'],ident['category'])
            excluded=(key not in wanted or
                bool(selection.get('event_ids')) and event['id'] not in selection['event_ids'] or
                bool(selection.get('market_ids')) and market['id'] not in selection['market_ids'])
            if excluded:market['exclusion']=market.get('exclusion') or 'Outside explicit native source cell selection'
        return catalog
    wanted=set()
    for scope in settings['scopes']:
        for key in scope['markets']:
            binding=period_binding(scope['sport'],key)
            base=binding['base'] if binding else key
            wanted.add((scope['sport'],{'h2h':'moneyline','h2h_3_way':'moneyline','spreads':'spread','totals':'total'}[base],binding['period'] if binding else 'full_game'))
    events={e['id']:e for e in catalog['events']}
    for market in catalog['markets']:
        event=events.get(market['event_id'])
        if not event:continue
        if event.get('exclusion') or event.get('identity')=='unresolved':
            market['exclusion']=market.get('exclusion') or 'Unresolved native event identity'
            continue
        ident=identity(event,market)
        excluded=((ident['competition'],ident['family'],ident['period']) not in wanted or
            bool(selection.get('event_ids')) and event['id'] not in selection['event_ids'] or
            bool(selection.get('market_ids')) and market['id'] not in selection['market_ids'])
        if excluded:market['exclusion']=market.get('exclusion') or 'Outside explicit source-session selection'
    return catalog
