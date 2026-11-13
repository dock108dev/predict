"""Read-only storage attribution, usable while the data runtime is stopped.

No migrations, extensions, cleanup, provider calls, or runtime controls. Tuple
statistics are estimates; physical relation sizes do not measure reclaimable
space. Optional pgstattuple scans require an already installed extension.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psycopg import sql
from app.collection.current_storage_policy import SQL_BYTE_CAP, writer_subset_usage
from app.storage.store import connect


RELATIONS = """SELECT c.oid,n.nspname AS schema,c.relname AS relation,
    pg_get_userbyid(c.relowner) AS owner,
    pg_relation_size(c.oid) AS heap_main_bytes,
    pg_table_size(c.oid) AS table_bytes_including_toast,
    pg_indexes_size(c.oid) AS index_bytes,
    pg_total_relation_size(c.oid) AS total_bytes,
    CASE WHEN c.reltoastrelid=0 THEN 0 ELSE pg_total_relation_size(c.reltoastrelid) END AS toast_bytes,
    CASE WHEN c.reltoastrelid=0 THEN 0 ELSE pg_relation_size(c.reltoastrelid) END AS toast_heap_bytes,
    CASE WHEN c.reltoastrelid=0 THEN 0 ELSE pg_indexes_size(c.reltoastrelid) END AS toast_index_bytes,
    c.reltoastrelid AS toast_oid,c.reltuples AS planner_rows_estimate,
    s.n_live_tup AS live_rows_estimate,s.n_dead_tup AS dead_rows_estimate,
    s.n_tup_ins,s.n_tup_upd,s.n_tup_del,s.n_tup_hot_upd,
    s.last_vacuum,s.last_autovacuum,s.last_analyze,s.last_autoanalyze,
    c.reloptions
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    LEFT JOIN pg_stat_all_tables s ON s.relid=c.oid
    WHERE c.relkind IN ('r','m') AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
    ORDER BY pg_total_relation_size(c.oid) DESC,c.oid"""


def snapshot(db, scan=()):
    # Bound each statement and avoid retaining a repeatable-read snapshot while
    # scanning: this observer must not itself prevent ordinary vacuum progress.
    db.execute("SET default_transaction_read_only=on")
    db.execute("SET statement_timeout='30s'")
    db.execute("SET lock_timeout='1s'")
    result = dict(started_at=datetime.now(timezone.utc).isoformat(),
        evidence_class='live_read_only_sql', sql_cap_bytes=SQL_BYTE_CAP,
        cautions=[
            'Relation size functions measure physical allocated bytes, not live payload bytes.',
            'TOAST is a subset of table bytes; do not add it to total bytes.',
            'Tuple counts and cumulative write counters are statistics, not exact counts.',
            'Dead tuples and free space are not a VACUUM FULL reclaim forecast.',
            'Independent statements are timestamped observations, not one MVCC census.',
        ])
    result['database'] = db.execute("""SELECT current_database() AS name,
        pg_database_size(current_database()) AS physical_bytes,
        pg_postmaster_start_time() AS postgres_started_at,
        (SELECT stats_reset FROM pg_stat_database WHERE datname=current_database()) AS stats_reset,
        clock_timestamp() AS measured_at""").fetchone()
    result['writer_subset_physical_bytes'] = writer_subset_usage(db)
    result['relations'] = db.execute(RELATIONS).fetchall()
    result['indexes'] = db.execute("""SELECT i.indrelid AS table_oid,
        t.relname AS table_name,c.relname AS index_name,pg_relation_size(c.oid) AS physical_bytes,
        i.indisvalid,i.indisready FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname='public' ORDER BY physical_bytes DESC""").fetchall()
    # Deliberately omit query text, connection strings and client addresses.
    result['transactions'] = db.execute("""SELECT pid,backend_type,state,xact_start,
        clock_timestamp()-xact_start AS transaction_age,backend_xmin,
        wait_event_type,wait_event,pg_blocking_pids(pid) AS blocked_by
        FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
        ORDER BY xact_start NULLS LAST""").fetchall()
    result['vacuum_progress'] = db.execute("""SELECT pid,relid,phase,heap_blks_total,
        heap_blks_scanned,heap_blks_vacuumed FROM pg_stat_progress_vacuum
        WHERE datname=current_database()""").fetchall()
    result['replication_slots'] = db.execute("""SELECT slot_type,active,xmin,catalog_xmin,
        restart_lsn FROM pg_replication_slots WHERE database=current_database()""").fetchall()
    result['prepared_transactions'] = db.execute("""SELECT transaction,prepared
        FROM pg_prepared_xacts WHERE database=current_database()""").fetchall()
    names = {r['relation'] for r in result['relations'] if r['schema']=='public'}
    retained = {r['relation'] for r in result['relations'] if r['schema']=='retained'}
    if {'current_grid_blob','current_grid_projection','current_grid_read_lease',
        'current_result_unit','current_result_parent_original'} <= retained:
        result['original_packets'] = db.execute("""SELECT count(*) AS packets,
            COALESCE(sum(retained_bytes),0) AS logical_packet_bytes,
            count(*) FILTER(WHERE unreferenced_at IS NULL) AS no_retirement_clock,
            count(*) FILTER(WHERE eligible) AS eligible_cleanup_packets,
            COALESCE(sum(retained_bytes) FILTER(WHERE eligible),0) AS eligible_cleanup_logical_bytes
            FROM (SELECT b.*,b.unreferenced_at<clock_timestamp()-interval '180 seconds'
                AND NOT EXISTS(SELECT 1 FROM retained.current_grid_projection g WHERE g.blob_id=b.id)
                AND NOT EXISTS(SELECT 1 FROM retained.current_result_unit u WHERE u.original_blob_id=b.id)
                AND NOT EXISTS(SELECT 1 FROM retained.current_result_parent_original p WHERE p.blob_id=b.id)
                AND NOT EXISTS(SELECT 1 FROM retained.current_grid_read_lease l WHERE l.packet_ids @> ARRAY[b.id])
                AS eligible FROM retained.current_grid_blob b) candidates""").fetchone()
    if 'pipeline_generation' in retained:
        result['generations'] = db.execute("""SELECT disposition,count(*) AS rows,
            min(admitted_at) AS oldest_admission,min(last_attempt) AS oldest_attempt,
            count(*) FILTER(WHERE disposition IN ('published','superseded')
                AND last_attempt<clock_timestamp()-interval '2 hours') AS age_cleanup_eligible
            FROM retained.pipeline_generation GROUP BY disposition ORDER BY disposition""").fetchall()
    if 'data_runtime' in names:
        result['runtime'] = db.execute("""SELECT runtime_id,heartbeat_at,global_stopped,
            paused_sources FROM data_runtime""").fetchall()
    result['tuple_scans'] = []
    if scan:
        extension = db.execute("""SELECT n.nspname AS schema FROM pg_extension e
            JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pgstattuple'""").fetchone()
        if extension is None:
            raise ValueError('pgstattuple_not_installed_no_extension_created')
        for name in scan:
            if name not in names:
                raise ValueError('scan_requires_existing_public_table')
            row = db.execute(sql.SQL('SELECT * FROM {}.pgstattuple(%s::regclass)').format(
                sql.Identifier(extension['schema'])), ('public.'+sql.Identifier(name).as_string(db),)).fetchone()
            relation = next(r for r in result['relations'] if r['schema']=='public' and r['relation']==name)
            toast = db.execute(sql.SQL('SELECT * FROM {}.pgstattuple(%s::regclass)').format(
                sql.Identifier(extension['schema'])), (str(relation['toast_oid']),)).fetchone() if relation['toast_oid'] else None
            result['tuple_scans'].append(dict(relation=name,measured_at=datetime.now(timezone.utc).isoformat(),facts=row,toast_facts=toast))
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--scan',action='append',default=[],help='Existing public table; full pgstattuple scan, at most 10 tables')
    args=parser.parse_args()
    if len(args.scan)>10:
        parser.error('at most 10 explicit table scans per report')
    try:
        with connect() as db:
            report=snapshot(db,args.scan)
    except Exception as exc:
        # Preserve a failed attempt, never confuse it with a zero-byte database.
        report=dict(at=datetime.now(timezone.utc).isoformat(),evidence_class='unavailable',
            error_type=type(exc).__name__,measured_database_bytes=None)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
        return 1
    args.output.write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(json.dumps(dict(output=str(args.output),database=report['database']),default=str))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
