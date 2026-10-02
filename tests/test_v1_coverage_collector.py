"""OFFLINE synthetic responses, ordinary routes, no provider or credential access."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from tests.test_acquisition_r2 import Fixture as Previous
from app.reference.odds_bindings import CHAMPIONSHIPS,BOOKS
from app.reference.outrights import AWARDS,normalize
from app.normalization.futures import SEASONS
from app.reference.aggregate import bind,augment
from app.collection.acquisition_policy import request_cost,totals
from app.collection.source_session import verify_rows,validate
from app.collection.transport_session import reopen
from app.dashboard.session_history import load,project_rows
from app.collection.v1_coverage import PAIRED

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'scripts/v1_coverage_package'
def configuration():return json.loads((PACKAGE/'run-spec.json').read_text())

class Fixture(Previous):
    def __init__(self,fault=None):super().__init__(fault);self.native_calls=[];self.award_rounds={};self.links=[]
    async def boot(self,path):
        o=await super().boot(path)
        o.spec_factory=lambda:dict(configuration(),mode='mock')
        return o
    def award_body(self,sport):
        home,away=self.names[sport]
        return [dict(id='OFFLINE-award-'+sport,sport_key=CHAMPIONSHIPS[sport],season=SEASONS[sport],award=AWARDS[sport],
          commence_time=self.schedule,bookmakers=[dict(key=b,markets=[dict(key='outrights',last_update=datetime.now(timezone.utc).isoformat(),
          outcomes=[dict(name=n,price='2.2' if b=='novig' else '1.9') for n in (home,away)])]) for b in BOOKS])]
    async def rest(self,req):
        if req.path.startswith('/v4/'):
            sport=next((s for s,k in CHAMPIONSHIPS.items() if '/'+k+'/' in req.path),None)
            if sport:
                self.odds_calls.append((req.path,dict(req.query)));self.used+=1;self.award_rounds[sport]=self.award_rounds.get(sport,0)+1
                headers={'x-requests-used':str(self.used),'x-requests-remaining':str(self.base_quota-self.used),'x-requests-last':'1'}
                if self.fault=='award_charge':headers['x-requests-last']='2'
                return web.json_response(self.award_body(sport),headers=headers)
            return await super().rest(req)
        self.native_calls.append((req.path,dict(req.query)))
        if req.path=='/trade-api/v2/milestones':
            # Unobserved fixture links are visibly labeled. Duplicated links are shared.
            eid='OFFLINE-unknown-linked-event';self.links.append(eid)
            return web.json_response(dict(milestones=[dict(id='OFFLINE-milestone',category='Sports',type='football_game',start_date=self.schedule,related_event_tickers=[eid,eid])],cursor='OFFLINE-capped-cursor'))
        if req.path=='/trade-api/v2/events/OFFLINE-unknown-linked-event':
            return web.json_response(dict(event=dict(event_ticker='OFFLINE-unknown-linked-event',series_ticker='OFFLINE-unknown-series',title='OFFLINE unknown predicate'),markets=[]))
        if req.path=='/trade-api/v2/series/OFFLINE-unknown-series':return web.json_response(dict(series=dict(ticker='OFFLINE-unknown-series',title='OFFLINE unknown offering')))
        if getattr(self,'supported_native',False) and req.path=='/trade-api/v2/markets' and req.query.get('event_ticker')=='k':return await Previous.rest(self,req)
        if getattr(self,'supported_native',False) and req.path=='/trade-api/v2/events' and req.query.get('series_ticker')=='KXNFLGAME':return await Previous.rest(self,req)
        if req.path=='/trade-api/v2/markets':return web.json_response(dict(markets=[],cursor=''))
        if req.path=='/trade-api/v2/events':return web.json_response(dict(events=[],cursor=''))
        if req.path=='/v1/events':
            if self.fault=='us_cap':return web.Response(body=b'{'+b' '*2100000)
            return web.json_response(dict(events=[]))
        return await super().rest(req)
    async def start(self,duration=20,fast=True):
        cfg=configuration()['source_session']
        if fast:cfg['refresh_seconds']=1
        if getattr(self,'supported_native',False):cfg['native_scopes']['kalshi']=[dict(sport='NFL',period='full_game',family='moneyline',category=None)]
        r=await self.client.post('/api/start',json=dict(duration=duration,source_settings=cfg),headers=self.origin)
        assert r.status==200,await r.text()
        saved=self.owner.session.journal.save
        def observed(row):
            saved(row);self.books+=row['type']=='prediction_book';self.changed.set()
        self.owner.session.journal.save=observed

class Contracts(unittest.TestCase):
    def test_exact_baseline_cost_matrix_and_unknown_keys(self):
        observed=json.loads((ROOT/'evidence/v1-coverage-comparison-20261001-v1/coverage-63.json').read_text())
        self.assertEqual(PAIRED,{c['cell_id'] for c in observed['cells'] if c['comparable_sources']})
        cfg=validate(configuration()['source_session']);self.assertEqual(totals(cfg)['requests'],31);self.assertEqual(totals(cfg)['credits'],102)
        for s in cfg['scopes']:
            self.assertEqual(request_cost(cfg,dict(path='/v4/sports/'+CHAMPIONSHIPS[s['sport']]+'/odds',params=dict(bookmakers=','.join(BOOKS),markets='outrights',oddsFormat='decimal',dateFormat='iso'))),1)
        with self.assertRaises(ValueError):request_cost(cfg,dict(path='/v4/sports/guessed_conference/odds',params={}))
    def test_award_field_optional_but_season_award_entrant_exact(self):
        f=Fixture();body=f.award_body('NFL');at=datetime.now(timezone.utc).isoformat()
        records=bind(normalize(json.dumps(body).encode(),'NFL',at));self.assertFalse(any(r['reasons'] for r in records),records)
        self.assertEqual({r['role'] for r in records},{'aggregated_venue_observation','bookmaker_reference'})
        for field,value in [('season',None),('award','AFC Championship')]:
            changed=deepcopy(body);changed[0][field]=value
            self.assertTrue(all(r['reasons'] for r in bind(normalize(json.dumps(changed).encode(),'NFL',at))))
        changed=deepcopy(body);changed[0]['bookmakers'][0]['markets'][0]['outcomes'][0]['name']='OFFLINE Unknown Entrant'
        self.assertTrue(bind(normalize(json.dumps(changed).encode(),'NFL',at))[0]['reasons'])

class Runtime(unittest.IsolatedAsyncioTestCase):
    async def test_complete_two_cycles_replay_details_history_isolation(self):
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
            f=Fixture('us_cap');o=await f.boot(tmp)
            try:
                await f.start();await f.wait(lambda:o.session.aggregate.health=='completed')
                self.assertEqual(len(f.odds_calls),31);self.assertEqual(o.session.aggregate.budget.credits,102)
                self.assertEqual(f.used-20,102);self.assertEqual(f.rounds,{s:2 for s in CHAMPIONSHIPS});self.assertEqual(f.award_rounds,{s:2 for s in CHAMPIONSHIPS})
                # one shared game discovery per sport; second prices use those IDs
                self.assertEqual(sum(p.endswith('/events') for p,q in f.odds_calls),6)
                await f.wait(lambda:'polymarket_us' in o.session.discovery.source_stops)
                feed=await (await f.client.get('/api/dashboard?view=feed')).json()
                award=next(r for r in feed['comparisons'] if r['identity']['family']=='futures');q=urlencode(dict(session=award['session'],hash=award['hash'],cutoff=award['cutoff']))
                detail=await (await f.client.get('/api/calculate?'+q)).json()
                self.assertIsNone(award['net']);self.assertIsNone(award['ev']);self.assertTrue(all(l['visible_size'] is None for l in award['legs']))
                await f.stop_route();self.assertIsNone(o.error,o.error);self.assertTrue(o.session.cleanup_complete)
                rows=reopen(o.session.journal.path)['rows'];self.assertEqual(verify_rows(rows)['snapshots'],24)
                saved=load(o.session.output);self.assertEqual(saved,project_rows(rows,saved['durable_cursor']))
                self.assertEqual(detail,await (await f.client.get('/api/calculate?'+q)).json())
                sid=o.session.sid
                self.assertEqual(await (await f.client.get('/api/opportunity-history?capture='+sid)).json(),await (await f.client.get('/api/opportunity-history?capture='+sid+'&download=true')).json())
                self.assertEqual(sum(p.endswith('/events/OFFLINE-unknown-linked-event') for p,q in f.native_calls),1)
                self.assertEqual(sum(p.endswith('/series/OFFLINE-unknown-series') for p,q in f.native_calls),1)
                calls=len(f.odds_calls);await asyncio.sleep(.02);self.assertEqual(calls,len(f.odds_calls))
            finally:await f.close()
    async def test_contradictory_award_quota_stops_paid_source(self):
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
            f=Fixture('award_charge');o=await f.boot(tmp)
            try:
                await f.start();await f.wait(lambda:bool(o.session.aggregate.budget.reason))
                self.assertEqual(len(f.odds_calls),2);self.assertEqual(o.session.aggregate.budget.credits,2)
                await f.stop_route();self.assertTrue(o.session.cleanup_complete)
            finally:await f.close()

class Deadline(unittest.IsolatedAsyncioTestCase):
    async def test_automatic_deadline_and_no_post_stop_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
            f=Fixture();o=await f.boot(tmp)
            try:
                await f.start(duration=3);await o.finalizer
                self.assertTrue(o.session.stop_event.is_set());self.assertTrue(o.session.cleanup_complete);self.assertFalse(o.active())
                calls=len(f.odds_calls);await asyncio.sleep(.05);self.assertEqual(calls,len(f.odds_calls))
            finally:await f.close()


class NativeBookPath(unittest.IsolatedAsyncioTestCase):
    async def test_selected_scoped_event_enters_actual_stream_and_reopens(self):
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
            f=Fixture('us_cap');f.supported_native=True;o=await f.boot(tmp)
            try:
                await f.start(duration=60)
                try:
                    async with asyncio.timeout(8):
                        while not f.active():await asyncio.sleep(.05)
                except TimeoutError:
                    raise AssertionError(json.dumps(o.session.discovery.project()[0]['kalshi'],default=str)[:10000])
                await f.images();await f.send(f.active()[0])
                await f.stop_route();self.assertIsNone(o.error,o.error)
                rows=reopen(o.session.journal.path)['rows']
                self.assertGreaterEqual(sum(r['type']=='prediction_book' and r['source']=='kalshi' for r in rows),2)
                saved=load(o.session.output);self.assertEqual(saved,project_rows(rows,saved['durable_cursor']));self.assertTrue(o.session.cleanup_complete)
            finally:await f.close()
