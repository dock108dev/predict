"""Focused fixture qualification over a verified disposable PostgreSQL cluster.

Two authored events exercise the real SQL, projection and financial owners. No
production source/model authority is changed and no provider request is made.
"""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
from time import perf_counter
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.collection.current_policy import DEFAULT, GRANT
from app.collection.data_runtime import DataRuntime
from app.collection.local_ownership import LocalOwnership
from app.collection.runtime_client import RuntimeClient
from app.collection.runtime_status import RuntimeState, read_runtime
from app.dashboard.current_state import unavailable
from app.dashboard.scanner_api import Scanner, ScannerReader
from app.storage.current_rows import CurrentRowStore, contract_id
from app.storage.payload_codec import payload_row
from app.storage.scanner_publication import current_revision, transaction
from app.storage.store import Store
from tests.sc06_fixture import AuthoredAdapters, native_books, records
from tests.test_ev04_content import AT

SOCKET = os.environ.get('DA_TEST_PGSOCKET')


class FixtureClock:
    def __init__(self):self.at = AT
    def __call__(self):return self.at.isoformat()
    def advance(self, seconds=1):self.at += timedelta(seconds=seconds)


class FixtureService:
    """Finite source substitute: SQL admission is observable, transport is absent."""
    allow_synthetic = False
    database_mode = False

    def __init__(self):
        self.runtime_id = str(uuid4());self.config = deepcopy(DEFAULT)
        self.config['authority'] = GRANT
        self.states = {v:dict(state='available') for v in ('kalshi','polymarket_us','novig','prophetx')}
        self.dispatch = True;self.closed = False;self.closing = False
        self.cleanup_errors = [];self.workers = {};self.digest = 'fixture-only'
        self.starts = 0

    def initial_state(self):
        value = unavailable();value['runtime_id'] = self.runtime_id
        return value

    async def start(self, store):self.starts += 1;self.store = store
    async def close(self):self.closed = True;self.dispatch = False
    def status(self):return dict(runtime_id=self.runtime_id,candidate_digest=self.digest,issues=[],exclusions=[])


class InertScanner:
    def start(self):pass
    async def close(self):pass


