"""Actual lock contention and local-only retries in a disposable database."""
import asyncio
from threading import Event
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from app.collection.current_database import DatabaseIngressSink
from app.collection.current_policy import DEFAULT
from app.storage.current_rows import LOCK
from tests import test_sc02_sql as base
SOCKET=base.SOCKET
from tests.test_d03_current_rows import fixture_records
from tests.test_ev09_n01 import AT


@skipUnless(SOCKET, 'Disposable SQL harness required')
class LockRecovery(IsolatedAsyncioTestCase):
    connect = classmethod(base.SQL.connect.__func__)
    setUpClass = classmethod(base.SQL.setUpClass.__func__)
    tearDownClass = classmethod(base.SQL.tearDownClass.__func__)

    def test_packed_images_survive_catalog_reannotation_and_failed_candidate(self):
        from copy import deepcopy
        from tests.test_current_service import native_fixture
        cat,book=native_fixture()
        sink=DatabaseIngressSink(None,DEFAULT)
        sink.reducer.inventory={'kalshi':cat}
        observation=dict(type='prediction_book',source='kalshi',book=book,
                         observed_at=book['raw']['received_at'],packets=[])
        row=dict(type='prediction_books',source='kalshi',observations=[observation])
        key=('kalshi',book['raw']['ref']['event_id'],book['raw']['ref']['market_id'])
        with patch('app.collection.current_database.connect',side_effect=self.connect):
            candidate,_,_=sink.prepare(row,{})
            self.assertNotIn(key,sink.reducer.books)
            sink.reducer=candidate
            encoded=candidate.books.encoded[key]
            # Canonical annotation can change while physical source terms stay identical.
            revised=deepcopy(cat);revised['events'][0]['stage']='annotation-update'
            catalog=dict(type='coverage_inventory',source='kalshi',inventory={'kalshi':revised},
                         generation=1,previous_generation=None,observed_at=book['raw']['received_at'])
            candidate,_,_=sink.prepare(catalog,{})
            self.assertEqual(candidate.books[key],observation)
            self.assertIs(candidate.books.encoded[key],encoded)
            bad=deepcopy(row);bad['observations'][0]['book']['sync']='unsynchronized'
            with self.assertRaises(ValueError):sink.prepare(bad,{})
            self.assertIs(sink.reducer.books.encoded[key],encoded)

    def test_process_normalization_commits_same_exact_sql_image(self):
        from tests.test_current_service import native_fixture
        from app.storage.store import hashed
        from app.storage.current_rows import CurrentRowStore
        cat,book=native_fixture()
        binding=cat['markets'][0]['v1_raw_binding']
        binding['sha256']=hashed({k:v for k,v in binding.items() if k!='sha256'})
        row=dict(type='prediction_books',source='kalshi',observations=[dict(
            type='prediction_book',source='kalshi',book=book,
            observed_at=book['raw']['received_at'],packets=[])])
        direct=DatabaseIngressSink(None,DEFAULT)
        worker=DatabaseIngressSink(None,DEFAULT,process_normalization=True)
        try:
            with patch('app.collection.current_database.connect',side_effect=self.connect), \
                    patch('app.collection.current_database.utc',return_value=book['raw']['received_at']):
                direct.reducer.inventory=worker.reducer.inventory={'kalshi':cat}
                direct.prepare(row,{})
                with self.connect() as db:expected=CurrentRowStore(db).capture()
                computed=worker.precompute_books('kalshi',[book],Event())
                worker.prepare(row,{},precomputed=computed)
                with self.connect() as db:actual=CurrentRowStore(db).capture()
                self.assertEqual(actual,expected)
                self.assertEqual(worker.metrics['precomputed_admissions'],1)
                self.assertGreater(worker.metrics['recent_preparations'][-1]['records'],0)
                # Neither a stale catalog nor crossing a phase boundary may use
                # the authored empty result as current calculation authority.
                stale=dict(computed,records=[],generation='retired')
                worker.prepare(row,{},precomputed=stale)
                self.assertGreater(worker.metrics['recent_preparations'][-1]['records'],0)
                stale=dict(computed,records=[],next_phase_at=book['raw']['received_at'])
                worker.prepare(row,{},precomputed=stale)
                self.assertGreater(worker.metrics['recent_preparations'][-1]['records'],0)
                self.assertEqual(worker.metrics['precomputed_generation_retries'],2)
        finally:worker.close()

    async def test_retry_same_received_image_and_stop(self):
        records=fixture_records()
        row=dict(type='current_aggregate_records',source='the_odds_api',sport='NFL',
                 records=records,complete_venues=[],received_at=AT)
        sink=DatabaseIngressSink(None,DEFAULT)
        sink.finish=lambda prepared,states: prepared
        def connection():
            db=self.connect();db.execute("SET lock_timeout='30ms'");return db
        with self.connect() as blocker, patch('app.collection.current_database.connect',side_effect=connection), \
                patch('app.collection.current_database.utc',return_value=AT):
            blocker.execute('SELECT pg_advisory_lock(%s)',(LOCK,))
            task=asyncio.create_task(sink.commit_async(row,{},Event()))
            for _ in range(100):
                if sink.metrics.get('transaction_retries'):break
                await asyncio.sleep(.02)
            self.assertGreater(sink.metrics.get('transaction_retries',0),0)
            self.assertFalse(task.done())
            self.assertEqual(sink.metrics['rejected_observations'],0)
            blocker.execute('SELECT pg_advisory_unlock(%s)',(LOCK,))
            await asyncio.wait_for(task,5)
            with self.connect() as db:
                receipts=db.execute('SELECT received_at FROM current_offer').fetchall()
                self.assertTrue(receipts)
                expected={r['quote']['times']['received_at'] for r in records}
                self.assertTrue(all(r['received_at'] in expected for r in receipts))
            blocker.execute('SELECT pg_advisory_lock(%s)',(LOCK,))
            revoked=Event();before=sink.metrics['transaction_retries']
            task=asyncio.create_task(sink.commit_async(row,{},revoked))
            for _ in range(100):
                if sink.metrics['transaction_retries']>before:break
                await asyncio.sleep(.02)
            revoked.set()
            with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,5)
            blocker.execute('SELECT pg_advisory_unlock(%s)',(LOCK,))

    async def test_single_book_does_not_renormalize_unchanged_sibling_markets(self):
        from copy import deepcopy
        from tests.test_current_service import native_fixture
        cat,book=native_fixture()
        cat=deepcopy(cat)
        original=cat['markets'][0]
        cat['markets'].extend(dict(deepcopy(original),id='unchanged-'+str(i)) for i in range(1000))
        sink=DatabaseIngressSink(None,DEFAULT)
        sink.reducer.inventory={'kalshi':cat}
        row=dict(type='prediction_books',source='kalshi',observations=[dict(type='prediction_book',source='kalshi',book=book,observed_at=book['raw']['received_at'],packets=[])])
        with patch('app.collection.current_database.connect',side_effect=self.connect), \
                patch('app.comparison.combined_native.normalize',return_value=([],[])) as normalize:
            sink.prepare(row,{})
        inventory=normalize.call_args.args[0]['record']['value']['inventory']
        self.assertEqual([m['id'] for m in inventory['markets']],[book['raw']['ref']['market_id']])
        self.assertEqual(len(sink.reducer.inventory['kalshi']['markets']),1001)

    def test_capture_only_catalog_preserves_images_without_calculation(self):
        from copy import deepcopy
        from tests.test_current_service import native_fixture
        cat,book=native_fixture();sink=DatabaseIngressSink(None,DEFAULT)
        sink.reducer.inventory={'kalshi':cat}
        observation=dict(type='prediction_book',source='kalshi',book=book,
                         observed_at=book['raw']['received_at'],packets=[])
        key=('kalshi',book['raw']['ref']['event_id'],book['raw']['ref']['market_id'])
        sink.reducer.books[key]=observation
        original=sink.reducer.books.encoded[key]
        revised=deepcopy(cat);revised['markets'][0]['provenance']=[dict(received_at='new capture')]
        row=dict(type='coverage_inventory',source='kalshi',inventory={'kalshi':revised},
                 generation=1,previous_generation=None,observed_at=book['raw']['received_at'])
        with patch('app.collection.current_database.connect',side_effect=self.connect), \
                patch('app.comparison.combined_native.normalize') as normalize:
            candidate,_,_=sink.prepare(row,{})
            normalize.assert_not_called()
        self.assertIs(candidate.books.encoded[key],original)
        self.assertEqual(sink.metrics['catalog_delta'],dict(retained=1,withdrawn=0,recalculated=0))

    def test_changed_comparison_catalog_defers_math_and_keeps_exact_image(self):
        from copy import deepcopy
        from tests.test_current_service import native_fixture
        from app.collection.current_catalog_delta import changes
        cat,book=native_fixture();sink=DatabaseIngressSink(None,DEFAULT)
        sink.reducer.inventory={'kalshi':cat}
        key=('kalshi',book['raw']['ref']['event_id'],book['raw']['ref']['market_id'])
        sink.reducer.books[key]=dict(type='prediction_book',source='kalshi',book=book,
                                    observed_at=book['raw']['received_at'],packets=[])
        original=sink.reducer.books.encoded[key]
        revised=deepcopy(cat);revised['events'][0]['stage']='new evidence'
        inventory={'kalshi':revised};delta=changes(sink.reducer.inventory,inventory)
        row=dict(type='coverage_inventory',source='kalshi',inventory=inventory,catalog_delta=delta,
                 defer_catalog_refresh=True,generation=1,previous_generation=None,observed_at=book['raw']['received_at'])
        with patch('app.collection.current_database.connect',side_effect=self.connect), \
                patch('app.comparison.combined_native.normalize') as normalize:
            candidate,_,_=sink.prepare(row,{})
            normalize.assert_not_called()
        self.assertIs(candidate.books.encoded[key],original)
        self.assertEqual(sink.metrics['catalog_delta']['deferred'],1)
