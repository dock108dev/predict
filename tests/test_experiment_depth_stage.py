"""Legacy SQLite receipt upgrade and durable rejection evidence."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.collection.experiment_depth_stage import DepthStage, KEY
from app.storage import experiment_depth as depth
from app.storage.store import encoded


class DepthStageMigration(TestCase):
    def test_v1_parks_large_receipts_and_their_followups_without_changing_evidence(self):
        target = datetime(2026, 11, 27, 23, 50, tzinfo=timezone.utc)
        known = target - timedelta(seconds=1)
        deadline = target + timedelta(minutes=1)
        later = target + timedelta(seconds=30)

        def payload(game_id, **fields):
            return depth.normalize(dict(game_id=game_id, schedule_id='schedule', target_at=target),
                                   observations={}, **fields)

        legacy = payload('legacy', known_at=known)
        wide = payload('wide', known_at=known, reason='x' * (600 * 1024))
        wide_id = sha256(encoded(wide)).hexdigest()
        followup = payload('wide', known_at=later, cutoff_at=later, kind='followup', origin_id=wide_id)

        with TemporaryDirectory() as temp:
            path = Path(temp) / 'stage.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''
                    CREATE TABLE staged (
                        game_id TEXT NOT NULL, schedule_id TEXT NOT NULL, target_at TEXT NOT NULL,
                        kind TEXT NOT NULL, deadline_at TEXT NOT NULL, staged_at TEXT NOT NULL,
                        receipt_id TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body)<=8388608),
                        PRIMARY KEY(game_id,schedule_id,target_at,kind)
                    ) WITHOUT ROWID;
                    PRAGMA user_version=1;
                ''')
                rows = []
                for item in (legacy, wide, followup):
                    body = encoded(item)
                    rows.append((*[item[field] for field in KEY], depth.clock(deadline), item['known_at'],
                                 sha256(body).hexdigest(), body))
                db.executemany('INSERT INTO staged VALUES (?,?,?,?,?,?,?,?)', rows)

            stage = DepthStage(path)
            with patch('app.collection.experiment_depth_stage.require_disk_space'):
                stage.initialize()
                stage.initialize()
            self.assertEqual([stage.load(entry) for entry in stage.entries()], [legacy, wide, followup])
            self.assertEqual(stage.put(dict(wide, reason='second capture'), deadline, known), wide_id)
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA trusted_schema=OFF')
                self.assertEqual(db.execute('SELECT * FROM staged').fetchall(), rows[:1])
                self.assertEqual(db.execute('SELECT * FROM staged_large ORDER BY kind').fetchall(), rows[1:])
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'experiment_depth_stage_incompatible'):
                    db.execute('INSERT INTO staged VALUES (?,?,?,?,?,?,?,?)',
                               ('wide', *rows[0][1:]))

    def test_upgrade_keeps_legacy_evidence_and_records_new_refusals(self):
        target = datetime(2026, 11, 27, 23, 50, tzinfo=timezone.utc)
        known = target - timedelta(seconds=1)
        deadline = target + timedelta(minutes=1)

        def receipt(game_id, reason=None):
            task = dict(game_id=game_id, schedule_id='schedule', target_at=target)
            observations = {'exact-side': dict(venue='novig', complete=True,
                received_at=depth.clock(known), levels=[dict(price='2/5', quantity='250')])}
            return depth.normalize(task, known_at=known, observations=observations, reason=reason)

        legacy = receipt('legacy-pending')
        legacy_body = encoded(legacy)
        legacy_id = sha256(legacy_body).hexdigest()
        legacy_entry = tuple(legacy[field] for field in KEY)
        completed = receipt('legacy-published')
        completed_id = sha256(encoded(completed)).hexdigest()
        disposition = (*[completed[field] for field in KEY], depth.clock(known), completed_id,
                       depth.clock(target), 'published', completed_id)

        with TemporaryDirectory() as temp:
            path = Path(temp) / 'stage.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('''
                    CREATE TABLE staged (
                        game_id TEXT NOT NULL, schedule_id TEXT NOT NULL, target_at TEXT NOT NULL,
                        kind TEXT NOT NULL, deadline_at TEXT NOT NULL, staged_at TEXT NOT NULL,
                        receipt_id TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body)<=524288),
                        PRIMARY KEY(game_id,schedule_id,target_at,kind)
                    ) WITHOUT ROWID;
                    CREATE TABLE disposition (
                        sequence INTEGER PRIMARY KEY, game_id TEXT NOT NULL, schedule_id TEXT NOT NULL,
                        target_at TEXT NOT NULL, kind TEXT NOT NULL, staged_at TEXT NOT NULL,
                        staged_receipt_id TEXT NOT NULL, finished_at TEXT NOT NULL,
                        reason TEXT NOT NULL, receipt_id TEXT
                    );
                ''')
                db.execute('INSERT INTO staged VALUES (?,?,?,?,?,?,?,?)',
                           (*legacy_entry, depth.clock(deadline), depth.clock(known), legacy_id, legacy_body))
                db.execute('INSERT INTO disposition VALUES (1,?,?,?,?,?,?,?,?,?)', disposition)

            with patch('app.collection.experiment_depth_stage.require_disk_space'):
                stage = DepthStage(path)
                stage.initialize()
                stage = DepthStage(path)
                stage.initialize()
                old_entry, = stage.entries()
                self.assertEqual(old_entry['receipt_id'], legacy_id)
                self.assertEqual(stage.load(old_entry), legacy)

                wide = receipt('above-legacy-limit', reason='é' * (256 * 1024))
                wide_body = encoded(wide)
                self.assertGreater(len(wide_body), 524288)
                wide_id = stage.put(wide, deadline, known)
                self.assertEqual(wide_id, sha256(wide_body).hexdigest())

                refused = receipt('beyond-cap', reason='over budget')
                refused_body = encoded(refused)
                with patch.object(depth, 'MAX_BYTES', len(refused_body) - 1):
                    with self.assertRaisesRegex(ValueError, '^experiment_depth_retention_limit$'):
                        stage.put(refused, deadline, known)
                malformed = dict(receipt('cannot-encode'), reason=float('nan'))
                with self.assertRaisesRegex(ValueError, '^experiment_depth_stage_encoding$'):
                    stage.put(malformed, deadline, known)

            reopened = DepthStage(path)
            self.assertEqual({row['receipt_id'] for row in reopened.entries()}, {legacy_id, wide_id})
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT receipt_id,body FROM staged WHERE game_id=?',
                                            ('legacy-pending',)).fetchone(), (legacy_id, legacy_body))
                self.assertEqual(db.execute('SELECT * FROM disposition').fetchall(), [(1, *disposition)])
                failures = db.execute('''SELECT game_id,schedule_id,target_at,kind,cutoff_at,failed_at,
                    reason,payload_bytes,receipt_id FROM capture_failure ORDER BY game_id''').fetchall()
            cutoff_clock, failed_clock = depth.clock(target), depth.clock(known)
            self.assertEqual(failures, [
                ('beyond-cap', 'schedule', cutoff_clock, 'decision', cutoff_clock, failed_clock,
                 'experiment_depth_retention_limit', len(refused_body), sha256(refused_body).hexdigest()),
                ('cannot-encode', 'schedule', cutoff_clock, 'decision', cutoff_clock, failed_clock,
                 'experiment_depth_stage_encoding', None, None),
            ])
