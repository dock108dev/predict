"""Native prediction adapters and stream engines owned by E6, never old controller."""
import asyncio
import base64
from dataclasses import asdict, replace
from hashlib import sha256
from decimal import Decimal
import json
from urllib.parse import urlsplit
import aiohttp
import httpx
from websockets.asyncio.client import connect
from app.adapters.kalshi import KalshiAdapter
from app.adapters.polymarket_us import PolymarketUSAdapter
from app.adapters.kalshi_stream import MarketStream as KStream
from app.adapters.polymarket_us_stream import MarketStream as PStream
from app.models.core import EvidenceKind
from .odds_http import mock_endpoint, utc, BudgetStop
from .run_spec import time_value
from .prediction_discovery import NFLPolymarketAdapter,validate_pregame


class PredictionBudget:
    def __init__(self, limits):self.limits=limits;self.dollars=Decimal(0);self.requests=0;self.connections=0;self.bytes=0
    def remaining_bytes(self):return self.limits['session_bytes']-self.bytes
    def charge_bytes(self,n):
        if n>self.remaining_bytes():raise BudgetStop('prediction_session_byte_cap')
        self.bytes+=n
    def reserve(self, kind):
        cost=Decimal(self.limits['dollars_per_'+kind])
        if self.dollars+cost>Decimal(self.limits['dollar_cap_per_source']):raise BudgetStop('prediction_dollar_cap')
        self.dollars+=cost
        if kind=='connection':self.connections+=1
        else:self.requests+=1


class MockREST:
    """Injected bounded HTTP client for unchanged REST discovery parsers."""
    def __init__(self, endpoint, limits, sink, timeout, budget, *, venue=None, credential=None):
        self.venue=venue; self.credential=credential
        if venue:
            from .venue_access import endpoint as validate
            self.endpoint=validate(venue,'rest',endpoint)
        else:self.endpoint=mock_endpoint(endpoint)
        self.limits=limits; self.sink=sink; self.timeout=timeout
        self.requests=0; self.bytes=0; self.client=None;self.budget=budget

    async def get(self, url, params=None, **kwargs):
        if self.budget.requests >= self.limits['discovery_requests']:
            raise BudgetStop('prediction_discovery_request_cap')
        if self.venue:await asyncio.sleep(getattr(self, 'request_interval', 1))
        self.budget.reserve('discovery_request')
        self.requests+=1
        if self.client is None:
            self.client=aiohttp.ClientSession(auto_decompress=False,trust_env=False,
                timeout=aiohttp.ClientTimeout(total=self.timeout),connector=aiohttp.TCPConnector(limit=1),read_bufsize=4096)
        path=urlsplit(url).path
        query=params if params is not None else urlsplit(url).query
        body=bytearray(); status=None; complete=False; reserved=0
        started=utc(); headers={'Accept-Encoding':'identity'}
        if self.credential and self.venue=='kalshi':headers.update(self.credential.headers(path))
        try:
            async with self.client.get(self.endpoint+path,params=query,allow_redirects=False,headers=headers) as response:
                status=response.status
                cap=min(self.limits['frame_bytes'],self.budget.remaining_bytes())
                if cap<=0: raise BudgetStop('prediction_discovery_byte_cap')
                self.budget.charge_bytes(cap);reserved=cap
                while True:
                    if len(body)==cap:
                        if not response.content.at_eof():raise BudgetStop('prediction_discovery_byte_cap')
                        break
                    chunk=await response.content.read(min(4096,cap-len(body)))
                    if not chunk: break
                    self.bytes+=len(chunk); room=cap-len(body); body.extend(chunk[:room])
                    if len(chunk)>room: raise BudgetStop('prediction_discovery_byte_cap')
                if response.headers.get('Content-Encoding','identity')!='identity':raise ValueError('compressed discovery refused')
                if self.credential:self.credential.check(bytes(body),headers)
                complete=True
                return httpx.Response(status,content=bytes(body),headers={k:response.headers[k] for k in ('Retry-After',) if k in response.headers},request=httpx.Request('GET',self.endpoint+path))
        finally:
            if complete:self.budget.bytes-=reserved-len(body)
            raw=bytes(body)
            if self.credential:
                try:self.credential.check(raw,headers)
                except ValueError:raw=b'';complete=False
            self.sink(dict(type='prediction_discovery_http',path=path,status=status,complete=complete,
                started_at=started,params=query,received_at=utc(),body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest(),requests=self.requests))

    async def aclose(self):
        if self.client: await self.client.close()


