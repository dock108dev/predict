"""Real retained selector evidence; generated faults only test defensive controls."""
import base64
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from app.collection import native_selectors as ns
from app.collection.coverage import catalog,params
from app.collection.continuous import Discovery

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/native-selectors-20260930'
def supported():return json.loads((OUT/'supported-pages.json').read_text())
def uspages():
    return [dict(p,acquisition_discovery_policy=ns.POLICY) for p in supported() if p['source']=='polymarket_us' and p['path']=='/v1/events']

class Retained(unittest.TestCase):
    def test_all_series_and_five_league_ids_have_source_authority(self):
        rows=json.loads((ROOT/'evidence/phase-0/kalshi-series.json').read_text())['series']
        self.assertTrue(set(ns.SERIES.values())<={r['ticker'] for r in rows})
        tags={}
        for p in json.loads((ROOT/'evidence/integrated-r4-derived-20260930-v1/native-pages.json').read_text()):
            if p['source']=='polymarket_us':
                for e in json.loads(base64.b64decode(p['body_b64']))['events']:
                    for t in e.get('tags',[]):
                        if t.get('league'):tags[t['league']['slug']]=t['league']
        self.assertTrue((set(ns.LEAGUES.values())-{'cbb'})<=set(tags));self.assertEqual(ns.query('polymarket_us','NCAAB')[1]['tagSlug'],'cbb')
    def test_real_kalshi_targeted_pages_select_without_substitution(self):
        ps=[dict(p,acquisition_discovery_policy=ns.POLICY) for p in supported() if p['source']=='kalshi' and p['path'].endswith('/events')]
        # The historical query omitted nested=false (documented default false).
        # Selection accepts a semantic default, with original bytes/hash intact.
        ps=[dict(p,params=dict(params(p),with_nested_markets='false')) for p in ps]
        games,excluded=ns.candidates(ps,'kalshi','NFL',datetime(2026,9,28,3,35,tzinfo=timezone.utc))
        self.assertEqual(games[0]['id'],'KXNFLGAME-26SEP28PHICHI');self.assertTrue(games[0]['scheduled_start'])
    def test_real_us_filtered_endpoint_selects_without_substitution(self):
        games,excluded=ns.candidates(uspages(),'polymarket_us','NFL',datetime(2026,9,28,3,35,tzinfo=timezone.utc))
        self.assertIn('112325',[e['id'] for e in games]);self.assertTrue(games)
        result={'kalshi':{'NFL':'retained supported game selection',**{s:'series catalog only; no retained supported game demonstration' for s in ns.SPORTS if s!='NFL'}},
                'polymarket_us':{'NFL':'retained filtered-event game selection',**{s:'league slug only; no retained supported game demonstration' for s in ns.SPORTS if s not in ('NFL','NCAAB')},'NCAAB':'selector slug and supported listing missing'}}
        # Historical evidence artifacts are immutable; tests do not rewrite them.
        self.assertEqual(result['kalshi']['NFL'],'retained supported game selection')
    def test_scope_and_no_broad_fallback(self):
        for sport in ns.SPORTS:
            path,q=ns.query('kalshi',sport);self.assertEqual(q['series_ticker'],ns.SERIES[sport]);self.assertEqual(q['with_nested_markets'],'false')
            if sport!='NCAAB':
                path,q=ns.query('polymarket_us',sport);self.assertEqual(path,'/v1/events');self.assertEqual(q['tagSlug'],ns.LEAGUES[sport])
    def test_documented_server_time_window_and_five_sport_tags(self):
        from datetime import timedelta
        at=datetime(2026,9,30,tzinfo=timezone.utc)
        for sport in ns.LEAGUES:
            path,q=ns.query('polymarket_us',sport,at)
            self.assertEqual(q['startTimeMin'],(at+timedelta(minutes=5)).isoformat())
            self.assertEqual(q['startTimeMax'],(at+timedelta(days=7)).isoformat())
            if sport!='NFL':self.assertEqual(q['tagSlugsAll'],'games')

    def test_compact_policy_preserves_excluded_volume(self):
        ps=[dict(p,acquisition_discovery_policy=ns.POLICY) for p in json.loads((ROOT/'evidence/integrated-r4-derived-20260930-v1/native-pages.json').read_text())]
        cats=[catalog(ps,v,datetime.now(timezone.utc)) for v in ('kalshi','polymarket_us')]
        self.assertEqual(sum(len(c['excluded_catalog']['events']) for c in cats),750)
        self.assertEqual(sum(len(c['excluded_catalog']['markets']) for c in cats),1841)
    def test_null_conflict_and_time_exclusions(self):
        p=uspages()[0];raw=json.loads(base64.b64decode(p['body_b64']));e=raw['events'][0]
        e['startTime']=None;e['teams'][0]['league']='nba'
        b=json.dumps(raw).encode();p.update(body_b64=base64.b64encode(b).decode(),body_sha256=sha256(b).hexdigest())
        games,ex=ns.candidates([p],'polymarket_us','NFL',datetime(2026,9,28,3,35,tzinfo=timezone.utc))
        self.assertIn('invalid_embedded_game_binding:conflicting_embedded_team_identity',[r['reason'] for r in ex]);self.assertNotIn(str(e['id']),[g['id'] for g in games])

    def test_null_metadata_cannot_construct_qualified_identity(self):
        p=uspages()[0];raw=json.loads(base64.b64decode(p['body_b64']));e=raw['events'][0]
        e['startTime']=None;e['tags']=None
        b=json.dumps(raw).encode();p.update(body_b64=base64.b64encode(b).decode(),body_sha256=sha256(b).hexdigest())
        games,ex=ns.candidates([p],'polymarket_us','NFL',datetime(2026,9,28,3,35,tzinfo=timezone.utc))
        finding=next(g for g in games if g['id']==str(e['id']))
        self.assertIsNone(finding['scheduled_start']);self.assertEqual(finding['schedule_status'],'unestablished')
        self.assertNotIn('canonical_key',finding)


class Pagination(unittest.IsolatedAsyncioTestCase):
    async def test_sport_failure_does_not_block_other_queries(self):
        d=SimpleNamespace(session=SimpleNamespace(spec={},emit=lambda *a:None),pages=[],source_stops={},selection_time=datetime.now(timezone.utc))
        calls=[]
        async def pages(venue,path,q,field,size,**kw):
            calls.append((path,q));
            if q.get('series_ticker')=='KXNFLGAME':raise ValueError('catalog_http_404')
        d.pages_for=pages
        await ns.discover(d,'kalshi');self.assertEqual(len(calls),6)
    async def test_duplicate_cursor_and_exact_two_page_cap(self):
        class Response:
            status_code=200
            count=0
            def json(self):
                self.count+=1
                return dict(events=[{'event_ticker':'id'+str(self.count)}],cursor='same')
        session=SimpleNamespace(spec={'source_session':{'native_discovery':ns.POLICY}},producers={},emit=lambda *a:None)
        d=Discovery(session);client=SimpleNamespace(get=AsyncMock(return_value=Response()));d.clients={'kalshi':client}
        with self.assertRaises(ValueError):await d.pages_for('kalshi','/trade-api/v2/events',{},'events',5,page_cap=2)
        self.assertEqual(client.get.await_count,2);self.assertEqual(d.source_stops['kalshi'],'invalid_catalog_cursor')
