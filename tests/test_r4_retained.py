"""Captured r4 structure, versioned compact metadata; isolated transports only."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp import web
from app.collection.native_payload import POLICY
from app.collection.transport_session import reopen
from app.dashboard.session_history import load,project_rows
from app.collection.catalog_metadata import resolve
from tests.test_native_redesign import Fixture as Synthetic,configuration
from tests.test_coverage import ke,pe

ROOT=Path(__file__).resolve().parents[1]
DERIVED=ROOT/'evidence/integrated-r4-derived-20260930-v1'
def pages():return json.loads((DERIVED/'native-pages.json').read_text())

class Fixture(Synthetic):
    def __init__(self,supported=False):super().__init__();self.supported=supported;self.original_pages=pages()
    async def rest(self,req):
        if req.path.startswith('/v4/') or req.path.endswith('/markets'):return await super().rest(req)
        q=dict(req.query)
        candidates=[r for r in self.original_pages if r['path']==req.path]
        row=next(r for r in candidates if ({k:str(v) for k,v in r['params'].items()}==q if isinstance(r['params'],dict) else not q))
        raw=base64.b64decode(row['body_b64'])
        if self.supported and ((req.path=='/v1/events' and q['offset']=='145') or (req.path=='/trade-api/v2/events' and q['cursor']=='')):
            d=json.loads(raw)
            if req.path=='/v1/events' and q['offset']=='145':
                e=pe('p');e.update(gameId=1,startTime=self.schedule,markets=[self.us_market('p0')]);d['events'][-1]=e
            if req.path=='/trade-api/v2/events' and q['cursor']=='':
                e,m=ke('k');m['start_date']=self.schedule;d['events'][-1]=e;d.setdefault('milestones',[]).append(m)
            raw=json.dumps(d,separators=(',',':')).encode() # Clearly labeled substitution only in offline supported variant.
        return web.Response(body=raw,status=row['status'])

class Retained(unittest.TestCase):
    def test_source_refs_resolve_and_no_new_identities(self):
        cats=json.loads((DERIVED/'compact-inventory.json').read_text());ps=pages()
        from app.collection.catalog_metadata import references
        count=0
        for venue,c in cats.items():
            for ref in references(c):
                self.assertIsInstance(resolve(ps,ref),dict);count+=1
            self.assertFalse(c['events']);self.assertFalse(c['markets'])
        self.assertEqual(count,2591)
    def test_all_aggregate_records_rebind_exactly(self):
        from app.reference.aggregate import bind
        rs=json.loads((DERIVED/'aggregate-records.json').read_text());count=0
        for r in rs:
            if r['type']=='aggregate_snapshot':
                rebound=bind([v['original'] for v in r['records']])
                from app.normalization.college_registry import aggregate_registry
                expected=[dict(v,registry_sha256=aggregate_registry().fingerprint) for v in r['records']]
                self.assertEqual(rebound,expected);count+=len(rebound)
        self.assertEqual(count,248)

class Runtime(unittest.IsolatedAsyncioTestCase):
    async def test_actual_catalog_stays_bounded_with_supported_books_beside_it(self):
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
            f=Fixture(supported=True);o=await f.boot(tmp)
            try:
                await f.start(duration=60);await f.native_images()
                for c in list(f.active()):await f.send(c)
                await f.wait(lambda:o.session.aggregate.health=='completed')
                self.assertFalse(o.session.stop_event.is_set(),o.session.reason)
                self.assertFalse(o.session.discovery.source_stops)
                self.assertEqual({k[0] for k in o.session.projection.books},{'kalshi','polymarket_us'})
                await f.stop_route();self.assertIsNone(o.error)
                saved=load(o.session.output);rs=reopen(o.session.journal.path)['rows']
                self.assertEqual(saved,project_rows(rs,saved['durable_cursor']))
                self.assertLess(o.session.resources()['peak_rss_bytes'],256*1024*1024)
                self.assertTrue(o.session.cleanup_complete)
            finally:await f.close()
