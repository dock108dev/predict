"""Copied-source journal rollover and SQL replay; disposable database only."""
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from psycopg import sql
from app.collection.current_database import catch_up_segments
from app.collection.current_journal import CurrentJournal
from app.storage.current_games import GameStore
from app.storage.store import connect,Store
from integration_tests.test_current_games import actual


class SegmentedSQL(unittest.TestCase):
    def test_rollover_preserves_original_checkpoints_and_imports_once(self):
        name='prediction_arb_test_segments_'+uuid4().hex[:12]
        with connect() as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            with tempfile.TemporaryDirectory() as folder:
                record=actual();raw=json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()+b'\n'
                original=Path(folder)/'observations.jsonl';original.write_bytes(raw)
                journal=CurrentJournal(folder,byte_cap=len(raw)+10,total_byte_cap=1024*1024)
                with connect(name) as db:
                    Store(db).migrate();store=GameStore(db)
                    self.assertEqual(catch_up_segments(store,journal,1)[1:],(1,0))
                    original_cursor=db.execute('SELECT byte_offset FROM current_import_cursor WHERE path=%s',(str(original.resolve()),)).fetchone()['byte_offset']
                journal.append(record);journal.append(record)
                self.assertEqual(len(journal.paths()),3);self.assertEqual(original.read_bytes(),raw)
                with connect(name) as db:
                    store=GameStore(db);keys,count,backlog=catch_up_segments(store,CurrentJournal(folder,byte_cap=len(raw)+10,total_byte_cap=1024*1024),1)
                    self.assertEqual(count,1);self.assertEqual(backlog,len(raw))
                    self.assertEqual(db.execute('SELECT byte_offset FROM current_import_cursor WHERE path=%s',(str(original.resolve()),)).fetchone()['byte_offset'],original_cursor)
                with connect(name) as db:
                    store=GameStore(db)
                    self.assertEqual(catch_up_segments(store,journal,8)[1:],(1,0))
                    self.assertEqual(catch_up_segments(store,journal,8)[1:],(0,0))
                    self.assertEqual(db.execute('SELECT count(*) AS n FROM current_envelope').fetchone()['n'],3)
                    self.assertEqual(db.execute('SELECT count(*) AS n FROM current_import_cursor').fetchone()['n'],3)
                self.assertEqual(original.read_bytes(),raw)
        finally:
            with connect() as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
