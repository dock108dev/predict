"""Freeze one database observation into a local, read-only replay archive."""
import argparse
from contextlib import closing
from datetime import timezone
from pathlib import Path
import os
import sqlite3
import tempfile

from . import comparison_snapshot as snapshots, ordinary_publication as publication
from .store import ROOT, connect, stamp

DIRECTORY = ROOT / '.local/odds-replay'
DATASETS = ('preview', 'frozen')
MAX_ARCHIVE_BYTES = 192 * 1024 * 1024


def capture():
    """The source data, source authority and calculation settings share one view."""
    with connect() as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        at = db.execute('SELECT clock_timestamp() AS captured_at').fetchone()['captured_at'].astimezone(timezone.utc)
        owner, states = publication.authority(db, at=at)
        inputs = snapshots.capture(db, at=at.isoformat(), ordinary=True)
        settings = publication.current_settings(db)
    control = {key: owner.get(key) for key in ('active', 'healthy', 'global_stopped', 'paused_sources')}
    return inputs, settings, control, states


def compile_archive(dataset, captured, directory=DIRECTORY):
    from app.comparison.inspection_math import offer_math

    if dataset not in DATASETS:
        raise ValueError('Unknown replay dataset')
    inputs, settings, owner, states = captured
    if not inputs['quotes']:
        raise ValueError('Replay capture contains no usable offers')
    at = stamp(inputs['captured_at'])
    result = publication.bind(snapshots.calculate(inputs, settings), inputs, 'ready')
    result = publication.project(result, inputs['dependencies'], owner, states, at=at,
                                 policy=inputs['policy_identity'], epoch=inputs['epoch'], settings=settings)
    result['replay'] = dict(dataset=dataset, captured_at=inputs['captured_at'],
                            id=result['id'], synthetic=False)
    originals = {quote['id']: quote for quote in inputs['quotes']}
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.replay-', suffix='.sqlite3', dir=directory)
    os.close(fd)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.execute(f'PRAGMA max_page_count={MAX_ARCHIVE_BYTES // 4096}')
            db.execute('CREATE TABLE archive (kind TEXT PRIMARY KEY, payload BLOB NOT NULL)')
            db.execute('CREATE TABLE detail (id TEXT PRIMARY KEY, payload BLOB NOT NULL)')
            db.execute('INSERT INTO archive VALUES (?, ?)', ('inputs', snapshots.pack(captured)))
            for row in result['rows']:
                row['evidence_result_id'] = result['id']
                row['captured_at'] = inputs['captured_at']
                proof = dict(result_id=result['id'], row=row, captured_at=inputs['captured_at'],
                             inspection=offer_math(row), originals=[originals[row['id']]],
                             assumptions=settings, provider_requests=0)
                db.execute('INSERT INTO detail VALUES (?, ?)', (row['id'], snapshots.pack(proof, fast=True)))
            compact = publication.compact_member(result)
            board = {k: v for k, v in compact.items() if k not in ('references', 'issues')}
            db.execute('INSERT INTO archive VALUES (?, ?)', ('board', snapshots.pack(board)))
        os.replace(temporary, directory / f'{dataset}.sqlite3')
    finally:
        Path(temporary).unlink(missing_ok=True)
    return dict(result['replay'], counts=result['counts'], current_prices=result['publication']['current_prices'],
                issues=len(inputs['issues']))


def open_archive(path):
    return closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', choices=DATASETS)
    parser.add_argument('--rebuild', action='store_true', help='Recalculate from saved inputs without opening PostgreSQL')
    args = parser.parse_args()
    if args.rebuild:
        with open_archive(DIRECTORY / f'{args.dataset}.sqlite3') as db:
            captured = snapshots.unpack(db.execute("SELECT payload FROM archive WHERE kind='inputs'").fetchone()[0])
    else:
        captured = capture()
    print(compile_archive(args.dataset, captured), flush=True)


if __name__ == '__main__':
    main()