@skipUnless(SOCKET, 'Explicit maintained disposable DA PostgreSQL lane required')
class SeparationSQL(IsolatedAsyncioTestCase):
    @classmethod
    def connect(cls, name=None):
        assert str(SOCKET).startswith('/tmp/predict-pg-'), 'Disposable cluster only'
        return psycopg.connect(host=SOCKET,port=55432,user='prediction_arb',
            dbname=name or cls.name,autocommit=True,row_factory=payload_row,connect_timeout=5)

    @classmethod
    def setUpClass(cls):
        cls.name = 'prediction_arb_da_' + uuid4().hex[:10]
        with cls.connect('prediction_arb') as db:
            assert str(db.execute('show data_directory').fetchone()['data_directory']).startswith('/tmp/predict-pg-')
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        with cls.connect() as db:Store(db).migrate()

    @classmethod
    def tearDownClass(cls):
        with cls.connect('prediction_arb') as db:
            db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))

    async def asyncSetUp(self):
        self.directory = TemporaryDirectory(prefix='predict-da-fixture-')
        fallback = patch('app.collection.runtime_client.load',return_value=deepcopy(DEFAULT))
        fallback.start();self.addCleanup(fallback.stop)
        self.clock = FixtureClock();self.service = FixtureService()
        self.state = RuntimeState(self.connect)
        with self.connect() as db:
            db.execute('TRUNCATE current_event CASCADE')
            db.execute('TRUNCATE current_source_status,current_refresh_scope,data_runtime,data_runtime_command,scanner_latest,latest_board,latest_board_status')
        self.state.write(self.service)
        self.rows = records(2,at=self.clock())
        self.admit(self.rows)

    async def asyncTearDown(self):self.directory.cleanup()

    def admit(self, rows):
        with self.connect() as db:
            with transaction(db):
                store = CurrentRowStore(db)
                store.upsert_records(rows,now=self.clock(),source_status=self.service.states)
                store.replace_native_books(native_books(rows))

    def scanner(self):
        return Scanner(self.service,connector=self.connect,clock=self.clock,durable=True,
            summary_path=Path(self.directory.name)/('summary-'+uuid4().hex))

    def drain(self, worker):
        for _ in range(8):
            worker.once()
            if not worker.projection.pending:return
        self.fail('Bounded two-event fixture did not settle')

    def latest(self):
        with self.connect() as db:return db.execute('SELECT * FROM scanner_latest WHERE singleton').fetchone()

    def assert_readable(self, reader):
        reader.start()
        self.assertFalse(reader.stopped(),getattr(reader,'unavailable_reason',None))

    async def test_sql_update_without_http_affected_reuse_restart_and_bounded_latest(self):
        worker = self.scanner()
        try:
            with AuthoredAdapters():
                self.drain(worker)
                original = deepcopy(worker.projection.rows)
                self.assertTrue(original, worker.projection.view())
                self.assertTrue(self.latest())
                from app.collection.current_storage_policy import sql_usage
                with self.connect() as db:self.assertGreater(sql_usage(db),0)
                # No app or HTTP object exists during admission/calculation.
                self.clock.advance()
                changed = deepcopy(self.rows[0])
                changed['quote']['original'].update(value='0.24',native_value='0.24')
                changed['quote']['depth'][0]['price'] = '0.24'
                changed['quote']['times'].update(source_at=self.clock(),received_at=self.clock())
                self.admit([changed]);self.drain(worker)
                after = deepcopy(worker.projection.rows)
                affected = unchanged = 0
                for key, before in original.items():
                    row = after[key]
                    if before['economic_revision'] == row['economic_revision']:
                        unchanged += 1
                        self.assertEqual(before['evaluated_at'],row['evaluated_at'])
                    else:affected += 1
                self.assertGreater(affected,0);self.assertGreater(unchanged,0)
                # Fresh app process state consumes only committed latest state.
                reader = ScannerReader(RuntimeClient(connector=self.connect),connector=self.connect,clock=self.clock)
                self.assert_readable(reader)
                self.assertEqual(reader.projection.rows,after)
                await reader.close()
                await worker.close()
                self.service.closed=False;self.service.dispatch=True
                worker=self.scanner();self.drain(worker)
                self.assertEqual({k:v['economic_revision'] for k,v in worker.projection.rows.items()},
                    {k:v['economic_revision'] for k,v in after.items()})
                self.assertEqual(worker.projection.evaluations,0)
                for _ in range(3):self.drain(worker)
                with self.connect() as db:
                    self.assertEqual(db.execute('SELECT count(*) n FROM scanner_latest').fetchone()['n'],1)
                    self.assertLess(db.execute('SELECT octet_length(payload::text) n FROM scanner_latest').fetchone()['n'],1024*1024)
        finally:await worker.close()

    async def test_dependency_removal_expiry_stop_dead_owner_and_late_publication(self):
        from app.storage.scanner_latest import publish
        worker=self.scanner();reader=ScannerReader(RuntimeClient(connector=self.connect),connector=self.connect,clock=self.clock)
        try:
            with AuthoredAdapters():
                self.drain(worker);self.assert_readable(reader)
                with self.connect() as db:proof=current_revision(db)
                revision=self.state.read()['revision']
                self.clock.advance()
                changed=deepcopy(self.rows[0]);changed['quote']['times'].update(source_at=self.clock(),received_at=self.clock())
                self.admit([changed])
                with self.connect() as db:self.assertFalse(publish(db,worker,proof=proof,runtime_revision=revision))
                reader.refresh();self.assertTrue(reader.stopped())
                self.drain(worker);reader.refresh();self.assertFalse(reader.stopped())
                with self.connect() as db:
                    with transaction(db):db.execute('DELETE FROM current_contract WHERE id=%s',(contract_id(changed),))
                reader.refresh();self.assertTrue(reader.stopped())
                self.drain(worker);reader.refresh()
                self.assertLess(len(reader.projection.rows),len(self.latest()['payload']['targets'])+1)
                self.clock.advance(901);reader.refresh();self.assertTrue(reader.stopped())
                self.clock.at=AT
                self.service.dispatch=False;self.state.write(self.service,global_stopped=True)
                reader.refresh();self.assertTrue(reader.stopped())
                with self.connect() as db:self.assertFalse(publish(db,worker,proof=current_revision(db),runtime_revision=revision))
                worker.once()
                stopped=self.latest()['payload']
                self.assertTrue(stopped['stopped']);self.assertFalse(stopped['rows'])
                self.assertFalse(stopped['receipts']);self.assertFalse(stopped['cache'])
                self.service.dispatch=True;self.state.write(self.service)
                with self.connect() as db:
                    db.execute("UPDATE data_runtime SET heartbeat_at=clock_timestamp()-interval '9 seconds'")
                    self.assertFalse(read_runtime(db)['healthy'])
                reader.refresh();self.assertTrue(reader.stopped())
        finally:await reader.close();await worker.close()

    async def test_live_source_status_clock_changes_bind_committed_runtime_and_sql_stop(self):
        """A source may advance between runtime heartbeats; only SQL is shared."""
        from app.comparison.scanner_tickets import selector
        worker=self.scanner();reader=ScannerReader(RuntimeClient(connector=self.connect),connector=self.connect,clock=self.clock)
        try:
            with AuthoredAdapters():
                self.drain(worker);self.assert_readable(reader)
                original=self.state.read();old_rows=deepcopy(reader.projection.rows)
                self.clock.advance()
                self.service.states['kalshi'].update(source_at=self.clock(),received_at=self.clock(),
                    reason_code='native_available',reason='Fixture source clock advanced between runtime heartbeats.')
                changed=deepcopy(self.rows[0]);changed['quote']['original'].update(value='0.24',native_value='0.24')
                changed['quote']['depth'][0]['price']='0.24'
                changed['quote']['times'].update(source_at=self.clock(),received_at=self.clock())
                # Actual ingress commits its newest source status with the quote,
                # while the separate compact runtime heartbeat still has old clocks.
                self.admit([changed])
                self.assertEqual(self.state.read()['revision'],original['revision'])
                self.assertEqual(self.state.read()['states'],original['states'])
                self.drain(worker);self.assert_readable(reader)
                self.assertNotEqual(reader.projection.rows,old_rows)
                native=next(row for row in reader.projection.rows.values() if 'kalshi' in row['venues'])
                bound=selector(reader.projection,native)
                _,selected_inputs=reader._selection_snapshot(bound)
                self.assertTrue(selected_inputs)
                with self.connect() as db:
                    committed=db.execute("SELECT state FROM current_source_status WHERE venue='kalshi'").fetchone()['state']
                    self.assertEqual(committed,self.service.states['kalshi'])
                    with transaction(db):
                        CurrentRowStore(db).upsert_records([],source_status=dict(kalshi=dict(
                            state='stopped',reason_code='native_stopped',reason='Fixture source Stop.')),now=self.clock())
                # The old runtime snapshot still says available. The newer SQL
                # Stop must immediately invalidate old publication/selection.
                self.assertEqual(self.state.read()['states']['kalshi']['state'],'available')
                reader.refresh();self.assertTrue(reader.stopped())
                self.drain(worker);self.assert_readable(reader)
                self.assertTrue(all('kalshi' not in row['venues'] for row in reader.projection.rows.values()))
                frame,_=reader._capture_selected(dict(inputs=selected_inputs))
                self.assertFalse(any(pair['input_check']['state']=='ready' for pair in frame['pairs']))
        finally:await reader.close();await worker.close()

    async def test_app_lifecycle_duplicate_owners_and_acknowledged_stop(self):
        service=FixtureService();owner_path=Path(self.directory.name)/'owner'
        runtime=DataRuntime(service,connector=self.connect,owner=LocalOwnership(owner_path),
            scanner_factory=lambda service:InertScanner())
        # No retained Stop from another test, and no production service/adapters.
        await runtime.start()
        duplicate=DataRuntime(FixtureService(),connector=self.connect,
            owner=LocalOwnership(Path(self.directory.name)/'other-owner'),scanner_factory=lambda service:InertScanner())
        try:
            with self.connect() as db:epoch=db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch']
            identity=service.runtime_id
            for _ in range(2):
                app=RuntimeClient(connector=self.connect)
                await app.start(None);await app.close()
                self.assertEqual(self.state.read()['runtime_id'],identity)
                with self.connect() as db:self.assertEqual(db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch'],epoch)
            with self.assertRaisesRegex(ValueError,'owns this database'):await duplicate.start()
            self.assertEqual(service.starts,1)
            self.assertTrue(runtime.state.read()['active'])
            proxy=RuntimeClient(connector=self.connect)
            acknowledgment=await proxy.stop()
            self.assertTrue(acknowledgment['acknowledged'])
            self.assertEqual(acknowledgment['runtime_id'],identity)
            self.assertFalse(runtime.state.read()['active'])
            self.assertTrue(runtime.state.read()['global_stopped'])
            await proxy.close()
        finally:await runtime.close()

    async def test_http_scanner_filter_poll_reads_do_not_evaluate_or_dispatch(self):
        from app.dashboard.scanner_api import mount
        worker=self.scanner()
        try:
            with AuthoredAdapters():
                self.drain(worker)
                app=web.Application();proxy=RuntimeClient(connector=self.connect)
                reader=mount(app,proxy);reader.connector=self.connect;reader.clock=self.clock;reader.projection.clock=self.clock
                reader.projection.evaluator=lambda *a,**k:self.fail('HTTP evaluated whole slate')
                client=TestClient(TestServer(app));await client.start_server()
                try:
                    with patch('app.comparison.scanner_projection.evaluate',side_effect=AssertionError('HTTP evaluated slate')), \
                         patch('app.storage.comparison_board.calculate_current',side_effect=AssertionError('HTTP board finance')), \
                         patch('app.collection.current_service.CurrentService.start',side_effect=AssertionError('HTTP started provider')):
                        for query in ('','?limit=1','?venues=kalshi','?minimum_edge=0','?offset=0&limit=2'):
                            result=await client.get('/api/scanner'+query)
                            self.assertEqual(result.status,200)
                            value=await result.json();self.assertEqual(value['provider_requests'],0)
                            self.assertTrue(value['rows'] or query=='?venues=kalshi')
                    self.assertEqual(self.service.starts,0)
                finally:await client.close()
        finally:await worker.close()

    async def process(self, role, started):
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.da_process',role,
            '--socket',SOCKET,'--database',self.name,'--directory',self.directory.name,
            '--fixture-start',str(started),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        line=await asyncio.wait_for(process.stdout.readline(),timeout=15)
        if not line:
            error=await process.stderr.read()
            self.fail(error.decode())
        return process,json.loads(line)

    async def terminate(self, process):
        if process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(),timeout=15)
        error=await process.stderr.read()
        if error and os.environ.get('PREDICT_CI_REPORT_ROOT'):
            Path(os.environ['PREDICT_CI_REPORT_ROOT'],f'fixture-process-{process.pid}.log').write_bytes(error)
        self.assertEqual(process.returncode,0,error.decode())

    async def wait_latest(self, runtime_id):
        for _ in range(100):
            latest=self.latest()
            if latest and latest['runtime_id']==runtime_id and latest['payload']['rows']:
                return latest
            await asyncio.sleep(.05)
        self.fail('Independent fixture data owner did not publish latest SQL')

    async def test_cross_process_app_absent_restart_duplicate_and_worker_reconcile(self):
        with self.connect() as db:
            db.execute('TRUNCATE current_event CASCADE')
            db.execute('CREATE TABLE da_fixture_dispatch(runtime_id text PRIMARY KEY,dispatched integer NOT NULL)')
        started=perf_counter();data=app=None
        try:
            data,identity=await self.process('data',started)
            original=await self.wait_latest(identity['runtime_id'])
            with self.connect() as db:epoch=db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch']
            # Data has already admitted and calculated before the first app exists.
            app,first=await self.process('app',started);await self.terminate(app);app=None
            app,second=await self.process('app',started)
            self.assertNotEqual(first['url'],second['url'])
            self.assertEqual(self.state.read()['runtime_id'],identity['runtime_id'])
            with self.connect() as db:self.assertEqual(db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch'],epoch)
            duplicate=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.da_process','data',
                '--socket',SOCKET,'--database',self.name,'--directory',self.directory.name,
                '--fixture-start',str(started),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            _,error=await asyncio.wait_for(duplicate.communicate(),timeout=15)
            self.assertNotEqual(duplicate.returncode,0);self.assertIn(b'owns native acquisition',error)
            await self.terminate(app);app=None
            await self.terminate(data);data=None
            data,restarted=await self.process('data',started)
            again=await self.wait_latest(restarted['runtime_id'])
            self.assertEqual({k:r['economic_revision'] for k,r in original['payload']['rows'].items()},
                {k:r['economic_revision'] for k,r in again['payload']['rows'].items()})
            with self.connect() as db:
                self.assertEqual(db.execute('SELECT sum(dispatched) n FROM da_fixture_dispatch').fetchone()['n'],1)
                self.assertEqual(db.execute('SELECT count(*) n FROM scanner_latest').fetchone()['n'],1)
            # An abrupt OS death leaves retained rows but loses authority within
            # the real eight-second heartbeat bound, without another app write.
            death_started=perf_counter();data.kill();await asyncio.wait_for(data.wait(),timeout=5);data=None
            for _ in range(90):
                if not self.state.read()['healthy']:break
                await asyncio.sleep(.1)
            self.assertFalse(self.state.read()['active'])
            death_seconds=perf_counter()-death_started
            self.assertLess(death_seconds,9.5)
            reader=ScannerReader(RuntimeClient(connector=self.connect),connector=self.connect,clock=self.clock)
            reader.start();self.assertTrue(reader.stopped());await reader.close()
            receipt=dict(evidence_class='Fixture only: two authored events, real disposable PostgreSQL, separate OS data/app processes, zero provider requests.',
                app_absent_publication=original['publication'],collector_runtime_id=identity['runtime_id'],
                app_restart_preserved_runtime=True,app_restart_preserved_epoch=epoch,
                duplicate_start_rejected=True,finite_fixture_admissions=1,
                worker_restart_runtime_id=restarted['runtime_id'],worker_restart_preserved_economics=True,
                latest_scanner_rows=1,dead_owner_authority_withdrawn_seconds=death_seconds,
                provider_requests=0)
            Path(os.environ['PREDICT_CI_REPORT_ROOT'],'working-loop.json').write_text(json.dumps(receipt,indent=2)+'\n')
        finally:
            if app:await self.terminate(app)
            if data:await self.terminate(data)
            with self.connect() as db:db.execute('DROP TABLE da_fixture_dispatch')

    @skipUnless(os.environ.get('DA_BROWSER')=='1','Opt-in focused DA Chromium walkthrough')
    async def test_focused_desktop_and_390px_browser(self):
        root=Path(__file__).resolve().parents[1]
        report=Path(os.environ['PREDICT_CI_REPORT_ROOT'])/'browser'
        report.mkdir(parents=True,exist_ok=True)
        # Independent data and app processes communicate only through SQL.
        with self.connect() as db:
            db.execute('TRUNCATE current_event CASCADE')
            db.execute('CREATE TABLE da_fixture_dispatch(runtime_id text PRIMARY KEY,dispatched integer NOT NULL)')
        data=app=None;started=perf_counter()
        try:
            data,identity=await self.process('data',started)
            await self.wait_latest(identity['runtime_id'])
            app,location=await self.process('app',started)
            process=await asyncio.create_subprocess_exec('node',str(root/'browser_tests/da_separation.cjs'),
                location['url'],str(report),cwd=root,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
            output,_=await asyncio.wait_for(process.communicate(),timeout=100)
            (report/'browser.log').write_bytes(output)
            self.assertEqual(process.returncode,0,output.decode())
            with self.connect() as db:self.assertEqual(db.execute('SELECT sum(dispatched) n FROM da_fixture_dispatch').fetchone()['n'],1)
        finally:
            if app:await self.terminate(app)
            if data:await self.terminate(data)
            with self.connect() as db:db.execute('DROP TABLE da_fixture_dispatch')
