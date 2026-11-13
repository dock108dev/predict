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
from time import monotonic

LOCK = 120046
PRESSURE_BYTES = SQL_BYTE_CAP * 3 // 5
REWRITE_RUNWAY_BYTES = 64 * 1024 * 1024
# Maintenance owns one transactional replacement, never collection capacity.
# The original remains recoverable until VACUUM commits. Host free-space and
# timeout guards apply independently; writers still enforce SQL_BYTE_CAP.
TRANSIENT_REWRITE_BYTES = 512 * 1024 * 1024
# Rewrites preserve every live row, including immutable Original packets.
# Account and journal tables are outside this maintenance owner.
COMPACT_TABLES = ('current_native_market_recovery', 'current_native_market_body', 'current_acquisition_image_parts',
    'current_native_ladder', 'native_ladder_revision', 'native_book_revision',
    'current_contract_storage', 'current_offer_storage', 'current_acquisition_market',
    'acquisition_receipt', 'sgo_event_evidence', 'latest_board', 'latest_dashboard', 'current_grid_projection',
    'current_result_unit', 'current_native_book', 'current_native_catalog_recovery',
    'comparison_snapshot', 'comparison_snapshot_result', 'comparison_publication', 'data_runtime', 'current_grid_blob')
MIN_REUSABLE_BYTES = 4 * 1024 * 1024
HOT_TABLES = ('current_acquisition_image_parts','current_acquisition_market',
              'native_ladder_revision','native_book_revision','current_offer_storage',
              'comparison_snapshot_result','comparison_snapshot')
