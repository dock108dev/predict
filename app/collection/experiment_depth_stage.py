"""Bounded collector-local staging for immutable public-depth receipts."""
from contextlib import closing, contextmanager
from hashlib import sha256
import json
import sqlite3

from app.storage import experiment_depth as storage
from app.storage.store import encoded

from .current_storage_policy import require_disk_space
from .odds_http import BudgetStop

MAX_PENDING_BUNDLES = 48
LEGACY_MAX_BYTES = 512 * 1024
KEY = ('game_id', 'schedule_id', 'target_at', 'kind')


class InvalidStagedReceipt(ValueError):
    pass


class DepthStage:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def _open(self):
        with closing(sqlite3.connect(self.path, timeout=1)) as db:
            db.row_factory = sqlite3.Row
            # Rollback transactions fsync the payload and the journal removal.
            db.execute('PRAGMA synchronous=EXTRA')
            db.execute('PRAGMA trusted_schema=OFF')
            with db:
                yield db

    def initialize(self):
        if not self.path.exists():
            require_disk_space(self.path, 64 * 1024)
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._open() as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version == 2:
                return
            if version not in (0, 1):
                raise ValueError('experiment_depth_stage_version')
            for table, limit in (('staged', LEGACY_MAX_BYTES), ('staged_large', storage.MAX_BYTES)):
                db.execute(f'''CREATE TABLE IF NOT EXISTS {table} (
                    game_id TEXT NOT NULL, schedule_id TEXT NOT NULL, target_at TEXT NOT NULL,
                    kind TEXT NOT NULL, deadline_at TEXT NOT NULL, staged_at TEXT NOT NULL,
                    receipt_id TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body)<={limit}),
                    PRIMARY KEY(game_id,schedule_id,target_at,kind)
                ) WITHOUT ROWID''')
            if version == 1:
                require_disk_space(self.path, 2 * self.path.stat().st_size + 64 * 1024)
                # Move both kinds together so the previous collector cannot
                # dispose of a small follow-up whose decision is still parked.
                db.execute('''INSERT INTO staged_large SELECT * FROM staged
                    WHERE (game_id,schedule_id,target_at) IN (SELECT game_id,schedule_id,target_at
                        FROM staged WHERE length(body)>?)''', (LEGACY_MAX_BYTES,))
                db.execute('''DELETE FROM staged WHERE (game_id,schedule_id,target_at,kind) IN
                    (SELECT game_id,schedule_id,target_at,kind FROM staged_large)''')
            db.execute('''CREATE VIEW staged_receipts AS
                SELECT * FROM staged UNION ALL SELECT * FROM staged_large''')
            db.execute(f'''CREATE TRIGGER keep_legacy_staging_compatible BEFORE INSERT ON staged
                WHEN length(NEW.body)>{LEGACY_MAX_BYTES} OR EXISTS (SELECT 1 FROM staged_large l
                    WHERE (l.game_id,l.schedule_id,l.target_at)=(NEW.game_id,NEW.schedule_id,NEW.target_at))
                BEGIN SELECT RAISE(ABORT, 'experiment_depth_stage_incompatible'); END''')
            db.execute('''CREATE TABLE IF NOT EXISTS disposition (
                    sequence INTEGER PRIMARY KEY, game_id TEXT NOT NULL, schedule_id TEXT NOT NULL,
                    target_at TEXT NOT NULL, kind TEXT NOT NULL, staged_at TEXT NOT NULL,
                    staged_receipt_id TEXT NOT NULL, finished_at TEXT NOT NULL,
                    reason TEXT NOT NULL, receipt_id TEXT
                )''')
            db.execute('''CREATE TABLE IF NOT EXISTS capture_failure (
                    game_id TEXT NOT NULL, schedule_id TEXT NOT NULL, target_at TEXT NOT NULL,
                    kind TEXT NOT NULL, cutoff_at TEXT NOT NULL, failed_at TEXT NOT NULL,
                    reason TEXT NOT NULL, payload_bytes INTEGER, receipt_id TEXT,
                    PRIMARY KEY(game_id,schedule_id,target_at,kind)
                ) WITHOUT ROWID''')
            db.execute('PRAGMA user_version=2')

    @staticmethod
    def _reject(db, key, cutoff_at, failed_at, reason, size, receipt_id):
        db.execute('''INSERT INTO capture_failure VALUES (?,?,?,?,?,?,?,?,?)
                      ON CONFLICT (game_id,schedule_id,target_at,kind) DO NOTHING''',
                   (*key, storage.clock(cutoff_at), storage.clock(failed_at), reason, size, receipt_id))

    def reject(self, task, kind, cutoff_at, failed_at, reason):
        key = task['game_id'], task['schedule_id'], storage.clock(task['target_at']), kind
        with self._open() as db:
            self._reject(db, key, cutoff_at, failed_at, reason, None, None)

    def put(self, payload, deadline_at, staged_at):
        key = tuple(payload[field] for field in KEY)
        try:
            body = encoded(payload)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            reason = 'experiment_depth_stage_encoding'
            self.reject(payload, payload['kind'], payload['cutoff_at'], staged_at, reason)
            raise ValueError(reason) from exc
        size = len(body)
        receipt_id = sha256(body).hexdigest()
        error = None
        with self._open() as db:
            db.execute('BEGIN IMMEDIATE')
            original = db.execute('''SELECT receipt_id FROM staged_receipts
                WHERE (game_id,schedule_id,target_at,kind)=(?,?,?,?)''', key).fetchone()
            if original:
                return original['receipt_id']
            occurrence = key[:3]
            try:
                if size > storage.MAX_BYTES:
                    raise ValueError('experiment_depth_retention_limit')
                if db.execute('SELECT count(*) FROM staged_receipts').fetchone()[0] >= MAX_PENDING_BUNDLES:
                    raise BlockingIOError('experiment_depth_stage_capacity')
                sibling_bytes = 0
                if size > LEGACY_MAX_BYTES:
                    sibling_bytes = db.execute('''SELECT coalesce(sum(length(body)),0) FROM staged
                        WHERE (game_id,schedule_id,target_at)=(?,?,?)''', occurrence).fetchone()[0]
                require_disk_space(self.path, 2 * (size + sibling_bytes) + 64 * 1024)
            except (ValueError, BlockingIOError, BudgetStop) as exc:
                error = exc
                self._reject(db, key, payload['cutoff_at'], staged_at, str(exc), size, receipt_id)
            else:
                if size > LEGACY_MAX_BYTES:
                    db.execute('''INSERT INTO staged_large SELECT * FROM staged
                        WHERE (game_id,schedule_id,target_at)=(?,?,?)''', occurrence)
                    db.execute('''DELETE FROM staged WHERE (game_id,schedule_id,target_at)=(?,?,?)''', occurrence)
                large = size > LEGACY_MAX_BYTES or db.execute('''SELECT 1 FROM staged_large
                    WHERE (game_id,schedule_id,target_at)=(?,?,?) LIMIT 1''', occurrence).fetchone()
                table = 'staged_large' if large else 'staged'
                db.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?)', (
                    *key, storage.clock(deadline_at), storage.clock(staged_at), receipt_id, body))
        if error is not None:
            raise error
        return receipt_id

    def entries(self):
        with self._open() as db:
            return db.execute('''SELECT game_id,schedule_id,target_at,kind,deadline_at,staged_at,receipt_id
                FROM staged_receipts ORDER BY kind,staged_at,game_id,schedule_id,target_at''').fetchall()

    def load(self, entry):
        key = tuple(entry[field] for field in KEY)
        with self._open() as db:
            row = db.execute('''SELECT body FROM staged_receipts
                WHERE (game_id,schedule_id,target_at,kind)=(?,?,?,?) AND receipt_id=?''',
                (*key, entry['receipt_id'])).fetchone()
        if row is None:
            raise BlockingIOError('experiment_depth_stage_changed')
        body = row['body']
        if not isinstance(body, bytes) or len(body) > storage.MAX_BYTES or sha256(body).hexdigest() != entry['receipt_id']:
            raise InvalidStagedReceipt('experiment_depth_stage_checksum')
        try:
            payload = json.loads(body)
            if (tuple(payload[field] for field in KEY) != key or payload['version'] != storage.VERSION
                    or encoded(payload) != body):
                raise InvalidStagedReceipt('experiment_depth_stage_identity')
            if not isinstance(payload['metrics'], dict) or not isinstance(payload['source_gaps'], dict):
                raise InvalidStagedReceipt('experiment_depth_stage_invalid')
            storage.validate(payload)
        except InvalidStagedReceipt:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
            reason = str(exc) if str(exc) in ('experiment_depth_cutoff', 'experiment_depth_receipt_clock') else 'experiment_depth_stage_invalid'
            raise InvalidStagedReceipt(reason) from exc
        return payload

    def finish(self, entry, reason, receipt_id=None):
        from app.research.experiment import utc

        key = tuple(entry[field] for field in KEY)
        with self._open() as db:
            deleted = 0
            for table in ('staged', 'staged_large'):
                deleted += db.execute(f'''DELETE FROM {table}
                    WHERE (game_id,schedule_id,target_at,kind)=(?,?,?,?) AND receipt_id=?''',
                    (*key, entry['receipt_id'])).rowcount
            if deleted:
                db.execute('''INSERT INTO disposition(game_id,schedule_id,target_at,kind,staged_at,
                    staged_receipt_id,finished_at,reason,receipt_id) VALUES (?,?,?,?,?,?,?,?,?)''',
                    (*key, entry['staged_at'], entry['receipt_id'], storage.clock(utc()), reason, receipt_id))
                db.execute('DELETE FROM disposition WHERE sequence <= (SELECT max(sequence) FROM disposition)-?',
                           (2 * MAX_PENDING_BUNDLES,))