class PredictionProducer:
    def __init__(self, venue, spec, rest_endpoint, websocket_endpoint, emit, health, *, credential=None, budget=None):
        self.venue=venue; self.spec=spec; self.row=spec['sources'][venue]
        self.real=spec['mode']=='real'; self.credential=credential
        self.kind=EvidenceKind.OBSERVATION if self.real else EvidenceKind.SYNTHETIC
        if self.real:
            from .venue_access import endpoint,REFERENCES
            if self.row['credential_reference']!=REFERENCES[venue] or credential is None:raise ValueError('dedicated project credential required')
            self.rest_endpoint=endpoint(venue,'rest',rest_endpoint);self.ws_endpoint=endpoint(venue,'ws',websocket_endpoint)
        else:
            self.rest_endpoint=mock_endpoint(rest_endpoint); self.ws_endpoint=mock_endpoint(websocket_endpoint)
        self.emit=emit; self.health=health; self.budget=budget or PredictionBudget(spec['prediction']); self.stream=None; self.adapter=None; self.bytes=0

    async def discover(self):
        p=self.spec['prediction']
        if self.adapter is None:
            client=MockREST(self.rest_endpoint,p,lambda r:self.emit(self.venue,r),self.spec.get('http',{}).get('timeout',5),self.budget,venue=self.venue if self.real else None,credential=self.credential)
            self.adapter=(KalshiAdapter(client=client,series=('KXNFLGAME',),max_pages=2 if self.real else 1,page_size=200 if self.real else 10,
                max_requests=p['discovery_requests'],retries=0,pregame_only=False) if self.venue=='kalshi' else
                (NFLPolymarketAdapter if self.real else PolymarketUSAdapter)(client=client,max_pages=10 if self.real else 1,page_size=5 if self.real else 10,request_cap=p['discovery_requests'],attempts=1))
        self.adapter.events.clear(); self.adapter.markets.clear()
        events=await self.adapter.discover_events()
        matches=[e for e in events if e.raw.ref.event_id==self.row['event_id']]
        if len(matches)!=1: raise ValueError('configured event absent or ambiguous in bounded discovery')
        event=matches[0]
        if event.scheduled_start != time_value(self.spec['scheduled_start']):
            raise ValueError('configured schedule changed')
        from app.normalization.observations import enrich_event
        normalized=enrich_event(event,environment='production' if self.real else 'synthetic')
        mapped=[self.row['participant_mapping'].get(x.name) for x in normalized.participants]
        if None in mapped or set(mapped)!=set(self.spec['participants']):
            raise ValueError('configured participant mapping mismatch')
        markets=await self.adapter.discover_markets(event.raw.ref.event_id)
        matches=[m for m in markets if m.raw.ref.market_id==self.row['market_id']]
        if len(matches)!=1: raise ValueError('configured market absent or ambiguous')
        market=matches[0]
        if market.state.value!='active' or market.market_type.value!='moneyline':
            raise ValueError('market not active moneyline')
        if market.raw.ref.event_id!=event.raw.ref.event_id:
            raise ValueError('configured market event mismatch')
        validate_pregame(event,market)
        self.emit(self.venue,dict(type='discovery_validated',event_id=self.row['event_id'],market_id=self.row['market_id'],
            scheduled_start=event.scheduled_start.isoformat(),mapping_revision=self.spec['mapping_revision']))
        self.emit(self.venue,dict(type='market_selected',market=json.loads(json.dumps(asdict(market),default=str))))
        return replace(market,raw=replace(market.raw,kind=self.kind))

    async def run(self, market):
        producer=self; limits=self.spec['prediction']
        class Socket:
            def __init__(self,socket,wire_limit): self.socket=socket;self.wire_limit=wire_limit
            async def send(self,body):
                producer.emit(producer.venue,dict(type='prediction_command',connection=producer.budget.connections,body=body))
                await self.socket.send(body)
            async def recv(self):
                pending=False
                try:
                    # Reserve one full permitted frame before awaiting ingress;
                    # concurrent discovery cannot spend the same byte allowance.
                    producer.budget.charge_bytes(self.wire_limit)
                    pending=True
                    body=await self.socket.recv()
                    raw=body.encode() if isinstance(body,str) else body
                    producer.budget.bytes-=self.wire_limit-len(raw)
                    pending=False
                    producer.bytes+=len(raw)
                    if producer.bytes>limits['session_bytes']: raise BudgetStop('prediction_session_byte_cap')
                    if producer.credential:producer.credential.check(raw,producer.handshake_headers)
                    producer.emit(producer.venue,dict(type='prediction_frame',connection=producer.budget.connections,received_at=utc(),
                        body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest()))
                    return body
                except asyncio.CancelledError:
                    # websockets.recv cancellation preserves the next complete
                    # message; no application body was delivered in this call.
                    if pending:producer.budget.bytes-=self.wire_limit
                    raise
                except BaseException:
                    producer.health(producer.venue,'disconnected')
                    raise
            async def close(self):
                producer.health(producer.venue,'disconnected')
                await self.socket.close()
        async def factory():
            if self.budget.remaining_bytes()<=0:raise BudgetStop('prediction_session_byte_cap')
            if self.budget.connections>=limits['connections']:raise BudgetStop('prediction_connection_cap')
            self.budget.reserve('connection')
            self.handshake_headers=self.credential.headers() if self.credential else {}
            wire_limit=min(limits['frame_bytes'],self.budget.remaining_bytes())
            socket=await connect(self.ws_endpoint,max_size=wire_limit,max_queue=1,
                                 compression=None,open_timeout=3,close_timeout=1,proxy=None,additional_headers=self.handshake_headers)
            self.health(self.venue,'awaiting_snapshot')
            return Socket(socket,wire_limit)
        self.stream=(KStream if self.venue=='kalshi' else PStream)(market if isinstance(market,list) else [market],factory,
            duration=self.spec['duration'],max_messages=limits['messages'],max_connections=limits['connections'],
            stale_seconds=self.spec['stale_seconds'],kind=self.kind)
        try:
            async for book in self.stream.run():
                # Preserve native book/receipt semantics; health updates aren't new wire arrivals.
                data=json.loads(json.dumps(asdict(book),default=str))
                from app.arbitrage import book_observations
                from app.storage.workflow import packet
                packets=[]
                for observation in book_observations(book,environment='production' if self.real else 'synthetic',evidence_class='current' if self.real else 'synthetic',source_time_semantics='unknown'):
                    row=packet(observation)
                    row['raw_b64']=base64.b64encode(row.pop('raw')).decode()
                    packets.append(row)
                self.emit(self.venue,dict(type='prediction_book',book=data,packets=packets,
                    receipt_semantics='derived native book state; wire arrivals separately retained'))
                self.health(self.venue,'connected' if book.sync.value=='synchronized' else ('disconnected' if self.stream.connection is None else 'ineligible'))
        finally:
            await self.stream.aclose()
            self.health(self.venue,'disconnected')
            self.emit(self.venue,dict(type='native_stream_finished',diagnostics=self.stream.diagnostics,closed=self.stream.closed))

    async def interrupt_connection(self):
        """Explicit supervised fault; native stream owns invalidation and recovery."""
        if not self.stream or not self.stream.connection or self.stream.closed:
            raise ValueError('source has no active connection')
        if self.budget.connections >= self.spec['prediction']['connections']:
            raise ValueError('no recovery connection allowance')
        self.emit(self.venue,dict(type='controlled_interruption',connection=self.budget.connections,
            reason='supervised client-induced socket close; not a natural outage'))
        self.health(self.venue,'disconnected')
        await self.stream.connection.close()

    async def aclose(self):
        try:
            if self.stream: await self.stream.aclose()
        finally:
            if self.adapter: await self.adapter.aclose()
