"""Ordinary typed native scope traversal from retained catalog selectors.

Identifiers locate metadata; they never provide market predicates or settlement
terms. Explicit cells, finite requests and per-cell omissions survive the journal.
"""
import aiohttp
from . import coverage
from .native_scope_bindings import POLICY, selectors_for
from .odds_http import BudgetStop

def evidenced_priorities(venue,sport):
    import json
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'fixtures/native-evidenced-priorities-v1.json'
    if path.stat().st_size>16384:raise ValueError('Native priority catalog bound')
    value=json.loads(path.read_text())
    if value.get('schema')!='native-evidenced-priorities-1' or len(value['targets'])>16:
        raise ValueError('Native priority catalog invalid')
    return {r[venue] for r in value['targets'] if r['sport']==sport}


def scopes(spec,venue):
    value=spec.get('source_session',{}).get('native_scopes') or spec.get('native_discovery',{}).get('native_scopes')
    if value is None:return []
    from .source_session import normalize_native_scopes
    return normalize_native_scopes(value).get(venue,[])


def enabled(spec,venue):
    from .native_payload import exact_transport
    return exact_transport(spec.get('native_transport')) and bool(scopes(spec,venue))


def cell_id(cell):
    return f"{cell['sport']}/{cell['period']}/{cell['category'] or cell['family']}"


async def discover(d,venue):
    from .v1_coverage import enabled as coverage_enabled
    if coverage_enabled(d.session.spec) and venue in getattr(d,'v1_scope_done',set()):return
    client=d.clients[venue]
    remaining=max(0,min(client.limits['discovery_requests'],getattr(client,'request_ceiling',client.limits['discovery_requests']))-client.requests)
    generations=1 if d.session.spec.get('native_discovery') else max(1,d.session.spec.get('source_session',{}).get('max_cycles',3)-d.generation+1)
    from .v1_coverage import enabled as coverage_enabled
    ceiling=client.requests+remaining if coverage_enabled(d.session.spec) else client.requests+remaining//generations
    client.native_scope_generation_ceiling=ceiling
    client.native_scope_request_context=True
    try:
        result=await _discover(d,venue,remaining,ceiling)
        if coverage_enabled(d.session.spec):
            if not hasattr(d,'v1_scope_done'):d.v1_scope_done=set()
            d.v1_scope_done.add(venue)
        return result
    finally:
        client.native_scope_request_context=False
        client.native_scope_generation_ceiling=None


