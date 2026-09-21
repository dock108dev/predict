"""Supervised finite qualification capture. Reads only the named project Keychain entry."""
import argparse
import asyncio
from contextlib import aclosing
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from keyring.backends.macOS import Keyring
from app.adapters.polymarket_us import PolymarketUSAdapter, next_market_data, decode
from app.adapters.polymarket_us_stream import MarketStream, RuntimeSigner, AuthenticatedTransport
from app.models.core import MarketType
from app.polymarket_us_verify import save_stream_evidence

async def capture(directory):
    directory.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    async with PolymarketUSAdapter(max_pages=1,page_size=3,request_cap=4,attempts=1) as rest:
        await rest.discover_events()
        markets=[]
        for event in rest.events:
            candidates=[m for m in await rest.discover_markets(event) if m.market_type==MarketType.MONEYLINE]
            for m in candidates:
                d=next_market_data(m)
                if d.get('active') is True and d.get('closed') is False and d.get('category')=='sports' and d.get('gameStartTime') and datetime.fromisoformat(d['gameStartTime'].replace('Z','+00:00'))>datetime.now(timezone.utc):
                    markets.append(await rest.get_market(m.raw.ref.market_id));break
        provenance=[]
        for i,r in enumerate(rest.responses):
            name=f'discovery-{i+1}.json';(directory/name).write_text(r.body)
            provenance.append({'file':name,'source':r.source,'received_at':r.received_at.isoformat(),'http_status':r.http_status})
        (directory/'discovery-provenance.json').write_text(json.dumps(provenance,indent=2))
    if not markets:raise ValueError('No bounded pregame selection')
    credentials=json.loads(Keyring().get_password('prediction-arb.polymarket-us','retail-api'))
    signer=RuntimeSigner(credentials['key_id'],credentials['secret_key']);del credentials
    transport=AuthenticatedTransport(signer,allow_connection=True)
    connections=0;timers=[];images={};changes=[];previous={};byte_count=0
    async def connect():
        nonlocal connections
        sock=await transport();connections+=1
        if connections==1:
            async def disconnect():
                await asyncio.sleep(20)
                stream.record('deliberate_local_disconnect')
                await asyncio.wait_for(sock.close(),2)
            timers.append(asyncio.create_task(disconnect()))
        return sock
    class LimitedStream(MarketStream):
        def parse(self,body,request_id,*,generation=None):
            nonlocal byte_count
            byte_count+=len(body.encode() if isinstance(body,str) else body)
            if byte_count>20_000_000:raise ValueError('storage budget exhausted')
            return super().parse(body,request_id,generation=generation)
    stream=LimitedStream(markets,connect,max_messages=1000,duration=240,max_connections=2,stale_seconds=30)
    reason='duration_or_message_budget'
    try:
        async with aclosing(stream.run()) as iterator:
            async for book in iterator:
                if book.sync.value=='unsynchronized' or book.receipt_freshness.value=='stale':continue
                md=decode(book.raw.json_text)['marketData'];slug=md['marketSlug']
                images.setdefault(connections,set()).add(slug)
                if slug in previous:
                    old=previous[slug]
                    for side in ['bids','offers']:
                        before={r['px']['value']:r['qty'] for r in old.get(side,[])}
                        after={r['px']['value']:r['qty'] for r in md.get(side,[])}
                        removed=sorted(set(before)-set(after));added=sorted(set(after)-set(before))
                        qty=[p for p in set(before)&set(after) if before[p]!=after[p]]
                        if removed or added or qty:
                            changes.append({'frame_index':len(stream.responses),'market_slug':slug,'side':side,
                                'previous_time':old.get('transactTime'),'time':md.get('transactTime'),
                                'removed':removed,'added':added,'quantity_changed':sorted(qty)})
                previous[slug]=md
                if len(images.get(2,set()))==len(markets) and any(c['removed'] for c in changes):
                    reason='membership_change_and_reconnected_images_obtained';break
                if byte_count>=20_000_000:reason='storage_budget';break
    finally:
        for t in timers:t.cancel()
        await asyncio.gather(*timers,return_exceptions=True)
        await stream.aclose()
        save_stream_evidence(directory,stream,markets[0],{'stop_reason':reason})
        summary={'elapsed_seconds':time.monotonic()-started,'connections':connections,'frames':len(stream.responses),
            'frame_bytes':byte_count,'markets':[{'event_id':m.raw.ref.event_id,'market_id':m.raw.ref.market_id,
                'slug':next_market_data(m)['slug']} for m in markets],
            'initial_image_markets_by_connection':{k:sorted(v) for k,v in images.items()},'changes':changes,'stop_reason':reason}
        (directory/'capture-summary.json').write_text(json.dumps(summary,indent=2))
        print(json.dumps({k:v for k,v in summary.items() if k!='changes'},indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:asyncio.run(capture(args.output))
    except Exception:
        print('Qualification capture stopped; sensitive exception details suppressed.',flush=True)
        raise SystemExit(1) from None
