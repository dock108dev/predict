"""One bounded multi-game run, using E6's journal, lifecycle and native streams."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import json
from app.adapters.kalshi import KalshiAdapter
from app.adapters.polymarket_us import next_market_data
from app.normalization.registry import Registry
from .prediction_discovery import NFLPolymarketAdapter, participant_mapping, validate_pregame
from .prediction_producer import MockREST, PredictionProducer
from .transport_session import TransportSession
from .venue_access import ENDPOINTS, REFERENCES


def native_identity(k, p, km, pm):
    """Resolve actual native outcomes, never infer a side from array order."""
    registry=Registry.load()
    def team(name):
        r=registry.resolve('team',name,league='NFL')
        if r.status!='resolved':raise ValueError('unresolved native outcome: '+str(name))
        return r.canonical_name,r.canonical_id
    _,ka=participant_mapping(k);_,pa=participant_mapping(p)
    ids=set(ka.values())
    if None in ids or len(ids)!=2 or ids!=set(pa.values()) or k.scheduled_start!=p.scheduled_start:raise ValueError('incompatible event identity')
    kd=next(m for m in km.raw.decode()['markets'] if m['ticker']==km.raw.ref.market_id)
    kn,ki=team(kd['yes_sub_title'])
    pmdata=next_market_data(pm);sides=pmdata['marketSides']
    if len(sides)!=2 or {s['long'] for s in sides}!={True,False}:raise ValueError('ambiguous native long/short')
    ps={};pids=set()
    for side in sides:
        name,cid=team(side['team']['name']);pids.add(cid)
        ps['polymarket_us:'+str(side['id'])]=dict(native_id=str(side['id']),participant=name,predicate='win',native_label='Long' if side['long'] else 'Short')
    if pids!=ids or ki not in ids or len(ps)!=2:raise ValueError('outcome identity differs from participants')
    teams=sorted(registry.entities[i]['name'] for i in ids)
    sd={'kalshi:yes':dict(native_id='yes',participant=kn,predicate='win'), 'kalshi:no':dict(native_id='no',participant=kn,predicate='not_win'),**ps}
    opposite=next(key for key,s in ps.items() if s['participant']!=kn)
    same=next(key for key,s in ps.items() if s['participant']==kn)
    sources={v:dict(event_id=e.raw.ref.event_id,market_id=m.raw.ref.market_id,participant_mapping=mapping,credential_reference=REFERENCES[v],entitlement_reference='docs/multi-game-dashboard-report.md') for v,e,m,mapping in [('kalshi',k,km,ka),('polymarket_us',p,pm,pa)]}
    return dict(id=k.raw.ref.event_id+'__'+p.raw.ref.event_id,title=k.title,scheduled_start=k.scheduled_start.isoformat(),teams=teams,sides=sd,sources=sources,
        candidates=[('cross-yes',kn+' YES + opposing US outcome',('kalshi:yes',opposite)),('kalshi-pair',kn+' YES + NO',('kalshi:yes','kalshi:no')),('cross-no',kn+' NO + US win',('kalshi:no',same))])


def common_events(events, now):
    buckets={v:{} for v in events};excluded=[]
    for v,values in events.items():
        for e in values:
            n,m=participant_mapping(e)
            try:
                validate_pregame(e,as_of=now)
                if n.league.canonical_id!='NFL' or len(m)!=2 or None in m.values() or len(set(m.values()))!=2:raise ValueError('unresolved participants')
                if e.scheduled_start<=now+timedelta(seconds=300):raise ValueError('less than five minutes before kickoff')
                key=(e.scheduled_start,tuple(sorted(m.values())))
                buckets[v].setdefault(key,[]).append(e)
            except ValueError as exc:excluded.append(dict(venue=v,event=e.raw.ref.event_id,reason=str(exc)))
    pairs=[]
    for key in sorted(set(buckets['kalshi'])|set(buckets['polymarket_us'])):
        a=buckets['kalshi'].get(key,[]);b=buckets['polymarket_us'].get(key,[])
        if len(a)==len(b)==1:pairs.append((a[0],b[0]))
        else:
            for v,es in [('kalshi',a),('polymarket_us',b)]:
                excluded.extend(dict(venue=v,event=e.raw.ref.event_id,reason='ambiguous match' if len(a)>1 or len(b)>1 else 'no exact participant/schedule overlap') for e in es)
    return pairs,excluded


class Discovery:
    def __init__(self,session):
        self.session=session;self.lock=asyncio.Lock();self.adapters={};self.games=[];self.markets={};self.last=None
        self.coverage=dict(found={},common=0,selected=0,excluded=[],truncated_by_limit=0,catalog_truncated=False)
    async def discover(self):
        async with self.lock:
            loop=asyncio.get_running_loop()
            if self.last is not None and loop.time()-self.last<40:return self.markets
            s=self.session
            if not self.adapters:
                for v in ENDPOINTS:
                    producer=s.producers[v]
                    client=MockREST(ENDPOINTS[v]['rest'],s.spec['prediction'],lambda r,v=v:s.emit(v,r),5,producer.budget,venue=v,credential=producer.credential)
                    a=(KalshiAdapter(client=client,series=('KXNFLGAME',),max_pages=2,page_size=200,max_requests=64,retries=0,pregame_only=False) if v=='kalshi' else NFLPolymarketAdapter(client=client,max_pages=10,page_size=5,request_cap=64,attempts=1))
                    self.adapters[v]=a;producer.adapter=a
                # Recheck the actual account limits within this run's shared request budget.
                access={}
                for path in ('/trade-api/v2/account/limits','/trade-api/v2/account/endpoint_costs'):
                    r=await self.adapters['kalshi'].client.get(ENDPOINTS['kalshi']['rest']+path)
                    if r.status_code!=200:raise ValueError('read-only API limits unavailable')
                    access[path]=r.json()
                from app.dashboard.e6_live import save_json
                save_json(s.output/'account-api-limits.json',access)
                lim=access['/trade-api/v2/account/limits']
                if lim.get('read',{}).get('refill_rate',0)<10:raise ValueError('insufficient read budget')
            events={}
            for v,a in self.adapters.items():
                a.events.clear();a.markets.clear();events[v]=await a.discover_events()
            truncated=any(self.adapters['kalshi'].discovery_truncated.values()) or self.adapters['polymarket_us'].discovery_truncated
            if truncated:raise ValueError('catalog truncated; earliest common games unestablished')
            if self.games:
                # Refresh only selected identities; never replace a missing game silently.
                for game in self.games:
                    ms={}
                    es={}
                    for v in ENDPOINTS:
                        source=game['sources'][v]
                        matches=[e for e in events[v] if e.raw.ref.event_id==source['event_id']]
                        if len(matches)!=1:raise ValueError('selected event disappeared')
                        es[v]=matches[0]
                        markets=await self.adapters[v].discover_markets(source['event_id'])
                        matches=[m for m in markets if m.raw.ref.market_id==source['market_id']]
                        if len(matches)!=1:raise ValueError('selected market disappeared')
                        ms[v]=matches[0];validate_pregame(es[v],ms[v])
                        if ms[v].state.value!='active':raise ValueError('selected market inactive')
                    if native_identity(es['kalshi'],es['polymarket_us'],ms['kalshi'],ms['polymarket_us'])!=game:raise ValueError('selected identity changed')
                    for v in ENDPOINTS:s.emit(v,dict(type='market_selected',game_id=game['id'],market=json.loads(json.dumps(asdict(ms[v]),default=str))))
            else:
                pairs,excluded=common_events(events,datetime.now(timezone.utc))
                self.coverage.update(found={v:len(es) for v,es in events.items()},common=len(pairs),excluded=excluded,catalog_truncated=bool(truncated))
                self.markets={v:[] for v in ENDPOINTS}
                for k,p in pairs:
                    if len(self.games)==getattr(s,'max_games',6):
                        self.coverage['truncated_by_limit']+=1
                        self.coverage.setdefault('beyond_limit',[]).append(dict(event=k.raw.ref.event_id,title=k.title,scheduled_start=k.scheduled_start.isoformat()))
                        continue
                    try:
                        ms={}
                        for v,e in [('kalshi',k),('polymarket_us',p)]:
                            markets=await self.adapters[v].discover_markets(e.raw.ref.event_id)
                            markets=sorted([m for m in markets if m.state.value=='active' and m.market_type.value=='moneyline'],key=lambda m:m.raw.ref.market_id)
                            if len(markets)!=(2 if v=='kalshi' else 1):raise ValueError('ambiguous active moneyline count')
                            ms[v]=markets[0];validate_pregame(e,ms[v])
                        game=native_identity(k,p,ms['kalshi'],ms['polymarket_us'])
                        # Terms must support the same bounded normal-winner assessment.
                        from app.opportunities.board import assess
                        meta=[dict(type='market_selected',source=v,observed_at=datetime.now(timezone.utc).isoformat(),market=json.loads(json.dumps(asdict(m),default=str))) for v,m in ms.items()]
                        assess(meta,datetime.now(timezone.utc).isoformat(),game)
                    except ValueError as exc:
                        self.coverage['excluded'].append(dict(event=k.raw.ref.event_id,reason=str(exc)));continue
                    self.games.append(game)
                    for v,m in ms.items():
                        self.markets[v].append(m)
                        s.emit(v,dict(type='market_selected',game_id=game['id'],market=json.loads(json.dumps(asdict(m),default=str))))
                self.coverage['selected']=len(self.games)
                s.emit('session',dict(type='multi_game_selection',games=self.games,coverage=self.coverage))
                from app.dashboard.e6_live import save_json
                save_json(s.output/'selection.json',dict(games=self.games,coverage=self.coverage))
                if not self.games:raise ValueError('no suitable overlapping games')
            for game in self.games:
                for v in ENDPOINTS:s.emit(v,dict(type='discovery_validated',game_id=game['id'],**{k:game['sources'][v][k] for k in ('event_id','market_id')},scheduled_start=game['scheduled_start'],mapping_revision='multi-game-native-1'))
            self.last=loop.time()
            return self.markets


class MultiProducer(PredictionProducer):
    async def discover(self):return (await self.discovery.discover())[self.venue]


class MultiSession(TransportSession):
    async def start(self):
        await super().start()
        # super.start schedules run; no yield occurs before these producers replace the idle defaults.
        self.discovery=Discovery(self)
        self.producers={v:MultiProducer(v,self.spec,self.endpoints[v]['rest'],self.endpoints[v]['ws'],self.emit,self.set_health,credential=(self.credentials or {}).get(v)) for v in ENDPOINTS}
        for p in self.producers.values():p.discovery=self.discovery
        return self.sid
    def emit(self,source,record):
        if record['type']=='prediction_book' and hasattr(self,'discovery'):
            ref=record['book']['raw']['ref']
            game=next((g for g in self.discovery.games if g['sources'][source]['market_id']==ref['market_id'] and g['sources'][source]['event_id']==ref['event_id']),None)
            if game is None:raise ValueError('book outside selected games')
            if datetime.now(timezone.utc)>=datetime.fromisoformat(game['scheduled_start']):
                self.request_stop('pregame_cutoff');return False
            record=dict(record,game_id=game['id'])
        return super().emit(source,record)
