"""Offline arbitrage production exclusions and synthetic conditional arithmetic."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from pathlib import Path

from app.arbitrage import Observation, Policy, book_observations, detect
from app.adapters.kalshi import Response as KR, parse_market as km, parse_book as kb
from app.adapters.polymarket_us import Response as PR, parse_market as pm, parse_book as pb
from app.matching import Matcher
from app.matching_example import synthetic
from app.moneyline import MoneylineMatcher, observe
from app.moneyline_captures import captured_inputs
from app.settlement import DIMENSIONS, SCENARIOS, fact, profile
from app.fee_example import scenario
from app.models.core import (Venue, EvidenceKind, RawPayload, NativeRef, Quote,
                             QuoteSide, Probability, Quantity, MarketState)
from decimal import Decimal

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,9,12,2,tzinfo=timezone.utc)


def synthetic_inputs(price_a='0.40',price_b='0.40',exception='0.5',environment='synthetic'):
    """Invented prices/rules; real fee formulas retain all their conditions."""
    parents=Matcher()
    a=synthetic('ka',Venue.KALSHI,names=('Atlanta Falcons','Pittsburgh Steelers'),league='NFL',env=environment)
    b=synthetic('pm',Venue.POLYMARKET_US,names=('Atlanta Falcons','Pittsburgh Steelers'),league='NFL',env=environment)
    parents.ingest([a,b])
    kn={'title':'Synthetic contract','ticker':'contract','event_ticker':'ka','market_type':'binary','yes_sub_title':'Atlanta',
        'rules_primary':'If Atlanta wins the Atlanta vs Pittsburgh professional football game originally scheduled for Sep 13, 2026, then the market resolves to Yes.'}
    pn={'title':'Synthetic market','id':'market','marketType':'moneyline','sportsMarketType':'football_team_full_game_winner',
        'marketSides':[{'id':'a','marketId':'market','long':True,'teamId':49,'team':{'id':49,'name':'Atlanta Falcons'}},
                       {'id':'b','marketId':'market','long':False,'teamId':74,'team':{'id':74,'name':'Pittsburgh Steelers'}}]}
    text='Invented Slice 10 rules, not venue settlement evidence.'; h=sha256(text.encode()).hexdigest()
    rules=profile(sources=[{'url':'synthetic:slice-10','sha256':h,'text':text}],
        dimensions={k:fact('synthetic-common',evidence=h) for k in DIMENSIONS},
        payouts={k:{'kind':'fraction','value':exception,'evidence':h} for k in SCENARIOS},actor='synthetic-fixture')
    rows=[]; observations=[]; contexts={}
    for parent,native,venue,price in [(a,kn,Venue.KALSHI,price_a),(b,pn,Venue.POLYMARKET_US,price_b)]:
        response=(KR if venue==Venue.KALSHI else PR)(json.dumps(native),'synthetic:slice-10',NOW,EvidenceKind.SYNTHETIC)
        market=km(response,native,'ka','KXNFLGAME') if venue==Venue.KALSHI else pm(response,native,'pm')
        row=observe(market,parent,rules,native=native,
            context={'series_ticker':'KXNFLGAME','product_metadata':{'competition_scope':'Game'}} if venue==Venue.KALSHI else {'id':'pm'},artifact='synthetic:slice-10')
        rows.append(row)
        # Only these supplied acquisition sides exist; neither bid is used as an ask.
        side='yes' if venue==Venue.KALSHI else 'b'
        raw=replace(market.raw,exchange_at=NOW)
        q=Quote(raw=raw,outcome_id=side,state=MarketState.ACTIVE,
            ask=QuoteSide(price=Probability(value=Decimal(price)),quantity=Quantity(value=Decimal('100'),unit='contracts')),
            bid=QuoteSide(price=Probability(value=Decimal('0.01'))))
        observations.append(Observation(q,environment,'synthetic','synchronized','partial','advanced','snapshot',
            locks_clear=True,units_verified=True,minimum='1',increment='1',sizing_evidence='invented sizing fixture'))
        c=scenario(venue.value); c.pop('fills'); c.pop('outcomes')
        c.update(environment=environment,market_id=row['native_market_id'],applicability_evidence='invented synthetic scenario',assume_no_settlement_fee=True)
        contexts[(row['key'],side)]=c
    matcher=MoneylineMatcher(); matcher.update(parents,rows)
    return parents,matcher,observations,contexts,rows


def evaluate_fixture(data,**kwargs):
    p,m,obs,ctx,_=data
    return detect(p,m,obs,ctx,evaluation_time=NOW,fill_grouping='single_fill_per_leg',**kwargs)


def selected(report):
    return next(c for c in report['candidates'] if c['conditional_calculation'] is not None)


def historical(*, observation_factory=book_observations, report_builder=detect):
    parents,rows,_,coverage=captured_inputs()
    matcher=MoneylineMatcher(); matcher.update(parents,rows)
    observations=[]; artifacts=[]
    root=ROOT/'evidence/slice-4/public-20260912'
    meta=json.loads((root/'report.json').read_text())['responses']
    def kr(n):
        r=meta[n]; path=root/r['file']; artifacts.append(str(path.relative_to(ROOT)))
        return KR(path.read_text(),r['source'],datetime.fromisoformat(r['received_at']),EvidenceKind.OBSERVATION)
    mr=kr(3); market=km(mr,json.loads(mr.body)['market'],'KXNFLGAME-26SEP13ATLPIT','KXNFLGAME')
    book=kb(kr(4),market)
    observations.extend(observation_factory(book,environment='production',evidence_class='historical',
        source_time_semantics='unknown',locks_clear=None))
    root=ROOT/'evidence/slice-2/qualification-20260911T234447Z/live'
    meta=json.loads((root/'result.json').read_text())
    records=next(v for v in meta.values() if isinstance(v,list) and v and isinstance(v[0],dict) and 'file' in v[0])
    seen=set()
    for r in records:
        path=root/r['file']; body=path.read_text(); data=json.loads(body).get('marketData',{})
        slug=data.get('marketSlug')
        if slug in seen: continue
        row=next((x for x in rows if x['venue']=='polymarket_us' and x['native'].get('slug')==slug),None)
        if not row: continue
        seen.add(slug); artifacts.append(str(path.relative_to(ROOT)))
        native=row['native']; mr=PR(json.dumps({'market':native}),row['raw']['source'],datetime.fromisoformat(row['raw']['received_at']),EvidenceKind.OBSERVATION)
        market=pm(mr,native,row['native_event_id'])
        response=PR(body,'wss://api.polymarket.us/v1/ws/markets',datetime.fromisoformat(r['received_at']),EvidenceKind.OBSERVATION)
        # Parsing a retained image alone does not replay the subscription lifecycle.
        book=pb(response,data,market,stream=True)
        observations.extend(observation_factory(book,environment='production',evidence_class='historical',
            source_time_semantics='last_change',locks_clear=None,
            source_time_problem='subscription lifecycle not replayed; retained image only'))
    report=report_builder(parents,matcher,observations,{},evaluation_time=NOW,fill_grouping='single_fill_per_leg')
    report['capture_coverage']=coverage
    report['artifacts']={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in artifacts}
    report['coverage_note']='Only retained ATL/PIT Kalshi and available PMUS images; missing books are not invented. Fee contexts and verified sizing are unavailable for this replay.'
    return report


def examples():
    rows={}
    for name,pa,pb,ex in [('positive','0.4','0.4','0.5'),('negative','0.55','0.55','0.5'),
                           ('fees-eliminate-gap','0.49','0.49','0.5'),('exceptional-loss','0.4','0.4','0')]:
        rows[name]=evaluate_fixture(synthetic_inputs(pa,pb,ex))
    # .4 + .4 at 100: 80 cost + 1.68 Kalshi + 1.44 PMUS = 83.12.
    # A separately labeled reserve consumes the remaining 16.88 exactly.
    rows['zero']=evaluate_fixture(synthetic_inputs(),policy=Policy(execution_reserve_usd='16.88'))
    data=synthetic_inputs(); next(c for c in data[3].values() if c['venue']=='polymarket_us').pop('assume_no_settlement_fee')
    rows['unknown-fees']=evaluate_fixture(data)
    for name,changes in [('unavailable-size',{'units_verified':False}),('maker-dependent',{'role':'maker'}),
                         ('inactive',{}),('stale',{}),('skew',{}),('duplicate-liquidity',{})]:
        data=synthetic_inputs(); obs=data[2]
        obs[0]=replace(obs[0],**changes)
        if name=='inactive': obs[0]=replace(obs[0],quote=replace(obs[0].quote,state=MarketState.CLOSED))
        if name in ('stale','skew'):
            age=31 if name=='stale' else 6
            obs[0]=replace(obs[0],quote=replace(obs[0].quote,raw=replace(obs[0].quote.raw,received_at=NOW-timedelta(seconds=age),exchange_at=NOW-timedelta(seconds=age))))
        if name=='duplicate-liquidity': obs.extend(deepcopy(obs))
        rows[name]=evaluate_fixture(data)
    expected={'positive':'16.88','zero':'0.00','negative':'-13.22','fees-eliminate-gap':'-1.25','exceptional-loss':'-83.12'}
    for name,profit in expected.items():
        assert Decimal(selected(rows[name])['conditional_calculation']['worst_case_profit'])==Decimal(profit),(name,selected(rows[name])['conditional_calculation']['worst_case_profit'])
    return {'description':'Offline diagnostics; all positive examples remain conditional under existing fee evidence. No synthetic or historical result is a current production opportunity.',
            'historical_production':historical(),'synthetic':rows,'independent_expected_worst_profits':expected,
            'next':'Full-depth calculation and sizing are separate; see app.depth'}

if __name__=='__main__':
    print(json.dumps(examples(),indent=2))
