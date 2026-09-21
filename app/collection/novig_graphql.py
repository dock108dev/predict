"""Replaceable discovery/display bridge. No NBX unit or executable-ask claims."""
import asyncio
import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import httpx
from .native_product import NativeVenue,empty_catalog

ENDPOINT='https://gql.novig.com/v1/graphql'
QUERY='''query PredictPregame {
  event(where: {status: {_eq: "OPEN_PREGAME"}, game: {league: {_eq: "NFL"}}}) {
    id description game { scheduled_start }
    markets { description outcomes { description last available } }
  }
}'''
REASON='GraphQL display only: native market IDs, period, rules, size and purchase semantics unverified'


def catalog(body,received_at):
    d=json.loads(body)
    if d.get('errors'):raise ValueError('GraphQL errors; partial data rejected')
    events=d['data']['event']
    if not isinstance(events,list) or len(events)>20:raise ValueError('GraphQL event cap')
    c=empty_catalog('display_only');c.update(environment='public',update_path='dated GraphQL display',event_discovery='bounded; pagination undocumented',market_completeness='unknown')
    for e in events:
        eid=e['id']
        if not isinstance(eid,str) or not eid or any(x['id']==eid for x in c['events']):raise ValueError('event identity')
        c['events'].append(dict(id=eid,title=e['description'],scheduled_start=e['game']['scheduled_start'],participants={},identity='unresolved',canonical_key=None,exclusion=REASON,sport='american_football',competition='NFL'))
        for index,m in enumerate(e['markets']):
            if len(c['markets'])>=100:raise ValueError('GraphQL market cap')
            prices=[]
            for o in m['outcomes']:
                for name in ('last','available'):
                    value=o.get(name)
                    if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not 0<=value<=1):raise ValueError('invalid display probability')
                prices.append(dict(label=o['description'],last=o.get('last'),available=o.get('available')))
            # Positional display IDs explicitly never enter native matching.
            c['markets'].append(dict(id=f'display:{eid}:{index}',event_id=eid,title=m['description'],market_type='unknown',period='unknown',status='unknown',exclusion=REASON,product_outcomes=[],terms={},sides=[],display_prices=prices,received_at=received_at,native_metadata=m,provenance=dict(source=ENDPOINT,received_at=received_at,sha256=sha256(body.encode()).hexdigest())))
    from .coverage import match_catalogs
    match_catalogs({'novig':c})
    return c


class GraphQLVenue(NativeVenue):
    async def native_discover(self):
        if self.config['state']!='enabled':return empty_catalog(self.config['state']),{}
        if getattr(self,'discovery_failed',False):return empty_catalog('unavailable',self.reason),{}
        try:
            if self.session.spec['mode']=='real' and not getattr(self.session,'native_authorized',False):raise ValueError('public collection approval required')
            transport=getattr(self.session,'graphql_fixture_transport',None)
            if self.session.spec['mode']=='mock' and transport is None:raise ValueError('fixture transport required')
            if self.session.spec['mode']!='mock' and transport is not None:raise ValueError('fixture-only injection')
            if self.budget.requests>=2:raise ValueError('GraphQL request cap')
            self.budget.requests+=1
            async with asyncio.timeout(10):
                async with httpx.AsyncClient(transport=transport,follow_redirects=False,timeout=5) as client:
                    async with client.stream('POST',ENDPOINT,json={'query':QUERY}) as r:
                        r.raise_for_status();data=bytearray()
                        async for part in r.aiter_bytes():
                            self.budget.bytes+=len(part)
                            if self.budget.bytes>1_000_000:raise ValueError('GraphQL byte cap')
                            data.extend(part)
            at=datetime.now(timezone.utc).isoformat();body=data.decode();c=catalog(body,at)
            self.session.emit('novig',dict(type='native_graphql_observation',body_b64=base64.b64encode(data).decode(),body_sha256=sha256(data).hexdigest(),received_at=at,source_url=ENDPOINT,query=QUERY))
            self.health('display_only');return c,{}
        except asyncio.CancelledError:raise
        except Exception as exc:
            self.discovery_failed=True;self.health('unavailable',type(exc).__name__)
            return empty_catalog('unavailable',type(exc).__name__),{}

    async def run(self,markets):
        await self.session.stop_event.wait()

    def snapshot(self):
        return dict(state=self.state,reason=self.reason,requests=self.budget.requests,body_bytes_charged=self.budget.bytes,connection_attempts=0,update_path='dated GraphQL display',usable=0,receiving=0,requested=0,acknowledged=0,semantics=dict(prices='displayed available and last; not normalized purchase asks',quantity='not queried; unknown',fees='unverified',settlement='unknown'))

    def account(self):pass
