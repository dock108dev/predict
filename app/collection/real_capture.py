"""Explicit bounded discovery/Start for one NFL event. No service or database use."""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json
from pathlib import Path
import signal
import time
from app.adapters.kalshi import KalshiAdapter
from app.adapters.polymarket_us import PolymarketUSAdapter,next_market_data
from app.normalization.observations import enrich_event
from .prediction_producer import MockREST,PredictionBudget
from .prediction_discovery import NFLPolymarketAdapter,participant_mapping
from .transport_session import ObservationJournal,TransportSession,reopen
from .venue_access import ENDPOINTS,REFERENCES,load_credentials
from .native_replay import verify_native

LIMITS=dict(messages=1000,connections=2,frame_bytes=1048576,session_bytes=16777216,discovery_requests=64,
            dollar_cap_per_source='0',dollars_per_discovery_request='0',dollars_per_connection='0',
            plan_evidence='docs/e6-prediction-only-report.md#access')


def write(path,value):path.write_text(json.dumps(value,indent=2,default=str)+'\n')

def usage(budgets):return {v:dict(requests=b.requests,connections=b.connections,bytes=b.bytes,dollars=str(b.dollars)) for v,b in budgets.items()}

def identify(events):
    result=[]
    for event in events:
        n,mapping=participant_mapping(event)
        if len(mapping)!=2 or None in mapping.values() or len(set(mapping.values()))!=2 or n.league.canonical_id!='NFL':continue
        result.append(dict(event_id=event.raw.ref.event_id,title=event.title,scheduled_start=event.scheduled_start,
                           mapping=mapping,extraction=asdict(n)))
    return result

async def discover(output, prior=None):
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();utc_start=datetime.now(timezone.utc)
    budgets={v:PredictionBudget(LIMITS) for v in ENDPOINTS};adapters={};journal=ObservationJournal(output/'discovery.jsonl')
    status='failed'
    if prior:
        previous=json.loads(prior.read_text())
        for v,b in budgets.items():b.requests=previous['usage'][v]['requests'];b.bytes=previous['usage'][v]['bytes']
    try:
        credentials=load_credentials()
        journal.save(dict(type='discovery_started',started_at=utc_start.isoformat(),limits=LIMITS,credential_references=REFERENCES))
        for venue in ENDPOINTS:
            client=MockREST(ENDPOINTS[venue]['rest'],LIMITS,lambda r,v=venue:journal.save(dict(r,source=v)),5,budgets[venue],venue=venue,credential=credentials[venue])
            adapters[venue]=(KalshiAdapter(client=client,series=('KXNFLGAME',),max_pages=2,page_size=200,max_requests=64,retries=0) if venue=='kalshi' else NFLPolymarketAdapter(client=client,max_pages=10,page_size=5,request_cap=64,attempts=1))
        async with asyncio.timeout(60):
            # Read only the two account API-limit endpoints; no balances, positions, or accounts list.
            kclient=adapters['kalshi'].client
            access={}
            for path in ('/trade-api/v2/account/limits','/trade-api/v2/account/endpoint_costs'):
                response=await kclient.get(ENDPOINTS['kalshi']['rest']+path)
                if response.status_code!=200:raise ValueError('Kalshi access limits unavailable')
                access[path]=response.json()
            write(output/'account-api-limits.json',access)
            events={}
            for venue,a in adapters.items():events[venue]=identify(await a.discover_events())
            write(output/'catalog.json',events)
            ktr=any(adapters['kalshi'].discovery_truncated.values());ptr=adapters['polymarket_us'].discovery_truncated
            if ktr or ptr:raise ValueError('bounded catalog truncated; earliest event unestablished')
            cutoff=datetime.now(timezone.utc)+timedelta(seconds=300)
            candidates=[]
            for k in events['kalshi']:
                for p in events['polymarket_us']:
                    if set(k['mapping'].values())!=set(p['mapping'].values()):continue
                    if k['scheduled_start']!=p['scheduled_start']:continue
                    if k['scheduled_start'] is None or k['scheduled_start']<=cutoff:continue
                    candidates.append((k['scheduled_start'],k,p))
            if not candidates:raise ValueError('no unambiguous future common event in catalog')
            candidates.sort(key=lambda x:(x[0],x[1]['event_id'],x[2]['event_id']))
            start,k,p=candidates[0]
            if sum(1 for c in candidates if c[0]==start and set(c[1]['mapping'].values())==set(k['mapping'].values()))!=1:raise ValueError('ambiguous common event identity')
            chosen={}
            for venue,event in [('kalshi',k),('polymarket_us',p)]:
                markets=await adapters[venue].discover_markets(event['event_id'])
                markets=[m for m in markets if m.state.value=='active' and m.market_type.value=='moneyline']
                if venue=='kalshi':
                    # Separate team-YES contracts; deterministic selection after both participants resolve.
                    markets=sorted(markets,key=lambda m:m.raw.ref.market_id)
                    if len(markets)!=2:raise ValueError('expected two native team moneylines')
                elif len(markets)!=1:raise ValueError('ambiguous US moneyline selection')
                chosen[venue]=dict(event_id=event['event_id'],market_id=markets[0].raw.ref.market_id,
                    participant_mapping=event['mapping'],credential_reference=REFERENCES[venue],entitlement_reference='account-api-limits.json; official-access.json')
                write(output/(venue+'-selected-market.json'),asdict(markets[0]))
            now=datetime.now(timezone.utc)
            spec=dict(mode='real',reference_enabled=False,event='NFL:'+k['event_id']+':'+p['event_id'],participants=sorted(k['mapping'].values()),
                scheduled_start=start.isoformat(),start_after=now.isoformat(),start_before=(now+timedelta(minutes=30)).isoformat(),
                duration=120,discovery_cadence=45,stale_seconds=30,sources=chosen,mapping_revision='discovery.jsonl+catalog.json',
                assessment_revisions=dict.fromkeys(['pairing','lineage','fees','settlement']),prediction=LIMITS,
                cleanup='close only this session transports; retain isolated file journals',capture_authorization='owner prompt 2026-09-15: prediction-only bounded capture; zero additional spend')
            if now+timedelta(minutes=32)>=start:spec['start_before']=(start-timedelta(seconds=121)).isoformat()
            write(output/'run-spec.json',spec)
            status='selected'
    finally:
        await asyncio.gather(*(a.aclose() for a in adapters.values()),return_exceptions=True)
        completion=dict(type='session_finished',status=status,started_at=utc_start.isoformat(),finished_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started,usage=usage(budgets))
        journal.save(completion);journal.close();write(output/'discovery-completion.json',completion)
    return status

