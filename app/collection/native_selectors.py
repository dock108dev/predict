"""Evidence-bound game discovery. Finding a listing never qualifies a contract."""
from datetime import timedelta
import aiohttp
import time
from . import coverage
from .odds_http import BudgetStop

POLICY='sport-directed-games-v1'
SPORTS=('NFL','NCAAF','NBA','NCAAB','MLB','NHL')
# Observed in phase-0/kalshi-series.json; no inferred ticker construction.
SERIES=dict(NFL='KXNFLGAME',NCAAF='KXNCAAFGAME',NBA='KXNBAGAME',
            NCAAB='KXNCAAMBGAME',MLB='KXMLBGAME',NHL='KXNHLGAME')
# NFL successful league endpoint; remaining slugs observed in r4 league tags.
# R2 complete /v2/leagues: CBB id=4, slug=cbb, tagId=8, basketball sportId=1;
# separate WCBB id=17. This identifies the native family, not division/game identity.
LEAGUES=dict(NFL='nfl',NCAAF='cfb',NBA='nba',NCAAB='cbb',MLB='mlb',NHL='nhl')
PAGE_SIZE=5
PAGES=2
MARKET_PAGES=1
GENERATIONS=3
# Two attempts/operation; existing per-source budget includes retries.
REQUEST_CAPS={'kalshi':4+GENERATIONS*(6*PAGES+6*MARKET_PAGES)*2,
              'polymarket_us':GENERATIONS*(2+5*PAGES+5*MARKET_PAGES)*2}

def policy(spec):
    return spec.get('native_discovery',{}).get('policy') or spec.get('source_session',{}).get('native_discovery')

def enabled(spec):return policy(spec)==POLICY

GAP_SLICE='native-gaps-v1'
GAP_SPORTS={'kalshi':('NCAAF','NHL'),'polymarket_us':('NCAAF','NBA','MLB','NHL','NCAAB')}
GAP_CAPS={'kalshi':12,'polymarket_us':30}
def gap_enabled(spec):return spec.get('native_discovery',{}).get('slice')==GAP_SLICE

def validate_probe(value, *, transport=None):
    value=dict(value)
    scopes=value.pop('native_scopes',None)
    if scopes is not None:
        from .native_payload import exact_transport
        from .source_session import normalize_native_scopes
        if not exact_transport(transport) or 'slice' in value:
            raise ValueError('Typed native scopes require explicit v2 ordinary metadata discovery')
        normalize_native_scopes(scopes)
    if 'slice' in value and value.pop('slice')!=GAP_SLICE:raise ValueError('Unknown native evidence slice')
    if value!={'policy':POLICY,'sports':list(SPORTS),'discovery_only':True,'generations':1}:
        raise ValueError('Exact six-sport native discovery-only contract required')

def query(venue,sport,at=None):
    if venue=='kalshi':
        return '/trade-api/v2/events',dict(series_ticker=SERIES[sport],status='open',with_milestones='true',with_nested_markets='false')
    slug=LEAGUES.get(sport)
    if not slug:return None
    q=dict(tagSlug=slug,active='true',closed='false',orderBy='startTime',orderDirection='asc')
    if sport=='NFL':q['sportsMarketTypes']='football_team_full_game_winner'
    else:q['tagSlugsAll']='games'  # observed games tag; documented AND filter
    if at:
        q.update(startTimeMin=(at+timedelta(minutes=5)).isoformat(),startTimeMax=(at+timedelta(days=7)).isoformat())
    return '/v1/events',q

