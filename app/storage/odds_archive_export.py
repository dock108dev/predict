"""Export sealed UTC daily shards to a verified remote filesystem."""
import argparse
from datetime import date, timedelta
import gzip
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
import signal
import shutil
import tempfile
from threading import Event

from .odds_archive import FEEDS, digest
from .store import connect, encoded

LOGGER = logging.getLogger(__name__)
LOCK = 120094
SHARD_ROWS = 12000
SHARD_BYTES = 6 * 1024 * 1024
MAX_WAIT = timedelta(minutes=15)
CHECK_INTERVAL = 30
MARKER = '.predict-archive-id'


def claim(db, *, feed=None, force=False):
    """Commit immutable membership before any filesystem operation."""
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        existing = db.execute('''SELECT id,feed,receipt_day FROM odds_archive_batch
            WHERE (%s::text IS NULL OR feed=%s) ORDER BY claimed_at,id LIMIT 1''', (feed,feed)).fetchone()
        if existing:
            return existing
        group = db.execute('''SELECT feed,receipt_day FROM odds_archive_stage
            WHERE batch_id IS NULL AND (%s::text IS NULL OR feed=%s) GROUP BY feed,receipt_day
            HAVING %s OR min(received_at)<=clock_timestamp()-%s OR sum(bytes)>=%s OR count(*)>=%s
            ORDER BY receipt_day,min(received_at),feed LIMIT 1''',
            (feed, feed, force, MAX_WAIT, SHARD_BYTES, SHARD_ROWS)).fetchone()
        if not group:
            return None
        ids = [row['id'] for row in db.execute('''WITH ordered AS (
            SELECT id,bytes,row_number() OVER (ORDER BY (body->>3) COLLATE "C" NULLS FIRST,
                (body->>2),received_at,id) position
            FROM odds_archive_stage WHERE batch_id IS NULL AND feed=%s AND receipt_day=%s
        ), limited AS (
            SELECT id,position,sum(bytes) OVER (ORDER BY position) running
            FROM ordered WHERE position<=%s
        ) SELECT id FROM limited WHERE position=1 OR running<=%s ORDER BY id''',
            (group['feed'], group['receipt_day'], SHARD_ROWS, SHARD_BYTES)).fetchall()]
        batch_id = digest([group['feed'], group['receipt_day'].isoformat(), [bytes(i).hex() for i in ids]])
        db.execute('INSERT INTO odds_archive_batch(feed,receipt_day,id) VALUES (%s,%s,%s)',
                   (group['feed'], group['receipt_day'], batch_id))
        db.execute('UPDATE odds_archive_stage SET batch_id=%s WHERE id=ANY(%s)', (batch_id, ids))
        return dict(group, id=batch_id)


def load_batch(db, batch):
    rows = db.execute('''SELECT id,body FROM odds_archive_stage WHERE batch_id=%s
        ORDER BY (body->>3) COLLATE "C" NULLS FIRST,(body->>2),received_at,id''',
                      (batch['id'],)).fetchall()
    ids = [bytes(row['id']).hex() for row in rows]
    if not rows or digest([batch['feed'], batch['receipt_day'].isoformat(), sorted(ids)]) != batch['id']:
        raise ValueError('odds_archive_batch_membership_conflict')
    for identity, row in zip(ids, rows):
        if digest(row['body']) != identity:
            raise ValueError('odds_archive_change_hash_conflict')
    return b''.join(encoded([identity,*row['body']])+b'\n' for identity,row in zip(ids,rows))


