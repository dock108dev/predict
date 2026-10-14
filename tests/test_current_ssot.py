"""Current policy ownership and explicit configuration; temporary/mocked state only."""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import json
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from multidict import MultiDict
from aiohttp import web

from app.collection import current_aggregate, current_policy, current_quota, current_schedule
from app.collection.current_aggregate_policy import POLICY
from tests.test_current_odds_transport import Client, Response
from app.collection.current_service import CurrentService


class PolicyOwnership(unittest.TestCase):
    def test_consumers_share_immutable_policy_and_attempt_declaration(self):
        for consumer in (current_aggregate.POLICY, current_policy.AGGREGATE_POLICY,
                         current_quota.POLICY, current_schedule.POLICY):
            self.assertIs(consumer, POLICY)
        with self.assertRaises(FrozenInstanceError):
            POLICY.interval_seconds = 1
        config = dict(current_policy.DEFAULT,aggregate_sports=['NFL','MLB'])
        with tempfile.TemporaryDirectory() as temp:
            attempt = current_policy.consume(temp, 'controlled', config, 'synthetic-candidate')
            retained = json.loads((Path(temp)/'attempt-controlled.json').read_text())
        from app.collection.current_policy import aggregate_scope
        self.assertEqual(attempt['aggregate_policy'], POLICY.record(aggregate_scope(config)))
        self.assertEqual(retained, attempt)
        attempt['aggregate_policy']['scope'].append('MLB')
        attempt['aggregate_policy']['bookmakers'].clear()
        self.assertEqual(config['sports'], ['NFL'])
        self.assertEqual(POLICY.bookmakers, ('novig', 'prophetx', 'pinnacle'))

    def test_incomplete_config_never_enables_acquisition_implicitly(self):
        for field in ('enabled', 'aggregate_enabled'):
            config = dict(current_policy.DEFAULT)
            config.pop(field)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Exact native'):
                current_policy.validate(config)
            with self.assertRaisesRegex(ValueError, 'Exact native'):
                CurrentService(config=config)
        self.assertFalse(current_policy.validate(dict(current_policy.DEFAULT, aggregate_enabled=False))['aggregate_enabled'])

    def test_default_absence_and_explicit_config_have_distinct_contracts(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(current_policy,'ROOT',Path(temp)):
            self.assertEqual(current_policy.load(),current_policy.validate(current_policy.DEFAULT))
            for path in (Path(temp)/'missing.json',Path(temp)/'.local/predict-current-config.json'):
                with self.subTest(path=path), self.assertRaisesRegex(FileNotFoundError,'Explicit current configuration'):
                    current_policy.load(path)
            path=Path(temp)/'config.json'
            config=dict(current_policy.DEFAULT,enabled=False,aggregate_enabled=False)
            path.write_text(json.dumps(config))
            self.assertEqual(current_policy.load(path),config)
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Exact native'):
                current_policy.load(path)

    def test_retired_preview_flag_rejected_before_service_or_credentials(self):
        result=subprocess.run([sys.executable,'-m','app.dashboard','--u0-preview'],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,2)
        self.assertIn('unrecognized arguments: --u0-preview',result.stderr)

    def test_unsupported_paid_transition_fails_before_any_durable_write(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = current_quota.QuotaLedger(Path(temp)/'quota')
            for credits in (500, 0, True, '100000'):
                with self.subTest(credits=credits), self.assertRaisesRegex(current_quota.QuotaStop, 'paid_account_policy_required'):
                    ledger.transition_account(dict(account_id='synthetic', monthly_credits=credits))
                self.assertFalse(ledger.directory.exists())


class TransportPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_transport_enforces_shared_bound_instead_of_literal_copy(self):
        transport = current_aggregate.CurrentOddsTransport()
        client = Client(Response(body=b'[0,0]'))
        with patch.object(current_aggregate, 'POLICY', replace(POLICY, response_bytes=4)), \
                patch.object(current_aggregate.aiohttp, 'ClientSession', return_value=client):
            with self.assertRaisesRegex(current_quota.QuotaStop, 'aggregate_response_byte_cap'):
                await transport.request(dict(path='/v4/sports', params={}), 'synthetic-key')
            await transport.close()
        self.assertTrue(client.closed)


class CalculationOwnership(unittest.TestCase):
    def test_saved_engine_binding_includes_shared_settings_adapter(self):
        from app.storage.current_games import engine_binding
        original=Path.read_bytes
        before=engine_binding()
        def changed(path):
            data=original(path)
            return data+b'\n# synthetic settings revision\n' if path.as_posix().endswith('/app/dashboard/query_policy.py') else data
        with patch.object(Path,'read_bytes',changed):
            self.assertNotEqual(engine_binding(),before)

    def test_removed_unused_adapters_do_not_return(self):
        from app.comparison import current_metrics
        from app.collection import public_contracts
        self.assertFalse(hasattr(current_metrics, 'apply_group_metrics'))
        self.assertFalse(hasattr(public_contracts, 'championship_descriptor'))

    def test_shared_settings_are_exact_bounded_and_explicit(self):
        from app.dashboard.query_policy import calculation_policy
        from app.dashboard.local_security import PublicRequestError
        from app.comparison.estimated_policy import DEFAULT_POLICY, LEGACY_POLICY
        result = calculation_policy(MultiDict(amount='500', ceiling='500.0', buffer='0.01', benchmark_venue='novig'), DEFAULT_POLICY)
        self.assertEqual(result.capital_ceiling_usd, '500')
        self.assertEqual(result.buffer_rate, '0.01')
        self.assertEqual(result.benchmark_venue, 'novig')
        self.assertEqual(calculation_policy({}, DEFAULT_POLICY.to_dict()), DEFAULT_POLICY)
        self.assertEqual(calculation_policy({}, LEGACY_POLICY), LEGACY_POLICY)
        for query in (MultiDict([('amount','500'),('amount','1000')]),
                      {'amount':'500','ceiling':'1000'}, {'benchmark_venue':'kalshi'},
                      {'buffer':'1.01'}, {'amount':'1e1000000','ceiling':'1'},
                      {'amount':'1','ceiling':'1e1000000'}):
            with self.subTest(query=query), self.assertRaises(PublicRequestError):
                calculation_policy(query, DEFAULT_POLICY)


class SharedPolicyEndpoints(unittest.IsolatedAsyncioTestCase):
    async def test_saved_endpoints_use_one_settings_adapter_before_sql(self):
        from app.dashboard import comparison_board_api, stored_games
        from app.dashboard.query_policy import calculation_policy
        from app.dashboard.local_security import PublicRequestError
        from app.comparison.estimated_policy import DEFAULT_POLICY
        provider=SimpleNamespace(closed=False, closing=False, dispatch=True, database=SimpleNamespace(status=lambda:{}))
        for module, path, view in ((comparison_board_api,'/api/boards/{view}','odds'),
                                   (stored_games,'/api/stored/result',None)):
            app=web.Application();module.mount(app,provider)
            handler=next(route.handler for route in app.router.routes() if route.method=='GET' and route.resource.canonical==path)
            req=SimpleNamespace(query=MultiDict(game='synthetic:game',amount='500'),match_info={'view':view})
            output=({'delivery_state':'complete'},False) if view else {'superseded':False,'state':{'events':[]}}
            with patch.object(module,'load',return_value=DEFAULT_POLICY), \
                 patch.object(module,'calculation_policy',wraps=calculation_policy) as settings, \
                 patch.object(module.asyncio,'to_thread',return_value=output) as sql:
                result=await handler(req)
                self.assertEqual(result.status,200)
                settings.assert_called_once_with(req.query,DEFAULT_POLICY)
                self.assertEqual(sql.call_args.args[2].capital_ceiling_usd,'500')
            req.query=MultiDict(game='synthetic:game',amount='500',ceiling='1000')
            with patch.object(module,'load',return_value=DEFAULT_POLICY), patch.object(module.asyncio,'to_thread') as sql:
                with self.assertRaises(PublicRequestError):await handler(req)
                sql.assert_not_called()