def candidates(pages,venue,sport,at):
    """Native game findings with explicit exclusions; no canonical identity needed.

    US filtered events endpoint bounds time on the server and locally. Unknown Kalshi milestone kinds stay schedule-unknown, but a game
    series listing can still justify bounded market metadata retrieval.
    """
    target=query(venue,sport)
    if not target:return [],[dict(reason='selector_unestablished',sport=sport)]
    path,q=target
    relevant=[p for p in pages if p['source']==venue and p['path']==path and all(str(coverage.params(p).get(k, 'false' if k=='with_nested_markets' else ''))==str(v) for k,v in q.items())]
    accepted,state=coverage.traversal(relevant,venue,'events')
    found={};excluded=[]
    for page,body,data in accepted:
        for e in data['events']:
            eid=str(e.get('event_ticker' if venue=='kalshi' else 'id') or '')
            reason=None;start=None;binding={}
            if venue=='kalshi':
                if e.get('series_ticker')!=SERIES[sport]:reason='conflicting_series'
                else:
                    from app.adapters.kalshi import SPORT_SERIES,parse_event
                    if SERIES[sport] in SPORT_SERIES:
                        try:start=parse_event(coverage.response(venue,page,body),e,SERIES[sport]).scheduled_start
                        except (ValueError,KeyError,TypeError,AttributeError):reason='invalid_game_metadata'
            else:
                slug=LEAGUES[sport]
                from app.adapters.polymarket_us import event_game_binding
                try:binding=event_game_binding(e,slug,live_bindings=page.get('native_binding_revision') in ('live-native-binding-1','live-native-binding-2'))
                except ValueError as exc:
                    excluded.append(dict(id=eid,reason=str(exc)));continue
                teams=binding['teams']
                leagues={str(t.get('league','')).lower() for t in (teams or []) if isinstance(t,dict)}
                tags={t.get('league',{}).get('slug') for t in (e.get('tags') or []) if isinstance(t,dict) and isinstance(t.get('league'),dict)}
                if not isinstance(teams,list) or len(teams)!=2 or len({t.get('name') for t in teams if isinstance(t,dict) and isinstance(t.get('name'),str) and t['name']})!=2:reason='missing_game_or_participants'
                elif leagues!={slug} or (tags and slug not in tags):reason='conflicting_or_missing_league'
                elif e.get('closed') is not False or e.get('active') is not True or e.get('ended') is True:reason='inactive_or_unknown_game'
                try:start=coverage.stamp(e['startTime']) if e.get('startTime') else None
                except (ValueError,TypeError,AttributeError):reason='invalid_schedule'
            if not eid or not e.get('title'):reason='missing_game_identity_or_title'
            if start and not at+timedelta(minutes=5)<start<=at+timedelta(days=7):reason='outside_game_window'
            if eid in found:reason='duplicate_game_identity'
            if reason:excluded.append(dict(id=eid,reason=reason));continue
            found[eid]=dict(id=eid,sport=sport,scheduled_start=start.isoformat() if start else None,
                schedule_status='observed' if start else 'unestablished',game_id=e.get('gameId'),
                response_sha256=page['body_sha256'],market_bindings=binding.get('markets',[]),participant_binding=binding.get('basis'),metadata_locator='embedded_slug' if binding.get('markets') else ('game_id' if type(e.get('gameId')) is int and e['gameId']>0 else 'unavailable'),qualification='native listing only; period, settlement and cross-source identity separate')
    return sorted(found.values(),key=lambda e:(e['scheduled_start'] is None,e['scheduled_start'] or '',e['id'])),excluded

async def discover(d,venue):
    if gap_enabled(d.session.spec):return await discover_gaps(d,venue)
    from .native_scope_discovery import enabled as scoped, discover as discover_scopes
    if scoped(d.session.spec,venue):return await discover_scopes(d,venue)
    return await discover_games(d,venue)


