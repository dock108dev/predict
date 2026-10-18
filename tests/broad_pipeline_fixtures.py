"""Authored source transports; no live acquisition or owner-state access."""
from copy import deepcopy
from datetime import datetime, timezone

from app.collection import coverage
from app.collection.native_scope_bindings import selectors_for
from app.collection.native_selectors import LEAGUES
from app.comparison.combined_native import normalize
from tests.multisport_fixtures import source_case, fake_discovery, current_book
from tests.test_current_multisport_ingress import worker


def partial_case(sport, family, period, token, *, clock=None):
    case=source_case(sport,family,token,clock=clock)
    selector=selectors_for(f'{sport}/{period}/{family}')[0]['binding']
    original=case['series'];series=selector['series_ticker'];case['series']=series
    event=case['events']['kalshi'];native=case['markets']['kalshi']
    eid=event['event_ticker'].replace(original,series,1)
    event.update(event_ticker=eid,series_ticker=series)
    native.update(event_ticker=eid,ticker=native['ticker'].replace(original,series,1))
    case['milestone']['related_event_tickers']=[eid]
    case['milestone']['details']['main_game_event_ticker']=eid
    phrase='the 1st half of the game' if period=='first_half' else 'the first '+period.split('_')[1]+' innings of the game'
    native['rules_primary']=native['rules_primary'].replace('in the game','in '+phrase)
    if family=='moneyline':
        phrase=phrase.replace('1st half','1st Half')
        native['rules_primary']=native['rules_primary'].replace('wins the game','wins '+phrase)
        if period=='first_half':native['yes_sub_title']+=' wins 1st Half'
    native['rules_secondary']='Overtime is excluded.'+(' Extra innings are excluded.' if sport=='MLB' else '')
    us=case['markets']['polymarket_us']
    from app.collection.public_contracts import load
    types=[kind for kind,row in load()['us_types'].items() if sport in row['competitions'] and
           (row['family'],row['period'])==(family,period)]
    if types:
        us['sportsMarketType']=types[0]
        us['description']=us['description'].split('. Full game')[0]+'. Overtime is excluded.'
        us['description']=us['description'].replace('in the game','in the first half of the game')
        if family=='moneyline':
            sides=us['marketSides'];home=sides[0]['team']['name'];away=sides[1]['team']['name']
            us['description']='1st Half Winner settles Yes if '+home+' outscores '+away+' in the first half of the game. Overtime is excluded. Equality is settled as No.'
            sides[1]['team']=deepcopy(sides[0]['team']);sides[1]['teamId']=sides[0]['teamId']
            sides[0]['description']='Yes';sides[1]['description']='No'
        case['events']['polymarket_us']['markets']=[deepcopy(us)]
    case['period']=period
    return case


async def captured_partial(case, venue):
    """Exact typed metadata ingress, independent of auto-discovery settings."""
    sport,family,period=case['league'],case['family'],case['period']
    owner,_=worker(venue,[sport],[family]);fake_discovery(owner,[case])
    owner._coverage_sport=sport;owner._coverage_checked=set()
    if venue=='kalshi':
        selector=selectors_for(f'{sport}/{period}/{family}')[0]
        await owner.get(selector['path'],dict(selector['params'],limit=5),'events',selector['binding'])
        await owner.get('/trade-api/v2/markets',dict(event_ticker=case['events'][venue]['event_ticker'],limit=50),'markets',selector['binding'])
    else:
        await owner.get('/v1/events',dict(tagSlug=LEAGUES[sport],limit=5,offset=0),'events')
        await owner.get('/v1/markets',dict(gameId=case['events'][venue]['gameId'],limit=50,offset=0),'markets')
    at=case['clock'].isoformat()
    catalog=coverage.catalog(owner.pages,venue,datetime.fromisoformat(at),compact_output=False)
    book=current_book(case,venue,clock=case['clock'])
    observations=[dict(type='prediction_book',source=venue,observed_at=at,book=book)]
    rows,excluded=normalize(dict(id='authored-partial-catalog',record=dict(source=venue,value=dict(inventory=catalog))),
        [dict(id='authored-partial-book',record=dict(retained_at=at,value=dict(observations=observations)))],at=at,include_missing=True)
    return rows,excluded,book,catalog


async def captured_core_matrix(clock=None):
    from tests.multisport_fixtures import SPORTS,FAMILIES
    clock=clock or datetime.now(timezone.utc)
    cases=[source_case(sport,family,'joint-matrix-'+sport+'-'+family,clock=clock)
           for sport in SPORTS for family in FAMILIES]
    rows=[];books=[]
    for venue in ('kalshi','polymarket_us'):
        owner,published=worker(venue);fake_discovery(owner,cases);await owner.discover()
        source_books=[current_book(case,venue,clock=clock) for case in cases]
        captured,excluded=normalize(dict(id='authored-joint-'+venue,
            record=dict(source=venue,value=dict(inventory=published[-1]))),
            [dict(id='authored-joint-books-'+venue,record=dict(retained_at=clock.isoformat(),
                value=dict(observations=[dict(type='prediction_book',source=venue,
                    observed_at=clock.isoformat(),book=book) for book in source_books])))],
            at=clock.isoformat(),include_missing=True)
        if excluded:raise AssertionError(excluded)
        rows.extend(captured);books.extend(source_books)
    return rows,books
