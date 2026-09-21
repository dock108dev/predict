"""Finite market-specific NBX stream. Unknown wire schemas fail closed."""
import asyncio
from dataclasses import replace
import json
import time
from websockets.exceptions import ConnectionClosed, InvalidStatus
from app.adapters.novig import (OrderImage, Response, HOSTS, decode, identity, native_state)
from app.models.core import MarketState


class MarketStream:
    def __init__(self, adapter, markets, *, duration=30, max_messages=100, reconnects=1,
                 reconnect_after=10, max_bytes=2_000_000):
        if not 0<duration<=120 or not 1<=max_messages<=1000 or not 0<=reconnects<=3 or not 0<reconnect_after<=120 or not 1<=max_bytes<=10_000_000:
            raise ValueError('invalid stream bounds')
        self.adapter=adapter
        self.images={m.raw.ref.market_id:OrderImage(m) for m in markets}
        self.duration,self.max_messages,self.reconnects=duration,max_messages,reconnects
        self.reconnect_after,self.max_bytes=reconnect_after,max_bytes
        self.generation,self.messages,self.bytes=0,0,0
        self.ws=None; self.closed=False
        self.frames=[]; self.connected=False
        self.connections=0; self.initial_images=0; self.ticks=0
        self.live={}

    def apply(self, response, generation):
        try:
            return self._apply(response, generation)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("malformed NBX frame") from exc

    def _apply(self, response, generation):
        if generation!=self.generation or self.closed: return []
        d=decode(response.body)
        if not isinstance(d,dict): raise ValueError('expected frame object')
        if d.get('event') in ('subscribed','unsubscribed'): return []
        if d.get('event') == 'error': raise ConnectionError('Novig protocol error')
        if d.get('event') == 'book':
            # Docs promise an enveloped book, but do not specify its data schema.
            # Support the documented REST BookResponseDto only; fail closed otherwise.
            data=d.get('data')
            if not isinstance(data,dict) or 'outcomeLadders' not in data:
                raise ValueError('unverified initial book envelope shape')
            mid=identity(data.get('marketId'))
            if mid not in self.images: return []
            image=self.images[mid]
            if image.initialized: raise ValueError('unexpected repeated initial book')
            image.snapshot(data); self.initial_images+=1
            return [image.book(response.raw(image.market.raw.ref.event_id,mid),self.adapter.effective_state(image.market))]
        typ=d.get('type')
        if typ in ('PLACE','CANCEL'):
            order=d['order']; mid=identity(order.get('marketId'))
            if mid not in self.images: return []
            image=self.images[mid]
            if d.get('market',{}).get('id',mid)!=mid: raise ValueError('tick market mismatch')
            # CLOSE forbids stale order ticks from reviving the book.
            if image.market.state in (MarketState.CLOSED,MarketState.SETTLED): return []
            image.tick(typ,order); self.ticks+=1
            return [image.book(response.raw(image.market.raw.ref.event_id,mid),self.adapter.effective_state(image.market))]
        if typ not in ('OPEN','CLOSE','START','END','EVENT_GOLIVE','EVENT_UNLIVE'):
            raise ValueError('unknown protocol message')
        market=d['market']; mid=identity(market.get('id')); eid=market.get('eventId')
        if mid not in self.images and eid not in {i.market.raw.ref.event_id for i in self.images.values()}: return []
        if mid in self.images:
            expected=self.images[mid].market.raw.ref.event_id
            if eid is not None and eid!=expected: raise ValueError('lifecycle event mismatch')
            eid=expected
        targets=[mid] if mid in self.images else []
        if typ.startswith('EVENT_'):
            is_live=typ=='EVENT_GOLIVE'
            changed=self.live.get(eid)!=is_live
            self.live[eid]=is_live
            self.adapter.event_status[eid]='OPEN_INGAME' if is_live else 'NONLIVE_UNSPECIFIED'
            targets=[k for k,i in self.images.items() if i.market.raw.ref.event_id==eid]
            if is_live and changed:
                for key in targets: self.images[key].orders.clear()
        updates=[]
        for key in targets:
            image=self.images[key]
            raw=response.raw(eid,key)
            if typ=='CLOSE':
                image.orders.clear()
                image.market=replace(image.market,state=MarketState.CLOSED,raw=raw)
            elif typ=='OPEN':
                image.market=replace(image.market,state=MarketState.ACTIVE,raw=raw)
            elif typ=='END':
                image.market=replace(image.market,state=MarketState.UNKNOWN,raw=raw)
            updates.append(replace(image.market,raw=raw,state=self.adapter.effective_state(image.market)))
            updates.append(image.book(raw,self.adapter.effective_state(image.market)))
        return updates

    async def _connect(self):
        token=await self.adapter.access_token()
        if self.adapter.stream_factory:
            return await self.adapter.stream_factory(token)
        from websockets.asyncio.client import connect
        # websockets automatically answers protocol Ping with Pong.
        return await connect(HOSTS[self.adapter.environment].replace('https:','wss:')+'/tape',
            additional_headers={'Authorization':'Bearer '+token},ping_interval=15,ping_timeout=15,
            open_timeout=5,close_timeout=2,max_size=min(self.max_bytes,1_000_000),max_queue=16)

    async def run(self):
        try:
            async with asyncio.timeout(self.duration):
                async for update in self._run():
                    yield update
        finally:
            await self.aclose()

    async def _run(self):
        deadline=time.monotonic()+self.duration
        try:
            for attempt in range(self.reconnects+1):
                if self.closed or time.monotonic()>=deadline: break
                self.generation+=1
                for image in self.images.values():
                    image.orders.clear(); image.initialized=False
                for eid in {i.market.raw.ref.event_id for i in self.images.values()}:
                    await self.adapter.refresh_event(eid)
                    self.live[eid]=self.adapter.event_status[eid]=='OPEN_INGAME'
                    await self.adapter.refresh_market_states(eid)
                for mid,image in self.images.items():
                    image.market=self.adapter.markets[mid]
                await self.adapter.refresh_locks()
                try:
                    self.ws=await self._connect(); self.connected=True; self.connections+=1
                    for channel in ('lifecycle',*self.images):
                        await self.ws.send(json.dumps({'event':'subscribe','data':channel}))
                    end=min(deadline,time.monotonic()+self.reconnect_after,
                            time.monotonic()+max(0,self.adapter.expires-self.adapter.clock()))
                    lock_at=time.monotonic()+3
                    while not self.closed and self.messages<self.max_messages and time.monotonic()<end:
                        if time.monotonic()>=lock_at:
                            await self.adapter.refresh_locks(); lock_at=time.monotonic()+3
                            for mid,image in self.images.items():
                                yield image.book(self.adapter.locks.raw(image.market.raw.ref.event_id,mid),self.adapter.effective_state(image.market))
                        try:
                            body=await asyncio.wait_for(self.ws.recv(),max(.001,min(end,lock_at)-time.monotonic()))
                        except TimeoutError: continue
                        if isinstance(body,bytes): body=body.decode('utf-8')
                        self.messages+=1; self.bytes+=len(body.encode())
                        if self.bytes>self.max_bytes: raise ValueError('stream storage budget exhausted')
                        r=Response(body,HOSTS[self.adapter.environment].replace('https:','wss:')+'/tape',self.adapter.now(),self.adapter.kind)
                        self.frames.append(r)
                        for update in self.apply(r,self.generation): yield update
                    if self.messages>=self.max_messages: break
                except (ConnectionError,OSError,ConnectionClosed,InvalidStatus) as exc:
                    if attempt==self.reconnects: raise ConnectionError('Novig stream connection failed') from None
                finally:
                    await self._close_socket()
                for mid,image in self.images.items():
                    image.initialized=False; image.orders.clear()
                    r=Response('{}','novig:transport-disconnected',self.adapter.now(),self.adapter.kind)
                    yield image.book(r.raw(image.market.raw.ref.event_id,mid),MarketState.UNKNOWN,transport=False)
                if attempt<self.reconnects:
                    await self.adapter.sleep(min(2**attempt,4))
                    await self.adapter.access_token(force=True)
        finally:
            await self.aclose()

    async def _close_socket(self):
        ws,self.ws=self.ws,None
        self.connected=False
        if ws:
            try:
                for channel in ('lifecycle',*self.images):
                    await asyncio.wait_for(ws.send(json.dumps({'event':'unsubscribe','data':channel})),1)
            except Exception: pass
            finally: await ws.close()

    async def aclose(self):
        self.closed=True; self.generation+=1
        await self._close_socket()
        for image in self.images.values():
            image.orders.clear(); image.initialized=False
