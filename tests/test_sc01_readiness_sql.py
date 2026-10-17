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
from app.storage.current_rows import CurrentRowStore
from app.storage.scanner_readiness import read
from app.collection.current_policy import DEFAULT, GRANT
from app.dashboard.comparison_board_api import mount
from tests.test_d03_current_rows import fixture_records
from tests.test_ev09_n01 import AT

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
            CurrentRowStore(db).upsert_records(fixture_records())

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

    async def test_older_and_unknown_observations_cannot_replace_known(self):
        with self.connect() as db:
            store=CurrentRowStore(db)
            with patch('app.storage.current_rows.utc',return_value=AT):
                before=store.capture()
                records=store.capture()['records'];target=next(r for r in records if r['quote']['times']['source_at'])
                for clock in ('2020-01-01T00:00:00Z',None):
                    changed=deepcopy(target);changed['quote']['times'].update(source_at=clock,received_at=AT);changed['quote']['original']['value']='99'
                    store.upsert_records([changed])
                    self.assertEqual(before['revision'],store.capture()['revision'])
                same=deepcopy(target);same['quote']['original']['value']='99'
                with self.assertRaisesRegex(ValueError,'equal_clock_price_conflict'):store.upsert_records([same])

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
