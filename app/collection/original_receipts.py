"""Bounded original SGO responses, outside the normalized SQL ingress contract.

No fetch/retry, eviction, credentials, request URLs or cursor values. A full store
records a gap instead of making a successful paid response fail admission.
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache
import fcntl
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from .current_policy import ROOT
from .current_storage_policy import FREE_DISK_BYTE_FLOOR, disk_capacity
from .sportsgameodds_adapter import MAX_PAGE_BYTES, parse_page, project_event
from .sportsgameodds_transport import validate_params
from .sgo_capabilities import supported_odd

FORMAT = 'predict-original-response-1'
PARSER_VERSION = 'sgo-full-game-points-1'
# A storage allocation, not a coverage/completion target. No automatic deletion.
MAX_COMPRESSED_BYTES = 128 * 1024 * 1024
MAX_RECEIPTS = 16_384
MANIFEST_RUNWAY = 64 * 1024


def directory(root=None):
    return Path(root or ROOT / '.local/predict-odds/original-responses')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def safe_scope(params):
    params = validate_params(params)
    return {key: sha256(value.encode()).hexdigest() if key == 'cursor' else value
            for key, value in params.items()}


def checkpoint_request_scope(metadata, params, batch, event_id):
    """Verify a logical one-event scope against its exact physical request."""
    physical = metadata['request_scope']
    if params.get('eventIDs') != event_id or params.get('cursor') or physical.get('cursor'):
        raise ValueError('retained_explicit_event_scope_unproven')
    if not batch:
        if physical != params:
            raise ValueError('retained_explicit_event_scope_unproven')
        return physical
    ids = physical.get('eventIDs', '').split(',')
    if (physical != batch.get('request_scope') or event_id not in ids or '' in ids
            or len(set(ids)) != len(ids) or batch.get('size') != len(ids)
            or physical.get('limit') != len(ids)
            or params != dict(physical, eventIDs=event_id, limit=1)):
        raise ValueError('retained_batch_event_scope_unproven')
    return physical


def checkpoint_page(body, metadata, params, batch, event_id, *, pull_id, attempt_id, venues=None):
    """Reparse the authenticated body and project the claimed member only."""
    checkpoint_request_scope(metadata, params, batch, event_id)
    parsed = parse_page(body, metadata['received_at'], venues=venues)
    if parsed.receipt_sha256 != metadata['receipt_sha256']:
        raise ValueError('retained_page_receipt_differs')
    returned = [event['event_id'] for event in parsed.events]
    if event_id not in returned or (batch and returned != batch.get('response_event_ids')):
        raise ValueError('retained_explicit_event_membership_unproven')
    if not batch and returned != [event_id]:
        raise ValueError('retained_explicit_event_membership_unproven')
    parsed = replace(parsed, attempt_id=attempt_id, received_at=metadata['received_at'],
                     physical_event_ids=tuple(returned) if batch else None)
    event = next(event for event in parsed.events if event['event_id'] == event_id)
    quotes = (quote for quote in parsed.quotes if quote['event_id'] == event_id)
    return project_event(parsed, event, quotes, pull_id=pull_id, request_scope=params)


def field_census(body, params):
    """Count received classes without claiming discarded fields were requested."""
    result = dict(requested_odd_ids=sorted(params['oddID'].split(',')),
                  other_markets='not_requested', received_supported_markets=0,
                  received_unsupported_markets=0, received_result_events=0,
                  classification='response_unparseable')
    try:
        value = json.loads(body)
        events = value.get('data') if isinstance(value, dict) else None
        if not isinstance(events, list):
            return result
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get('results'):
                result['received_result_events'] += 1
            odds = event.get('odds') or {}
            if isinstance(odds, dict):
                for odd in odds.values():
                    supported = supported_odd(odd)
                    result['received_supported_markets' if supported else
                           'received_unsupported_markets'] += 1
        result['classification'] = 'received_field_census'
    except (ValueError, UnicodeError, RecursionError):
        pass
    return result


@contextmanager
def writable(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / '.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with sqlite3.connect(root / 'manifest.sqlite3', timeout=5) as db:
            db.row_factory = sqlite3.Row
            db.executescript('''
                CREATE TABLE IF NOT EXISTS receipt (
                    id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, received_at TEXT NOT NULL,
                    metadata TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS receipt_body ON receipt(sha256);
                CREATE TABLE IF NOT EXISTS gap (
                    reason TEXT PRIMARY KEY, count INTEGER NOT NULL,
                    first_at TEXT NOT NULL, last_at TEXT NOT NULL);
            ''')
            yield db


def readonly(root):
    path = root / 'manifest.sqlite3'
    if not path.is_file():
        return None
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def capture(params, response, *, root=None, max_bytes=MAX_COMPRESSED_BYTES,
            max_receipts=MAX_RECEIPTS):
    """Retain HTTP-200 bytes once; identical retries never duplicate payloads."""
    if type(max_bytes) is not int or max_bytes < 0 or type(max_receipts) is not int or max_receipts < 0:
        raise ValueError('nonnegative retention bounds required')
    scope = safe_scope(params)
    if response.status != 200:
        return dict(state='not_retained', reason='transport_does_not_retain_error_bodies')
    body = response.body
    if not isinstance(body, bytes) or len(body) > MAX_PAGE_BYTES:
        raise ValueError('bounded original bytes required')
    at = datetime.fromisoformat(response.received_at.replace('Z', '+00:00'))
    if at.utcoffset() is None:
        raise ValueError('receipt timezone required')
    digest = sha256(body).hexdigest()
    identity = sha256(encoded([digest, response.received_at, scope, PARSER_VERSION])).hexdigest()
    root = directory(root)
    try:
        if not disk_capacity(root, MANIFEST_RUNWAY)['available']:
            # Even diagnostic metadata must preserve the floor. This refusal
            # remains visible in the collector heartbeat/request trace.
            return dict(state='not_retained', reason='disk_free_floor', receipt_sha256=digest,
                        received_at=response.received_at, manifest_written=False)
        with writable(root) as db:
            existing = db.execute('SELECT metadata FROM receipt WHERE id=?', (identity,)).fetchone()
            if existing:
                prior = json.loads(existing['metadata'])
                if prior['state'] == 'retained':
                    _verified(root / (digest + '.json.gz'), digest)
                return prior
            payload = gzip.compress(body, compresslevel=6, mtime=0)
            path = root / (digest + '.json.gz')
            used = sum(p.stat().st_size for p in root.glob('*.json.gz'))
            count = db.execute('SELECT count(*) FROM receipt').fetchone()[0]
            reason = ('receipt_count_cap' if count >= max_receipts else
                      'compressed_byte_cap' if not path.exists() and used + len(payload) > max_bytes else
                      'disk_free_floor' if not path.exists() and
                      shutil.disk_usage(root).free < FREE_DISK_BYTE_FLOOR + len(payload) + MANIFEST_RUNWAY else None)
            metadata = dict(format=FORMAT, id=identity, provider='sportsgameodds',
                            receipt_sha256=digest, received_at=response.received_at,
                            parser_version=PARSER_VERSION, request_scope=scope,
                            cursor_is_hash='cursor' in scope, raw_bytes=len(body),
                            gzip_bytes=len(payload) if reason is None else None,
                            state='not_retained' if reason else 'retained', reason=reason,
                            fields=field_census(body, params), normalized_link=dict(receipt_sha256=digest),
                            admission='not_inferred_from_retention')
            if reason:
                db.execute('''INSERT INTO gap VALUES (?,1,?,?) ON CONFLICT(reason) DO UPDATE SET
                              count=count+1,last_at=excluded.last_at''',
                           (reason, response.received_at, response.received_at))
            else:
                if not path.exists():
                    fd, temporary = tempfile.mkstemp(prefix='.receipt-', dir=root)
                    try:
                        with os.fdopen(fd, 'wb') as out:
                            out.write(payload)
                            out.flush()
                            os.fsync(out.fileno())
                        os.replace(temporary, path)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
                else:
                    # An interrupted write or damaged payload must never become
                    # a claimed reprocessing witness on retry.
                    _read_payload(path, digest)
            if count < max_receipts:
                db.execute('INSERT INTO receipt VALUES (?,?,?,?)',
                           (identity, digest, response.received_at, encoded(metadata).decode()))
            return metadata
    except (OSError, sqlite3.Error, EOFError, ValueError):
        # Preserve paid accounting/admission, expose a retention failure. The
        # runtime heartbeat records this result even if its manifest is broken.
        return dict(state='not_retained', reason='original_receipt_storage_error',
                    receipt_sha256=digest, received_at=response.received_at)


def _read_payload(path, digest):
    with gzip.open(path, 'rb') as stream:
        body = stream.read(MAX_PAGE_BYTES + 1)
    if len(body) > MAX_PAGE_BYTES or sha256(body).hexdigest() != digest:
        raise ValueError('original receipt integrity failure')
    return body


@lru_cache(maxsize=128)
def _verified_stat(path, digest, size, modified_ns):
    # Cache only verification facts, never response bodies. Immutable files
    # shared by many rows are decompressed once per observed file revision.
    _read_payload(Path(path), digest)
    return True


def _verified(path, digest):
    info = path.stat()
    return _verified_stat(str(path), digest, info.st_size, info.st_mtime_ns)


def lookup(receipt_sha256, *, root=None):
    if not isinstance(receipt_sha256, str) or not re.fullmatch('[0-9a-f]{64}', receipt_sha256):
        return dict(state='not_recorded', reason='receipt_hash_unavailable', captures=[])
    root = directory(root)
    try:
        db = readonly(root)
    except (OSError, sqlite3.Error):
        return dict(state='unavailable', reason='original_receipt_manifest_unavailable', captures=[])
    if db is None:
        return dict(state='not_recorded', reason='original_response_retention_not_active_at_receipt', captures=[])
    try:
        rows = db.execute('SELECT metadata FROM receipt WHERE sha256=? ORDER BY received_at,id',
                          (receipt_sha256,)).fetchall()
        captures = [json.loads(row['metadata']) for row in rows]
        retained = [row for row in captures if row['state'] == 'retained']
        path = root / (receipt_sha256 + '.json.gz')
        present = path.is_file()
        verified = retained and present and _verified(path, receipt_sha256)
        state = 'retained' if verified else 'not_retained' if captures else 'not_recorded'
        return dict(state=state, reason=None if state == 'retained' else
                    'retained_payload_missing' if retained else captures[-1]['reason'] if captures else
                    'original_response_not_recorded', captures=captures,
                    raw_bytes=retained[-1]['raw_bytes'] if retained else None,
                    gzip_bytes=retained[-1]['gzip_bytes'] if retained else None,
                    integrity='sha256_verified' if verified else 'not_established')
    except (OSError, sqlite3.Error, ValueError, EOFError):
        return dict(state='unavailable', reason='original_receipt_integrity_or_manifest_failure', captures=[])
    finally:
        db.close()


def read(receipt_id, *, root=None):
    root = directory(root)
    db = readonly(root)
    if db is None:
        raise KeyError('original receipt not recorded')
    try:
        row = db.execute('SELECT metadata FROM receipt WHERE id=?', (receipt_id,)).fetchone()
        if row is None:
            raise KeyError('original receipt not recorded')
        metadata = json.loads(row['metadata'])
        if metadata['state'] != 'retained':
            raise ValueError('original receipt not retained')
        return metadata, _read_payload(root / (metadata['receipt_sha256'] + '.json.gz'),
                                       metadata['receipt_sha256'])
    finally:
        db.close()


def status(*, root=None):
    root = directory(root)
    try:
        db = readonly(root)
    except (OSError, sqlite3.Error):
        return dict(state='unavailable', reason='original_receipt_manifest_unavailable')
    if db is None:
        return dict(state='not_started', captured_receipts=0, compressed_bytes=0, gaps=[],
                    compressed_byte_cap=MAX_COMPRESSED_BYTES, receipt_cap=MAX_RECEIPTS)
    try:
        row = db.execute('SELECT count(*) AS count,min(received_at) AS first_at,max(received_at) AS last_at FROM receipt').fetchone()
        return dict(state='bounded_capture', captured_receipts=row['count'], first_at=row['first_at'],
                    last_at=row['last_at'], compressed_bytes=sum(p.stat().st_size for p in root.glob('*.json.gz')),
                    compressed_byte_cap=MAX_COMPRESSED_BYTES, receipt_cap=MAX_RECEIPTS,
                    gaps=[dict(row) for row in db.execute('SELECT * FROM gap ORDER BY reason')],
                    retention='no_automatic_eviction', complete_history=False,
                    observed_at=datetime.now(timezone.utc).isoformat())
    except (OSError, sqlite3.Error):
        return dict(state='unavailable', reason='original_receipt_manifest_unavailable')
    finally:
        db.close()
