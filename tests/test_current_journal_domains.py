"""Copied/synthetic journal roots only; no provider or owned-data access."""
from copy import deepcopy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from app.collection.current_journal import CurrentJournal
from app.collection.current_journal_domains import (
    NAME, artifact_usage, pack_record, unpack_record,
)
from app.collection.odds_http import BudgetStop


def record(index=0):
    return dict(schema='predict-current-observation-1', source='kalshi', kind='catalog',
                retained_at=f'2026-10-14T01:00:{index:02d}Z', value=dict(games=[
                    dict(id=f'event-{n}', participant_a=f'club-{n * 2}',
                         participant_b=f'club-{n * 2 + 1}', start='2026-10-15T17:00:00Z',
                         instrument=f'contract-{n}', price='.47', depth=200 + n,
                         native_unit='contracts', nullable=None)
                    for n in range(300)]))


def rows(journal):
    return [CurrentJournal.read_record(json.loads(line), path.parent)
            for path in journal.paths() for line in path.read_bytes().splitlines()]


class JournalDomains(unittest.TestCase):
    def test_ordinary_default_and_legacy_cap_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            ordinary = CurrentJournal(directory)
            self.assertTrue(ordinary.compact_history)
            self.assertFalse(CurrentJournal(directory, byte_cap=1000).compact_history)
            self.assertTrue(CurrentJournal(directory, byte_cap=1000, compact_history=True).compact_history)

    def test_exact_receipt_price_revision_and_preserved_original_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CurrentJournal(directory)
            old = json.dumps(dict(old='untouched'), separators=(',', ':')).encode() + b'\n'
            journal.path.write_bytes(old)
            identity = str(journal.path.resolve())
            expected = [record(i) for i in range(12)]
            expected[-1]['value']['games'][127]['price'] = '.53'
            expected[-1]['value']['games'][127]['depth'] = 341
            for row in expected:
                journal.append(row)
            self.assertEqual(journal.path.read_bytes(), old)
            self.assertEqual(str(journal.path.resolve()), identity)
            self.assertEqual(rows(CurrentJournal(directory)), [dict(old='untouched')] + expected)
            with closing(sqlite3.connect(Path(directory) / NAME)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM domain_base').fetchone()[0], 1)
            snapshot = journal.snapshot()
            self.assertGreater(snapshot['domain_bytes'], 0)
            self.assertGreaterEqual(snapshot['allocation_bytes'], snapshot['total_bytes'])
            legacy_size = sum(len(json.dumps(row).encode()) for row in expected)
            self.assertLess(snapshot['allocation_bytes'], legacy_size // 3)

    def test_committed_anchor_survives_interruption_before_append(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CurrentJournal(directory)
            with patch.object(journal, '_append_raw', side_effect=OSError('controlled interruption')):
                with self.assertRaises(OSError):
                    journal.append(record())
            self.assertGreater(artifact_usage(directory), 0)
            self.assertEqual(rows(CurrentJournal(directory)), [])
            reopened = CurrentJournal(directory)
            reopened.append(record())
            self.assertEqual(rows(reopened), [record()])
            with closing(sqlite3.connect(Path(directory) / NAME)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM domain_base').fetchone()[0], 1)

    def test_precommit_failure_rolls_back_and_restart_reuses_clean_store(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def budget(extra):
                calls.append(extra)
                if len(calls) == 4:
                    raise BudgetStop('controlled precommit refusal')
            with self.assertRaisesRegex(BudgetStop, 'precommit'):
                pack_record(record(), directory, budget)
            packed = pack_record(record(), directory, lambda extra: None)
            self.assertEqual(unpack_record(packed, directory), record())
            with closing(sqlite3.connect(Path(directory) / NAME)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM domain_base').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT scope_count FROM domain_meta').fetchone()[0], 1)

    def test_missing_corrupt_and_unknown_references_refuse(self):
        for corruption in ('missing', 'body', 'hash', 'schema', 'sqlite'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as directory:
                packed = pack_record(record(), directory, lambda extra: None)
                if corruption == 'missing':
                    (Path(directory) / NAME).unlink()
                elif corruption == 'body':
                    with closing(sqlite3.connect(Path(directory) / NAME)) as db:
                        db.execute('DROP TRIGGER domain_base_immutable_update')
                        db.execute("UPDATE domain_base SET body=x'0001'")
                        db.commit()
                elif corruption == 'hash':
                    parts = packed['payload'].split(':')
                    parts[2] = '0' * 64
                    packed['payload'] = ':'.join(parts)
                elif corruption == 'schema':
                    packed['schema'] = 'predict-domain-journal-999'
                else:
                    (Path(directory) / NAME).write_bytes(b'bad sqlite')
                with self.assertRaises(ValueError):
                    unpack_record(packed, directory)

    def test_artifact_companions_are_counted_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            packed = pack_record(record(), directory, lambda extra: None)
            before = artifact_usage(directory)
            extra = Path(directory) / (NAME + '-wal')
            extra.write_bytes(b'x' * 5000)
            self.assertGreaterEqual(artifact_usage(directory), before + 5000)
            extra.unlink()
            extra.symlink_to(Path(directory) / NAME)
            with self.assertRaisesRegex(BudgetStop, 'integrity_failed'):
                unpack_record(packed, directory)

    def test_tight_guard_refuses_before_domain_creation_or_old_byte_change(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CurrentJournal(directory, byte_cap=1000000, total_byte_cap=50000,
                                     compact_history=True)
            journal.path.write_bytes(b'{}\n')
            with self.assertRaisesRegex(BudgetStop, 'storage_cap'):
                journal.append(record())
            self.assertEqual(journal.path.read_bytes(), b'{}\n')
            self.assertFalse((Path(directory) / NAME).exists())

    def test_logical_record_cap_is_checked_before_artifact_write(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CurrentJournal(directory, record_cap=1000, compact_history=True)
            with self.assertRaisesRegex(BudgetStop, 'record_cap'):
                journal.append(record())
            self.assertFalse((Path(directory) / NAME).exists())

    def test_legacy_record_returns_same_value(self):
        value = deepcopy(record())
        self.assertIs(unpack_record(value, '/nonexistent/never-created'), value)

    def test_two_compact_writers_share_durable_anchor_without_lost_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            writers = [CurrentJournal(directory), CurrentJournal(directory)]
            def append(index):
                writers[index % 2].append(record(index))
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(append, range(20)))
            self.assertEqual(sorted(rows(CurrentJournal(directory)), key=lambda row: row['retained_at']),
                             [record(index) for index in range(20)])
            with closing(sqlite3.connect(Path(directory) / NAME)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM domain_base').fetchone()[0], 1)

    def test_missing_anchor_prevents_reopened_active_file_from_being_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CurrentJournal(directory)
            journal.append(record())
            saved = journal.paths()[-1].read_bytes()
            (Path(directory) / NAME).unlink()
            with self.assertRaisesRegex(BudgetStop, 'integrity_failed'):
                CurrentJournal(directory).paths()
            self.assertEqual(journal.path.parent.joinpath('observations-000001.jsonl').read_bytes(), saved)

    def test_prepare_recovers_real_process_crash_after_sqlite_dirty_cache_spill(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CurrentJournal(directory)
            journal.append(record())
            original = {path.name: path.read_bytes() for path in journal.paths()}
            child = textwrap.dedent('''
                import os, sys
                from app.collection.current_journal import CurrentJournal
                from app.collection.current_journal_domains import pack_record
                journal = CurrentJournal(sys.argv[1])
                calls = []
                def budget(extra):
                    journal._check_budget(append_bytes=extra)
                    calls.append(extra)
                    if len(calls) == 3:
                        os._exit(73)
                with journal._lock():
                    pack_record(dict(source='crash-source', kind='crash-kind',
                        value=dict(random=os.urandom(512 * 1024).hex())),
                        journal.path.parent, budget)
                raise RuntimeError('controlled crash boundary not reached')
            ''')
            result = subprocess.run([sys.executable, '-c', child, directory],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 73, result.stderr.decode())
            rollback = Path(directory) / (NAME + '-journal')
            self.assertGreater(rollback.stat().st_size, 0)
            self.assertGreater((Path(directory) / NAME).stat().st_size, 512 * 1024)
            crashed = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
            with self.assertRaisesRegex(BudgetStop, 'storage_cap'):
                CurrentJournal(directory, total_byte_cap=1).prepare()
            self.assertEqual({path.name: path.read_bytes() for path in Path(directory).iterdir()}, crashed)
            with patch('app.collection.current_journal.require_disk_space',
                       side_effect=BudgetStop('current_observation_disk_free_floor')):
                with self.assertRaisesRegex(BudgetStop, 'disk_free_floor'):
                    CurrentJournal(directory).prepare()
            self.assertEqual({path.name: path.read_bytes() for path in Path(directory).iterdir()}, crashed)
            reopened = CurrentJournal(directory)
            self.assertEqual(set(path.name for path in reopened.prepare()), set(original))
            self.assertEqual(rows(reopened), [record()])
            self.assertEqual(reopened.records, 0)
            for name, raw in original.items():
                self.assertEqual((Path(directory) / name).read_bytes(), raw)
            self.assertFalse(rollback.exists())
            reopened.append(record(1))
            self.assertEqual(rows(reopened), [record(), record(1)])
            with closing(sqlite3.connect(Path(directory) / NAME)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM domain_base').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT scope_count FROM domain_meta').fetchone()[0], 1)

    def test_recovery_refuses_missing_store_instead_of_creating_anchor_database(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CurrentJournal(directory)
            journal.append(record())
            (Path(directory) / NAME).unlink()
            rollback = Path(directory) / (NAME + '-journal')
            rollback.write_bytes(b'unresolved rollback evidence')
            before = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
            with self.assertRaisesRegex(BudgetStop, 'integrity_failed'):
                CurrentJournal(directory).prepare()
            self.assertEqual({path.name: path.read_bytes() for path in Path(directory).iterdir()}, before)
            (Path(directory) / NAME).write_bytes(b'corrupt database bytes')
            before = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
            with self.assertRaisesRegex(BudgetStop, 'integrity_failed'):
                CurrentJournal(directory).prepare()
            self.assertEqual({path.name: path.read_bytes() for path in Path(directory).iterdir()}, before)


if __name__ == '__main__':
    unittest.main()
