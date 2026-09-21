"""Injected transports. Synthetic event time advances with real monotonic time."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from time import monotonic
from app.reference.fixtures import before, payload, source, assessment
from app.reference.adapter import Response
from app.pricing.fixtures import target
from dataclasses import replace
from app.fees.engine import digest


def knowledge():
    at = before(10000)
    return (replace(source(identity='source-synthetic-e6'), effective_at=at, known_at=at),
            replace(assessment(), effective_at=at, known_at=at),
            target(effective_at=at, known_at=at))


class WallClock:
    def __init__(self, origin=None):
        self.origin = datetime.fromisoformat(origin or before(7200))
        self.started = monotonic()
    def now(self): return (self.origin + timedelta(seconds=monotonic()-self.started)).isoformat()
    async def sleep(self, seconds): await asyncio.sleep(seconds)


class ReferenceTransport:
    def __init__(self, clock, interruption=300, outage=8, failure=None):
        self.clock=clock; self.start=monotonic(); self.interruption=interruption; self.outage=outage
        self.failure=failure; self.calls=0; self.closed=False
    async def request(self, request):
        self.calls+=1
        elapsed=monotonic()-self.start
        if self.interruption is not None and self.interruption<=elapsed<self.interruption+self.outage:
            raise OSError('injected reference disconnect')
        if self.failure=='quota': return Response(200,payload(),(('x-requests-remaining','0'),))
        if self.failure=='entitlement': return Response(403,b'{"synthetic":"no entitlement"}')
        body=payload().replace(before(65).encode(),self.clock.now().encode())
        if self.calls in (7,21): body=body.replace(b'2.1000',b'0.5000')
        elif self.calls%3: body=body.replace(b'2.1000',b'2.2000')
        return Response(200,body,(('x-requests-remaining',str(200-self.calls)),))
    async def aclose(self): self.closed=True


class PredictionTransport:
    def __init__(self, venue, template, clock, interruption=None, outage=8, stale=False):
        self.venue=venue; self.template=template; self.clock=clock; self.start=monotonic()
        self.interruption=interruption; self.outage=outage; self.stale=stale; self.calls=0; self.closed=False
    async def snapshot(self):
        self.calls+=1
        elapsed=monotonic()-self.start
        if self.interruption is not None and self.interruption<=elapsed<self.interruption+self.outage:
            raise OSError('injected prediction disconnect')
        b=deepcopy(self.template); at=self.clock.now()
        b['known_at']=b['effective_at']=at
        raw=b['observation']['quote']['raw']; raw['received_at']=at
        raw['exchange_at']=(datetime.fromisoformat(at)-timedelta(seconds=60)).isoformat() if self.stale else at
        price='0.2' if self.calls%3 else '0.55'
        b['observation']['quote']['ask']['price']['value']=price
        b['levels']=[list(x) for x in b['levels']]
        b['levels'][0][0]=price
        import json
        raw['json_text']=json.dumps({'synthetic':True,'venue':self.venue,'snapshot':self.calls,'levels':b['levels']})
        raw['source']='synthetic:E6-injected-full-snapshot'
        b['evidence']='synthetic:E6 delivered full snapshot; invented existing fixture terms'
        b['id']=digest({k:v for k,v in b.items() if k!='id'})
        return b
    async def aclose(self): self.closed=True


class DiscoveryTransport:
    def __init__(self, change=None, after=1): self.calls=0; self.change=change; self.after=after; self.closed=False
    async def discover(self):
        from app.reference.records import EVENT
        from app.reference.fixtures import terms
        self.calls+=1
        row=dict(event=EVENT,start=terms().scheduled_start.isoformat(),resolved=True,phase='pregame',present=True)
        if self.change and self.calls>self.after:
            if self.change=='schedule': row['start']=(terms().scheduled_start+timedelta(hours=1)).isoformat()
            if self.change=='disappearance': row['present']=False
            if self.change=='identity': row['resolved']=False
            if self.change=='kickoff': row['phase']='inplay'
        return row
    async def aclose(self): self.closed=True
