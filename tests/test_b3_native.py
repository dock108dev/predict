import asyncio
from dataclasses import replace
from decimal import Decimal,localcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from app.collection.native_semantics import purchase_book
from app.collection.native_product import validate_sources,REFERENCES,catalog_from
from app.adapters.novig import NovigAdapter,OrderImage,parse_market
from app.novig_example import MARKET,response,snapshot,order
from tests.test_polymarket_us import captured,market
from app.adapters.polymarket_us import parse_book,decode
from app.models.core import EvidenceKind


def configuration():
    from app.dashboard.coverage_owner import spec
    s=spec();s.update(mode='mock',reference_enabled=False)
    s['native_sources']={v:dict(state='enabled',environment='production',poll_seconds=10,event_cap=1,market_cap=2) for v in ('kalshi','polymarket_us')}
    s['native_sources']['novig']=dict(state='enabled',environment='qa',credential_reference=REFERENCES['novig']['qa'],leagues=['NFL'],poll_seconds=10,event_cap=1,market_cap=2)
    s['native_sources']['prophetx']=dict(state='unselected')
    return s

class Semantics(unittest.TestCase):
    def test_novig_original_units_and_asks(self):
        m=parse_market(response(MARKET),MARKET,'synthetic-event');i=OrderImage(m)
        d=snapshot();d['outcomeLadders'][0]['bids']=[order(qty='45000',price='.360')];i.snapshot(d)
        b=i.book(response(d).raw('synthetic-event','synthetic-market'))
        n=purchase_book(b)
        self.assertEqual(b.outcomes[0].bids.levels[0].quantity.value,45000)
        ask=n.outcomes[1].asks.levels[0]
        self.assertEqual((ask.price.value,ask.quantity.value),(Decimal('.640'),Decimal('450')))
        self.assertEqual(ask.price.value*ask.quantity.value,Decimal('288'))
        self.assertEqual(n.raw,b.raw);self.assertEqual(n.sync,b.sync);self.assertEqual(n.outcomes[1].asks.depth,b.outcomes[0].bids.depth)
        i.tick('PLACE',order(qty='100',price='.360'));n=purchase_book(i.book(b.raw))
        self.assertEqual(n.outcomes[1].asks.levels[0].quantity.value,1)
    def test_us_retained_short_fractional_native_identity(self):
        r=captured('pmus-tb-cin-book.json');b=parse_book(r,decode(r.body)['marketData'],market())
        with localcontext() as ctx:
            ctx.prec=3;n=purchase_book(b)
        self.assertEqual(n.outcomes[1].outcome_id,'763431')
        for original,derived in zip(b.outcomes[0].bids.levels,n.outcomes[1].asks.levels):
            self.assertEqual(derived.price.value,1-original.price.value)
            self.assertEqual(derived.quantity,original.quantity)
        self.assertEqual(n.raw,b.raw);self.assertIsNone(b.outcomes[1].asks)
    def test_disabled_reject_secrets_and_validate(self):
        s=configuration();validate_sources(s)
        s['native_sources']['novig']['client_secret']='forbidden'
        with self.assertRaises(ValueError):validate_sources(s)

