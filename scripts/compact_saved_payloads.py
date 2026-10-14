#!/usr/bin/env python3
"""Inspect, archive and explicitly rewrite only lossless saved payload representations."""
import argparse
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from psycopg import sql
from app.storage.payload_codec import TABLES, decode, encode
from app.storage.store import connect, encoded, ROOT
from app.collection.current_storage_policy import require_disk_space, sql_usage

COLUMNS = {
    'current_game_snapshot': ('id', 'game_key', 'input_version', 'policy_version', 'as_of', 'payload_sha256'),
    'current_game_result': ('id', 'snapshot_id', 'payload_sha256', 'calculated_at'),
    'current_envelope': ('id', 'payload_sha256', 'source', 'kind', 'retained_at'),
}
DEFAULT_TABLES = ('current_game_snapshot', 'current_game_result')


def selected_tables(tables):
    tables=tuple(tables)
    if not tables or len(set(tables))!=len(tables) or any(table not in TABLES for table in tables):
        raise ValueError('payload_table_selection_invalid')
    return tables


def file_hash(path):
    digest = sha256()
    with Path(path).open('rb') as source:
        while body := source.read(1024 * 1024):
            digest.update(body)
    return digest.hexdigest()


def save_json(path, value):
    temporary=path.with_suffix(path.suffix+'.new')
    with temporary.open('x') as target:
        json.dump(value,target,sort_keys=True,indent=2)
        target.write('\n');target.flush();os.fsync(target.fileno())
    temporary.chmod(0o600)
    temporary.replace(path)


def public_row(row):
    return {k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in row.items()}


def rows(db, table):
    names = sql.SQL(',').join(map(sql.Identifier, COLUMNS[table]))
    with db.cursor(name='payload_' + uuid4().hex) as cursor:
        cursor.itersize = 1
        cursor.execute(sql.SQL('SELECT {},payload AS stored_payload FROM {} ORDER BY id').format(names, sql.Identifier(table)))
        yield from cursor


def summary(db, table, archive=None):
    digest = sha256()
    counts = dict(rows=0, logical_bytes=0, stored_text_bytes=0, planned_text_bytes=0, changed_rows=0)
    for row in rows(db, table):
        physical = row.pop('stored_payload')
        original = decode(physical)
        body = original.encode('utf-8')
        if sha256(body).hexdigest() != row['payload_sha256']:
            raise ValueError('original_payload_hash_mismatch:' + table + ':' + row['id'])
        planned = encode(original)
        if decode(planned).encode('utf-8') != body:
            raise ValueError('payload_round_trip_mismatch')
        digest.update(encoded(dict(public_row(row), logical_bytes=len(body))) + b'\n')
        if archive is not None:
            archive.write(encoded(dict(public_row(row), stored_payload=physical)) + b'\n')
        counts['rows'] += 1
        counts['logical_bytes'] += len(body)
        counts['stored_text_bytes'] += len(physical.encode('utf-8'))
        counts['planned_text_bytes'] += len(planned.encode('utf-8'))
        counts['changed_rows'] += planned != physical
    return dict(counts, logical_rows_sha256=digest.hexdigest())


def latest_fingerprint(db):
    values = db.execute('SELECT * FROM current_latest_result ORDER BY game_key,policy_version').fetchall()
    return sha256(encoded(values)).hexdigest()


def sizes(db,tables=DEFAULT_TABLES):
    return {table: db.execute('SELECT pg_total_relation_size(%s) AS n', (table,)).fetchone()['n'] for table in tables}


def verify_backup(path, expected=None):
    path = Path(path).resolve()
    actual = file_hash(path)
    if expected is not None and actual != expected:
        raise ValueError('backup_hash_changed')
    with path.open('rb') as source:
        if source.read(5) != b'PGDMP':
            raise ValueError('full_custom_backup_required')
    listing = subprocess.check_output(['pg_restore', '--list', str(path)], text=True, timeout=30)
    for table in ('current_envelope', 'current_source_projection', 'current_game_projection', *TABLES, 'current_latest_result', 'current_import_cursor'):
        if 'TABLE DATA public ' + table + ' ' not in listing:
            raise ValueError('backup_table_missing:' + table)
    return dict(path=str(path), sha256=actual, bytes=path.stat().st_size)


def require_stopped(database):
    if database != 'prediction_arb':
        return
    for folder in ('opportunity-board', 'opportunity-board-beta'):
        path = ROOT / '.local' / folder / 'process.json'
        if not path.exists():
            continue
        record = json.loads(path.read_text())
        command = subprocess.run(['/bin/ps', '-p', str(record['pid']), '-o', 'command='], capture_output=True, text=True).stdout.strip()
        birth = subprocess.run(['/bin/ps', '-p', str(record['pid']), '-o', 'lstart='], capture_output=True, text=True).stdout.strip()
        if command == record['command'] and birth == record.get('started'):
            raise ValueError('supported_stop_required_before_payload_rewrite')


def inspect(database, output, backup=None,tables=DEFAULT_TABLES):
    selected=selected_tables(tables)
    output = Path(output).resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    archives = {}
    tables = {}
    with connect(database) as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        db.execute("SET LOCAL TIME ZONE 'UTC'")
        before_sizes = sizes(db,selected)
        before_usage = sql_usage(db)
        pointer_hash = latest_fingerprint(db)
        for table in selected:
            path = output / (table + '.jsonl.gz')
            with gzip.open(path, 'wb', compresslevel=6) as archive:
                tables[table] = summary(db, table, archive)
            with path.open('rb') as archive:os.fsync(archive.fileno())
            path.chmod(0o600)
            archives[table] = dict(path=str(path), sha256=file_hash(path), bytes=path.stat().st_size)
    report = dict(version='predict-saved-payload-representation-1', database=database, tables=tables,selected_tables=list(selected),
        original_archives=archives, latest_pointer_sha256=pointer_hash,
        before_table_bytes=before_sizes, before_sql_bytes=before_usage,
        backup=verify_backup(backup) if backup else None, applied=False)
    path = output / 'plan.json'
    save_json(path,report)
    return report


