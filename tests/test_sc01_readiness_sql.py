"""SC01 disposable PostgreSQL and HTTP reads. Never starts collection."""
from pathlib import Path
import tempfile
ISOLATED_ROOT = tempfile.TemporaryDirectory(prefix='sc01-sql-')
import os
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
import unittest
from unittest.mock import patch

import psycopg
from psycopg import sql
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from app.storage.payload_codec import payload_row
from app.storage.store import Store, encoded
from app.storage.current_rows import CurrentRowStore, contract_id, native_offer_ask_counts
from app.storage.scanner_readiness import capture, capture_reservation, read
from app.storage.scanner_preparation import PreparationCache
from app.storage.scanner_publication import current_revision
from app.storage.comparison_board import ReadContext
from app.comparison.scanner_readiness import Selection
from app.collection.current_policy import DEFAULT, GRANT
from app.dashboard.comparison_board import entries, price
from app.dashboard.comparison_board_api import mount
from tests.test_d03_current_rows import fixture_records
from tests.test_ev09_n01 import AT, envelopes

SOCKET = os.environ.get('SC01_TEST_PGSOCKET')


@unittest.skipUnless(SOCKET, 'Explicit disposable-cluster socket required')
class ReadOnlySQL(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def connect(cls, name=None):
        return psycopg.connect(host=SOCKET,port=55432,user='prediction_arb',dbname=name or cls.name,
                              autocommit=True,row_factory=payload_row,connect_timeout=5)

    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_sc01_'+uuid4().hex[:10]
        with cls.connect('prediction_arb') as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        with cls.connect() as db:
            with patch('app.storage.store.ROOT',Path(ISOLATED_ROOT.name)):
                Store(db).migrate()
            # Replay admission at the retained observation time, including expiry.
            CurrentRowStore(db).upsert_records(fixture_records(),now=AT)

    @classmethod
    def tearDownClass(cls):
        with cls.connect('prediction_arb') as db:
            db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))

    def before(self, db):
        return {r['tablename']:db.execute(sql.SQL('SELECT count(*) n FROM {}').format(sql.Identifier(r['tablename']))).fetchone()['n'] for r in db.execute("select tablename from pg_tables where schemaname='public'").fetchall()}

    async def test_readonly_capture_no_writes_or_acquisition(self):
        with self.connect() as db:
            before=self.before(db)
            with patch('app.storage.current_rows.utc',return_value=AT), patch('socket.socket.connect',side_effect=AssertionError('No acquisition')):
                a=read(db,config=DEFAULT,authority=GRANT,at=AT)
                b=read(db,config=DEFAULT,authority=GRANT,at=AT)
            self.assertEqual(a,b)
            self.assertEqual(self.before(db),before)
            self.assertEqual(a['provider_requests'],0)
            self.assertFalse(a['evaluation']['no_qualifying_opportunities'])
            self.assertEqual(a['failed_occurrences'],[])
            self.assertEqual(sum(s['discovery']['offered_contracts']['value'] for s in a['scopes']),a['counts']['observed_instruments']['value'])

    async def test_scoped_capture_keeps_exact_results_and_skips_unrelated_components(self):
        from app.comparison.scanner_readiness import Selection
        from app.storage import scanner_readiness

        def all_components(db, planned, selection, scopes, wanted):
            return ((ids, True) for ids in planned)

        selection=Selection(venues=('kalshi','polymarket_us'), sports=('football',),
                            leagues=('NFL',), markets=('winner',))
        with self.connect() as db, patch('app.storage.current_rows.utc',return_value=AT):
            member=db.execute("""SELECT e.provider,e.native_event_id FROM current_event e JOIN current_contract c
                ON e.id=c.event_id JOIN current_offer o ON c.id=o.contract_id
                WHERE e.competition='NFL' AND c.venue='kalshi' AND c.facts#>>'{market_identity,family}'='moneyline'
                ORDER BY e.id LIMIT 1""").fetchone()
            for members in (None, (tuple(member.values()),)):
                with self.subTest(members=members):
                    args=dict(config=DEFAULT, authority=GRANT, at=AT, selection=selection, members=members)
                    with patch.object(scanner_readiness,'_selected_components',side_effect=all_components), \
                         patch.object(scanner_readiness,'ReadContext',wraps=scanner_readiness.ReadContext) as unscoped:
                        baseline=scanner_readiness.capture(db,**args)
                    with patch.object(scanner_readiness,'ReadContext',wraps=scanner_readiness.ReadContext) as scoped:
                        actual=scanner_readiness.capture(db,**args)
                    self.assertEqual(actual[:2],baseline[:2])
                    self.assertEqual(actual[2]['publication_proof'],baseline[2]['publication_proof'])
                    self.assertGreater(len(actual[0]['instruments']),0)
                    self.assertLess(scoped.call_count,unscoped.call_count)

    async def test_older_and_unknown_observations_cannot_replace_known(self):
        with self.connect() as db:
            store=CurrentRowStore(db)
            with patch('app.storage.current_rows.utc',return_value=AT):
                before=store.capture()
                records=store.capture()['records'];target=next(r for r in records if r['quote']['times']['source_at'])
                for clock in ('2020-01-01T00:00:00Z',None):
                    changed=deepcopy(target);changed['quote']['times'].update(source_at=clock,received_at=AT);changed['quote']['original']['value']='99'
                    # An old/unknown observation has no renewed book confirmation.
                    changed['quote'].pop('book_confirmation',None)
                    store.upsert_records([changed])
                    self.assertEqual(before['revision'],store.capture()['revision'])
                same=deepcopy(target);same['quote']['original']['value']='99'
                with self.assertRaisesRegex(ValueError,'equal_clock_price_conflict'):store.upsert_records([same])

    async def test_native_book_head_advancement_preserves_exact_evidence_and_blocks_execution(self):
        name = self.name + '_native'
        with self.connect('prediction_arb') as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            with self.connect(name) as db, patch('app.storage.current_rows.utc', return_value=AT):
                with patch('app.storage.store.ROOT', Path(ISOLATED_ROOT.name)):
                    Store(db).migrate()
                store = CurrentRowStore(db)
                records = fixture_records()
                target = next(r for r in records if r['quote']['venue'] == 'polymarket_us')
                source = target['quote']['source']
                book = next(o['book'] for e in envelopes() if e['record']['kind'] == 'admitted_books'
                            for o in e['record']['value']['observations']
                            if o['book']['raw']['ref']['market_id'] == source['native_market_id'])
                book.pop('book_confirmation')
                for record in records:
                    quote = record['quote']
                    if quote['venue'] == 'polymarket_us' and quote['source']['native_market_id'] == source['native_market_id']:
                        quote.pop('book_confirmation', None)
                store.upsert_records(records, now=AT)
                store.replace_native_books([book])
                linked = store.native_offer_books()[contract_id(target)]
                self.assertTrue(linked['is_current'])
                cache = PreparationCache()
                selection = Selection(venues=('polymarket_us',), sports=('football',),
                                      leagues=('NFL',), markets=('winner',))
                args = dict(config=DEFAULT, authority=GRANT, at=AT, selection=selection, cache=cache)
                key = ['polymarket_us', *[source[k] for k in
                       ('native_event_id', 'native_market_id', 'native_outcome_id', 'native_side')]]
                def observation():
                    response, inputs, _ = capture(db, **args)
                    self.assertEqual(response['failed_occurrences'], [])
                    instrument = next(i for i in response['instruments'] if i['native_key'] == key)
                    return instrument, inputs

                before, _ = observation()
                self.assertTrue(before['synchronized_depth'])
                self.assertEqual(before['checks']['execution'], {'state':'ready', 'reason_codes':[]})
                self.assertEqual(before['clocks']['book_at'], book['raw']['exchange_at'])
                self.assertEqual(before['clocks']['book_received_at'], book['raw']['received_at'])
                retained_levels = sum(row['n'] for row in native_offer_ask_counts(db))
                self.assertGreater(retained_levels, len(book['outcomes']))
                reservation = capture_reservation(db)
                proof = current_revision(db)
                receipt_only = deepcopy(book)
                receipt_only['raw']['received_at'] = '2026-10-14T01:14:50+00:00'
                store.replace_native_books([receipt_only])
                updated_proof = current_revision(db)
                self.assertEqual(updated_proof['current_rows_revision'], proof['current_rows_revision'])
                self.assertNotEqual(updated_proof['facts_revision'], proof['facts_revision'])
                receipt_superseded, receipt_inputs = observation()
                self.assertEqual(receipt_superseded['clocks'], before['clocks'])
                self.assertIn('book_revision_superseded', receipt_superseded['checks']['execution']['reason_codes'])
                self.assertNotIn(receipt_superseded['id'], receipt_inputs)

                newer = deepcopy(book)
                newer['raw'].update(exchange_at='2026-10-14T01:15:02+00:00',
                                    received_at='2026-10-14T01:15:03+00:00')
                for outcome in newer['outcomes']:
                    if outcome['asks'] is not None:
                        del outcome['asks']['levels'][1:]
                store.replace_native_books([newer])
                retained = store.native_offer_books()[contract_id(target)]
                self.assertEqual(retained['book_id'], linked['book_id'])
                self.assertFalse(retained['is_current'])
                self.assertEqual(sum(row['n'] for row in native_offer_ask_counts(db)), retained_levels)
                self.assertEqual(capture_reservation(db), reservation)

                after, inputs = observation()
                self.assertEqual(after['id'], before['id'])
                self.assertEqual(after['clocks'], before['clocks'])
                self.assertFalse(after['synchronized_depth'])
                self.assertIn('book_revision_superseded', after['checks']['execution']['reason_codes'])
                self.assertNotEqual(after['checks']['execution']['state'], 'ready')
                self.assertNotIn(after['id'], inputs)
                observed = next(q for bundle in ReadContext(Store(db), at=AT).observation_bundles()
                                for _, _, q in entries(bundle['state_inputs']) if q['source'] == source)
                depth = price(observed)['observed_depth']
                self.assertEqual(depth['book_revision'], linked['revision'])
                self.assertEqual(depth['source_at'], book['raw']['exchange_at'])
                self.assertEqual(depth['received_at'], book['raw']['received_at'])
                self.assertEqual(depth['total_levels'], len(target['quote']['depth']))
                self.assertEqual(depth['clock_basis'], 'native_book_revision')
        finally:
            with self.connect('prediction_arb') as db:
                db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    async def test_http_reads_use_existing_authority_and_never_settings_loader(self):
        provider=SimpleNamespace(closed=False,closing=False,dispatch=True,config=deepcopy(DEFAULT),states={v:dict(state='available') for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')})
        app=web.Application();mount(app,provider)
        client=TestClient(TestServer(app))
        with patch('app.dashboard.comparison_board_api.connect',self.connect),patch('app.dashboard.comparison_board_api.load',side_effect=AssertionError('No settings writer/loader')),patch('app.storage.current_rows.utc',return_value=AT):
            await client.start_server()
            try:
                a=await client.get('/api/boards/readiness?venues=kalshi,polymarket_us')
                self.assertEqual(a.status,200);body=await a.json()
                self.assertEqual(body['provider_requests'],0)
                self.assertEqual(body['selection']['venues'],['kalshi','polymarket_us'])
                self.assertEqual(body['evaluation']['state'],'not_evaluated')
                self.assertEqual(body['failed_occurrences'],[])
            finally:await client.close()
