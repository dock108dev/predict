"""Pure scope controls; no provider transport, credentials or activation."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.collection.continuous import REST
from app.collection.native_payload import validate_transport
from app.collection.prediction_producer import PredictionBudget
from app.collection.odds_http import BudgetStop
from app.collection.run_spec import preflight, time_value

ROOT=Path(__file__).resolve().parents[1]


class DiagnosticRuntimeScope(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory()
        loader=importlib.util.spec_from_file_location('diagnostic_runtime_scope_builder',ROOT/'scripts/us_metadata_package/build.py')
        module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
        cls.clock=datetime(2026,9,30,22,0,tzinfo=timezone.utc)
        path=Path(cls.folder.name)/'OFFLINE-unused-package'
        module.build(path,offline=True,now=cls.clock)
        cls.original=json.loads((path/'run-spec.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def check(self,spec):
        with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials prohibited')):
            return preflight(spec,now=self.clock)

    def test_exact_public_metadata_spec_and_independent_full_window(self):
        self.assertTrue(self.check(self.original)['valid'])
        window=self.original['us_metadata_diagnostic']['validity_window']
        self.assertEqual(time_value(window['start']),time_value(self.original['start_after']))
        self.assertEqual((time_value(window['expires'])-time_value(self.original['start_before'])).total_seconds(),32)
        self.assertEqual(self.original['prediction']['connections'],0)
        self.assertEqual(self.original['prediction']['messages'],0)
        self.assertNotIn('kalshi',self.original['sources'])

    def test_every_scope_mutation_is_refused(self):
        mutations={
            'book connection':lambda s:s['prediction'].update(connections=1),
            'book message':lambda s:s['prediction'].update(messages=1),
            'frame bytes':lambda s:s['prediction'].update(frame_bytes=262144),
            'retry allowance':lambda s:s['prediction'].update(discovery_requests=2),
            'extra duration':lambda s:s.update(duration=16),
            'changed cadence':lambda s:s.update(discovery_cadence=1),
            'missing explicit transport':lambda s:s.pop('native_transport'),
            'budget increase':lambda s:s['native_transport'].update(response_entity_bytes=4194304),
            'Kalshi enabled':lambda s:s['native_sources']['kalshi'].update(state='enabled'),
            'credentials reference':lambda s:s['sources']['polymarket_us'].update(credential_reference='keychain:forbidden'),
            'event substitution':lambda s:s['us_metadata_diagnostic']['target'].update(event_id='127805'),
            'query filter':lambda s:s['us_metadata_diagnostic']['request'].update(params={'marketTypes':['moneyline']}),
            'route change':lambda s:s['us_metadata_diagnostic']['request'].update(path='/v1/events'),
            'host change':lambda s:s['us_metadata_diagnostic']['request'].update(host='https://polymarket.com'),
            'baseline alteration':lambda s:s['us_metadata_diagnostic']['historical_baseline']['event'].update(title='changed'),
            'different start window':lambda s:s.update(start_after='2026-09-30T22:00:01+00:00'),
            'missing cleanup margin':lambda s:s.update(start_before=s['us_metadata_diagnostic']['validity_window']['expires']),
            'paired review':lambda s:s.update(native_review_records=[]),
            'aggregate':lambda s:s.update(source_session={}),
            'reference':lambda s:s.update(reference_enabled=True),
            'economics':lambda s:s['assessment_revisions'].update(fees='unqualified'),
        }
        for name,mutate in mutations.items():
            with self.subTest(name=name):
                spec=deepcopy(self.original);mutate(spec)
                self.assertFalse(self.check(spec)['valid'])

    def test_latest_start_and_legacy_transport_boundary(self):
        self.assertFalse(preflight(self.original,now=time_value(self.original['us_metadata_diagnostic']['validity_window']['expires']))['valid'])
        self.assertIsNone(validate_transport({}))
        legacy=json.loads((ROOT/'evidence/native-nyi-tor-20260930-v3/run-spec.json').read_text())
        self.assertIsNone(validate_transport(legacy))

    async def test_invalid_dispatch_is_refused_before_http(self):
        spec=deepcopy(self.original);spec['mode']='mock'
        session=SimpleNamespace(spec=spec)
        client=REST('http://127.0.0.1:1',spec['prediction'],lambda row:None,5,PredictionBudget(spec['prediction']))
        client.session=session;client.source_venue='polymarket_us'
        cases=[('http://127.0.0.1:1/v1/events',{}),('http://127.0.0.1:1/v1/events/127805',{}),
               ('http://127.0.0.1:1/v1/events/127804',{'filter':'invented'})]
        with patch('app.collection.prediction_producer.MockREST.get',side_effect=AssertionError('HTTP must not dispatch')):
            for url,params in cases:
                with self.subTest(url=url,params=params):
                    with self.assertRaisesRegex(BudgetStop,'us_metadata_request_outside_sealed_scope'):
                        await client.get(url,params)
            client.source_venue='kalshi'
            with self.assertRaisesRegex(BudgetStop,'us_metadata_request_outside_sealed_scope'):
                await client.get('http://127.0.0.1:1/v1/events/127804',{})
        self.assertEqual(client.budget.requests,0)


if __name__=='__main__':unittest.main()
