"""Explicit stopped-runtime sports reset; independent business state is preserved.

This is a deliberate cutover tool, never an app-startup migration or recovery.
No directories, credentials, account records or generic research SQL are deleted.
"""
import argparse
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from psycopg import sql
from .store import ROOT, connect, encoded

LEGACY_TABLES = (
    'current_calculation_attempt', 'current_latest_result', 'current_game_result',
    'current_game_snapshot', 'current_game_projection', 'current_source_projection',
    'current_import_cursor', 'current_envelope', 'current_domain_head',
    'current_domain_anchor', 'current_price_latest', 'current_price_revision',
    'current_price_game', 'current_price_game_fact',
)
# Exact file families, never their containing directories. No audit attempt or
# account receipt files match these allowlists.
SPORTS_FILES = (
    '.local/predict-observations/observations.jsonl',
    '.local/predict-observations/observations-[0-9][0-9][0-9][0-9][0-9][0-9].jsonl',
    '.local/predict-observations/observations.manifest.json',
    '.local/predict-observations/observations.domains.sqlite3',
    '.local/predict-observations/observations.domains.sqlite3-journal',
    '.local/predict-observations/observations.domains.sqlite3-wal',
    '.local/predict-observations/observations.domains.sqlite3-shm',
    '.local/predict-odds/diagnostics/NFL.json',
    '.local/predict-odds/diagnostics/NCAAF.json',
    '.local/predict-odds/diagnostics/NBA.json',
    '.local/predict-odds/diagnostics/NCAAB.json',
    '.local/predict-odds/diagnostics/MLB.json',
    '.local/predict-odds/diagnostics/NHL.json',
)


def fingerprint(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('reset_requires_regular_file:' + str(path))
    h = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return dict(bytes=path.stat().st_size, sha256=h.hexdigest())


def sports_files(root=ROOT):
    return sorted({p for pattern in SPORTS_FILES for p in root.glob(pattern)})


def protected_files(root=ROOT):
    files = set(root.glob('.local/predict*.json'))
    files.update(root.glob('.local/estimate-policy.json'))
    files.update(root.glob('.env'))
    for folder in ('predict-odds', 'predict-current'):
        base = root / '.local' / folder
        files.update(p for p in base.rglob('*') if p.is_file()
                     and 'diagnostics' not in p.relative_to(base).parts
                     and p.suffix != '.lock')
    return {str(p.relative_to(root)): fingerprint(p) for p in sorted(files)}


def protected_sql(db):
    """Hash every non-current table except migration history, without exporting it."""
    names = [r['tablename'] for r in db.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND left(tablename,8)<>'current_' AND tablename<>'schema_migration' "
        "ORDER BY tablename").fetchall()]
    result = {}
    for name in names:
        hashes = db.execute(sql.SQL(
            'SELECT md5(row_to_json(t)::text) AS hash FROM {} t ORDER BY 1'
        ).format(sql.Identifier(name))).fetchall()
        result[name] = dict(rows=len(hashes), sha256=sha256(
            encoded([r['hash'] for r in hashes])).hexdigest())
    return result


def plan(db, root=ROOT):
    from app.collection.current_policy import candidate
    existing = {r['tablename'] for r in db.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()}
    return dict(version='predict-sports-reset-1', source_digest=candidate()[0],
                tables=[t for t in LEGACY_TABLES if t in existing],
                files={str(p.relative_to(root)): fingerprint(p) for p in sports_files(root)},
                protected_files=protected_files(root), protected_sql=protected_sql(db))


def require_stopped(db):
    for path in (ROOT / '.local/opportunity-board/process.json',
                 ROOT / '.local/opportunity-board-beta/process.json'):
        if path.exists():
            value = json.loads(path.read_text())
            process = subprocess.run(['/bin/ps', '-p', str(value['pid']), '-o', 'command='],
                                     capture_output=True, text=True).stdout.strip()
            if process == value['command']:
                raise ValueError('reset_requires_stopped_board')
    clients = db.execute("SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                         "AND pid<>pg_backend_pid()").fetchall()
    if clients:
        raise ValueError('reset_requires_no_database_clients')


def apply(db, expected, root=ROOT):
    require_stopped(db)
    # Hold the same acquisition lock without changing its retained identity.
    lock = root / '.local/predict-native-owner.lock'
    with lock.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        actual = plan(db, root)
        if actual != expected:
            raise ValueError('reset_plan_changed')
        with db.transaction():
            db.execute('SELECT pg_advisory_xact_lock(901091)')
            # No CASCADE: an unexpected dependency stops reset instead of
            # broadening the sports allowlist into protected records.
            if actual['tables']:
                db.execute(sql.SQL('TRUNCATE {}').format(sql.SQL(',').join(
                    sql.Identifier(t) for t in actual['tables'])))
        for name, before in actual['files'].items():
            path = root / name
            if fingerprint(path) != before:
                raise ValueError('sports_file_changed_during_reset')
            path.unlink()
        after_files, after_sql = protected_files(root), protected_sql(db)
        if after_files != actual['protected_files'] or after_sql != actual['protected_sql']:
            raise ValueError('protected_state_changed_during_reset')
        from app.collection.current_policy import candidate
        if candidate()[0] != actual['source_digest']:
            raise ValueError('source_changed_during_reset')
        return dict(version='predict-sports-reset-receipt-1',
                    deleted_tables=actual['tables'], deleted_files=actual['files'],
                    protected_files=after_files, protected_sql=after_sql,
                    protected_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    with connect() as db:
        if args.apply:
            if args.receipt is None:
                parser.error('--receipt is required with --apply')
            receipt = apply(db, json.loads(args.plan.read_text()))
            args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
            print('Sports reset complete; protected state unchanged.')
        else:
            args.plan.write_text(json.dumps(plan(db), indent=2) + '\n')
            print('Explicit sports reset plan written. No data changed.')


if __name__ == '__main__':
    main()
