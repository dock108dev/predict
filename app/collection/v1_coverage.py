"""Finite missing-pair discovery; observed links locate, predicates admit."""
import re
from .native_scope_bindings import series_binding
from .source_bindings import required_cells
from .odds_http import BudgetStop
from . import coverage

POLICY='v1-missing-pairs-1'
COMPETITIONS=dict(NFL='Pro Football',NBA='Pro Basketball (M)',MLB='Pro Baseball',NHL='Pro Hockey',NCAAF='College Football',NCAAB='College Basketball (M)')
# Stable IDs of dated retained pairs. These never assert fresh availability.
PAIRED=frozenset(('NFL/full_game/moneyline','NFL/full_game/spread','NFL/full_game/total','NFL/first_half/moneyline',
 'NBA/full_game/moneyline','MLB/full_game/moneyline','MLB/full_game/total','MLB/first_5/moneyline',
 'NHL/full_game/moneyline','NHL/full_game/spread','NHL/full_game/total',
 'NCAAF/full_game/moneyline','NCAAF/full_game/spread','NCAAF/full_game/total','NCAAF/first_half/moneyline'))

def enabled(spec):return spec.get('source_session',{}).get('coverage_policy')in (POLICY,'v1-counterpart-completion-1')

def priority(cell):
    from .native_scope_discovery import cell_id
    cid=cell_id(cell)
    return (cid in PAIRED,cell['period']=='full_game',cid)

async def linked(d,ceiling,states):
    """One milestone page/sport; at most 17 observed links, no ticker synthesis."""
    if getattr(d,'v1_links_attempted',False):return
    d.v1_links_attempted=True
    client=d.clients['kalshi'];ops=[];seen=getattr(d,'v1_observed_links',set());d.v1_observed_links=seen
    series_seen=getattr(d,'v1_series_seen',set());d.v1_series_seen=series_seen
    def allowed():return client.requests<ceiling and 'kalshi' not in d.source_stops and not d.session.stop_event.is_set()
    async def get(path,params,kind):
        if not allowed():raise BudgetStop('v1_discovery_allowance_or_stop')
        response=await client.get(client.endpoint+path,params)
        ops.append(dict(path=path,params=params,kind=kind))
        if response.status_code!=200:raise ValueError('linked_http_'+str(response.status_code))
        return response.json()
    # Shared per sport response, rather than seventeen duplicate milestone queries.
    for sport,competition in COMPETITIONS.items():
        cells=[k for k in states if k.startswith(sport+'/') and not states[k]['series']]
        if not cells:continue
        for cid in cells:states[cid]['locator_discovery']='not_reached'
        try:
            body=await get('/trade-api/v2/milestones',dict(category='Sports',competition=competition,limit=20),'locator')
            milestones=body.get('milestones')
            if not isinstance(milestones,list) or len(milestones)>20:raise ValueError('milestone_bound')
            links=[]
            for m in milestones:
                if m.get('category')!='Sports' or not isinstance(m.get('related_event_tickers'),list):continue
                # Query scope alone cannot overcome explicit competition conflict.
                if m.get('details',{}).get('competition') not in (None,competition):continue
                for eid in m['related_event_tickers']:
                    if isinstance(eid,str) and re.fullmatch('[A-Za-z0-9_-]{1,160}',eid) and eid not in seen and eid not in links:links.append(eid)
            for cid in cells:states[cid].update(locator_discovery='observed_links' if links else 'empty_bounded_page',cursor_capped=bool(body.get('cursor')),observed_event_ids=links[:17])
            for eid in links[:3]: # bounded sport share prevents one competition consuming all links
                if len(seen)>=17:break
                if not allowed():break
                seen.add(eid)
                detail=await get('/trade-api/v2/events/'+eid,dict(with_nested_markets='false'),'complete_identity_metadata')
                event=detail.get('event')
                if not isinstance(event,dict) or event.get('event_ticker')!=eid:raise ValueError('linked_event_identity')
                ticker=event.get('series_ticker')
                if not isinstance(ticker,str) or not re.fullmatch('[A-Za-z0-9_-]{1,160}',ticker):raise ValueError('linked_series_identity')
                if ticker not in series_seen:
                    series=await get('/trade-api/v2/series/'+ticker,{},'series_metadata')
                    if series.get('series',{}).get('ticker')!=ticker:raise ValueError('linked_series_conflict')
                    series_seen.add(ticker)
                # Unknown series remain locators with observed metadata, never
                # a guessed predicate or substituted period.
                binding=series_binding(ticker)
                client.native_scope_binding=binding
                try:
                    await d.pages_for('kalshi','/trade-api/v2/markets',dict(event_ticker=eid),'markets',5,page_cap=1)
                finally:client.native_scope_binding=None
                if binding:
                    cid=f"{binding['sport']}/{binding['period']}/{binding['category'] or binding['family']}"
                    if cid in states:states[cid].update(state='observed_supported_series',selected_events=[eid],metadata='complete_bounded_market_page')
                for cid in cells:states[cid]['metadata']='observed_link_metadata_predicate_unresolved'
            for cid in cells:
                if links and not any(e in seen for e in links):states[cid]['metadata']='not_reached_allowance'
                states[cid]['state']='locator_observed_predicate_unresolved' if links else 'empty_bounded_milestones'
        except (ValueError,TimeoutError,BudgetStop) as exc:
            for cid in cells:states[cid].update(state='capped' if isinstance(exc,BudgetStop) else 'query_failed',reason=str(exc))
    d.session.emit('kalshi',dict(type='v1_link_discovery',operations=ops,observed_links=sorted(seen),limit=17,cells=states,
        qualification='Observed identifiers and returned metadata only; unresolved predicates remain excluded'))


