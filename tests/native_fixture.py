"""Native-shaped Novig fixture; explicit synthetic period, no provider access."""
import asyncio
from dataclasses import replace
import httpx
from app.adapters.novig import NovigAdapter
from app.models.core import EvidenceKind
from app.novig_example import MARKET,snapshot


def factory(fixture):
    async def build(venue,config,observer):
        if venue!='novig':raise AssertionError('unselected source must not activate')
        async def handler(req):
            if req.url.path.endswith('/oauth/token'):return httpx.Response(200,json=dict(access_token='fixture-token-unique',expires_in=1800))
            if req.url.path.endswith('/events'):return httpx.Response(200,json=[dict(id='n-event',description='Detroit Lions vs Buffalo Bills',league='NFL',status='OPEN_PREGAME',scheduledStart=fixture.schedule)])
            if req.url.path.endswith('/events/n-event'):return httpx.Response(200,json=dict(id='n-event',status='OPEN_PREGAME'))
            native=dict(MARKET,id='n-market',eventId='n-event',outcomeIds=['home','away'],outcomes=[dict(id='home',description='Buffalo Bills'),dict(id='away',description='Detroit Lions')])
            if 'getMarketsByEvent' in req.url.path:return httpx.Response(200,json=[native])
            if req.url.path.endswith('/locks'):return httpx.Response(200,json=dict(systemLock=None,lockedEventIds=[]))
            if req.url.path.endswith('/book/n-market'):
                d=snapshot();d['marketId']='n-market'
                for ladder in d['outcomeLadders']:
                    for o in ladder['bids']:o['marketId']='n-market'
                return httpx.Response(200,json=d)
            raise AssertionError(req.url.path)
        async def sleep(_):await asyncio.sleep(0)
        a=NovigAdapter(environment='qa',client_id='fixture-client-unique',client_secret='fixture-secret-unique',client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),sleep=sleep,retries=0,observer=observer,evidence_kind=EvidenceKind.SYNTHETIC)
        original=a.discover_markets
        async def markets(eid):return tuple(replace(m,period='full_game') for m in await original(eid))
        a.discover_markets=markets
        return [a]
    return build
