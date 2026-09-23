"""Isolated one-event policy over ordinary native collection and product history."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import time
from app.collection import coverage
from app.collection.continuous import ContinuousSession, Discovery, REST, endpoints_for, now, rss, LIMITS
from app.collection.odds_http import BudgetStop
from app.collection.two_source_policy import POLICY, validate
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.e6_live import save_json


def individual_game(event):
    """Require native game ID plus the native full-game-winner taxonomy, never title guessing."""
    native=event.get('_native',{})
    gid=native.get('gameId')
    valid_id=type(gid) is int and gid>0 or isinstance(gid,str) and gid.isdigit() and int(gid)>0
    markets=native.get('markets',[])
    return bool(valid_id and isinstance(markets,list) and any(
        isinstance(m,dict) and m.get('sportsMarketType')==POLICY['us_event_filter'] for m in markets))


def restrict_games(cats):
    for event in cats['polymarket_us']['events']:
        if not individual_game(event):event['exclusion']='not_native_individual_nfl_winner_game'
    return cats


def failure_reason(exc):
    if isinstance(exc,TimeoutError):return 'discovery_deadline'
    if isinstance(exc,BudgetStop):return str(exc)
    if isinstance(exc,BaseExceptionGroup):
        for child in exc.exceptions:
            reason=failure_reason(child)
            if reason!='bounded_discovery_failed':return reason
    return 'bounded_discovery_failed'


def choose_event(cats, at):
    """Exact schedule and independently normalized participants; reject ambiguity."""
    coverage.match_catalogs(cats)
    candidates=[]
    for k in cats['kalshi']['events']:
        if k['competition']!='NFL' or k['identity']!='resolved' or k['exclusion'] or k['matching_status']!='matched':continue
        if coverage.stamp(k['scheduled_start'])<=at+timedelta(seconds=POLICY['kickoff_margin_seconds']):continue
        peers=[p for p in cats['polymarket_us']['events'] if p['id'] in k['counterpart_event_ids'] and p['competition']=='NFL' and p['identity']=='resolved' and not p['exclusion'] and p['matching_status']=='matched']
        if len(peers)==1:candidates.append((k,peers[0]))
    if not candidates:raise BudgetStop('no_compatible_shared_pregame_event')
    k,p=min(candidates,key=lambda pair:(pair[0]['scheduled_start'],pair[0]['id'],pair[1]['id']))
    return dict(kalshi=k['id'],polymarket_us=p['id'],scheduled_start=k['scheduled_start'],
                participants=sorted(k['participants'].values()),basis='Exact UTC schedule and independently resolved NFL participants; market rules/economics not inferred')


class QualificationDiscovery(Discovery):
    def __init__(self,session):
        super().__init__(session);self.failure=None;self.traversals={}

    async def pages_for(self, venue, path, query, field, size):
        client=self.clients[venue];cursor='';seen=set();ids=set();result=[]
        traversal=dict(pages=0,rows=0,state='pending');self.traversals[venue+'/'+field]=traversal
        maximum=POLICY['event_pages'] if field=='events' else POLICY['market_pages']
        for page in range(maximum):
            pagination=dict(limit=POLICY['page_size'],**({'cursor':cursor} if venue=='kalshi' else {'offset':page*POLICY['page_size']}))
            response=await client.get(endpoints_for(self.session)[venue]['rest']+path,{**query,**pagination})
            if response.status_code!=200:raise BudgetStop('catalog_http_'+str(response.status_code))
            data=response.json();rows=data.get(field)
            if not isinstance(rows,list) or len(rows)>POLICY['page_size']:raise BudgetStop('catalog_page_scope_exceeded')
            native_ids=[str(r.get('event_ticker' if field=='events' else 'ticker')) if venue=='kalshi' else str(r.get('id')) for r in rows]
            if any(i in ('None','') for i in native_ids) or len(set(native_ids))!=len(native_ids) or ids.intersection(native_ids):
                raise BudgetStop('duplicate_or_missing_catalog_identity')
            ids.update(native_ids);result.extend(rows)
            traversal.update(pages=page+1,rows=len(result),state='bounded_partial')
            if venue=='kalshi':
                cursor=data.get('cursor')
                if not isinstance(cursor,str) or (cursor and cursor in seen):raise BudgetStop('invalid_catalog_cursor')
                if not cursor:traversal['state']='exhausted';break
                seen.add(cursor)
            elif len(rows)<POLICY['page_size']:traversal['state']='exhausted';break
        return result

    async def venue(self, venue):
        if venue not in coverage.VENUES:return await super().venue(venue)
        if venue in getattr(self.session,'source_access_errors',{}):raise BudgetStop('credential_unavailable_'+venue)
        s=self.session
        if venue not in self.clients:
            client=REST(endpoints_for(s)[venue]['rest'],s.spec['prediction'],lambda r:self.receipt(venue,r),5,
                        s.producers[venue].budget,venue=venue if s.spec['mode']=='real' else None,credential=(s.credentials or {}).get(venue))
            client.session=s;client.request_ceiling=POLICY['rest_attempts'][venue];self.clients[venue]=client
        client=self.clients[venue]
        if venue=='kalshi':
            limits=[]
            for path in ('/trade-api/v2/account/limits','/trade-api/v2/account/endpoint_costs'):
                r=await client.get(endpoints_for(s)[venue]['rest']+path)
                if r.status_code!=200:raise BudgetStop('account_limits_unavailable')
                limits.append(r.json())
            client.account_limits(*limits);s.emit(venue,dict(type='verified_account_budget',limits=limits[0],costs=limits[1]))
            await self.pages_for(venue,'/trade-api/v2/events',dict(series_ticker='KXNFLGAME',status='open',with_milestones='true'),'events',5)
        else:
            await self.pages_for(venue,'/v1/events',dict(tagSlug='nfl',active='true',closed='false',orderBy='startTime',orderDirection='asc',
                sportsMarketTypes=POLICY['us_event_filter'],startTimeMin=(now()+timedelta(seconds=POLICY['kickoff_margin_seconds'])).isoformat()),'events',5)

    async def discover(self, force=False):
        async with self.lock:
            if self.failure:raise BudgetStop(self.failure)
            if self.session.stop_event.is_set():raise asyncio.CancelledError()
            if self.completed:return self.markets
            self.generation=1;self.refresh=dict(state='running',generation=1,started_at=now().isoformat())
            remaining=POLICY['discovery_seconds']-(time.monotonic()-self.session.started_monotonic)
            try:
                async with asyncio.timeout(max(0,remaining)):
                    # Cancel sibling discovery on any failure: no late catalog work.
                    async with asyncio.TaskGroup() as tg:
                        for v in self.venues:tg.create_task(self.venue(v))
                    cats=restrict_games({v:coverage.catalog(self.pages,v,now()) for v in coverage.VENUES})
                    try:selected=choose_event(cats,now())
                    except BudgetStop:
                        if any(t['state']=='bounded_partial' for k,t in self.traversals.items() if k.endswith('/events')):
                            raise BudgetStop('event_page_limit_without_shared_game') from None
                        raise
                    self.session.selected_event=selected
                    us=next(e for e in cats['polymarket_us']['events'] if e['id']==selected['polymarket_us'])
                    game_id=us.get('_native',{}).get('gameId')
                    if not game_id:raise BudgetStop('selected_us_game_id_missing')
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self.pages_for('kalshi','/trade-api/v2/markets',dict(event_ticker=selected['kalshi']),'markets',5))
                        tg.create_task(self.pages_for('polymarket_us','/v1/markets',dict(gameId=str(game_id),active='true',closed='false'),'markets',5))
                    cats,markets=super().project()
                    for v in coverage.VENUES:
                        eligible=[m for m in cats[v]['markets'] if m['event_id']==selected[v] and not m.get('subscription_exclusion') and not m.get('parse_exclusion') and m['market_type']=='moneyline' and m['period']=='full_game' and m['status']=='active']
                        ids=[m['id'] for m in sorted(eligible,key=lambda m:m['id'])[:POLICY['markets_per_venue']]]
                        if not ids:raise BudgetStop('selected_winner_market_missing_'+v)
                        cats[v]['selection']=dict(ids=ids,eligible=len(eligible))
                        cats[v]['qualification_ids']=ids
                        markets[v]={mid:markets[v][mid] for mid in ids}
                        for m in cats[v]['markets']:
                            if m['id'] not in ids:m['subscription_exclusion']='outside_one_event_qualification_selection'
                    # Both source bindings must exist before any subscription.
                    selected['markets']={v:list(cats[v]['selection']['ids']) for v in coverage.VENUES}
                    selected['subscription_ids']={v:[m['id'] if v=='kalshi' else m['native_slug'] for m in cats[v]['markets'] if m['id'] in selected['markets'][v]] for v in coverage.VENUES}
                    self.session.emit('session',dict(type='qualification_selection',selection=selected,policy=POLICY))
                    at=now().isoformat()
                    admitted,error=self.admission('session',dict(type='coverage_inventory',generation=1,published_at=at,inventory=cats,previous_generation=None,discovery_error=None))
                    if error:raise error
                    if not admitted:raise BudgetStop('inventory_publication_not_retained')
                    self.inventory,self.markets=cats,markets;self.published_generation=1;self.published_at=at
                    self.completed=True;self.coverage=cats;self.refresh.update(state='completed',finished_at=at)
                    return markets
            except BaseException as exc:
                if self.failure is None:
                    self.failure=self.session.reason or failure_reason(exc)
                    self.refresh.update(state='failed',reason=self.failure,finished_at=now().isoformat())
                    # Persist the first failure before Stop freezes the saved cutoff.
                    # Waiting producers cannot begin another discovery or replace it.
                    if not self.session.stop_event.is_set():
                        self.session.emit('session',dict(type='qualification_discovery_failed',reason=self.failure,
                            traversals=deepcopy(self.traversals),responses=deepcopy(self.responses)))
                        try:
                            async with asyncio.timeout(.5):await self.session.queue.join()
                        except TimeoutError:pass
                    self.session.request_stop(self.failure)
                raise



class QualificationSession(ContinuousSession):
    supports_two_source_qualification=True
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        validate(self.spec)
        self.sid=self.spec['two_source_qualification']['attempt_id']

    async def start(self):
        validate(self.spec)
        if rss()>=LIMITS['rss_bytes']:raise ValueError('qualification initial RSS cap')
        marker=self.output.parent/'b3-attempt.json'
        begin=json.loads(marker.read_text())['started_monotonic'] if self.spec['mode']=='real' else time.monotonic()
        await super().start()
        self.started_monotonic=begin
        self.discovery=QualificationDiscovery(self)
        return self.sid

    def guard_scope(self,source,record):
        from .two_source_scope import violation
        reason=violation(source,record,getattr(self,'selected_event',{}))
        if reason:
            # Quarantine original bounded input separately: replay never parses it as a frame.
            super().emit(source,dict(type='qualification_scope_violation',direction=(
                'outgoing' if record['type']=='prediction_command' else 'incoming' if record['type']=='prediction_frame' else 'admission'),
                reason=reason,rejected=record))
            stop='qualification_subscription_scope_violation' if record['type']=='prediction_command' else 'qualification_admission_scope_violation'
            self.request_stop(stop)
            raise BudgetStop(stop)

    def emit(self,source,record):
        self.guard_scope(source,record)
        return super().emit(source,record)

    def request_stop(self,reason):
        if self.reason is None and getattr(self,'projection',None):
            try:self.stop_snapshot=self.projection.snapshot(mode='saved')
            except Exception:self.stop_snapshot=None
        super().request_stop(reason)

    async def discoveries(self):
        # No second discovery, event replacement or added subscription group.
        await self.stop_event.wait()

    async def monitor(self):
        ordinary=asyncio.create_task(super().monitor())
        try:
            while not self.stop_event.is_set():
                ended=next((v for v in coverage.VENUES for g in self.producers[v].groups.values()
                            if g.get('task') and g['task'].done()),None)
                if ended:
                    self.request_stop('qualification_source_ended_'+ended);break
                elapsed=time.monotonic()-self.started_monotonic
                if elapsed>=POLICY['cleanup_start_seconds']:
                    self.request_stop('qualification_deadline');break
                if elapsed>=POLICY['target_stop_seconds'] and all(self.producers[v].snapshot()['usable']>0 for v in coverage.VENUES):
                    self.request_stop('qualification_observation_target');break
                await self.pause(.1)
        finally:
            ordinary.cancel();await asyncio.gather(ordinary,return_exceptions=True)

    async def close_resources(self):
        await super().close_resources()
        if not self.cleanup_errors and self.spec['mode']=='real':
            path=self.output.parent/'network-closed.json'
            if not path.exists():save_json(path,dict(attempt_id=self.spec['two_source_qualification']['attempt_id'],at=now().isoformat(),monotonic=time.monotonic()))


class QualificationOwner(CoverageOwner):
    async def start(self,max_games=None,duration=90):
        if duration!=90:raise ValueError('Frozen qualification requires 90-second duration')
        value=self.spec_factory()
        if value['mode']=='mock':
            validate(value)
            marker=self.pilot_output/'fixture-attempt.json'
            if marker.exists():raise ValueError('Fixture qualification allowance consumed')
            save_json(marker,dict(attempt_id=value['two_source_qualification']['attempt_id'],mode='synthetic'))
        return await super().start(max_games=max_games,duration=duration)

    def status(self):
        result=super().status();result.update(fixed_duration=90,qualification_scope='One pregame NFL event; bounded discovery; two prediction sources only')
        if (self.pilot_output/'fixture-attempt.json').exists():result['start_available']=False
        return result

    async def finish(self,folder):
        await super().finish(folder)
        if self.error:return
        try:
            from app.collection.two_source_audit import oracle
            from hashlib import sha256
            snapshot=getattr(self.session,'stop_snapshot',None)
            if snapshot is None:raise ValueError('stop cutoff unavailable')
            value=oracle(snapshot)
            required=len(json.dumps(value,indent=2).encode())+4096
            if rss()>=LIMITS['rss_bytes'] or required+sum(p.stat().st_size for p in folder.iterdir() if p.is_file())>LIMITS['output_bytes']:
                raise ValueError('qualification finalization resource cap')
            save_json(folder/'qualification-oracle.json',value)
            save_json(folder/'qualification-manifest.json',dict(files={name:sha256((folder/name).read_bytes()).hexdigest() for name in ('manifest.json','qualification-oracle.json')}))
        except Exception:
            self.error='Qualification cutoff audit incomplete; retained evidence requires review'