def apply(database, output, vacuum=False,tables=None):
    output = Path(output).resolve()
    plan = json.loads((output / 'plan.json').read_text())
    selected=selected_tables(plan.get('selected_tables',DEFAULT_TABLES))
    if tables is not None and selected_tables(tables)!=selected:
        raise ValueError('payload_table_selection_conflict')
    if set(plan['tables'])!=set(selected) or set(plan['original_archives'])!=set(selected):
        raise ValueError('payload_table_plan_conflict')
    if (output/'representation-verified.json').exists():
        raise ValueError('payload_rewrite_already_committed')
    if plan['database'] != database or plan.get('applied'):
        raise ValueError('payload_plan_identity_conflict')
    if not plan.get('backup'):
        raise ValueError('full_custom_backup_required')
    verify_backup(plan['backup']['path'], plan['backup']['sha256'])
    for archive in plan['original_archives'].values():
        if file_hash(archive['path']) != archive['sha256']:
            raise ValueError('original_payload_archive_changed')
    require_stopped(database)
    prospective = 2 * sum(t['planned_text_bytes'] for t in plan['tables'].values())
    require_disk_space(ROOT / '.local' / 'postgres', prospective)
    with connect(database) as db:
        with db.transaction():
            db.execute("SET LOCAL TIME ZONE 'UTC'")
            other = db.execute("SELECT count(*) AS n FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'").fetchone()['n']
            if other:
                raise ValueError('exclusive_stopped_database_required')
            db.execute('SELECT pg_advisory_xact_lock(901091)')
            for table in selected:
                db.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(sql.Identifier(table)))
            if latest_fingerprint(db) != plan['latest_pointer_sha256']:
                raise ValueError('latest_pointer_changed_since_inspection')
            for table in selected:
                before = summary(db, table)
                if before != plan['tables'][table]:
                    raise ValueError('logical_rows_changed_since_inspection:' + table)
                trigger = 'immutable_' + table
                enabled = db.execute('SELECT tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname=%s', (table, trigger)).fetchone()
                if not enabled or enabled['tgenabled'] != 'O':
                    raise ValueError('immutable_trigger_not_enabled:' + table)
                db.execute(sql.SQL('ALTER TABLE {} DISABLE TRIGGER {}').format(sql.Identifier(table), sql.Identifier(trigger)))
                for row in rows(db, table):
                    physical = row['stored_payload']
                    planned = encode(physical)
                    if physical == planned:
                        continue
                    updated = db.execute(sql.SQL('UPDATE {} SET payload=%s WHERE id=%s AND payload_sha256=%s AND payload=%s').format(sql.Identifier(table)),
                        (planned, row['id'], row['payload_sha256'], physical))
                    if updated.rowcount != 1:
                        raise ValueError('physical_payload_compare_and_swap_failed')
                db.execute(sql.SQL('ALTER TABLE {} ENABLE TRIGGER {}').format(sql.Identifier(table), sql.Identifier(trigger)))
                after = summary(db, table)
                if any(after[k] != before[k] for k in ('rows', 'logical_bytes', 'logical_rows_sha256')):
                    raise ValueError('logical_payload_verification_failed:' + table)
            if latest_fingerprint(db) != plan['latest_pointer_sha256']:
                raise ValueError('latest_pointer_changed_during_rewrite')
        save_json(output/'representation-verified.json',dict(version=plan['version'],database=database,
            representation_applied=True,logical_rows_verified=True,latest_pointer_sha256=plan['latest_pointer_sha256'],
            logical_table_rows={table:{k:plan['tables'][table][k] for k in ('rows','logical_bytes','logical_rows_sha256')} for table in selected},
            vacuum_complete=False))
        if vacuum:
            db.execute("SET statement_timeout='120s'")
            for table in selected:
                db.execute(sql.SQL('VACUUM (FULL, ANALYZE) {}').format(sql.Identifier(table)))
            db.execute("SET statement_timeout='30s'")
        with db.transaction():
            db.execute('SET TRANSACTION READ ONLY')
            after_sizes = sizes(db,selected)
            after_usage = sql_usage(db)
            triggers = db.execute('SELECT tgname,tgenabled FROM pg_trigger WHERE tgname=ANY(%s) ORDER BY tgname',
                (['immutable_'+table for table in selected],)).fetchall()
            if len(triggers)!=len(selected) or any(row['tgenabled']!='O' for row in triggers):
                raise ValueError('immutable_trigger_inventory_changed')
    result = dict(plan, applied=True, vacuumed=vacuum, after_table_bytes=after_sizes,
        after_sql_bytes=after_usage, immutable_triggers=triggers)
    path = output / 'applied.json'
    save_json(path,result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'apply'))
    parser.add_argument('--database', default='prediction_arb')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--vacuum', action='store_true')
    parser.add_argument('--tables',nargs='+',choices=TABLES)
    args = parser.parse_args()
    if args.action == 'inspect' and args.vacuum:
        parser.error('--vacuum requires apply')
    report = inspect(args.database, args.output, args.backup,args.tables or DEFAULT_TABLES) if args.action == 'inspect' else apply(args.database, args.output, args.vacuum,args.tables)
    print(json.dumps({k: v for k, v in report.items() if k not in ('original_archives', 'tables')}, indent=2))


if __name__ == '__main__':
    main()