def counterpart_rank(event,projection):
    """Prefer exact observed canonical participants and schedule, never titles."""
    from app.normalization.college_registry import aggregate_registry
    from app.reference.product import time
    registry=aggregate_registry();sport=event.get('sport_key')
    from app.reference.product import SPORT_KEYS
    competition=next((s for s,k in SPORT_KEYS.items() if k==sport),None)
    team_ids=[registry.resolve('team',event.get(f),league=competition,venue='the_odds_api').canonical_id for f in ('home_team','away_team')]
    if None in team_ids or competition=='MLB':return 1 # occurrence must be independently verified
    for catalog in getattr(projection,'inventory',{}).values():
        for observed in catalog.get('events',[]):
            if observed.get('competition')==competition and observed.get('identity')=='resolved' and set(observed.get('participants',{}).values())==set(team_ids):
                if observed.get('scheduled_start') and time(observed['scheduled_start'])==time(event['commence_time']):return 0
    return 1


def native_counterpart_rank(d,venue,event_id):
    """Selection only: exact shared schedule/participants precede independent IDs."""
    worker=getattr(d.session,'aggregate',None)
    cache=getattr(d,'counterpart_rank_catalogs',{})
    d.counterpart_rank_catalogs=cache
    def source_catalog(source):
        signature=tuple(p.get('body_sha256') for p in d.pages if p.get('source')==source)
        key=(source,signature,d.selection_time)
        if key not in cache:
            # Source-local event identity only; admission sharing occurs later.
            cache[key]=coverage.catalog(d.pages,source,d.selection_time,compact_output=False,share_identity=False)
        return cache[key]
    catalog=source_catalog(venue)
    observed=next((e for e in catalog['events'] if e['id']==event_id),None)
    if not observed or observed.get('identity')!='resolved' or observed.get('competition')=='MLB':return 1
    from app.normalization.college_registry import aggregate_registry
    from app.reference.product import time
    registry=aggregate_registry()
    other='polymarket_us' if venue=='kalshi' else 'kalshi'
    other_catalog=source_catalog(other)
    for e in other_catalog['events']:
        if e.get('identity')=='resolved' and e.get('competition')==observed['competition'] and set(e.get('participants',{}).values())==set(observed['participants'].values()) and e.get('scheduled_start')==observed.get('scheduled_start'):return 0
    for selected in (worker.selected_events.get(observed['competition'],[]) if worker else []):
        ids=[registry.resolve('team',selected[f],league=observed['competition'],venue='the_odds_api').canonical_id for f in ('home_team','away_team')]
        if None not in ids and set(ids)==set(observed['participants'].values()) and observed.get('scheduled_start') and time(observed['scheduled_start'])==time(selected['commence_time']):return 0
    return 1
