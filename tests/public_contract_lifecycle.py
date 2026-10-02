"""Explicitly synthetic documented source formats in ordinary owned sessions."""
import asyncio,json
from copy import deepcopy
from tests.mlb_preview import Session as Base, owner as base_owner
from tests.test_nfl_resolution import fixture,rec
from app.collection.transport_session import ObservationJournal
from app.dashboard.session_projection import SessionProjection
from app.resolution.source_adapters import adapt
from app.resolution.core import target

AT='2026-10-04T22:00:00Z'

def rows_fixture():
    rows,_,_,_=fixture('moneyline','full_game')
    for src in ('novig','prophetx'):
        rows[1]['inventory'][src]=json.loads(json.dumps(rows[1]['inventory']['polymarket_us']).replace('polymarket_us',src))
        for row in list(rows):
            if row.get('source')=='polymarket_us':rows.append(json.loads(json.dumps(row).replace('polymarket_us',src)))
    return rows


def sequence(s):
    records=[];queries={}
    def context(source,format):
        g=next(g for g in s['games'] if set(g['sources'])=={'kalshi','polymarket_us'} if source in ('kalshi','polymarket_us','odds_api')) if source in ('kalshi','polymarket_us','odds_api') else next(g for g in s['games'] if set(g['sources'])=={'kalshi',source})
        e=next(v['catalog']['events'][0] for v in s['sources'] if v['source_id']=='kalshi')
        contract=next(k for k in g['sides'] if k.startswith(('kalshi:yes:' if source=='kalshi' else 'polymarket_us:' if source=='odds_api' else source+':')))
        native=dict(g['sources'][source if source!='odds_api' else 'kalshi'],outcome_id=g['sides'][contract]['native_id'])
        if source=='odds_api':native=dict(event_id='SYNTHETIC-ODDS-E',market_id='SYNTHETIC-scores',outcome_id='SYNTHETIC-pair')
        c=dict(source=source,native=native,source_event_id=native['event_id'],target=target(s,g,e),contract=contract,period='full_game')
        queries[format]=g['id'];return c
    def add(format,body,c,previous=None):
        at=f'2026-10-04T21:{len(records):02}:00Z'
        r=adapt(format,json.dumps(body),c,url='https://example.invalid/SYNTHETIC-documented-format/'+format,received_at=at,evidence_mode='synthetic',previous=previous)
        records.append(r);return r
    c=context('kalshi','kalshi_market');m=dict(market=dict(ticker=c['native']['market_id'],event_ticker=c['native']['event_id'],result=''))
    add('kalshi_market',m,c);m['market'].update(result='yes',settlement_ts='2026-10-04T21:00:00Z');add('kalshi_market',m,c)
    c=context('polymarket_us','us_instrument');c.update(instrument_symbol='SYNTHETIC-SYMBOL',instrument_market_id=c['native']['market_id'],side='long')
    m=dict(symbol=c['instrument_symbol'],priceScale='100',stats=None);add('us_instrument',m,c)
    m['stats']=dict(settlementPx='0',settlementPreliminary=False,settlementPriceCalculationMethod='SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_1',settlementSetTime='2026-10-04T21:02:00Z')
    a=add('us_instrument',m,c);m['stats'].update(settlementPx='100',settlementSetTime='2026-10-04T21:04:00Z');add('us_instrument',m,c,a)
    c=context('polymarket_us','us_retail');c.update(slug='SYNTHETIC-SLUG',slug_market_id=c['native']['market_id'],side='long')
    m=dict(slug=c['slug'],settlement=None);add('us_retail',m,c);m['settlement']='0.5';add('us_retail',m,c)
    c=context('novig','novig_v3_market');out=c['native']['outcome_id'];c['remediation_observed']=True
    m=dict(marketId=c['native']['market_id'],eventId=c['native']['event_id'],status='SETTLED',voids='FMV',outcomes=[dict(outcomeId=out,status='0.3'),dict(outcomeId='SYNTHETIC-other',status='0.7')])
    a=add('novig_v3_market',m,c);m['status']='CLOSED'
    for o in m['outcomes']:o['status']='TBD'
    b=add('novig_v3_market',m,c,a);m['status']='SETTLED';m['outcomes'][0]['status']='WIN';m['outcomes'][1]['status']='LOSS';add('novig_v3_market',m,c,b)
    c=context('prophetx','prophetx_order');c['order_id']='SYNTHETIC-ORDER'
    m=dict(data=dict(order_id=c['order_id'],market_id=c['native']['market_id'],sport_event_id=c['native']['event_id'],outcome_id=c['native']['outcome_id'],status='open',winning_status='tbd'),last_synced_at='2026-10-04T21:10:00Z')
    add('prophetx_order',m,c);m['data'].update(status='closed',winning_status='profit',settled_at='2026-10-04T21:10:00Z');add('prophetx_order',m,c)
    m['data']['winning_status']='draw';add('prophetx_order',m,c)
    c=context('odds_api','odds_scores');c.update(home_label='SYNTHETIC Home',away_label='SYNTHETIC Away')
    m=dict(id=c['native']['event_id'],sport_key='americanfootball_nfl',commence_time=c['target']['event']['scheduled_start'],completed=False,home_team=c['home_label'],away_team=c['away_label'],scores=None,last_update=None)
    add('odds_scores',m,c);m.update(completed=True,scores=[dict(name=c['home_label'],score='24'),dict(name=c['away_label'],score='17')],last_update='2026-10-04T21:13:00Z');add('odds_scores',m,c)
    return records,queries

class Session(Base):
    prefix='SYNTHETIC-public-resolution-'
    async def start(self):
        self.journal=ObservationJournal(self.output/(self.sid+'.jsonl'));self.state='running';self.queue=asyncio.Queue()
        for row in rows_fixture():
            row['session_id']=self.sid
            if row['type']=='session_started':row['spec']=self.spec
            self.append(row)
        self.target=self.projection.snapshot();self.records,self.queries=sequence(self.target)
        self.task=asyncio.create_task(self.produce())
    def emit(self,source,value):
        if self.stop_event.is_set():return False
        self.append(dict(value,source=source,session_id=self.sid,observed_at=value['resolution']['received_at']));return True

def owner(root):return base_owner(root,session_factory=Session)
