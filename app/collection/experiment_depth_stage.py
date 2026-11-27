"""Bounded collector-local staging for immutable public-depth receipts."""
from contextlib import closing, contextmanager
from hashlib import sha256
import json
import sqlite3

from app.storage import experiment_depth as storage
from app.storage.store import encoded

from .current_storage_policy import require_disk_space

MAX_PENDING_BUNDLES = 48
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
            db.executescript(f'''BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS staged (
                    game_id TEXT NOT NULL, schedule_id TEXT NOT NULL, target_at TEXT NOT NULL,
                    kind TEXT NOT NULL, deadline_at TEXT NOT NULL, staged_at TEXT NOT NULL,
                    receipt_id TEXT NOT NULL, body BLOB NOT NULL CHECK(length(body)<={storage.MAX_BYTES}),
                    PRIMARY KEY(game_id,schedule_id,target_at,kind)
                ) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS disposition (
                    sequence INTEGER PRIMARY KEY, game_id TEXT NOT NULL, schedule_id TEXT NOT NULL,
                    target_at TEXT NOT NULL, kind TEXT NOT NULL, staged_at TEXT NOT NULL,
                    staged_receipt_id TEXT NOT NULL, finished_at TEXT NOT NULL,
                    reason TEXT NOT NULL, receipt_id TEXT
                );
            ''')

    def put(self, payload, deadline_at, staged_at):
        body = encoded(payload)
        if len(body) > storage.MAX_BYTES:
            raise ValueError('experiment_depth_retention_limit')
        receipt_id = sha256(body).hexdigest()
        require_disk_space(self.path, 2 * len(body) + 64 * 1024)
        key = tuple(payload[field] for field in KEY)
        with self._open() as db:
            db.execute('BEGIN IMMEDIATE')
            original = db.execute('''SELECT receipt_id FROM staged
                WHERE (game_id,schedule_id,target_at,kind)=(?,?,?,?)''', key).fetchone()
            if original:
                return original['receipt_id']
            if db.execute('SELECT count(*) FROM staged').fetchone()[0] >= MAX_PENDING_BUNDLES:
                raise BlockingIOError('experiment_depth_stage_capacity')
            db.execute('INSERT INTO staged VALUES (?,?,?,?,?,?,?,?)', (
                *key, storage.clock(deadline_at), storage.clock(staged_at), receipt_id, body))
        return receipt_id

    def entries(self):
        with self._open() as db:
            return db.execute('''SELECT game_id,schedule_id,target_at,kind,deadline_at,staged_at,receipt_id
                FROM staged ORDER BY kind,staged_at,game_id,schedule_id,target_at''').fetchall()

    def load(self, entry):
        key = tuple(entry[field] for field in KEY)
        with self._open() as db:
            row = db.execute('''SELECT body FROM staged
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
            deleted = db.execute('''DELETE FROM staged
                WHERE (game_id,schedule_id,target_at,kind)=(?,?,?,?) AND receipt_id=?''',
                (*key, entry['receipt_id'])).rowcount
            if deleted:
                db.execute('''INSERT INTO disposition(game_id,schedule_id,target_at,kind,staged_at,
                    staged_receipt_id,finished_at,reason,receipt_id) VALUES (?,?,?,?,?,?,?,?,?)''',
                    (*key, entry['staged_at'], entry['receipt_id'], storage.clock(utc()), reason, receipt_id))
                db.execute('DELETE FROM disposition WHERE sequence <= (SELECT max(sequence) FROM disposition)-?',
                           (2 * MAX_PENDING_BUNDLES,))
