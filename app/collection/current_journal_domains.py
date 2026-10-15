"""Immutable domain bases for future journal records; old JSONL stays untouched.

The SQLite file is owned by the journal, guarded by its flock and included in
the same disk allowance. A committed base can outlive an interrupted append;
such an orphan is safe, reusable and remains charged to the allowance.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

from .odds_http import BudgetStop

VERSION = 'predict-domain-journal-2'
NAME = 'observations.domains.sqlite3'
MAX_RAW = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024
MAX_SCOPES = 1000000
APPLICATION_ID = 0x504A3032
_SUFFIXES = ('', '-journal', '-wal', '-shm')


def artifact_paths(directory):
    root = Path(directory)
    return [root / (NAME + suffix) for suffix in _SUFFIXES
            if os.path.lexists(root / (NAME + suffix))]


def artifact_usage(directory):
    total = 0
    for path in artifact_paths(directory):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BudgetStop('current_observation_integrity_failed')
        total += max(info.st_size, info.st_blocks * 512)
    if total > MAX_ARTIFACT_BYTES:
        raise BudgetStop('current_observation_storage_cap')
    return total


def _sync(directory):
    for path in artifact_paths(directory):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _connect(directory, *, readonly=False, create=True):
    path = Path(directory) / NAME
    artifact_usage(directory)
    if (readonly or not create) and not path.exists():
        raise ValueError('missing journal domain base')
    if not readonly and not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    # URI mode=ro also refuses creation on read/recovery. Existing sidecars and
    # every SQLite companion are checked before SQLite can follow a link.
    mode = 'ro' if readonly else 'rwc' if create else 'rw'
    db = sqlite3.connect(path.as_uri() + '?mode=' + mode,
                         uri=True, timeout=10)
    try:
        db.execute('PRAGMA trusted_schema=OFF')
        application = db.execute('PRAGMA application_id').fetchone()[0]
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if (application, version) != (APPLICATION_ID, 2):
            if readonly or (application, version) != (0, 0) or path.stat().st_size:
                raise ValueError('unsupported journal domain database')
        if not readonly:
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA cache_size=-64')
            db.execute('PRAGMA mmap_size=0')
    except Exception:
        db.close()
        raise
    return db


def recover_domains(directory, budget_callback):
    """Recover a crashed SQLite transaction under the journal owner's flock.

    Read-only SQLite cannot roll back dirty pages spilled before a process
    crash. Recovery opens the existing sidecar for SQLite's own rollback before
    any JSONL validation. It creates no facts or records and grants no dispatch
    or publication authority. Missing/corrupt stores remain hard failures.
    """
    directory = Path(directory).resolve()
    if not os.path.lexists(directory / (NAME + '-journal')):
        return False
    artifact_usage(directory)
    budget_callback(0)
    path = directory / NAME
    if not path.exists():
        raise ValueError('missing journal domain base')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        header = stream.read(100)
    # SQLite may delete an invalid rollback companion before reporting a bad
    # main file. Refuse an alien/truncated header before allowing recovery I/O.
    # A zero-byte main file is the supported interrupted first-creation state.
    if header and (len(header) != 100 or header[:16] != b'SQLite format 3\x00'
            or (int.from_bytes(header[68:72], 'big'), int.from_bytes(header[60:64], 'big'))
            not in ((APPLICATION_ID, 2), (0, 0))):
        raise ValueError('invalid journal domain recovery header')
    db = None
    try:
        db = _connect(directory, create=False)
        # The header reads in _connect force SQLite hot-journal recovery;
        # taking/releasing the transaction proves the write recovery completed.
        db.execute('BEGIN IMMEDIATE')
        db.rollback()
    except sqlite3.Error as exc:
        raise ValueError('invalid journal domain recovery') from exc
    finally:
        if db is not None:
            db.close()
    _sync(directory)
    budget_callback(0)
    return True


def _base(db, base_id):
    from app.storage.domain_delta import decompress
    row = db.execute('SELECT expanded_bytes,body FROM domain_base WHERE id=?', (base_id,)).fetchone()
    if row is None or type(row[0]) is not int or not 0 <= row[0] <= MAX_RAW:
        raise ValueError('missing or invalid journal domain base')
    raw = decompress(row[1], MAX_RAW)
    if len(raw) != row[0] or hashlib.sha256(raw).hexdigest() != base_id:
        raise ValueError('journal domain base hash conflict')
    return raw


def pack_record(record, directory, budget_callback):
    """Called under CurrentJournal's lock; commit/fsync precedes JSONL append."""
    from app.storage.domain_delta import compress, make_delta, scope_for_record, encode_header
    raw = json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                     allow_nan=False).encode()
    if len(raw) + 1 > MAX_RAW:
        raise BudgetStop('current_observation_record_cap')
    directory = Path(directory).resolve()
    scope = scope_for_record(record)
    if not isinstance(scope, str) or len(scope.encode()) > MAX_RAW:
        raise ValueError('invalid journal domain scope')
    # Exact domain identity may contain a batch's instrument list. Keep its
    # indexed key fixed-size without dropping or normalizing any identity.
    scope = hashlib.sha256(scope.encode()).hexdigest()
    budget_callback(0)
    # New database/schema plus rollback journal must fit before any creation.
    if not (directory / NAME).exists():
        budget_callback(128 * 1024)
    db = None
    try:
        db = _connect(directory)
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA user_version').fetchone()[0] == 0:
            db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            db.execute('PRAGMA user_version=2')
        db.execute('CREATE TABLE IF NOT EXISTS domain_base ('
                   'id TEXT PRIMARY KEY,expanded_bytes INTEGER NOT NULL,body BLOB NOT NULL) WITHOUT ROWID')
        db.execute('CREATE TABLE IF NOT EXISTS domain_scope ('
                   'scope TEXT PRIMARY KEY,base_id TEXT NOT NULL REFERENCES domain_base(id)) WITHOUT ROWID')
        db.execute("CREATE TRIGGER IF NOT EXISTS domain_base_immutable_update "
                   "BEFORE UPDATE ON domain_base BEGIN SELECT RAISE(ABORT,'immutable journal domain base'); END")
        db.execute("CREATE TRIGGER IF NOT EXISTS domain_base_immutable_delete "
                   "BEFORE DELETE ON domain_base BEGIN SELECT RAISE(ABORT,'immutable journal domain base'); END")
        db.execute('CREATE TABLE IF NOT EXISTS domain_meta ('
                   'id INTEGER PRIMARY KEY CHECK(id=1),scope_count INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO domain_meta VALUES (1,0)')
        row = db.execute('SELECT base_id FROM domain_scope WHERE scope=?', (scope,)).fetchone()
        if row is None:
            if db.execute('SELECT scope_count FROM domain_meta WHERE id=1').fetchone()[0] >= MAX_SCOPES:
                raise BudgetStop('current_observation_domain_scope_cap')
            base_id = hashlib.sha256(raw).hexdigest()
            body = compress(raw)
            # Bound the new payload and rollback/index pages before insertion.
            budget_callback(len(body) * 3 + 128 * 1024)
            db.execute('INSERT OR IGNORE INTO domain_base VALUES (?,?,?)', (base_id, len(raw), body))
            db.execute('INSERT INTO domain_scope VALUES (?,?)', (scope, base_id))
            db.execute('UPDATE domain_meta SET scope_count=scope_count+1 WHERE id=1')
            base = _base(db, base_id)
        else:
            base_id = row[0]
            base = _base(db, base_id)
        encoded = encode_header(base_id, raw, make_delta(base, raw))
        outer = dict(schema=VERSION, payload=encoded)
        encoded_bytes = len(json.dumps(outer, separators=(',', ':'), sort_keys=True).encode()) + 1
        # SQLite may still hold dirty pages in its bounded cache. Charge their
        # full projected main-file extent plus a conservative rollback reserve
        # before committing, including any existing WAL/SHM/journal files.
        projected = db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0]
        main = directory / NAME
        current = max(main.stat().st_size, main.stat().st_blocks * 512)
        budget_callback(encoded_bytes + max(0, projected - current) + 128 * 1024)
        db.commit()
        _sync(directory)
        budget_callback(encoded_bytes)
        return outer
    except sqlite3.Error as exc:
        raise ValueError('invalid journal domain storage') from exc
    finally:
        if db is not None:
            db.close()


def unpack_record(record, directory):
    """Read exactly one referenced immutable base, never a whole-store scan."""
    if (isinstance(record, dict) and isinstance(record.get('schema'), str)
            and record['schema'].startswith('predict-domain-journal-')
            and record['schema'] != VERSION):
        raise ValueError('unsupported journal domain schema')
    if not isinstance(record, dict) or record.get('schema') != VERSION:
        return record
    if set(record) != {'schema', 'payload'}:
        raise ValueError('invalid journal domain reference')
    from app.storage.domain_delta import decode_header, apply_delta
    db = None
    try:
        base_id, size, digest, delta = decode_header(record['payload'])
        if type(size) is not int or not 0 <= size <= MAX_RAW:
            raise ValueError('journal domain expanded cap')
        db = _connect(Path(directory).resolve(), readonly=True)
        base = _base(db, base_id)
        raw = apply_delta(base, delta, size)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('journal domain payload hash conflict')
        from .current_journal import _json
        value = _json(raw)
        if not isinstance(value, dict) or value.get('schema') == VERSION:
            raise ValueError('invalid journal domain payload')
        return value
    except sqlite3.Error as exc:
        raise ValueError('invalid journal domain storage') from exc
    finally:
        if db is not None:
            db.close()
