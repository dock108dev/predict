"""Post-attempt local regressions: original structure, loopback-only repetition."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from aiohttp import web
from app.collection.transport_session import reopen
from app.collection.continuous import Discovery
from app.dashboard.session_history import load,project_rows
from app.dashboard.session_projection import identity
from app.reference.aggregate import bind
from tests.test_acquisition_r3 import Fixture

ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/'evidence/integrated-source-r3-attempt-986223b2-b5d3-474a-b501-eedf8cd44eba/ce5feb44-9bbe-4c52-91d6-b2fe52f87f8a'
def rows():return reopen(next(LIVE.glob('*.jsonl')))['rows']

class Retained(unittest.TestCase):
    def test_null_schedule_and_explicit_unknown_season(self):
        for event in (dict(id='unresolved',scheduled_start=None),dict(id='unresolved',scheduled_start=None,season=None)):
            result=identity(event,{})
            self.assertIsNone(result['scheduled_start'])
            self.assertIn(result['season'],('',None))
            self.assertEqual(result['event'],['unresolved','unresolved'])

    def test_original_catalog_projects_without_championship_admission(self):
        session=SimpleNamespace(spec=json.loads((LIVE/'run-spec.json').read_text()),producers={},product_session=True)
        discovery=Discovery(session)
        discovery.pages=[r for r in rows() if r['type']=='prediction_discovery_http']
        cats,markets=discovery.project()
        self.assertEqual(len(cats['polymarket_us']['events']),2)
        self.assertEqual(len(cats['polymarket_us']['markets']),21)
        self.assertFalse(cats['polymarket_us']['selection']['ids'])
        self.assertTrue(all(r['exclusion'] for r in cats['polymarket_us']['markets']))
        self.assertEqual(cats['polymarket_us']['event_discovery'],'failed')

    def test_all_observations_bind_and_original_incomplete_session_is_exact(self):
        counts={}
        for row in rows():
            if row['type']=='aggregate_snapshot':
                rebound=bind([r['original'] for r in row['records']]);counts[row['sport']]=len(rebound)
                from app.normalization.college_registry import aggregate_registry
                expected=[dict(r,registry_sha256=aggregate_registry().fingerprint) for r in row['records']]
                self.assertEqual(rebound,expected)
                self.assertFalse(any(r['reasons'] for r in rebound))
                self.assertTrue(all(r['original']['fees'] is None and r['original']['settlement'] is None for r in rebound))
        self.assertEqual(counts,dict(NFL=54,NCAAF=46,NBA=18,MLB=50,NHL=78))
        saved=load(LIVE);projected=project_rows(rows(),saved['durable_cursor'])
        self.assertEqual(saved,dict(projected,state='incomplete'))
        self.assertEqual(len(saved['aggregate_coverage']),63)

class CapturedFixture(Fixture):
    async def boot(self,path):
        result=await super().boot(path);self.native_calls=[]
        return result
    async def rest(self,req):
        if req.path.startswith('/v4/'):return await super().rest(req)
        self.native_calls.append((req.path,dict(req.query)))
        candidates=[r for r in rows() if r['type']=='prediction_discovery_http' and r['path']==req.path]
        if req.path=='/v1/events':
            target=next(r for r in candidates if int(r['params']['offset'])==int(req.query['offset']))
        else:target=candidates[0]
        raw=base64.b64decode(target['body_b64'])
        if not target['complete']:raw+=b'SIMULATED byte beyond original truncated prefix'
        return web.Response(body=raw,status=target['status'])

class Runtime(unittest.IsolatedAsyncioTestCase):
    async def test_real_catalog_structure_source_stops_keep_aggregate_alive(self):
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No real credentials')):
            f=CapturedFixture();owner=await f.boot(tmp)
            try:
                await f.start()
                await f.wait(lambda:owner.session.aggregate.health=='completed')
                await f.wait(lambda:owner.session.discovery.completed)
                self.assertFalse(owner.session.stop_event.is_set())
                self.assertEqual(len(f.odds_calls),37)
                self.assertEqual(set(owner.session.discovery.source_stops),{'kalshi','polymarket_us'})
                self.assertEqual(len(f.native_calls),5)
                self.assertEqual(len(owner.session.discovery.inventory['polymarket_us']['events']),2)
                await owner.session.discovery.discover(force=True)
                self.assertEqual(len(f.native_calls),5)
                await f.stop_route();self.assertTrue(owner.session.cleanup_complete)
                saved=load(owner.session.output);journal=reopen(owner.session.journal.path)['rows']
                self.assertEqual(saved,project_rows(journal,saved['durable_cursor']))
                self.assertEqual(len(saved['aggregate_coverage']),63)
            finally:await f.close()

class ListingEvidence(unittest.TestCase):
    def test_complete_associations_only_no_economics_or_truncated_prefix(self):
        from app.collection.listing_evidence import retained_us_futures
        pages=[r for r in rows() if r['type']=='prediction_discovery_http']
        result=retained_us_futures(pages)
        self.assertEqual(len(result),21)
        self.assertEqual({r['event_id'] for r in result},{'6435','6436'})
        self.assertTrue(all(r['association']=='observed_native_listing' for r in result))
        self.assertTrue(all(r['settlement_rules'] is None and r['fees'] is None and not r['quotes_admitted'] for r in result))
        self.assertFalse(retained_us_futures([r for r in pages if not r['complete']]))
        p=deepcopy(next(r for r in pages if r['source']=='polymarket_us' and r['complete']))
        p['body_sha256']='incorrect'
        with self.assertRaises(ValueError):retained_us_futures([p])
