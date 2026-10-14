"""Durable local journal rollover; isolated roots and no provider requests."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.collection.current_journal import CurrentJournal
from app.collection.odds_http import BudgetStop


def raw(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode() + b'\n'


class Segments(unittest.TestCase):
    def journal(self, directory, *, byte_cap=100, total_byte_cap=20000):
        return CurrentJournal(directory, byte_cap=byte_cap,
                              total_byte_cap=total_byte_cap, record_cap=1000)

    def records(self, journal):
        return [json.loads(line) for path in journal.paths()
                for line in path.read_bytes().splitlines()]

    def image(self, directory):
        return {path.name: path.read_bytes() for path in Path(directory).iterdir()
                if path.is_file()}

    def test_prepare_is_idempotent_and_preserves_original_without_fake_records(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            original_raw = raw(dict(source_at='2026-10-13T00:00:00Z', price='.43'))
            journal.path.write_bytes(original_raw)
            identity = str(journal.path.resolve())
            prepared = journal.prepare()
            manifest_raw = journal.manifest_path.read_bytes()
            self.assertEqual(prepared, journal.prepare())
            self.assertEqual(journal.manifest_path.read_bytes(), manifest_raw)
            self.assertEqual(journal.path.read_bytes(), original_raw)
            self.assertEqual(str(journal.path.resolve()), identity)
            self.assertEqual(prepared[-1].read_bytes(), b'')
            self.assertEqual(journal.records, 0)
            self.assertEqual(self.records(journal), [json.loads(original_raw)])

    def test_original_path_bytes_and_cursor_identity_survive_rotation_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'observations.jsonl'
            original_raw = raw(dict(source_at='2026-10-13T00:00:00Z', price='.43'))
            original.write_bytes(original_raw)
            identity = str(original.resolve())
            journal = self.journal(directory, byte_cap=80)
            for index in range(5):
                journal.append(dict(index=index, price='.47', padding='x' * 20))
            self.assertEqual(original.read_bytes(), original_raw)
            self.assertEqual(str(journal.path.resolve()), identity)
            manifest = json.loads(journal.manifest_path.read_bytes())
            self.assertEqual(manifest['sealed'][0], dict(name=original.name, index=0,
                bytes=len(original_raw), sha256=hashlib.sha256(original_raw).hexdigest()))
            reopened = self.journal(directory, byte_cap=80)
            self.assertEqual(self.records(reopened), [json.loads(original_raw)] + [
                dict(index=i, price='.47', padding='x' * 20) for i in range(5)])
            self.assertEqual(journal.segment_paths(), reopened.paths())
            self.assertEqual(journal.snapshot()['active_bytes'], len(raw(dict(index=4, price='.47', padding='x' * 20))))
            self.assertTrue(all(path.stat().st_size <= 80 for path in reopened.paths()[1:]))

    def test_exact_segment_boundary_rolls_only_before_the_next_record(self):
        record = dict(price='.52')
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory, byte_cap=len(raw(record)) * 2)
            journal.append(record)
            journal.append(record)
            self.assertEqual(len(journal.paths()), 2)
            journal.append(record)
            self.assertEqual(len(journal.paths()), 3)
            self.assertEqual(self.records(journal), [record] * 3)

    def test_total_cap_includes_manifest_and_never_changes_existing_data_on_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            record = dict(price='.52')
            journal.append(record)
            snapshot = journal.snapshot()
            self.assertGreater(snapshot['total_bytes'], snapshot['bytes'])
            before = self.image(directory)
            capped = self.journal(directory, total_byte_cap=snapshot['total_bytes'] + len(raw(record)) - 1)
            with self.assertRaisesRegex(BudgetStop, 'current_observation_storage_cap'):
                capped.append(record)
            self.assertEqual(self.image(directory), before)

    def test_two_writers_use_one_manifest_and_do_not_drop_or_duplicate_records(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.journal(directory, byte_cap=200, total_byte_cap=50000)
            second = self.journal(directory, byte_cap=200, total_byte_cap=50000)
            def append(index):
                (first if index % 2 else second).append(dict(index=index, price='.48'))
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(append, range(100)))
            records = self.records(self.journal(directory, byte_cap=200, total_byte_cap=50000))
            self.assertEqual(sorted(record['index'] for record in records), list(range(100)))
            self.assertEqual(first.records + second.records, 100)

    def test_sealed_hash_cache_avoids_rehashing_until_stat_identity_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            journal.append(dict(price='.48'))
            with patch.object(journal, '_digest_file', wraps=journal._digest_file) as digest:
                journal.paths()
                journal.snapshot()
                journal.paths()
                self.assertEqual(digest.call_count, 0)
            original = journal.path
            original.write_bytes(b'{}\n')
            with self.assertRaisesRegex(BudgetStop, 'current_observation_integrity_failed'):
                journal.paths()

    def test_sealed_same_length_modification_is_rejected_on_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'observations.jsonl'
            original.write_bytes(raw(dict(price='.48')))
            journal = self.journal(directory)
            journal.append(dict(price='.52'))
            original.write_bytes(raw(dict(price='.49')))
            with self.assertRaisesRegex(BudgetStop, 'current_observation_integrity_failed'):
                self.journal(directory).paths()

    def test_original_incomplete_tail_is_preserved_and_never_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'observations.jsonl'
            original.write_bytes(b'{')
            with self.assertRaisesRegex(BudgetStop, 'current_observation_incomplete_tail'):
                self.journal(directory).append(dict(price='.48'))
            self.assertEqual(original.read_bytes(), b'{')
            self.assertFalse((Path(directory) / 'observations.manifest.json').exists())

    def test_active_incomplete_or_invalid_complete_tail_is_preserved(self):
        for suffix, reason in ((b'{', 'incomplete_tail'), (b'not-json\n', 'integrity_failed')):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                journal = self.journal(directory)
                journal.append(dict(price='.48'))
                active = journal.paths()[-1]
                before = active.read_bytes() + suffix
                active.write_bytes(before)
                with self.assertRaisesRegex(BudgetStop, reason):
                    self.journal(directory).append(dict(price='.52'))
                self.assertEqual(active.read_bytes(), before)

    def test_manifest_corruption_and_nonempty_orphan_do_not_grant_authority(self):
        for corrupt in ('manifest', 'orphan'):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                journal = self.journal(directory)
                journal.append(dict(price='.48'))
                if corrupt == 'manifest':
                    manifest = json.loads(journal.manifest_path.read_bytes())
                    manifest['active']['index'] = 2
                    journal.manifest_path.write_text(json.dumps(manifest))
                else:
                    (Path(directory) / 'observations-000002.jsonl').write_bytes(raw(dict(price='.49')))
                before = self.image(directory)
                with self.assertRaisesRegex(BudgetStop, 'manifest_corrupt'):
                    self.journal(directory).append(dict(price='.52'))
                self.assertEqual(self.image(directory), before)

    def test_failed_rotation_manifest_publish_recovers_empty_orphan_without_data_loss(self):
        record = dict(price='.48')
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory, byte_cap=len(raw(record)))
            journal.append(record)
            first = journal.paths()[-1]
            first_raw = first.read_bytes()
            with patch('app.collection.current_journal.os.replace', side_effect=OSError('controlled')):
                with self.assertRaises(OSError):
                    journal.append(dict(price='.49'))
            self.assertEqual(first.read_bytes(), first_raw)
            self.assertEqual((Path(directory) / 'observations-000002.jsonl').read_bytes(), b'')
            reopened = self.journal(directory, byte_cap=len(raw(record)))
            self.assertTrue(reopened.snapshot()['pending_rotation'])
            reopened.append(dict(price='.49'))
            self.assertEqual(self.records(reopened), [record, dict(price='.49')])
            self.assertFalse(reopened.snapshot()['pending_rotation'])
            self.assertFalse(reopened.temporary_path.exists())

    def test_low_disk_refusal_preserves_original_and_creates_no_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            journal.path.write_bytes(raw(dict(price='.48')))
            before = self.image(directory)
            with patch('app.collection.current_journal.require_disk_space', side_effect=BudgetStop('current_observation_disk_free_floor')):
                with self.assertRaisesRegex(BudgetStop, 'disk_free_floor'):
                    journal.append(dict(price='.49'))
            self.assertEqual(self.image(directory), before)

    def test_symlink_journal_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_bytes(raw(dict(price='.48')))
            observations = Path(directory) / 'journal'
            observations.mkdir()
            (observations / 'observations.jsonl').symlink_to(target)
            with self.assertRaisesRegex(BudgetStop, 'integrity_failed'):
                self.journal(observations).append(dict(price='.49'))
            self.assertEqual(target.read_bytes(), raw(dict(price='.48')))

    def test_legacy_small_cap_is_not_expanded_and_cannot_write_sealed_original(self):
        with tempfile.TemporaryDirectory() as directory:
            record = dict(price='.48')
            original = CurrentJournal(directory, byte_cap=len(raw(record)))
            original.append(record)
            with self.assertRaisesRegex(BudgetStop, 'storage_cap'):
                original.append(record)
            self.journal(directory).append(record)
            before = original.path.read_bytes()
            with self.assertRaisesRegex(BudgetStop, 'manifest_corrupt'):
                original.append(record)
            self.assertEqual(original.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
