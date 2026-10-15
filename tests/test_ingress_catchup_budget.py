"""Explicit retained imports keep record transactions, checkpoints and Stop."""
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest import TestCase
from unittest.mock import patch

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
