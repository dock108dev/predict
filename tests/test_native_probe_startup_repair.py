"""Offline startup and no-subscription boundaries; no remote transport allowed."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
from aiohttp.test_utils import TestClient,TestServer
from app.collection.continuous import ContinuousSession,Venue
from app.collection.native_approval import implementation,digest
from app.collection.prediction_producer import PredictionProducer
from app.collection.venue_access import ENDPOINTS
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from tests.native_selector_runtime import Fixture

ROOT=Path(__file__).resolve().parents[1]
def spec():return json.loads((ROOT/'evidence/native-discovery-probe-20260930/run-spec.json').read_text())

class StartupFailure(unittest.IsolatedAsyncioTestCase):
    async def test_pre_task_failure_closes_owned_resources_and_consumes_attempt(self):
        resource=AsyncMock()
        class FailedSession(ContinuousSession):
            async def start(self):
                self.producers={'fixture_resource':resource}
                raise ValueError('OFFLINE injected pre-task failure')
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
            root=Path(tmp).resolve();out=root/'attempt';approval=root/'approval.json';s=spec()
            approval.write_text(json.dumps(dict(approved=True,output=str(out),implementation_sha256=digest(implementation()),spec_sha256=digest(s))))
            o=CoverageOwner(root/'saved',pilot_output=out,endpoints=ENDPOINTS,spec_factory=lambda:deepcopy(s),product_mode=True,native_approval_path=approval,session_factory=FailedSession)
            client=TestClient(TestServer(create_app(owner=o,sessions={},watch_path=root/'watches.json')));await client.start_server();origin={'Origin':str(client.make_url('/')).rstrip('/')}
            try:
                response=await client.post('/api/start',json={'duration':90},headers=origin);self.assertEqual(response.status,422)
                self.assertTrue((out/'b3-attempt.json').exists());self.assertTrue(o.session.cleanup_complete);self.assertFalse(o.active());self.assertIsNone(o.owner_lock)
                resource.aclose.assert_awaited_once()
                failure=json.loads((o.session.output/'startup-failure.json').read_text());self.assertFalse(failure['primary_journal_created']);self.assertTrue(failure['cleanup_complete'])
                self.assertIn('attempt retained',o.error)
                diagnostic=(o.session.output/'startup-failure.json').read_bytes()
                # Separate offline control request proves refusal, never another live allowance.
                response=await client.post('/api/start',json={'duration':90},headers=origin);self.assertEqual(response.status,422);self.assertIn('consumed',await response.text())
                resource.aclose.assert_awaited_once()
                self.assertEqual((o.session.output/'startup-failure.json').read_bytes(),diagnostic)
            finally:await client.close()

class SubscriptionBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_does_not_promote_metadata_to_subscription(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Fixture(probe=True);o=await f.boot(tmp)
            try:
                await f.start(duration=10);await f.wait(lambda:o.session.discovery.completed)
                with patch('app.collection.continuous.PredictionProducer',side_effect=AssertionError('Stream construction forbidden')):
                    for venue in ('kalshi','polymarket_us'):
                        p=o.session.producers[venue]
                        # Force recomputation with a selected candidate: discovery-only
                        # still overrides eligibility at the actual subscription boundary.
                        mid=next(iter(o.session.discovery.markets[venue]))
                        with patch('app.collection.continuous.select_inventory',return_value=([mid],1)):
                            await p.reconcile()
                        self.assertFalse(p.selected);self.assertFalse(p.groups)
                await f.stop_route();self.assertTrue(o.session.cleanup_complete)
            finally:await f.close()

class CredentialBoundary(unittest.TestCase):
    def test_ordinary_real_stream_still_requires_credentials(self):
        s=spec();s.pop('native_discovery')
        for venue in ('kalshi','polymarket_us'):
            with self.assertRaisesRegex(ValueError,'dedicated project credential required'):
                PredictionProducer(venue,s,ENDPOINTS[venue]['rest'],ENDPOINTS[venue]['ws'],lambda *a:None,lambda *a:None)
