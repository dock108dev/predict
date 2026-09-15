"""Bounded NBX CASH market data; no trading or account operations."""
import asyncio
from contextlib import aclosing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import json
import time
from urllib.parse import quote
import httpx
from app.adapters.base import ReadOnlyAdapter
from app.adapters.kalshi import identity, timestamp
from app.models.core import (Venue, EvidenceKind, RawPayload, NativeRef, Event, Market,
    Outcome, MarketType, MarketState, OrderBook, OutcomeBook, Ladder, BookLevel,
    Probability, Quantity, Depth, BookSync, SourceTimeProgress, ReceiptFreshness,
    Quote, QuoteSide, SettlementProfile, parse_decimal, reject_constant)

HOSTS = {'production': 'https://api.novig.com', 'qa': 'https://api-qa.novig.us'}
AUTH = {'production': 'https://api.novig.com/nbx/v1/auth/emm-token',
        'qa': 'https://auth-qa.novig.us/oauth/token'}


def decode(body):
    return json.loads(body, parse_float=Decimal, parse_constant=reject_constant)


@dataclass(frozen=True)
class Response:
    body: str
    source: str
    received_at: datetime
    kind: EvidenceKind = EvidenceKind.OBSERVATION

    def raw(self, eid, mid=None):
        return RawPayload(ref=NativeRef(venue=Venue.NOVIG, event_id=identity(eid), market_id=mid),
            source=self.source, received_at=self.received_at, json_text=self.body, kind=self.kind)


def parse_market(r, d, eid):
    if d.get('eventId') != eid:
        raise ValueError('event identity mismatch')
    outcomes = tuple(Outcome(native_id=identity(o['id']), label=o['description']) for o in d['outcomes'])
    if len(outcomes) != 2 or set(d['outcomeIds']) != {o.native_id for o in outcomes}:
        raise ValueError('expected two native outcomes')
    return Market(raw=r.raw(eid, identity(d['id'])), title=d['description'], outcomes=outcomes,
        market_type=MarketType.MONEYLINE if d.get('type') == 'MONEY' else MarketType.UNKNOWN,
        state=native_state(d.get('status')))


def native_state(s):
    return {'OPEN': MarketState.ACTIVE, 'CLOSED': MarketState.CLOSED,
            'SETTLED': MarketState.SETTLED}.get(s, MarketState.UNKNOWN)


class OrderImage:
    """ID replacements, never aggregate deltas. Atomic validation before mutation."""
    def __init__(self, market):
        self.market = market
        self.orders = {}
        self.initialized = False

    def order(self, d):
        if d.get('marketId') != self.market.raw.ref.market_id or d.get('outcomeId') not in {o.native_id for o in self.market.outcomes}:
            raise ValueError('order identity mismatch')
        if d.get('currency') != 'CASH':
            raise ValueError('only CASH payout cents supported')
        p, q = parse_decimal(d['price']), parse_decimal(d['qty'])
        if not Decimal('0.001') <= p <= Decimal('0.999') or p != p.quantize(Decimal('.001')) or q < 0:
            raise ValueError('invalid NBX price or remaining quantity')
        return identity(d['id']), (d['outcomeId'], p, q)

    def snapshot(self, d):
        if d.get('marketId') != self.market.raw.ref.market_id:
            raise ValueError('book identity mismatch')
        rows, seen = {}, set()
        for side in d['outcomeLadders']:
            oid = identity(side['outcomeId'])
            if oid in seen:
                raise ValueError('duplicate ladder')
            seen.add(oid)
            for order in side['bids']:
                key, value = self.order(order)
                if key in rows or value[0] != oid:
                    raise ValueError('duplicate order or ladder mismatch')
                rows[key] = value
        if seen != {o.native_id for o in self.market.outcomes}:
            raise ValueError('missing outcome ladder')
        self.orders, self.initialized = rows, True

    def tick(self, typ, d):
        if not self.initialized:
            raise ValueError('tick before initial image')
        if typ == 'CANCEL':
            if d.get('marketId') != self.market.raw.ref.market_id:
                raise ValueError('cancel identity mismatch')
            self.orders.pop(identity(d['id']), None)
        elif typ == 'PLACE':
            key, value = self.order(d)
            if value[2] == 0:
                self.orders.pop(key, None)
            else:
                self.orders[key] = value
        else:
            raise ValueError('unknown order operation')

    def book(self, raw, state=MarketState.UNKNOWN, *, transport=True):
        outcomes = []
        for o in self.market.outcomes:
            totals = {}
            for oid, p, q in self.orders.values():
                if oid == o.native_id and q > 0:
                    totals[p] = totals.get(p, Decimal(0)) + q
            ladder = Ladder(depth=Depth.UNKNOWN, levels=tuple(BookLevel(price=Probability(value=p),
                quantity=Quantity(value=q, unit='payout_cents')) for p,q in sorted(totals.items(), reverse=True)))
            outcomes.append(OutcomeBook(outcome_id=o.native_id, bids=ladder if self.initialized else None))
        return OrderBook(raw=raw, outcomes=tuple(outcomes), quantity_unit='payout_cents', state=state,
            sync=BookSync.UNKNOWN if self.initialized and transport else BookSync.UNSYNCHRONIZED,
            source_time_progress=SourceTimeProgress.MISSING, receipt_freshness=ReceiptFreshness.UNKNOWN)


