"""Six-sport bounded discovery seam, qualified only with controlled catalogs.

The callback supplies the existing native HTTP receipt shape. No client,
credential, retry, configuration loader or provider operation is owned here.
"""
from copy import deepcopy
from datetime import timedelta
import base64
import json
from app.collection import coverage as native_coverage, native_payload
from app.collection.current_policy import DEFAULT
from app.collection.native_scope_bindings import selectors_for, POLICY as SCOPE_POLICY
from app.collection.native_selectors import query, candidates
from app.collection.odds_http import BudgetStop
from .coverage import SPORTS, FAMILIES

VERSION = 'comparison-discovery-1'
PAGE_SIZE = 5
LISTING_PAGES = 2
METADATA_PAGES = 1
MAX_REQUESTS = len(SPORTS) * (LISTING_PAGES + METADATA_PAGES)
WIRE_BYTES = native_payload.TRANSPORT_CONTRACT['discovery_wire_bytes']
RETAINED_BYTES = 8 * 1024 * 1024


def budget(config=DEFAULT):
    """Declare bounds before any callback can be dispatched."""
    return dict(requests=min(MAX_REQUESTS,config['requests_per_source'],config['discovery_pages']),
        listing_pages_per_sport=LISTING_PAGES,metadata_pages_per_sport=METADATA_PAGES,
        listing_page_rows=PAGE_SIZE,metadata_page_rows=50,
        events=min(6,config['events_per_source']),subscriptions=config['markets_per_source'],
        catalog_markets=512,wire_bytes=min(WIRE_BYTES,config['source_bytes']),
        retained_receipt_bytes=RETAINED_BYTES,inventory_bytes=2*1024*1024,
        rss_bytes=config['rss_bytes'],retries=0)


def fair_markets(markets, cap, sports=SPORTS, families=FAMILIES, rotation=0):
    """Round-robin sport/family pools, never a large first sport's ladder."""
    if type(cap) is not int or cap < 0 or cap > DEFAULT['markets_per_source']:
        raise ValueError('Subscription cap exceeded')
    order=list(sports)
    if order:
        offset=rotation%len(order)
        order=order[offset:]+order[:offset]
    pools={(s,f): sorted([m for m in markets if m.get('sport')==s and m.get('family')==f],key=lambda m:m['id'])
           for s in order for f in families}
    selected=[]
    seen=set()
    while len(selected)<cap and any(pools.values()):
        for key,pool in pools.items():
            if pool and len(selected)<cap:
                value=pool.pop(0)
                if value['id'] in seen:
                    raise ValueError('Duplicate selected market')
                seen.add(value['id'])
                selected.append(value)
    return selected


