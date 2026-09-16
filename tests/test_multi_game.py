import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp.test_utils import AioHTTPTestCase
from app.dashboard.opportunity_board import load_sessions,catalog
from app.dashboard.multi_game import configuration,MultiOwner,project_game,default_point,game_calculation,rank_filter
from app.collection.multi_game import native_identity,common_events
from app.collection.run_spec import preflight
from app.collection.native_replay import verify_native_saved
from app.dashboard.multi_game_server import create_app
from app.opportunities.board import SIDES,TEAMS,CANDIDATES

class MultiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sessions=load_sessions();cls.p,cls.rows=next(iter(cls.sessions.values()));src=cls.rows[0]['spec']['sources']
        cls.game=dict(id=src['kalshi']['event_id']+'__'+src['polymarket_us']['event_id'],title='Detroit at Buffalo',scheduled_start=cls.p['kickoff'],teams=list(TEAMS),sides={k:dict(v,**({'native_label':'Long' if k.endswith('1315440') else 'Short'} if k.startswith('polymarket') else {})) for k,v in SIDES.items()},sources=src,candidates=CANDIDATES)
    def test_preflight_bounds(self):
        s=configuration();lim=s.pop('multi_game_limits');self.assertTrue(preflight(s)['valid']);self.assertLessEqual(s['duration'],180);self.assertEqual(lim['max_games'],6);self.assertEqual(lim['concurrent_sockets'],2)
    def test_cross_event_isolation_and_unknown_probability(self):
        t,rows=project_game(self.rows,self.game);p=default_point(t)
        r=game_calculation(p,rows,self.game,'100','cent')
        self.assertIsNone(r['ev']['probability']);self.assertIsNone(r['ev']['expected_profit']);self.assertEqual(r['ev']['status'],'Assumption needed')
        foreign=deepcopy(next(r for r in self.rows if r['type']=='prediction_book'))
        foreign['book']['raw']['ref']['event_id']='another-game'
        t2,_=project_game(self.rows+[foreign],self.game)
        self.assertEqual(t,t2)
        foreign=deepcopy(next(r for r in self.rows if r['type']=='prediction_book'));foreign['game_id']='different'
        with self.assertRaises(ValueError):project_game(self.rows+[foreign],self.game)
    def test_depth_capped_and_supported_purchase(self):
        t,rows=project_game(self.rows,self.game);p=default_point(t)
        r=game_calculation(p,rows,self.game,'100000000','cent')
        for c in r['candidates']:
            self.assertTrue(c['depth_limited']);self.assertLess(Decimal(c['modeled_quantity']),Decimal('100000000'))
        short=next(c for c in r['contracts'] if c['id'].endswith('1315441'));self.assertIsNone(short['ask'])
    def test_sort_filter_unknown_negative_positive_stale(self):
        base=dict(status='Conditional scenario',usable=True,venues=['kalshi'],venue_pair='kalshi',game_title='Detroit Buffalo')
        rows=[dict(base,id='positive',profit='2',return_pct='3'),dict(base,id='negative',profit='-2',return_pct='-1'),dict(base,id='unknown',profit=None,return_pct=None),dict(base,id='stale',profit='100',return_pct='100',usable=False)]
        self.assertEqual([r['id'] for r in rank_filter(rows)],['positive','negative','unknown','stale'])
        self.assertEqual([r['id'] for r in rank_filter(rows,positive=True,freshness='usable')],['positive'])
        self.assertEqual(rank_filter(rows,search='jets'),[]);self.assertEqual(rank_filter(rows,venue='polymarket_us'),[])
    def test_real_near_miss_and_ev_separation(self):
        t,rows=project_game(self.rows,self.game);p=default_point(t)
        a=game_calculation(p,rows,self.game,'100','cent','.4');b=game_calculation(p,rows,self.game,'100','cent','.2')
        self.assertEqual([(x['id'],x['profit'],x['return_pct']) for x in a['candidates']],[(x['id'],x['profit'],x['return_pct']) for x in b['candidates']]);self.assertNotEqual(a['ev']['expected_profit'],b['ev']['expected_profit'])
        c=next(c for c in a['candidates'] if c['id']=='cross-buffalo');self.assertEqual(Decimal(c['profit']),Decimal('-3.86'))
        self.assertIsNone(game_calculation(p,rows,self.game,'100','unknown','.4')['ev']['expected_profit'])
    def test_freshness_and_saved(self):
        t,rows=project_game(self.rows,self.game,live=True);r=game_calculation(t[-1],rows,self.game,'100','cent')
        self.assertTrue(all(not c['usable'] for c in r['candidates']))
        saved={'rows':self.rows,'sha256':'test','state':'complete'};r=verify_native_saved(saved);self.assertTrue(r['exact_packets'])

class HTTPTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp=tempfile.TemporaryDirectory();self.owner=MultiOwner(Path(self.tmp.name),spec_factory=configuration)
        with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('idle access')):
            return create_app(owner=self.owner)
    async def test_dashboard_drilldown_and_no_default_ev(self):
        r=await(await self.client.get('/api/dashboard')).json();self.assertEqual(r['coverage']['selected'],1);self.assertEqual(len(r['rows']),3)
        row=r['rows'][0];q={k:row[k] for k in ('session','hash','cutoff')};q.update(quantity='100',scenario='cent',probability='.4')
        detail=await(await self.client.get('/api/calculate',params=q)).json();self.assertEqual(detail['game']['id'],row['game_id']);self.assertEqual(detail['quantity'],'100')
        ev=await(await self.client.get('/api/dashboard',params={'view':'ev'})).json();self.assertTrue(all(x['profit'] is None for x in ev['rows']))
        self.assertFalse((await(await self.client.get('/api/status')).json())['active'])
    async def test_guard_persists_without_dispatch(self):
        (Path(self.tmp.name)/'attempt.json').write_text('{}')
        with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('no extra run')):
            with self.assertRaises(ValueError):await self.owner.start()
    async def tearDownAsync(self):
        await super().tearDownAsync()
        self.tmp.cleanup()

if __name__=='__main__':unittest.main()

class SavedDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_identity_duplicates_schedule_and_native_sides(self):
        import base64,httpx
        from urllib.parse import urlsplit
        from app.adapters.kalshi import KalshiAdapter
        from app.collection.prediction_discovery import NFLPolymarketAdapter
        rows=[json.loads(l)['row'] for l in Path('evidence/e6/prediction-only/real-20260915-discovery6/discovery.jsonl').read_text().splitlines()]
        class Client:
            def __init__(self,v):self.rows=[r for r in rows if r.get('source')==v and r['type']=='prediction_discovery_http']
            async def get(self,url,params=None,**kw):
                path=urlsplit(url).path
                r=next(r for r in self.rows if r['path']==path and (r['params'] or None)==(params or urlsplit(url).query or None))
                return httpx.Response(r['status'],content=base64.b64decode(r['body_b64']),request=httpx.Request('GET',url))
            async def aclose(self):pass
        k=KalshiAdapter(client=Client('kalshi'),series=('KXNFLGAME',),max_pages=2,page_size=200,max_requests=64,retries=0,pregame_only=False)
        p=NFLPolymarketAdapter(client=Client('polymarket_us'),max_pages=10,page_size=5,request_cap=64,attempts=1)
        es={'kalshi':await k.discover_events(),'polymarket_us':await p.discover_events()}
        now=datetime(2026,9,16,tzinfo=timezone.utc)
        pairs,excluded=common_events(es,now);self.assertEqual(len(pairs),32);self.assertEqual(excluded,[])
        a,b=pairs[0];ms=await k.discover_markets(a.raw.ref.event_id);ps=await p.discover_markets(b.raw.ref.event_id)
        game=native_identity(a,b,sorted(ms,key=lambda x:x.raw.ref.market_id)[0],ps[0])
        self.assertEqual(game['sides']['polymarket_us:1315440']['participant'],'Detroit Lions')
        self.assertEqual(game['sides']['kalshi:yes']['participant'],'Buffalo Bills')
        with self.assertRaises(ValueError):native_identity(a,replace(b,scheduled_start=b.scheduled_start+timedelta(hours=1)),ms[0],ps[0])
        duplicate={'kalshi':[*es['kalshi'],a],'polymarket_us':es['polymarket_us']}
        pairs,excluded=common_events(duplicate,now);self.assertEqual(len(pairs),31);self.assertTrue(any(x['reason']=='ambiguous match' for x in excluded))
        pairs,excluded=common_events(es,a.scheduled_start-timedelta(seconds=299));self.assertEqual(len(pairs),31)
