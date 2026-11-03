"""Independently committed retention and measured pressure reclamation.

Never owns acquisition controls, accounting, or publication acceptance. FULL
rewrites are single-table, transactional, bounded-lock operations. A failed
rewrite leaves the original intact. Ordinary vacuum reuses space; only a
successful rewrite is expected to lower the physical database guard quantity.
"""
from psycopg import sql
from psycopg.errors import LockNotAvailable
from psycopg.pq import TransactionStatus
from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage, require_disk_space
from .store import ROOT

LOCK = 120046
PRESSURE_BYTES = SQL_BYTE_CAP * 3 // 5
REWRITE_RUNWAY_BYTES = 64 * 1024 * 1024
# Maintenance owns one transactional replacement, never collection capacity.
# The original remains recoverable until VACUUM commits. Host free-space and
# timeout guards apply independently; writers still enforce SQL_BYTE_CAP.
TRANSIENT_REWRITE_BYTES = 512 * 1024 * 1024
# Rewrites preserve every live row, including immutable Original packets.
# Account and journal tables are outside this maintenance owner.
COMPACT_TABLES = ('current_native_market_recovery', 'current_acquisition_image',
    'current_native_depth', 'current_contract', 'current_offer', 'current_acquisition_market',
    'current_acquisition_page', 'latest_board', 'latest_dashboard', 'current_grid_projection',
    'current_result_unit', 'current_native_book', 'current_native_catalog_recovery',
    'comparison_snapshot', 'comparison_snapshot_result', 'data_runtime', 'current_grid_blob')
MIN_REUSABLE_BYTES = 4 * 1024 * 1024


def maintain(db, *, compact=True, collecting=False):
    if db.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError('storage_maintenance_requires_independent_transaction')
    if not db.execute('SELECT pg_try_advisory_lock(%s) held', (LOCK,)).fetchone()['held']:
        return dict(state='busy')
    result = dict(before_bytes=sql_usage(db), rewrites=[], deferred=[])
    settings = {name: db.execute(sql.SQL('SHOW {}').format(sql.Identifier(name))).fetchone()[name]
                for name in ('lock_timeout', 'statement_timeout')}
    capture_lock=False
    try:
        db.execute("SET lock_timeout='1s'")
        db.execute("SET statement_timeout='60s'")
        if db.execute("SELECT to_regclass('public.comparison_snapshot_review') r").fetchone()['r']:
            from .comparison_snapshot import prune as prune_snapshots
            prune_snapshots(db)
        with db.transaction():
            if db.execute("SELECT to_regclass('public.current_grid_read_lease') r").fetchone()['r']:
                from .grid_packet_store import cleanup
                cleanup(db)
            if db.execute("SELECT to_regclass('public.pipeline_generation') r").fetchone()['r']:
                from .pipeline_generation import prune
                prune(db)
            if db.execute("SELECT to_regclass('public.current_result_unit') r").fetchone()['r']:
                from .result_publication import prune as prune_units
                prune_units(db)
            if db.execute("SELECT to_regclass('public.current_result_work') r").fetchone()['r']:
                from .result_inventory import prune as prune_inventory
                prune_inventory(db)
        # Retention is committed even if reclamation fails or publication rejects.
        # A capture and a FULL rewrite must not spend the same runway.
        capture_lock = compact and sql_usage(db) >= PRESSURE_BYTES and db.execute(
            'SELECT pg_try_advisory_lock(901153) held').fetchone()['held']
        if capture_lock:
            ext = db.execute("SELECT n.nspname AS schema FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pgstattuple'").fetchone()
            if ext:
                candidates = db.execute('''SELECT oid,relname,reltoastrelid,pg_total_relation_size(oid) bytes
                    FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)
                    ORDER BY pg_total_relation_size(oid)''', (list(COMPACT_TABLES),)).fetchall()
                for row in candidates:
                    if sql_usage(db) < PRESSURE_BYTES:break
                    free = 0
                    heap_bytes = 0
                    for oid in (row['oid'],row['reltoastrelid']):
                        if oid:
                            facts = db.execute(sql.SQL('SELECT * FROM {}.pgstattuple(%s::regclass)').format(sql.Identifier(ext['schema'])), (str(oid),)).fetchone()
                            free += facts['free_space'] + facts['dead_tuple_len']
                            heap_bytes += facts['table_len']
                    if free < MIN_REUSABLE_BYTES or free < heap_bytes // (4 if collecting else 12):continue
                    # Old relation + replacement + indexes/WAL runway; host floor
                    # remains separate from the unchanged application SQL cap.
                    # Requiring the temporary copy to fit the operating cap
                    # deadlocks reclamation precisely when it is needed most.
                    # Bound the transient peak separately; this does not admit
                    # sports writes beyond the normal database guard.
                    before_rewrite=sql_usage(db)
                    peak_bound=before_rewrite+row['bytes']+REWRITE_RUNWAY_BYTES
                    # While acquisition is live the independent heartbeat sees
                    # both copies. Reserve the extra rewrite allowance for idle
                    # maintenance and startup, before dispatch and the heartbeat.
                    allowance=0 if collecting else TRANSIENT_REWRITE_BYTES
                    if peak_bound >= SQL_BYTE_CAP+allowance:
                        result['deferred'].append(dict(table=row['relname'], reason='rewrite_headroom',reusable_bytes=free))
                        continue
                    require_disk_space(ROOT/'.local/postgres', append_bytes=row['bytes']*3)
                    try:
                        db.execute(sql.SQL('VACUUM (FULL, ANALYZE) {}').format(sql.Identifier('public',row['relname'])))
                    except LockNotAvailable:
                        result['deferred'].append(dict(table=row['relname'], reason='lock_timeout'))
                        continue
                    after = db.execute('SELECT pg_total_relation_size(%s::regclass) n', (str(row['oid']),)).fetchone()['n']
                    result['rewrites'].append(dict(table=row['relname'],before_bytes=row['bytes'],after_bytes=after,measured_reusable_bytes=free,
                        transient_peak_bound_bytes=peak_bound,operating_cap_bytes=SQL_BYTE_CAP))
        result['after_bytes'] = sql_usage(db)
        return result
    finally:
        if capture_lock:db.execute('SELECT pg_advisory_unlock(901153)')
        for name,value in settings.items():db.execute('SELECT set_config(%s,%s,false)', (name,value))
        db.execute('SELECT pg_advisory_unlock(%s)', (LOCK,))
