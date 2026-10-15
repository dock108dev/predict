"""Explicit guarded lossless migration; never runs from an ordinary app read.

Use a copied-data rehearsal first. Metadata/IDs/hash columns never change. Each
table transaction either restores its immutable trigger and commits completely,
or rolls back; rerunning skips exact versioned rows. No old database is restored.
"""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import argparse
import resource
import time
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from .store import Store,exact_time
from .payload_codec import payload_row,FRAME_PREFIX,DOMAIN_PREFIX,decode_for_connection
from .domain_history import encode

TABLES=('current_envelope','current_game_snapshot','current_game_result')


def backfill_source_receipts(db):
    """Only fill new metadata from exact original source receipts, atomically.

    One indexed envelope read serves every projection referencing that receipt;
    quote.times.received_at/book.raw.received_at remain separate from retention.
    Catalogs retain their original capture ordering through envelope retained_at.
    The partial index in 011 bounds grouping to transitional rows. Neither SQL
    timestamp rounding nor a current wall clock enters the new numeric order.
    """
    rows=0;envelopes=0
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(901091)')
        with db.cursor(name='source_receipt_backfill',row_factory=dict_row) as cursor:
            cursor.itersize=1
            cursor.execute('''SELECT DISTINCT envelope_id FROM current_source_projection
              WHERE received_order IS NULL ORDER BY envelope_id''')
            for pending in cursor:
                envelope_id=pending['envelope_id']
                envelope=db.execute('''SELECT CASE WHEN octet_length(payload)<=12582912 THEN payload ELSE NULL END AS payload,
                  payload_sha256,source,kind FROM current_envelope WHERE id=%s''',
                    (envelope_id,)).fetchone()
                if not envelope or not isinstance(envelope['payload'],str):raise ValueError('source_receipt_original_envelope_missing_or_over_capacity')
                raw=decode_for_connection(envelope['payload'],db)
                if sha256(raw.encode()).hexdigest()!=envelope['payload_sha256']:
                    raise ValueError('source_receipt_original_envelope_hash_mismatch')
                record=json.loads(raw)
                if (not isinstance(record,dict) or record.get('source')!=envelope['source']
                        or record.get('kind')!=envelope['kind'] or not isinstance(record.get('retained_at'),str)):
                    raise ValueError('source_receipt_original_envelope_invalid')
                expected={'aggregate_batch':'quote','catalog':'catalog','admitted_books':'book'}.get(record['kind'])
                if expected is None:raise ValueError('source_receipt_original_binding_conflict')
                with db.cursor(name='source_receipt_original_rows',row_factory=dict_row) as projections:
                    projections.itersize=1
                    projections.execute('''SELECT source,kind,native_id,
                      CASE WHEN octet_length(payload)<=8388608 THEN payload ELSE NULL END AS payload
                      FROM current_source_projection WHERE received_order IS NULL AND envelope_id=%s
                      ORDER BY source,kind,native_id''',(envelope_id,))
                    for projection in projections:
                        if projection['source']!=record['source'] or projection['kind']!=expected:
                            raise ValueError('source_receipt_original_binding_conflict')
                        if not isinstance(projection['payload'],str):raise ValueError('source_receipt_projection_byte_capacity')
                        value=json.loads(projection['payload'])
                        try:
                            receipt=(value['quote']['times']['received_at'] if expected=='quote' else
                                value['book']['raw']['received_at'] if expected=='book' else record['retained_at'])
                        except (KeyError,TypeError) as exc:
                            raise ValueError('source_receipt_original_clock_missing') from exc
                        if not isinstance(receipt,str):raise ValueError('source_receipt_original_clock_missing')
                        received=exact_time(receipt)
                        updated=db.execute('''UPDATE current_source_projection SET received_order=%s
                          WHERE source=%s AND kind=%s AND native_id=%s AND received_order IS NULL''',
                            (received,projection['source'],projection['kind'],projection['native_id']))
                        rows+=updated.rowcount
                envelopes+=1
        if db.execute('SELECT 1 FROM current_source_projection WHERE received_order IS NULL LIMIT 1').fetchone():
            raise ValueError('source_receipt_backfill_incomplete')
    return dict(rows=rows,envelopes=envelopes,original_columns_unchanged=True,
        receipt_clock='original quote.times.received_at / book.raw.received_at; catalogs original retained_at; exact fractional seconds')


