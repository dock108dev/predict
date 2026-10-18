"""Authored SQL-reader state checks; no owner SQL, provider or acquisition.

The real reader, projection withdrawal and HTTP handlers run against a detached
publication. An unavailable publication must not claim an acknowledged Stop.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from app.collection.current_policy import DEFAULT
from app.comparison.current_dependencies import digest, instant
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.comparison.scanner_projection import Projection
from app.dashboard.scanner_api import ScannerReader, mount
from app.storage.scanner_latest import snapshot
from tests.test_sc02_projection import AT, fake, frame


class ReadOnlyFixture:
    def __init__(self, owner):self.owner = owner
    def __enter__(self):return self
    def __exit__(self, *args):return False
    def transaction(self):return self
    def execute(self, statement, *args):
        if statement.startswith('SET TRANSACTION'):return self
        if statement == 'SELECT * FROM scanner_latest WHERE singleton':return self
        raise AssertionError('Unexpected fixture SQL: ' + statement)
    def fetchone(self):return deepcopy(self.owner.row)


class ReaderStates(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = AT
        self.runtime = dict(healthy=True, active=True, runtime_id='authored-runtime',
            config=deepcopy(DEFAULT), states={}, revision=1, heartbeat_at=AT,
            calculations=dict(scanner='running'), global_stopped=False)
        self.proof = dict(epoch='authored', facts_revision='facts', current_rows_revision='rows')
        self.policy = replace(DEFAULT_POLICY, sizing_mode='ceiling')
        marker = digest(dict(rows=self.proof, config=self.runtime['config'], states={},
            engine='authored-engine', policy=self.policy.to_dict(), registry=('authored-registry', None)))
        p = Projection(clock=lambda:self.now, evaluator=fake)
        facts, inputs = frame()
        for key, value in inputs.items():
            value['quote']['source'] = dict(provider='authored', native_event_id='event-' + key)
        p.ingest(facts, inputs);p.drain()
        self.fixture_inputs = deepcopy(inputs)
        payload = snapshot(SimpleNamespace(projection=p, summaries=SimpleNamespace(store=None),
            deadline=None, marker=marker))
        self.row = dict(runtime_id=self.runtime['runtime_id'], runtime_revision=1,
            publication=p.publication, published_at=AT, payload=payload)
        self.reader = ScannerReader(SimpleNamespace(remote_runtime=True),
            connector=lambda:ReadOnlyFixture(self), clock=lambda:self.now)
        self.reader.preparation.registry = lambda **kwargs:('authored-registry', None)
        for name, replacement in (
                ('app.collection.runtime_status.read_runtime', lambda db:deepcopy(self.runtime)),
                ('app.storage.scanner_publication.current_revision', lambda db:deepcopy(self.proof)),
                ('app.dashboard.scanner_api.engine_binding', lambda:'authored-engine'),
                ('app.dashboard.scanner_api.load', lambda:self.policy)):
            replacement_patch = patch(name, replacement)
            replacement_patch.start();self.addCleanup(replacement_patch.stop)
        self.reader.refresh()
        self.assertFalse(self.reader.stopped())
        self.assertTrue(self.reader.projection.rows)

    async def asyncTearDown(self):await self.reader.close()

    def assert_unavailable(self):
        self.assertTrue(self.reader.stopped(), 'Ticket authority must remain withdrawn')
        view = self.reader.projection.view()
        self.assertEqual(view['coverage']['state'], 'unavailable')
        self.assertFalse(view['coverage']['complete'])
        self.assertFalse(view['coverage']['no_qualifying_opportunities'])
        self.assertFalse(view['rows'])
        self.assertFalse(self.reader.projection.receipts)
        self.assertFalse(self.reader.projection.cache)
        self.assertFalse(self.reader.projection.targets)

    async def request(self, path):
        app = web.Application()
        with patch('app.dashboard.scanner_api.ScannerReader', return_value=self.reader):
            mount(app, SimpleNamespace(remote_runtime=True))
        route = next(route for route in app.router.routes()
            if route.method == 'GET' and route.resource.canonical == path.split('?')[0])
        response = await route.handler(make_mocked_request('GET', path, app=app))
        return response.status, json.loads(response.body)

    async def test_new_sql_before_publication_is_unavailable_then_recovers(self):
        original = deepcopy(self.proof)
        self.proof['facts_revision'] = 'newly-committed-facts'
        self.reader.refresh();self.assert_unavailable()
        status, response = await self.request('/api/scanner')
        self.assertEqual(status, 200)
        self.assertEqual(response['coverage']['state'], 'unavailable')
        publication = self.reader.projection.publication
        self.reader.refresh()
        self.assertEqual(self.reader.projection.publication, publication)
        with self.assertRaisesRegex(ValueError, 'data_runtime_unavailable'):
            self.reader._capture_selected({})
        self.proof = original
        self.reader.refresh()
        self.assertFalse(self.reader.stopped())
        self.assertTrue(self.reader.projection.rows)

    async def test_absent_expired_failed_and_dead_owner_do_not_claim_stop(self):
        original_row, original_runtime = deepcopy((self.row, self.runtime))
        for failure in ('absent', 'deadline', 'calculation', 'heartbeat'):
            with self.subTest(failure=failure):
                self.row, self.runtime = deepcopy((original_row, original_runtime))
                if failure == 'absent':self.row = None
                elif failure == 'deadline':self.row['payload']['deadline'] = AT
                elif failure == 'calculation':self.runtime['calculations']['scanner'] = 'failed'
                else:self.runtime.update(healthy=False, active=False)
                self.reader.refresh();self.assert_unavailable()
                self.row, self.runtime = deepcopy((original_row, original_runtime))
                self.reader.refresh();self.assertFalse(self.reader.stopped())

    async def test_read_failure_and_delayed_heartbeat_cutoff_withdraw_without_stop(self):
        with patch.object(self.reader, 'connector', side_effect=OSError('fixture database absent')):
            self.reader.refresh();self.assert_unavailable()
        self.reader.refresh()
        self.now = (instant(AT) + timedelta(seconds=8)).isoformat()
        self.assertTrue(self.reader._withdraw_if_stopped())
        self.assert_unavailable()
        # A delayed heartbeat can recover the same stored publication after a
        # fresh proof; the local withdrawal must not suppress its restoration.
        self.runtime['heartbeat_at'] = self.now
        self.reader.refresh()
        self.assertFalse(self.reader.stopped())
        self.assertTrue(self.reader.projection.rows)

    async def test_explicit_global_stop_is_stopped_and_stale_publication_cannot_resume(self):
        self.runtime.update(active=False, global_stopped=True)
        self.reader.refresh()
        status, response = await self.request('/api/scanner')
        self.assertEqual(status, 200)
        self.assertEqual(response['coverage']['state'], 'stopped')
        self.assertFalse(response['rows'])
        self.assertTrue(self.reader.stopped())
        self.reader.refresh()
        self.assertEqual(self.reader.projection.view()['coverage']['state'], 'stopped')
        self.assertFalse(self.reader.projection.receipts)
        self.runtime['active'] = True  # A stale dispatch bit cannot defeat Stop.
        self.reader.refresh()
        self.assertTrue(self.reader.stopped())
        self.assertFalse(self.reader.projection.rows)

    async def test_ticket_unavailable_preserves_selected_and_replacement_frames(self):
        from app.comparison.scanner_tickets import Tickets, selector
        from app.comparison.scanner_destinations import Destinations
        from tests.test_sc03_tickets import finance, catalog
        p = self.reader.projection
        selected = selector(p, next(iter(p.rows.values())))
        tickets = Tickets(p, calculate=finance, stopped=self.reader.stopped,
            collection_stopped=lambda:self.reader.collection_stopped,
            current_selected=lambda selection:(p.frame, self.fixture_inputs),
            destinations=Destinations(catalog(p.frame['instruments'])), allow_authored=True)
        try:
            client = 'authored_reader_client'
            initial = await tickets.command(dict(operation='select', client_id=client,
                sequence=1, selection=selected))
            replacement = await tickets.command(dict(operation='revalidate', client_id=client,
                sequence=2, ticket_id=initial['ticket_id'], amount='500'))
            self.assertTrue(replacement['replacement_frame'])
            original_proof = deepcopy(self.proof)
            self.proof['facts_revision'] = 'newly-committed-facts'
            self.reader.refresh()
            unavailable = tickets.inspect(client, initial['ticket_id'])
            self.assertEqual(unavailable['state'], 'temporarily_unavailable')
            self.assertFalse(unavailable['ready_for_manual_action'])
            self.assertEqual(unavailable['selected_frame'], replacement['selected_frame'])
            self.assertEqual(unavailable['replacement_frame'], replacement['replacement_frame'])
            self.proof = original_proof;self.reader.refresh()
            recovered = tickets.inspect(client, initial['ticket_id'])
            self.assertEqual(recovered['state'], 'revised')
            self.assertFalse(recovered['ready_for_manual_action'])
            self.runtime.update(active=False, global_stopped=True);self.reader.refresh()
            stopped = tickets.inspect(client, initial['ticket_id'])
            self.assertEqual(stopped['state'], 'stopped')
            self.assertFalse(stopped['ready_for_manual_action'])
        finally:await tickets.close()

    async def test_binding_failure_distinguishes_publication_gap_and_actual_stop(self):
        from urllib.parse import urlencode
        row = next(iter(self.reader.projection.rows.values()))
        query = dict(server_id=self.reader.projection.server_id, epoch=self.reader.projection.epoch,
            row_id=row['id'], dependency_revision=row['dependency_revision'],
            economic_revision=row['economic_revision'])
        self.proof['facts_revision'] = 'newly-committed-facts'
        status, response = await self.request('/api/scanner/ticket/binding?' + urlencode(query))
        self.assertEqual(status, 409)
        self.assertEqual(response['error'], 'ticket_current_proof_unavailable')
        self.runtime.update(active=False, global_stopped=True)
        status, response = await self.request('/api/scanner/ticket/binding?' + urlencode(query))
        self.assertEqual(status, 409)
        self.assertEqual(response['error'], 'ticket_stopped')

    async def test_unavailable_during_ticket_finance_has_no_stopped_reason(self):
        from app.comparison.scanner_tickets import Tickets, selector
        from tests.test_sc03_tickets import finance
        p = self.reader.projection
        selected = selector(p, next(iter(p.rows.values())))
        def during(*args, **kwargs):
            self.reader.healthy = False
            return finance(*args, **kwargs)
        tickets = Tickets(p, calculate=during, stopped=self.reader.stopped,
            collection_stopped=lambda:self.reader.collection_stopped,
            current_selected=lambda selection:(p.frame, self.fixture_inputs))
        try:
            value = await tickets.command(dict(operation='select',
                client_id='authored_reader_client', sequence=1, selection=selected))
            self.assertEqual(value['state'], 'temporarily_unavailable')
            self.assertEqual(value['reason'], 'temporarily_unavailable')
            self.assertFalse(value['ready_for_manual_action'])
        finally:await tickets.close()

    async def test_transition_read_keeps_unavailability_censored_and_silent(self):
        self.row = None
        status, response = await self.request('/api/scanner/transitions')
        self.assertEqual(status, 200)
        self.assertEqual(response['continuity'], 'censored')
        self.assertFalse(response['events'])
        self.assertFalse(response['coverage_complete'])
        self.assert_unavailable()

    async def test_retained_stop_summary_needs_current_explicit_latch(self):
        from app.comparison.scanner_summaries import MAX_BYTES, MAX_EPISODES, RETENTION_SECONDS
        self.row['payload']['summary'] = dict(records={},
            latest=dict(reason='stopped', state='stopped', observed_at=AT),
            meta=dict(first=AT, last=AT, lost=True, complete_publications=0,
                gaps=1, evicted=0, high_water=0),
            failed=None, max_bytes=MAX_BYTES, max_episodes=MAX_EPISODES,
            retention_seconds=RETENTION_SECONDS, physical_bytes=0)
        # The background observation may lag a newly running runtime.
        value = self.reader.summaries.read(at=AT)
        self.assertEqual(value['state'], 'unavailable')
        self.assertIsNone(value['coverage']['checked_zero'])
        self.proof['facts_revision'] = 'newly-committed-facts'
        value = self.reader.summaries.read(at=AT)
        self.assertEqual(value['state'], 'unavailable')
        self.assertFalse(value['coverage']['complete'])
        self.runtime.update(active=False, global_stopped=True)
        value = self.reader.summaries.read(at=AT)
        self.assertEqual(value['state'], 'stopped')
        self.assertIsNone(value['coverage']['checked_zero'])
