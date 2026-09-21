"""Native source extensions for the existing bounded collector and B2 projection.

Configuration contains references only. Authentication is lazy, only after an
explicit approved Start. REST observations are dated snapshots, never stream claims.
"""
import asyncio
import base64
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from decimal import Decimal
from urllib.parse import urlsplit
from app.collection.prediction_producer import PredictionBudget
from app.collection.native_semantics import purchase_book, SEMANTICS
from app.models.core import EvidenceKind

SOURCES = ('kalshi','polymarket_us','novig','prophetx')
REFERENCES = {
    'novig': {'production':'keychain:prediction-arb.novig.production/market-data','qa':'keychain:prediction-arb.novig.qa/market-data'},
    'prophetx': {'production':'keychain:prediction-arb.prophetx.production/trading-api','sandbox':'keychain:prediction-arb.prophetx.sandbox/trading-api'},
}


def validate_sources(spec):
    sources=spec['native_sources']
    if not isinstance(sources,dict) or set(sources)!=set(SOURCES): raise ValueError('four explicit source slots required')
    for venue,c in sources.items():
        if not isinstance(c,dict):raise ValueError('source object required')
        if set(c)-{'transport','selected','state','environment','credential_reference','leagues','tournament_ids','poll_seconds','event_cap','market_cap','series','tags'}:
            raise ValueError('unexpected source configuration; secrets prohibited')
        if 'selected' in c and type(c['selected']) is not bool:raise ValueError('invalid selection')
        if c.get('state') not in ('enabled','disabled','not_configured','unselected'): raise ValueError('invalid source state')
        if c.get('transport','nbx' if venue=='novig' else 'native') not in (('nbx','graphql') if venue=='novig' else ('native',)):raise ValueError('invalid source transport')
        if c['state']!='enabled': continue
        if venue=='novig' and c.get('transport')=='graphql':
            if c.get('environment')!='public' or 'credential_reference' in c:raise ValueError('public GraphQL needs no credentials')
            continue
        for field in ('series','tags'):
            if field in c and (not isinstance(c[field],list) or not 1<=len(c[field])<=6 or any(not isinstance(x,str) or not x or not all(ch.isalnum() or ch in '_-' for ch in x) for x in c[field])):raise ValueError('invalid discovery scope')
        if c.get('environment') not in (('production',) if venue in SOURCES[:2] else tuple(REFERENCES[venue])): raise ValueError('environment required')
        if venue in REFERENCES and c.get('credential_reference')!=REFERENCES[venue][c['environment']]: raise ValueError('dedicated reference required')
        for k,lo,hi in [('poll_seconds',10,60),('event_cap',1,4),('market_cap',1,10)]:
            if type(c.get(k)) is not int or not lo<=c[k]<=hi: raise ValueError('invalid native bound')
        if venue=='novig' and (not c.get('leagues') or any(x not in ('NFL','NBA','MLB','NHL','NCAAF','NCAAB') for x in c['leagues'])): raise ValueError('explicit leagues required')
        if venue=='prophetx' and (not c.get('tournament_ids') or len(c['tournament_ids'])>6 or any(not str(x).isdigit() for x in c['tournament_ids'])): raise ValueError('native tournament IDs required')
    if spec.get('reference_enabled'): raise ValueError('B4 acquisition remains separate')
    if sum(len(c.get('leagues',[])) for c in sources.values() if c['state']=='enabled')>2: raise ValueError('bounded Novig league count')


def empty_catalog(state,reason=None):
    return dict(state=state,events=[],markets=[],selection=dict(ids=[],eligible=0),event_discovery=state,
                market_completeness='unestablished',source_error=reason,limitations=[])


def load_native_secret(venue,config):
    from keyring.backends.macOS import Keyring
    reference=REFERENCES[venue][config['environment']]
    if config['credential_reference']!=reference: raise ValueError('credential reference mismatch')
    service,account=reference.removeprefix('keychain:').split('/')
    try:
        value=json.loads(Keyring().get_password(service,account) or '{}')
        if 'environment' in value and value.pop('environment')!=config['environment']:raise ValueError('credential environment mismatch')
        keys=('client_id','client_secret') if venue=='novig' else ('access_key','secret_key')
        if set(value)!=set(keys) or any(not isinstance(value[k],str) or not value[k] for k in keys):raise ValueError()
        return value
    except Exception: raise ValueError('dedicated source credentials unavailable') from None