def migrate(db,*,fail_after=None,report=lambda v:None):
    Store(db).migrate();receipts=backfill_source_receipts(db);out={};total=0
    report(dict(table='current_source_projection',source_receipt_backfill=receipts,committed=True))
    for table in TABLES:
        trigger='immutable_'+table
        rows=0;logical=0;before_bytes=0;after_bytes=0;start=time.monotonic()
        order='retained_at' if table=='current_envelope' else 'as_of' if table=='current_game_snapshot' else 'calculated_at'
        with db.transaction():
            db.execute('SELECT pg_advisory_xact_lock(901091)')
            enabled=db.execute('SELECT tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname=%s',(table,trigger)).fetchone()
            if not enabled or enabled['tgenabled']!='O':raise ValueError('immutable_trigger_not_enabled:'+table)
            db.execute(sql.SQL('ALTER TABLE {} DISABLE TRIGGER {}').format(sql.Identifier(table),sql.Identifier(trigger)))
            with db.cursor(name='domain_migrate_'+table,row_factory=dict_row) as cursor:
                cursor.itersize=1
                where=sql.SQL('left(payload,%s)<>%s');args=[len(FRAME_PREFIX),FRAME_PREFIX]
                if table=='current_envelope':
                    where+=sql.SQL(" AND (kind='catalog' OR left(payload,%s)<>%s)");args.extend([len(DOMAIN_PREFIX),DOMAIN_PREFIX])
                cursor.execute(sql.SQL('SELECT id,payload,payload_sha256,octet_length(payload) AS old_bytes FROM {} WHERE {} ORDER BY {},id').format(sql.Identifier(table),where,sql.Identifier(order)),args)
                for row in cursor:
                    raw=decode_for_connection(row['payload'],db);digest=sha256(raw.encode()).hexdigest()
                    if digest!=row['payload_sha256']:raise ValueError('original_logical_hash_mismatch:'+table)
                    packed=encode(raw,db,table)
                    db.execute(sql.SQL('UPDATE {} SET payload=%s WHERE id=%s AND payload_sha256=%s').format(sql.Identifier(table)),(packed,row['id'],digest))
                    # Independent reader verifies the persisted dependency and
                    # exact logical result before this transaction can commit.
                    saved=db.execute(sql.SQL('SELECT payload,payload_sha256 FROM {} WHERE id=%s').format(sql.Identifier(table)),(row['id'],)).fetchone()
                    if saved['payload']!=raw or saved['payload_sha256']!=digest:raise ValueError('migrated_logical_conflict:'+table)
                    rows+=1;total+=1;logical+=len(raw.encode());before_bytes+=row['old_bytes'];after_bytes+=len(packed.encode())
                    if fail_after is not None and total>=fail_after:raise RuntimeError('injected_domain_migration_interruption')
                    if rows%500==0:report(dict(table=table,rows=rows,seconds=time.monotonic()-start))
            db.execute(sql.SQL('ALTER TABLE {} ENABLE TRIGGER {}').format(sql.Identifier(table),sql.Identifier(trigger)))
        out[table]=dict(rows=rows,logical_bytes=logical,before_payload_bytes=before_bytes,after_payload_bytes=after_bytes,seconds=time.monotonic()-start)
        report(out[table]|dict(table=table,committed=True))
    return dict(tables=out,total_rows=total,source_receipt_backfill=receipts,max_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

def main():
    p=argparse.ArgumentParser();p.add_argument('--database',required=True);p.add_argument('--socket',required=True)
    p.add_argument('--report',required=True);p.add_argument('--fail-after',type=int);p.add_argument('--installed-binding')
    a=p.parse_args()
    if not a.database.startswith('prediction_arb'):raise ValueError('dedicated_project_database_only')
    if a.database=='prediction_arb':
        if not a.installed_binding:raise ValueError('installed_binding_required')
        binding=json.loads(Path(a.installed_binding).read_text())
        if not binding.get('copied_data_gates_passed') or not binding.get('owned_runtime_stopped'):raise ValueError('installed_migration_gates_unmet')
        root=Path(__file__).resolve().parents[2]
        actual={str(path.relative_to(root)) for path in (root/'app').rglob('*')
            if path.is_file() and '__pycache__' not in path.parts
            and path.suffix in {'.py','.sql','.json','.js','.html','.css'}}
        if actual!=set(binding['source_files']):raise ValueError('installed_source_file_set_changed')
        for name,expected in binding['source_files'].items():
            if sha256((Path(__file__).resolve().parents[2]/name).read_bytes()).hexdigest()!=expected:raise ValueError('installed_source_binding_changed:'+name)
    with psycopg.connect(host=a.socket,port=55432,user='prediction_arb',dbname=a.database,autocommit=True,row_factory=payload_row) as db:
        if a.database=='prediction_arb':
            others=db.execute("SELECT count(*) AS n FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'").fetchone()['n']
            if others:raise ValueError('exclusive_stopped_database_required')
        result=migrate(db,fail_after=a.fail_after,report=lambda v:print(json.dumps(v),flush=True))
    result.update(database=a.database,at=datetime.now(timezone.utc).isoformat(),original_logical_payloads_unchanged=True,derived_source_receipt_metadata=True)
    Path(a.report).write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':main()