async def capture(output):
    spec=json.loads((output/'run-spec.json').read_text());prior=json.loads((output/'discovery-completion.json').read_text())
    if prior['status']!='selected':raise ValueError('discovery did not select a market')
    # Refuse a second session in this output, even after interruption.
    marker=output/'capture-started.json'
    with marker.open('x') as f:json.dump(dict(started_at=datetime.now(timezone.utc).isoformat()),f)
    budgets={v:PredictionBudget(spec['prediction']) for v in ENDPOINTS}
    for v,b in budgets.items():
        b.requests=prior['usage'][v]['requests'];b.bytes=prior['usage'][v]['bytes']
    credentials=load_credentials();owner=TransportSession(spec,output/'session',ENDPOINTS,credentials=credentials,budgets=budgets)
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,owner.request_stop,'manual_stop')
    began=time.monotonic();start=datetime.now(timezone.utc)
    try:
        await owner.start();await owner.task
    finally:
        if owner.task and not owner.task.done():await owner.stop()
        for sig in (signal.SIGINT,signal.SIGTERM):loop.remove_signal_handler(sig)
    elapsed=time.monotonic()-began
    saved=reopen(owner.journal.path)
    replay=verify_native(owner.journal.path)
    write(output/'replay.json',replay)
    write(output/'saved-observations.json',saved)
    result=dict(session_id=owner.sid,journal=str(owner.journal.path),started_at=start.isoformat(),finished_at=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=elapsed,reason=owner.reason,delivered=owner.delivered,persisted=owner.persisted,
        counts=dict(Counter((r.get('source','session')+':'+r['type']) for r in saved['rows'])),usage=usage(budgets),
        exact_reopen=saved==reopen(owner.journal.path),replay=replay,
        closed={v:dict(adapter=p.adapter.closed,stream=p.stream.closed if p.stream else None) for v,p in owner.producers.items()},
        economics=dict(arb='unavailable: current outcome/settlement compatibility and effective fee/account rounding unqualified',
                       mispricing='unavailable: optional reference disabled; no probability model'),reference_requests=0,additional_spend='0')
    write(output/'capture-summary.json',result)
    print(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--discover',action='store_true');group.add_argument('--start',action='store_true')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--prior',type=Path);args=parser.parse_args()
    try:asyncio.run(discover(args.output,args.prior) if args.discover else capture(args.output))
    except Exception as exc:
        # Never print transport or credential exception bodies.
        print(json.dumps(dict(status='stopped',error_type=type(exc).__name__)))
        raise SystemExit(1) from None

if __name__=='__main__':main()
