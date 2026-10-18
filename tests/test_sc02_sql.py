"""Dedicated disposable-cluster integration; never migrates an owner database."""
import tempfile
ROOT = tempfile.TemporaryDirectory(prefix='predict-sc02-sql-')
import os
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
import psycopg
from psycopg import sql
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from app.storage.payload_codec import payload_row
from app.storage.store import Store
from app.storage.current_rows import CurrentRowStore
from app.storage.scanner_readiness import capture,read
from app.storage.scanner_publication import transaction,subscribe,lookup
from app.dashboard.scanner_api import Scanner,mount
from app.collection.current_policy import DEFAULT,GRANT
from tests.test_d03_current_rows import fixture_records
from tests.test_ev09_n01 import AT

SOCKET=os.environ.get('SC02_TEST_PGSOCKET')


@skipUnless(SOCKET,'Explicit separate disposable SC02 cluster required')
class SQL(IsolatedAsyncioTestCase):
    @classmethod
    def connect(cls,name=None):
        assert str(SOCKET).startswith(('/tmp/predict-sc02-pg-','/tmp/predict-pg-')), 'separate disposable cluster only'
        return psycopg.connect(host=SOCKET,port=55432,user='prediction_arb',dbname=name or cls.name,
            autocommit=True,row_factory=payload_row,connect_timeout=5)

    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_sc02_'+uuid4().hex[:10]
        with cls.connect('prediction_arb') as db:
            cls.cluster=db.execute('show data_directory').fetchone()['data_directory']
            assert str(cls.cluster).startswith(('/tmp/predict-sc02-pg-','/tmp/predict-pg-'))
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        with cls.connect() as db:
            assert db.execute('select current_database() name').fetchone()['name']==cls.name
            with patch('app.storage.store.ROOT',Path(ROOT.name)):Store(db).migrate()
            CurrentRowStore(db).upsert_records(fixture_records())

    @classmethod
    def tearDownClass(cls):
        with cls.connect('prediction_arb') as db:
            db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))

    def provider(self):
        config=deepcopy(DEFAULT);config['authority']=GRANT
        return SimpleNamespace(closed=False,closing=False,dispatch=True,config=config,states={})

    async def test_detached_repeatable_read_and_read_v1_unchanged(self):
        with self.connect() as db:
            with patch('app.storage.current_rows.utc',return_value=AT):
                frame,inputs,metadata=capture(db,config=DEFAULT,authority=GRANT,at=AT)
                self.assertEqual(frame,read(db,config=DEFAULT,authority=GRANT,at=AT))
            self.assertEqual(db.info.transaction_status,psycopg.pq.TransactionStatus.IDLE)
            self.assertEqual(frame['provider_requests'],0)
            self.assertTrue(inputs);self.assertTrue(metadata['current_rows_revision'])
            self.assertFalse(frame['evaluation']['no_qualifying_opportunities'])

    async def test_true_post_commit_revision_and_nested_rollback_unknown(self):
        seen=[];close=subscribe(seen.append)
        try:
            with self.connect() as db:
                with transaction(db):
                    db.execute('update current_row_epoch set epoch=%s where singleton=true',(uuid4().hex,))
                    self.assertEqual(seen,[])
                self.assertEqual(len(seen),1)
                with patch('app.storage.current_rows.utc',return_value=AT):revision=CurrentRowStore(db).capture()['revision']
                self.assertEqual(seen[0]['current_rows_revision'],revision)
                self.assertEqual(lookup(revision),seen[0])
                with self.assertRaises(ValueError):
                    with transaction(db):
                        db.execute('update current_row_epoch set epoch=%s where singleton=true',(uuid4().hex,))
                        raise ValueError('authored rollback')
                self.assertEqual(len(seen),1)
                with db.transaction():
                    with transaction(db):db.execute('select 1')
                self.assertEqual(len(seen),1)
        finally:close()

    async def test_scanner_worker_capture_finance_after_release_stop_and_failure(self):
        worker=Scanner(self.provider(),connector=self.connect,clock=lambda:AT)
        from tests.test_sc02_projection import frame as authored_frame, fake
        original_capture=worker._capture
        calls=[]
        connections=[]
        from contextlib import contextmanager
        @contextmanager
        def tracked_connector():
            with self.connect() as db:
                connections.append(db)
                yield db
        worker.connector=tracked_connector
        def controlled_capture():
            real,_,metadata,elapsed=original_capture()
            # Explicit authored ready partition substitutes only the test input;
            # SQL capture/connection release and the worker path remain actual.
            authored,inputs=authored_frame()
            return authored,inputs,metadata,elapsed
        def finance(*args,**kw):
            self.assertTrue(connections)
            self.assertTrue(all(db.closed for db in connections))
            calls.append(True)
            return fake(*args,**kw)
        worker._capture=controlled_capture
        worker.projection.evaluator=finance
        with patch('socket.socket.connect',side_effect=AssertionError('No provider requests')):
            worker.once()
        self.assertEqual(len(calls),1)
        v=worker.projection.view()
        self.assertIn(v['coverage']['state'],('unavailable','partial','incomplete','not_evaluated','evaluated_zero','evaluated_positive'))
        self.assertEqual(v['provider_requests'],0)
        worker.provider.dispatch=False;worker.once()
        self.assertEqual(worker.projection.view()['coverage']['state'],'stopped')
        await worker.close()

    async def test_http_only_server_authored_receipts_and_bounded_protocol(self):
        app=web.Application();provider=self.provider()
        worker=mount(app,provider);worker.connector=self.connect;worker.clock=lambda:AT;worker.projection.clock=lambda:AT
        client=TestClient(TestServer(app));await client.start_server()
        try:
            for query in ('?receipts=forged','?evaluated_at=2027','?amount=1000','?venues=pinnacle','?limit=101'):
                r=await client.get('/api/scanner'+query);self.assertEqual(r.status,400)
            r=await client.get('/api/scanner?limit=2');self.assertEqual(r.status,200)
            body=await r.json();self.assertEqual(body['version'],'predict-opportunity-scanner-1')
            self.assertLessEqual(len(body['rows']),2);self.assertEqual(body['provider_requests'],0)
            provider.dispatch=False
            r=await client.get('/api/scanner');self.assertEqual((await r.json())['coverage']['state'],'stopped')
        finally:await client.close()

    async def test_sql_probe_failure_rolls_back_only_measurement_savepoint(self):
        seen=[];close=subscribe(seen.append)
        try:
            with self.connect() as db:
                epoch=uuid4().hex
                def broken_probe(connection):connection.execute('SELECT 1 / 0')
                with patch('app.storage.scanner_publication.prepare',side_effect=broken_probe):
                    with self.assertLogs('app.storage.scanner_publication',level='ERROR'):
                        with transaction(db):
                            db.execute('update current_row_epoch set epoch=%s where singleton=true',(epoch,))
                self.assertEqual(db.execute('select epoch from current_row_epoch').fetchone()['epoch'],epoch)
                self.assertEqual(seen,[])
                with transaction(db):db.execute('SELECT 1')
                self.assertEqual(len(seen),1)
        finally:close()

    async def test_probe_capacity_and_measurement_failure_do_not_abort_ingress(self):
        from unittest.mock import MagicMock
        from app.storage.scanner_publication import current_revision
        fake=MagicMock()
        fake.execute.side_effect=[SimpleNamespace(fetchone=lambda:dict(epoch='authored')),
            SimpleNamespace(fetchall=lambda:[{}]*16385),SimpleNamespace(fetchall=lambda:[])]
        with self.assertRaisesRegex(ValueError,'revision_probe_capacity'):current_revision(fake)
        seen=[];close=subscribe(seen.append)
        try:
            with self.connect() as db:
                epoch=uuid4().hex
                with patch('app.storage.scanner_publication.prepare',side_effect=ValueError('authored measurement failure')):
                    with transaction(db):db.execute('update current_row_epoch set epoch=%s where singleton=true',(epoch,))
                self.assertEqual(db.execute('select epoch from current_row_epoch').fetchone()['epoch'],epoch)
                self.assertEqual(seen,[])
        finally:close()
