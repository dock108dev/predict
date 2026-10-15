"""Ordinary SQL restart keeps current rows and never replays retired journals."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg import sql
from app.collection.current_database import DatabasePipeline
from app.storage.current_rows import CurrentRowStore
from app.storage.store import connect, Store
from tests.test_d03_current_rows import future_records


class CurrentRestartSQL(unittest.IsolatedAsyncioTestCase):
    async def test_restart_rotates_context_keeps_rows_and_never_replays_journal(self):
        name = 'prediction_arb_test_restart_' + uuid4().hex[:12]
        with connect() as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            with connect(name) as db:
                Store(db).migrate()
                rows = CurrentRowStore(db)
                rows.upsert_records(future_records())
                before = rows.capture()
            with tempfile.TemporaryDirectory() as folder:
                journal = Path(folder) / 'observations.jsonl'
                journal.write_text('retired invalid journal must never be read')
                original = journal.read_bytes()
                service = SimpleNamespace(
                    config=dict(cleanup_seconds=2, sports=['NFL'], families=['moneyline']),
                    sink=SimpleNamespace(error=None), journal=SimpleNamespace(root=folder))
                with patch('app.collection.current_database.connect', side_effect=lambda: connect(name)), \
                     patch('app.collection.current_journal.CurrentJournal', side_effect=AssertionError('no replay')):
                    pipe = DatabasePipeline(service)
                    await pipe.start()
                    try:
                        await asyncio.to_thread(pipe.tick)
                    finally:
                        self.assertTrue(await pipe.close())
                    self.assertTrue(pipe.task.done())
                self.assertEqual(journal.read_bytes(), original)
            with connect(name) as db:
                after = CurrentRowStore(db).capture()
                self.assertNotEqual(before['epoch'], after['epoch'])
                self.assertEqual(before['records'], after['records'])
                for table in ('current_envelope', 'current_import_cursor', 'current_game_snapshot', 'current_game_result'):
                    self.assertEqual(db.execute(sql.SQL('SELECT count(*) n FROM {}').format(
                        sql.Identifier(table))).fetchone()['n'], 0)
        finally:
            with connect() as db:
                db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