def listing_association(m):
    """Bind only observed native semantics; descriptions are not settlement rules."""
    native=json.loads(m.raw.json_text,parse_float=Decimal);venue=m.raw.ref.venue.value
    evidence=dict(event_id=m.raw.ref.event_id,market_id=m.raw.ref.market_id,
        source=m.raw.source,received_at=m.raw.received_at.isoformat(),sha256=sha256(m.raw.json_text.encode()).hexdigest())
    row=None
    if venue=='prophetx':
        from app.adapters.prophetx import market_key
        def leaves(items):
            for x in items:
                if x.get('market_strikes'):yield from leaves(x['market_strikes'])
                else:yield x
        row=next((x for x in leaves(native.get('data',{}).get(m.raw.ref.event_id,[])) if market_key(m.raw.ref.event_id,x)==m.raw.ref.market_id),None)
    return dict(**evidence,period=m.period or 'unknown',
        period_basis='native sub_type='+str(row.get('sub_type')) if row and m.period else 'native period not established',
        native_description=row.get('description') if row else None,
        settlement_rules=None,settlement_status='listing-specific settlement rules unverified')


def catalog_from(events,markets,environment,*,at=None):
    from app.normalization.observations import enrich_event
    from app.normalization.registry import Registry
    registry=Registry.load();cat=empty_catalog('enabled');cat['event_discovery']='bounded';cat['market_completeness']='bounded'
    objects={};by_event={}
    for e in events:
        enriched=enrich_event(e,environment=environment)
        participants={p.name:p.resolution.canonical_id for p in enriched.participants}
        league=enriched.league.canonical_id or e.league or 'unknown'
        er=dict(id=e.raw.ref.event_id,title=e.title,scheduled_start=e.scheduled_start.isoformat() if e.scheduled_start else None,
                participants=participants,identity='unresolved',canonical_key=None,exclusion=None,
                sport={'NFL':'american_football','NCAAF':'american_football','NBA':'basketball','NCAAB':'basketball','MLB':'baseball','NHL':'hockey'}.get(league,e.sport or 'unknown'),competition=league,
                native_event=json.loads(e.raw.json_text),provenance=dict(source=e.raw.source,received_at=e.raw.received_at.isoformat(),sha256=sha256(e.raw.json_text.encode()).hexdigest()))
        if e.raw.ref.venue.value=='prophetx':
            native=next((x for x in json.loads(e.raw.json_text).get('data',{}).get('sport_events',[]) if str(x.get('event_id'))==er['id']),{})
            if native.get('status')!='not_started':er['exclusion']='native event phase not verified pregame'
        by_event[er['id']]=er;cat['events'].append(er)
    for m in markets:
        er=by_event[m.raw.ref.event_id]
        # Native moneyline outcome labels may establish Novig participants only
        # when both resolve uniquely in the event's explicit league.
        mapped=[registry.resolve('team',o.label,league=er['competition']) for o in m.outcomes]
        ids=[r.canonical_id for r in mapped]
        if m.raw.ref.venue.value=='novig' and m.market_type.value=='moneyline' and len(ids)==2 and None not in ids and len(set(ids))==2:
            if not er['participants']:er['participants']={o.label:r.canonical_id for o,r in zip(m.outcomes,mapped)}
        people=list(er['participants'].values())
        if len(people)==2 and None not in people and len(set(people))==2 and er['scheduled_start']:
            er.update(identity='resolved',canonical_key=[er['scheduled_start'],sorted(people)])
        outcomes=[]
        if len(ids)==2 and None not in ids and set(ids)==set(people):
            outcomes=[dict(native_id=o.native_id,participant=registry.entities[r.canonical_id]['name'],predicate='win',native_label=o.label) for o,r in zip(m.outcomes,mapped)]
        period=m.period or 'unknown'
        row=dict(id=m.raw.ref.market_id,event_id=er['id'],title=m.title,market_type=m.market_type.value,period=period,
                 status=m.state.value,exclusion=None,product_outcomes=outcomes,terms={},
                 listing_association=listing_association(m),native_metadata=json.loads(m.raw.json_text),provenance=dict(source=m.raw.source,received_at=m.raw.received_at.isoformat(),sha256=sha256(m.raw.json_text.encode()).hexdigest()),
                 sides=[dict(id=o.native_id,label=o.label,purchase_support='supported' if outcomes else 'unknown') for o in m.outcomes])
        if m.market_type.value!='moneyline' or period!='full_game':row['exclusion']='unsupported family or period (B5)'
        elif not outcomes:row['exclusion']='unresolved native participants'
        elif m.state.value!='active':row['exclusion']='inactive or unknown market state'
        cat['markets'].append(row);objects[row['id']]=m
    from .continuous import select_inventory,now
    ids=[m['id'] for m in cat['markets'] if m['status']=='active' and not by_event[m['event_id']]['exclusion'] and by_event[m['event_id']]['scheduled_start'] and datetime.fromisoformat(by_event[m['event_id']]['scheduled_start'])>(at or now())][:10]
    cat['selection']=dict(ids=ids,eligible=len(ids))
    return cat,objects