def quotes(book):
    # Native bids only: complementary asks are deliberately left unavailable.
    return tuple(Quote(raw=book.raw, outcome_id=o.outcome_id, state=book.state,
        bid=QuoteSide(price=o.bids.levels[0].price, quantity=o.bids.levels[0].quantity)
        if o.bids and o.bids.levels else None) for o in book.outcomes)


class NovigAdapter(ReadOnlyAdapter):
    venue = Venue.NOVIG

    def __init__(self, *, environment, client_id, client_secret, client=None, league='NFL',
                 max_requests=30, max_pages=1, page_size=5, max_markets=2, retries=1,
                 max_bytes=8_000_000, sleep=asyncio.sleep, clock=time.monotonic, now=None,
                 stream_factory=None, stream_options=None, evidence_kind=EvidenceKind.OBSERVATION):
        if environment not in HOSTS:
            raise ValueError('explicit QA or production required')
        for n, limit in ((max_requests,100),(max_pages,5),(page_size,100),(max_markets,10),(max_bytes,50_000_000)):
            if type(n) is not int or not 1 <= n <= limit:
                raise ValueError('invalid bound')
        if type(retries) is not int or not 0 <= retries <= 2 or league not in ('NFL','MLB'):
            raise ValueError('invalid retry or league')
        self.environment, self.client_id, self.client_secret = environment, identity(client_id), identity(client_secret)
        self.client = client or httpx.AsyncClient(timeout=5, follow_redirects=False)
        self.league, self.max_requests, self.max_pages, self.page_size = league,max_requests,max_pages,page_size
        self.max_markets,self.retries,self.max_bytes = max_markets,retries,max_bytes
        self.sleep,self.clock,self.now = sleep,clock,now or (lambda: datetime.now(timezone.utc))
        self.stream_factory,self.stream_options = stream_factory,stream_options or {}
        self.kind = evidence_kind
        self.requests,self.bytes,self.renewals = 0,0,0
        self.token,self.expires = None,0
        self.closed = False
        self.responses,self.http_statuses,self.streams = [],[],set()
        self.events,self.markets,self.metadata,self.event_status = {},{},{},{}
        self.locks = None
        self.truncated = False
        self._mutex = asyncio.Lock()

    async def _request(self, method, url, **kwargs):
        if self.closed or self.requests >= self.max_requests:
            raise RuntimeError('closed or request budget exhausted')
        self.requests += 1
        await self.sleep(.25)  # 4 requests/sec, well below all published ceilings
        async with self.client.stream(method, url, **kwargs) as r:
            body = bytearray()
            async for part in r.aiter_bytes():
                self.bytes += len(part)
                if self.bytes > self.max_bytes:
                    raise RuntimeError('response storage budget exhausted')
                body.extend(part)
            self.http_statuses.append(r.status_code)
            return r.status_code, r.headers, body.decode('utf-8')

    async def access_token(self, force=False):
        async with self._mutex:
            if self.token and not force and self.clock() < self.expires:
                return self.token
            payload = {'grant_type':'client_credentials','client_id':self.client_id,'client_secret':self.client_secret}
            if self.environment == 'qa':
                payload['audience'] = HOSTS['qa']
            for attempt in range(self.retries+1):
                try:
                    status,headers,body = await self._request('POST',AUTH[self.environment],json=payload)
                except httpx.TransportError:
                    if attempt == self.retries: raise ConnectionError('Novig auth transport failed') from None
                    await self._delay({},attempt); continue
                if status == 200:
                    data = decode(body)
                    token = identity(data['access_token'])
                    lifetime = parse_decimal(data.get('expires_in',1800))
                    if lifetime <= 30:
                        raise ValueError('token lifetime too short')
                    self.token,self.expires = token,self.clock()+float(min(lifetime,Decimal(1800)))-30
                    self.renewals += 1
                    return token
                if status not in (429,500,502,503,504) or attempt == self.retries:
                    raise ConnectionError(f'Novig authentication HTTP {status}')
                await self._delay(headers,attempt)

    async def _delay(self, headers, attempt):
        delay = max(Decimal(2)**attempt, parse_decimal(headers.get('Retry-After','0'))/1000,
                    parse_decimal(headers.get('X-RateLimit-Reset','0'))/1000)
        if delay > 10:
            raise ConnectionError('retry delay exceeds bounded wait')
        await self.sleep(float(delay))

    async def _get(self,path,params=None):
        for attempt in range(self.retries+1):
            token = await self.access_token()
            try:
                status,headers,body = await self._request('GET',HOSTS[self.environment]+'/nbx/v2/emm/'+path,
                    params=params,headers={'Authorization':'Bearer '+token})
            except httpx.TransportError:
                if attempt == self.retries: raise ConnectionError('Novig REST transport failed') from None
                await self._delay({},attempt); continue
            if status == 200:
                decode(body)
                r=Response(body,HOSTS[self.environment]+'/nbx/v2/emm/'+path + ('?'+str(httpx.QueryParams(params)) if params else ''),self.now(),self.kind)
                self.responses.append(r)
                if headers.get('X-RateLimit-Remaining') == '0':
                    await self._delay(headers,0)
                return r
            if status == 404:
                raise LookupError(path)
            if status == 401 and attempt < self.retries:
                await self.access_token(force=True)
                continue
            if status not in (429,500,502,503,504) or attempt == self.retries:
                raise ConnectionError(f'Novig REST HTTP {status}')
            await self._delay(headers,attempt)

    async def discover_events(self):
        found={}
        for page in range(self.max_pages):
            r=await self._get('events',{'league':self.league,'type':'Game','status':'OPEN_PREGAME',
                'limit':self.page_size,'offset':page*self.page_size})
            rows=decode(r.body)
            if not isinstance(rows,list): raise ValueError('expected event list')
            for d in rows:
                eid=identity(d['id']); start=timestamp(d.get('scheduledStart'))
                if eid in found: raise ValueError('duplicate event across pages')
                if d.get('league') != self.league or d.get('status') != 'OPEN_PREGAME' or not start or start <= self.now():
                    continue
                found[eid]=Event(raw=r.raw(eid),title=d['description'],league=self.league,scheduled_start=start)
                self.event_status[eid]=d['status']
            if len(rows)<self.page_size: break
        else: self.truncated=True
        self.events=found
        return tuple(found.values())

    async def discover_markets(self,event_id=None):
        if not self.events: await self.discover_events()
        if event_id is not None and event_id not in self.events: raise LookupError(event_id)
        result={}
        for eid in ((event_id,) if event_id else tuple(self.events)):
            r=await self._get('events/getMarketsByEvent/'+quote(eid,safe=''),{'currency':'CASH'})
            rows=decode(r.body)
            if not isinstance(rows,list): raise ValueError('expected market list')
            for d in rows:
                m=parse_market(r,d,eid)
                if m.raw.ref.market_id in result: raise ValueError('duplicate market')
                if len(result)>=self.max_markets:
                    self.truncated=True; break
                result[m.raw.ref.market_id]=m; self.metadata[m.raw.ref.market_id]=d
            if len(result)>=self.max_markets: break
        self.markets.update(result)
        return tuple(result.values())

    def _market(self,mid):
        if self.closed: raise RuntimeError('adapter closed')
        if mid not in self.markets: raise LookupError(mid)
        return self.markets[mid]

    async def refresh_locks(self):
        self.locks=None
        r=await self._get('locks'); d=decode(r.body)
        if 'systemLock' not in d or not isinstance(d.get('lockedEventIds'),list): raise ValueError('invalid locks')
        if d['systemLock'] is not None and not isinstance(d['systemLock'],dict): raise ValueError('invalid system lock')
        for eid in d['lockedEventIds']: identity(eid)
        self.locks=r

    def effective_state(self,market):
        if market.state in (MarketState.CLOSED,MarketState.SETTLED): return market.state
        if self.locks is None or (self.now()-self.locks.received_at).total_seconds()>5: return MarketState.UNKNOWN
        d=decode(self.locks.body)
        if d['systemLock'] is not None or market.raw.ref.event_id in d['lockedEventIds']: return MarketState.SUSPENDED
        event_state=self.event_status.get(market.raw.ref.event_id)
        if event_state in ('FINAL','CANCELED'):
            return MarketState.CLOSED if event_state=='FINAL' else MarketState.CANCELED
        if event_state in ('DELAYED','CLOSED_PREGAME'): return MarketState.SUSPENDED
        if event_state not in ('OPEN_PREGAME','OPEN_INGAME'): return MarketState.UNKNOWN
        return market.state

    async def refresh_event(self,eid):
        r=await self._get('events/'+quote(eid,safe='')); d=decode(r.body)
        if d.get('id') != eid: raise ValueError('event mismatch')
        self.event_status[eid]=d['status']

    async def refresh_market_states(self,eid):
        r=await self._get("events/getMarketsByEvent/"+quote(eid,safe=""),{"currency":"CASH"})
        rows=decode(r.body)
        if not isinstance(rows,list): raise ValueError("expected markets")
        found={}
        for d in rows:
            if d.get("id") in self.markets:
                m=parse_market(r,d,eid); found[m.raw.ref.market_id]=m
        expected={mid for mid,m in self.markets.items() if m.raw.ref.event_id==eid}
        if set(found)!=expected: raise ValueError("selected market absent on recovery")
        self.markets.update(found)

    async def get_snapshot(self,market_id):
        m=self._market(market_id)
        await self.refresh_event(m.raw.ref.event_id)
        await self.refresh_market_states(m.raw.ref.event_id)
        m=self._market(market_id)
        await self.refresh_locks()
        r=await self._get('book/'+quote(market_id,safe=''),{'currency':'CASH'})
        image=OrderImage(m); image.snapshot(decode(r.body))
        return image.book(r.raw(m.raw.ref.event_id,market_id),self.effective_state(m))

    async def get_market_rules(self,market_id):
        m=self._market(market_id)
        # NBX schema exposes no listing-specific rule link; do not infer one.
        return SettlementProfile(raw=m.raw)

    async def get_fee_metadata(self,market_id):
        m=self._market(market_id)
        return {'native_market':m.raw,'event_status':self.event_status.get(m.raw.ref.event_id),
            'schedule_source':'https://docs.novig.com/fees','effective_fee':None,
            'listing_rule_source':None,'account_terms':None}

    async def stream_markets(self,market_ids):
        from app.adapters.novig_stream import MarketStream
        if not isinstance(market_ids,tuple) or not 1<=len(market_ids)<=self.max_markets or len(set(market_ids))!=len(market_ids):
            raise ValueError('bounded unique market tuple required')
        stream=MarketStream(self,[self._market(mid) for mid in market_ids],**self.stream_options)
        self.streams.add(stream)
        try:
            async with aclosing(stream.run()) as updates:
                async for update in updates: yield update
        finally:
            await stream.aclose(); self.streams.discard(stream)

    async def aclose(self):
        self.closed=True
        for stream in tuple(self.streams): await stream.aclose()
        self.token=None; self.client_secret=''
        await self.client.aclose()
