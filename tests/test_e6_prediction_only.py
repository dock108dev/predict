"""Prediction-first owner regressions; all transport tests use local servers."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.test_e6_transport import IntegrationTests, spec
from app.collection.run_spec import preflight
from app.collection.native_replay import verify_native
from app.collection.transport_session import TransportSession,reopen
from app.collection.prediction_producer import PredictionBudget

class PredictionOnly(IntegrationTests):
    # Inherit local fixtures, not test methods that require reference collection.
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.s['reference_enabled']=False
        self.s['sources'].pop('the_odds_api');self.s.pop('http');self.s.pop('reference_cadence')
    async def test_native_producers_recovery_mixed_persistence_and_exact_reopen(self):
        with patch('app.collection.transport_session.OddsHTTP',side_effect=AssertionError('reference constructed')):
            o=await self.start();await o.task
        self.assertEqual(self.ref_calls,0);self.assertIsNone(o.reference)
        self.assertNotIn('reference',o.health)
        result=verify_native(o.journal.path)
        self.assertTrue(all(result['exact_native_books'].values()))
        self.assertGreaterEqual(self.k_connections,2);self.assertGreaterEqual(self.p_connections,2)
        self.assertEqual(o.delivered,o.persisted)
        self.assertEqual(reopen(o.journal.path),reopen(o.journal.path))
    async def test_cancel_backoff_and_start_over_60_seconds(self):
        self.s['duration']=120
        o=await self.start();await asyncio.sleep(.15);await o.stop()
        self.assertEqual(o.reason,'manual_stop');self.assertEqual(o.state,'stopped')
    async def test_prediction_capacity_stops(self):
        self.s['prediction']['session_bytes']=64
        o=await self.start();await o.task
        self.assertEqual(o.state,'stopped')
        self.assertTrue(o.reason.startswith('discovery_failure'))
    async def test_reference_failure_does_not_stop_predictions(self):
        ref=spec();self.s.update(reference_enabled=True,http=ref['http'],reference_cadence=.05)
        self.s['sources']['the_odds_api']=ref['sources']['the_odds_api'];self.s['http']['credits']=1
        o=await self.start();await o.task
        self.assertEqual(o.reason,'duration_or_kickoff_cutoff')
        self.assertTrue(any(r['type']=='prediction_book' for r in reopen(o.journal.path)['rows']))

class PureTests(unittest.TestCase):
    def test_default_off_key_presence_no_lookup(self):
        s=spec();s.pop('reference_enabled');s.pop('http');s.pop('reference_cadence');s['sources'].pop('the_odds_api')
        with patch('os.environ',{'ODDS_API_KEY':'must-not-be-read'}),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credential lookup')):
            self.assertTrue(preflight(s)['valid'])
            owner=TransportSession(s,'/unused',{})
            self.assertEqual(owner.state,'idle');self.assertIsNone(owner.reference)
    def test_skeleton_prediction_only(self):
        s=json.loads(Path('docs/e6-first-real-run.json').read_text())
        errors=preflight(s)['errors']
        self.assertFalse(any('http' in x or 'reference_cadence' in x or 'the_odds_api' in x for x in errors))
    def test_credentials_missing_redacted(self):
        from app.collection.venue_access import load_credentials
        with patch('keyring.backends.macOS.Keyring.get_password',side_effect=RuntimeError('SECRET')):
            with self.assertRaisesRegex(RuntimeError,'kalshi: existing dedicated') as e:load_credentials()
            self.assertNotIn('SECRET',str(e.exception))
    def test_production_destination_and_secret_echo(self):
        from app.collection.venue_access import endpoint,Credential
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        import base64
        seed=Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())
        c=Credential('polymarket_us',dict(key_id='dummy-private-id',secret_key=base64.b64encode(seed).decode()))
        self.assertNotIn('dummy-private-id',repr(c))
        with self.assertRaises(ValueError):c.check(b'{"error":"dummy-private-id"}')
        with self.assertRaises(ValueError):endpoint('kalshi','rest','https://evil.invalid')
    def test_queue_and_ingress_limits(self):
        from app.collection.transport_session import ObservationJournal
        from app.collection.odds_http import BudgetStop
        with tempfile.TemporaryDirectory() as tmp:
            o=TransportSession(spec(),tmp,{})
            o.journal=ObservationJournal(Path(tmp)/'queue')
            try:
                for _ in range(48):o.emit('kalshi',dict(type='test'))
                with self.assertRaises(asyncio.QueueFull):o.emit('kalshi',dict(type='test'))
                self.assertEqual(o.reason,'queue_capacity')
            finally:o.journal.close()

    def test_production_rest_constructor_is_idle_and_bounded(self):
        from app.collection.prediction_producer import MockREST
        from app.collection.venue_access import ENDPOINTS
        limits=spec()['prediction'];budget=PredictionBudget(limits)
        with patch('aiohttp.ClientSession',side_effect=AssertionError('network')):
            client=MockREST(ENDPOINTS['kalshi']['rest'],limits,lambda r:None,5,budget,venue='kalshi')
            self.assertEqual(client.limits,limits);self.assertEqual(client.timeout,5)
            self.assertEqual(client.budget.requests,0);self.assertIsNone(client.client)

class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_generic_catalog_native_filter_and_no_credentials(self):
        from app.collection.prediction_discovery import NFLPolymarketAdapter
        from app.adapters.polymarket_us import PolymarketUSAdapter
        with patch.object(PolymarketUSAdapter,'_get',return_value='response') as get:
            a=NFLPolymarketAdapter()
            try:
                self.assertEqual(await a._get('/v2/leagues/nfl/events',{'limit':5,'offset':0}),'response')
                path,query=get.call_args.args
                self.assertEqual(path,'/v1/events')
                self.assertEqual(query['sportsMarketTypes'],'football_team_full_game_winner')
                self.assertEqual(query['tagSlug'],'nfl')
            finally:await a.aclose()
    def test_abbreviation_and_mascot_must_agree(self):
        from app.models.core import Event
        from app.adapters.kalshi import Response
        from app.collection.prediction_discovery import participant_mapping
        from datetime import datetime,timezone
        def mapping(title):
            raw=json.dumps(dict(events=[dict(event_ticker='E',series_ticker='KXNFLGAME',title=title)]))
            e=Event(raw=Response(raw,'local mock',datetime.now(timezone.utc)).raw('E'),league='NFL',title=title)
            return participant_mapping(e)[1]
        self.assertEqual(mapping('DET Lions vs BUF Bills'),{'DET Lions':'NFL:DET','BUF Bills':'NFL:BUF'})
        self.assertIsNone(mapping('DET Bills vs BUF Lions')['DET Bills'])
    def test_phase_rescheduling_conflicting_market_schedule(self):
        from app.collection.prediction_discovery import validate_pregame
        from app.models.core import Event
        from app.adapters.polymarket_us import Response
        from datetime import datetime,timezone,timedelta
        for changes in [dict(live=True),dict(rescheduledFromGameId=123),dict(period='Q1')]:
            row=dict(id='E',startTime=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),**changes)
            raw=Response(json.dumps(dict(events=[row])),'local mock',datetime.now(timezone.utc)).raw('E')
            event=Event(raw=raw,title='A vs B',scheduled_start=datetime.fromisoformat(row['startTime']))
            with self.assertRaises(ValueError):validate_pregame(event)
