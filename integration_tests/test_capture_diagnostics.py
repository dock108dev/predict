"""Real transaction readback for the diagnostic ledger, never owner storage."""
import asyncio
import unittest
import uuid
from unittest.mock import patch
from psycopg import sql
from app.storage import Store,connect
from app.dashboard.controller import DEFAULTS
from app.dashboard.diagnostics import Measurements,reconcile
from app.capture_benchmark import DiagnosticPipeline,fixture,trial


class CaptureDiagnosticStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_diagnostic_test_'+uuid.uuid4().hex[:8]
        with connect() as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        with connect(cls.name) as db:Store(db).migrate()
    @classmethod
    def tearDownClass(cls):
        with connect() as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
    def connector(self,ignored=None):return connect(self.name)
    def prepared(self):
        m=Measurements();p=DiagnosticPipeline('synthetic',dict(DEFAULTS),self.name,m,self.connector,2)
        p.start();p.parents,p.matcher,p.contexts,p.rows,books=fixture(2)
        p.titles={r['key']:r['native']['title'] for r in p.rows}
        m.active='book-under-test';m.items=[dict(id=m.active,accepted=True,processed=False)]
        return m,p,books[0]
    def readback(self,m,p):
        with self.connector() as db:
            ids=lambda table:[r['id'] for r in db.execute(sql.SQL('SELECT id FROM {} WHERE session_id=%s').format(sql.Identifier(table)),(p.sid,)).fetchall()]
            n=db.execute('SELECT count(*) n FROM quote_observation WHERE session_id=%s',(p.sid,)).fetchone()['n']
            return reconcile(m,ids('receipt'),ids('calculation'),ids('coverage_event'),n)
    def test_second_side_failure_rolls_back_returned_first_side(self):
        m,p,book=self.prepared();p.fail_side=2
        try:
            with self.assertRaises(RuntimeError):p.book(book)
            r=self.readback(m,p)
            self.assertEqual(r['counts']['attempted_receipt_writes'],2)
            self.assertEqual(r['counts']['committed_receipts'],0)
            self.assertEqual(p.receipts,0)
            self.assertEqual(p.books,{})
            self.assertEqual(p.current_receipts,{})
            self.assertTrue(r['bindings'][0]['returned'])
            self.assertFalse(r['bindings'][0]['committed'])
            self.assertTrue(all(r['gates'].values()))
        finally:p.finish('injected rollback test',0,True)
    def test_evaluation_failure_preserves_committed_receipts_as_partial_work(self):
        m,p,book=self.prepared()
        try:
            with patch.object(p,'evaluate',side_effect=RuntimeError('injected evaluate failure')):
                with self.assertRaises(RuntimeError):p.book(book)
            r=self.readback(m,p)
            self.assertEqual(r['counts']['committed_receipts'],2)
            self.assertEqual(r['counts']['unprocessed'],1)
            self.assertTrue(all(r['gates'].values()))
        finally:p.finish('partial item test',0,True)
    def test_real_storage_expected_overflow_both_market_limits(self):
        for n in (2,4):
            result=asyncio.run(trial(self.connector,n,'overflow40'))
            self.assertTrue(result['gates_pass'],result['accounting'])
            self.assertTrue(result['burst_preserved'])
            self.assertEqual(result['remaining_queue'],0)
            self.assertEqual(result['saved_state']['state'],'complete')
            self.assertEqual(result['accounting']['counts']['rejected'],0)
            self.assertEqual(result['accounting']['counts']['processed'],41)
            self.assertEqual(result['accounting']['counts']['unprocessed'],0)
    def test_receipt_limit_on_second_side_is_atomic(self):
        m,p,book=self.prepared();p.limits={**p.limits,'receipts':1}
        try:
            with self.assertRaises(OverflowError):p.book(book)
            self.assertEqual(p.receipts,0);self.assertEqual(p.raw_bytes,0)
            self.assertEqual(p.observations,{});self.assertEqual(p.books,{})
            self.assertEqual(self.readback(m,p)['counts']['committed_receipts'],0)
        finally:p.finish('limit',1,True)
    def test_view_rollback_does_not_advance_sequence_or_poison_artifacts(self):
        m,p,book=self.prepared();p.defer_views=True
        try:
            p.book(book);before=p.seq
            original=p.store.metadata
            with patch.object(p.store,'metadata',side_effect=RuntimeError('rollback view')):
                with self.assertRaises(RuntimeError):p.evaluate()
            self.assertEqual(p.seq,before)
            self.assertEqual(self.readback(m,p)['counts']['committed_receipts'],2)
            view=p.evaluate();self.assertEqual(view['sequence'],before+1)
            with self.connector() as db:
                self.assertGreaterEqual(Store(db).replay_all(),1)
        finally:p.finish('view rollback',0)
    def test_calculation_envelope_uses_same_validated_snapshot(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import json
        parents,matcher,_,_,_=fixture(4)
        with TemporaryDirectory() as folder:
            for n,obj in enumerate((parents,matcher)):
                path=Path(folder)/str(n);obj.save(path)
                self.assertEqual(obj.envelope(),json.loads(path.read_text()))

    def test_detached_calculation_keeps_exact_committed_receipts_during_capture(self):
        from concurrent.futures import ThreadPoolExecutor
        from dataclasses import replace
        from datetime import datetime,timezone,timedelta
        from app.dashboard.refresh import compute,thaw_result
        from app.storage.replay import replay
        m,p,book=self.prepared();p.defer_views=True
        try:
            p.book(book);snapshot=p.snapshot();old_ids=set(p.current_receipts.values())
            original_times={o.quote.raw.received_at for o in p.observations.values()}
            with ThreadPoolExecutor(max_workers=1) as executor:
                calculation=executor.submit(compute,snapshot)
                newer=replace(book,raw=replace(book.raw,received_at=datetime.now(timezone.utc)+timedelta(milliseconds=1)))
                p.book(newer);new_ids=set(p.current_receipts.values())
                result=calculation.result()
            self.assertTrue(old_ids.isdisjoint(new_ids))
            data=thaw_result(result);self.assertEqual(set(data['receipt_ids']),old_ids)
            self.assertEqual({datetime.fromisoformat(o['quote']['raw']['received_at']) for o in data['audit']['input']['observations']},original_times)
            p.persist_refresh(result)
            with self.connector() as db:
                saved=Store(db)
                row=db.execute('SELECT * FROM calculation WHERE session_id=%s',(p.sid,)).fetchone()
                self.assertEqual(set(row['receipt_ids']),old_ids)
                replay(saved.get(row['audit_hash']))
                self.assertEqual(db.execute('SELECT count(*) n FROM receipt WHERE session_id=%s',(p.sid,)).fetchone()['n'],4)
        finally:p.finish('detached input test',0)

    def test_prepared_publication_rollback_retry_and_out_of_order(self):
        from app.dashboard.refresh import compute
        m,p,book=self.prepared();p.defer_views=True
        try:
            p.book(book);first=compute(p.snapshot())
            p.book(book);second=compute(p.snapshot())
            with patch.object(p.store,'metadata',side_effect=RuntimeError('publication rollback')):
                with self.assertRaises(RuntimeError):p.persist_refresh(second)
            self.assertEqual(p.seq,0);self.assertFalse(p.store.precompiled)
            self.assertIsNone(p.store.precompiled_written)
            with self.connector() as db:
                self.assertEqual(db.execute('SELECT count(*) n FROM calculation WHERE session_id=%s',(p.sid,)).fetchone()['n'],0)
            p.persist_refresh(second);self.assertIsNone(p.persist_refresh(first))
            with self.connector() as db:
                self.assertEqual(db.execute('SELECT count(*) n FROM calculation WHERE session_id=%s',(p.sid,)).fetchone()['n'],1)
                self.assertGreaterEqual(Store(db).replay_all(),1)
        finally:p.finish('publication rollback test',0)

    def test_compute_writer_owns_connection_and_settles_before_capture_finish(self):
        from concurrent.futures import ThreadPoolExecutor
        import pickle,threading
        from app.dashboard.refresh import RefreshWriter,StopBudget
        m,p,book=self.prepared();p.defer_views=True;threads=[]
        def connector(database):
            threads.append(('open',threading.get_ident()))
            db=self.connector(database)
            class Owned:
                def __getattr__(self,name):return getattr(db,name)
                def execute(self,*a,**kw):
                    threads.append(('sql',threading.get_ident()));return db.execute(*a,**kw)
                def close(self):threads.append(('close',threading.get_ident()));db.close()
            return Owned()
        writer=RefreshWriter(connector,p.database,p.sid,p.mode,p.limits,StopBudget())
        try:
            p.book(book);snapshot=p.snapshot();old=set(p.current_receipts.values())
            with ThreadPoolExecutor(max_workers=1) as executor:
                future=executor.submit(writer.run,snapshot)
                p.book(book)
                result=pickle.loads(future.result())
                executor.submit(writer.close).result()
            self.assertEqual(result['sid'],p.sid)
            self.assertEqual(len({t for _,t in threads}),1)
            self.assertNotEqual(threads[0][1],threading.get_ident())
            self.assertEqual(threads[-1][0],'close')
            with self.connector() as db:
                row=db.execute('SELECT receipt_ids,audit_hash FROM calculation WHERE session_id=%s',(p.sid,)).fetchone()
                self.assertEqual(set(row['receipt_ids']),old)
                self.assertGreaterEqual(Store(db).replay_all(),1)
        finally:p.finish('separate writer test',0)