async def discover_games(d,venue):
    s=d.session;findings={};selected={};failures={}
    # Bounded league metadata obtains the exact missing NCAAB slug evidence.
    if venue=='polymarket_us':
        try:await d.pages_for(venue,'/v2/leagues',{},'leagues',50,page_cap=2)
        except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
            if isinstance(exc,BudgetStop) and venue not in d.source_stops:raise
            failures['league_metadata']=str(exc)
    for sport in SPORTS:
        if venue in d.source_stops:
            findings[sport]=dict(state='not_reached_source_stopped',selected=None,reason=d.source_stops[venue]);continue
        target=query(venue,sport,d.selection_time)
        if target is None:
            findings[sport]=dict(state='selector_unestablished',selected=None,exclusions=[]);continue
        path,q=target
        try:
            await d.pages_for(venue,path,q,'events',PAGE_SIZE,page_cap=PAGES)
            games,excluded=candidates(d.pages,venue,sport,d.selection_time)
            relevant=[p for p in d.pages if p['source']==venue and p['path']==path and all(str(coverage.params(p).get(k))==str(v) for k,v in q.items())]
            _,traversal=coverage.traversal(relevant,venue,'events')
            findings[sport]=dict(state='game_found' if games else 'no_eligible_game_in_bounded_query',
                                selected=games[0] if games else None,exclusions=excluded,traversal=traversal)
            if games:selected[sport]=games[0]
        except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
            if isinstance(exc,BudgetStop) and venue not in d.source_stops:raise
            findings[sport]=dict(state='query_failed',reason=str(exc),selected=None)
    # Metadata is separated from listing discovery and from executable admission.
    for sport,e in selected.items():
        if venue in d.source_stops:
            findings[sport]['metadata_error']='not_reached_source_stopped';continue
        try:
            path='/trade-api/v2/markets' if venue=='kalshi' else '/v1/markets'
            q=dict(event_ticker=e['id']) if venue=='kalshi' else dict(gameId=str(e['game_id']),active='true',closed='false')
            if venue=='polymarket_us' and e.get('game_id') is None:
                q=gap_market_query(venue,e)
                if q is None:
                    findings[sport]['metadata_error']='unavailable_no_evidenced_locator';continue
            await d.pages_for(venue,path,q,'markets',50,page_cap=MARKET_PAGES)
        except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
            if isinstance(exc,BudgetStop) and venue not in d.source_stops:raise
            findings[sport]['metadata_error']=str(exc)
    d.session.emit(venue,dict(type='native_acquisition_selection',policy=POLICY,selected={k:v['id'] for k,v in selected.items()},
        sports=findings,failures=failures,unavailable_sports=[k for k in SPORTS if k not in selected],
        limitation='At most two five-game pages per evidenced league/series; not exhaustive. Game finding is not market, period, schedule, settlement or cross-source qualification.'))
    if not hasattr(d,'acquisition_selected'):d.acquisition_selected={}
    d.acquisition_selected[venue]={e['id'] for e in selected.values()}


def gap_query(venue,sport,at):
    if sport not in GAP_SPORTS[venue]:raise ValueError('Sport outside evidence slice')
    path,q=query(venue,sport,at)
    if venue=='polymarket_us':
        # Documented marketTypes filters; wire behavior remains probe evidence.
        q.update(marketTypes='moneyline',includeHidden='false',includePopularPlayerProps='false')
    return path,q

def gap_market_query(venue,event):
    if venue=='kalshi':return dict(event_ticker=event['id'])
    # Same slug-filter path as PolymarketUSAdapter.discover_markets. Never
    # synthesize a gameId or slug. One bounded five-market page, no extra query.
    refs=event.get('market_bindings') or []
    if refs:return dict(slug=[m['slug'] for m in refs[:5]],active='true',closed='false')
    if type(event.get('game_id')) is int and event['game_id']>0:
        return dict(gameId=str(event['game_id']),active='true',closed='false',sportsMarketTypes='SPORTS_MARKET_TYPE_MONEYLINE')
    return None