class NativeVenue:
    """One source, bounded adapters, independent failure, shared journal and Stop."""
    def __init__(self,session,venue,config):
        self.session,self.venue,self.config=session,venue,config
        self.budget=PredictionBudget(session.spec['prediction']);self.adapters=[];self.adapter_by_market={};self.markets={}
        self.ever={k:set() for k in ('requested','acknowledged','receiving','usable')};self.groups={};self.serial=0
        self.state=config['state'];self.reason=None;self.closed=False;self.failed_markets=set();self.lock=asyncio.Lock()

    def health(self,state,reason=None,market_ids=None):
        self.state=state;self.reason=reason;self.session.health[self.venue]=state
        self.session.emit(self.venue,dict(type='source_health',state=state,gap_reason=reason,market_ids=market_ids))

    def retain(self,r):
        raw=r.body.encode()
        self.budget.charge_bytes(len(raw))
        self.session.emit(self.venue,dict(type='native_rest_observation',received_at=r.received_at.isoformat(),
            path=urlsplit(r.source).path,source_url=r.source,body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest(),
            environment=self.config['environment'],update_path='dated REST snapshot'))

    async def prepare(self):
        if self.adapters:return
        factory=getattr(self.session,'native_adapter_factory',None)
        if factory:
            if self.session.spec['mode']!='mock':raise ValueError('injected adapter is fixture-only')
            self.adapters=await factory(self.venue,self.config,self.retain)
            return
        if self.session.spec['mode']!='real':raise ValueError('fixture adapter must be explicitly injected')
        secret=load_native_secret(self.venue,self.config)
        if self.venue=='novig':
            from app.adapters.novig import NovigAdapter
            self.adapters=[NovigAdapter(environment=self.config['environment'],**secret,league=league,max_requests=30,
                max_pages=1,page_size=self.config['event_cap'],max_markets=self.config['market_cap'],retries=0,max_bytes=2_000_000,observer=self.retain) for league in self.config['leagues']]
        else:
            from app.adapters.prophetx import ProphetXAdapter,Client,Credentials
            self.adapters=[ProphetXAdapter(Client(Credentials(self.config['environment'],**secret),request_budget=30,retries=0,byte_budget=2_000_000,observer=self.retain),tournament_ids=self.config['tournament_ids'])]

    def account(self):
        if not self.adapters:return
        if self.venue=='novig':
            self.budget.requests=sum(a.requests for a in self.adapters)
            self.budget.bytes=max(self.budget.bytes,sum(a.bytes for a in self.adapters))
        else:
            self.budget.requests=sum(30-a.client.remaining for a in self.adapters)
            self.budget.bytes=max(self.budget.bytes,sum(2_000_000-a.client.bytes_remaining for a in self.adapters))

    async def native_discover(self):
        async with self.lock:
            return await self._native_discover()

    async def _native_discover(self):
        if self.config['state']!='enabled':return empty_catalog(self.config['state']),{}
        if getattr(self,'discovery_failed',False):return empty_catalog('unavailable',self.reason),{}
        try:
            await self.prepare();events=[];markets=[];bindings={}
            for adapter in self.adapters:
                found=await adapter.discover_events()
                for e in found[:self.config['event_cap']]:
                    events.append(e)
                    for m in (await adapter.discover_markets(e.raw.ref.event_id))[:self.config['market_cap']]:
                        markets.append(m);bindings[m.raw.ref.market_id]=adapter
            cat,objects=catalog_from(events,markets,self.config['environment'])
            cat['selection']['ids']=cat['selection']['ids'][:self.config['market_cap']]
            cat.update(semantics=SEMANTICS[self.venue],environment=self.config['environment'],update_path='dated REST snapshot')
            cat['limitations']=[SEMANTICS[self.venue]['fees'],SEMANTICS[self.venue]['settlement']]
            self.markets=objects;self.adapter_by_market=bindings
            self.health('awaiting_snapshot')
            return cat,objects
        except asyncio.CancelledError:raise
        except Exception as exc:
            self.health('unavailable',type(exc).__name__)
            self.discovery_failed=True
            return empty_catalog('unavailable',type(exc).__name__),{}
        finally:self.account()

    async def discover(self):
        return (await self.session.discovery.discover())[self.venue]

    async def run(self,markets):
        if self.config['state']!='enabled':
            self.health(self.config['state']);await self.session.stop_event.wait();return
        while not self.session.stop_event.is_set():
            cat=(self.session.discovery.inventory or {}).get(self.venue,{})
            for mid in cat.get('selection',{}).get('ids',[]):
                if mid in self.failed_markets:continue
                try:
                    a=self.adapter_by_market[mid];self.ever['requested'].add(mid)
                    async with self.lock:
                        book=await a.get_snapshot(mid)
                        m=self.markets[mid]
                    if self.session.stop_event.is_set():return
                    self.session.emit(self.venue,dict(type='market_selected',market=json.loads(json.dumps(asdict(m),default=str))))
                    native=asdict(book);book=purchase_book(book)
                    from app.arbitrage import book_observations
                    from app.storage.workflow import packet
                    packets=[]
                    observations=book_observations(book,environment=self.config['environment'],evidence_class='current' if self.session.spec['mode']=='real' else 'synthetic',source_time_semantics='unknown')
                    # ProphetX has verified prices but no supported sized ladders.
                    prices={q.outcome_id:q for q in getattr(book,'normalized_quotes',())}
                    for obs in observations:
                        if obs.quote.outcome_id in prices:obs=replace(obs,quote=prices[obs.quote.outcome_id])
                        p=packet(obs);p['raw_b64']=base64.b64encode(p.pop('raw')).decode();packets.append(p)
                    self.health('connected',market_ids=[mid])
                    self.session.emit(self.venue,dict(type='prediction_book',book=json.loads(json.dumps(asdict(book),default=str)),
                        native_book=json.loads(json.dumps(native,default=str)),packets=packets,environment=self.config['environment'],
                        update_path='dated REST snapshot',receipt_semantics='HTTP receipt; source age and streaming synchronization unverified'))
                    self.ever['receiving'].add(mid)
                    await self.session.queue.join()
                except asyncio.CancelledError:raise
                except Exception as exc:
                    from app.diagnostics import failure
                    failure(__name__,'native_snapshot',exc)
                    self.health('unavailable',type(exc).__name__,[mid])
                    # Isolate this market; no automatic retry of failed requests.
                    self.failed_markets.add(mid)
                finally:self.account()
            await self.session.pause(self.config['poll_seconds'])

    def snapshot(self):
        return dict(state=self.state,reason=self.reason,requests=self.budget.requests,body_bytes_charged=self.budget.bytes,
            connection_attempts=0,update_path='dated REST snapshot',usable=0,receiving=len(self.ever['receiving']),
            requested=len(self.ever['requested']),acknowledged=0,semantics=SEMANTICS[self.venue])

    def safety_exclusions(self):return set()

    async def aclose(self):
        self.closed=True
        for a in self.adapters:await a.aclose()
        if self.config['state']=='enabled':
            self.state='disconnected';self.reason='source stopped'
            self.session.health[self.venue]='disconnected'
            if not self.session.intake_closed:
                self.health('disconnected','source stopped')