async def _discover(d,venue,remaining,ceiling):
    requested=scopes(d.session.spec,venue)
    from .v1_coverage import enabled as coverage_enabled, priority
    if coverage_enabled(d.session.spec):requested=sorted(requested,key=priority)
    states={cell_id(c):dict(state='not_reached',series=[],attempted_selectors=[],omitted_selectors=[],selected_events=[],metadata='not_requested') for c in requested}
    if venue!='kalshi':return await discover_us(d,requested,states,remaining,ceiling)
    client=d.clients[venue]
    if not hasattr(d,'scope_traversal'):d.scope_traversal={}
    seen=d.scope_traversal.setdefault(venue,set())
    chosen={};selected=set();metadata=[];operations=[];processed_metadata=set()
    winners=[c for c in requested if c['period']=='full_game' and c['family']=='moneyline']
    others=[c for c in requested if c not in winners]
    # Every selected cell receives its first catalog opportunity before another
    # alias for that cell; complete provider-local winner metadata remains first
    # in integrated sessions. Metadata-only traversals prioritize all cells.
    selectors={cell_id(c):selectors_for(cell_id(c),venue) for c in requested}
    if coverage_enabled(d.session.spec):selectors={k:v[:1] for k,v in selectors.items()}
    for key,values in selectors.items():
        states[key]['series']=[v['binding']['series_ticker'] for v in values]
        if not values:states[key]['state']='selector_unestablished'

    async def listing(c,selector):
        key=cell_id(c);ticker=selector['binding']['series_ticker']
        if client.requests>=ceiling:
            if states[key]['state']=='not_reached':states[key]['state']='not_reached_request_allowance'
            states[key]['omitted_selectors'].append(dict(series_ticker=ticker,reason='generation_request_allowance'))
            return
        if venue in d.source_stops:
            if states[key]['state']=='not_reached':states[key].update(state='not_reached_source_stopped',reason=d.source_stops[venue])
            states[key]['omitted_selectors'].append(dict(series_ticker=ticker,reason=d.source_stops[venue]));return
        client.native_scope_binding=selector['binding']
        states[key]['attempted_selectors'].append(ticker)
        before=len(d.pages)
        try:
            metadata_only=bool(d.session.spec.get('native_discovery'))
            size=5 if d.session.spec.get('source_session',{}).get('coverage_policy')=='v1-counterpart-completion-1' else 20 if metadata_only and c['sport']=='NFL' and c['period']=='full_game' else 1
            await d.pages_for(venue,selector['path'],selector['params'],'events',size,page_cap=1)
            pages=d.pages[before:]
            candidates=[]
            for page in pages:
                if page.get('status')!=200 or not page.get('usable_metadata'):continue
                _,data=coverage.decode_page(page)
                for e in data.get('events',[]):
                    if e.get('series_ticker')==ticker and isinstance(e.get('event_ticker'),str) and e['event_ticker'] and e.get('title'):
                        candidates.append(e)
            states[key].update(state='bounded_listing_found' if candidates else 'no_listing_in_bounded_page',
                response_sha256s=[p['body_sha256'] for p in pages])
            seen.add(ticker)
            if candidates:
                from .v1_coverage import native_counterpart_rank
                ordered=sorted(candidates,key=lambda e:((native_counterpart_rank(d,venue,e['event_ticker']) if coverage_enabled(d.session.spec) else 1),e['event_ticker']))
                priority=evidenced_priorities(venue,c['sport']) if metadata_only and c['period']=='full_game' else set()
                targets=[e for e in ordered if e['event_ticker'] in priority]
                if ordered[0] not in targets:targets.insert(0,ordered[0])
                for event in targets[:8]:
                    eid=event['event_ticker'];states[key]['selected_events'].append(eid)
                    selected.add(eid);chosen[key]=selector
                    metadata.append((key,eid,selector))
        except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
            if isinstance(exc,BudgetStop) and venue not in d.source_stops:
                from .native_payload import query_cap_reasons
                RESPONSE_CAP_REASONS=query_cap_reasons(d.session.spec)
                if str(exc) not in RESPONSE_CAP_REASONS:raise
            states[key].update(state='query_failed',reason=str(exc))
        finally:
            client.native_scope_binding=None
            operations.append(dict(cell_id=key,series_ticker=ticker,kind='events'))

    async def market_page(key,eid,selector):
        if client.requests>=ceiling:
            states[key]['metadata']='not_reached_request_allowance';return
        if venue in d.source_stops:
            states[key]['metadata']='not_reached_source_stopped';return
        client.native_scope_binding=selector['binding']
        before=len(d.pages)
        processed_metadata.add((key,eid))
        try:
            await d.pages_for(venue,'/trade-api/v2/markets',dict(event_ticker=eid),'markets',50 if d.session.spec.get('source_session',{}).get('coverage_policy')=='v1-counterpart-completion-1' else 5,page_cap=1)
            pages=d.pages[before:]
            states[key].update(metadata='complete_bounded_market_page',
                metadata_response_sha256s=[p['body_sha256'] for p in pages if p.get('usable_metadata')],
                metadata_scope='one finite page; catalog exhaustion remains separate')
        except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
            if isinstance(exc,BudgetStop) and venue not in d.source_stops:
                from .native_payload import query_cap_reasons
                RESPONSE_CAP_REASONS=query_cap_reasons(d.session.spec)
                if str(exc) not in RESPONSE_CAP_REASONS:raise
            states[key].update(metadata='query_failed',metadata_reason=str(exc))
        finally:
            client.native_scope_binding=None
            operations.append(dict(cell_id=key,event_id=eid,kind='markets'))

    if coverage_enabled(d.session.spec):
        from .v1_coverage import linked
        if d.session.spec.get('source_session',{}).get('coverage_policy')!='v1-counterpart-completion-1':await linked(d,min(ceiling,client.requests+57),states)
        others=requested;winners=[]
    for c in winners:
        values=selectors[cell_id(c)]
        if values:await listing(c,values[0])
    integrated=bool(d.session.spec.get('source_session')) and not coverage_enabled(d.session.spec)
    if integrated:
        for key,eid,selector in list(metadata):await market_page(key,eid,selector)
        if not getattr(d,'fee_metadata_attempted',False):
            target=next((entry for entry in metadata if entry[0]=='NFL/full_game/moneyline'),None)
            if target:
                d.fee_metadata_attempted=True
                from .native_fee_metadata import collect
                await collect(d,target[2]['binding']['series_ticker'],target[1],ceiling)
    # Rotate additional catalog families across complete generations. Empty
    # responses establish only this bounded query, never provider-wide absence.
    for alias in range(max((len(v) for v in selectors.values()),default=0)):
        for c in others:
            key=cell_id(c);values=selectors[key]
            if alias>=len(values):continue
            if key in chosen:
                states[key]['omitted_selectors'].append(dict(series_ticker=values[alias]['binding']['series_ticker'],reason='event_selected_from_independent_native_series'))
                continue
            selector=values[alias]
            if selector['binding']['series_ticker'] in seen:
                states[key]['omitted_selectors'].append(dict(series_ticker=selector['binding']['series_ticker'],reason='retained_prior_generation_query'))
                if states[key]['state']=='not_reached':states[key]['state']='prior_generation_query_retained'
                continue
            before_meta=len(metadata)
            await listing(c,selector)
            if coverage_enabled(d.session.spec):
                for key,eid,sel in metadata[before_meta:]:await market_page(key,eid,sel)
    pending=[entry for entry in metadata if (entry[0],entry[1]) not in processed_metadata]
    for key,eid,selector in pending:await market_page(key,eid,selector)
    if not hasattr(d,'acquisition_selected'):d.acquisition_selected={}
    d.acquisition_selected[venue]=selected
    d.session.emit(venue,dict(type='native_scope_discovery',policy=POLICY,cells=states,
        operations=operations,request_allowance=remaining,active_generation_request_ceiling=ceiling,
        request_ceiling_enforcement='hard per-generation before each HTTP attempt; no scoped retries',
        limitation='Retained exact series catalog selectors, bounded one-event/five-market pages. Listing identity, selected markets, outcome/line/period/season predicates, eligible state and native semantic review are independent. Unreached/unestablished cells are never absence or qualified live coverage.'))