CAPTURE_WAIT_SECONDS = 10
LIVE_REWRITE_LOCK_TIMEOUT = '100ms'
REWRITE_TURN_SECONDS = 5
# A completed copy measures irreducible page/TOAST slack. Do not keep copying
# that same slack: require another bounded unit of growth/reusable space first.
# This is process-local advice only; a changed relfilenode invalidates it.
_rewrite_floor = {}
_last_collecting_candidate = {}
REWRITE_FLOORS = 128


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
        if db.execute("SELECT to_regclass('public.comparison_result_reference') r").fetchone()['r']:
            from .comparison_snapshot import prune as prune_snapshots
            prune_snapshots(db)
        with db.transaction():
            if db.execute("SELECT to_regclass('current_grid_read_lease') r").fetchone()['r']:
                from .grid_packet_store import cleanup
                cleanup(db)
            if db.execute("SELECT to_regclass('pipeline_generation') r").fetchone()['r']:
                from .pipeline_generation import prune
                prune(db)
            if db.execute("SELECT to_regclass('current_result_unit') r").fetchone()['r']:
                from .result_publication import prune as prune_units
                prune_units(db)
            if db.execute("SELECT to_regclass('current_result_work') r").fetchone()['r']:
                from .result_inventory import prune as prune_inventory
                prune_inventory(db)
        # Source evidence shares the current-row writer lock. Do not let a busy
        # writer roll back or delay unrelated retention work above.
        with db.transaction():
            reference = db.execute("SELECT to_regclass('public.current_sgo_reference') r").fetchone()['r']
            frames = db.execute("SELECT to_regclass('public.sgo_event_evidence') r").fetchone()['r']
            history = db.execute("SELECT to_regclass('public.current_sgo_history') r").fetchone()['r']
            native = db.execute("SELECT to_regclass('public.native_book_revision') r").fetchone()['r']
            if reference or frames or history or native:
                from .current_rows import LOCK as CURRENT_ROWS_LOCK
                if not db.execute('SELECT pg_try_advisory_xact_lock(%s) held', (CURRENT_ROWS_LOCK,)).fetchone()['held']:
                    if reference or frames or history:
                        result['deferred'].append(dict(table='sportsgameodds_reference', reason='lock_busy'))
                    if native:
                        result['deferred'].append(dict(table='native_book_revision', reason='lock_busy'))
                else:
                    from .store import now
                    if reference:
                        from .sportsgameodds_reference import prune as prune_sgo
                        versioned = db.execute("SELECT to_regclass('public.sgo_quote_revision') IS NOT NULL ready").fetchone()['ready']
                        if versioned:
                            result['sgo_reference_expired'] = prune_sgo(db, at=now())
                        else:
                            # First startup runs maintenance before forward
                            # migrations. Leave these quotes for the new owner.
                            result['deferred'].append(dict(table='sportsgameodds_reference', reason='migration_pending'))
                    if frames:
                        from .sportsgameodds_reference import prune_frames
                        result['sgo_frame_expired'] = prune_frames(db, at=now())
                    if history:
                        from .sportsgameodds_reference import prune_history
                        result['sgo_history_expired'] = prune_history(db, at=now())
                    if native:
                        from .native_ladder_batch import prune as prune_native_revisions
                        def execute_native(query, params, *, synchronous=False):
                            return db.execute(query, params)
                        result['native_book_expired'] = prune_native_revisions(execute_native)
        if collecting and result['before_bytes'] >= PRESSURE_BYTES:
            # Full-scope native replacement can consume the remaining runway
            # before the server's default minute autovacuum wake-up. Recycle
            # dead working pages in place; no live evidence is deleted and no
            # temporary relation copy competes with ongoing acquisition.
            for table in HOT_TABLES:
                try:
                    db.execute(sql.SQL('VACUUM (TRUNCATE FALSE) {}').format(sql.Identifier(table)))
                except LockNotAvailable:
                    result['deferred'].append(dict(table=table, reason='reuse_lock_timeout'))
        # Read-only bloat scans do not consume rewrite runway or change MVCC
        # visibility. Reserve the publication lock only for an eligible FULL
        # rewrite; no-op scans must not withhold already-admitted games.
        result['capture_lock_acquired']=False
        if compact and sql_usage(db) >= PRESSURE_BYTES:
            rewrite_started=monotonic()
            ext = db.execute("SELECT n.nspname AS schema FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pgstattuple'").fetchone()
            if ext:
                candidates = db.execute('''SELECT c.oid,c.relname,c.relfilenode,c.reltoastrelid,n.nspname AS schema,COALESCE(parent.relname,c.relname) owner,pg_total_relation_size(c.oid) bytes,
                    COALESCE(f.members,1) partition_count
                    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    LEFT JOIN pg_inherits own ON own.inhrelid=c.oid
                    LEFT JOIN pg_class parent ON parent.oid=own.inhparent
                    LEFT JOIN (SELECT inhparent,count(*) members FROM pg_inherits GROUP BY inhparent) f ON f.inhparent=own.inhparent
                    WHERE c.relnamespace=ANY(current_schemas(false)::regnamespace[]) AND c.relkind='r'
                    AND (c.relname=ANY(%s) OR EXISTS(SELECT 1 FROM pg_inherits i JOIN pg_class p ON p.oid=i.inhparent
                      WHERE i.inhrelid=c.oid AND p.relnamespace=c.relnamespace AND p.relname=ANY(%s)))
                    ORDER BY pg_total_relation_size(c.oid)''', (list(COMPACT_TABLES),list(COMPACT_TABLES))).fetchall()
                if collecting and candidates:
                    last=_last_collecting_candidate.get(db.info.dbname)
                    index=next((i+1 for i,r in enumerate(candidates) if r['oid']==last),0)
                    candidates=candidates[index:]+candidates[:index]
                for index,row in enumerate(candidates):
                    if collecting:
                        if index and monotonic()-rewrite_started>=REWRITE_TURN_SECONDS:
                            result['continue_compaction']=True
                            break
                        _last_collecting_candidate[db.info.dbname]=row['oid']
                        if len(_last_collecting_candidate)>8:
                            _last_collecting_candidate.pop(next(iter(_last_collecting_candidate)))
                    if sql_usage(db) < PRESSURE_BYTES:break
                    free = 0
                    heap_bytes = 0
                    for oid in (row['oid'],row['reltoastrelid']):
                        if oid:
                            facts = db.execute(sql.SQL('SELECT * FROM {}.pgstattuple(%s::regclass)').format(sql.Identifier(ext['schema'])), (str(oid),)).fetchone()
                            free += facts['free_space'] + facts['dead_tuple_len']
                            heap_bytes += facts['table_len']
                    # Splitting one owner must not multiply its unreclaimed-space
                    # budget by the number of children. Keep the same logical
                    # owner's minimum while bounding each physical copy.
                    reclaim_unit=max(1,MIN_REUSABLE_BYTES//row['partition_count'])
                    # Recovery changes in complete catalog bursts. Its cold partitions
                    # can each strand several MB below the hot-owner 25% bar.
                    # The installed image/contract/offer owners stranded tens of
                    # MB between 12.5% and 25% while their admissions waited.
                    divisor=12
                    if collecting and row['owner']!='current_native_market_recovery':
                        divisor=8 if row['owner'] in ('current_acquisition_image_parts','current_contract_storage','current_offer_storage') else 4
                    if free < reclaim_unit or free < heap_bytes // divisor:continue
                    floor_key=(db.info.dbname,row['oid'])
                    floor=_rewrite_floor.get(floor_key)
                    if (floor and floor['node']==row['relfilenode']
                            and row['bytes']-floor['bytes']<reclaim_unit
                            and free-floor['free']<reclaim_unit):
                        result.setdefault('unchanged_rewrite_floor',[]).append(row['relname'])
                        continue
                    # Old relation + replacement + indexes/WAL runway; host floor
                    # remains separate from the unchanged application SQL cap.
                    # Requiring the temporary copy to fit the operating cap
                    # deadlocks reclamation precisely when it is needed most.
                    # Bound the transient peak separately; this does not admit
                    # sports writes beyond the normal database guard.
                    if not capture_lock:
                        started=monotonic()
                        if collecting:
                            db.execute("SELECT set_config('lock_timeout',%s,false)",(str(CAPTURE_WAIT_SECONDS)+'s',))
                            try:
                                db.execute('SELECT pg_advisory_lock(901153)')
                                capture_lock=True
                            except LockNotAvailable:result['state']='busy'
                            finally:db.execute("SET lock_timeout='1s'")
                        else:
                            capture_lock=db.execute('SELECT pg_try_advisory_lock(901153) held').fetchone()['held']
                        result['capture_lock_acquired']=capture_lock
                        result['capture_lock_wait_seconds']=round(monotonic()-started,6)
                        if not capture_lock:break
                    # Scanning preceded lock ownership: refresh the physical
                    # size before applying the unchanged copy/runway guard.
                    row=dict(row,bytes=db.execute('SELECT pg_total_relation_size(%s::regclass) n',
                        (str(row['oid']),)).fetchone()['n'])
                    before_rewrite=sql_usage(db)
                    peak_bound=before_rewrite+row['bytes']+REWRITE_RUNWAY_BYTES
                    # While acquisition is live the independent heartbeat sees
                    # both copies. Reserve the extra rewrite allowance for idle
                    # maintenance and startup, before dispatch and the heartbeat.
                    allowance=0 if collecting else TRANSIENT_REWRITE_BYTES
                    if peak_bound >= SQL_BYTE_CAP+allowance:
                        result['deferred'].append(dict(table=row['relname'], reason='rewrite_headroom',reusable_bytes=free))
                        db.execute('SELECT pg_advisory_unlock(901153)')
                        capture_lock=False
                        continue
                    require_disk_space(ROOT/'.local/postgres', append_bytes=row['bytes']*3)
                    if collecting:
                        db.execute("SELECT set_config('lock_timeout',%s,false)", (LIVE_REWRITE_LOCK_TIMEOUT,))
                    try:
                        db.execute(sql.SQL('VACUUM (FULL, ANALYZE) {}').format(sql.Identifier(row['schema'],row['relname'])))
                    except LockNotAvailable:
                        result['deferred'].append(dict(table=row['relname'], reason='lock_timeout'))
                        continue
                    finally:
                        # The physical replacement has committed (or failed).
                        # Subsequent size scans and recovery repacking must not
                        # continue withholding the next publication turn.
                        db.execute('SELECT pg_advisory_unlock(901153)')
                        capture_lock=False
                        if collecting:
                            db.execute("SET lock_timeout='1s'")
                    after = db.execute('SELECT pg_total_relation_size(%s::regclass) n', (str(row['oid']),)).fetchone()['n']
                    result['rewrites'].append(dict(table=row['relname'],before_bytes=row['bytes'],after_bytes=after,measured_reusable_bytes=free,
                        transient_peak_bound_bytes=peak_bound,operating_cap_bytes=SQL_BYTE_CAP,minimum_reclaim_bytes=reclaim_unit))
                    _rewrite_floor.pop(floor_key,None)
                    if row['bytes']-after<reclaim_unit:
                        current=db.execute('SELECT relfilenode,reltoastrelid FROM pg_class WHERE oid=%s',(row['oid'],)).fetchone()
                        remaining=0
                        for oid in (row['oid'],current['reltoastrelid']):
                            if oid:
                                facts=db.execute(sql.SQL('SELECT * FROM {}.pgstattuple(%s::regclass)').format(sql.Identifier(ext['schema'])),(str(oid),)).fetchone()
                                # Dead tuples can become reclaimable when an
                                # older reader finishes without any growth.
                                # Only already-empty page slack forms the floor.
                                remaining+=facts['free_space']
                        _rewrite_floor[floor_key]=dict(node=current['relfilenode'],bytes=after,free=remaining)
                        while len(_rewrite_floor)>REWRITE_FLOORS:_rewrite_floor.pop(next(iter(_rewrite_floor)))
                    if collecting and monotonic()-rewrite_started>=REWRITE_TURN_SECONDS:
                        # Yield between rewrites on a bounded time budget. A
                        # single small status-table rewrite must not monopolize
                        # every tick while larger reclaimable relations wait.
                        # Each individual SQL operation retains its timeout.
                        result['continue_compaction']=sql_usage(db)>=PRESSURE_BYTES
                        break
        if db.execute("SELECT to_regclass('public.current_native_market_recovery') r").fetchone()['r']:
            from .recovery_codec import repack
            result['recovery_repack']=repack(db)
        if db.execute("SELECT to_regclass('public.current_native_market_body') r").fetchone()['r']:
            from . import native_market_metadata
            result['native_metadata_backfill']=native_market_metadata.convert(db)
            result['native_metadata_pruned']=native_market_metadata.prune(db)
        result['after_bytes'] = sql_usage(db)
        return result
    finally:
        if capture_lock:db.execute('SELECT pg_advisory_unlock(901153)')
        for name,value in settings.items():db.execute('SELECT set_config(%s,%s,false)', (name,value))
        db.execute('SELECT pg_advisory_unlock(%s)', (LOCK,))
