import asyncio
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from app.collection.novig_graphql import GraphQLVenue,catalog,QUERY,ENDPOINT
from app.collection.native_rest_replay import NativeRestVerifier
from app.collection.native_product import listing_association,validate_sources
from app.novig_example import MARKET,response
from app.adapters.novig import parse_market
from tests.test_b3_native import configuration

BODY={'data':{'event':[{'id':'synthetic-e','description':'Synthetic fixture','game':{'scheduled_start':'2027-01-01T20:00:00Z'},'markets':[{'description':'Synthetic winner','outcomes':[{'description':'Home','last':0.4,'available':0.5}]}]}]}}

class Bridge(unittest.IsolatedAsyncioTestCase):
    async def test_no_secrets_exact_catalog_no_executable_quotes(self):
        rows=[];requests=[];spec=configuration();spec['native_sources']['novig']=dict(state='enabled',transport='graphql',environment='public')
        validate_sources(spec)
        async def handle(r):
            requests.append(r);return httpx.Response(200,json=BODY)
        session=SimpleNamespace(spec=spec,health={},intake_closed=False,stop_event=asyncio.Event(),emit=lambda v,r:rows.append(dict(r,source=v)),graphql_fixture_transport=httpx.MockTransport(handle))
        p=GraphQLVenue(session,'novig',spec['native_sources']['novig'])
        with patch('app.collection.native_product.load_native_secret',side_effect=AssertionError('no secret lookup')):
            c,markets=await p.native_discover()
            self.assertEqual(c['state'],'display_only');self.assertEqual(markets,{})
            self.assertFalse(c['selection']['ids']);self.assertEqual(c['markets'][0]['period'],'unknown')
            self.assertEqual(c['markets'][0]['display_prices'][0]['available'],.5)
            self.assertEqual(str(requests[0].url),ENDPOINT);self.assertNotIn('authorization',requests[0].headers)
            self.assertEqual(json.loads(requests[0].content),{'query':QUERY})
            v=NativeRestVerifier()
            for row in rows:v.feed(row)
            inventory=dict(type='coverage_inventory',inventory={'novig':c})
            v.feed(inventory);bad=deepcopy(inventory);bad['inventory']['novig']['markets'][0]['display_prices'][0]['available']=.9
            with self.assertRaises(ValueError):v.feed(bad)
            await p.native_discover();await p.native_discover();self.assertEqual(len(requests),2)
            self.assertEqual(p.state,'unavailable');await p.aclose()
    async def test_partial_errors_and_byte_cap_fail_without_retry(self):
        for payload in ({'errors':[{'message':'no'}],'data':BODY['data']}, {'padding':'x'*1_000_001}):
            calls=[]
            async def handle(r):calls.append(r);return httpx.Response(200,json=payload)
            session=SimpleNamespace(spec=configuration(),health={},intake_closed=False,stop_event=asyncio.Event(),emit=lambda *x:None,graphql_fixture_transport=httpx.MockTransport(handle))
            p=GraphQLVenue(session,'novig',dict(state='enabled',transport='graphql',environment='public'))
            self.assertEqual((await p.native_discover())[0]['state'],'unavailable')
            await p.native_discover();self.assertEqual(len(calls),1)
    def test_missing_period_never_promoted(self):
        m=parse_market(response(MARKET),MARKET,'synthetic-event')
        a=listing_association(m);self.assertEqual(a['period'],'unknown');self.assertIsNone(a['settlement_rules'])
        self.assertEqual(a['market_id'],m.raw.ref.market_id)
        self.assertEqual(a['sha256'],sha256(m.raw.json_text.encode()).hexdigest())

class SegmentedReplay(unittest.TestCase):
    def test_retained_native_across_segments_corruption_and_incomplete(self):
        from app.collection.segmented import SegmentedJournal,SegmentedReader,POLICY
        from app.collection.transport_session import reopen
        from app.dashboard.coverage_owner import replay_segmented
        from app.dashboard.session_history import project_rows
        import shutil
        path=Path('evidence/b3-native-integration-20260920/browser/sessions/26d86fba-9261-4abf-8519-67131d2ef11c/26d86fba-9261-4abf-8519-67131d2ef11c.jsonl')
        before=sha256(path.read_bytes()).hexdigest();rows=reopen(path)['rows']
        with tempfile.TemporaryDirectory() as t,patch.dict(POLICY,segment_logical=64):
            root=Path(t);j=SegmentedJournal(root/'history',label='offline replay of retained synthetic B3; not new collection')
            for row in rows:j.save(row)
            j.finish(cleanup_complete=True)
            self.assertGreater(len(j.segments),1)
            result=replay_segmented(root/'history')
            self.assertEqual(result['native_rest']['exact_native_rest_books']['novig'],3)
            self.assertEqual(project_rows(iter(rows)),project_rows(SegmentedReader(root/'history').rows()))
            shutil.copytree(root/'history',root/'corrupt')
            p=next((root/'corrupt').glob('segment-*.jsonl'));p.write_bytes(p.read_bytes().replace(b'"sha256":',b'"sha255":',1))
            with self.assertRaises((ValueError,KeyError)):replay_segmented(root/'corrupt')
            incomplete=SegmentedJournal(root/'incomplete',label='deliberately interrupted offline fixture')
            for row in rows[:-1]:incomplete.save(row)
            incomplete.finish(cleanup_complete=False)
            with self.assertRaises(ValueError):replay_segmented(root/'incomplete')
            self.assertTrue(list(SegmentedReader(root/'incomplete').rows(allow_interrupted=True)))
            # Even a structurally valid journal must reject altered purchase quantities.
            altered=deepcopy(rows)
            row=next(r for r in altered if r['type']=='prediction_book' and r['source']=='novig')
            row['packets'][1]['normalized']['quotes'][0]['ask_size']='999'
            v=NativeRestVerifier()
            with self.assertRaises(ValueError):
                for row in altered:v.feed(row)
        self.assertEqual(sha256(path.read_bytes()).hexdigest(),before)