def _sync_directory(path):
    descriptor = os.open(path, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class DirectoryArchive:
    """POSIX remote mount with no-replace writes and verified read-back."""

    def __init__(self, path, expected_identity):
        self.path = Path(path)
        self.expected_identity = expected_identity
        if not self.path.is_absolute() or not expected_identity or len(expected_identity) > 128:
            raise ValueError('odds_archive_mount_configuration_required')

    def verify_mount(self):
        with (self.path / MARKER).open(encoding='utf-8') as marker:
            if marker.read(130).strip() != self.expected_identity:
                raise ValueError('odds_archive_mount_identity_mismatch')

    def write(self, batch, raw):
        self.verify_mount()
        feed, day, identity = batch['feed'], batch['receipt_day'], batch['id']
        if feed not in FEEDS or type(day) is not date or not re.fullmatch(r'[0-9a-f]{64}', identity):
            raise ValueError('odds_archive_invalid_path')
        relative = Path('v1',feed,day.isoformat(),f'{identity}.jsonl.gz')
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Persist directory entries as well as the data file before ACK.
        for directory in reversed(tuple(target.parents)[:4]):
            _sync_directory(directory)
        if not target.exists():
            compressed = gzip.compress(raw, compresslevel=6, mtime=0)
            if shutil.disk_usage(self.path).free < len(compressed)+512*1024*1024:
                raise ValueError('odds_archive_destination_capacity')
            with tempfile.NamedTemporaryFile(prefix=f'.{identity}.', dir=target.parent) as temporary:
                temporary.write(compressed)
                temporary.flush()
                os.fsync(temporary.fileno())
                try:
                    os.link(temporary.name, target)
                except FileExistsError:
                    pass
                _sync_directory(target.parent)
        with target.open('rb') as file, gzip.GzipFile(fileobj=file) as decoded:
            if decoded.read(len(raw)+1) != raw:
                raise ValueError('odds_archive_remote_content_conflict')
            size = os.fstat(file.fileno()).st_size
        self.verify_mount()
        return dict(path=relative.as_posix(), bytes=size, sha256=sha256(raw).hexdigest())


def acknowledge(db, batch, receipt):
    """Clear only the exact verified membership; repeat ACK is harmless."""
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        if not db.execute('SELECT 1 FROM odds_archive_batch WHERE id=%s', (batch['id'],)).fetchone():
            return False
        expected_path = f"v1/{batch['feed']}/{batch['receipt_day']}/{batch['id']}.jsonl.gz"
        raw = load_batch(db, batch)
        if (receipt.get('path') != expected_path or type(receipt.get('bytes')) is not int
                or receipt['bytes'] <= 0 or receipt.get('sha256') != sha256(raw).hexdigest()):
            raise ValueError('odds_archive_remote_receipt_conflict')
        db.execute('SELECT 1 FROM odds_archive_usage WHERE singleton FOR UPDATE')
        removed = db.execute('''WITH rows AS (
            DELETE FROM odds_archive_stage WHERE batch_id=%s RETURNING bytes
        ) SELECT count(*) count,coalesce(sum(bytes),0) bytes FROM rows''', (batch['id'],)).fetchone()
        db.execute('UPDATE odds_archive_usage SET staged_bytes=staged_bytes-%s WHERE singleton', (removed['bytes'],))
        db.execute('''UPDATE odds_archive_feed_status SET
            verified=verified+%s,verified_file_bytes=verified_file_bytes+%s,
            last_verified_at=clock_timestamp(),last_verified_file=%s WHERE feed=%s''',
            (removed['count'],receipt['bytes'],receipt['path'],batch['feed']))
        db.execute('DELETE FROM odds_archive_batch WHERE id=%s', (batch['id'],))
        return True


def expire_heads(db):
    return db.execute('''DELETE FROM odds_archive_head WHERE identity IN (
        SELECT identity FROM odds_archive_head WHERE expires_at<clock_timestamp()
        ORDER BY expires_at LIMIT 10000)''').rowcount


def status(db):
    usage = db.execute('''SELECT staged_bytes,(SELECT min(received_at) FROM odds_archive_stage) oldest,
        (SELECT extract(epoch FROM clock_timestamp()-min(received_at))::bigint FROM odds_archive_stage) oldest_age_seconds,
        (SELECT count(*) FROM odds_archive_batch) pending_batches FROM odds_archive_usage''').fetchone()
    feeds = db.execute('SELECT * FROM odds_archive_feed_status ORDER BY feed').fetchall()
    return dict(usage, feeds=feeds)


def run(archive, stop):
    while not stop.is_set():
        try:
            with connect() as db:
                if not db.execute('SELECT pg_try_advisory_lock(%s) held', (LOCK,)).fetchone()['held']:
                    stop.wait(CHECK_INTERVAL)
                    continue
                archive.verify_mount()
                for feed in sorted(FEEDS):
                    try:
                        for _ in range(8):
                            if stop.is_set() or not (batch := claim(db, feed=feed)):
                                break
                            receipt = archive.write(batch, load_batch(db,batch))
                            acknowledge(db,batch,receipt)
                            LOGGER.info('Verified odds archive shard %s (%s bytes)', receipt['path'],receipt['bytes'])
                    except Exception:
                        LOGGER.exception('Odds archive delivery failed for %s; staged evidence retained', feed)
        except Exception:
            LOGGER.exception('Odds archive delivery failed; staged evidence retained')
        stop.wait(CHECK_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--status', action='store_true')
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--flush', action='store_true', help='Verify and export currently staged rows once, without waiting for shard age')
    args = parser.parse_args()
    if args.status:
        with connect() as db:
            print(json.dumps(status(db), default=str))
        return
    archive = DirectoryArchive(os.environ.get('PREDICT_ODDS_ARCHIVE_ROOT','/archive'),
                               os.environ.get('PREDICT_ODDS_ARCHIVE_ID'))
    if args.check:
        archive.verify_mount()
        with connect() as db:
            lag = status(db)['oldest_age_seconds'] or 0
        return int(lag > 1800)
    if args.flush:
        archive.verify_mount()
        with connect() as db:
            if not db.execute('SELECT pg_try_advisory_lock(%s) held', (LOCK,)).fetchone()['held']:
                raise ValueError('odds_archive_export_already_running')
            for feed in sorted(FEEDS):
                for _ in range(64):
                    batch = claim(db,feed=feed,force=True)
                    if not batch:
                        break
                    acknowledge(db,batch,archive.write(batch,load_batch(db,batch)))
            print(json.dumps(status(db),default=str))
        return
    logging.basicConfig(level=logging.INFO)
    stop = Event()
    for sig in (signal.SIGINT,signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run(archive,stop)


if __name__ == '__main__':
    raise SystemExit(main())