async def discover_us(d,requested,states,remaining,ceiling):
    """Evidenced family filters and current listing-bound exact details."""
    from .native_selectors import SPORTS, query, candidates, gap_market_query
    from .native_payload import query_cap_reasons
    RESPONSE_CAP_REASONS=query_cap_reasons(d.session.spec)
    from app.adapters.polymarket_us import LIVE_FULL_GAME_TYPES
    from .v1_coverage import enabled as coverage_enabled
    client=d.clients['polymarket_us'];selected={};operations=[];findings={}
    wanted={c['sport'] for c in requested}
    metadata_only=bool(d.session.spec.get('native_discovery'))
    def allowed():return client.requests<ceiling and 'polymarket_us' not in d.source_stops
    def local(exc):
        if isinstance(exc,BudgetStop) and 'polymarket_us' not in d.source_stops and str(exc) not in RESPONSE_CAP_REASONS:raise exc
    async def details(sport,events):
        from .continuous import endpoints_for
        results=[]
        for event in events:
            result=dict(event_id=event['id'],event_delivery='not_requested',market_delivery='not_requested')
            if metadata_only and d.session.spec.get('v1_comparison_policy')!='manual-comparison-2' and getattr(d,'us_expanded_delivery_blocked',None):
                result.update(event_delivery='not_reached_previous_event_envelope_cap',event_reason=d.us_expanded_delivery_blocked)
            elif (metadata_only or coverage_enabled(d.session.spec)) and allowed():
                path='/v1/events/'+event['id'];before=len(d.pages)
                try:
                    response=await client.get(endpoints_for(d.session)['polymarket_us']['rest']+path,{})
                    if response.status_code!=200:raise ValueError('catalog_http_'+str(response.status_code))
                    result.update(event_delivery='complete',event_response_sha256=d.pages[-1]['body_sha256'])
                except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
                    local(exc);result.update(event_delivery='query_failed',event_reason=str(exc))
                    if str(exc) in RESPONSE_CAP_REASONS:d.us_expanded_delivery_blocked=str(exc)
                operations.append(dict(sport=sport,path=path,event_id=event['id'],kind='event_detail'))
            if allowed():
                bindings=event.get('market_bindings',[])
                before=len(d.pages)
                if bindings:
                    path='/v1/market/id/'+bindings[0]['id']
                    try:
                        response=await client.get(endpoints_for(d.session)['polymarket_us']['rest']+path,{})
                        if response.status_code!=200:raise ValueError('catalog_http_'+str(response.status_code))
                        result.update(market_delivery='complete',market_response_sha256=d.pages[-1]['body_sha256'])
                    except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
                        local(exc);result.update(market_delivery='query_failed',market_reason=str(exc))
                    operations.append(dict(sport=sport,path=path,event_id=event['id'],kind='market_detail'))
                else:
                    params=dict(gameId=str(event['game_id']),active='true',closed='false') if event.get('game_id') else gap_market_query('polymarket_us',event)
                    if params is None:result['market_delivery']='unavailable_no_evidenced_locator'
                    else:
                        try:
                            await d.pages_for('polymarket_us','/v1/markets',params,'markets',5,page_cap=1)
                            result['market_delivery']='complete_bounded_market_page'
                        except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
                            local(exc);result.update(market_delivery='query_failed',market_reason=str(exc))
                        operations.append(dict(sport=sport,path='/v1/markets',event_id=event['id'],kind='markets'))
            else:result['market_delivery']='not_reached_source_or_request_allowance'
            results.append(result)
        findings[sport]['details']=results
        findings[sport]['metadata']='complete_selected_details' if results and all(r['market_delivery'].startswith('complete') for r in results) else 'partial_selected_details'
    for sport in SPORTS:
        if sport not in wanted:continue
        path,params=query('polymarket_us',sport,d.selection_time)
        slug=params['tagSlug'];fine_type=LIVE_FULL_GAME_TYPES.get(slug)
        if fine_type:params['sportsMarketTypes']=fine_type
        if not allowed():
            findings[sport]=dict(state='not_reached_request_allowance' if 'polymarket_us' not in d.source_stops else 'not_reached_source_stopped',selected=None,metadata='not_requested');continue
        before=len(d.pages)
        try:
            size=20 if metadata_only and sport=='NFL' else 5
            await d.pages_for('polymarket_us',path,params,'events',size,page_cap=1)
            games,excluded=candidates(d.pages[before:],'polymarket_us',sport,d.selection_time)
            if coverage_enabled(d.session.spec):
                from .v1_coverage import native_counterpart_rank
                games.sort(key=lambda e:(native_counterpart_rank(d,'polymarket_us',e['id']),e['id']))
            findings[sport]=dict(state='game_found' if games else 'no_eligible_game_in_bounded_query',selected=games[0] if games else None,exclusions=excluded,metadata='not_requested',response_sha256s=[p['body_sha256'] for p in d.pages[before:]])
            if games:
                priorities=evidenced_priorities('polymarket_us',sport) if metadata_only else set()
                targets=[e for e in games if e['id'] in priorities]
                if games[0] not in targets:targets.insert(0,games[0])
                selected[sport]=targets[:1] if coverage_enabled(d.session.spec) else targets[:8]
                # Useful complete details precede a later sport's large query.
                if metadata_only:await details(sport,selected[sport])
        except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
            local(exc);findings[sport]=dict(state='query_failed',reason=str(exc),selected=None,metadata='not_requested')
        operations.append(dict(sport=sport,path=path,kind='events'))
    if not metadata_only:
        for sport,events in selected.items():await details(sport,events)
    if d.session.spec.get('v1_comparison_policy')in ('manual-comparison-1','manual-comparison-2'):
        from .v1_comparison import us_selectors
        shared=set()
        from .v1_coverage import enabled as coverage_enabled
        if coverage_enabled(d.session.spec):
            for sport in sorted({c['sport'] for c in requested if c['family']=='futures'}):
                if not allowed():break
                path,params=query('polymarket_us',sport,d.selection_time)
                params['sportsMarketTypes']='SPORTS_MARKET_TYPE_FUTURE'
                try:await d.pages_for('polymarket_us',path,params,'events',5,page_cap=1)
                except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:local(exc)
                operations.append(dict(sport=sport,path=path,params=params,kind='award_locator_discovery'))
        for cell in requested:
            if cell['period']=='full_game' and cell['family']=='moneyline':continue
            for event in selected.get(cell['sport'],[]):
                for selector in us_selectors(cell,event.get('game_id')):
                    if not event.get('game_id') or not allowed():continue
                    signature=(selector['path'],tuple(sorted(selector['params'].items())))
                    if signature in shared:continue
                    shared.add(signature)
                    try:
                        await d.pages_for('polymarket_us',selector['path'],dict(selector['params'],active='true',closed='false'),'markets',5,page_cap=1)
                        states[cell_id(cell)].update(state='documented_family_query_complete',metadata='complete_bounded_market_page')
                    except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
                        local(exc);states[cell_id(cell)].update(state='query_failed',reason=str(exc))
                    operations.append(dict(cell_id=cell_id(cell),event_id=event['id'],kind='documented_family_markets',**selector))
    for cell in requested:
        state=states[cell_id(cell)];sport=cell['sport'];found=findings.get(sport,{})
        winner=cell['period']=='full_game' and cell['family']=='moneyline'
        state.update(state=found.get('state','not_reached') if winner else (state['state'] if state['state']!='not_reached' else 'documented_locator_awaiting_exact_game' if d.session.spec.get('v1_comparison_policy')in ('manual-comparison-1','manual-comparison-2') and us_selectors(cell) else 'exact_family_selector_unestablished'),game_catalog=found,selected_events=[e['id'] for e in selected.get(sport,[])],metadata=found.get('metadata','not_requested'),qualification='Exact current game locator; market family predicate and semantic review remain separate')
    if not hasattr(d,'acquisition_selected'):d.acquisition_selected={}
    d.acquisition_selected['polymarket_us']={e['id'] for events in selected.values() for e in events}
    d.session.emit('polymarket_us',dict(type='native_scope_discovery',policy=POLICY,cells=states,operations=operations,request_allowance=remaining,active_generation_request_ceiling=ceiling,request_ceiling_enforcement='hard per-generation before each HTTP attempt; no scoped retries',limitation='Evidenced full-game type filters; metadata NFL targets must match current complete listings. Exact event/market delivery and review are independent. No exhaustive absence claim or substituted sport/season.'))
