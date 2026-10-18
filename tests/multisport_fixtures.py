"""Generated, disposable source/type examples; never an application admission list."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from types import SimpleNamespace

SPORTS=('NFL','NCAAF','NBA','NCAAB','MLB','NHL')
FAMILIES=('moneyline','spread','total')


def compatible_winner_equality(state, venues=('novig','prophetx','polymarket_us')):
    """Authored temporal-selection context; does not rewrite source fixtures.

    Native tie cashflows and sportsbook refunds can differ in authentic inputs.
    Temporal/price-selection tests supply compatible equality explicitly so they
    continue testing freshness/reselection rather than asserting that difference
    disappeared. Original prices, sides, descriptions and clocks stay untouched.
    """
    from app.dashboard.current_contract import quotes_of
    for event in state['events']:
        for group in event['groups']:
            if group['market'] != 'winner':
                continue
            for outcome in group['outcomes']:
                for quote in quotes_of(outcome):
                    if quote['venue'] not in venues:
                        continue
                    facts = quote.setdefault('native_contract', {}).setdefault('same_outcome', {})
                    facts['equality'] = dict(treatment='predicate',payout=None,refund_fees='not_applicable',unknown_reason=None)


def source_case(league, family, token, *, clock=None, line=None):
    """New event identity per token, with previously supported participants."""
    from app.collection.admission_enrichment import repair_registry, TEAM_KEYS
    from app.collection.native_scope_bindings import selectors_for
    from app.collection.native_selectors import LEAGUES
    registry=repair_registry();data=json.loads(registry.to_json())
    mappings=[m for m in data['native_mappings'] if m['kind']=='team' and m['venue']=='kalshi'
              and m.get('environment')=='production' and m.get('league')==league]
    unique={m['target']:m['native_id'] for m in mappings}
    home,away=sorted(unique)[:2]
    teams=[dict(id=unique[cid],name=registry.entities[cid]['name'],league=LEAGUES[league],ordering=role)
           for cid,role in ((home,'home'),(away,'away'))]
    clock=clock or datetime.now(timezone.utc)
    start=(clock+timedelta(days=2)).replace(microsecond=0).isoformat()
    game='synthetic-occurrence-'+token
    series=selectors_for(league+'/full_game/'+family)[0]['binding']['series_ticker']
    kevent=series+'-UNSEEN-'+token;kmarket=kevent+'-HOME'
    uevent=str(int(sha256((token+league).encode()).hexdigest()[:10],16));umarket=uevent+'1'
    unit='runs' if league=='MLB' else 'goals' if league=='NHL' else 'points'
    line=str(line if line is not None else ('45.5' if family=='total' else '3.5'))
    common=dict(game_id=game,game_number=1,original_start=start,schedule_status='original',
                season='2026-2027' if league in ('NBA','NCAAB','NHL') else '2026',stage='regular_season',competition=league,home=home,away=away,scheduled_start=start)
    detail=dict(season=dict(year=2026,type='REG',name='2026-2027' if league in ('NBA','NCAAB','NHL') else '2026'),home_team_id=unique[home],away_team_id=unique[away],
                main_game_event_ticker=kevent,game_number=1,original_start=start,schedule_status='original',status='scheduled')
    milestone=dict(id='milestone-'+token,source_id=game,source_provider='sportradar',category='Sports',
        type={'NFL':'football_game','NCAAF':'football_game','NBA':'basketball_game','NCAAB':'basketball_game','MLB':'baseball_game','NHL':'hockey_match'}[league],
        start_date=start,related_event_tickers=[kevent],details=detail)
    knative=dict(ticker=kmarket,event_ticker=kevent,title=teams[0]['name']+' '+family,status='active',
        yes_sub_title=teams[0]['name'],no_sub_title='No',custom_strike={TEAM_KEYS[league]:unique[home]})
    if family=='moneyline':
        knative.update(strike_type='structured',rules_primary='If '+teams[0]['name']+' wins the game, then the market resolves to Yes.')
    else:
        knative.update(strike_type='greater',floor_strike=line,cap_strike=None)
        if family=='spread':
            knative.update(yes_sub_title=teams[0]['name']+' wins by over '+line,
                rules_primary='If '+teams[0]['name']+' wins by more than '+line+' '+unit+' in the game, then the market resolves to Yes.')
        else:
            knative.update(yes_sub_title='Over '+line,custom_strike={},
                rules_primary='If '+teams[0]['name']+' and '+teams[1]['name']+' collectively score more than '+line+' '+unit+' in the game, then the market resolves to Yes.')
    suffix={'moneyline':'winner','spread':'spread','total':'total'}[family]
    prefix={'NFL':'football','NCAAF':'football','NBA':'basketball','NCAAB':'basketball','MLB':'baseball','NHL':'hockey'}[league]
    unative=dict(id=umarket,slug='generated-'+league.lower()+'-'+family+'-'+token,
        question=teams[0]['name']+' '+family,status='MARKET_STATE_OPEN',active=True,closed=False,
        marketType={'moneyline':'moneyline','spread':'spreads','total':'totals'}[family],
        sportsMarketType=prefix+'_team_full_game_'+suffix,gameStartTime=start,line=line,
        marketSides=[dict(id=umarket+'L',marketId=umarket,long=True,teamId=teams[0]['id'],team=deepcopy(teams[0]),description=teams[0]['name']),
                     dict(id=umarket+'S',marketId=umarket,long=False,teamId=teams[1]['id'],team=deepcopy(teams[1]),description=teams[1]['name'])])
    if family=='moneyline':unative['description']='This market settles Yes if '+teams[0]['name']+' wins the game.'
    elif family=='spread':
        from decimal import Decimal
        signed=format(-Decimal(line),'f');unative['line']=signed
        unative['marketSides'][0]['description']=signed;unative['marketSides'][1]['description']=line
        unative['description']='This market will settle to Yes if '+teams[0]['name']+' covers a '+signed+' '+unit.removesuffix('s')+' spread in the game.'
    else:
        for side,label in zip(unative['marketSides'],('Over','Under')):
            side['description']=label;side.pop('team');side.pop('teamId')
        unative['description']='This market will settle to Yes if '+teams[0]['name']+' and '+teams[1]['name']+' combine for more than '+line+' '+unit+' in the game.'
    scoring={'NFL':'Full game includes overtime.','NCAAF':'Full game includes overtime.',
        'NBA':'Full game includes overtime.','NCAAB':'Full game includes overtime.',
        'MLB':'Full game includes extra innings.','NHL':'Full game includes overtime and shootout; official final score.'}[league]
    knative['rules_secondary']=scoring;unative['description']+=' '+scoring
    if family=='moneyline':
        equality_clause=' If the game ends in a tie, the market will settle to $0.50.'
        knative['rules_secondary']+=equality_clause;unative['description']+=equality_clause
    event_k=dict(event_ticker=kevent,series_ticker=series,title=teams[1]['name']+' at '+teams[0]['name'])
    event_u=dict(id=uevent,gameId=int(uevent),sportradarGameId=game,title=event_k['title'],
        startTime=start,active=True,closed=False,ended=False,period='NS',teams=deepcopy(teams),markets=[deepcopy(unative)],
        season='2026-2027' if league in ('NBA','NCAAB','NHL') else '2026',stage='regular_season',gameNumber=1,originalStartTime=start,rescheduledFromGameId=None)
    return dict(league=league,family=family,token=token,event=common,events={'kalshi':event_k,'polymarket_us':event_u},
        markets={'kalshi':knative,'polymarket_us':unative},milestone=milestone,series=series,clock=clock)


def fake_discovery(worker, cases):
    """Install bounded fake HTTP on a real worker; real catalog/admission executes.

    cases is a mutable list: append after startup to prove recurring new discovery.
    """
    calls=[]
    async def get(path,params,field=None,scope=None):
        from app.collection.native_selectors import LEAGUES
        venue=worker.venue
        if field=='events':
            relevant=[c for c in cases if (c['series']==params.get('series_ticker') if venue=='kalshi'
                else LEAGUES[c['league']]==params.get('tagSlug'))]
            offset=int(params.get('cursor','next-0').removeprefix('next-')) if venue=='kalshi' else params.get('offset',0)
            limit=params.get('limit',5);window=relevant[offset:offset+limit]
            rows=[deepcopy(c['events'][venue]) for c in window]
            payload=dict(events=rows,**({'cursor':'next-'+str(offset+limit) if offset+limit<len(relevant) else '',
                'milestones':[deepcopy(c['milestone']) for c in window]} if venue=='kalshi' else {}))
        else:
            relevant=[c for c in cases if (c['events'][venue]['event_ticker']==params.get('event_ticker') if venue=='kalshi'
                else (params.get('gameId') is not None and str(c['events'][venue].get('gameId'))==str(params.get('gameId'))) or path.endswith('/'+c['markets'][venue]['id']))]
            rows=[deepcopy(c['markets'][venue]) for c in relevant]
            payload=dict(markets=rows,**({'cursor':''} if venue=='kalshi' else {})) if field=='markets' else dict(market=rows[0])
        raw=json.dumps(payload).encode();at=datetime.now(timezone.utc).isoformat()
        page=dict(source=venue,path=path,params=deepcopy(params),status=200,complete=True,usable_metadata=True,
            received_at=at,body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest(),
            native_binding_revision='live-native-binding-2',v1_comparison_policy='manual-comparison-2')
        if scope:page.update(native_scope_binding=scope,native_scope_policy='native-scope-bindings-v1')
        worker.pages.append(page);worker._coverage_checked.add(worker._coverage_sport)
        calls.append(dict(path=path,params=deepcopy(params),field=field))
        return rows if field else payload
    worker.get=get
    return calls


def current_book(case, venue, *, clock=None, price='0.51'):
    clock=clock or datetime.now(timezone.utc)
    native=case['markets'][venue];event=case['events'][venue]
    mid=native['ticker'] if venue=='kalshi' else native['id']
    eid=event['event_ticker'] if venue=='kalshi' else event['id']
    sides=['yes','no'] if venue=='kalshi' else [s['id'] for s in native['marketSides']]
    return dict(raw=dict(ref=dict(venue=venue,event_id=eid,market_id=mid),source='generated-fake-transport',
        received_at=clock.isoformat(),exchange_at=clock.isoformat(),json_text='{}',kind='observation'),
        state='active',sync='synchronized',sequence='1',quantity_unit='contracts',outcomes=[dict(outcome_id=s,
        asks=dict(depth='full',levels=[dict(price=dict(value=price),quantity=dict(value='10',unit='contracts'))]),bids=None) for s in sides])
