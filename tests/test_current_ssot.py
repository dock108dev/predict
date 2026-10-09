"""Current policy ownership and explicit configuration; temporary/mocked state only."""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

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
