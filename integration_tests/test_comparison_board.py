"""Current SQL/API contract; disposable database, retained facts, no acquisition."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg import sql

from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard.comparison_board import response, entries, quote_key
from app.storage.comparison_board import (
    ReadContext, discover, calculate_current, context_identity, capture, saved,
)
from app.storage.current_games import GameStore
from app.storage.current_rows import CurrentRowStore, contract_id
from app.storage.store import connect, Store
from tests.test_ev09_n01 import retained, envelopes, AT, SELECTED


class ComparisonBoardSQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # SQL visibility and admission must use the same historical replay clock.
        clock = patch('app.storage.current_rows.utc', return_value=AT)
        clock.start()
        cls.addClassCleanup(clock.stop)
        cls.name = 'prediction_arb_test_b01_' + uuid4().hex[:12]
        with connect() as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.db = connect(cls.name)
        Store(cls.db).migrate()
        cls.rows = CurrentRowStore(cls.db)
        original, _ = retained()
        # Admit retained facts at their replay time, not the date CI happens to run.
        cls.rows.upsert_records(original['records'], now=AT)
        members = set(map(tuple, original['members']))
        cls.rows.replace_native_books([
            o['book'] for e in envelopes() if e['record']['kind'] == 'admitted_books'
            for o in e['record']['value']['observations']
            if (e['record']['source'], o['book']['raw']['ref']['event_id']) in members
        ])

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with connect() as db:
            db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))

    def setUp(self):
        self.transaction = self.db.transaction(force_rollback=True)
        self.transaction.__enter__()

    def tearDown(self):
        self.transaction.__exit__(None, None, None)

    def current(self, policy=DEFAULT_POLICY, at=AT):
        context = ReadContext(GameStore(self.db), at=at)
        bundle = discover(context.store, context=context, selected=SELECTED)[0]
        bundle['calculation_context'] = context_identity(bundle, policy, context)
        return context, bundle

    def test_sql_catalog_and_exact_financial_trace(self):
        context, bundle = self.current()
        self.assertEqual(context.catalog()['version'], 'predict-board-catalog-2')
        self.assertEqual(context.catalog()['limits']['maximum_games'], len(context.catalog()['games']))
        actual = calculate_current(bundle, DEFAULT_POLICY, context=context)
        expected = {quote_key(q): q for _, _, q in entries(retained()[1])}
        for _, _, q in entries(actual['state']):
            prior = expected[quote_key(q)]
            self.assertEqual(q['original'], prior['original'])
            self.assertEqual(q['times']['source_at'], prior['times']['source_at'])
            for field in ('financial_metrics', 'funding', 'classification'):
                self.assertEqual(q['calculations']['funded_estimate'].get(field),
                                 prior['calculations']['funded_estimate'].get(field))

    def test_reads_and_calculations_never_write_archives(self):
        context, bundle = self.current()
        for view in ('odds', 'ev', 'arbs'):
            value = None if view == 'odds' else calculate_current(bundle, DEFAULT_POLICY, context=context)
            out = response(bundle, value, DEFAULT_POLICY, view=view, filter='all', at=AT)
            self.assertEqual(out['version'], 'predict-comparison-board-2')
            self.assertEqual(out['calculation_context'], bundle['calculation_context'])
            self.assertNotIn('snapshot_id', out)
            self.assertNotIn('result_id', out)
        for table in ('current_envelope', 'current_game_snapshot', 'current_game_result',
                      'current_calculation_attempt', 'current_import_cursor'):
            self.assertEqual(self.db.execute(sql.SQL('SELECT count(*) n FROM {}').format(
                sql.Identifier(table))).fetchone()['n'], 0)

    def test_archive_entry_points_fail_explicitly(self):
        for reader in (capture, saved):
            with self.assertRaisesRegex(ValueError, 'archive_retired'):
                reader(GameStore(self.db), 'old-game', DEFAULT_POLICY)

    def test_policy_and_engine_changes_revoke_context(self):
        context, bundle = self.current()
        identity = bundle['calculation_context']
        for policy in (replace(DEFAULT_POLICY, capital_ceiling_usd='500'),
                       replace(DEFAULT_POLICY, buffer_rate='0.01')):
            self.assertNotEqual(identity['context_id'], context_identity(bundle, policy, context)['context_id'])
        context.engine = 'changed-engine'
        self.assertNotEqual(identity['context_id'], context_identity(bundle, DEFAULT_POLICY, context)['context_id'])

    def test_receipt_arrival_changes_context_without_renewing_source_clock(self):
        _, before = self.current()
        row = deepcopy(next(r for r in retained()[0]['records'] if r['quote']['venue'] == 'novig'))
        original = row['quote']['times']['source_at']
        row['quote']['times']['received_at'] = '2026-10-14T01:16:00Z'
        self.rows.upsert_records([row], now=AT)
        _, after = self.current()
        self.assertNotEqual(before['calculation_context'], after['calculation_context'])
        changed = next(r for r in after['records'] if contract_id(r) == contract_id(row))
        self.assertEqual(changed['quote']['times']['source_at'], original)

    def test_other_occurrence_does_not_revoke_selected_context(self):
        _, before = self.current()
        rows = deepcopy([r for r in retained()[0]['records'] if r['quote']['venue'] == 'novig'])
        for row in rows:
            row['event']['id'] = 'authored-other-event'
            row['quote']['source']['native_event_id'] = 'authored-other-event'
            row['event']['scheduled_start'] = '2026-10-18T20:15:00Z'
            row['market_identity']['scheduled_start'] = '2026-10-18T20:15:00Z'
        self.rows.upsert_records(rows, now=AT)
        _, after = self.current()
        self.assertEqual(before['calculation_context'], after['calculation_context'])

    def test_reset_and_temporal_boundaries_revoke_context(self):
        _, before = self.current()
        self.db.execute("UPDATE current_row_epoch SET epoch='authored-reset' WHERE singleton=true")
        _, reset = self.current()
        self.assertNotEqual(before['calculation_context'], reset['calculation_context'])
        _, later = self.current(at='2026-10-14T03:00:00Z')
        self.assertNotEqual(reset['calculation_context'], later['calculation_context'])
        self.assertEqual(ReadContext(GameStore(self.db), at='2030-01-01T00:00:00Z').catalog()['games'], [])

    def test_failed_offer_update_is_atomic(self):
        before = self.rows.capture()
        rows = deepcopy(retained()[0]['records'])
        rows[0]['quote']['original']['value'] = '9.9999'
        with self.assertRaisesRegex(ValueError, 'equal_clock'):
            self.rows.upsert_records(rows, now=AT)
        self.assertEqual(self.rows.capture(), before)

    def test_replay_clock_is_explicit_and_default_ingress_still_expires(self):
        with patch('app.storage.current_rows.utc', return_value='2030-01-01T00:00:00Z'):
            self.rows.upsert_records(retained()[0]['records'], now=AT)
            self.assertEqual(self.db.execute('SELECT count(*) n FROM current_offer').fetchone()['n'],
                             len(retained()[0]['records']))
            self.assertEqual(self.rows.capture()['records'], [])
            # Ordinary ingress keeps its real-time expiry default.
            self.rows.upsert_records([])
            self.assertEqual(self.db.execute('SELECT count(*) n FROM current_event').fetchone()['n'], 0)

    def test_loopback_requires_background_publication_and_reports_database_failure(self):
        # Current ingress alone is not a published financial board. The required
        # latest-board SQL suite covers positive publication/details/Stop journeys.
        import asyncio
        from app.dashboard.comparison_board_api import mount
        async def check():
            provider = SimpleNamespace(dispatch=True, closed=False, closing=False,
                                       database=SimpleNamespace(status=lambda: dict(state='available')))
            app = web.Application()
            mount(app, provider)
            with patch('app.dashboard.comparison_board_api.connect', side_effect=lambda: connect(self.name)), \
                 patch('app.dashboard.comparison_board_api.calculate_current', side_effect=AssertionError('requests cannot publish missing background results')), \
                 patch('app.collection.current_account_recovery.observe_and_activate', side_effect=AssertionError('no acquisition')), \
                 patch('httpx.Client.send', side_effect=AssertionError('no provider traffic')):
                async with TestClient(TestServer(app)) as client:
                    catalog_reply = await client.get('/api/boards/games')
                    self.assertEqual(catalog_reply.status, 200)
                    catalog = await catalog_reply.json()
                    self.assertEqual(catalog['games'], [])
                    self.assertEqual(catalog['provider_requests'], 0)
                    for view in ('odds', 'ev', 'arbs', 'details', 'inputs'):
                        result = await client.get('/api/boards/' + view, params=dict(
                            game='combined:unpublished', filter='all', context_id='unpublished', quote='unpublished'))
                        self.assertEqual(result.status, 409, await result.text())
                        self.assertEqual((await result.json())['provider_requests'], 0)
                    history = await client.get('/api/boards/history')
                    self.assertEqual(history.status, 410)
                    with patch('app.dashboard.comparison_board_api.connect', side_effect=OSError('offline')):
                        failed = await client.get('/api/boards/games')
                        self.assertEqual(failed.status, 503)
                        self.assertEqual((await failed.json())['provider_requests'], 0)
        asyncio.run(check())