class DiscoveryCycle:
    def __init__(self, venue, *, config=DEFAULT, sports=SPORTS, families=FAMILIES, rotation=0):
        if venue not in ('kalshi','polymarket_us') or set(sports)-set(SPORTS) or set(families)-set(FAMILIES):
            raise ValueError('Unsupported discovery scope')
        if not sports or len(set(sports))!=len(sports) or not families or len(set(families))!=len(families):
            raise ValueError('Exact unique discovery scope required')
        if type(rotation) is not int or rotation<0:
            raise ValueError('Invalid discovery rotation')
        self.venue=venue
        self.config=deepcopy(config)
        self.sports=tuple(sports)
        self.families=tuple(families)
        self.rotation=rotation
        self.bounds=budget(config)
        if self.bounds['requests']<len(sports) or self.bounds['events']<len(sports):
            raise ValueError('First opportunity/event budget cannot cover configured sports')
        self.requests=self.bytes=self.retained=0
        self.pages=[]
        self.stopped=False
        self.consumed=False

    async def run(self, fetch, at, *, ledger=None, dispatch=lambda:True):
        """One finite cycle. `fetch(request)` must obey its outer owner guard."""
        if self.consumed:
            raise ValueError('A discovery cycle is consumed exactly once')
        self.consumed=True
        order=list(self.sports)
        offset=self.rotation%len(order)
        order=order[offset:]+order[:offset]
        family=self.families[self.rotation%len(self.families)]
        cells={s:dict(sport=s,family=family,state='not_checked',completeness='unmeasured',
                      listing_completeness='unmeasured',selected=None,metadata='not_checked',exclusions=[],pages=0,observed_eligible_ids=[]) for s in self.sports}
        queries={}
        selections={}
        page_groups={s:[] for s in self.sports}

        async def operation(request, sport, metadata=False):
            cell=cells[sport]
            if not dispatch():
                raise BudgetStop('comparison_dispatch_revoked')
            if self.stopped or self.requests>=self.bounds['requests'] or self.bytes>=self.bounds['wire_bytes']:
                cell['metadata' if metadata else 'state']='global_budget_excluded'
                cell['completeness']='partial'
                return None
            self.requests+=1
            try:
                request['limits']=dict(wire_bytes=min(native_payload.TRANSPORT_CONTRACT['response_wire_bytes'],self.bounds['wire_bytes']-self.bytes),
                    decoded_bytes=native_payload.TRANSPORT_CONTRACT['response_decoded_bytes'],
                    retained_bytes=self.bounds['retained_receipt_bytes']-self.retained)
                page=await fetch(deepcopy(request))
                if not dispatch():
                    raise BudgetStop('comparison_dispatch_revoked')
                if page.get('source')!=self.venue or page.get('path')!=request['path'] or native_coverage.params(page)!=request['params']:
                    raise ValueError('receipt_query_identity')
                encoded=page.get('body_b64','')
                if not isinstance(encoded,str):
                    raise ValueError('invalid_encoded_receipt')
                # Response bytes consume source budget even when status,
                # completeness, decoding or admission subsequently fails.
                wire=page.get('resource_usage',{}).get('wire_bytes')
                if wire is None:
                    wire=len(base64.b64decode(encoded,validate=True))
                if type(wire) is not int or wire<0:
                    raise ValueError('invalid_wire_accounting')
                self.bytes+=wire
                if self.bytes>self.bounds['wire_bytes']:
                    self.stopped=True
                    cell['metadata' if metadata else 'state']='global_budget_excluded'
                    cell['completeness']='partial'
                    return None
                if page.get('status')!=200 or page.get('complete') is not True:
                    cell['metadata' if metadata else 'state']='failed_source'
                    return None
                body_raw=base64.b64decode(encoded,validate=True)
                cap=native_payload.TRANSPORT_CONTRACT['response_decoded_bytes']
                if len(body_raw)>cap:
                    cell['metadata' if metadata else 'state']='query_capacity_exclusion'
                    return None
                raw,data=native_coverage.decode_page(page)
                native_payload.parse(body_raw,limits=native_payload.TRANSPORT_CONTRACT,revised=True)
                if wire<len(body_raw):
                    raise ValueError('invalid_wire_accounting')
                value=deepcopy(page)
                value.update(acquisition_discovery_policy='sport-directed-games-v1',v1_comparison_policy='manual-comparison-2')
                if request.get('binding'):
                    value.update(native_scope_binding=request['binding'],native_scope_policy=SCOPE_POLICY)
                retained=len(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode())
                if self.retained+retained>self.bounds['retained_receipt_bytes']:
                    self.stopped=True
                    cell['metadata' if metadata else 'state']='global_budget_excluded'
                    cell['completeness']='partial'
                    return None
                self.retained+=retained
                self.pages.append(value)
                return value,raw,data
            except BudgetStop as exc:
                if str(exc)=='comparison_dispatch_revoked':
                    raise
                cell['metadata' if metadata else 'state']='query_capacity_exclusion'
                return None
            except (ValueError,KeyError,TypeError,AttributeError,TimeoutError):
                cell['metadata' if metadata else 'state']='rejected_payload'
                return None

        async def listing(sport,position):
            cell=cells[sport]
            request=deepcopy(queries[sport])
            request['params']['cursor' if self.venue=='kalshi' else 'offset']=position
            result=await operation(request,sport)
            if result is None:
                return None
            page,raw,data=result
            page_groups[sport].append(page)
            accepted,traversal=native_coverage.traversal(page_groups[sport],self.venue,'events')
            if traversal['state']=='failed':
                cell['state']='rejected_payload'
                cell['completeness']='partial'
                selections.pop(sport,None)
                cell['selected']=None
                return None
            cell['pages']+=1
            cell['listing_completeness']='complete' if traversal['state']=='exhausted' else 'partial'
            cell['completeness']=cell['listing_completeness']
            found=[]
            if self.venue=='kalshi':
                from app.adapters.kalshi import parse_event
                for native in data.get('events',[]):
                    try:
                        event=parse_event(native_coverage.response(self.venue,page,raw),native,request['params']['series_ticker'],typed_scope=True)
                        if event.scheduled_start is None:
                            raise ValueError('missing_schedule')
                        if not at+timedelta(minutes=5)<event.scheduled_start<=at+timedelta(days=7):
                            raise ValueError('outside_schedule_window')
                        found.append(dict(id=native['event_ticker'],sport=sport,scheduled_start=event.scheduled_start.isoformat()))
                    except (ValueError,KeyError,TypeError):
                        cell['exclusions'].append('returned_metadata_unverified')
            else:
                found,excluded=candidates(page_groups[sport],self.venue,sport,at)
                cell['exclusions']+=['returned_metadata_unverified']*len(excluded)
            if found:
                cell['observed_eligible_ids']=sorted(set(cell['observed_eligible_ids'])|{e['id'] for e in found})
                found.sort(key=lambda e:(e['scheduled_start'] is None,e['scheduled_start'] or '',e['id']))
                selections.setdefault(sport,found[self.rotation%len(found)])
                cell['selected']=selections[sport]['id']
            cell['state']='offerings_returned' if any(d.get('events') for _,_,d in accepted) else 'no_offerings_returned'
            return traversal.get('next_position') if traversal['state']=='bounded/truncated' else None

        # Every configured sport receives its first opportunity before any
        # second page or metadata. Families and sport priority rotate by cycle.
        next_positions={}
        for sport in order:
            if self.venue=='kalshi':
                selectors=selectors_for(sport+'/full_game/'+family)
                if not selectors:
                    cells[sport]['state']='selector_unestablished'
                    continue
                queries[sport]=deepcopy(selectors[0])
            else:
                path,params=query(self.venue,sport,at)
                queries[sport]=dict(path=path,params=params)
            queries[sport]['params']['limit']=PAGE_SIZE
            position=await listing(sport,'' if self.venue=='kalshi' else 0)
            if position is not None:
                next_positions[sport]=position
        for sport in order:
            if sport in next_positions:
                await listing(sport,next_positions[sport])
        selected_markets=[]
        for sport in order:
            if sport not in selections:
                continue
            event=selections[sport]
            if self.venue=='kalshi':
                request=dict(path='/trade-api/v2/markets',params=dict(event_ticker=event['id'],limit=50,cursor=''),binding=queries[sport]['binding'])
            elif type(event.get('game_id')) is int and event['game_id']>0:
                request=dict(path='/v1/markets',params=dict(gameId=str(event['game_id']),active='true',closed='false',limit=50,offset=0))
            elif event.get('market_bindings'):
                request=dict(path='/v1/markets',params=dict(slug=[m['slug'] for m in event['market_bindings'][:50]],active='true',closed='false',limit=50,offset=0))
            else:
                cells[sport]['metadata']='locator_unestablished'
                continue
            result=await operation(request,sport,True)
            if result is None:
                continue
            _,_,data=result
            rows=data.get('markets')
            if not isinstance(rows,list) or len(rows)>50:
                cells[sport]['metadata']='rejected_payload'
                continue
            ids=set()
            for market in rows:
                if not isinstance(market,dict):
                    cells[sport]['exclusions'].append('returned_metadata_unverified')
                    continue
                mid=market.get('ticker' if self.venue=='kalshi' else 'id')
                valid=(market.get('event_ticker')==event['id'] if self.venue=='kalshi' else
                    str(market.get('gameId'))==str(event.get('game_id')) and event.get('game_id') is not None or
                    any(market.get('id')==b['id'] and market.get('slug')==b['slug'] for b in event.get('market_bindings',[])))
                if self.venue=='polymarket_us':
                    from app.collection.public_contracts import us_type
                    meaning=us_type(market,competition=sport)
                    valid=valid and meaning.get('status')=='DOCUMENTED_LOCATOR' and meaning.get('family')==family and meaning.get('period')=='full_game'
                if not isinstance(mid,str) or not mid or mid in ids or not valid:
                    cells[sport]['exclusions'].append('returned_metadata_unverified')
                    continue
                ids.add(mid)
                selected_markets.append(dict(id=mid,sport=sport,family=family,event_id=event['id']))
            cells[sport]['metadata']='partial' if len(rows)==50 or (self.venue=='kalshi' and data.get('cursor')) else 'complete'
        for cell in cells.values():
            cell['exclusions']=cell['exclusions'][:100]
            if cell['exclusions'] or len(cell['observed_eligible_ids'])>1 or cell['metadata'] in ('partial','failed_source','rejected_payload','query_capacity_exclusion','global_budget_excluded','locator_unestablished'):
                cell['completeness']='partial'
        if ledger is not None:
            for sport,cell in cells.items():
                state=cell['state']
                if state in ('not_checked','selector_unestablished','global_budget_excluded'):
                    continue
                status=state if state in ('failed_source','rejected_payload') else 'failed_source' if state=='query_capacity_exclusion' else state
                offered=None if status in ('failed_source','rejected_payload') else dict(games=sum(len(native_coverage.decode_page(p)[1]['events']) for p in page_groups[sport]),markets=sum(m['sport']==sport for m in selected_markets))
                ledger.observe(sport,self.venue,checked_at=at.isoformat(),status=status,offered=offered,
                    reason='query_capacity' if state=='query_capacity_exclusion' else 'source_failed' if status=='failed_source' else 'payload_rejected' if status=='rejected_payload' else 'query_empty' if state=='no_offerings_returned' else None,
                    completeness=cell['completeness'],family=family,query=queries.get(sport))
        chosen=fair_markets(selected_markets,self.bounds['subscriptions'],self.sports,self.families,self.rotation)
        return dict(schema=VERSION,evidence_class='controlled callback receipts; no current-provider claim',
            budgets=deepcopy(self.bounds),usage=dict(requests=self.requests,wire_bytes=self.bytes,retained_bytes=self.retained),
            cells=list(cells.values()),selected_events=selections,selected_markets=chosen,
            pages=self.pages,rotation=self.rotation,expansion_active=False)


def current_catalog(result,venue,at):
    """Pass exact selected IDs to the shared discovery parser."""
    if result.get('schema')!=VERSION or venue not in ('kalshi','polymarket_us'):
        raise ValueError('Exact bounded discovery result required')
    selection=dict(events=[e['id'] for e in result['selected_events'].values()],
                   markets=[m['id'] for m in result['selected_markets']])
    catalog=native_coverage.catalog(result['pages'],venue,at,compact_output=False,current_selection=selection)
    if len(catalog['events'])>6 or len(catalog['markets'])>20 or len(json.dumps(catalog,default=str).encode())>result['budgets']['inventory_bytes']:
        raise ValueError('Bounded discovery catalog capacity')
    return catalog