class Runtime(unittest.IsolatedAsyncioTestCase):
    async def test_native_rest_into_ordinary_product_and_saved_cutoff(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer,TestClient
        from tests.segmented_collector_fixture import Fixture
        from app.collection.continuous import ContinuousSession
        from app.dashboard.coverage_owner import CoverageOwner
        from app.dashboard.multi_game_server import create_app
        from app.dashboard.session_history import load
        f=Fixture();calls=[];adapters=[]
        async def native_factory(venue,c,observer):
            self.assertEqual(venue,'novig')
            async def handler(req):
                calls.append(req.url.path)
                if req.url.path.endswith('/oauth/token'):return httpx.Response(200,json=dict(access_token='fixture-token-unique',expires_in=1800))
                if req.url.path.endswith('/events'):return httpx.Response(200,json=[dict(id='n-event',description='Detroit Lions vs Buffalo Bills',league='NFL',status='OPEN_PREGAME',scheduledStart=f.schedule)])
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
            # Explicit synthetic full-game fixture; native period remains unverified.
            original=a.discover_markets
            async def markets(eid):return tuple(replace(m,period='full_game') for m in await original(eid))
            a.discover_markets=markets;adapters.append(a);return [a]
        class Session(ContinuousSession):
            native_adapter_factory=staticmethod(native_factory)
        feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
        f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
        f.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
        with tempfile.TemporaryDirectory() as t,patch('app.collection.native_product.load_native_secret',side_effect=AssertionError('secret lookup forbidden')):
            o=CoverageOwner(Path(t)/'old',pilot_output=Path(t)/'new',endpoints=f.endpoints,product_mode=True,spec_factory=configuration,session_factory=Session);f.owner=o
            client=TestClient(TestServer(create_app(owner=o,sessions={})));await client.start_server()
            try:
                await o.start(duration=30)
                save=o.session.journal.save
                def observed(row):
                    save(row);f.books+=row['type']=='prediction_book';f.changed.set()
                o.session.journal.save=observed
                async with asyncio.timeout(10):
                    while len(f.active())!=2:await asyncio.sleep(.01)
                await f.images()
                await asyncio.sleep(.1)
                self.assertTrue(o.session.producers['novig'].ever['receiving'], {'catalog':o.session.discovery.inventory,'health':o.session.health,'calls':calls})
                result=await (await client.get('/api/dashboard')).json()
                self.assertTrue(any('novig' in r['venues'] for r in result['rows']),result)
                self.assertEqual(next(s for s in result['sources'] if s['source_id']=='prophetx')['state'],'unselected')
                snap=o.current_snapshot();cutoff=snap['durable_cursor'];sid=snap['session_id']
                self.assertTrue(any('native_rest_observation'==r['type'] for r in __import__('app.collection.transport_session',fromlist=['reopen']).reopen(o.session.journal.path)['rows']))
                await o.stop();await o.finalizer
                from app.collection.native_rest_replay import verify
                from app.collection.transport_session import reopen
                verify(reopen(o.session.journal.path)['rows'])
                self.assertIsNone(o.error);self.assertTrue(adapters[0].closed)
                self.assertEqual(o.session.health['novig'],'disconnected')
                self.assertEqual(snap['games'],load(Path(t)/'new'/sid,cutoff)['games'])
                self.assertFalse(o.session.emit('novig',dict(type='late')))
                self.assertTrue(calls);self.assertFalse(f.active())
            finally:await client.close();await f.close()


class Boundaries(unittest.IsolatedAsyncioTestCase):
    async def test_unselected_slot_never_calls_factory_or_secret_store(self):
        from types import SimpleNamespace
        from app.collection.native_product import NativeVenue
        stop=asyncio.Event();stop.set();rows=[]
        session=SimpleNamespace(spec=configuration(),intake_closed=False,stop_event=stop,health={'prophetx':'idle'},emit=lambda v,r:rows.append((v,r)))
        p=NativeVenue(session,'prophetx',dict(state='unselected'))
        with patch('app.collection.native_product.load_native_secret',side_effect=AssertionError('forbidden')):
            cat,_=await p.native_discover();await p.run({});await p.aclose()
        self.assertEqual(cat['state'],'unselected');self.assertEqual(p.adapters,[]);self.assertEqual(p.budget.requests,0)

    async def test_failed_market_does_not_stop_other_market_or_session(self):
        from types import SimpleNamespace
        from app.collection.native_product import NativeVenue
        stop=asyncio.Event();rows=[]
        async def pause(_):stop.set()
        session=SimpleNamespace(spec=configuration(),stop_event=stop,health={'novig':'idle'},emit=lambda v,r:rows.append(r),queue=asyncio.Queue(),pause=pause)
        c=configuration()['native_sources']['novig'];p=NativeVenue(session,'novig',c)
        m=parse_market(response(MARKET),MARKET,'synthetic-event');i=OrderImage(m);i.snapshot(snapshot());b=i.book(response(snapshot()).raw('synthetic-event','synthetic-market'))
        class Adapter:
            async def get_snapshot(self,mid):
                if mid=='bad':raise ConnectionError('fixture unavailable')
                return b
        a=Adapter();p.adapter_by_market={'bad':a,'synthetic-market':a};p.markets={'synthetic-market':m}
        session.discovery=SimpleNamespace(inventory={'novig':{'selection':{'ids':['bad','synthetic-market']}}})
        await p.run({})
        self.assertEqual(p.failed_markets,{'bad'});self.assertEqual(p.ever['receiving'],{'synthetic-market'})
        self.assertEqual([r['market_ids'] for r in rows if r['type']=='source_health' and r['state']=='unavailable'],[['bad']])
        self.assertTrue(any(r['type']=='prediction_book' for r in rows))

class Approval(unittest.TestCase):
    def test_exact_scope_identity_consumption_and_explicit_approval(self):
        from app.collection.native_approval import validate_approval,digest
        from app.collection.venue_access import ENDPOINTS
        from app.dashboard.coverage_owner import spec
        s=spec();s['native_sources']=configuration()['native_sources'];s['native_sources']['novig']=dict(state='not_configured');s.pop('multi_game_limits',None)
        with tempfile.TemporaryDirectory() as t,patch('app.collection.native_approval.implementation',return_value={'candidate':'hash'}):
            p=Path(t)/'approval.json';a=dict(approved=False,spec_sha256=digest(s),implementation_sha256=digest({'candidate':'hash'}),output=str(Path(t).resolve()));p.write_text(json.dumps(a))
            with self.assertRaises(ValueError):validate_approval(s,ENDPOINTS,p,t)
            a['approved']=True;p.write_text(json.dumps(a));validate_approval(s,ENDPOINTS,p,t)
            changed=dict(s,duration=s['duration']-1)
            with self.assertRaises(ValueError):validate_approval(changed,ENDPOINTS,p,t)
            validate_approval(s,ENDPOINTS,p,t,consume=True)
            with self.assertRaises(ValueError):validate_approval(s,ENDPOINTS,p,t)

class RetainedProphet(unittest.IsolatedAsyncioTestCase):
    async def test_actual_sandbox_prices_enter_product_as_unsized_dated_quotes(self):
        from tests.test_prophetx_live_replay import ReplayClient,captured
        from app.adapters.prophetx import ProphetXAdapter
        from app.arbitrage import book_observations
        from app.storage.workflow import packet
        from app.dashboard.session_projection import SessionProjection
        from dataclasses import asdict
        from datetime import datetime,timezone
        import base64
        a=ProphetXAdapter(ReplayClient(),tournament_ids=('31',))
        events=await a.discover_events();markets=await a.discover_markets('19458')
        e=next(e for e in events if e.raw.ref.event_id=='19458');m=next(m for m in markets if m.raw.ref.market_id=='19458:219:0');b=a.native_books[m.raw.ref.market_id]
        cat,_=catalog_from([e],[m],'sandbox',at=datetime(2026,9,12,tzinfo=timezone.utc))
        self.assertEqual(cat['events'][0]['competition'],'NFL');self.assertEqual(cat['events'][0]['sport'],'american_football');self.assertEqual(cat['markets'][0]['period'],'full_game')
        p=SessionProjection();at=b.raw.received_at.isoformat()
        def emit(source,r):p.apply(dict(r,source=source,observed_at=at,session_id='retained-sandbox',ingress_id=str(p.cursor)))
        emit('session',dict(type='session_started',spec=dict(mode='real',native_sources={'prophetx':dict(environment='sandbox')},mapping_revision='retained-replay')))
        emit('session',dict(type='coverage_inventory',inventory={'prophetx':cat},generation=1,previous_generation=None))
        emit('prophetx',dict(type='market_selected',market=json.loads(json.dumps(asdict(m),default=str))))
        observations=book_observations(b,environment='sandbox',evidence_class='historical',source_time_semantics='unknown');prices={q.outcome_id:q for q in b.normalized_quotes};packets=[]
        for o in observations:
            o=replace(o,quote=prices.get(o.quote.outcome_id,o.quote));x=packet(o);x['raw_b64']=base64.b64encode(x.pop('raw')).decode();packets.append(x)
        emit('prophetx',dict(type='prediction_book',book=json.loads(json.dumps(asdict(b),default=str)),packets=packets,update_path='dated REST snapshot'))
        snap=p.snapshot(mode='saved');quotes=snap['market_catalog'][0]['quotes']
        self.assertEqual(len(quotes),2);self.assertTrue(all(q['ask_size'] is None for q in quotes))
        self.assertLess(abs(Decimal(quotes[0]['ask'])-Decimal(100)/Decimal(246)),Decimal('1e-27'))
        self.assertEqual(snap['sources'][-1]['environment'],'sandbox')
