"""Source ledger ordinary routes are read-only and preserve exact saved cutoffs."""
import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from app.collection.transport_session import ObservationJournal
from app.dashboard.multi_game_server import create_app
from app.dashboard.coverage_owner import delivery_limits
from app.dashboard.session_history import load
from app.collection.native_payload import TRANSPORT_CONTRACT
from tests.test_session_projection import fixture


class Routes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        rows=fixture()
        self.sid=rows[0]['session_id']
        self.folder=root/self.sid
        self.folder.mkdir()
        journal=ObservationJournal(self.folder/(self.sid+'.jsonl'))
        for row in rows:journal.save(row)
        journal.close()
        self.snapshot=load(self.folder)
        async def close():pass
        owner=SimpleNamespace(output=root,session=None,start_controls=frozenset({'duration'}),close=close,
            status=lambda:dict(active=False),saved=lambda:[],active=lambda:False,
            history_paths=lambda:{self.sid:self.folder})
        self.client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=root/'watches.json')))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_static_and_saved_exact_download_no_collection(self):
        from app.collection.source_bindings import load_ledger,ledger_for_snapshot
        with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credential access forbidden')):
            response=await self.client.get('/api/source-bindings?download=true')
            self.assertEqual(response.status,200)
            self.assertEqual(await response.json(),load_ledger())
            self.assertIn('predict-source-bindings-63.json',response.headers['Content-Disposition'])
            query='capture='+self.sid+'&cutoff='+self.snapshot['durable_cursor']
            ordinary=await self.client.get('/api/source-bindings?'+query)
            self.assertEqual(ordinary.status,200)
            selected=await ordinary.json()
            self.assertEqual(selected,ledger_for_snapshot(self.snapshot))
            download=await self.client.get('/api/source-bindings?'+query+'&download=true')
            self.assertEqual(selected,await download.json())
            self.assertEqual(selected['required_cells'],63)
            self.assertEqual(selected['source_cell_count'],252)
            self.assertEqual(self.snapshot,load(self.folder))

    async def test_reject_unbound_cutoff_and_unknown_or_duplicate_controls(self):
        for query in ('cutoff=x','capture=missing','capture='+self.sid+'&cutoff=wrong',
                      'download=yes','download=true&download=false','start=true'):
            with self.subTest(query=query):
                response=await self.client.get('/api/source-bindings?'+query)
                self.assertEqual(response.status,422,await response.text())


class ResourceDescription(unittest.TestCase):
    def test_exact_selected_contract_and_legacy_limits(self):
        root=Path(__file__).resolve().parents[1]
        spec=json.loads((root/'evidence/native-nyi-tor-20260930-v3/run-spec.json').read_text())
        self.assertEqual(delivery_limits(spec),{})
        spec['native_transport']=dict(TRANSPORT_CONTRACT)
        values=delivery_limits(spec)
        self.assertEqual(values['native_transport'],TRANSPORT_CONTRACT)
        self.assertEqual(values['per_venue_body_bytes'],spec['prediction']['session_bytes'])
        self.assertEqual(values['native_http_request_caps']['polymarket_us'],1)
        self.assertEqual(values['native_catalog_retained_bytes'],2*1024*1024)
        self.assertEqual(values['sampled_rss_stop_bytes'],256*1024*1024)
        spec['native_transport']['response_entity_bytes']+=1
        with self.assertRaises(ValueError):delivery_limits(spec)


class NativeScopes(unittest.TestCase):
    def test_all_native_cells_selected_independently_of_aggregate_keys(self):
        from app.collection.source_bindings import required_cells
        from app.collection.source_session import validate,filter_native_catalog
        from tests.test_source_session import settings
        cells=required_cells()
        config=settings(native_scopes={source:[{k:v for k,v in c.items() if k!='cell_id'} for c in cells]
                                       for source in ('kalshi','polymarket_us')},
                        correspondence_policy='source-correspondence-1')
        validate(config)
        compact=settings(native_scopes={'kalshi':'required-63-v1','polymarket_us':'required-63-v1'})
        self.assertLess(len(json.dumps(compact).encode()),4096)
        self.assertEqual(len(validate(compact)['native_scopes']['kalshi']),63)
        self.assertEqual(compact['native_scopes']['kalshi'],'required-63-v1')
        # Aggregate requests keep their original documented keys.
        self.assertEqual(config['scopes'][0]['markets'],['h2h','spreads','totals'])
        for source in ('kalshi','polymarket_us'):
            catalog=dict(events=[],markets=[])
            for index,cell in enumerate(cells):
                eid='event-'+str(index)
                catalog['events'].append(dict(id=eid,canonical_key=['canonical',eid],
                    identity='resolved',exclusion=None,competition=cell['sport']))
                catalog['markets'].append(dict(id='market-'+str(index),event_id=eid,
                    market_type=cell['family'],period=cell['period'],category=cell['category'],exclusion=None))
            filter_native_catalog(catalog,source,config)
            self.assertEqual(len(catalog['markets']),63)
            self.assertTrue(all(m['exclusion'] is None for m in catalog['markets']))
        # A source absent from explicit scopes receives no selection authority.
        catalog=dict(events=[dict(id='e',identity='resolved',canonical_key=['e'],competition='MLB')],
                     markets=[dict(id='m',event_id='e',market_type='moneyline',period='regulation_9',exclusion=None)])
        config['native_scopes'].pop('polymarket_us')
        filter_native_catalog(catalog,'polymarket_us',config)
        self.assertIn('native source cell',catalog['markets'][0]['exclusion'])

    def test_unknown_and_duplicate_cells_cannot_extend_authority(self):
        from app.collection.source_session import validate
        from tests.test_source_session import settings
        cell=dict(sport='MLB',period='regulation_9',family='moneyline',category=None)
        good=settings(native_scopes={'kalshi':[cell]})
        self.assertEqual(validate(good),good)
        for change in (dict(period='first_7'),dict(sport='NFL',period='period_1'),
                       dict(category='league_champion'),dict(family='futures'),dict(category=[])):
            bad=deepcopy(good);bad['native_scopes']['kalshi'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):validate(bad)
        bad=deepcopy(good);bad['native_scopes']['kalshi'].append(cell)
        with self.assertRaisesRegex(ValueError,'Duplicate'):validate(bad)
        with self.assertRaisesRegex(ValueError,'correspondence'):validate(settings(correspondence_policy='unversioned'))


if __name__=='__main__':unittest.main()
