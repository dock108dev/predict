"""Live orchestration uses the already-qualified read-only adapters and streams."""
import asyncio,json
from datetime import datetime,timezone
from contextlib import aclosing
from app.adapters.kalshi import KalshiAdapter
from app.adapters.polymarket_us import PolymarketUSAdapter,next_market_data
from app.adapters.kalshi_stream import MarketStream as KStream,AuthenticatedTransport as KTransport,keychain_signer
from app.adapters.polymarket_us_stream import MarketStream as PStream,AuthenticatedTransport as PTransport,RuntimeSigner
from app.models.core import MarketType,MarketState
from app.normalization.observations import enrich_event


def credentials(venue):
    if venue=='kalshi':return KTransport(keychain_signer())
    from keyring.backends.macOS import Keyring
    value=Keyring().get_password('prediction-arb.polymarket-us','retail-api')
    if not value:raise RuntimeError('project credential unavailable')
    c=json.loads(value)
    return PTransport(RuntimeSigner(c['key_id'],c['secret_key']),allow_connection=True)


def event_key(e):
    n=enrich_event(e,environment='production')
    return (tuple(sorted(p.resolution.canonical_id or '' for p in n.participants)),e.scheduled_start)


def select_events(discovered,limit):
    # Canonical identities only prioritize subscriptions; actual matching runs separately.
    common=set(event_key(e) for e in discovered.get('kalshi',[])) & set(event_key(e) for e in discovered.get('polymarket_us',[]))
    return {v:sorted(es,key=lambda e:(event_key(e) not in common,e.scheduled_start,event_key(e)[0],e.raw.ref.event_id))[:limit] for v,es in discovered.items()}


class LimitedSocket:
    def __init__(self,socket,run,venue):self.socket=socket;self.run=run;self.venue=venue
    async def send(self,message):return await self.socket.send(message)
    async def recv(self):
        try:body=await self.socket.recv()
        except Exception:
            self.run.health(self.venue,'disconnected','Venue disconnected');raise
        self.run.messages+=1;self.run.network_bytes+=len(body.encode() if isinstance(body,str) else body)
        if self.run.messages>=self.run.limits['receipts'] or self.run.network_bytes>=self.run.limits['storage_bytes']:
            self.run.request_stop('Message or storage limit reached')
        return body
    async def close(self):
        self.run.health(self.venue,'disconnected','Subscription closed')
        return await self.socket.close()


class LiveSource:
    def __init__(self,run):self.run=run;self.adapters={};self.streams={}
    async def prepare(self):
        self.adapters={'kalshi':KalshiAdapter(series=('KXNFLGAME',),max_pages=1,page_size=10,max_requests=24,retries=1),
            'polymarket_us':PolymarketUSAdapter(max_pages=1,page_size=8,request_cap=16,attempts=1)}
        async def events(v,a):
            try:
                self.run.health(v,'discovering','Finding current pregame NFL events')
                es=await a.discover_events();now=datetime.now(timezone.utc)
                return v,[e for e in es if e.scheduled_start and e.scheduled_start>now]
            except Exception:
                self.run.health(v,'unavailable','Current event discovery unavailable');return v,[]
        discovered=dict(await asyncio.gather(*(events(v,a) for v,a in self.adapters.items())))
        selected=await asyncio.to_thread(select_events,discovered,self.run.limits['markets'])
        results=[]
        for v,a in self.adapters.items():
            rows=[];fees={};used=[]
            try:
                for event in selected[v]:
                    found=await a.discover_markets(event.raw.ref.event_id)
                    candidates=[m for m in found if m.state==MarketState.ACTIVE and (v=='kalshi' or m.market_type==MarketType.MONEYLINE)]
                    for m in candidates:
                        if len(rows)>=self.run.limits['markets']:break
                        m=await a.get_market(m.raw.ref.market_id)
                        if v=='kalshi':
                            native=json.loads(m.raw.json_text)['market']
                            body=json.loads(event.raw.json_text)
                            context=next(x for x in body['events'] if x['event_ticker']==event.raw.ref.event_id)
                        else:
                            native=json.loads(m.raw.json_text)['market']
                            if native.get('category')!='sports' or native.get('sportsMarketType')!='football_team_full_game_winner':continue
                            context=next(x for x in json.loads(event.raw.json_text)['events'] if str(x['id'])==event.raw.ref.event_id)
                            context={k:val for k,val in context.items() if k!='markets'}
                        rows.append((m,native,context))
                        if event not in used:used.append(event)
                    if v=='kalshi' and event in used:
                        try:
                            f=await a.get_fee_metadata(event.raw.ref.event_id)
                            fees[event.raw.ref.event_id]=dict(source='current Kalshi series/event fee metadata',series_id='KXNFLGAME',event_id=event.raw.ref.event_id,event_history_complete=not f['truncated'],
                                series_changes=json.loads(f['series_history'].body,parse_float=str)['series_fee_change_arr'],event_changes=[x for r in f['event_overrides'] for x in json.loads(r.body,parse_float=str)['event_fee_changes']])
                        except Exception:pass # Absent context remains explicitly unknown in fee engine.
                    if len(rows)>=self.run.limits['markets']:break
                self.run.health(v,'ready' if rows else 'unavailable',f'{len(rows)} current markets selected' if rows else 'No usable pregame markets in bounded discovery')
            except Exception:self.run.health(v,'unavailable','Market refresh unavailable; retained selections are limited')
            results.append(dict(venue=v,events=used,markets=rows,responses=list(a.responses),fees=fees,coverage=dict(venue=v,discovered_events=len(discovered[v]),selected_events=len(used),selected_markets=len(rows),requests=a.requests,discovery_truncated=a.discovery_truncated,fee_metadata_events=len(fees),note=self.run.status[v]['note'])))
        return results

    async def venue(self,d):
        v=d['venue'];a=self.adapters[v];markets=[m for m,_,_ in d['markets']]
        if not markets:return
        # Useful snapshots are available even if the named stream credential is missing.
        for m in markets:
            try:
                b=await a.get_snapshot(m.raw.ref.market_id)
                self.run.health(v,'snapshot','Public snapshot; connecting live updates')
                self.run.offer(('book',b))
            except Exception:self.run.offer(('gap',dict(venue=v,reason='Snapshot unavailable')))
        try:transport=await asyncio.to_thread(credentials,v)
        except Exception:
            self.run.health(v,'unavailable','Saved credential unavailable; authenticated updates disabled')
            self.run.offer(('disconnect',(v,'Saved credential unavailable')));return
        async def factory():
            socket=await transport();self.run.health(v,'connected','Authenticated read-only connection')
            return LimitedSocket(socket,self.run,v)
        stream=(KStream if v=='kalshi' else PStream)(markets,factory,duration=self.run.limits['seconds'],max_messages=self.run.limits['receipts'],max_connections=1,stale_seconds=10)
        self.streams[v]=stream
        try:
            async with aclosing(stream.run()) as updates:
                async for book in updates:
                    if self.run.stop_event.is_set():break
                    self.run.health(v,'connected' if book.sync.value=='synchronized' else 'disconnected',
                        'Receiving market observations' if book.sync.value=='synchronized' else 'Awaiting a new synchronized book')
                    self.run.offer(('book',book))
        finally:
            self.run.health(v,'disconnected','Live updates stopped')
            self.run.offer(('disconnect',(v,'Live subscription ended')))

    async def close(self):
        await asyncio.gather(*(s.aclose() for s in self.streams.values()),return_exceptions=True)
        await asyncio.gather(*(a.aclose() for a in self.adapters.values()),return_exceptions=True)