async def discover_gaps(d,venue):
    """Fair bounded slice on the ordinary REST/journal path; no broad fallback.

    First listing opportunity for every gap precedes metadata, extra pages and
    deferred recovery. Each operation has at most two attempts; recovery is last.
    Envelope rejection ends that query family, not independent sport discovery.
    """
    scopes=GAP_SPORTS[venue];client=d.clients[venue]
    states={s:dict(state='pending',selected=None,metadata='not_requested',exclusions=[]) for s in scopes}
    omitted={s:dict(state='retained_evidence_reused_no_request',selected=None) for s in SPORTS if s not in scopes}
    selections={};pending=[];counts={};terminal=set();next_positions={};requested_metadata=set();retry_at={}
    async def attempt(sport,kind,position):
        state=states[sport];key=(sport,kind,str(position))
        if venue in d.source_stops:
            state.setdefault('omissions',[]).append(kind+':source_stopped');return
        if (sport,kind) in terminal:return
        if counts.get(key,0)>=2:return
        if counts.get(key,0):
            wait=max(0,retry_at.get(key,0)-time.monotonic())
            if time.monotonic()+wait>=d.session.started_monotonic+d.session.spec['duration']:
                state.setdefault('omissions',[]).append(kind+':retry_after_exceeds_remaining_duration');return
            if wait:await client.bounded_wait(wait)
        counts[key]=counts.get(key,0)+1
        if kind=='events':
            path,q=gap_query(venue,sport,d.selection_time);size=5 if venue=='kalshi' else 1
        else:
            e=selections[sport];path='/trade-api/v2/markets' if venue=='kalshi' else '/v1/markets';size=5
            q=gap_market_query(venue,e)
            if len(e.get('market_bindings',[]))>5:state['omitted_metadata_slugs']=len(e['market_bindings'])-5
            if q is None:
                state['metadata']='unavailable_no_evidenced_locator';return
        before=client.requests
        try:
            await d.pages_for(venue,path,q,kind,size,page_cap=1,start_position=position)
            if kind=='events':
                relevant=[p for p in d.pages if p['source']==venue and p['path']==path and all(str(coverage.params(p).get(k))==str(v) for k,v in q.items())]
                _,traversal=coverage.traversal(relevant,venue,'events')
                if traversal['state']=='failed':
                    d.stop_source(venue,'invalid_gap_traversal');raise ValueError('invalid_gap_traversal')
                games,excluded=candidates(d.pages,venue,sport,d.selection_time)
                # Slice requires explicit kickoff for time-sensitive selection.
                excluded.extend(dict(id=e['id'],reason='missing_schedule_for_current_selection') for e in games if e['scheduled_start'] is None)
                games=[e for e in games if e['scheduled_start'] is not None]
                state.update(state='game_found' if games else 'no_eligible_game_in_bounded_query',exclusions=excluded,traversal=traversal)
                if games:
                    selections[sport]=games[0];state['selected']=games[0]
                if traversal['state']=='bounded/truncated' and counts[key]==1:
                    next_positions[sport]=traversal['next_position']
            else:state['metadata']='complete_bounded_page'
        except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
            reason=str(exc)
            from .native_payload import RESPONSE_CAP_REASONS
            if isinstance(exc,BudgetStop) and reason not in RESPONSE_CAP_REASONS and venue not in d.source_stops:raise
            state['metadata' if kind=='markets' else 'state']='query_failed'
            state.setdefault('errors',[]).append(dict(kind=kind,position=position,reason=reason,attempt=counts[key]))
            if reason in RESPONSE_CAP_REASONS:
                terminal.add((sport,kind));state['response_envelope_exceeded']=True
            elif (isinstance(exc,(TimeoutError,aiohttp.ClientError)) or reason in ('catalog_http_429','catalog_http_500','catalog_http_502','catalog_http_503','catalog_http_504')) and counts[key]==1:
                retry_at[key]=max(time.monotonic()+1,getattr(client,'gap_retry_at',0));pending.append((sport,kind,position))
        finally:
            d.session.emit(venue,dict(type='native_gap_operation',sport=sport,kind=kind,position=position,attempt=counts[key],http_attempts=client.requests-before,phase=phase))
    def initial():return '' if venue=='kalshi' else 0
    phase='first_opportunities'
    for sport in scopes:await attempt(sport,'events',initial())
    phase='selected_metadata'
    for sport in scopes:
        if sport in selections:
            requested_metadata.add(sport);await attempt(sport,'markets',initial())
    phase='additional_pages'
    for sport in scopes:
        if sport not in selections and sport in next_positions:
            await attempt(sport,'events',next_positions[sport])
            if sport in selections:
                requested_metadata.add(sport);await attempt(sport,'markets',initial())
    phase='deferred_recovery'
    # Fair first opportunities finished. No more than one recovery per operation.
    for sport,kind,position in list(pending):
        await attempt(sport,kind,position)
        if sport in selections and sport not in requested_metadata:
            requested_metadata.add(sport);await attempt(sport,'markets',initial())
    # A newly selected metadata operation may itself have one deferred retry.
    for sport,kind,position in pending:
        if kind=='markets' and counts[(sport,kind,str(position))]==1:await attempt(sport,kind,position)
    for sport,state in states.items():
        if state['state']=='pending':state['state']='not_reached_source_stopped'
        if sport in selections and state['metadata']=='not_requested':state['metadata']='not_reached_source_stopped'
    if not hasattr(d,'acquisition_selected'):d.acquisition_selected={}
    d.acquisition_selected[venue]={e['id'] for e in selections.values()}
    d.session.emit(venue,dict(type='native_acquisition_selection',policy=POLICY,slice=GAP_SLICE,selected={s:e['id'] for s,e in selections.items()},sports={**omitted,**states},failures=dict(source_stop=d.source_stops.get(venue)),unavailable_sports=[s for s in scopes if s not in selections],limitation='Gap slice: at most two listing pages and one selected-market page per sport, two attempts each; first opportunities precede recovery. NFL/completed scopes reused, never refreshed. Time-sensitive IDs resolved at Start. Listings are not qualified identities.'))
