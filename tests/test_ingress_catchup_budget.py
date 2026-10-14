"""Larger catch-up passes retain record transactions, checkpoints and Stop."""
from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest import TestCase
from unittest.mock import patch

from app.collection.current_database import DatabasePipeline, catch_up_segments
from app.comparison.calculation_control import cancellation, CalculationStopped
from app.storage.current_games import GameStore


class CursorDB:
    def __init__(self):self.offset=0;self.imported=[];self.commits=0
    def execute(self,query,params):
        if query.startswith('SELECT'):return SimpleNamespace(fetchone=lambda:dict(byte_offset=self.offset))
        self.offset=params[1]
    @contextmanager
    def transaction(self):
        before=(self.offset,list(self.imported))
        try:yield
        except BaseException:
            self.offset,self.imported=before;raise
        else:self.commits+=1


class IngressBudget(TestCase):
    def test_time_budget_stops_at_a_committed_record_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.jsonl';lines=[json.dumps(dict(i=i)).encode()+b'\n' for i in range(3)];path.write_bytes(b''.join(lines))
            db=CursorDB();store=GameStore(db)
            def imported(record,identity):db.imported.append(record['i']);return {'game'}
            with patch.object(store,'import_record',side_effect=imported),patch('time.monotonic',side_effect=[0.0,0.9,1.1]):
                self.assertEqual(store.catch_up(path,records=64,deadline=1.0),({'game'},2))
            self.assertEqual(db.imported,[0,1]);self.assertEqual(db.offset,len(lines[0])+len(lines[1]));self.assertEqual(db.commits,2)
            with patch.object(store,'import_record',side_effect=imported):store.catch_up(path,records=64)
            self.assertEqual(db.imported,[0,1,2]);self.assertEqual(db.offset,path.stat().st_size)

    def test_stop_after_import_commits_envelope_and_cursor_before_handback(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.jsonl';path.write_text(''.join(json.dumps(dict(i=i))+'\n' for i in range(3)))
            db=CursorDB();store=GameStore(db);stopped=[False]
            def imported(record,identity):
                db.imported.append(record['i'])
                if record['i']==1:stopped[0]=True
                return {'game'}
            with patch.object(store,'import_record',side_effect=imported),self.assertRaises(CalculationStopped),cancellation(lambda:stopped[0]):
                store.catch_up(path,records=64)
            self.assertEqual(db.imported,[0,1]);self.assertEqual(db.commits,2)
            stopped[0]=False
            with patch.object(store,'import_record',side_effect=imported):store.catch_up(path,records=64)
            self.assertEqual(db.imported,[0,1,2])

    def test_shared_deadline_does_not_skip_later_path_checkpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[Path(folder)/str(i) for i in range(2)]
            for path in paths:path.write_bytes(b'x'*10)
            offsets={};calls=[]
            class Store:
                def catch_up(self,path,records,deadline):
                    calls.append((path.name,records,deadline));offsets[str(path.resolve())]=2;return {'game'},1
                def execute(self,query,params):return SimpleNamespace(fetchone=lambda:dict(byte_offset=offsets.get(params[0],0)))
            store=Store();store.db=store
            with patch('app.collection.current_database.monotonic',side_effect=[0.0,1.1]):
                keys,count,backlog=catch_up_segments(store,SimpleNamespace(paths=lambda:paths),64,deadline=1.0)
            self.assertEqual((keys,count,backlog),({'game'},1,18));self.assertEqual(calls,[('0',64,1.0)])

    def test_pipeline_coalesces_legacy_projection_once_for_the_larger_pass(self):
        service=SimpleNamespace(journal=object());pipe=DatabasePipeline(service,[]);pipe.bootstrapped=True
        projects=[];store=SimpleNamespace(project=projects.append)
        with patch('app.collection.current_database.connect',return_value=nullcontext(object())), \
                patch('app.collection.current_database.Store',return_value=SimpleNamespace(migrate=lambda:None)), \
                patch('app.collection.current_database.GameStore',return_value=store), \
                patch('app.collection.current_database.sql_usage',return_value=0), \
                patch('app.collection.current_database.require_disk_space'), \
                patch('app.collection.current_database.monotonic',return_value=42.0), \
                patch('app.collection.current_database.catch_up_segments',return_value=({'game:a','game:b'},64,100)) as catch:
            self.assertEqual(pipe.tick(import_only=True),64)
        self.assertEqual(projects,['game:a','game:b'])
        self.assertEqual(catch.call_args.kwargs,dict(records=64,deadline=43.0))
        self.assertEqual(pipe.MAX_PENDING,4)
